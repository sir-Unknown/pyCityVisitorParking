"""Tests for the Rotterdam provider using a scripted fake portal (no live calls)."""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pycityvisitorparking.exceptions import (
    AuthError,
    NotFoundError,
    ProviderError,
    ValidationError,
)
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.provider.rotterdam.api import Provider
from pycityvisitorparking.provider.rotterdam.mendix import find_operation_id

NOW = datetime(2026, 3, 15, 10, 20, 45, tzinfo=UTC)


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _microflow_call(operation_id: str, *names: str) -> dict[str, Any]:
    return {
        "type": "tryCatch",
        "body": [
            {
                "type": "microflowCall",
                "operationId": operation_id,
                "parameters": [{"name": name} for name in names],
            }
        ],
    }


_ACTION_PARAMS = ("ParkeeractieHelper", "Kanaal", "APIResultaat", "MachtigingId")
_NANOFLOWS = {
    "Parkeren.KentekenOpslaan": {
        "instructions": [_microflow_call("OP_PLATE_SAVE", "KentekenHelper")]
    },
    "Parkeren.KentekenVerwijderen": {
        "instructions": [_microflow_call("OP_PLATE_DELETE", "KentekenHelper")]
    },
    "Parkeren.ParkeeractieStarten": {"instructions": [_microflow_call("OP_SAVE", *_ACTION_PARAMS)]},
    "Parkeren.ParkeeractieGeplandAnnuleren": {
        "instructions": [_microflow_call("OP_CANCEL", *_ACTION_PARAMS)]
    },
    "Parkeren.ParkeerkostenBerekening": {
        "instructions": [_microflow_call("OP_COST", "ParkeeractieHelper", "MachtigingId")]
    },
}
PAGE_XML = (
    "\ufeff<?xml version='1.0' encoding='utf-8'?><m:page><m:nanoflows>"
    + html.escape(json.dumps(_NANOFLOWS), quote=True)
    + "</m:nanoflows></m:page>"
)


def _obj(entity: str, guid: str, attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        "objectType": entity,
        "guid": guid,
        "attributes": {
            name: {"readonly": True, "value": value} for name, value in attributes.items()
        },
    }


def _authorization(
    guid: str = "100",
    *,
    permit_guid: str = "200",
    permit_type: str = "Bezoekersvergunning",
    description: str = "Permit",
) -> dict[str, Any]:
    return _obj(
        "Parkeren.Machtiging",
        guid,
        {
            "_Id": f"auth-{guid}",
            "Status": "Actief",
            "VergunningType": permit_type,
            "Omschrijving": description,
            "Parkeren.Machtiging_Vergunning": permit_guid,
        },
    )


def _action(
    action_id: str,
    plate: str,
    start: datetime,
    end: datetime,
    *,
    permit_guid: str = "200",
    name: str | None = None,
) -> dict[str, Any]:
    return _obj(
        "Parkeren.Parkeeractie",
        f"guid-{action_id}",
        {
            "_Id": action_id,
            "Kenteken": plate,
            "KentekenOmschrijving": name,
            "Landcode": "NL",
            "ZoneNaam": "Zone A",
            "Starttijd": _ms(start),
            "Eindtijd": _ms(end),
            "IsGeannuleerd": False,
            "Parkeren.Parkeeractie_Vergunning": permit_guid,
        },
    )


def _plate(plate_id: str, plate: str, name: str, *, favorite: bool = False) -> dict[str, Any]:
    return _obj(
        "Parkeren.Kenteken",
        f"guid-{plate_id}",
        {
            "_Id": plate_id,
            "Kenteken": plate,
            "Omschrijving": name,
            "Landcode": "NL",
            "IsFavoriet": favorite,
            "IsVerwijderd": False,
        },
    )


class _Response:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self._payload = payload

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)


class _Context:
    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> _Response:
        return self._response

    async def __aexit__(self, *_exc_info: object) -> bool:
        return False


