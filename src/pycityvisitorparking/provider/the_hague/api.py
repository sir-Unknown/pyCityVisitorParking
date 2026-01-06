"""The Hague provider implementation."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import aiohttp

from ...exceptions import AuthError, NetworkError, ProviderError, ValidationError
from ...models import Favorite, Permit, Reservation, ZoneValidityBlock
from ..base import BaseProvider
from ..loader import ProviderManifest
from .const import (
    ACCOUNT_ENDPOINT,
    DEFAULT_API_URI,
    DEFAULT_HEADERS,
    FAVORITE_ENDPOINT,
    PERMIT_MEDIA_TYPE_HEADER,
    RESERVATION_ENDPOINT,
    SESSION_ENDPOINT,
)

_ERROR_CODE_RE = re.compile(r"^[a-z0-9_]+$")
_ERROR_MESSAGES = {
    "pv19": "License plate not found",
    "pv20": "You have an invalid permit type",
    "pv46": "You have no valid parking permit",
    "pv51": "Maximum reservations reached",
    "pv52": "Insufficient balance",
    "pv63": "This license plate is already reserved at this time",
    "pv71": "Upstream server not reachable",
    "pv72": "No parking in selected zone",
    "pv74": "Invalid start time",
    "pv75": "Invalid end time",
    "pv76": "No paid parking at this time",
    "pv77": "No valid session found",
    "pv97": "Incorrect license plate",
    "pv111": "Incorrect credentials supplied",
    "dit_kenteken_is_reeds_aangemeld": "License plate is already registered",
    "account_already_linked": "This account is already linked",
    "ilp": "Enter the license plate number without punctuation marks please",
    "npvs_offline": "The parking registry is not available at this time.",
}
_LOGGER = logging.getLogger(__name__)


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
        if api_uri is None:
            api_uri = DEFAULT_API_URI
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
        _LOGGER.debug("Provider %s login started", self.provider_id)
        merged = self._merge_credentials(credentials, **kwargs)
        username = merged.get("username")
        password = merged.get("password")
        permit_media_type_id = merged.get("permit_media_type_id")
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
        _LOGGER.debug("Provider %s login completed", self.provider_id)

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        _LOGGER.debug("Provider %s get_permit started", self.provider_id)
        account = await self._request_json("GET", ACCOUNT_ENDPOINT, allow_reauth=True)
        permit = self._map_permit(account)
        _LOGGER.debug("Provider %s get_permit completed", self.provider_id)
        return permit

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        _LOGGER.debug("Provider %s list_reservations started", self.provider_id)
        data = await self._request_json("GET", RESERVATION_ENDPOINT, allow_reauth=True)
        reservations = self._map_reservation_list(data)
        _LOGGER.debug(
            "Provider %s list_reservations completed count=%s",
            self.provider_id,
            len(reservations),
        )
        return reservations

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate."""
        _LOGGER.debug("Provider %s start_reservation started", self.provider_id)
        start_dt, end_dt = self._validate_reservation_times(
            start_time,
            end_time,
            require_both=True,
        )
        start_time_value = self._format_utc_timestamp(start_dt)
        end_time_value = self._format_utc_timestamp(end_dt)
        normalized_plate = self._normalize_license_plate(license_plate)
        name_value = name or normalized_plate
        # The API requires a name; default to the normalized plate when omitted.
        payload = {
            "id": None,
            "name": name_value,
            "license_plate": normalized_plate,
            "start_time": start_time_value,
            "end_time": end_time_value,
        }
        data = await self._request_json(
            "POST",
            RESERVATION_ENDPOINT,
            json=payload,
            allow_reauth=True,
        )
        reservation = self._map_reservation(data)
        _LOGGER.debug("Provider %s start_reservation completed", self.provider_id)
        return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""
        _LOGGER.debug("Provider %s update_reservation started", self.provider_id)
        if not self.reservation_update_possible:
            raise ProviderError("Reservation updates are not supported.")
        if start_time is not None or name is not None:
            raise ValidationError("Only end_time can be updated.")
        if end_time is None:
            raise ValidationError("end_time is required.")
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        end_dt = self._normalize_datetime(end_time)
        normalized_end_time = self._format_utc_timestamp(end_dt)
        payload = {"end_time": normalized_end_time}
        data = await self._request_json(
            "PATCH",
            f"{RESERVATION_ENDPOINT}/{reservation_id_value}",
            json=payload,
            allow_reauth=True,
        )
        reservation = self._map_reservation(data)
        _LOGGER.debug("Provider %s update_reservation completed", self.provider_id)
        return reservation

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        """End a reservation."""
        _LOGGER.debug("Provider %s end_reservation started", self.provider_id)
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        end_dt = self._normalize_datetime(end_time)
        normalized_end_time = self._format_utc_timestamp(end_dt)
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
        reservation = Reservation(
            id=existing.id,
            name=existing.name,
            license_plate=existing.license_plate,
            start_time=existing.start_time,
            end_time=normalized_end_time,
        )
        _LOGGER.debug("Provider %s end_reservation completed", self.provider_id)
        return reservation

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        _LOGGER.debug("Provider %s list_favorites started", self.provider_id)
        data = await self._request_json("GET", FAVORITE_ENDPOINT, allow_reauth=True)
        favorites = self._map_favorite_list(data)
        _LOGGER.debug(
            "Provider %s list_favorites completed count=%s",
            self.provider_id,
            len(favorites),
        )
        return favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        _LOGGER.debug("Provider %s add_favorite started", self.provider_id)
        normalized_plate = self._normalize_license_plate(license_plate)
        favorites = await self.list_favorites()
        for favorite in favorites:
            if favorite.license_plate == normalized_plate:
                raise ValidationError("license_plate is already a favorite.")
        name_value = name or normalized_plate
        payload = {"name": name_value, "license_plate": normalized_plate}
        data = await self._request_json(
            "POST",
            FAVORITE_ENDPOINT,
            json=payload,
            allow_reauth=True,
        )
        favorite = self._map_favorite(data)
        _LOGGER.debug("Provider %s add_favorite completed", self.provider_id)
        return favorite

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Native favorite update implementation."""
        _LOGGER.debug("Provider %s update_favorite started", self.provider_id)
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
        favorite = self._map_favorite(data)
        _LOGGER.debug("Provider %s update_favorite completed", self.provider_id)
        return favorite

    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
        _LOGGER.debug("Provider %s remove_favorite started", self.provider_id)
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        await self._request_text(
            "DELETE",
            f"{FAVORITE_ENDPOINT}/{favorite_id_value}",
            allow_reauth=True,
        )
        _LOGGER.debug("Provider %s remove_favorite completed", self.provider_id)

    def _map_permit(self, account: Any) -> Permit:
        if not isinstance(account, dict):
            raise ProviderError("Provider response included invalid account data.")
        account_id = self._coerce_response_id(account.get("id"), "account id")
        remaining_balance = self._parse_int(account.get("debit_minutes"))
        zone_validity = self._map_zone_validity(
            account.get("zone_validity"),
            fallback_zone=account.get("zone"),
        )
        return Permit(
            id=account_id,
            remaining_balance=remaining_balance,
            zone_validity=zone_validity,
        )

    def _map_zone_validity(
        self,
        raw: Any,
        *,
        fallback_zone: Any | None = None,
    ) -> list[ZoneValidityBlock]:
        if raw is None:
            raw_list: list[dict[str, Any]] = []
        elif not isinstance(raw, list):
            raise ProviderError("Provider response included invalid zone validity.")
        else:
            raw_list = [item for item in raw if isinstance(item, dict)]
        entries: list[tuple[ZoneValidityBlock, bool]] = []
        for item in raw_list:
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
        if not entries and isinstance(fallback_zone, dict):
            start_raw = fallback_zone.get("start_time")
            end_raw = fallback_zone.get("end_time")
            if isinstance(start_raw, str) and isinstance(end_raw, str):
                try:
                    start = self._ensure_utc_timestamp(start_raw)
                    end = self._ensure_utc_timestamp(end_raw)
                except ValidationError as exc:
                    raise ProviderError("Provider returned invalid zone data.") from exc
                _LOGGER.warning(
                    "Provider %s zone validity fallback used",
                    self.provider_id,
                )
                entries.append((ZoneValidityBlock(start_time=start, end_time=end), True))
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
                    _LOGGER.warning("Provider %s reauth triggered", self.provider_id)
                    await self._reauthenticate()
                    headers = self._build_headers()
                    request_kwargs["headers"] = headers
                    continue
                raise
        raise ProviderError("Request failed.")

    async def _request(self, method: str, url: str, *, expect_json: bool, **kwargs: Any) -> Any:
        retries = self._retry_count if method.upper() == "GET" else 0
        attempts = retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                timeout = kwargs.pop("timeout", self._timeout)
                if timeout is None:
                    timeout = self._timeout
                async with self._session.request(
                    method,
                    url,
                    timeout=timeout,
                    ssl=True,
                    **kwargs,
                ) as response:
                    if response.status == 400:
                        message = await self._error_message_from_response(response)
                        if message:
                            raise ProviderError(message)
                    self._raise_for_status(response)
                    if expect_json:
                        try:
                            return await response.json()
                        except (aiohttp.ContentTypeError, ValueError) as exc:
                            raise ProviderError("Response did not contain valid JSON.") from exc
                    return await response.text()
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    raise NetworkError("Network request failed.") from exc
        if last_error is not None:
            raise NetworkError("Network request failed.") from last_error
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

    def _normalize_error_code(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.startswith("pv"):
            suffix = normalized[2:]
            if suffix.isdigit():
                return f"pv{int(suffix)}"
        return normalized

    def _error_message_for_code(self, value: str) -> str | None:
        code = self._normalize_error_code(value)
        if not _ERROR_CODE_RE.match(code):
            return None
        message = _ERROR_MESSAGES.get(code)
        if message:
            return f"Provider error {code}: {message}"
        return f"Provider error {code}."

    async def _error_message_from_response(self, response: aiohttp.ClientResponse) -> str | None:
        try:
            data = await response.json()
        except (aiohttp.ContentTypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("description") or data.get("Description")
        if not isinstance(raw, str) or not raw.strip():
            return None
        return self._error_message_for_code(raw)
