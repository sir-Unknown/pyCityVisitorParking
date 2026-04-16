"""2park provider implementation."""

from __future__ import annotations

import asyncio
import json as _json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from ...exceptions import AuthError, ProviderError, ValidationError
from ...models import Favorite, Permit, Reservation
from ...util import format_utc_timestamp, parse_timestamp
from ..base import BaseProvider
from ..loader import ProviderManifest
from .const import (
    API_TIMEZONE,
    AUTH_ENDPOINT,
    BALANCE_AMOUNT_LABEL,
    BALANCE_CURRENCY_LABEL,
    BALANCE_ENDPOINT,
    CATEGORIES_ENDPOINT,
    DEFAULT_API_URI,
    DEFAULT_HEADERS,
    EXTEND_ACTION_ENDPOINT,
    HANDLE_FAVORITE_ENDPOINT,
    LOCALE,
    MEMBER_TYPE_LPN,
    PARAM_LOCATION,
    PARAM_MBR_IDENT,
    PARAM_NICKNAME,
    PARAM_TIMEEND,
    PARAM_TIMESTART,
    PARAM_VALID_UNTIL,
    PRODUCT_DETAILS_ENDPOINT,
    START_ACTION_ENDPOINT,
    STOP_ACTION_ENDPOINT,
    TIME_FORMAT,
)

_LOCATION_RE = re.compile(r"^([A-Z]{3})\w+_(\d+)\$")


