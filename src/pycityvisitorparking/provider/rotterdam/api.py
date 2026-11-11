"""Rotterdam provider implementation."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import aiohttp

from ...exceptions import AuthError, NotFoundError, ProviderError, ValidationError
from ...models import (
    BALANCE_UNIT_MINUTE,
    Favorite,
    Permit,
    Reservation,
    Zone,
    ZoneValidityBlock,
)
from ..base import BaseProvider
from ..loader import ProviderManifest
from .const import (
    ASSOC_ACTION_PERMIT,
    ASSOC_AUTHORIZATION_ACCOUNT,
    ASSOC_AUTHORIZATION_PERMIT,
    ASSOC_BALANCE_AUTHORIZATION,
    ASSOC_BALANCE_PERMIT,
    ASSOC_PARKING_TIME_ZONE,
    ASSOC_PLATE_ACCOUNT,
    ASSOC_ZONE_RELATION_PERMIT,
    ASSOC_ZONE_RELATION_ZONE,
    CHANNEL,
    CONSTANT_MINUTES_PER_UNIT,
    CSRF_HEADER,
    DEFAULT_HEADERS,
    ENTITY_API_RESULT,
    ENTITY_BALANCE,
    ENTITY_PARKING_ACTION,
    ENTITY_PARKING_ACTION_HELPER,
    ENTITY_PARKING_TIME,
    ENTITY_PERMIT_AUTHORIZATION,
    ENTITY_PLATE,
    ENTITY_PLATE_HELPER,
    ENTITY_ZONE_RELATION,
    EU_PLATE_MAX_LENGTH,
    LANDCODE_EU,
    LANDCODE_NL,
    LOCAL_TIMEZONE,
    NL_PLATE_LENGTH,
    OPERATION_ACTION_CANCEL,
    OPERATION_ACTION_COST,
    OPERATION_ACTION_SAVE,
    OPERATION_PLATE_DELETE,
    OPERATION_PLATE_SAVE,
    OPERATIONS,
    PAGE_ENDPOINT,
    PERMIT_STATUS_ACTIVE,
    PERMIT_TYPE_BUSINESS_HOURS,
    SESSION_PARAMS,
    XAS_ENDPOINT,
    ZONE_TYPE_ZONE,
)
from .mendix import (
    MendixObject,
    datetime_from_milliseconds,
    find_operation_id,
    milliseconds_from_datetime,
    parse_integer,
    parse_objects,
    xpath_guid,
    xpath_opaque_id,
)

_CACHE_BUST_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
_MAX_DETAIL_CHARS = 200


def _values(values: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Wrap attribute values in the Mendix ``changes`` format."""
    return {name: {"value": value} for name, value in values.items()}


