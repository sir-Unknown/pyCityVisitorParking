"""The Hague provider implementation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import aiohttp

from ...const import RESOLVED_PERMIT_MEDIA_TYPE_ID
from ...exceptions import AuthError, ProviderError, ValidationError
from ...models import BALANCE_UNIT_MINUTE, Favorite, Permit, Reservation, ZoneValidityBlock
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

    @property
    def resolved_login_params(self) -> dict[str, str]:
        """Return provider-resolved login parameters from the last successful login."""
        result: dict[str, str] = {}
        if self._permit_media_type_id is not None:
            result[RESOLVED_PERMIT_MEDIA_TYPE_ID] = self._permit_media_type_id
        return result

    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """Authenticate against the provider."""
        self._plogger.operation_started("login")
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
        self._plogger.operation_completed("login")

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        self._plogger.operation_started("get_permit")
        account = await self._request_json("GET", ACCOUNT_ENDPOINT, allow_reauth=True)
        permit = self._map_permit(account)
        self._plogger.operation_completed("get_permit")
        return permit

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        self._plogger.operation_started("list_reservations")
        data = await self._request_json("GET", RESERVATION_ENDPOINT, allow_reauth=True)
        reservations = self._map_reservation_list(data)
        self._plogger.operation_completed("list_reservations", count=len(reservations))
        return reservations

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate."""
        self._plogger.operation_started("start_reservation")
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
        self._plogger.operation_completed("start_reservation")
        return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""
        self._plogger.operation_started("update_reservation")
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
        self._plogger.operation_completed("update_reservation")
        return reservation

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        """End a reservation."""
        self._plogger.operation_started("end_reservation")
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        end_dt = self._normalize_datetime(end_time)
        normalized_end_time = self._format_utc_timestamp(end_dt)
        existing = self._find_by_id(await self.list_reservations(), reservation_id_value)
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
        self._plogger.operation_completed("end_reservation")
        return reservation

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        self._plogger.operation_started("list_favorites")
        data = await self._request_json("GET", FAVORITE_ENDPOINT, allow_reauth=True)
        favorites = self._map_favorite_list(data)
        self._plogger.operation_completed("list_favorites", count=len(favorites))
        return favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        self._plogger.operation_started("add_favorite")
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
        self._plogger.operation_completed("add_favorite")
        return favorite

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Native favorite update implementation."""
        self._plogger.operation_started("update_favorite")
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        if license_plate is None and name is None:
            raise ValidationError("license_plate or name is required.")
        existing = None
        if license_plate is None or name is None:
            existing = self._find_by_id(await self.list_favorites(), favorite_id_value)
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
        self._plogger.operation_completed("update_favorite")
        return favorite

    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
        self._plogger.operation_started("remove_favorite")
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        await self._request_text(
            "DELETE",
            f"{FAVORITE_ENDPOINT}/{favorite_id_value}",
            allow_reauth=True,
        )
        self._plogger.operation_completed("remove_favorite")

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
            balance_unit=BALANCE_UNIT_MINUTE,
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
        **_kwargs: Any,
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
        **_kwargs: Any,
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

        async def perform_request() -> Any:
            return await self._request(
                method,
                url,
                expect_json=expect_json,
                **request_kwargs,
            )

        async def handle_reauth() -> None:
            await self._reauthenticate()
            request_kwargs["headers"] = self._build_headers()

        return await self._request_with_optional_reauth(
            allow_reauth=allow_reauth,
            request=perform_request,
            on_reauth=handle_reauth,
        )

    async def _request(self, method: str, url: str, *, expect_json: bool, **kwargs: Any) -> Any:
        async def handle_response(
            response: aiohttp.ClientResponse,
            _attempt: int,
            _attempts: int,
        ) -> Any:
            if response.status == 400:
                message = await self._error_message_from_response(response)
                if message:
                    raise ProviderError(message)
            self._plogger.response_status(response.status)
            self._raise_for_status(response)
            if expect_json:
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    self._plogger.invalid_json(await response.text())
                    raise ProviderError("Response did not contain valid JSON.") from exc
            return await response.text()

        return await self._request_with_retries(
            method,
            url,
            request_kwargs=kwargs,
            response_handler=handle_response,
        )

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
        self._plogger.reauthenticating()
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
        except aiohttp.ContentTypeError, ValueError:
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("description") or data.get("Description")
        if not isinstance(raw, str) or not raw.strip():
            return None
        return self._error_message_for_code(raw)