class Provider(BaseProvider):
    """Provider for 2park."""

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
        self._product_id: str | None = None
        self._product_location: str | None = None
        self._api_timezone: ZoneInfo | None = None

    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """Authenticate against the provider."""
        self._log_operation_started("login")
        merged = self._merge_credentials(credentials, **kwargs)
        username = merged.get("username")
        password = merged.get("password")
        product_id = merged.get("product_id")
        location = merged.get("location")

        if not username:
            raise ValidationError("username is required.")
        if not password:
            raise ValidationError("password is required.")

        data = await self._post_form(
            AUTH_ENDPOINT,
            {"email": username, "password": password, "locale": LOCALE},
            allow_reauth=False,
        )
        major = data.get("status", {}).get("code", {}).get("major")
        if major != "OK":
            raise AuthError("Authentication failed.")

        if product_id is None or location is None:
            detected_id, detected_location = await self._detect_product(product_id)
            product_id = product_id or detected_id
            location = location or detected_location

        self._product_id = product_id
        self._product_location = location
        self._credentials = {"username": username, "password": password}
        if product_id:
            self._credentials["product_id"] = product_id
        if location:
            self._credentials["location"] = location
        self._log_operation_completed("login", product_id=product_id, location=location)

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        self._log_operation_started("get_permit")
        await self._ensure_authenticated()
        data = await self._post_form(
            BALANCE_ENDPOINT,
            {"product_id": self._product_id or "", "locale": LOCALE},
        )
        permit = self._map_permit(data)
        self._log_operation_completed("get_permit")
        return permit

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        self._log_operation_started("list_reservations")
        details = await self._fetch_product_details()
        reservations = self._map_reservation_list(details)
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
        self._log_operation_started("start_reservation")
        await self._ensure_authenticated()
        start_dt, end_dt = self._validate_reservation_times(start_time, end_time, require_both=True)
        normalized_plate = self._normalize_license_plate(license_plate)
        location = self._product_location
        if not location:
            raise ProviderError("No parking location available for this product.")

        start_str = self._format_provider_timestamp(start_dt)
        end_str = self._format_provider_timestamp(end_dt)
        action_payload = {
            "action": {
                "atn_parameters": [
                    {"prr_label": PARAM_MBR_IDENT, "prr_value": normalized_plate},
                    {"prr_label": PARAM_TIMESTART, "prr_value": start_str},
                    {"prr_label": PARAM_TIMEEND, "prr_value": end_str},
                    {"prr_label": PARAM_LOCATION, "prr_value": location},
                ]
            }
        }
        data = await self._post_form(
            START_ACTION_ENDPOINT,
            {
                "product_id": self._product_id or "",
                "locale": LOCALE,
                "data": _json.dumps(action_payload),
            },
        )
        major = data.get("status", {}).get("code", {}).get("major")
        if major != "OK":
            message = data.get("status", {}).get("message", "Unknown error")
            raise ProviderError(f"Failed to start reservation: {message}")

        action = data.get("data") or {}
        reservation = self._map_action(action, normalized_plate, name)
        if reservation is None:
            # Response did not include action data; build from request parameters.
            action_id = self._coerce_id(action.get("atn_id")) if isinstance(action, dict) else ""
            reservation = Reservation(
                id=action_id or "unknown",
                name=name or normalized_plate,
                license_plate=normalized_plate,
                start_time=format_utc_timestamp(start_dt),
                end_time=format_utc_timestamp(end_dt),
            )
        self._log_operation_completed("start_reservation")
        return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation end time."""
        self._log_operation_started("update_reservation")
        if start_time is not None or name is not None:
            raise ValidationError("Only end_time can be updated.")
        if end_time is None:
            raise ValidationError("end_time is required.")
        reservation_id_value = self._require_id(reservation_id, "reservation_id")

        existing = self._find_by_id(await self.list_reservations(), reservation_id_value)
        if existing is None:
            raise ValidationError("reservation_id was not found.")

        try:
            existing_start_dt = parse_timestamp(existing.start_time)
        except ValidationError as exc:
            raise ProviderError("Provider returned invalid reservation data.") from exc
        end_dt = self._normalize_datetime(end_time)
        self._validate_reservation_times(existing_start_dt, end_dt, require_both=True)

        valid_until_str = self._format_provider_timestamp(end_dt)
        data = await self._post_form(
            EXTEND_ACTION_ENDPOINT,
            {
                "action_id": reservation_id_value,
                "locale": LOCALE,
                "product_id": self._product_id or "",
                PARAM_VALID_UNTIL: valid_until_str,
            },
        )
        major = data.get("status", {}).get("code", {}).get("major")
        if major != "OK":
            message = data.get("status", {}).get("message", "Unknown error")
            raise ProviderError(f"Failed to update reservation: {message}")

        self._log_operation_completed("update_reservation")
        return Reservation(
            id=existing.id,
            name=existing.name,
            license_plate=existing.license_plate,
            start_time=existing.start_time,
            end_time=format_utc_timestamp(end_dt),
        )

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        """End a reservation."""
        self._log_operation_started("end_reservation")
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        end_dt = self._normalize_datetime(end_time)
        normalized_end_time = format_utc_timestamp(end_dt)

        existing = self._find_by_id(await self.list_reservations(), reservation_id_value)
        if existing is None:
            raise ValidationError("reservation_id was not found.")

        data = await self._post_form(
            STOP_ACTION_ENDPOINT,
            {
                "action_id": reservation_id_value,
                "product_id": self._product_id or "",
                "locale": LOCALE,
            },
        )
        major = data.get("status", {}).get("code", {}).get("major")
        if major != "OK":
            message = data.get("status", {}).get("message", "Unknown error")
            raise ProviderError(f"Failed to end reservation: {message}")

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
        """Return stored license plates as favorites."""
        self._log_operation_started("list_favorites")
        details = await self._fetch_product_details()
        favorites = self._map_favorite_list(details)
        self._log_operation_completed("list_favorites", count=len(favorites))
        return favorites

    async def fetch_all(self) -> tuple[Permit, list[Reservation], list[Favorite]]:
        """Return permit, reservations, and favorites with two parallel provider fetches."""
        self._log_operation_started("fetch_all")
        await self._ensure_authenticated()
        permit_data, details = await asyncio.gather(
            self._post_form(
                BALANCE_ENDPOINT,
                {"product_id": self._product_id or "", "locale": LOCALE},
            ),
            self._post_form(
                PRODUCT_DETAILS_ENDPOINT,
                {"product_id": self._product_id or "", "locale": LOCALE},
            ),
        )
        permit = self._map_permit(permit_data)
        reservations = self._map_reservation_list(details)
        favorites = self._map_favorite_list(details)
        self._log_operation_completed(
            "fetch_all",
            reservations=len(reservations),
            favorites=len(favorites),
        )
        return permit, reservations, favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        self._log_operation_started("add_favorite")
        normalized_plate = self._normalize_license_plate(license_plate)
        for existing in await self.list_favorites():
            if existing.license_plate == normalized_plate:
                self._log_operation_failed("add_favorite", "duplicate license_plate")
                raise ValidationError("license_plate is already a favorite.")
        name_value = name or normalized_plate
        data = await self._post_form(
            HANDLE_FAVORITE_ENDPOINT,
            {
                "data": _json.dumps(
                    {
                        "favorite": {
                            "fav_parameters": [
                                {"prr_label": PARAM_NICKNAME, "prr_value": name_value}
                            ],
                            "action": "add",
                            "mbr_ident": normalized_plate,
                        }
                    }
                ),
                "locale": LOCALE,
                "product_id": self._product_id or "",
            },
        )
        major = data.get("status", {}).get("code", {}).get("major")
        if major != "OK":
            message = data.get("status", {}).get("message", "Unknown error")
            raise ProviderError(f"Failed to add favorite: {message}")

        favorites = await self.list_favorites()
        favorite = next((f for f in favorites if f.license_plate == normalized_plate), None)
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
        self._log_operation_started("remove_favorite")
        favorite_id_value = self._require_id(favorite_id, "favorite_id")

        existing = self._find_by_id(await self.list_favorites(), favorite_id_value)
        if existing is None:
            raise ValidationError("favorite_id was not found.")

        data = await self._post_form(
            HANDLE_FAVORITE_ENDPOINT,
            {
                "data": _json.dumps(
                    {
                        "favorite": {
                            "fav_parameters": [
                                {"prr_label": PARAM_NICKNAME, "prr_value": existing.name}
                            ],
                            "action": "remove",
                            "mbr_ident": existing.license_plate,
                        }
                    }
                ),
                "locale": LOCALE,
                "product_id": self._product_id or "",
            },
        )
        major = data.get("status", {}).get("code", {}).get("major")
        if major != "OK":
            message = data.get("status", {}).get("message", "Unknown error")
            raise ProviderError(f"Failed to remove favorite: {message}")
        self._log_operation_completed("remove_favorite")

    async def _detect_product(self, product_id: str | None) -> tuple[str, str | None]:
        """Fetch categories and return (product_id, location) for the selected product."""
        data = await self._post_form(
            CATEGORIES_ENDPOINT,
            {"locale": LOCALE},
            allow_reauth=False,
        )
        candidates: list[dict[str, Any]] = []
        for category in data.get("data", {}).get("categories", []):
            for product in category.get("cty_products", []):
                pdt_id = product.get("pdt_id", "")
                if product_id is not None and pdt_id != product_id:
                    continue
                candidates.append(product)
        # Prefer non-blocked products. pdt_is_blocked is a string "true"/"false".
        # Delegated accounts always have pdt_is_blocked="true", so fall back to the
        # first blocked product when no non-blocked candidate exists.
        candidates.sort(key=lambda p: str(p.get("pdt_is_blocked", "true")).lower() != "false")
        if candidates:
            best = candidates[0]
            return best.get("pdt_id", ""), _extract_location(best)
        raise ProviderError("No suitable 2park product found for this account.")

    async def _fetch_product_details(self) -> dict[str, Any]:
        await self._ensure_authenticated()
        return await self._post_form(
            PRODUCT_DETAILS_ENDPOINT,
            {"product_id": self._product_id or "", "locale": LOCALE},
        )

    async def _ensure_authenticated(self) -> None:
        if self._product_id is None:
            if not self._credentials:
                raise AuthError("Authentication required.")
            await self.login(self._credentials)

    async def _reauthenticate(self) -> None:
        self._product_id = None
        if not self._credentials:
            raise AuthError("Authentication required.")
        self._log_reauthenticating()
        await self.login(self._credentials)

    def _map_permit(self, data: Any) -> Permit:
        balance = data.get("data", {}).get("balance", {}) if isinstance(data, dict) else {}
        amount = _parse_balance_amount(balance)
        balance_unit = _parse_balance_currency(balance)
        permit_id = self._coerce_id(self._product_id) or "permit"
        return Permit(
            id=permit_id, remaining_balance=amount, zone_validity=[], balance_unit=balance_unit
        )

    def _map_reservation_list(self, details: Any) -> list[Reservation]:
        if not isinstance(details, dict):
            raise ProviderError("Provider response included invalid product details.")
        members = [
            m
            for m in details.get("data", {}).get("pdt_members", [])
            if isinstance(m, dict) and m.get("mbr_type") == MEMBER_TYPE_LPN
        ]
        reservations: list[Reservation] = []
        for member in members:
            plate_raw = member.get("mbr_identifier", "")
            try:
                plate = self._normalize_license_plate(plate_raw) if plate_raw else ""
            except ValidationError:
                plate = ""
            for action in member.get("mbr_actions", []):
                reservation = self._map_action(action, plate, None)
                if reservation is not None:
                    reservations.append(reservation)
        return reservations

    def _map_action(
        self,
        action: Any,
        plate: str,
        name: str | None,
    ) -> Reservation | None:
        if not isinstance(action, dict):
            return None
        action_id = self._coerce_id(action.get("atn_id"))
        if not action_id:
            return None
        params = {
            p["prr_label"]: p["prr_value"]
            for p in action.get("atn_parameters", [])
            if isinstance(p, dict) and "prr_label" in p
        }
        start_raw = params.get(PARAM_TIMESTART)
        end_raw = params.get(PARAM_TIMEEND)
        plate_from_params = params.get(PARAM_MBR_IDENT) or plate
        if not start_raw or not end_raw:
            return None
        try:
            normalized_plate = (
                self._normalize_license_plate(plate_from_params) if plate_from_params else plate
            )
            start_utc = self._parse_provider_timestamp(start_raw)
            end_utc = self._parse_provider_timestamp(end_raw)
        except ValidationError as exc:
            raise ProviderError("Provider returned invalid reservation data.") from exc
        return Reservation(
            id=action_id,
            name=name or normalized_plate,
            license_plate=normalized_plate,
            start_time=start_utc,
            end_time=end_utc,
        )

    def _map_favorite_list(self, details: Any) -> list[Favorite]:
        if not isinstance(details, dict):
            raise ProviderError("Provider response included invalid product details.")
        members = [
            m
            for m in details.get("data", {}).get("pdt_members", [])
            if isinstance(m, dict) and m.get("mbr_type") == MEMBER_TYPE_LPN
        ]
        favorites: list[Favorite] = []
        for member in members:
            plate_raw = member.get("mbr_identifier", "")
            if not plate_raw:
                continue
            try:
                plate = self._normalize_license_plate(plate_raw)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid favorite data.") from exc
            member_id = self._coerce_id(member.get("mbr_id")) or plate
            nickname = _extract_nickname(member)
            favorites.append(Favorite(id=member_id, name=nickname or plate, license_plate=plate))
        return favorites

    def _parse_provider_timestamp(self, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Provider timestamp must be a non-empty string.")
        try:
            naive = datetime.strptime(value.strip(), TIME_FORMAT)
        except ValueError as exc:
            raise ValidationError("Provider timestamp is not in expected format.") from exc
        localized = naive.replace(tzinfo=self._provider_timezone(), fold=0)
        return format_utc_timestamp(localized)

    def _format_provider_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            raise ValidationError("Timestamp must include timezone information.")
        localized = value.astimezone(self._provider_timezone())
        return localized.strftime(TIME_FORMAT)

    def _provider_timezone(self) -> ZoneInfo:
        try:
            if self._api_timezone is None:
                self._api_timezone = ZoneInfo(API_TIMEZONE)
            return self._api_timezone
        except ZoneInfoNotFoundError as exc:
            raise ProviderError(f"Timezone data for {API_TIMEZONE} is unavailable.") from exc

    async def _post_form(
        self,
        endpoint: str,
        form_data: dict[str, Any],
        *,
        allow_reauth: bool = True,
    ) -> Any:
        url = self._build_url(endpoint)
        return await self._request_with_optional_reauth(
            allow_reauth=allow_reauth,
            request=lambda: self._do_post_form(url, form_data),
            on_reauth=self._reauthenticate,
        )

    async def _do_post_form(self, url: str, form_data: dict[str, Any]) -> Any:
        async def handle_response(
            response: aiohttp.ClientResponse,
            _attempt: int,
            _attempts: int,
        ) -> Any:
            self._log_response_status(response.status)
            if response.status in (401, 403):
                self._log_request_failure(response.status)
                raise AuthError("Authentication failed.")
            if not 200 <= response.status < 300:
                self._log_request_failure(response.status)
                raise ProviderError(f"Provider request failed with status {response.status}.")
            try:
                return await response.json(content_type=None)
            except (aiohttp.ContentTypeError, ValueError) as exc:
                self._log_invalid_json(await response.text())
                raise ProviderError("Response did not contain valid JSON.") from exc

        return await self._request_with_retries(
            "POST",
            url,
            request_kwargs={"data": form_data, "headers": DEFAULT_HEADERS},
            response_handler=handle_response,
        )


def _parse_balance_amount(balance: dict[str, Any]) -> float:
    for param in balance.get("ble_parameters", []):
        if param.get("prr_label") == BALANCE_AMOUNT_LABEL:
            raw = param.get("prr_value")
            try:
                return float(raw)
            except TypeError, ValueError:
                return 0.0
    return 0.0


def _parse_balance_currency(balance: dict[str, Any]) -> str | None:
    for param in balance.get("ble_parameters", []):
        if param.get("prr_label") == BALANCE_CURRENCY_LABEL:
            value = param.get("prr_value")
            return str(value) if value else None
    return None


def _extract_location(product: dict[str, Any]) -> str | None:
    """Extract the LOCATION default value from a product's parameter groups.

    Falls back to deriving the location code from the product ID pattern,
    e.g. ``BDABZRG_1317$...`` -> ``BDA1317``.
    """
    for group in product.get("pdt_parameter_groups", []):
        if group.get("pgp_label") != "START":
            continue
        for param in group.get("pgp_parameters", []):
            if param.get("prr_label") == PARAM_LOCATION:
                value = param.get("prr_value") or param.get("prr_default_value")
                if value:
                    return value
    match = _LOCATION_RE.match(product.get("pdt_id", ""))
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return None


def _extract_nickname(member: dict[str, Any]) -> str | None:
    for param in member.get("mbr_parameters", []):
        if param.get("prr_label") == PARAM_NICKNAME:
            return param.get("prr_value")
    return None
