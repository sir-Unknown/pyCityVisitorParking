"""DVS Portal provider implementation."""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from ...exceptions import AuthError, ProviderError, ValidationError
from ...models import BALANCE_UNIT_MINUTE, Favorite, Permit, Reservation, ZoneValidityBlock
from ...util import format_utc_timestamp, parse_timestamp
from ..base import BaseProvider
from ..loader import ProviderManifest
from ..logger import get_provider_logger
from .const import (
    API_TIMEZONE,
    AUTH_HEADER,
    AUTH_PREFIX,
    DEFAULT_API_URI,
    DEFAULT_HEADERS,
    FAVORITE_REMOVE_ENDPOINT,
    FAVORITE_UPSERT_ENDPOINT,
    LOGIN_ENDPOINT,
    LOGIN_GETBASE_ENDPOINT,
    LOGIN_METHOD_PAS,
    RESERVATION_CREATE_ENDPOINT,
    RESERVATION_END_ENDPOINT,
    RESERVATION_UPDATE_ENDPOINT,
    RETRY_AFTER_HEADER,
)

_LOGGER = get_provider_logger(__name__)


class Provider(BaseProvider):
    """Provider for DVS Portal."""

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
        self._token: str | None = None
        self._auth_header_value: str | None = None
        self._session_authenticated = False
        self._credentials: dict[str, str] | None = None
        self._permit_media_type_id: str | int | None = None
        self._permit_media_code: str | None = None
        self._api_timezone: ZoneInfo | None = None
        self._operation_lock = asyncio.Lock()
        self._lock_owner: asyncio.Task[Any] | None = None

    def _build_auth_header(self, token: str) -> str:
        """Return the Authorization header value for a raw provider token."""
        encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
        return f"{AUTH_PREFIX}{encoded}"

    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """Authenticate against the provider."""
        async with self._operation_guard():
            self._log_operation_started("login")
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
            if permit_media_type_id is None:
                permit_media_type_id = await self._fetch_permit_media_type_id(operation="login")
            self._validate_media_type_id(permit_media_type_id)

            payload = {
                "identifier": username,
                "loginMethod": LOGIN_METHOD_PAS,
                "password": password,
                "otp": None,
                "resetCode": None,
                "asIdentifier": None,
                "zipCode": None,
                "permitMediaTypeID": permit_media_type_id,
            }
            data = await self._request_json(
                "POST",
                LOGIN_ENDPOINT,
                json=payload,
                allow_reauth=False,
                operation="login",
            )

            status_value = data.get("LoginStatus")
            if isinstance(status_value, str) and status_value.isdigit():
                status_value = int(status_value)
            token = data.get("Token")
            error_message = data.get("ErrorMessage")
            requires_otp = data.get("RequiresOtp")
            if status_value == 2 or error_message:
                self._log_with_metadata(
                    logging.WARNING,
                    (
                        "Provider %s login failed: LoginStatus=%r token_present=%s "
                        "requires_otp=%r error_message=%r"
                    ),
                    self.provider_id,
                    status_value,
                    bool(token),
                    requires_otp,
                    error_message,
                )
                raise AuthError("Authentication failed.")

            self._token = str(token) if token else None
            self._auth_header_value = (
                self._build_auth_header(self._token) if self._token is not None else None
            )
            self._session_authenticated = True
            self._permit_media_type_id = permit_media_type_id
            self._credentials = {
                "username": username,
                "password": password,
                "permit_media_type_id": str(permit_media_type_id),
            }
            # Some DVS deployments authenticate via a session cookie and omit Token from
            # the login payload. In that case, perform a lightweight follow-up fetch to
            # verify the session and cache permit defaults for later requests.
            if token:
                permit = (
                    self._extract_permit(data) if self._response_includes_permit(data) else None
                )
                if permit is not None:
                    self._cache_defaults(permit)
            else:
                await self._fetch_base(operation="login")
            self._log_operation_completed(
                "login",
                login_status=status_value,
                token_present=bool(token),
                permit_media_type_id=permit_media_type_id,
            )

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        async with self._operation_guard():
            self._log_operation_started("get_permit")
            permit = await self._fetch_base(operation="get_permit")
            mapped = self._map_permit(permit)
            self._log_operation_completed("get_permit")
            return mapped

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        async with self._operation_guard():
            self._log_operation_started("list_reservations")
            reservations = self._reservations_from_permit(
                await self._fetch_base(operation="list_reservations")
            )
            self._log_operation_completed("list_reservations", count=len(reservations))
            return reservations

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate."""
        async with self._operation_guard():
            self._log_operation_started("start_reservation")
            start_time_utc, end_time_utc = self._validate_reservation_times(
                start_time,
                end_time,
                require_both=True,
            )
            start_time_utc_value = self._format_utc_timestamp(start_time_utc)
            end_time_utc_value = self._format_utc_timestamp(end_time_utc)
            normalized_plate = self._normalize_license_plate(license_plate)
            await self._ensure_defaults(operation="start_reservation")

            # DVS Portal expects local timestamps with offsets and milliseconds in requests.
            start_time_local = self._format_provider_timestamp(start_time_utc)
            end_time_local = self._format_provider_timestamp(end_time_utc)
            payload = {
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": self._permit_media_code,
                "DateFrom": start_time_local,
                "DateUntil": end_time_local,
                "LicensePlate": {
                    "Value": normalized_plate,
                    "Name": name,
                },
            }
            data = await self._request_json_auth(
                "POST",
                RESERVATION_CREATE_ENDPOINT,
                json=payload,
                operation="start_reservation",
            )
            permit = await self._permit_from_response(
                data,
                "reservation create",
                operation="start_reservation",
            )
            reservations = self._reservations_from_permit(permit)
            reservation = self._select_reservation(
                reservations,
                license_plate=normalized_plate,
                start_time=start_time_utc_value,
                end_time=end_time_utc_value,
            )
            if reservation is None:
                raise ProviderError("Reservation was not returned by the provider.")
            self._log_operation_completed("start_reservation")
            return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""
        async with self._operation_guard():
            self._log_operation_started("update_reservation")
            if not self.reservation_update_possible:
                raise ProviderError("Reservation updates are not supported.")
            if start_time is not None or name is not None:
                raise ValidationError("Only end_time can be updated.")
            if end_time is None:
                raise ValidationError("end_time is required.")
            reservation_id_value = self._coerce_id(reservation_id).strip()
            if not reservation_id_value:
                raise ValidationError("reservation_id is required.")

            end_dt = self._normalize_datetime(end_time)
            existing = self._select_reservation(
                self._reservations_from_permit(
                    await self._fetch_base(operation="update_reservation")
                ),
                reservation_id=reservation_id_value,
            )
            if existing is None:
                self._log_operation_failed("update_reservation", "reservation_id not found")
                raise ValidationError("reservation_id was not found.")
            if self._permit_media_type_id is None or self._permit_media_code is None:
                raise ProviderError("Permit media defaults are missing.")
            try:
                existing_start_dt = parse_timestamp(existing.start_time)
                existing_end_dt = parse_timestamp(existing.end_time)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid reservation data.") from exc

            self._validate_reservation_times(existing_start_dt, end_dt, require_both=True)
            # A negative delta shortens the reservation; the API accepts this.
            delta_seconds = int((end_dt - existing_end_dt).total_seconds())
            if delta_seconds % 60 != 0:
                # The API accepts minute deltas only.
                raise ValidationError("end_time must be aligned to whole minutes.")
            minutes_delta = delta_seconds // 60
            payload = {
                "Minutes": minutes_delta,
                "ReservationID": reservation_id_value,
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": self._permit_media_code,
            }
            data = await self._request_json_auth(
                "POST",
                RESERVATION_UPDATE_ENDPOINT,
                json=payload,
                operation="update_reservation",
            )
            permit = await self._permit_from_response(
                data,
                "reservation update",
                operation="update_reservation",
            )
            reservations = self._reservations_from_permit(permit)
            updated = self._select_reservation(
                reservations,
                reservation_id=reservation_id_value,
            )
            if updated is None:
                raise ProviderError("Reservation was not returned by the provider.")
            self._log_operation_completed("update_reservation")
            return updated

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        """End a reservation."""
        async with self._operation_guard():
            self._log_operation_started("end_reservation")
            end_dt = self._normalize_datetime(end_time)
            normalized_end_time = self._format_utc_timestamp(end_dt)
            await self._ensure_defaults(operation="end_reservation")
            existing = self._select_reservation(
                self._reservations_from_permit(await self._fetch_base(operation="end_reservation")),
                reservation_id=reservation_id,
            )
            if existing is None:
                self._log_operation_failed("end_reservation", "reservation_id not found")
                raise ValidationError("reservation_id was not found.")
            payload = {
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": self._permit_media_code,
                "ReservationID": reservation_id,
            }
            data = await self._request_json_auth(
                "POST",
                RESERVATION_END_ENDPOINT,
                json=payload,
                operation="end_reservation",
            )
            permit = await self._permit_from_response(
                data,
                "reservation end",
                operation="end_reservation",
            )
            self._cache_defaults(permit)
            reservation = Reservation(
                id=existing.id,
                name=existing.name,
                license_plate=existing.license_plate,
                start_time=existing.start_time,
                end_time=normalized_end_time,
            )
            self._log_operation_completed("end_reservation")
            return reservation

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        async with self._operation_guard():
            self._log_operation_started("list_favorites")
            favorites = self._favorites_from_permit(
                await self._fetch_base(operation="list_favorites")
            )
            self._log_operation_completed("list_favorites", count=len(favorites))
            return favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        async with self._operation_guard():
            self._log_operation_started("add_favorite")
            normalized_plate = self._normalize_license_plate(license_plate)
            favorites = self._favorites_from_permit(
                await self._fetch_base(operation="add_favorite")
            )
            for favorite in favorites:
                if favorite.license_plate == normalized_plate:
                    self._log_operation_failed("add_favorite", "duplicate license_plate")
                    raise ValidationError("license_plate is already a favorite.")
            # The list call also refreshes cached permit media defaults.
            if self._permit_media_type_id is None or self._permit_media_code is None:
                raise ProviderError("Permit media defaults are missing.")
            name_value = name or normalized_plate

            payload = {
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": self._permit_media_code,
                "licensePlate": {
                    "Value": normalized_plate,
                    "Name": name_value,
                },
                "updateLicensePlate": None,
                "name": name_value,
            }
            data = await self._request_json_auth(
                "POST",
                FAVORITE_UPSERT_ENDPOINT,
                json=payload,
                operation="add_favorite",
            )
            try:
                permit = self._extract_permit(data)
            except ProviderError:
                self._log_missing_response_data("favorite upsert", fallback="refetching list")
                favorites = self._favorites_from_permit(
                    await self._fetch_base(operation="add_favorite")
                )
            else:
                favorites = self._favorites_from_permit(permit)
            favorite = self._select_favorite(favorites, normalized_plate)
            if favorite is None:
                raise ProviderError("Favorite was not returned by the provider.")
            self._log_operation_completed("add_favorite")
            return favorite

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Native favorite update implementation."""
        raise ProviderError("Favorite updates are not supported.")

    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
        async with self._operation_guard():
            self._log_operation_started("remove_favorite")
            normalized_plate = self._normalize_license_plate(favorite_id)
            favorites = self._favorites_from_permit(
                await self._fetch_base(operation="remove_favorite")
            )
            # DVS removal expects the stored favorite name when available.
            found = next((f for f in favorites if f.license_plate == normalized_plate), None)
            name_value = (found and found.name) or normalized_plate
            if self._permit_media_type_id is None or self._permit_media_code is None:
                raise ProviderError("Permit media defaults are missing.")
            payload = {
                "permitMediaTypeID": self._permit_media_type_id,
                "permitMediaCode": self._permit_media_code,
                "licensePlate": normalized_plate,
                "name": name_value,
            }
            await self._request_json_auth(
                "POST",
                FAVORITE_REMOVE_ENDPOINT,
                json=payload,
                operation="remove_favorite",
            )
            self._log_operation_completed("remove_favorite")

    async def _fetch_permit_media_type_id(self, *, operation: str = "login") -> str | int:
        data = await self._request_json(
            "GET",
            LOGIN_ENDPOINT,
            allow_reauth=False,
            operation=operation,
        )
        types = data.get("PermitMediaTypes")
        if not isinstance(types, list) or not types:
            raise ProviderError("Provider did not return permit media types.")
        first = types[0]
        if not isinstance(first, dict) or "ID" not in first:
            raise ProviderError("Provider did not return a permit media type ID.")
        return first["ID"]

    async def _permit_from_response(
        self,
        data: dict[str, Any],
        label: str,
        *,
        operation: str = "fetch_base",
    ) -> dict[str, Any]:
        """Extract permit from a response, falling back to a full fetch on failure."""
        try:
            return self._extract_permit(data)
        except ProviderError:
            self._log_missing_response_data(label)
            return await self._fetch_base(operation=operation)

    def _reservations_from_permit(self, permit: dict[str, Any]) -> list[Reservation]:
        """Cache permit defaults and map active reservations."""
        self._cache_defaults(permit)
        return self._map_reservations(self._select_permit_media(permit))

    def _favorites_from_permit(self, permit: dict[str, Any]) -> list[Favorite]:
        """Cache permit defaults and map stored favorites."""
        self._cache_defaults(permit)
        return self._map_favorites(self._select_permit_media(permit))

    async def _fetch_base(self, *, operation: str = "fetch_base") -> dict[str, Any]:
        data = await self._request_json_auth(
            "POST",
            LOGIN_GETBASE_ENDPOINT,
            operation=operation,
        )
        permit = self._extract_permit(data)
        self._cache_defaults(permit)
        return permit

    async def _ensure_authenticated(self) -> None:
        if self._token is None and not self._session_authenticated:
            if not self._credentials:
                raise AuthError("Authentication required.")
            await self.login(self._credentials)

    async def _ensure_defaults(self, *, operation: str = "ensure_defaults") -> None:
        await self._ensure_authenticated()
        if self._permit_media_type_id is None or self._permit_media_code is None:
            await self._fetch_base(operation=operation)
        if self._permit_media_type_id is None or self._permit_media_code is None:
            raise ProviderError("Permit media defaults are missing.")

    def _extract_permit(self, data: dict[str, Any]) -> dict[str, Any]:
        permit = data.get("Permit")
        if not permit:
            permits = data.get("Permits")
            if isinstance(permits, list) and permits:
                permit = permits[0]
        if not isinstance(permit, dict):
            raise ProviderError("Provider response did not include permit data.")
        return permit

    def _response_includes_permit(self, data: dict[str, Any]) -> bool:
        """Return whether a provider response already includes permit details."""
        permit = data.get("Permit")
        if isinstance(permit, dict):
            return True
        permits = data.get("Permits")
        return isinstance(permits, list) and any(isinstance(item, dict) for item in permits)

    def _select_permit_media(self, permit: dict[str, Any]) -> dict[str, Any]:
        media_items = permit.get("PermitMedias")
        if not isinstance(media_items, list) or not media_items:
            raise ProviderError("Provider response did not include permit media.")
        media = media_items[0]
        if not isinstance(media, dict):
            raise ProviderError("Provider response included invalid permit media.")
        return media

    def _cache_defaults(self, permit: dict[str, Any]) -> None:
        media = self._select_permit_media(permit)
        type_id = media.get("TypeID")
        code = media.get("Code")
        if type_id is not None:
            self._validate_media_type_id(type_id)
            self._permit_media_type_id = type_id
        if isinstance(code, str) and code.strip():
            self._permit_media_code = code.strip()

    def _map_permit(self, permit: dict[str, Any]) -> Permit:
        media = self._select_permit_media(permit)
        permit_id = (
            self._coerce_id(media.get("Code"))
            or self._coerce_id(permit.get("ZoneCode"))
            or "permit"
        )
        remaining_balance = self._parse_int(media.get("Balance"))
        zone_validity = self._map_zone_validity(permit.get("BlockTimes"))
        return Permit(
            id=permit_id,
            remaining_balance=remaining_balance,
            zone_validity=zone_validity,
            balance_unit=BALANCE_UNIT_MINUTE,
        )

    def _map_zone_validity(self, block_times: Any) -> list[ZoneValidityBlock]:
        if block_times is None:
            return []
        if not isinstance(block_times, list):
            raise ProviderError("Provider response included invalid block times.")
        entries: list[tuple[ZoneValidityBlock, bool]] = []
        for block in block_times:
            if not isinstance(block, dict):
                continue
            is_free = block.get("IsFree") is True
            start_raw = block.get("ValidFrom")
            end_raw = block.get("ValidUntil")
            if not start_raw or not end_raw:
                continue
            try:
                start = self._parse_provider_timestamp(start_raw)
                end = self._parse_provider_timestamp(end_raw)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid block time data.") from exc
            entries.append((ZoneValidityBlock(start_time=start, end_time=end), not is_free))
        # Only include chargeable windows (IsFree is not true).
        return self._filter_chargeable_zone_validity(entries)

    def _map_reservations(self, permit_media: dict[str, Any]) -> list[Reservation]:
        raw = permit_media.get("ActiveReservations")
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ProviderError("Provider response included invalid reservations.")
        reservations: list[Reservation] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            reservation_id = item.get("ReservationID")
            start_raw = item.get("ValidFrom")
            end_raw = item.get("ValidUntil")
            plate_info = item.get("LicensePlate")
            if (
                reservation_id is None
                or not start_raw
                or not end_raw
                or not isinstance(plate_info, dict)
            ):
                continue
            plate_value = plate_info.get("Value") or plate_info.get("DisplayValue")
            if not plate_value:
                continue
            try:
                normalized_plate = self._normalize_license_plate(plate_value)
                start = self._parse_provider_timestamp(start_raw)
                end = self._parse_provider_timestamp(end_raw)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid reservation data.") from exc
            name = plate_info.get("DisplayValue") or plate_value
            reservations.append(
                Reservation(
                    id=self._coerce_id(reservation_id),
                    name=name,
                    license_plate=normalized_plate,
                    start_time=start,
                    end_time=end,
                )
            )
        return reservations

    def _map_favorites(self, permit_media: dict[str, Any]) -> list[Favorite]:
        raw = permit_media.get("LicensePlates")
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ProviderError("Provider response included invalid favorites.")
        favorites: list[Favorite] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            value = item.get("Value")
            if not value:
                continue
            try:
                normalized = self._normalize_license_plate(value)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid favorite data.") from exc
            favorites.append(
                Favorite(
                    id=normalized,
                    name=item.get("Name") or "",
                    license_plate=normalized,
                )
            )
        return favorites

    def _parse_provider_timestamp(self, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Provider timestamp must be a non-empty string.")
        raw = value.strip()
        if raw.endswith("Z"):
            return self._ensure_utc_timestamp(raw)
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValidationError("Provider timestamp is not a valid ISO 8601 value.") from exc
        if parsed.tzinfo is None:
            # DVS Portal returns local timestamps without offsets; assume Europe/Amsterdam.
            # fold=0 picks the pre-transition (standard time) occurrence when a local time
            # is ambiguous during a DST changeover, ensuring deterministic behaviour.
            parsed = parsed.replace(tzinfo=self._provider_timezone(), fold=0)
        return format_utc_timestamp(parsed)

    def _format_provider_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            raise ValidationError("Timestamp must include timezone information.")
        if value.tzinfo == UTC and value.microsecond == 0:
            normalized = value
        else:
            normalized = self._normalize_datetime(value)
        localized = normalized.astimezone(self._provider_timezone())
        return localized.isoformat(timespec="milliseconds")

    def _provider_timezone(self) -> ZoneInfo:
        try:
            if self._api_timezone is None:
                self._api_timezone = ZoneInfo(API_TIMEZONE)
            return self._api_timezone
        except ZoneInfoNotFoundError as exc:
            raise ProviderError(f"Timezone data for {API_TIMEZONE} is unavailable.") from exc

    def _select_reservation(
        self,
        reservations: list[Reservation],
        reservation_id: str | None = None,
        license_plate: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> Reservation | None:
        return next(
            (
                r
                for r in reservations
                if (reservation_id is None or r.id == reservation_id)
                and (license_plate is None or r.license_plate == license_plate)
                and (start_time is None or r.start_time == start_time)
                and (end_time is None or r.end_time == end_time)
            ),
            None,
        )

    def _select_favorite(self, favorites: list[Favorite], plate: str) -> Favorite | None:
        return next((f for f in favorites if f.license_plate == plate), None)

    def _validate_media_type_id(self, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValidationError("permit_media_type_id must be a string or integer.")
        if isinstance(value, str) and not value.strip():
            raise ValidationError("permit_media_type_id must be non-empty.")

    async def _request_json_auth(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        operation: str | None = None,
    ) -> Any:
        await self._ensure_authenticated()
        headers = {}
        if self._auth_header_value is not None:
            headers[AUTH_HEADER] = self._auth_header_value
        return await self._request_json(
            method,
            path,
            json=json,
            headers=headers,
            allow_reauth=True,
            operation=operation,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        allow_reauth: bool = False,
        operation: str | None = None,
    ) -> Any:
        url = self._build_url(path)
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        return await self._request(
            method,
            url,
            expect_json=True,
            json=json,
            headers=merged_headers,
            allow_reauth=allow_reauth,
            operation=operation,
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        expect_json: bool,
        json: Any = None,
        headers: dict[str, str] | None = None,
        allow_reauth: bool = False,
        operation: str | None = None,
    ) -> Any:
        request_headers = dict(headers or {})

        async def perform_request() -> Any:
            return await self._request_with_backoff(
                method,
                url,
                expect_json=expect_json,
                json=json,
                headers=request_headers,
                operation=operation,
            )

        async def handle_reauth() -> None:
            await self._reauthenticate()
            request_headers.clear()
            request_headers.update(DEFAULT_HEADERS)
            if self._auth_header_value is not None:
                request_headers[AUTH_HEADER] = self._auth_header_value

        return await self._request_with_optional_reauth(
            allow_reauth=allow_reauth,
            request=perform_request,
            on_reauth=handle_reauth,
        )

    async def _request_with_backoff(
        self,
        method: str,
        url: str,
        *,
        expect_json: bool,
        json: Any,
        headers: dict[str, str],
        operation: str | None,
    ) -> Any:
        async def handle_response(
            response: aiohttp.ClientResponse,
            attempt: int,
            attempts: int,
        ) -> Any:
            if response.status == 429:
                await self._handle_rate_limit(response, method, attempt, attempts)
                raise self._RetryRequest()
            self._log_response_status(response.status)
            if not 200 <= response.status < 300:
                body = await response.text()
                self._log_request_failure(
                    response.status,
                    method=method,
                    url=url,
                    operation=operation,
                    payload=json,
                    body=body,
                    content_type=response.headers.get("Content-Type"),
                )
                if response.status in (401, 403):
                    raise AuthError("Authentication failed.")
                raise ProviderError(f"Provider request failed with status {response.status}.")
            if expect_json:
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    self._log_invalid_json(await response.text())
                    raise ProviderError("Response did not contain valid JSON.") from exc
            return await response.text()

        return await self._request_with_retries(
            method,
            url,
            request_kwargs={"headers": headers, "json": json},
            response_handler=handle_response,
        )

    async def _handle_rate_limit(
        self,
        response: aiohttp.ClientResponse,
        method: str,
        attempt: int,
        attempts: int,
    ) -> None:
        try:
            delay = int(response.headers.get(RETRY_AFTER_HEADER, 0))
        except ValueError:
            delay = 0
        if delay > 0:
            # Respect server-provided cooldown before retrying.
            _LOGGER.debug(
                "Provider %s rate limited, retrying after %s seconds",
                self.provider_id,
                delay,
            )
            await asyncio.sleep(delay)
        # For non-GET requests the delay is still applied as a courtesy to the server,
        # but retrying a mutating request is not safe so the error is raised regardless.
        if method.upper() != "GET" or attempt >= attempts - 1:
            raise ProviderError("Provider rate limit exceeded.")

    async def _reauthenticate(self) -> None:
        self._token = None
        self._auth_header_value = None
        self._session_authenticated = False
        if not self._credentials:
            raise AuthError("Authentication required.")
        self._log_reauthenticating()
        await self.login(self._credentials)

    @asynccontextmanager
    async def _operation_guard(self) -> AsyncIterator[None]:
        """Serialize provider operations that mutate or depend on shared state."""
        task = asyncio.current_task()
        if task is not None and self._lock_owner is task:
            yield
            return
        async with self._operation_lock:
            self._lock_owner = task
            try:
                yield
            finally:
                self._lock_owner = None
