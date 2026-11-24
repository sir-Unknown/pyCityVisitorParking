"""Amsterdam provider implementation."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

from ...exceptions import (
    AuthError,
    ErrorCode,
    ProviderError,
    ServiceUnavailableError,
    ValidationError,
)
from ...models import (
    BALANCE_UNIT_EURO,
    BALANCE_UNIT_MINUTE,
    Balance,
    Favorite,
    PaidHoursBlock,
    Permit,
    Reservation,
    ReservationTarget,
)
from ...util import parse_timestamp
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
    PAID_PARKING_ZONE_BY_MACHINE_ENDPOINT,
    PARKING_SESSION_COST_CALCULATOR_ENDPOINT,
    PARKING_SESSION_EDIT_ENDPOINT,
    PARKING_SESSION_LIST_ENDPOINT,
    PARKING_SESSION_START_ENDPOINT,
    PERMIT_LIST_ENDPOINT,
    PERMIT_LIST_FOR_CLIENT_ENDPOINT,
    PERMIT_OVERVIEW_PRODUCT_LIST_ENDPOINT,
)

try:
    _LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
except ZoneInfoNotFoundError:
    _LOCAL_TZ = UTC


# Upstream rejection messages, compared lowercased.
_INVALID_MACHINE_MESSAGES = frozenset(
    {
        "this parking machine does not exist.",
        "the chosen parking machine is not within the allowed zones.",
    }
)
# NPR (the national parking register) being down is a temporary outage, not a rejection.
_SERVICE_UNAVAILABLE_MESSAGES = frozenset({"npr is unavailable."})


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
        # Default parking machine of the permit (ssp.favorite_machine_number).
        self._machine_number: int | str | None = None
        # Whether the permit lets the user pick a parking machine (client_product.config).
        self._can_select_zone = False
        self._parking_context_loaded = False
        self._validity_start: datetime | None = None
        # Paid hours of other parking machines per machine, with the local date fetched.
        self._machine_paid_hours: dict[int, tuple[date, list[PaidHoursBlock]]] = {}

    async def login(self, credentials: Mapping[str, str] | None = None, **kwargs: str) -> None:
        """Authenticate against the provider."""
        self._plogger.operation_started("login")
        merged = self._merge_credentials(credentials, **kwargs)
        username = merged.get("username")
        password = merged.get("password")
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
        client_product_id = self._extract_client_product_id(token_payload)

        self._token = raw_token
        self._auth_header_value = auth_value
        self._roles = roles
        self._credentials = {
            "username": username,
            "password": password,
        }
        self._machine_number = None
        self._can_select_zone = False
        self._parking_context_loaded = False
        self._validity_start = None
        self._machine_paid_hours = {}
        self._logged_in = True
        if client_product_id is None:
            client_product_id = await self._fetch_client_product_id()
        self._client_product_id = client_product_id
        self._plogger.operation_completed("login")

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        self._plogger.operation_started("get_permit")
        client_product_id = self._require_client_product_id()
        data = await self._request_json(
            "GET",
            CLIENT_PRODUCT_ENDPOINT.format(client_product_id=client_product_id),
            allow_reauth=True,
            auth_required=True,
        )
        self._cache_parking_context(data)
        paid_hours = await self._paid_hours()
        permit = self._map_permit(
            data,
            client_product_id=client_product_id,
            paid_hours=paid_hours,
        )
        self._plogger.operation_completed("get_permit")
        return permit

    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""
        self._plogger.operation_started("list_reservations")
        items = await self._fetch_session_items()
        reservations = self._map_reservations(items)
        self._plogger.operation_completed("list_reservations", count=len(reservations))
        return reservations

    async def list_reservation_targets(self) -> list[ReservationTarget]:
        """Return the permit's default parking machine, then the machines of open sessions.

        Other machine numbers (read from a parking machine) are accepted as
        ``reservation_target_id`` too. Permits without zone selection have no targets.
        """
        await self._ensure_parking_context()
        if not self._can_select_zone or self._machine_number is None:
            return []
        reservations = self._map_reservations(await self._fetch_session_items())
        return await self._targets(await self._paid_hours(), reservations)

    async def get_reservation_target(self, reservation_target_id: str) -> ReservationTarget:
        """Return a parking machine of the permit's zones as target, with its paid hours."""
        target_id = self._validate_reservation_target_id(reservation_target_id)
        if target_id is None:
            raise ValidationError("reservation_target_id is required.")
        machine = self._parse_machine_number(target_id)
        await self._ensure_parking_context()
        if not self._can_select_zone:
            raise ValidationError("reservation_target_id is not supported for this permit.")
        if machine == self._machine_number:
            return self._target(machine, await self._paid_hours())
        await self._resolve_machine_zone(machine)
        return self._target(machine, await self._machine_paid_hours_for(machine))

    async def fetch_all(
        self,
    ) -> tuple[Permit, list[Reservation], list[Favorite], list[ReservationTarget]]:
        """Return all data, reusing the permit's paid hours for the default target."""
        permit, reservations, favorites = await asyncio.gather(
            self.get_permit(),
            self.list_reservations(),
            self.list_favorites(),
        )
        targets = await self._targets(permit.paid_hours, reservations)
        return permit, reservations, favorites, targets

    async def _targets(
        self, default_paid_hours: list[PaidHoursBlock], reservations: list[Reservation]
    ) -> list[ReservationTarget]:
        """Return the default machine (with the permit's windows), then open-session machines.

        A machine whose paid hours cannot be fetched is left out, so reservations
        there fall back to the default machine's windows.
        """
        if not self._can_select_zone or self._machine_number is None:
            return []
        targets = [self._target(self._machine_number, default_paid_hours)]
        default_id = str(self._machine_number)
        others = {
            int(reservation.reservation_target_id)
            for reservation in reservations
            if reservation.reservation_target_id
            and reservation.reservation_target_id != default_id
            and reservation.reservation_target_id.isdigit()
        }
        for machine in sorted(others):
            try:
                paid_hours = await self._machine_paid_hours_for(machine)
            except ProviderError as exc:
                self._plogger.debug(
                    "could not fetch paid hours of another parking machine: %s: %s",
                    type(exc).__name__,
                    exc.detail,
                )
                continue
            targets.append(self._target(machine, paid_hours))
        return targets

    def _target(self, machine: int | str, paid_hours: list[PaidHoursBlock]) -> ReservationTarget:
        return ReservationTarget(id=str(machine), name=str(machine), paid_hours=list(paid_hours))

    async def _paid_hours(self) -> list[PaidHoursBlock]:
        """Return the paid hours of the default machine; empty when they cannot be fetched."""
        try:
            return await self._build_paid_zone_validity(days=14)
        except ProviderError as exc:
            self._plogger.debug(
                "could not fetch paid hours: %s: %s", type(exc).__name__, exc.detail
            )
            return []

    async def _machine_paid_hours_for(self, machine: int) -> list[PaidHoursBlock]:
        """Return the paid hours of another machine, fetched at most once per local day."""
        today = self._now().astimezone(_LOCAL_TZ).date()
        cached = self._machine_paid_hours.get(machine)
        if cached is not None and cached[0] == today:
            return cached[1]
        paid_hours = await self._build_paid_zone_validity(days=14, machine_number=machine)
        self._machine_paid_hours[machine] = (today, paid_hours)
        return paid_hours

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
        reservation_target_id: str | None = None,
    ) -> Reservation:
        """Start a reservation, at a parking machine given as ``reservation_target_id``.

        Without a target the permit's default machine is used.
        """
        self._plogger.operation_started("start_reservation")
        target_id = self._validate_reservation_target_id(reservation_target_id)
        target_machine = self._parse_machine_number(target_id) if target_id else None
        start_dt, end_dt = self._validate_reservation_times(
            start_time,
            end_time,
            require_both=True,
        )
        # A start in the past means "start now"; send the current time instead.
        start_dt, end_dt = self._validate_reservation_times(
            self._start_not_before_now(start_dt, whole_minute=False), end_dt, require_both=True
        )
        await self._ensure_parking_context()
        # Like the portal, a start before the permit's validity moves to its start.
        if self._validity_start is not None and start_dt < self._validity_start:
            start_dt, end_dt = self._validate_reservation_times(
                self._validity_start, end_dt, require_both=True
            )
        normalized_plate = self._normalize_license_plate(license_plate)
        client_product_id = self._require_client_product_id()
        payload: dict[str, Any] = {
            "vrn": normalized_plate,
            "client_product_id": self._coerce_client_product_id(client_product_id),
            "started_at": self._format_rfc1123(start_dt),
            "ended_at": self._format_rfc1123(end_dt),
        }
        payload.update(await self._machine_fields(target_machine))
        if self._is_visitor_role():
            payload["brand"] = "IDEAL"
        data = await self._request_json(
            "POST",
            PARKING_SESSION_START_ENDPOINT,
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        # Write responses are undocumented; without a complete session, read it back.
        session = self._complete_session(data)
        if session is not None:
            reservation = self._map_reservation(session)
        else:
            reservation = self._select_reservation(
                await self.list_reservations(),
                reservation_id=self._response_session_id(data),
                license_plate=normalized_plate,
                end_time=self._format_utc_timestamp(end_dt),
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
        self._plogger.operation_started("update_reservation")
        if not self.reservation_update_possible:
            raise ProviderError(
                "Reservation updates are not supported.", error_code=ErrorCode.NOT_SUPPORTED
            )
        if start_time is not None or name is not None:
            raise ValidationError("Only end_time can be updated.")
        if end_time is None:
            raise ValidationError("end_time is required.")
        reservation_id_value = self._require_id(reservation_id, "reservation_id")
        end_dt = self._normalize_datetime(end_time)
        payload = {"new_ended_at": self._format_offset_timestamp(end_dt)}
        current = await self._ensure_session_editable(reservation_id_value)
        data = await self._request_json(
            "PATCH",
            PARKING_SESSION_EDIT_ENDPOINT.format(reservation_id=reservation_id_value),
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        reservation = await self._reservation_after_edit(
            data, current, reservation_id_value, end_dt
        )
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
        payload = {"new_ended_at": self._format_offset_timestamp(end_dt)}
        current = await self._ensure_session_editable(reservation_id_value)
        data = await self._request_json(
            "PATCH",
            PARKING_SESSION_EDIT_ENDPOINT.format(reservation_id=reservation_id_value),
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        reservation = await self._reservation_after_edit(
            data, current, reservation_id_value, end_dt
        )
        self._plogger.operation_completed("end_reservation")
        return reservation

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        self._plogger.operation_started("list_favorites")
        data = await self._request_json(
            "GET",
            FAVORITE_LIST_ENDPOINT,
            allow_reauth=True,
            auth_required=True,
        )
        favorites = self._map_favorite_list(data)
        self._plogger.operation_completed("list_favorites", count=len(favorites))
        return favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        self._plogger.operation_started("add_favorite")
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
        # The portal checks only `code: 201` and re-reads the list; so do we.
        favorite = self._complete_favorite(data)
        if favorite is None:
            favorite = self._select_favorite(
                await self.list_favorites(),
                license_plate=normalized_plate,
            )
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
        raise ProviderError(
            "Favorite updates are not supported.", error_code=ErrorCode.NOT_SUPPORTED
        )

    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
        self._plogger.operation_started("remove_favorite")
        favorite_id_value = self._require_id(favorite_id, "favorite_id")
        await self._request_text(
            "DELETE",
            FAVORITE_DELETE_ENDPOINT.format(favorite_id=favorite_id_value),
            allow_reauth=True,
            auth_required=True,
        )
        self._plogger.operation_completed("remove_favorite")

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
        reauth_enabled = allow_reauth and auth_required

        async def perform_request() -> Any:
            return await self._request(
                method,
                url,
                expect_json=expect_json,
                **request_kwargs,
            )

        async def handle_reauth() -> None:
            await self._reauthenticate()
            request_kwargs["headers"] = self._build_headers(auth_required=auth_required)

        return await self._request_with_optional_reauth(
            allow_reauth=reauth_enabled,
            request=perform_request,
            on_reauth=handle_reauth,
        )

    async def _request(self, method: str, url: str, *, expect_json: bool, **kwargs: Any) -> Any:
        async def handle_response(
            response: aiohttp.ClientResponse,
            _attempt: int,
            _attempts: int,
        ) -> Any:
            self._plogger.response_status(response.status)
            if response.status == 400:
                message = await self._error_message_from_response(response)
                if message and message.lower() in _SERVICE_UNAVAILABLE_MESSAGES:
                    raise ServiceUnavailableError(f"Provider error: {message}")
                if message:
                    raise ProviderError(
                        f"Provider error: {message}", error_code=ErrorCode.PROVIDER_REJECTED
                    )
            self._raise_for_status(response)
            if expect_json:
                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise await self._invalid_json_error(response) from exc
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
        raise ValidationError("client_product_id could not be determined from provider data.")

    def _coerce_client_product_id(self, value: str) -> int | str:
        if value.isdigit():
            return int(value)
        return value

    def _map_permit(
        self,
        data: Any,
        *,
        client_product_id: str,
        paid_hours: list[PaidHoursBlock],
    ) -> Permit:
        if not isinstance(data, dict):
            raise ProviderError("Provider response included invalid permit data.")
        # The meldcode (login username) is a credential, so it never becomes the id.
        permit_id = client_product_id
        return Permit(
            id=permit_id,
            paid_hours=paid_hours,
            balances=self._extract_balances(data),
        )

    async def _build_paid_zone_validity(
        self, *, days: int, machine_number: int | None = None
    ) -> list[PaidHoursBlock]:
        """Return paid parking windows for today through the next given days.

        ``time_frame_data`` is a weekly schedule (index 0 is Monday), so one
        cost calculation covers every day of the range. Without ``machine_number``
        the default machine is used.
        """
        if days < 0:
            raise ValidationError("Days must be zero or positive.")
        today = self._now().astimezone(_LOCAL_TZ).date()
        time_frame_data = await self._fetch_time_frame_data(machine_number)
        if not isinstance(time_frame_data, list):
            self._plogger.debug("cost calculation returned no weekly paid parking schedule")
        entries: list[tuple[PaidHoursBlock, bool]] = []
        for offset in range(days + 1):
            target_date = today + timedelta(days=offset)
            entries.extend(self._map_time_frame_data_for_date(time_frame_data, target_date))
        if isinstance(time_frame_data, list) and not entries:
            # The schedule format is only known from the portal bundle; describe what
            # arrived so a debug log shows why no block was read.
            self._plogger.debug(
                "weekly paid parking schedule has no readable blocks: %s",
                self._describe_time_frame_data(time_frame_data),
            )
        return self._filter_paid_hours(entries)

    def _describe_time_frame_data(self, raw: list[Any]) -> str:
        """Return the shape of a weekly schedule: day types, block keys, time values."""
        days = [type(day).__name__ if not isinstance(day, list) else len(day) for day in raw]
        first_block = next(
            (block for day in raw if isinstance(day, list) for block in day),
            None,
        )
        if not isinstance(first_block, dict):
            return f"days={days} first_block={type(first_block).__name__}"
        # Clock times are not personal data; other values are left out.
        times = {
            key: first_block.get(key) for key in ("startTime", "endTime") if key in first_block
        }
        return f"days={days} first_block_keys={sorted(first_block)} times={times!r}"

    async def _fetch_time_frame_data(self, machine_number: int | None) -> Any:
        """Return the weekly paid parking schedule from a cost calculation.

        ``time_frame_data`` is a weekly schedule, so the calculated period only
        has to be one the portal accepts: a session that starts now (or at the
        permit's validity start) and lasts an hour, never one in the past.
        """
        await self._ensure_parking_context()
        start = self._now()
        if self._validity_start is not None and start < self._validity_start:
            start = self._validity_start
        payload: dict[str, Any] = {
            "client_product_id": self._coerce_client_product_id(self._require_client_product_id()),
            "started_at": self._format_rfc1123(start),
            "ended_at": self._format_rfc1123(start + timedelta(hours=1)),
        }
        # The portal sends only the machine number to the cost calculator.
        if machine_number is not None:
            payload["machine_number"] = machine_number
        elif self._can_select_zone:
            if self._machine_number is None:
                raise ProviderError("Permit has no default parking machine.")
            payload["machine_number"] = self._machine_number
        data = await self._request_json(
            "POST",
            PARKING_SESSION_COST_CALCULATOR_ENDPOINT,
            json=payload,
            allow_reauth=True,
            auth_required=True,
        )
        time_frame_data = self._extract_time_frame_data(data)
        if time_frame_data is None:
            # Only the key names are logged; the values hold amounts and ids.
            self._plogger.debug(
                "cost calculation response has no time_frame_data; keys: %s",
                sorted(data) if isinstance(data, dict) else type(data).__name__,
            )
        return time_frame_data

    def _extract_time_frame_data(self, data: Any) -> Any:
        if isinstance(data, dict):
            if "time_frame_data" in data:
                return data.get("time_frame_data")
            nested = data.get("parking_session_balance")
            if isinstance(nested, dict) and "time_frame_data" in nested:
                return nested.get("time_frame_data")
        return None

    def _map_time_frame_data_for_date(
        self,
        raw: Any,
        target_date: date,
    ) -> list[tuple[PaidHoursBlock, bool]]:
        if not isinstance(raw, list):
            return []
        weekday = target_date.weekday()
        if weekday >= len(raw):
            return []
        day_blocks = raw[weekday]
        if not isinstance(day_blocks, list):
            return []
        entries: list[tuple[PaidHoursBlock, bool]] = []
        for block in day_blocks:
            if not isinstance(block, dict):
                continue
            start_clock = self._parse_time_frame_value(block.get("startTime"))
            end_clock = self._parse_time_frame_value(block.get("endTime"))
            if start_clock is None or end_clock is None:
                continue
            start_local = datetime.combine(target_date, start_clock, tzinfo=_LOCAL_TZ)
            end_local = datetime.combine(target_date, end_clock, tzinfo=_LOCAL_TZ)
            if end_local <= start_local:
                end_local = end_local + timedelta(days=1)
            entries.append(
                (
                    PaidHoursBlock(
                        start_time=self._format_utc_timestamp(start_local),
                        end_time=self._format_utc_timestamp(end_local),
                    ),
                    True,
                )
            )
        return entries

    def _parse_time_frame_value(self, value: Any) -> time | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if len(text) != 4 or not text.isdigit():
            return None
        hour = int(text[:2])
        minute = int(text[2:])
        if hour > 23 or minute > 59:
            return None
        return time(hour, minute)

    def _extract_balances(self, data: dict[str, Any]) -> list[Balance]:
        """Return the main account balances: time first, then money.

        ``time_balance`` is in seconds and ``money_balance`` in cents. A permit
        can hold both (hours plus money for the reduced parking fee); each one
        that is present is reported, ``0`` included.
        """
        ssp = data.get("ssp")
        main_account = ssp.get("main_account") if isinstance(ssp, dict) else None
        if not isinstance(main_account, dict):
            return []
        balances: list[Balance] = []
        if main_account.get("time_balance") is not None:
            minutes = self._parse_int(main_account["time_balance"]) // 60
            balances.append(Balance(minutes, BALANCE_UNIT_MINUTE))
        if main_account.get("money_balance") is not None:
            euros = self._parse_int(main_account["money_balance"]) / 100
            balances.append(Balance(euros, BALANCE_UNIT_EURO))
        return balances

    def _parse_machine_number(self, value: str) -> int:
        """Validate a parking machine number given as ``reservation_target_id``."""
        text = value.strip()
        if not text.isascii() or not text.isdigit() or int(text) == 0:
            raise ValidationError("reservation_target_id must be a parking machine number.")
        return int(text)

    async def _resolve_machine_zone(self, machine_number: int) -> int | str | None:
        """Return the zone of a parking machine, validated against the permit."""
        client_product_id = self._coerce_client_product_id(self._require_client_product_id())
        try:
            data = await self._request_json(
                "POST",
                PAID_PARKING_ZONE_BY_MACHINE_ENDPOINT,
                json={
                    "client_product_id": client_product_id,
                    "machine_number": machine_number,
                },
                allow_reauth=True,
                auth_required=True,
            )
        except ProviderError as exc:
            upstream = exc.detail.lower().removeprefix("provider error: ")
            if (
                exc.error_code == ErrorCode.PROVIDER_REJECTED
                and upstream in _INVALID_MACHINE_MESSAGES
            ):
                raise ValidationError(
                    "reservation_target_id is not a parking machine of this permit."
                ) from None
            raise
        zone = data.get("zone") if isinstance(data, dict) else None
        return self._coerce_optional_id(zone.get("zone_id")) if isinstance(zone, dict) else None

    def _cache_parking_context(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        config = data.get("config")
        self._can_select_zone = isinstance(config, dict) and config.get("can_select_zone") is True
        self._parking_context_loaded = True
        validity = data.get("validity")
        self._validity_start = self._parse_validity_start(validity)
        # The permit's default machine; zones are only resolved for other machines.
        ssp = data.get("ssp")
        self._machine_number = (
            self._coerce_optional_id(ssp.get("favorite_machine_number"))
            if isinstance(ssp, dict)
            else None
        )

    def _parse_validity_start(self, validity: Any) -> datetime | None:
        if not isinstance(validity, dict) or not validity.get("started_at"):
            return None
        try:
            return parse_timestamp(self._parse_provider_timestamp(str(validity["started_at"])))
        except ProviderError:
            return None

    async def _ensure_parking_context(self) -> None:
        if self._parking_context_loaded:
            return
        client_product_id = self._require_client_product_id()
        data = await self._request_json(
            "GET",
            CLIENT_PRODUCT_ENDPOINT.format(client_product_id=client_product_id),
            allow_reauth=True,
            auth_required=True,
        )
        self._cache_parking_context(data)

    async def _machine_fields(self, target_machine: int | None) -> dict[str, Any]:
        """Return the parking machine fields for a session start.

        Like the portal, a machine is only sent for permits with
        ``config.can_select_zone``. Another machine than the default is
        resolved to its zone and never becomes the new default.
        """
        if not self._can_select_zone:
            if target_machine is not None:
                raise ValidationError("reservation_target_id is not supported for this permit.")
            return {}
        if target_machine is None or target_machine == self._machine_number:
            if self._machine_number is None:
                raise ValidationError("Permit has no default parking machine; pass a target.")
            return {"machine_number": self._machine_number}
        fields: dict[str, Any] = {
            "machine_number": target_machine,
            "is_new_favorite_machine_number": False,
        }
        zone_id = await self._resolve_machine_zone(target_machine)
        if zone_id is not None:
            fields["zone_id"] = zone_id
        return fields

    def _coerce_optional_id(self, value: Any) -> int | str | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value != 0 else None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            if text.isdigit():
                number = int(text)
                return number if number != 0 else None
            return text
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            number = int(text)
            return number if number != 0 else None
        return text

    async def _fetch_session_items(self) -> list[dict[str, Any]]:
        """Return the raw parking sessions of the permit."""
        # Newest first, like the portal, so open sessions stay on the first page.
        params = {
            "page": 1,
            "row_per_page": 250,
            "sort": "parking_session_id:desc",
            "filters[client_product_id]": self._require_client_product_id(),
        }
        data = await self._request_json(
            "GET",
            PARKING_SESSION_LIST_ENDPOINT,
            params=params,
            allow_reauth=True,
            auth_required=True,
        )
        if isinstance(data, dict):
            raw_items = data.get("data") or data.get("parking_sessions") or data.get("results")
            if raw_items is None:
                return []
        else:
            raw_items = data
        if not isinstance(raw_items, list):
            raise ProviderError("Provider response included invalid reservations.")
        return [item for item in raw_items if isinstance(item, dict)]

    def _is_open_session(self, item: dict[str, Any]) -> bool:
        status = str(item.get("status", "")).upper()
        return not status or status in {"ACTIVE", "FUTURE"}

    def _map_reservations(self, items: list[dict[str, Any]]) -> list[Reservation]:
        return [self._map_reservation(item) for item in items if self._is_open_session(item)]

    async def _ensure_session_editable(self, reservation_id: str) -> dict[str, Any] | None:
        """Reject changes the portal does not offer for this session; return the session.

        The portal only edits or stops sessions with ``can_edit`` that are
        ACTIVE or FUTURE. A session missing from the first page is left to the
        backend to judge.
        """
        for item in await self._fetch_session_items():
            if str(item.get("parking_session_id")) != reservation_id:
                continue
            if item.get("can_edit") is False or not self._is_open_session(item):
                raise ProviderError(
                    "Reservation cannot be changed.", error_code=ErrorCode.PROVIDER_REJECTED
                )
            return item
        return None

    async def _reservation_after_edit(
        self,
        data: Any,
        current: dict[str, Any] | None,
        reservation_id: str,
        end_dt: datetime,
    ) -> Reservation:
        """Return the edited session: from the response, else the session read before the edit.

        An ended session is no longer open, so it cannot be read back from the list.
        """
        session = self._complete_session(data)
        if session is not None:
            return self._map_reservation(session)
        if current is not None:
            return replace(
                self._map_reservation(current), end_time=self._format_utc_timestamp(end_dt)
            )
        reservation = self._select_reservation(
            await self.list_reservations(), reservation_id=reservation_id
        )
        if reservation is None:
            raise ProviderError("Reservation was not returned by the provider.")
        return reservation

    def _response_session(self, data: Any) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            return None
        nested = data.get("parking_session")
        return nested if isinstance(nested, dict) else data

    def _complete_session(self, data: Any) -> dict[str, Any] | None:
        """Return the session of a write response only when it has every mapped field."""
        item = self._response_session(data)
        if (
            item is not None
            and (item.get("parking_session_id") or item.get("id"))
            and (item.get("vrn") or item.get("license_plate"))
            and (item.get("started_at") or item.get("start_time"))
            and (item.get("ended_at") or item.get("end_time"))
        ):
            return item
        return None

    def _response_session_id(self, data: Any) -> str | None:
        item = self._response_session(data)
        if item is None:
            return None
        value = item.get("parking_session_id") or item.get("id")
        if value is None:
            return None
        return str(value).strip() or None

    def _map_reservation(self, item: dict[str, Any]) -> Reservation:
        reservation_id = self._coerce_response_id(
            item.get("parking_session_id") or item.get("id"),
            "reservation id",
        )
        # parking_session list uses vrn/started_at/ended_at.
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
        machine_number = self._coerce_optional_id(item.get("machine_number"))
        return Reservation(
            id=reservation_id,
            name=name_value,
            license_plate=normalized_plate,
            start_time=start_time,
            end_time=end_time,
            reservation_target_id=str(machine_number) if machine_number is not None else None,
        )

    def _select_reservation(
        self,
        reservations: list[Reservation],
        *,
        reservation_id: str | None = None,
        license_plate: str | None = None,
        end_time: str | None = None,
    ) -> Reservation | None:
        """Find by id; with a plate, fall back to the plate and end time."""
        if reservation_id:
            found = self._find_by_id(reservations, reservation_id)
            if found is not None or license_plate is None:
                return found
        if license_plate is None:
            return None
        for reservation in reservations:
            if reservation.license_plate != license_plate:
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

    def _complete_favorite(self, data: Any) -> Favorite | None:
        """Return the favorite of a write response only when it has an id and a plate."""
        if not isinstance(data, dict):
            return None
        nested = data.get("favorite_vrn")
        item = nested if isinstance(nested, dict) else data
        if (item.get("favorite_vrn_id") or item.get("id")) and (
            item.get("vrn") or item.get("license_plate")
        ):
            return self._map_favorite(item)
        return None

    def _map_favorite(self, item: dict[str, Any]) -> Favorite:
        favorite_id = self._coerce_response_id(
            item.get("favorite_vrn_id") or item.get("id"),
            "favorite id",
        )
        # favorite_vrn list/add uses vrn/description.
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
        except TypeError, ValueError:
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
        except ValueError, json.JSONDecodeError:
            return {}

    def _extract_roles(self, payload: dict[str, Any]) -> tuple[str, ...]:
        roles = payload.get("roles")
        if isinstance(roles, list):
            normalized = [str(role) for role in roles if isinstance(role, str)]
            return tuple(normalized)
        return ()

    def _extract_client_product_id(self, payload: dict[str, Any]) -> str | None:
        # Handle multiple JWT payload shapes seen across deployments/versions.
        for key in ("client_product_id", "clientProductId"):
            value = payload.get(key)
            text = self._coerce_client_product_id_value(value)
            if text:
                return text
        for key in ("client_product_ids", "clientProductIds"):
            text = self._extract_client_product_id_from_container(payload.get(key))
            if text:
                return text
        for key in ("client_products", "clientProducts", "client_product", "clientProduct"):
            text = self._extract_client_product_id_from_container(payload.get(key))
            if text:
                return text
        return None

    async def _fetch_client_product_id(self) -> str:
        last_error: Exception | None = None
        attempts = [
            (
                PERMIT_OVERVIEW_PRODUCT_LIST_ENDPOINT,
                {"page": 1, "row_per_page": 25},
                self._extract_client_product_id_from_product_list,
            ),
            (
                PERMIT_LIST_FOR_CLIENT_ENDPOINT,
                None,
                self._extract_client_product_id_from_permit_list,
            ),
            (PERMIT_LIST_ENDPOINT, None, self._extract_client_product_id_from_permit_list),
        ]
        for path, params, extractor in attempts:
            try:
                data = await self._request_json(
                    "GET",
                    path,
                    params=params,
                    allow_reauth=False,
                    auth_required=True,
                )
            except ProviderError as exc:
                last_error = exc
                continue
            client_product_id = extractor(data)
            if client_product_id:
                return client_product_id
        raise ProviderError("Provider did not return client_product_id.") from last_error

    def _extract_client_product_id_from_product_list(self, data: Any) -> str | None:
        if isinstance(data, dict):
            for key in ("client_product_id", "clientProductId"):
                text = self._coerce_client_product_id_value(data.get(key))
                if text:
                    return text
            items = data.get("data") or data.get("results") or data.get("items")
            return self._extract_client_product_id_from_product_items(items)
        if isinstance(data, list):
            return self._extract_client_product_id_from_product_items(data)
        return None

    def _extract_client_product_id_from_product_items(self, value: Any) -> str | None:
        if not isinstance(value, list):
            return None
        for item in value:
            if not isinstance(item, dict):
                continue
            if self._is_client_product_item(item):
                for key in (
                    "client_product_id",
                    "clientProductId",
                    "product_id",
                    "productId",
                    "id",
                ):
                    text = self._coerce_client_product_id_value(item.get(key))
                    if text:
                        return text
            for key in ("client_product_id", "clientProductId"):
                text = self._coerce_client_product_id_value(item.get(key))
                if text:
                    return text
        return None

    def _is_client_product_item(self, item: dict[str, Any]) -> bool:
        for key in ("type", "request_type", "requestType", "product_type", "productType"):
            value = item.get(key)
            if isinstance(value, str) and value.lower() == "client_product":
                return True
        return False

    def _extract_client_product_id_from_permit_list(self, data: Any) -> str | None:
        if isinstance(data, dict):
            for key in ("client_product_id", "clientProductId", "mainId"):
                text = self._coerce_client_product_id_value(data.get(key))
                if text:
                    return text
            permits = data.get("permit") or data.get("permits") or data.get("results")
            if isinstance(permits, list):
                return self._extract_client_product_id_from_permits(permits)
        if isinstance(data, list):
            return self._extract_client_product_id_from_permits(data)
        return None

    def _extract_client_product_id_from_permits(self, permits: list[Any]) -> str | None:
        for permit in permits:
            if not isinstance(permit, dict):
                continue
            for key in ("client_product_id", "clientProductId", "product_id", "productId"):
                text = self._coerce_client_product_id_value(permit.get(key))
                if text:
                    return text
            # Permit listings often only expose permit_id; treat it as the client product id.
            text = self._coerce_client_product_id_value(permit.get("permit_id"))
            if text:
                return text
        return None

    def _coerce_client_product_id_value(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _extract_client_product_id_from_container(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("client_product_id", "id"):
                text = self._coerce_client_product_id_value(value.get(key))
                if text:
                    return text
            for key in ("client_product_ids", "clientProductIds"):
                text = self._extract_client_product_id_from_container(value.get(key))
                if text:
                    return text
            for key in ("client_products", "clientProducts", "client_product", "clientProduct"):
                text = self._extract_client_product_id_from_container(value.get(key))
                if text:
                    return text
            return None
        if isinstance(value, list):
            for item in value:
                text = self._extract_client_product_id_from_container(item)
                if text:
                    return text
            return None
        return self._coerce_client_product_id_value(value)

    def _is_visitor_role(self) -> bool:
        return "ROLE_VISITOR_SSP" in self._roles

    async def _error_message_from_response(self, response: aiohttp.ClientResponse) -> str | None:
        try:
            data = await response.json()
        except aiohttp.ContentTypeError, ValueError:
            return None
        if isinstance(data, dict):
            message = data.get("message") or data.get("error")
            if isinstance(message, str):
                trimmed = message.strip()
                if trimmed:
                    return trimmed
        return None