class _Portal:
    """Scripted stand-in for the Mendix runtime."""

    def __init__(self) -> None:
        self.xpath_results: list[tuple[str, list[dict[str, Any]]]] = []
        self.zone_objects: list[dict[str, Any]] = []
        self.operations: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self.requests: list[dict[str, Any]] = []
        self.xpaths: list[str] = []
        self.login_status = 200
        self.expire_session_once = False
        self.logins = 0
        self._guid = 9000

    def request(self, method: str, url: str, **kwargs: Any) -> _Context:
        headers = kwargs.get("headers") or {}
        if method == "GET":
            self.requests.append({"url": url})
            return _Context(_Response(200, PAGE_XML))
        body = json.loads(kwargs["data"])
        self.requests.append({"url": url, "body": body, "headers": headers})
        return _Context(self._handle(body, headers))

    def _handle(self, body: dict[str, Any], headers: dict[str, str]) -> _Response:
        action = body["action"]
        if action == "get_session_data":
            return _Response(
                200,
                {
                    "csrftoken": "anonymous-token",
                    "cachebust": "42",
                    "constants": [{"name": "Parkeren.MinutenPerEenheid", "value": "10"}],
                },
            )
        if action == "login":
            self.logins += 1
            if self.login_status != 200:
                return _Response(self.login_status, {})
            return _Response(200, {"csrftoken": f"session-token-{self.logins}"})
        if self.expire_session_once and headers.get("X-Csrf-Token") == "session-token-1":
            self.expire_session_once = False
            return _Response(401, {})
        if action == "retrieve_by_xpath":
            xpath = body["params"]["xpath"]
            self.xpaths.append(xpath)
            for needle, objects in self.xpath_results:
                if needle in xpath:
                    return _Response(200, {"objects": objects})
            return _Response(200, {"objects": []})
        if action == "retrieve_by_ids":
            return _Response(200, {"objects": self.zone_objects})
        if action == "instantiate":
            self._guid += 1
            guid = str(self._guid)
            entity = body["params"]["objecttype"]
            return _Response(
                200,
                {
                    "actionResult": guid,
                    "objects": [
                        {"objectType": entity, "guid": guid, "attributes": {}, "hash": "h"}
                    ],
                },
            )
        if action == "runtimeOperation":
            return _Response(200, self.operations[body["operationId"]](body))
        raise AssertionError(f"unexpected action {action}")

    def operation_calls(self, operation_id: str) -> list[dict[str, Any]]:
        return [
            request["body"]
            for request in self.requests
            if request.get("body", {}).get("operationId") == operation_id
        ]


def _provider(portal: _Portal) -> Provider:
    provider = Provider(
        portal,  # type: ignore[arg-type]
        ProviderManifest(
            id="rotterdam",
            name="Rotterdam",
            favorite_update_fields=("license_plate", "name"),
            reservation_update_fields=("start_time", "end_time"),
            zone_selection=True,
        ),
        base_url="https://portal.example",
    )
    provider._now = lambda: NOW  # type: ignore[method-assign]
    return provider


async def _logged_in(portal: _Portal) -> Provider:
    provider = _provider(portal)
    await provider.login({"username": "user@example.com", "password": "secret"})
    return provider


