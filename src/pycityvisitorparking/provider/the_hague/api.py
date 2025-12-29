"""The Hague provider implementation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import aiohttp

from ...exceptions import AuthError, ProviderError, ValidationError
from ...models import Favorite, Permit, Reservation, ZoneValidityBlock
from ..base import BaseProvider
from ..loader import ProviderManifest
from .const import (
    ACCOUNT_ENDPOINT,
    DEFAULT_HEADERS,
    FAVORITE_ENDPOINT,
    PERMIT_MEDIA_TYPE_HEADER,
    RESERVATION_ENDPOINT,
    SESSION_ENDPOINT,
)


class Provider(BaseProvider):
    """Provider for The Hague visitor parking."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        manifest: ProviderManifest,
        *,
        base_url: str | None = None,
        api_uri: str | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
        retry_count: int = 0,
    ) -> None:
        """Initialize the provider."""
        super().__init__(
            session,
            manifest,
            base_url=base_url,
            api_uri=api_uri,
            timeout=timeout,
            retry_count=retry_count,
        )
        self._credentials: dict[str, str] | None = None
        self._permit_media_type_id: str | None = None
        self._logged_in = False

    async def login(self, credentials: Mapping[str, str] | None = None, **kwargs: str) -> None:
        """Authenticate against the provider."""
        merged = self._merge_credentials(credentials, **kwargs)
        username = merged.get("username")
        password = merged.get("password")
        permit_media_type_id = merged.get("permit_media_type_id") or merged.get("permitMediaTypeId")
        if not username:
            raise ValidationError("username is required.")
        if not password:
            raise ValidationError("password is required.")
        if permit_media_type_id is None:
            permit_media_type_id = self._permit_media_type_id
        permit_media_type_id = self._normalize_permit_media_type_id(permit_media_type_id)

        auth = aiohttp.BasicAuth(username, password)
        await self._request_text(
            "GET",
            SESSION_ENDPOINT,
            auth=auth,
            allow_reauth=False,
        )
        self._credentials = {
            "username": username,
            "password": password,
        }
        if permit_media_type_id is not None:
            self._credentials["permit_media_type_id"] = permit_media_type_id
        self._permit_media_type_id = permit_media_type_id
        self._logged_in = True

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        account = await self._request_json("GET", ACCOUNT_ENDPOINT, allow_reauth=True)
        return self._map_permit(account)

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        data = await self._request_json("GET", RESERVATION_ENDPOINT, allow_reauth=True)
        return self._map_reservation_list(data)

    async def start_reservation(
        self,
        license_plate: str,
        start_time: str,
        end_time: str,
        name: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate."""
        start_time, end_time = self._validate_reservation_times(
            start_time,
            end_time,
            require_both=True,
        )
        normalized_plate = self._normalize_license_plate(license_plate)
        name_value = name or normalized_plate
        # The API requires a name; default to the normalized plate when omitted.
        payload = {
            "id": None,
            "name": name_value,
            "license_plate": normalized_plate,
            "start_time": start_time,
            "end_time": end_time,
        }
        data = await self._request_json(
            "POST",
            RESERVATION_ENDPOINT,
            json=payload,
            allow_reauth=True,
        )
        return self._map_reservation(data)

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""
        if start_time is not None or name is not None:
            raise ValidationError("Only end_time can be updated.")
        if end_time is None:
            raise ValidationError("end_time is required.")
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        normalized_end_time = self._ensure_utc_timestamp(end_time)
        payload = {"end_time": normalized_end_time}
        data = await self._request_json(
            "PATCH",
            f"{RESERVATION_ENDPOINT}/{reservation_id_value}",
            json=payload,
            allow_reauth=True,
        )
        return self._map_reservation(data)

    async def end_reservation(self, reservation_id: str, end_time: str) -> Reservation:
        """End a reservation."""
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        normalized_end_time = self._ensure_utc_timestamp(end_time)
        existing = self._find_reservation(
            await self.list_reservations(),
            reservation_id_value,
        )
        if existing is None:
            raise ValidationError("reservation_id was not found.")
        await self._request_text(
            "DELETE",
            f"{RESERVATION_ENDPOINT}/{reservation_id_value}",
            allow_reauth=True,
        )
        return Reservation(
            id=existing.id,
            name=existing.name,
            license_plate=existing.license_plate,
            start_time=existing.start_time,
            end_time=normalized_end_time,
        )

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        data = await self._request_json("GET", FAVORITE_ENDPOINT, allow_reauth=True)
        return self._map_favorite_list(data)

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        normalized_plate = self._normalize_license_plate(license_plate)
        name_value = name or normalized_plate
        payload = {"name": name_value, "license_plate": normalized_plate}
        data = await self._request_json(
            "POST",
            FAVORITE_ENDPOINT,
            json=payload,
            allow_reauth=True,
        )
        return self._map_favorite(data)

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Native favorite update implementation."""
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        if license_plate is None and name is None:
            raise ValidationError("license_plate or name is required.")
        existing = None
        if license_plate is None or name is None:
            existing = self._find_favorite(await self.list_favorites(), favorite_id_value)
            if existing is None:
                raise ValidationError("favorite_id was not found.")
        plate_value = license_plate or (existing.license_plate if existing else None)
        if plate_value is None:
            raise ValidationError("license_plate is required.")
        normalized_plate = self._normalize_license_plate(plate_value)
        name_value = name or (existing.name if existing else None) or normalized_plate
        payload = {"name": name_value, "license_plate": normalized_plate}
        data = await self._request_json(
            "PATCH",
            f"{FAVORITE_ENDPOINT}/{favorite_id_value}",
            json=payload,
            allow_reauth=True,
        )
        return self._map_favorite(data)

    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        await self._request_text(
            "DELETE",
            f"{FAVORITE_ENDPOINT}/{favorite_id_value}",
            allow_reauth=True,
        )

    def _map_permit(self, account: Any) -> Permit:
        if not isinstance(account, dict):
            raise ProviderError("Provider response included invalid account data.")
        account_id = self._coerce_response_id(account.get("id"), "account id")
        remaining_balance = self._parse_int(account.get("debit_minutes"))
        zone_validity = self._map_zone_validity(account.get("zone_validity"))
        return Permit(
            id=account_id,
            remaining_balance=remaining_balance,
            zone_validity=zone_validity,
        )

    def _map_zone_validity(self, raw: Any) -> list[ZoneValidityBlock]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ProviderError("Provider response included invalid zone validity.")
        entries: list[tuple[ZoneValidityBlock, bool]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            start_raw = item.get("start_time")
            end_raw = item.get("end_time")
            if not start_raw or not end_raw:
                continue
            is_free = item.get("is_free") is True
            try:
                start = self._ensure_utc_timestamp(start_raw)
                end = self._ensure_utc_timestamp(end_raw)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid zone validity data.") from exc
            entries.append((ZoneValidityBlock(start_time=start, end_time=end), not is_free))
        # Only include chargeable windows (is_free is not true).
        return self._filter_chargeable_zone_validity(entries)

    def _map_reservation_list(self, data: Any) -> list[Reservation]:
        if data is None:
            return []
        if not isinstance(data, list):
            raise ProviderError("Provider response included invalid reservations.")
        reservations: list[Reservation] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            reservations.append(self._map_reservation(item))
        return reservations

    def _map_reservation(self, data: Any) -> Reservation:
        if not isinstance(data, dict):
            raise ProviderError("Provider response included invalid reservation data.")
        reservation_id = self._coerce_response_id(data.get("id"), "reservation id")
        license_plate = data.get("license_plate")
        name = data.get("name") or ""
        start_raw = data.get("start_time")
        end_raw = data.get("end_time")
        if license_plate is None or start_raw is None or end_raw is None:
            raise ProviderError("Provider response missing reservation fields.")
        if not isinstance(license_plate, str):
            raise ProviderError("Provider response included invalid reservation data.")
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            raise ProviderError("Provider response included invalid reservation data.")
        if name is not None and not isinstance(name, str):
            name = str(name)
        try:
            normalized_plate = self._normalize_license_plate(license_plate)
            start = self._ensure_utc_timestamp(start_raw)
            end = self._ensure_utc_timestamp(end_raw)
        except ValidationError as exc:
            raise ProviderError("Provider returned invalid reservation data.") from exc
        return Reservation(
            id=reservation_id,
            name=name or "",
            license_plate=normalized_plate,
            start_time=start,
            end_time=end,
        )

    def _map_favorite_list(self, data: Any) -> list[Favorite]:
        if data is None:
            return []
        if not isinstance(data, list):
            raise ProviderError("Provider response included invalid favorites.")
        favorites: list[Favorite] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            favorites.append(self._map_favorite(item))
        return favorites

    def _map_favorite(self, data: Any) -> Favorite:
        if not isinstance(data, dict):
            raise ProviderError("Provider response included invalid favorite data.")
        favorite_id = self._coerce_response_id(data.get("id"), "favorite id")
        license_plate = data.get("license_plate")
        name = data.get("name") or ""
        if license_plate is None:
            raise ProviderError("Provider response missing favorite fields.")
        if not isinstance(license_plate, str):
            raise ProviderError("Provider response included invalid favorite data.")
        if name is not None and not isinstance(name, str):
            name = str(name)
        try:
            normalized_plate = self._normalize_license_plate(license_plate)
        except ValidationError as exc:
            raise ProviderError("Provider returned invalid favorite data.") from exc
        return Favorite(
            id=favorite_id,
            name=name or "",
            license_plate=normalized_plate,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        if self._permit_media_type_id:
            headers[PERMIT_MEDIA_TYPE_HEADER] = self._permit_media_type_id
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        allow_reauth: bool,
    ) -> Any:
        if allow_reauth:
            await self._ensure_authenticated()
        return await self._request_with_reauth(
            method,
            path,
            expect_json=True,
            json=json,
            auth=None,
            allow_reauth=allow_reauth,
        )

    async def _request_text(
        self,
        method: str,
        path: str,
        *,
        allow_reauth: bool,
        auth: aiohttp.BasicAuth | None = None,
    ) -> str:
        if allow_reauth:
            await self._ensure_authenticated()
        return await self._request_with_reauth(
            method,
            path,
            expect_json=False,
            json=None,
            auth=auth,
            allow_reauth=allow_reauth,
        )

    async def _request_with_reauth(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool,
        json: Any | None,
        auth: aiohttp.BasicAuth | None,
        allow_reauth: bool,
    ) -> Any:
        url = self._build_url(path)
        headers = self._build_headers()
        request_kwargs: dict[str, Any] = {"headers": headers, "auth": auth}
        if json is not None:
            request_kwargs["json"] = json
        attempts = 2 if allow_reauth else 1
        for attempt in range(attempts):
            try:
                return await self._request(
                    method,
                    url,
                    expect_json=expect_json,
                    **request_kwargs,
                )
            except AuthError:
                if allow_reauth and attempt == 0:
                    await self._reauthenticate()
                    headers = self._build_headers()
                    request_kwargs["headers"] = headers
                    continue
                raise
        raise ProviderError("Request failed.")

    async def _ensure_authenticated(self) -> None:
        if self._logged_in:
            return
        if not self._credentials:
            raise AuthError("Authentication required.")
        await self.login(self._credentials)

    async def _reauthenticate(self) -> None:
        self._logged_in = False
        if not self._credentials:
            raise AuthError("Authentication required.")
        await self.login(self._credentials)

    def _normalize_permit_media_type_id(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValidationError("permit_media_type_id must be a string or integer.")
        normalized = str(value).strip()
        if not normalized:
            raise ValidationError("permit_media_type_id must be non-empty.")
        return normalized

    def _require_id(self, value: Any, field: str) -> str:
        if value is None:
            raise ValidationError(f"{field} is required.")
        text = str(value).strip()
        if not text:
            raise ValidationError(f"{field} is required.")
        return text

    def _coerce_response_id(self, value: Any, field: str) -> str:
        if value is None:
            raise ProviderError(f"Provider response missing {field}.")
        text = str(value).strip()
        if not text:
            raise ProviderError(f"Provider response missing {field}.")
        return text

    def _find_reservation(
        self,
        reservations: list[Reservation],
        reservation_id: str,
    ) -> Reservation | None:
        for reservation in reservations:
            if reservation.id == reservation_id:
                return reservation
        return None

    def _find_favorite(
        self,
        favorites: list[Favorite],
        favorite_id: str,
    ) -> Favorite | None:
        for favorite in favorites:
            if favorite.id == favorite_id:
                return favorite
        return None

    def _parse_int(self, value: Any) -> int:
        if value is None or isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return 0
            try:
                return int(stripped)
            except ValueError:
                return 0
        return 0
