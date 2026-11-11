"""Refactored DVS Portal provider implementation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import aiohttp

from ...const import RESOLVED_PERMIT_MEDIA_TYPE_ID
from ...exceptions import AuthError, ProviderError, ValidationError
from ...models import Favorite, Permit, Reservation
from ...util import parse_timestamp
from ..base import BaseProvider, _HttpSession
from ..loader import ProviderManifest
from .const import (
    DEFAULT_API_URI,
    FAVORITE_REMOVE_ENDPOINT,
    FAVORITE_UPSERT_ENDPOINT,
    LOGIN_ENDPOINT,
    LOGIN_GETBASE_ENDPOINT,
    RESERVATION_CREATE_ENDPOINT,
    RESERVATION_END_ENDPOINT,
    RESERVATION_UPDATE_ENDPOINT,
)
from .mapping import PortalMapper
from .profile import DvsPortalProfile, PortalProfile
from .session import PortalSessionState
from .transport import PortalTransport


class Provider(BaseProvider):
    """Provider for DVS Portal with split mapping and transport internals."""

    def __init__(
        self,
        session: _HttpSession,
        manifest: ProviderManifest,
        *,
        base_url: str | None = None,
        api_uri: str | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
        retry_count: int = 0,
        profile: PortalProfile | None = None,
    ) -> None:
        """Initialize the provider."""
        super().__init__(
            session,
            manifest,
            base_url=base_url,
            api_uri=api_uri or DEFAULT_API_URI,
            timeout=timeout,
            retry_count=retry_count,
        )
        self._state = PortalSessionState()
        self._profile = profile or DvsPortalProfile()
        self._mapper = PortalMapper(self, self._state)
        self._transport = PortalTransport(self, self._state, self._profile, self._plogger)
        self._operation_lock = asyncio.Lock()
        self._lock_owner: asyncio.Task[Any] | None = None

    @property
    def resolved_login_params(self) -> dict[str, str]:
        """Return provider-resolved login parameters from the last successful login."""
        result: dict[str, str] = {}
        if self._state.permit_media_type_id is not None:
            result[RESOLVED_PERMIT_MEDIA_TYPE_ID] = str(self._state.permit_media_type_id)
        return result

    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """Authenticate against the provider."""
        async with self._operation_guard():
            self._plogger.operation_started("login")
            await self._transport.fetch_app_env()
            merged = self._merge_credentials(credentials, **kwargs)
            username = merged.get("username")
            password = merged.get("password")
            permit_media_type_id = merged.get("permit_media_type_id")
            if not username:
                raise ValidationError("username is required.")
            if not password:
                raise ValidationError("password is required.")
            if permit_media_type_id is None:
                permit_media_type_id = self._state.permit_media_type_id
            if permit_media_type_id is None:
                permit_media_type_id = await self._fetch_permit_media_type_id(operation="login")
            self._validate_media_type_id(permit_media_type_id)

            payload = self._profile.build_login_payload(
                username=username,
                password=password,
                permit_media_type_id=permit_media_type_id,
            )
            data = await self._request_json(
                "POST",
                LOGIN_ENDPOINT,
                json=payload,
                allow_reauth=False,
                include_auth=False,
                operation="login",
            )

            status_value = self._profile.normalize_login_status(data.get("LoginStatus"))
            token = data.get("Token")
            error_message = data.get("ErrorMessage")
            requires_otp = data.get("RequiresOtp")
            if self._profile.is_login_error(data, status_value):
                self._plogger.log(
                    logging.WARNING,
                    "login failed: LoginStatus=%r token_present=%s "
                    "requires_otp=%r error_message=%r",
                    status_value,
                    bool(token),
                    requires_otp,
                    error_message,
                )
                raise AuthError("Authentication failed.")

            self._state.token = str(token) if token else None
            self._state.auth_header_value = (
                self._profile.build_auth_header(self._state.token)
                if self._state.token is not None
                else None
            )
            self._state.session_authenticated = True
            self._state.permit_media_type_id = permit_media_type_id
            self._state.credentials = {
                "username": username,
                "password": password,
                "permit_media_type_id": str(permit_media_type_id),
            }

            if self._mapper.response_includes_permit(data):
                permit = self._mapper.extract_permit(data)
                try:
                    self._mapper.cache_defaults(permit)
                except ProviderError:
                    # Some deployments include Permit/Permits in the login response
                    # before PermitMedias is fully populated. Fall back to getbase
                    # so a successful login does not regress into an auth failure.
                    self._plogger.missing_response_data(
                        "login", fallback="fetching base", response_data=permit
                    )
                    await self._fetch_base(operation="login", allow_reauth=False)
            else:
                await self._fetch_base(operation="login", allow_reauth=False)

            self._plogger.operation_completed(
                "login",
                login_status=status_value,
                token_present=bool(token),
                permit_media_type_id=permit_media_type_id,
            )

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        async with self._operation_guard():
            self._plogger.operation_started("get_permit")
            permit = await self._fetch_base(operation="get_permit")
            mapped = self._mapper.map_permit(permit)
            self._plogger.operation_completed("get_permit")
            return mapped

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        async with self._operation_guard():
            self._plogger.operation_started("list_reservations")
            reservations = self._mapper.reservations_from_permit(
                await self._fetch_base(operation="list_reservations")
            )
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
        async with self._operation_guard():
            self._plogger.operation_started("start_reservation")
            start_time_utc, end_time_utc = self._validate_reservation_times(
                start_time,
                end_time,
                require_both=True,
            )
            start_time_utc_value = self._format_utc_timestamp(start_time_utc)
            end_time_utc_value = self._format_utc_timestamp(end_time_utc)
            normalized_plate = self._normalize_license_plate(license_plate)
            await self._ensure_defaults(operation="start_reservation")

            payload = {
                "permitMediaTypeID": self._state.permit_media_type_id,
                "permitMediaCode": self._state.permit_media_code,
                "DateFrom": self._mapper.format_provider_timestamp(start_time_utc),
                "DateUntil": self._mapper.format_provider_timestamp(end_time_utc),
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
            reservations = self._mapper.reservations_from_permit(permit)
            reservation = self._mapper.select_reservation(
                reservations,
                license_plate=normalized_plate,
                start_time=start_time_utc_value,
                end_time=end_time_utc_value,
            )
            if reservation is None:
                raise ProviderError("Reservation was not returned by the provider.")
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
        async with self._operation_guard():
            self._plogger.operation_started("update_reservation")
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
            existing = self._mapper.select_reservation(
                self._mapper.reservations_from_permit(
                    await self._fetch_base(operation="update_reservation")
                ),
                reservation_id=reservation_id_value,
            )
            if existing is None:
                self._plogger.operation_failed("update_reservation", "reservation_id not found")
                raise ValidationError("reservation_id was not found.")
            if self._state.permit_media_type_id is None or self._state.permit_media_code is None:
                raise ProviderError("Permit media defaults are missing.")
            try:
                existing_start_dt = parse_timestamp(existing.start_time)
                existing_end_dt = parse_timestamp(existing.end_time)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid reservation data.") from exc

            self._validate_reservation_times(existing_start_dt, end_dt, require_both=True)
            delta_seconds = int((end_dt - existing_end_dt).total_seconds())
            if delta_seconds % 60 != 0:
                raise ValidationError("end_time must be aligned to whole minutes.")
            payload = {
                "Minutes": delta_seconds // 60,
                "ReservationID": reservation_id_value,
                "permitMediaTypeID": self._state.permit_media_type_id,
                "permitMediaCode": self._state.permit_media_code,
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
            reservations = self._mapper.reservations_from_permit(permit)
            updated = self._mapper.select_reservation(
                reservations,
                reservation_id=reservation_id_value,
            )
            if updated is None:
                raise ProviderError("Reservation was not returned by the provider.")
            self._plogger.operation_completed("update_reservation")
            return updated

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        """End a reservation."""
        async with self._operation_guard():
            self._plogger.operation_started("end_reservation")
            end_dt = self._normalize_datetime(end_time)
            normalized_end_time = self._format_utc_timestamp(end_dt)
            await self._ensure_defaults(operation="end_reservation")
            existing = self._mapper.select_reservation(
                self._mapper.reservations_from_permit(
                    await self._fetch_base(operation="end_reservation")
                ),
                reservation_id=reservation_id,
            )
            if existing is None:
                self._plogger.operation_failed("end_reservation", "reservation_id not found")
                raise ValidationError("reservation_id was not found.")
            payload = {
                "permitMediaTypeID": self._state.permit_media_type_id,
                "permitMediaCode": self._state.permit_media_code,
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
            self._mapper.cache_defaults(permit)
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
        async with self._operation_guard():
            self._plogger.operation_started("list_favorites")
            favorites = self._mapper.favorites_from_permit(
                await self._fetch_base(operation="list_favorites")
            )
            self._plogger.operation_completed("list_favorites", count=len(favorites))
            return favorites

    async def fetch_all(self) -> tuple[Permit, list[Reservation], list[Favorite]]:
        """Return permit, reservations, and favorites with a single provider fetch."""
        async with self._operation_guard():
            self._plogger.operation_started("fetch_all")
            permit_raw = await self._fetch_base(operation="fetch_all")
            permit = self._mapper.map_permit(permit_raw)
            reservations = self._mapper.reservations_from_permit(permit_raw)
            favorites = self._mapper.favorites_from_permit(permit_raw)
            self._plogger.operation_completed(
                "fetch_all",
                reservations=len(reservations),
                favorites=len(favorites),
            )
            return permit, reservations, favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        async with self._operation_guard():
            self._plogger.operation_started("add_favorite")
            normalized_plate = self._normalize_license_plate(license_plate)
            favorites = self._mapper.favorites_from_permit(
                await self._fetch_base(operation="add_favorite")
            )
            for favorite in favorites:
                if favorite.license_plate == normalized_plate:
                    self._plogger.operation_failed("add_favorite", "duplicate license_plate")
                    raise ValidationError("license_plate is already a favorite.")
            if self._state.permit_media_type_id is None or self._state.permit_media_code is None:
                raise ProviderError("Permit media defaults are missing.")
            name_value = name or normalized_plate

            payload = {
                "permitMediaTypeID": self._state.permit_media_type_id,
                "permitMediaCode": self._state.permit_media_code,
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
            if data.get("ErrorMessage"):
                self._plogger.provider_error_response(data, operation="favorite upsert")
            try:
                favorites = self._mapper.favorites_from_permit(self._mapper.extract_permit(data))
            except ProviderError:
                self._plogger.missing_response_data(
                    "favorite upsert", fallback="refetching list", response_data=data
                )
                favorites = self._mapper.favorites_from_permit(
                    await self._fetch_base(operation="add_favorite")
                )
            favorite = self._mapper.select_favorite(favorites, normalized_plate)
            if favorite is None:
                raise ProviderError("Favorite was not returned by the provider.")
            self._plogger.operation_completed("add_favorite")
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
            self._plogger.operation_started("remove_favorite")
            normalized_plate = self._normalize_license_plate(favorite_id)
            favorites = self._mapper.favorites_from_permit(
                await self._fetch_base(operation="remove_favorite")
            )
            found = next(
                (favorite for favorite in favorites if favorite.license_plate == normalized_plate),
                None,
            )
            name_value = (found and found.name) or normalized_plate
            if self._state.permit_media_type_id is None or self._state.permit_media_code is None:
                raise ProviderError("Permit media defaults are missing.")
            payload = {
                "permitMediaTypeID": self._state.permit_media_type_id,
                "permitMediaCode": self._state.permit_media_code,
                "licensePlate": normalized_plate,
                "name": name_value,
            }
            await self._request_json_auth(
                "POST",
                FAVORITE_REMOVE_ENDPOINT,
                json=payload,
                operation="remove_favorite",
            )
            self._plogger.operation_completed("remove_favorite")

    async def _fetch_permit_media_type_id(self, *, operation: str = "login") -> str | int:
        """Return the default permit media type ID from the login bootstrap call."""
        data = await self._request_json(
            "GET",
            LOGIN_ENDPOINT,
            allow_reauth=False,
            include_auth=False,
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
        if data.get("ErrorMessage"):
            self._plogger.provider_error_response(data, operation=label)
        try:
            permit = self._mapper.extract_permit(data)
        except ProviderError:
            self._plogger.missing_response_data(label, response_data=data)
            return await self._fetch_base(operation=operation)
        self._mapper.cache_defaults(permit)
        return permit

    async def _fetch_base(
        self, *, operation: str = "fetch_base", allow_reauth: bool = True
    ) -> dict[str, Any]:
        """Fetch the current base model and return the active permit."""
        if allow_reauth:
            data = await self._request_json_auth(
                "POST",
                LOGIN_GETBASE_ENDPOINT,
                operation=operation,
            )
        else:
            data = await self._request_json(
                "POST",
                LOGIN_GETBASE_ENDPOINT,
                allow_reauth=False,
                include_auth=True,
                operation=operation,
            )
        permit = self._mapper.extract_permit(data)
        self._mapper.cache_defaults(permit)
        return permit

    async def _ensure_defaults(self, *, operation: str = "ensure_defaults") -> None:
        """Ensure auth and permit media defaults are available."""
        await self._transport.ensure_authenticated()
        if self._state.permit_media_type_id is None or self._state.permit_media_code is None:
            await self._fetch_base(operation=operation)
        if self._state.permit_media_type_id is None or self._state.permit_media_code is None:
            raise ProviderError("Permit media defaults are missing.")

    def _build_auth_header(self, token: str) -> str:
        """Return the Authorization header value for a raw provider token."""
        return self._profile.build_auth_header(token)

    @property
    def _token(self) -> str | None:
        """Compatibility access for tests and diagnostics."""
        return self._state.token

    @_token.setter
    def _token(self, value: str | None) -> None:
        """Compatibility access for tests and diagnostics."""
        self._state.token = value

    @property
    def _auth_header_value(self) -> str | None:
        """Compatibility access for tests and diagnostics."""
        return self._state.auth_header_value

    @_auth_header_value.setter
    def _auth_header_value(self, value: str | None) -> None:
        """Compatibility access for tests and diagnostics."""
        self._state.auth_header_value = value

    @property
    def _session_authenticated(self) -> bool:
        """Compatibility access for tests and diagnostics."""
        return self._state.session_authenticated

    @_session_authenticated.setter
    def _session_authenticated(self, value: bool) -> None:
        """Compatibility access for tests and diagnostics."""
        self._state.session_authenticated = value

    @property
    def _permit_media_type_id(self) -> str | int | None:
        """Compatibility access for tests and diagnostics."""
        return self._state.permit_media_type_id

    @_permit_media_type_id.setter
    def _permit_media_type_id(self, value: str | int | None) -> None:
        """Compatibility access for tests and diagnostics."""
        self._state.permit_media_type_id = value

    @property
    def _permit_media_code(self) -> str | None:
        """Compatibility access for tests and diagnostics."""
        return self._state.permit_media_code

    @_permit_media_code.setter
    def _permit_media_code(self, value: str | None) -> None:
        """Compatibility access for tests and diagnostics."""
        self._state.permit_media_code = value

    def _validate_media_type_id(self, value: Any) -> None:
        """Validate the provider media type ID."""
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValidationError("permit_media_type_id must be a string or integer.")
        if isinstance(value, str) and not value.strip():
            raise ValidationError("permit_media_type_id must be non-empty.")

    def _extract_permit(self, data: dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.extract_permit(data)

    def _response_includes_permit(self, data: dict[str, Any]) -> bool:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.response_includes_permit(data)

    def _select_permit_media(self, permit: dict[str, Any]) -> dict[str, Any]:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.select_permit_media(permit)

    def _cache_defaults(self, permit: dict[str, Any]) -> None:
        """Backward-compatible mapper wrapper for tests and introspection."""
        self._mapper.cache_defaults(permit)

    def _map_permit(self, permit: dict[str, Any]) -> Permit:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.map_permit(permit)

    def _map_reservations(self, permit_media: dict[str, Any]) -> list[Reservation]:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.map_reservations(permit_media)

    def _map_favorites(self, permit_media: dict[str, Any]) -> list[Favorite]:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.map_favorites(permit_media)

    def _parse_provider_timestamp(self, value: str) -> str:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.parse_provider_timestamp(value)

    def _format_provider_timestamp(self, value: datetime) -> str:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.format_provider_timestamp(value)

    def _select_reservation(
        self,
        reservations: list[Reservation],
        reservation_id: str | None = None,
        license_plate: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> Reservation | None:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.select_reservation(
            reservations,
            reservation_id=reservation_id,
            license_plate=license_plate,
            start_time=start_time,
            end_time=end_time,
        )

    def _select_favorite(self, favorites: list[Favorite], plate: str) -> Favorite | None:
        """Backward-compatible mapper wrapper for tests and introspection."""
        return self._mapper.select_favorite(favorites, plate)

    async def _request_json_auth(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        operation: str | None = None,
    ) -> Any:
        """Backward-compatible transport wrapper for tests and introspection."""
        return await self._transport.request_json_auth(
            method,
            path,
            json=json,
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
        include_auth: bool = False,
        operation: str | None = None,
    ) -> Any:
        """Backward-compatible transport wrapper for tests and introspection."""
        return await self._transport.request_json(
            method,
            path,
            json=json,
            headers=headers,
            allow_reauth=allow_reauth,
            include_auth=include_auth,
            operation=operation,
        )

    @asynccontextmanager
    async def _operation_guard(self) -> AsyncIterator[None]:
        """Serialize operations that depend on shared session state."""
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
