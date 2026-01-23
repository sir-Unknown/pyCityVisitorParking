"""Amsterdam provider implementation."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from ...exceptions import AuthError, ProviderError, ValidationError
from ...models import Favorite, Permit, Reservation, ZoneValidityBlock
from ..base import BaseProvider
from ..loader import ProviderManifest
from .const import (
    CLIENT_PRODUCT_ENDPOINT,
    DEFAULT_API_URI,
    DEFAULT_HEADERS,
    FAVORITE_ADD_ENDPOINT,
    FAVORITE_DELETE_ENDPOINT,
    FAVORITE_LIST_ENDPOINT,
    LOGIN_ENDPOINT,
    PARKING_SESSION_EDIT_ENDPOINT,
    PARKING_SESSION_LIST_ENDPOINT,
    PARKING_SESSION_START_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)
try:
    _LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:
    _LOCAL_TZ = UTC


class Provider(BaseProvider):
    """Provider for Amsterdam visitor parking (EGIS Parking Services)."""

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
        self._credentials: dict[str, str] | None = None
        self._client_product_id: str | None = None
        self._roles: tuple[str, ...] = ()
        self._logged_in = False

    async def login(self, credentials: Mapping[str, str] | None = None, **kwargs: str) -> None:
        """Authenticate against the provider."""
        _LOGGER.debug("Provider %s login started", self.provider_id)
        merged = self._merge_credentials(credentials, **kwargs)
        username = merged.get("username")
        password = merged.get("password")
        client_product_id = merged.get("client_product_id")
        if not username:
            raise ValidationError("username is required.")
        if not password:
            raise ValidationError("password is required.")

        payload = {"username": username, "password": password}
        data = await self._request_json(
            "POST",
            LOGIN_ENDPOINT,
            json=payload,
            allow_reauth=False,
            auth_required=False,
        )
        token = self._extract_token(data)
        if not token:
            raise AuthError("Authentication failed.")
        raw_token = token.removeprefix("Bearer ").strip() if token.startswith("Bearer ") else token
        auth_value = token if token.startswith("Bearer ") else f"Bearer {token}"

        token_payload = self._decode_token(raw_token)
        roles = self._extract_roles(token_payload)
        if client_product_id is None:
            client_product_id = self._extract_client_product_id(token_payload)

        self._token = raw_token
        self._auth_header_value = auth_value
        self._client_product_id = client_product_id
        self._roles = roles
        self._credentials = {
            "username": username,
            "password": password,
        }
        if client_product_id:
            self._credentials["client_product_id"] = client_product_id
        self._logged_in = True
        _LOGGER.debug("Provider %s login completed", self.provider_id)

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        _LOGGER.debug("Provider %s get_permit started", self.provider_id)
        client_product_id = self._require_client_product_id()
        data = await self._request_json(
            "GET",
            CLIENT_PRODUCT_ENDPOINT.format(client_product_id=client_product_id),
            allow_reauth=True,
            auth_required=True,
        )
        permit = self._map_permit(data, client_product_id=client_product_id)
        _LOGGER.debug("Provider %s get_permit completed", self.provider_id)
        return permit

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        _LOGGER.debug("Provider %s list_reservations started", self.provider_id)
        client_product_id = self._require_client_product_id()
        params = {
            "page": 1,
            "row_per_page": 250,
            "filters[client_product_id]": client_product_id,
        }
        data = await self._request_json(
            "GET",
            PARKING_SESSION_LIST_ENDPOINT,
            params=params,
            allow_reauth=True,
            auth_required=True,
        )
        reservations = self._map_reservations(data)
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
        normalized_plate = self._normalize_license_plate(license_plate)
        client_product_id = self._require_client_product_id()
        payload: dict[str, Any] = {
            "vrn": normalized_plate,
            "client_product_id": self._coerce_client_product_id(client_product_id),
            "started_at": self._format_rfc1123(start_dt),
            "ended_at": self._format_rfc1123(end_dt),
        }
        if self._is_visitor_role():
            payload["brand"] = "IDEAL"
        data = await self._request_json(
            "POST",
            PARKING_SESSION_START_ENDPOINT,
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        reservation = self._map_reservation_response(data)
        if reservation is None:
            reservation = self._select_reservation(
                await self.list_reservations(),
                license_plate=normalized_plate,
                start_time=self._format_utc_timestamp(start_dt),
                end_time=self._format_utc_timestamp(end_dt),
            )
        if reservation is None:
            raise ProviderError("Reservation was not returned by the provider.")
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
        payload = {"new_ended_at": self._format_offset_timestamp(end_dt)}
        data = await self._request_json(
            "PATCH",
            PARKING_SESSION_EDIT_ENDPOINT.format(reservation_id=reservation_id_value),
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        reservation = self._map_reservation_response(data)
        if reservation is None:
            reservation = self._select_reservation(
                await self.list_reservations(),
                reservation_id=reservation_id_value,
            )
        if reservation is None:
            raise ProviderError("Reservation was not returned by the provider.")
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
        payload = {"new_ended_at": self._format_offset_timestamp(end_dt)}
        data = await self._request_json(
            "PATCH",
            PARKING_SESSION_EDIT_ENDPOINT.format(reservation_id=reservation_id_value),
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        reservation = self._map_reservation_response(data)
        if reservation is None:
            reservation = self._select_reservation(
                await self.list_reservations(),
                reservation_id=reservation_id_value,
            )
        if reservation is None:
            raise ProviderError("Reservation was not returned by the provider.")
        _LOGGER.debug("Provider %s end_reservation completed", self.provider_id)
        return reservation

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        _LOGGER.debug("Provider %s list_favorites started", self.provider_id)
        data = await self._request_json(
            "GET",
            FAVORITE_LIST_ENDPOINT,
            allow_reauth=True,
            auth_required=True,
        )
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
        payload = {
            "vrn": normalized_plate,
            "description": name or "",
        }
        data = await self._request_json(
            "POST",
            FAVORITE_ADD_ENDPOINT,
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        favorite = self._map_favorite_response(data)
        if favorite is None:
            favorite = self._select_favorite(
                await self.list_favorites(),
                license_plate=normalized_plate,
            )
        if favorite is None:
            raise ProviderError("Favorite was not returned by the provider.")
        _LOGGER.debug("Provider %s add_favorite completed", self.provider_id)
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
        _LOGGER.debug("Provider %s remove_favorite started", self.provider_id)
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        await self._request_text(
            "DELETE",
            FAVORITE_DELETE_ENDPOINT.format(favorite_id=favorite_id_value),
            allow_reauth=True,
            auth_required=True,
        )
        _LOGGER.debug("Provider %s remove_favorite completed", self.provider_id)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: Mapping[str, Any] | None = None,
        allow_reauth: bool,
        auth_required: bool,
    ) -> Any:
        if auth_required and allow_reauth:
            await self._ensure_authenticated()
        return await self._request_with_reauth(
            method,
            path,
            expect_json=True,
            json=json,
            params=params,
            allow_reauth=allow_reauth,
            auth_required=auth_required,
        )

    async def _request_text(
        self,
        method: str,
        path: str,
        *,
        allow_reauth: bool,
        auth_required: bool,
    ) -> str:
        if auth_required and allow_reauth:
            await self._ensure_authenticated()
        return await self._request_with_reauth(
            method,
            path,
            expect_json=False,
            json=None,
            params=None,
            allow_reauth=allow_reauth,
            auth_required=auth_required,
        )

    async def _request_with_reauth(
        self,
        method: str,
        path: str,
        *,
        expect_json: bool,
        json: Any | None,
        params: Mapping[str, Any] | None,
        allow_reauth: bool,
        auth_required: bool,
    ) -> Any:
        url = self._build_url(path)
        headers = self._build_headers(auth_required=auth_required)
        request_kwargs: dict[str, Any] = {"headers": headers}
        if json is not None:
            request_kwargs["json"] = json
        if params is not None:
            request_kwargs["params"] = params
        attempts = 2 if allow_reauth and auth_required else 1
        for attempt in range(attempts):
            try:
                return await self._request(
                    method,
                    url,
                    expect_json=expect_json,
                    **request_kwargs,
                )
            except AuthError:
                if allow_reauth and auth_required and attempt == 0:
                    _LOGGER.warning("Provider %s reauth triggered", self.provider_id)
                    await self._reauthenticate()
                    headers = self._build_headers(auth_required=auth_required)
                    request_kwargs["headers"] = headers
                    continue
                raise
        raise ProviderError("Request failed.")

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
            self._raise_for_status(response)
            if expect_json:
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
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
        await self.login(self._credentials)

    def _build_headers(self, *, auth_required: bool) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        if auth_required:
            if not self._auth_header_value:
                raise AuthError("Authentication required.")
            headers["Authorization"] = self._auth_header_value
        return headers

    def _require_client_product_id(self) -> str:
        if self._client_product_id:
            return self._client_product_id
        raise ValidationError("client_product_id is required.")

    def _coerce_client_product_id(self, value: str) -> int | str:
        if value.isdigit():
            return int(value)
        return value

    def _map_permit(self, data: Any, *, client_product_id: str) -> Permit:
        if not isinstance(data, dict):
            raise ProviderError("Provider response included invalid permit data.")
        permit_id = self._coerce_id(
            data.get("client_product_id") or data.get("id") or client_product_id
        )
        if not permit_id:
            permit_id = client_product_id
        remaining_balance = self._extract_balance(data)
        zone_validity = self._map_zone_validity(data)
        return Permit(
            id=permit_id,
            remaining_balance=remaining_balance,
            zone_validity=zone_validity,
        )

    def _map_zone_validity(self, data: dict[str, Any]) -> list[ZoneValidityBlock]:
        entries: list[tuple[ZoneValidityBlock, bool]] = []
        raw_zone_validity = data.get("zone_validity")
        if isinstance(raw_zone_validity, list):
            for item in raw_zone_validity:
                if not isinstance(item, dict):
                    continue
                start_raw = item.get("start_time") or item.get("started_at")
                end_raw = item.get("end_time") or item.get("ended_at")
                if not start_raw or not end_raw:
                    continue
                try:
                    start = self._parse_provider_timestamp(str(start_raw))
                    end = self._parse_provider_timestamp(str(end_raw))
                except ProviderError as exc:
                    raise ProviderError("Provider returned invalid zone validity data.") from exc
                is_free = item.get("is_free") is True
                entries.append((ZoneValidityBlock(start_time=start, end_time=end), not is_free))
        validity = data.get("validity")
        if not entries and isinstance(validity, dict):
            start_raw = validity.get("started_at") or validity.get("start_time")
            end_raw = validity.get("ended_at") or validity.get("end_time")
            if start_raw and end_raw:
                try:
                    start = self._parse_provider_timestamp(str(start_raw))
                    end = self._parse_provider_timestamp(str(end_raw))
                except ProviderError as exc:
                    raise ProviderError("Provider returned invalid validity data.") from exc
                entries.append((ZoneValidityBlock(start_time=start, end_time=end), True))
        return self._filter_chargeable_zone_validity(entries)

    def _extract_balance(self, data: dict[str, Any]) -> int:
        ssp = data.get("ssp")
        if isinstance(ssp, dict):
            main_account = ssp.get("main_account")
            if isinstance(main_account, dict):
                for key in ("time_balance", "money_balance", "balance"):
                    if key in main_account:
                        return self._parse_int(main_account.get(key))
        for key in ("time_balance", "money_balance", "balance"):
            if key in data:
                return self._parse_int(data.get(key))
        return 0

    def _map_reservations(self, data: Any) -> list[Reservation]:
        items: list[Any]
        if isinstance(data, dict):
            raw_items = data.get("data") or data.get("parking_sessions") or data.get("results")
            if raw_items is None:
                return []
            if not isinstance(raw_items, list):
                raise ProviderError("Provider response included invalid reservations.")
            items = raw_items
        elif isinstance(data, list):
            items = data
        else:
            raise ProviderError("Provider response included invalid reservations.")
        reservations: list[Reservation] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).upper()
            if status and status not in {"ACTIVE", "FUTURE"}:
                continue
            reservations.append(self._map_reservation(item))
        return reservations

    def _map_reservation_response(self, data: Any) -> Reservation | None:
        if isinstance(data, dict):
            if isinstance(data.get("parking_session"), dict):
                return self._map_reservation(data["parking_session"])
            if "parking_session_id" in data or "id" in data:
                return self._map_reservation(data)
        return None

    def _map_reservation(self, item: dict[str, Any]) -> Reservation:
        reservation_id = self._coerce_response_id(
            item.get("parking_session_id") or item.get("id"),
            "reservation id",
        )
        plate_raw = item.get("vrn") or item.get("license_plate") or ""
        normalized_plate = self._normalize_license_plate(str(plate_raw))
        name = item.get("permit_name") or item.get("zone_description") or item.get("name")
        name_value = str(name).strip() if name is not None else normalized_plate
        start_raw = item.get("started_at") or item.get("start_time")
        end_raw = item.get("ended_at") or item.get("end_time")
        if not start_raw or not end_raw:
            raise ProviderError("Provider response missing reservation timestamps.")
        start_time = self._parse_provider_timestamp(str(start_raw))
        end_time = self._parse_provider_timestamp(str(end_raw))
        return Reservation(
            id=reservation_id,
            name=name_value,
            license_plate=normalized_plate,
            start_time=start_time,
            end_time=end_time,
        )

    def _select_reservation(
        self,
        reservations: list[Reservation],
        *,
        reservation_id: str | None = None,
        license_plate: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> Reservation | None:
        if reservation_id:
            return self._find_by_id(reservations, reservation_id)
        for reservation in reservations:
            if license_plate and reservation.license_plate != license_plate:
                continue
            if start_time and reservation.start_time != start_time:
                continue
            if end_time and reservation.end_time != end_time:
                continue
            return reservation
        return None

    def _map_favorite_list(self, data: Any) -> list[Favorite]:
        if isinstance(data, dict):
            raw_items = data.get("favorite_vrns") or data.get("data") or data.get("results")
            if raw_items is None:
                return []
            if not isinstance(raw_items, list):
                raise ProviderError("Provider response included invalid favorites.")
            items = raw_items
        elif isinstance(data, list):
            items = data
        else:
            raise ProviderError("Provider response included invalid favorites.")
        favorites: list[Favorite] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            favorites.append(self._map_favorite(item))
        return favorites

    def _map_favorite_response(self, data: Any) -> Favorite | None:
        if isinstance(data, dict):
            if isinstance(data.get("favorite_vrn"), dict):
                return self._map_favorite(data["favorite_vrn"])
            if "favorite_vrn_id" in data or "id" in data:
                return self._map_favorite(data)
        return None

    def _map_favorite(self, item: dict[str, Any]) -> Favorite:
        favorite_id = self._coerce_response_id(
            item.get("favorite_vrn_id") or item.get("id"),
            "favorite id",
        )
        plate_raw = item.get("vrn") or item.get("license_plate") or ""
        normalized_plate = self._normalize_license_plate(str(plate_raw))
        name = item.get("description") or item.get("name")
        name_value = str(name).strip() if name is not None else normalized_plate
        return Favorite(
            id=favorite_id, name=name_value or normalized_plate, license_plate=normalized_plate
        )

    def _select_favorite(
        self,
        favorites: list[Favorite],
        *,
        license_plate: str,
    ) -> Favorite | None:
        for favorite in favorites:
            if favorite.license_plate == license_plate:
                return favorite
        return None

    def _parse_provider_timestamp(self, value: str) -> str:
        try:
            return self._ensure_utc_timestamp(value)
        except ValidationError:
            pass
        parsed = self._parse_rfc1123(value)
        if parsed is not None:
            return self._format_utc_timestamp(parsed)
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ProviderError("Provider response included invalid timestamp.") from exc
        if parsed.tzinfo is None:
            # Assume provider-local timestamps are Europe/Amsterdam.
            parsed = parsed.replace(tzinfo=_LOCAL_TZ)
            return self._format_utc_timestamp(parsed)
        raise ProviderError("Provider response included invalid timestamp.")

    def _parse_rfc1123(self, value: str) -> datetime | None:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def _format_rfc1123(self, value: datetime) -> str:
        normalized = self._normalize_datetime(value)
        return format_datetime(normalized, usegmt=True)

    def _format_offset_timestamp(self, value: datetime) -> str:
        normalized = self._normalize_datetime(value)
        return normalized.isoformat()

    def _extract_token(self, data: Any) -> str | None:
        if isinstance(data, dict):
            token = data.get("token")
            if isinstance(token, str) and token.strip():
                return token.strip()
        return None

    def _decode_token(self, token: str) -> dict[str, Any]:
        token = token.removeprefix("Bearer ").strip() if token.startswith("Bearer ") else token
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padded = payload + "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
            return json.loads(decoded.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {}

    def _extract_roles(self, payload: dict[str, Any]) -> tuple[str, ...]:
        roles = payload.get("roles")
        if isinstance(roles, list):
            normalized = [str(role) for role in roles if isinstance(role, str)]
            return tuple(normalized)
        return ()

    def _extract_client_product_id(self, payload: dict[str, Any]) -> str | None:
        value = payload.get("client_product_id")
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _is_visitor_role(self) -> bool:
        return "ROLE_VISITOR_SSP" in self._roles

    async def _error_message_from_response(self, response: aiohttp.ClientResponse) -> str | None:
        try:
            data = await response.json()
        except (aiohttp.ContentTypeError, ValueError):
            return None
        if isinstance(data, dict):
            message = data.get("message") or data.get("error")
            if isinstance(message, str):
                trimmed = message.strip()
                if trimmed:
                    return f"Provider error: {trimmed}"
        return None