def _accepted(
    result_changes: dict[str, Any] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def respond(body: dict[str, Any]) -> dict[str, Any]:
        result_guid = body["params"]["APIResultaat"]["guid"]
        return {
            "changes": {result_guid: {"isSuccess": {"value": True}}},
            "objects": (result_changes or {}).get("objects", []),
        }

    return respond


def _cost(body: dict[str, Any]) -> dict[str, Any]:
    helper_guid = body["params"]["ParkeeractieHelper"]["guid"]
    return {"changes": {helper_guid: {"Kosten": {"value": "1"}, "Eenheden": {"value": "2"}}}}


# --- authentication -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_uses_signed_in_csrf_token_on_later_requests() -> None:
    portal = _Portal()
    provider = await _logged_in(portal)
    await provider.list_favorites()
    assert portal.requests[-1]["headers"]["X-Csrf-Token"] == "session-token-1"
    login_body = next(r["body"] for r in portal.requests if r["body"]["action"] == "login")
    assert login_body["params"] == {"username": "user@example.com", "password": "secret"}


@pytest.mark.asyncio
async def test_login_rejects_bad_credentials_and_missing_fields() -> None:
    portal = _Portal()
    portal.login_status = 401
    provider = _provider(portal)
    with pytest.raises(AuthError):
        await provider.login({"username": "user@example.com", "password": "wrong"})
    with pytest.raises(ValidationError):
        await provider.login({"username": "user@example.com"})


@pytest.mark.asyncio
async def test_expired_session_is_renewed_once_and_request_retried() -> None:
    portal = _Portal()
    provider = await _logged_in(portal)
    portal.expire_session_once = True
    portal.xpath_results = [("Parkeren.Kenteken", [_plate("p1", "AB12CD", "Car")])]
    favorites = await provider.list_favorites()
    assert [item.license_plate for item in favorites] == ["AB12CD"]
    assert portal.logins == 2


# --- permit -------------------------------------------------------------------------


def _permit_portal() -> _Portal:
    portal = _Portal()
    portal.xpath_results = [
        ("Parkeren.Machtiging", [_authorization()]),
        ("Parkeren.Saldo", [_obj("Parkeren.Saldo", "300", {"SaldoHuidig": "6"})]),
        (
            "Masterdata.ZoneVergunningRelatie",
            [
                _obj(
                    "Masterdata.ZoneVergunningRelatie",
                    "400",
                    {"Masterdata.ZoneVergunningRelatie_Zone": "500"},
                )
            ],
        ),
        (
            "Masterdata.Parkeertijd",
            [
                _obj(
                    "Masterdata.Parkeertijd",
                    "600",
                    {
                        "VanafTijd": _ms(NOW + timedelta(hours=2)),
                        "TotTijd": _ms(NOW + timedelta(hours=10)),
                    },
                ),
                _obj(
                    "Masterdata.Parkeertijd",
                    "601",
                    {
                        "VanafTijd": _ms(NOW + timedelta(hours=2)),
                        "TotTijd": _ms(NOW + timedelta(hours=10)),
                    },
                ),
                _obj(
                    "Masterdata.Parkeertijd",
                    "602",
                    {
                        "VanafTijd": _ms(NOW - timedelta(hours=1)),
                        "TotTijd": _ms(NOW + timedelta(hours=1)),
                    },
                ),
            ],
        ),
    ]
    portal.zone_objects = [
        _obj("Masterdata.Zone", "500", {"Naam": "Zone A", "TypeZone": "Zone", "isDeleted": False})
    ]
    return portal


@pytest.mark.asyncio
async def test_get_permit_converts_balance_units_to_minutes_and_sorts_windows() -> None:
    portal = _permit_portal()
    provider = await _logged_in(portal)
    permit = await provider.get_permit()
    assert permit.id == "auth-100"
    assert permit.remaining_balance == 60.0  # 6 units of 10 minutes
    assert permit.balance_unit == "MINUTE"
    # Duplicate windows collapse and the result is chronological, in UTC with a Z suffix.
    assert [(b.start_time, b.end_time) for b in permit.zone_validity] == [
        ("2026-03-15T09:20:45Z", "2026-03-15T11:20:45Z"),
        ("2026-03-15T12:20:45Z", "2026-03-15T20:20:45Z"),
    ]
    assert any("Parkeren.Saldo_Vergunning = '200' and Jaar = 2026" in x for x in portal.xpaths)


@pytest.mark.asyncio
async def test_business_hours_permit_reads_the_monthly_balance() -> None:
    portal = _permit_portal()
    portal.xpath_results[0] = (
        "Parkeren.Machtiging",
        [_authorization(permit_type="Bedrijfsurenvergunning")],
    )
    provider = await _logged_in(portal)
    await provider.get_permit()
    assert any(
        "Parkeren.SaldoZakelijk_Machtiging = '100' and Jaar = 2026 and Maand = 3" in x
        for x in portal.xpaths
    )


@pytest.mark.asyncio
async def test_missing_balance_row_reports_zero() -> None:
    portal = _permit_portal()
    portal.xpath_results = [item for item in portal.xpath_results if item[0] != "Parkeren.Saldo"]
    provider = await _logged_in(portal)
    assert (await provider.get_permit()).remaining_balance == 0.0


@pytest.mark.asyncio
async def test_get_permit_without_active_permit_raises_not_found() -> None:
    provider = await _logged_in(_Portal())
    with pytest.raises(NotFoundError):
        await provider.get_permit()


@pytest.mark.asyncio
async def test_fetch_all_selects_the_permit_once() -> None:
    portal = _permit_portal()
    portal.xpath_results.append(("Parkeren.Kenteken", [_plate("p1", "AB12CD", "Car")]))
    provider = await _logged_in(portal)
    permit, reservations, favorites = await provider.fetch_all()
    assert permit.id == "auth-100"
    assert reservations == []
    assert [item.id for item in favorites] == ["p1"]
    assert sum("Parkeren.Machtiging" in x for x in portal.xpaths) == 1


# --- reservations -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reservations_maps_plate_name_and_utc_times() -> None:
    portal = _permit_portal()
    portal.xpath_results.append(
        (
            "Parkeren.Parkeeractie",
            [
                _action("late", "ab-12-cd", NOW + timedelta(hours=3), NOW + timedelta(hours=4)),
                _action(
                    "now",
                    "XX99YY",
                    NOW - timedelta(minutes=5),
                    NOW + timedelta(hours=1),
                    name="Bakkie",
                ),
            ],
        )
    )
    provider = await _logged_in(portal)
    reservations = await provider.list_reservations()
    assert [(r.id, r.name, r.license_plate) for r in reservations] == [
        ("now", "Bakkie", "XX99YY"),
        ("late", "AB12CD", "AB12CD"),
    ]
    assert reservations[0].start_time == "2026-03-15T10:15:45Z"
    assert any("Parkeren.Parkeeractie_Vergunning = '200'" in x for x in portal.xpaths)


@pytest.mark.asyncio
async def test_start_reservation_prices_then_saves_like_the_web_client() -> None:
    portal = _permit_portal()
    portal.operations = {"OP_COST": _cost, "OP_SAVE": _accepted({"objects": []})}
    created = _action("new", "AB12CD", NOW.replace(second=0), NOW + timedelta(hours=1))
    portal.xpath_results.append(("Parkeren.Parkeeractie", [created]))
    provider = await _logged_in(portal)
    reservation = await provider.start_reservation("ab-12-cd", NOW, NOW + timedelta(hours=1))
    assert reservation.id == "new"
    assert reservation.license_plate == "AB12CD"
    assert reservation.zone_id == "Zone A"
    (cost_call,) = portal.operation_calls("OP_COST")
    (save_call,) = portal.operation_calls("OP_SAVE")
    assert cost_call["params"]["MachtigingId"] == {"value": "auth-100"}
    assert save_call["params"]["Kanaal"] == {"value": "WEB_APP"}
    helper_guid = save_call["params"]["ParkeeractieHelper"]["guid"]
    changes = save_call["changes"][helper_guid]
    assert changes["Kenteken"] == {"value": "AB12CD"}
    assert changes["Landcode"] == {"value": "NL"}
    assert changes["KentekenOmschrijving"] == {"value": "AB12CD"}
    assert changes["ZoneDisplayNaam"] == {"value": "Zone A"}
    # Seconds are dropped and a start in the past moves to the current minute.
    assert changes["Starttijd"] == {"value": _ms(NOW.replace(second=0))}
    assert changes["Eindtijd"] == {"value": _ms((NOW + timedelta(hours=1)).replace(second=0))}
    # Cost fields from the pricing call are carried into the save call.
    assert changes["Kosten"] == {"value": "1"}


@pytest.mark.asyncio
async def test_start_reservation_echoed_object_is_used_without_extra_lookup() -> None:
    portal = _permit_portal()
    echoed = _action("echo", "AB12CD", NOW, NOW + timedelta(hours=1))
    portal.operations = {"OP_COST": _cost, "OP_SAVE": _accepted({"objects": [echoed]})}
    provider = await _logged_in(portal)
    reservation = await provider.start_reservation(
        "AB12CD", NOW, NOW + timedelta(hours=1), "Bakkie"
    )
    assert reservation.id == "echo"
    assert sum("Parkeren.Parkeeractie" in x for x in portal.xpaths) == 0


@pytest.mark.asyncio
async def test_start_reservation_rejection_raises_without_leaking_the_plate() -> None:
    portal = _permit_portal()

    def reject(body: dict[str, Any]) -> dict[str, Any]:
        result_guid = body["params"]["APIResultaat"]["guid"]
        return {
            "changes": {
                result_guid: {
                    "isSuccess": {"value": False},
                    "FoutberichtEN": {"value": "Plate AB12CD has no balance"},
                }
            }
        }

    portal.operations = {"OP_COST": _cost, "OP_SAVE": reject}
    provider = await _logged_in(portal)
    with pytest.raises(ProviderError) as excinfo:
        await provider.start_reservation("AB12CD", NOW, NOW + timedelta(hours=1))
    assert excinfo.value.error_code == "provider_rejected"
    assert "AB12CD" not in (excinfo.value.detail or "")
    assert "no balance" in (excinfo.value.detail or "")


def _add_second_zone(portal: _Portal, name: str = "Zone 10") -> None:
    portal.zone_objects.insert(
        0,
        _obj("Masterdata.Zone", "501", {"Naam": name, "TypeZone": "Zone", "isDeleted": False}),
    )


def _save_zone(portal: _Portal) -> dict[str, Any]:
    (save_call,) = portal.operation_calls("OP_SAVE")
    helper_guid = save_call["params"]["ParkeeractieHelper"]["guid"]
    return save_call["changes"][helper_guid]["ZoneDisplayNaam"]


def _multi_zone_booking_portal() -> _Portal:
    portal = _permit_portal()
    _add_second_zone(portal)
    portal.operations = {"OP_COST": _cost, "OP_SAVE": _accepted({"objects": []})}
    portal.xpath_results.append(
        ("Parkeren.Parkeeractie", [_action("new", "AB12CD", NOW, NOW + timedelta(hours=1))])
    )
    return portal


@pytest.mark.asyncio
async def test_start_reservation_without_zone_id_uses_first_zone_by_name() -> None:
    portal = _multi_zone_booking_portal()
    provider = await _logged_in(portal)
    await provider.start_reservation("AB12CD", NOW, NOW + timedelta(hours=1))
    assert _save_zone(portal) == {"value": "Zone 10"}


@pytest.mark.asyncio
async def test_start_reservation_books_in_the_requested_zone() -> None:
    portal = _multi_zone_booking_portal()
    provider = await _logged_in(portal)
    await provider.start_reservation("AB12CD", NOW, NOW + timedelta(hours=1), zone_id="Zone A")
    assert _save_zone(portal) == {"value": "Zone A"}


@pytest.mark.asyncio
async def test_start_reservation_rejects_a_zone_outside_the_permit_before_saving() -> None:
    portal = _multi_zone_booking_portal()
    provider = await _logged_in(portal)
    with pytest.raises(ValidationError, match="zone_id"):
        await provider.start_reservation("AB12CD", NOW, NOW + timedelta(hours=1), zone_id="Zone B")
    assert portal.operation_calls("OP_COST") == []
    assert portal.operation_calls("OP_SAVE") == []


@pytest.mark.asyncio
async def test_zones_with_the_same_name_are_refused() -> None:
    portal = _permit_portal()
    _add_second_zone(portal, name="Zone A")
    provider = await _logged_in(portal)
    with pytest.raises(ProviderError, match="same name"):
        await provider.get_permit()


def _parking_times(zone_guid: str, windows: list[tuple[datetime, datetime]]) -> tuple:
    return (
        f"Masterdata.Parkeertijd_Zone = '{zone_guid}'",
        [
            _obj(
                "Masterdata.Parkeertijd",
                f"{zone_guid}-{index}",
                {"VanafTijd": _ms(start), "TotTijd": _ms(end)},
            )
            for index, (start, end) in enumerate(windows)
        ],
    )


def _utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.asyncio
async def test_get_permit_lists_each_zone_with_its_own_merged_windows() -> None:
    portal = _permit_portal()
    _add_second_zone(portal)
    day = (NOW + timedelta(days=1)).replace(hour=0, minute=0, second=0)
    hours = [day + timedelta(hours=offset) for offset in range(32)]
    portal.xpath_results = [
        # Zone 10: Friday 09:00-01:00 local is stored as overlapping rows split at midnight.
        _parking_times(
            "501",
            [(hours[8], hours[22]), (hours[8], hours[23]), (hours[23], hours[24])],
        ),
        _parking_times("500", [(hours[8], hours[22]), (hours[30], hours[31])]),
        *portal.xpath_results,
    ]
    provider = await _logged_in(portal)
    permit = await provider.get_permit()
    assert [(zone.id, zone.name) for zone in permit.zones] == [
        ("Zone 10", "Zone 10"),
        ("Zone A", "Zone A"),
    ]
    windows = {
        zone.id: [(b.start_time, b.end_time) for b in zone.zone_validity] for zone in permit.zones
    }
    assert windows == {
        "Zone 10": [(_utc(hours[8]), _utc(hours[24]))],
        "Zone A": [(_utc(hours[8]), _utc(hours[22])), (_utc(hours[30]), _utc(hours[31]))],
    }
    # The permit-level windows are those of the default zone.
    assert permit.zone_validity == permit.zones[0].zone_validity


@pytest.mark.asyncio
async def test_start_reservation_validates_input_before_any_request() -> None:
    provider = await _logged_in(_Portal())
    with pytest.raises(ValidationError):
        await provider.start_reservation(
            "AB12CD", datetime(2026, 3, 15, 11), NOW + timedelta(hours=2)
        )
    with pytest.raises(ValidationError):
        await provider.start_reservation("AB12CD", NOW + timedelta(hours=1), NOW)
    with pytest.raises(ValidationError):
        await provider.start_reservation("!!", NOW, NOW + timedelta(hours=1))


@pytest.mark.asyncio
async def test_update_reservation_cannot_move_the_start_of_a_running_reservation() -> None:
    portal = _permit_portal()
    running = _action("run", "AB12CD", NOW - timedelta(minutes=30), NOW + timedelta(hours=1))
    portal.xpath_results.append(("_Id = 'run'", [running]))
    provider = await _logged_in(portal)
    with pytest.raises(ValidationError, match="start_time"):
        await provider.update_reservation("run", start_time=NOW)
    with pytest.raises(ValidationError, match="name"):
        await provider.update_reservation("run", name="x")


@pytest.mark.asyncio
async def test_update_reservation_extends_the_end_and_rereads() -> None:
    portal = _permit_portal()
    running = _action("run", "AB12CD", NOW - timedelta(minutes=30), NOW + timedelta(hours=1))
    extended = _action("run", "AB12CD", NOW - timedelta(minutes=30), NOW + timedelta(hours=2))
    portal.operations = {"OP_COST": _cost, "OP_SAVE": _accepted()}
    portal.xpath_results.append(("_Id = 'run'", [running]))
    provider = await _logged_in(portal)
    new_end = (NOW + timedelta(hours=2)).replace(second=0)
    # After the save the portal reports the new end time.
    original = portal.operations["OP_SAVE"]

    def save_and_switch(body: dict[str, Any]) -> dict[str, Any]:
        portal.xpath_results[-1] = ("_Id = 'run'", [extended])
        return original(body)

    portal.operations["OP_SAVE"] = save_and_switch
    reservation = await provider.update_reservation("run", end_time=new_end)
    (save_call,) = portal.operation_calls("OP_SAVE")
    helper_guid = save_call["params"]["ParkeeractieHelper"]["guid"]
    changes = save_call["changes"][helper_guid]
    assert changes["_Id"] == {"value": "run"}
    assert changes["Eindtijd"] == {"value": _ms(new_end)}
    assert changes["Starttijd"] == {"value": _ms(NOW - timedelta(minutes=30))}
    assert reservation.end_time == "2026-03-15T12:20:45Z"


@pytest.mark.asyncio
async def test_end_reservation_stops_a_running_reservation_at_the_current_time() -> None:
    portal = _permit_portal()
    running = _action("run", "AB12CD", NOW - timedelta(minutes=30), NOW + timedelta(hours=1))
    portal.operations = {"OP_SAVE": _accepted()}
    portal.xpath_results.append(("_Id = 'run'", [running]))
    provider = await _logged_in(portal)
    # An end time in the past is moved to now; no pricing call is made for a stop.
    await provider.end_reservation("run", NOW - timedelta(hours=1))
    (save_call,) = portal.operation_calls("OP_SAVE")
    helper_guid = save_call["params"]["ParkeeractieHelper"]["guid"]
    assert save_call["changes"][helper_guid]["Eindtijd"] == {"value": _ms(NOW)}
    assert portal.operation_calls("OP_COST") == []


@pytest.mark.asyncio
async def test_end_reservation_cancels_a_planned_reservation() -> None:
    portal = _permit_portal()
    planned = _action("plan", "AB12CD", NOW + timedelta(hours=2), NOW + timedelta(hours=3))
    portal.operations = {"OP_CANCEL": _accepted()}
    portal.xpath_results.append(("_Id = 'plan'", [planned]))
    provider = await _logged_in(portal)
    reservation = await provider.end_reservation("plan", NOW)
    assert len(portal.operation_calls("OP_CANCEL")) == 1
    assert portal.operation_calls("OP_SAVE") == []
    assert reservation.id == "plan"


@pytest.mark.asyncio
async def test_reservation_id_cannot_inject_xpath() -> None:
    provider = await _logged_in(_permit_portal())
    with pytest.raises(ValidationError):
        await provider.end_reservation("x' or 1=1 or _Id = '", NOW)
    with pytest.raises(ValidationError, match="not found"):
        await provider.end_reservation("missing", NOW)


# --- favorites ----------------------------------------------------------------------


def _saved_plate_operation() -> Callable[[dict[str, Any]], dict[str, Any]]:
    def save(body: dict[str, Any]) -> dict[str, Any]:
        values = body["changes"][body["params"]["KentekenHelper"]["guid"]]
        stored = _plate(
            values["_Id"]["value"] or "new-id",
            values["Kenteken"]["value"],
            values["Omschrijving"]["value"],
            favorite=values["IsFavoriet"]["value"],
        )
        return {"objects": [stored]}

    return save


@pytest.mark.asyncio
async def test_add_favorite_picks_dutch_or_foreign_country_class() -> None:
    portal = _Portal()
    portal.operations = {"OP_PLATE_SAVE": _saved_plate_operation()}
    provider = await _logged_in(portal)
    favorite = await provider.add_favorite("ab-12-cd", "Car")
    assert (favorite.id, favorite.name, favorite.license_plate) == ("new-id", "Car", "AB12CD")
    await provider.add_favorite("ABCDEFGHI")
    first, second = portal.operation_calls("OP_PLATE_SAVE")
    assert first["changes"][first["params"]["KentekenHelper"]["guid"]]["Landcode"] == {
        "value": "NL"
    }
    assert first["changes"][first["params"]["KentekenHelper"]["guid"]]["_Id"] == {"value": ""}
    assert second["changes"][second["params"]["KentekenHelper"]["guid"]]["Landcode"] == {
        "value": "EU"
    }
    with pytest.raises(ValidationError, match="at most 10"):
        await provider.add_favorite("A" * 11)


@pytest.mark.asyncio
async def test_add_favorite_rejects_duplicates() -> None:
    portal = _Portal()
    portal.xpath_results = [("Parkeren.Kenteken", [_plate("p1", "AB12CD", "Car")])]
    provider = await _logged_in(portal)
    with pytest.raises(ValidationError, match="already"):
        await provider.add_favorite("ab 12 cd")


@pytest.mark.asyncio
async def test_update_favorite_keeps_id_and_default_flag() -> None:
    portal = _Portal()
    portal.xpath_results = [("Parkeren.Kenteken", [_plate("p1", "AB12CD", "Car", favorite=True)])]
    portal.operations = {"OP_PLATE_SAVE": _saved_plate_operation()}
    provider = await _logged_in(portal)
    favorite = await provider.update_favorite("p1", name="Renamed")
    assert (favorite.id, favorite.name, favorite.license_plate) == ("p1", "Renamed", "AB12CD")
    (call,) = portal.operation_calls("OP_PLATE_SAVE")
    values = call["changes"][call["params"]["KentekenHelper"]["guid"]]
    assert values["IsFavoriet"] == {"value": True}
    with pytest.raises(ValidationError, match="not found"):
        await provider.update_favorite("missing", name="x")


@pytest.mark.asyncio
async def test_remove_favorite_sends_the_stored_plate() -> None:
    portal = _Portal()
    portal.xpath_results = [("Parkeren.Kenteken", [_plate("p1", "AB12CD", "Car")])]
    portal.operations = {"OP_PLATE_DELETE": lambda _body: {}}
    provider = await _logged_in(portal)
    await provider.remove_favorite("p1")
    (call,) = portal.operation_calls("OP_PLATE_DELETE")
    values = call["changes"][call["params"]["KentekenHelper"]["guid"]]
    assert values["_Id"] == {"value": "p1"}
    assert values["Kenteken"] == {"value": "AB12CD"}
    with pytest.raises(ValidationError, match="not found"):
        await provider.remove_favorite("missing")


# --- operation discovery ------------------------------------------------------------


def test_find_operation_id_requires_an_unambiguous_parameter_match() -> None:
    nanoflows = {
        "Flow": {
            "instructions": [
                _microflow_call("A", "One"),
                _microflow_call("B", "One", "Two"),
            ]
        },
        "Dup": {"instructions": [_microflow_call("C", "One"), _microflow_call("D", "One")]},
    }
    page = "<m:nanoflows>" + html.escape(json.dumps(nanoflows)) + "</m:nanoflows>"
    assert find_operation_id(page, "Flow", frozenset({"One"})) == "A"
    assert find_operation_id(page, "Flow", frozenset({"One", "Two"})) == "B"
    assert find_operation_id(page, "Dup", frozenset({"One"})) is None
    assert find_operation_id(page, "Missing", frozenset({"One"})) is None
    assert find_operation_id("<page/>", "Flow", frozenset({"One"})) is None


@pytest.mark.asyncio
async def test_unresolvable_operation_raises_provider_error() -> None:
    portal = _Portal()
    provider = await _logged_in(portal)
    provider._pages["ParkerenWeb/KentekenToevoegenBewerken.page.xml"] = "<page/>"
    with pytest.raises(ProviderError, match="could not be resolved"):
        await provider.add_favorite("AB12CD")