class Provider(BaseProvider):
    """Provider for Rotterdam visitor parking (Mendix based portal)."""

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
        self._csrf_token: str | None = None
        self._constants: dict[str, str] = {}
        self._cache_bust: str | None = None
        self._operations: dict[str, str] = {}
        self._pages: dict[str, str] = {}
        self._auth_lock = asyncio.Lock()
        self._session_generation = 0

    # ------------------------------------------------------------------
    # Authentication and transport
    # ------------------------------------------------------------------

    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """Authenticate against the provider."""
        self._plogger.operation_started("login")
        merged = self._merge_credentials(credentials, **kwargs)
        username = merged.get("username", "").strip()
        password = merged.get("password", "")
        if not username:
            raise ValidationError("username is required.")
        if not password:
            raise ValidationError("password is required.")
        async with self._auth_lock:
            await self._authenticate(username, password)
        self._credentials = {"username": username, "password": password}
        self._plogger.operation_completed("login")

    async def _authenticate(self, username: str, password: str) -> None:
        """Start an anonymous session and sign in on it."""
        self._csrf_token = None
        session = await self._post(
            {"action": "get_session_data", "params": dict(SESSION_PARAMS)},
            operation="session_data",
        )
        csrf_token = session.get("csrftoken")
        if not isinstance(csrf_token, str) or not csrf_token:
            raise ProviderError("Provider session did not include a CSRF token.")
        self._csrf_token = csrf_token
        try:
            result = await self._post(
                {"action": "login", "params": {"username": username, "password": password}},
                operation="login",
            )
        except Exception:
            self._csrf_token = None
            raise
        signed_in_token = result.get("csrftoken")
        if not isinstance(signed_in_token, str) or not signed_in_token:
            self._csrf_token = None
            raise ProviderError("Provider login did not return a session token.")
        self._csrf_token = signed_in_token
        self._constants = {
            str(item["name"]): str(item["value"])
            for item in session.get("constants", [])
            if isinstance(item, Mapping) and "name" in item and "value" in item
        }
        cache_bust = session.get("cachebust")
        self._cache_bust = (
            cache_bust
            if isinstance(cache_bust, str) and _CACHE_BUST_RE.fullmatch(cache_bust)
            else None
        )
        self._session_generation += 1

    async def _reauthenticate(self, seen_generation: int) -> None:
        async with self._auth_lock:
            if self._session_generation != seen_generation:
                return  # Another task already renewed the session.
            if self._credentials is None:
                raise AuthError("Authentication required.")
            self._plogger.reauthenticating()
            self._clear_session_cookies()
            await self._authenticate(self._credentials["username"], self._credentials["password"])

    def _clear_session_cookies(self) -> None:
        # Sign in on a fresh anonymous session instead of reusing the expired one.
        cookie_jar = getattr(self._session, "cookie_jar", None)
        host = urlsplit(self._base_url or "").hostname
        if cookie_jar is not None and host:
            cookie_jar.clear_domain(host)

    async def _post(self, body: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
        """POST a runtime request without reauthentication.

        The body is sent as pre-serialized data so the shared request logger never sees
        license plates or credentials.
        """
        headers = dict(DEFAULT_HEADERS)
        if self._csrf_token:
            headers[CSRF_HEADER] = self._csrf_token
        data = await self._request_json(
            "POST",
            XAS_ENDPOINT,
            data=json.dumps(body),
            headers=headers,
            operation=operation,
        )
        if not isinstance(data, dict):
            raise ProviderError("Provider response was not an object.")
        return data

    async def _xas(self, body: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
        """POST a runtime request and reauthenticate once when the session expired."""
        if self._credentials is None:
            raise AuthError("Authentication required.")
        generation = self._session_generation

        async def reauth() -> None:
            await self._reauthenticate(generation)

        return await self._request_with_optional_reauth(
            allow_reauth=True,
            request=lambda: self._post(body, operation=operation),
            on_reauth=reauth,
        )

    async def _retrieve(self, xpath: str, *, operation: str) -> list[MendixObject]:
        data = await self._xas(
            {
                "action": "retrieve_by_xpath",
                "params": {"xpath": xpath, "schema": {}, "count": False},
            },
            operation=operation,
        )
        return parse_objects(data)

    async def _instantiate(self, entity: str) -> dict[str, Any]:
        """Create a server-side helper object and return its raw representation."""
        data = await self._xas(
            {
                "action": "instantiate",
                "params": {"objecttype": entity},
                "changes": {},
                "objects": [],
            },
            operation="instantiate",
        )
        guid = data.get("actionResult")
        raw_objects = data.get("objects")
        if isinstance(raw_objects, list):
            for raw in raw_objects:
                if (
                    isinstance(raw, dict)
                    and raw.get("guid") == guid
                    and raw.get("objectType") == entity
                ):
                    return raw
        raise ProviderError("Provider did not create the requested object.")

    async def _page_definition(self, page: str) -> str:
        cached = self._pages.get(page)
        if cached is not None:
            return cached
        path = f"{PAGE_ENDPOINT}/{page}"
        if self._cache_bust:
            path = f"{path}?{self._cache_bust}"
        text = await self._request_text(
            "GET",
            path,
            headers={"Accept": "application/xml, text/xml, */*"},
            operation="page_definition",
        )
        self._pages[page] = text
        return text

    async def _operation_id(self, key: str) -> str:
        """Resolve the operation id of a microflow from the published page definitions.

        DESIGN DECISION D3 (see README "Design decisions"): ids are never hardcoded.
        """
        cached = self._operations.get(key)
        if cached is not None:
            return cached
        spec = OPERATIONS[key]
        page_xml = await self._page_definition(spec.page)
        operation_id = find_operation_id(page_xml, spec.nanoflow, spec.parameters)
        if operation_id is None:
            self._plogger.operation_failed("resolve_operation", "not found", key=key)
            raise ProviderError("Provider operation could not be resolved.")
        self._operations[key] = operation_id
        return operation_id

    async def _call_operation(
        self,
        key: str,
        params: Mapping[str, Any],
        changes: Mapping[str, Mapping[str, Any]],
        objects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        operation_id = await self._operation_id(key)
        return await self._xas(
            {
                "action": "runtimeOperation",
                "operationId": operation_id,
                "params": params,
                "validationGuids": [],
                "changes": changes,
                "objects": objects,
            },
            operation=key,
        )

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _minutes_per_unit(self) -> int:
        minutes = parse_integer(self._constants.get(CONSTANT_MINUTES_PER_UNIT))
        if minutes <= 0:
            raise ProviderError("Provider did not publish the balance unit length.")
        return minutes

    # ------------------------------------------------------------------
    # Permit
    # ------------------------------------------------------------------

    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""
        self._plogger.operation_started("get_permit")
        authorization = await self._select_authorization()
        permit = await self._build_permit(authorization)
        self._plogger.operation_completed("get_permit")
        return permit

    async def fetch_all(self) -> tuple[Permit, list[Reservation], list[Favorite]]:
        """Return permit, reservations, and favorites with a single permit selection."""
        authorization = await self._select_authorization()
        permit_guid = self._permit_guid(authorization)
        permit, reservations, favorites = await asyncio.gather(
            self._build_permit(authorization),
            self._reservations_for(permit_guid),
            self.list_favorites(),
        )
        return permit, reservations, favorites

    async def _load_authorizations(self) -> list[MendixObject]:
        """Return the account's usable permit authorizations in a stable order."""
        found = await self._retrieve(
            f"//{ENTITY_PERMIT_AUTHORIZATION}["
            f"Status = '{PERMIT_STATUS_ACTIVE}'"
            " and IsVerwijderdDoorGebruiker = false()"
            " and (TijdstipIntrekken = empty or TijdstipIntrekken > '[%CurrentDateTime%]')"
            f" and {ASSOC_AUTHORIZATION_ACCOUNT} = '[%CurrentUser%]']",
            operation="retrieve_permits",
        )
        found.sort(
            key=lambda item: (item.text("Omschrijving") or "", item.text("_Id") or "", item.guid)
        )
        return found

    async def _select_authorization(self) -> MendixObject:
        # DESIGN DECISION D2 (see README "Design decisions"): with several usable permits
        # the first one in the stable order of ``_load_authorizations`` is used.
        found = await self._load_authorizations()
        if not found:
            raise NotFoundError("No active permit found for this account.")
        return found[0]

    def _permit_guid(self, authorization: MendixObject) -> str:
        return xpath_guid(authorization.text(ASSOC_AUTHORIZATION_PERMIT), "permit reference")

    def _authorization_id(self, authorization: MendixObject) -> str:
        return self._coerce_response_id(authorization.text("_Id"), "permit id")

    async def _build_permit(self, authorization: MendixObject) -> Permit:
        permit_guid = self._permit_guid(authorization)
        balance, zone_objects = await asyncio.gather(
            self._remaining_balance(authorization, permit_guid),
            self._permit_zones(permit_guid),
        )
        zones = await self._zones(zone_objects)
        return Permit(
            id=self._authorization_id(authorization),
            remaining_balance=balance,
            # DESIGN DECISION D1 (see README "Design decisions"): the permit-level windows
            # are those of the default zone, the first of ``zones``.
            zone_validity=zones[0].zone_validity if zones else [],
            balance_unit=BALANCE_UNIT_MINUTE,
            zones=zones,
        )

    async def _remaining_balance(self, authorization: MendixObject, permit_guid: str) -> float:
        """Return the remaining balance in minutes."""
        local_now = self._now().astimezone(ZoneInfo(LOCAL_TIMEZONE))
        if authorization.text("VergunningType") == PERMIT_TYPE_BUSINESS_HOURS:
            # Business-hours permits carry a balance per calendar month.
            authorization_guid = xpath_guid(authorization.guid, "permit authorization")
            constraint = (
                f"{ASSOC_BALANCE_AUTHORIZATION} = '{authorization_guid}'"
                f" and Jaar = {local_now.year} and Maand = {local_now.month}"
            )
        else:
            constraint = f"{ASSOC_BALANCE_PERMIT} = '{permit_guid}' and Jaar = {local_now.year}"
        rows = await self._retrieve(
            f"//{ENTITY_BALANCE}[{constraint}]", operation="retrieve_balance"
        )
        units = parse_integer(rows[0].value("SaldoHuidig")) if rows else 0
        return float(units * self._minutes_per_unit())

    async def _permit_zones(self, permit_guid: str) -> list[MendixObject]:
        """Return the permit's zones ordered by name; the first one is the default zone."""
        relations = await self._retrieve(
            f"//{ENTITY_ZONE_RELATION}[{ASSOC_ZONE_RELATION_PERMIT} = '{permit_guid}']",
            operation="retrieve_zone_relations",
        )
        zone_ids = sorted(
            {
                xpath_guid(zone_id, "zone reference")
                for relation in relations
                if (zone_id := relation.text(ASSOC_ZONE_RELATION_ZONE)) is not None
            }
        )
        if not zone_ids:
            return []
        data = await self._xas(
            {"action": "retrieve_by_ids", "params": {"ids": zone_ids, "schema": {}}},
            operation="retrieve_zones",
        )
        zones = [
            zone
            for zone in parse_objects(data)
            if zone.value("isDeleted") is not True
            and zone.text("TypeZone") in (None, ZONE_TYPE_ZONE)
        ]
        names = [self._zone_id(zone) for zone in zones]
        if len(set(names)) != len(names):
            # Parking actions address a zone by name, so names must identify a zone.
            raise ProviderError("Provider returned several zones with the same name.")
        zones.sort(key=self._zone_id)
        return zones

    def _zone_id(self, zone: MendixObject) -> str:
        """Return the public zone id: the zone name, which parking actions are booked by."""
        name = zone.text("Naam")
        if not name:
            raise ProviderError("Provider response included a zone without a name.")
        return name

    async def _zones(self, zones: list[MendixObject]) -> list[Zone]:
        """Map the permit's zones, each with its upcoming chargeable windows."""
        windows = await asyncio.gather(
            *(self._zone_validity(xpath_guid(zone.guid, "zone id")) for zone in zones)
        )
        return [
            Zone(id=self._zone_id(zone), name=self._zone_id(zone), zone_validity=validity)
            for zone, validity in zip(zones, windows, strict=True)
        ]

    async def _zone_validity(self, zone_guid: str) -> list[ZoneValidityBlock]:
        """Return the upcoming parking-time windows of one zone.

        Every stored parking-time window is a chargeable window, so no free windows exist
        to filter out. Overlapping and touching windows are merged; the portal splits a
        window that crosses midnight into two rows.
        """
        rows = await self._retrieve(
            f"//{ENTITY_PARKING_TIME}[{ASSOC_PARKING_TIME_ZONE} = '{zone_guid}' "
            "and TotTijd > '[%CurrentDateTime%]']",
            operation="retrieve_parking_times",
        )
        windows: list[tuple[datetime, datetime]] = []
        for row in rows:
            start = datetime_from_milliseconds(row.value("VanafTijd"))
            end = datetime_from_milliseconds(row.value("TotTijd"))
            if start is None or end is None or end <= start:
                raise ProviderError("Provider returned invalid zone validity data.")
            windows.append((start, end))
        merged: list[tuple[datetime, datetime]] = []
        for start, end in sorted(windows):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        entries = [
            (
                ZoneValidityBlock(
                    start_time=self._format_utc_timestamp(start),
                    end_time=self._format_utc_timestamp(end),
                ),
                True,
            )
            for start, end in merged
        ]
        return self._filter_chargeable_zone_validity(entries)

    # ------------------------------------------------------------------
    # Reservations
    # ------------------------------------------------------------------

    async def list_reservations(self) -> list[Reservation]:
        """Return active and planned reservations."""
        self._plogger.operation_started("list_reservations")
        authorization = await self._select_authorization()
        reservations = await self._reservations_for(self._permit_guid(authorization))
        self._plogger.operation_completed("list_reservations", count=len(reservations))
        return reservations

    async def _reservations_for(self, permit_guid: str) -> list[Reservation]:
        rows = await self._retrieve(
            f"//{ENTITY_PARKING_ACTION}["
            "IsGeannuleerd = false() and Eindtijd > '[%CurrentDateTime%]'"
            f" and {ASSOC_ACTION_PERMIT} = '{permit_guid}']",
            operation="retrieve_reservations",
        )
        reservations = [self._map_reservation(row) for row in rows]
        reservations.sort(key=lambda item: (item.start_time, item.id))
        return reservations

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
        zone_id: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate, in ``zone_id`` or the default zone."""
        self._plogger.operation_started("start_reservation")
        requested_zone = self._validate_zone_id(zone_id)
        start_dt, end_dt = self._validate_reservation_times(start_time, end_time, require_both=True)
        plate = self._normalize_license_plate(license_plate)
        landcode = self._landcode(plate)
        start_dt, end_dt = self._reservation_window(start_dt, end_dt, clamp_start=True)
        authorization = await self._select_authorization()
        permit_guid = self._permit_guid(authorization)
        zone_name = await self._zone_name(permit_guid, requested_zone)
        values: dict[str, Any] = {
            "Kenteken": plate,
            "Landcode": landcode,
            "KentekenOmschrijving": name or plate,
            "ZoneDisplayNaam": zone_name,
            "Starttijd": milliseconds_from_datetime(start_dt),
            "Eindtijd": milliseconds_from_datetime(end_dt),
        }
        data = await self._submit_action(
            OPERATION_ACTION_SAVE, authorization, values, plate=plate, preview_cost=True
        )
        reservation = await self._created_reservation(
            data, permit_guid, plate=plate, start_dt=start_dt, end_dt=end_dt
        )
        self._plogger.operation_completed("start_reservation")
        return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update the start and/or end time of a reservation."""
        self._plogger.operation_started("update_reservation")
        if not self.reservation_update_possible:
            raise ProviderError("Reservation updates are not supported.")
        if name is not None:
            raise ValidationError("name cannot be updated.")
        start_dt, end_dt = self._validate_reservation_times(
            start_time, end_time, require_both=False
        )
        if start_dt is None and end_dt is None:
            raise ValidationError("start_time or end_time is required.")
        reservation_id_value = xpath_opaque_id(
            self._require_id(reservation_id, "reservation_id"), "reservation_id"
        )
        existing = await self._find_action(reservation_id_value, active_only=True)
        existing_start = datetime_from_milliseconds(existing.value("Starttijd"))
        existing_end = datetime_from_milliseconds(existing.value("Eindtijd"))
        if existing_start is None or existing_end is None:
            raise ProviderError("Provider response included invalid reservation data.")
        started = existing_start <= self._now()
        if (
            start_dt is not None
            and started
            and self._minute(start_dt) != self._minute(existing_start)
        ):
            raise ValidationError("start_time cannot be changed after the reservation started.")
        new_start = existing_start if started or start_dt is None else start_dt
        new_end = end_dt if end_dt is not None else existing_end
        new_start, new_end = self._reservation_window(new_start, new_end, clamp_start=not started)
        authorization = await self._authorization_for(existing)
        values = self._values_from_action(existing)
        if not started:
            # DESIGN DECISION D4 (see README "Design decisions"): a running reservation
            # keeps its stored start untouched; only a planned one gets a new start.
            values["Starttijd"] = milliseconds_from_datetime(new_start)
        values["Eindtijd"] = milliseconds_from_datetime(new_end)
        await self._submit_action(
            OPERATION_ACTION_SAVE,
            authorization,
            values,
            plate=existing.text("Kenteken") or "",
            preview_cost=True,
        )
        reservation = await self._reread_reservation(reservation_id_value)
        self._plogger.operation_completed("update_reservation")
        return reservation

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        """End a running reservation, or cancel a planned one."""
        self._plogger.operation_started("end_reservation")
        reservation_id_value = xpath_opaque_id(
            self._require_id(reservation_id, "reservation_id"), "reservation_id"
        )
        end_dt = self._normalize_datetime(end_time)
        existing = await self._find_action(reservation_id_value, active_only=True)
        existing_start = datetime_from_milliseconds(existing.value("Starttijd"))
        if existing_start is None:
            raise ProviderError("Provider response included invalid reservation data.")
        authorization = await self._authorization_for(existing)
        values = self._values_from_action(existing)
        plate = existing.text("Kenteken") or ""
        now = self._now()
        if existing_start > now:
            # A planned reservation has nothing to stop; the portal deletes it instead.
            await self._submit_action(
                OPERATION_ACTION_CANCEL, authorization, values, plate=plate, preview_cost=False
            )
            self._plogger.operation_completed("end_reservation")
            return self._map_reservation(existing)
        # Never end in the past: the portal stops a running reservation at the current time.
        values["Eindtijd"] = milliseconds_from_datetime(max(end_dt, now))
        await self._submit_action(
            OPERATION_ACTION_SAVE, authorization, values, plate=plate, preview_cost=False
        )
        reservation = await self._reread_reservation(reservation_id_value)
        self._plogger.operation_completed("end_reservation")
        return reservation

    def _minute(self, value: datetime) -> datetime:
        return value.replace(second=0, microsecond=0)

    def _reservation_window(
        self,
        start: datetime,
        end: datetime,
        *,
        clamp_start: bool,
    ) -> tuple[datetime, datetime]:
        """Return the start and end at the minute resolution the portal works with.

        DESIGN DECISION D4 (see README "Design decisions"): the portal works with minutes,
        so seconds are dropped. A start in the past means "start now" for the portal, so it
        is moved to the current minute when ``clamp_start`` is set.
        """
        start_minute = self._minute(start)
        end_minute = self._minute(end)
        if clamp_start:
            start_minute = max(start_minute, self._minute(self._now()))
        if end_minute <= start_minute:
            raise ValidationError("end_time must be after start_time.")
        return start_minute, end_minute

    async def _zone_name(self, permit_guid: str, zone_id: str | None) -> str:
        """Return the name of the zone to park in; ``None`` selects the default zone."""
        zones = await self._permit_zones(permit_guid)
        if not zones:
            raise ProviderError("The permit has no zones to park in.")
        if zone_id is None:
            # DESIGN DECISION D1 (see README "Design decisions"): the default zone is the
            # first one in the order of ``_permit_zones``.
            return self._zone_id(zones[0])
        for zone in zones:
            if self._zone_id(zone) == zone_id:
                return zone_id
        raise ValidationError("zone_id is not a zone of the permit.")

    async def _find_action(self, reservation_id: str, *, active_only: bool) -> MendixObject:
        active = " and Eindtijd > '[%CurrentDateTime%]'" if active_only else ""
        rows = await self._retrieve(
            f"//{ENTITY_PARKING_ACTION}[_Id = '{reservation_id}' and IsGeannuleerd = false(){active}]",
            operation="retrieve_reservation",
        )
        if not rows:
            raise ValidationError("reservation_id was not found.")
        return rows[0]

    async def _reread_reservation(self, reservation_id: str) -> Reservation:
        row = await self._find_action(reservation_id, active_only=False)
        return self._map_reservation(row)

    async def _authorization_for(self, action: MendixObject) -> MendixObject:
        """Return the account's authorization for the permit a reservation belongs to."""
        permit_guid = xpath_guid(action.text(ASSOC_ACTION_PERMIT), "permit reference")
        for authorization in await self._load_authorizations():
            if authorization.text(ASSOC_AUTHORIZATION_PERMIT) == permit_guid:
                return authorization
        raise ProviderError("No permit authorization found for this reservation.")

    def _values_from_action(self, action: MendixObject) -> dict[str, Any]:
        """Build the helper values the portal derives from an existing parking action."""
        return {
            "_Id": action.text("_Id"),
            "ParksaverId": action.text("ParksaverId"),
            "ZoneDisplayNaam": action.text("ZoneNaam"),
            "Kenteken": action.text("Kenteken"),
            "KentekenOmschrijving": action.text("KentekenOmschrijving"),
            "Landcode": action.text("Landcode"),
            "Starttijd": action.value("Starttijd"),
            "Eindtijd": action.value("Eindtijd"),
            "Kosten": action.value("Parkeerkosten"),
            "Eenheden": action.value("Eenheden"),
        }

    async def _submit_action(
        self,
        operation: str,
        authorization: MendixObject,
        values: Mapping[str, Any],
        *,
        plate: str,
        preview_cost: bool,
    ) -> dict[str, Any]:
        """Run a parking action microflow the way the web client does and check its result."""
        authorization_id = self._authorization_id(authorization)
        helper = await self._instantiate(ENTITY_PARKING_ACTION_HELPER)
        result = await self._instantiate(ENTITY_API_RESULT)
        helper_guid = str(helper["guid"])
        result_guid = str(result["guid"])
        changes = _values(values)
        if preview_cost:
            # The web client prices the action before saving it; mirror that so the
            # helper carries the same cost fields.
            cost = await self._call_operation(
                OPERATION_ACTION_COST,
                {
                    "ParkeeractieHelper": {"guid": helper_guid},
                    "MachtigingId": {"value": authorization_id},
                },
                {helper_guid: changes},
                [helper],
            )
            server_changes = cost.get("changes")
            if isinstance(server_changes, Mapping):
                helper_changes = server_changes.get(helper_guid)
                if isinstance(helper_changes, Mapping):
                    changes = {**changes, **helper_changes}
        data = await self._call_operation(
            operation,
            {
                "ParkeeractieHelper": {"guid": helper_guid},
                "Kanaal": {"value": CHANNEL},
                "APIResultaat": {"guid": result_guid},
                "MachtigingId": {"value": authorization_id},
            },
            {helper_guid: changes},
            [helper, result],
        )
        self._ensure_action_succeeded(data, result_guid, plate)
        return data

    def _ensure_action_succeeded(
        self, data: Mapping[str, Any], result_guid: str, plate: str
    ) -> None:
        changes = data.get("changes")
        entry = changes.get(result_guid) if isinstance(changes, Mapping) else None
        if not isinstance(entry, Mapping):
            raise ProviderError("Provider did not confirm the parking action.")
        flag = entry.get("isSuccess")
        if isinstance(flag, Mapping) and flag.get("value") is True:
            return
        message = None
        for key in ("FoutberichtEN", "Foutbericht"):
            candidate = entry.get(key)
            if isinstance(candidate, Mapping) and isinstance(candidate.get("value"), str):
                message = candidate["value"]
                break
        detail = None
        if message:
            # The provider message is free text; keep the plate out of it.
            detail = (
                " ".join(message.replace(plate, "***").split())[:_MAX_DETAIL_CHARS]
                if plate
                else message
            )
        raise ProviderError(
            "Provider rejected the parking action.",
            error_code="provider_rejected",
            detail=detail,
        )

    async def _created_reservation(
        self,
        data: Mapping[str, Any],
        permit_guid: str,
        *,
        plate: str,
        start_dt: datetime,
        end_dt: datetime,
    ) -> Reservation:
        for item in parse_objects(data):
            if item.entity == ENTITY_PARKING_ACTION:
                return self._map_reservation(item)
        # The response did not echo the new action: find the closest match instead.
        rows = await self._retrieve(
            f"//{ENTITY_PARKING_ACTION}[Kenteken = '{plate}' and IsGeannuleerd = false()"
            f" and Eindtijd > '[%CurrentDateTime%]' and {ASSOC_ACTION_PERMIT} = '{permit_guid}']",
            operation="retrieve_reservation",
        )
        target_start = milliseconds_from_datetime(start_dt)
        target_end = milliseconds_from_datetime(end_dt)
        best: MendixObject | None = None
        best_distance: int | None = None
        for row in rows:
            distance = abs(parse_integer(row.value("Starttijd")) - target_start) + abs(
                parse_integer(row.value("Eindtijd")) - target_end
            )
            if best_distance is None or distance < best_distance:
                best, best_distance = row, distance
        if best is None:
            raise ProviderError("Provider accepted the reservation but did not return it.")
        return self._map_reservation(best)

    def _map_reservation(self, action: MendixObject) -> Reservation:
        reservation_id = self._coerce_response_id(action.text("_Id"), "reservation id")
        plate = self._plate_from_response(action.text("Kenteken"))
        start = datetime_from_milliseconds(action.value("Starttijd"))
        end = datetime_from_milliseconds(action.value("Eindtijd"))
        if start is None or end is None:
            raise ProviderError("Provider response included invalid reservation data.")
        return Reservation(
            id=reservation_id,
            name=action.text("KentekenOmschrijving") or plate,
            license_plate=plate,
            start_time=self._format_utc_timestamp(start),
            end_time=self._format_utc_timestamp(end),
            zone_id=action.text("ZoneNaam"),
        )

    # ------------------------------------------------------------------
    # Favorites (saved license plates)
    # ------------------------------------------------------------------

    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""
        self._plogger.operation_started("list_favorites")
        favorites = [self._map_favorite(item) for item in await self._retrieve_plates()]
        self._plogger.operation_completed("list_favorites", count=len(favorites))
        return favorites

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""
        self._plogger.operation_started("add_favorite")
        plate = self._normalize_license_plate(license_plate)
        landcode = self._landcode(plate)
        existing = await self._retrieve_plates()
        if any(self._plate_from_response(item.text("Kenteken")) == plate for item in existing):
            raise ValidationError("license_plate is already a favorite.")
        saved = await self._save_plate(
            favorite_id=None,
            plate=plate,
            landcode=landcode,
            name=name or plate,
            is_default=False,
        )
        self._plogger.operation_completed("add_favorite")
        return self._map_favorite(saved)

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Native favorite update implementation."""
        favorite_id_value = xpath_opaque_id(
            self._require_id(favorite_id, "favorite_id"), "favorite_id"
        )
        if license_plate is None and name is None:
            raise ValidationError("license_plate or name is required.")
        plates = await self._retrieve_plates()
        existing = self._find_plate(plates, favorite_id_value)
        plate = (
            self._normalize_license_plate(license_plate)
            if license_plate is not None
            else self._plate_from_response(existing.text("Kenteken"))
        )
        if any(
            item.text("_Id") != favorite_id_value
            and self._plate_from_response(item.text("Kenteken")) == plate
            for item in plates
        ):
            raise ValidationError("license_plate is already a favorite.")
        saved = await self._save_plate(
            favorite_id=favorite_id_value,
            plate=plate,
            landcode=self._landcode(plate),
            name=name or existing.text("Omschrijving") or plate,
            is_default=existing.value("IsFavoriet") is True,
        )
        return self._map_favorite(saved)

    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
        self._plogger.operation_started("remove_favorite")
        favorite_id_value = xpath_opaque_id(
            self._require_id(favorite_id, "favorite_id"), "favorite_id"
        )
        existing = self._find_plate(await self._retrieve_plates(), favorite_id_value)
        plate = self._plate_from_response(existing.text("Kenteken"))
        helper = await self._instantiate(ENTITY_PLATE_HELPER)
        helper_guid = str(helper["guid"])
        await self._call_operation(
            OPERATION_PLATE_DELETE,
            {"KentekenHelper": {"guid": helper_guid}},
            {
                helper_guid: _values(
                    {
                        "_Id": favorite_id_value,
                        "Landcode": existing.text("Landcode") or self._landcode(plate),
                        "Kenteken": existing.text("Kenteken"),
                        "Omschrijving": existing.text("Omschrijving"),
                        "IsFavoriet": existing.value("IsFavoriet") is True,
                    }
                )
            },
            [helper],
        )
        self._plogger.operation_completed("remove_favorite")

    async def _retrieve_plates(self) -> list[MendixObject]:
        rows = await self._retrieve(
            f"//{ENTITY_PLATE}[IsVerwijderd = false() and {ASSOC_PLATE_ACCOUNT} = '[%CurrentUser%]']",
            operation="retrieve_favorites",
        )
        rows.sort(
            key=lambda item: ((item.text("Omschrijving") or "").lower(), item.text("_Id") or "")
        )
        return rows

    def _find_plate(self, plates: list[MendixObject], favorite_id: str) -> MendixObject:
        for item in plates:
            if item.text("_Id") == favorite_id:
                return item
        raise ValidationError("favorite_id was not found.")

    async def _save_plate(
        self,
        *,
        favorite_id: str | None,
        plate: str,
        landcode: str,
        name: str,
        is_default: bool,
    ) -> MendixObject:
        """Create or update a saved plate and return the stored object."""
        helper = await self._instantiate(ENTITY_PLATE_HELPER)
        helper_guid = str(helper["guid"])
        data = await self._call_operation(
            OPERATION_PLATE_SAVE,
            {"KentekenHelper": {"guid": helper_guid}},
            {
                helper_guid: _values(
                    {
                        "_Id": favorite_id or "",
                        "Landcode": landcode,
                        "Kenteken": plate,
                        "Omschrijving": name,
                        "IsFavoriet": is_default,
                    }
                )
            },
            [helper],
        )
        for item in parse_objects(data):
            if item.entity == ENTITY_PLATE:
                return item
        raise ProviderError("Provider did not confirm the saved license plate.")

    def _map_favorite(self, item: MendixObject) -> Favorite:
        plate = self._plate_from_response(item.text("Kenteken"))
        return Favorite(
            id=self._coerce_response_id(item.text("_Id"), "favorite id"),
            name=item.text("Omschrijving") or plate,
            license_plate=plate,
        )

    # ------------------------------------------------------------------
    # License plates
    # ------------------------------------------------------------------

    def _landcode(self, plate: str) -> str:
        """Return the portal's country class for a normalized plate.

        The portal distinguishes Dutch plates (exactly six characters) from foreign plates
        (up to ten characters).
        """
        if len(plate) == NL_PLATE_LENGTH:
            return LANDCODE_NL
        if len(plate) <= EU_PLATE_MAX_LENGTH:
            return LANDCODE_EU
        raise ValidationError(f"license_plate may have at most {EU_PLATE_MAX_LENGTH} characters.")

    def _plate_from_response(self, raw: str | None) -> str:
        if raw is None:
            raise ProviderError("Provider response missing license plate.")
        try:
            return self._normalize_license_plate(raw)
        except ValidationError as exc:
            raise ProviderError("Provider response included an invalid license plate.") from exc
