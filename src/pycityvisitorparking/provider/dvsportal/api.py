"""DVS Portal provider implementation."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from ...exceptions import AuthError, NetworkError, ProviderError, ValidationError
from ...models import Favorite, Permit, Reservation, ZoneValidityBlock
from ...util import format_utc_timestamp
from ..base import BaseProvider
from ..loader import ProviderManifest
from .const import (
    AUTH_HEADER,
    AUTH_PREFIX,
    DEFAULT_HEADERS,
    FAVORITE_REMOVE_ENDPOINT,
    FAVORITE_UPSERT_ENDPOINT,
    LOGIN_ENDPOINT,
    LOGIN_GETBASE_ENDPOINT,
    LOGIN_METHOD_PAS,
    RESERVATION_CREATE_ENDPOINT,
    RESERVATION_END_ENDPOINT,
    RETRY_AFTER_HEADER,
)


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
        self._permit_media_type_id: str | int | None = None
        self._permit_media_code: str | None = None

    async def login(self, credentials: Mapping[str, str] | None = None, **kwargs: str) -> None:
        """Authenticate against the provider."""
        merged = self._merge_credentials(credentials, **kwargs)
        identifier = merged.get("identifier")
        password = merged.get("password")
        permit_media_type_id = merged.get("permit_media_type_id") or merged.get("permitMediaTypeID")
        if not identifier:
            raise ValidationError("identifier is required.")
        if not password:
            raise ValidationError("password is required.")
        if permit_media_type_id is None:
            permit_media_type_id = self._permit_media_type_id
        if permit_media_type_id is None:
            permit_media_type_id = await self._fetch_permit_media_type_id()
        self._validate_media_type_id(permit_media_type_id)

        payload = {
            "identifier": identifier,
            "loginMethod": LOGIN_METHOD_PAS,
            "password": password,
            "permitMediaTypeID": permit_media_type_id,
        }
        data = await self._request_json(
            "POST",
            LOGIN_ENDPOINT,
            json=payload,
            allow_reauth=False,
        )

        status_value = data.get("LoginStatus")
        if isinstance(status_value, str) and status_value.isdigit():
            status_value = int(status_value)
        token = data.get("Token")
        if status_value == 2 or not token:
            raise AuthError("Authentication failed.")

        self._token = str(token)
        self._auth_header_value = self._build_auth_header(self._token)
        self._permit_media_type_id = permit_media_type_id
        self._credentials = {
            "identifier": identifier,
            "password": password,
            "permit_media_type_id": str(permit_media_type_id),
        }

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        permit = await self._fetch_base()
        return self._map_permit(permit)

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        permit = await self._fetch_base()
        permit_media = self._select_permit_media(permit)
        return self._map_reservations(permit_media)

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
        await self._ensure_defaults()

        payload = {
            "permitMediaTypeID": self._permit_media_type_id,
            "permitMediaCode": self._permit_media_code,
            "DateFrom": start_time,
            "DateUntil": end_time,
            "LicensePlate": {
                "Value": normalized_plate,
                "Name": name,
            },
        }
        data = await self._request_json_auth(
            "POST",
            RESERVATION_CREATE_ENDPOINT,
            json=payload,
        )
        permit = self._extract_permit(data)
        self._cache_defaults(permit)
        permit_media = self._select_permit_media(permit)
        reservations = self._map_reservations(permit_media)
        reservation = self._select_reservation(
            reservations,
            license_plate=normalized_plate,
            start_time=start_time,
            end_time=end_time,
        )
        if reservation is None:
            raise ProviderError("Reservation was not returned by the provider.")
        return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""
        raise ProviderError("Reservation updates are not supported.")

    async def end_reservation(self, reservation_id: str, end_time: str) -> Reservation:
        """End a reservation."""
        normalized_end_time = self._ensure_utc_timestamp(end_time)
        await self._ensure_defaults()

        existing = self._select_reservation(
            await self.list_reservations(),
            reservation_id=str(reservation_id),
            fallback_first=False,
        )
        if existing is None:
            raise ValidationError("reservation_id was not found.")
        payload = {
            "permitMediaTypeID": self._permit_media_type_id,
            "permitMediaCode": self._permit_media_code,
            "ReservationID": str(reservation_id),
        }
        data = await self._request_json_auth(
            "POST",
            RESERVATION_END_ENDPOINT,
            json=payload,
        )
        permit = self._extract_permit(data)
        self._cache_defaults(permit)
        if existing is None:
            raise ProviderError("Reservation not found for ending.")
        return Reservation(
            id=existing.id,
            name=existing.name,
            license_plate=existing.license_plate,
            start_time=existing.start_time,
            end_time=normalized_end_time,
        )

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        permit = await self._fetch_base()
        permit_media = self._select_permit_media(permit)
        return self._map_favorites(permit_media)

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        normalized_plate = self._normalize_license_plate(license_plate)
        await self._ensure_defaults()

        payload = {
            "permitMediaTypeID": self._permit_media_type_id,
            "permitMediaCode": self._permit_media_code,
            "licensePlate": {
                "Value": normalized_plate,
                "Name": name,
            },
            "updateLicensePlate": None,
        }
        data = await self._request_json_auth(
            "POST",
            FAVORITE_UPSERT_ENDPOINT,
            json=payload,
        )
        permit = self._extract_permit(data)
        self._cache_defaults(permit)
        permit_media = self._select_permit_media(permit)
        favorites = self._map_favorites(permit_media)
        favorite = self._select_favorite(favorites, normalized_plate)
        if favorite is None:
            raise ProviderError("Favorite was not returned by the provider.")
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
        await self._ensure_defaults()
        normalized_plate = self._normalize_license_plate(favorite_id)
        payload = {
            "permitMediaTypeID": self._permit_media_type_id,
            "permitMediaCode": self._permit_media_code,
            "licensePlate": normalized_plate,
            "name": None,
        }
        await self._request_json_auth("POST", FAVORITE_REMOVE_ENDPOINT, json=payload)

    async def _fetch_permit_media_type_id(self) -> str | int:
        data = await self._request_json(
            "GET",
            LOGIN_ENDPOINT,
            allow_reauth=False,
        )
        types = data.get("PermitMediaTypes")
        if not isinstance(types, list) or not types:
            raise ProviderError("Provider did not return permit media types.")
        first = types[0]
        if not isinstance(first, dict) or "ID" not in first:
            raise ProviderError("Provider did not return a permit media type ID.")
        return first["ID"]

    async def _fetch_base(self) -> dict[str, Any]:
        await self._ensure_authenticated()
        data = await self._request_json_auth("POST", LOGIN_GETBASE_ENDPOINT, json=None)
        permit = self._extract_permit(data)
        self._cache_defaults(permit)
        return permit

    async def _ensure_authenticated(self) -> None:
        if self._token is None:
            if not self._credentials:
                raise AuthError("Authentication required.")
            await self.login(self._credentials)
        if self._token and not self._auth_header_value:
            self._auth_header_value = self._build_auth_header(self._token)

    async def _ensure_defaults(self) -> None:
        await self._ensure_authenticated()
        if self._permit_media_type_id is None or self._permit_media_code is None:
            await self._fetch_base()
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

    def _select_permit_media(self, permit: dict[str, Any]) -> dict[str, Any]:
        medias = permit.get("PermitMedias")
        if not isinstance(medias, list) or not medias:
            raise ProviderError("Provider response did not include permit media.")
        media = medias[0]
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
        permit_id = self._coerce_id(media.get("Code")) or self._coerce_id(permit.get("ZoneCode"))
        if not permit_id:
            permit_id = "permit"
        remaining_balance = self._parse_int(media.get("Balance"))
        zone_validity = self._map_zone_validity(permit.get("BlockTimes"))
        return Permit(
            id=permit_id,
            remaining_balance=remaining_balance,
            zone_validity=zone_validity,
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
                    name=name or "",
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
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
            except ZoneInfoNotFoundError as exc:
                raise ProviderError("Timezone data for Europe/Amsterdam is unavailable.") from exc
        return format_utc_timestamp(parsed)

    def _select_reservation(
        self,
        reservations: list[Reservation],
        reservation_id: str | None = None,
        license_plate: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        *,
        fallback_first: bool = True,
    ) -> Reservation | None:
        for reservation in reservations:
            if reservation_id is not None and reservation.id != reservation_id:
                continue
            if license_plate is not None and reservation.license_plate != license_plate:
                continue
            if start_time is not None and reservation.start_time != start_time:
                continue
            if end_time is not None and reservation.end_time != end_time:
                continue
            return reservation
        if fallback_first and reservations:
            return reservations[0]
        return None

    def _select_favorite(self, favorites: list[Favorite], plate: str) -> Favorite | None:
        for favorite in favorites:
            if favorite.license_plate == plate:
                return favorite
        return favorites[0] if favorites else None

    def _build_auth_header(self, token: str) -> str:
        encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
        return f"{AUTH_PREFIX}{encoded}"

    def _validate_media_type_id(self, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ValidationError("permit_media_type_id must be a string or integer.")
        if isinstance(value, str) and not value.strip():
            raise ValidationError("permit_media_type_id must be non-empty.")

    def _coerce_id(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def _parse_int(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
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

    async def _request_json_auth(self, method: str, path: str, *, json: Any | None = None) -> Any:
        await self._ensure_authenticated()
        if not self._auth_header_value:
            raise AuthError("Authentication required.")
        headers = {AUTH_HEADER: self._auth_header_value}
        return await self._request_json(
            method,
            path,
            json=json,
            headers=headers,
            allow_reauth=True,
        )

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        allow_reauth: bool,
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
        )

    async def _request(
        self,
        method: str,
        url: str,
        *,
        expect_json: bool,
        json: Any,
        headers: dict[str, str],
        allow_reauth: bool,
    ) -> Any:
        attempts = 2 if allow_reauth else 1
        for attempt in range(attempts):
            try:
                return await self._request_with_backoff(
                    method,
                    url,
                    expect_json=expect_json,
                    json=json,
                    headers=headers,
                )
            except AuthError:
                if allow_reauth and attempt == 0:
                    await self._reauthenticate()
                    headers = {**DEFAULT_HEADERS, AUTH_HEADER: self._auth_header_value or ""}
                    continue
                raise
        raise ProviderError("Request failed.")

    async def _request_with_backoff(
        self,
        method: str,
        url: str,
        *,
        expect_json: bool,
        json: Any,
        headers: dict[str, str],
    ) -> Any:
        retries = self._retry_count if method.upper() == "GET" else 0
        attempts = retries + 1
        for attempt in range(attempts):
            try:
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    timeout=self._timeout,
                    ssl=True,
                ) as response:
                    if response.status == 429:
                        await self._handle_rate_limit(response, method, attempt, attempts)
                        continue
                    if response.status in (401, 403):
                        raise AuthError("Authentication failed.")
                    if not 200 <= response.status < 300:
                        raise ProviderError(
                            f"Provider request failed with status {response.status}."
                        )
                    if expect_json:
                        try:
                            return await response.json()
                        except (aiohttp.ContentTypeError, ValueError) as exc:
                            raise ProviderError("Response did not contain valid JSON.") from exc
                    return await response.text()
            except (aiohttp.ClientError, TimeoutError) as exc:
                if attempt >= attempts - 1:
                    raise NetworkError("Network request failed.") from exc
        raise NetworkError("Network request failed.")

    async def _handle_rate_limit(
        self,
        response: aiohttp.ClientResponse,
        method: str,
        attempt: int,
        attempts: int,
    ) -> None:
        retry_after = response.headers.get(RETRY_AFTER_HEADER)
        if retry_after:
            try:
                delay = int(retry_after)
            except ValueError:
                delay = 0
            if delay > 0:
                # Respect server-provided cooldown before retrying.
                await asyncio.sleep(delay)
        if method.upper() != "GET" or attempt >= attempts - 1:
            raise ProviderError("Provider rate limit exceeded.")

    async def _reauthenticate(self) -> None:
        self._token = None
        self._auth_header_value = None
        if not self._credentials:
            raise AuthError("Authentication required.")
        await self.login(self._credentials)
