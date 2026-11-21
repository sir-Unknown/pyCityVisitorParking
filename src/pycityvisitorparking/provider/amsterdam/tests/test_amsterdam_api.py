from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pycityvisitorparking.exceptions import (
    AuthError,
    ErrorCode,
    ProviderError,
    ServiceUnavailableError,
    ValidationError,
)
from pycityvisitorparking.models import BALANCE_UNIT_MINUTE, ReservationTarget
from pycityvisitorparking.provider.amsterdam.api import Provider
from pycityvisitorparking.provider.loader import ProviderManifest


def _token(payload: dict[str, Any]) -> str:
    def encode(value: dict[str, Any]) -> str:
        raw = json.dumps(value).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode(payload)}.sig"


LOGIN_RESPONSE = {"token": _token({"client_product_id": 42, "roles": ["ROLE_SSP"]})}
CLIENT_PRODUCT = {
    "client_product_id": 42,
    "config": {"can_select_zone": True},
    "ssp": {"favorite_machine_number": 1111, "main_account": {"time_balance": 600}},
}
STARTED_SESSION = {
    "parking_session_id": 9,
    "vrn": "AB12CD",
    "started_at": "2030-01-01T10:00:00+00:00",
    "ended_at": "2030-01-01T11:00:00+00:00",
}


class _FakeResponse:
    def __init__(self, payload: Any, *, status: int = 200) -> None:
        self.status = status
        self._payload = payload
        self.headers: dict[str, str] = {"Content-Type": "application/json"}

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return json.dumps(self._payload)


class _FakeRequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _RoutedSession:
    """Serve queued responses per (method, path-suffix) and record every call."""

    def __init__(self, routes: dict[tuple[str, str], list[_FakeResponse]]) -> None:
        self._routes = routes
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeRequestContext:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        for (route_method, suffix), queue in self._routes.items():
            if method == route_method and url.endswith(suffix):
                return _FakeRequestContext(queue.pop(0) if len(queue) > 1 else queue[0])
        raise AssertionError(f"Unexpected request {method} {url}")

    def calls_to(self, suffix: str) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["url"].endswith(suffix)]


def _provider(session: _RoutedSession) -> Provider:
    return Provider(
        session,  # type: ignore[arg-type]
        ProviderManifest(
            id="amsterdam",
            name="Amsterdam",
            favorite_update_fields=(),
            reservation_update_fields=("end_time",),
            balance_units=("MINUTE", "EURO"),
            reservation_target_selection="free_input",
        ),
        base_url="https://example",
    )


def _routes(**overrides: list[_FakeResponse]) -> dict[tuple[str, str], list[_FakeResponse]]:
    routes: dict[tuple[str, str], list[_FakeResponse]] = {
        ("POST", "/api/ssp/login_check"): [_FakeResponse(LOGIN_RESPONSE)],
        ("GET", "/api/v1/client_product/42"): [_FakeResponse(CLIENT_PRODUCT)],
        ("POST", "/api/v1/ssp/parking_session/start"): [_FakeResponse(STARTED_SESSION)],
        ("POST", "/api/v1/ssp/parking_session/cost_calculator"): [
            _FakeResponse({"time_frame_data": []})
        ],
        ("GET", "/api/v1/ssp/parking_session/list"): [
            _FakeResponse({"data": [{**STARTED_SESSION, "status": "ACTIVE", "can_edit": True}]})
        ],
        ("PATCH", "/api/v1/ssp/parking_session/9/edit"): [_FakeResponse(STARTED_SESSION)],
        ("GET", "/api/v1/ssp/favorite_vrn/list"): [_FakeResponse({"favorite_vrns": []})],
    }
    for key, value in overrides.items():
        method, suffix = key.split("|")
        routes[(method, suffix)] = value
    return routes


def _times() -> tuple[datetime, datetime]:
    start = datetime(2030, 1, 1, 10, tzinfo=UTC)
    return start, start + timedelta(hours=1)


async def test_start_reservation_uses_favorite_machine_by_default() -> None:
    session = _RoutedSession(_routes())
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    await provider.start_reservation("ab-12-cd", *_times())

    payload = session.calls_to("/parking_session/start")[0]["kwargs"]["json"]
    assert payload["machine_number"] == 1111
    assert "is_new_favorite_machine_number" not in payload


async def test_permit_without_zone_selection_sends_no_machine() -> None:
    product = {"client_product_id": 42, "config": {"can_select_zone": False}, "ssp": {}}
    session = _RoutedSession(_routes(**{"GET|/api/v1/client_product/42": [_FakeResponse(product)]}))
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    await provider.get_permit()
    await provider.start_reservation("ab-12-cd", *_times())

    start_payload = session.calls_to("/parking_session/start")[0]["kwargs"]["json"]
    cost_payload = session.calls_to("/parking_session/cost_calculator")[0]["kwargs"]["json"]
    for payload in (start_payload, cost_payload):
        assert "machine_number" not in payload
        assert "zone_id" not in payload


async def test_get_permit_reports_minutes_and_uses_one_cost_calculation() -> None:
    session = _RoutedSession(_routes())
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    permit = await provider.get_permit()

    assert permit.remaining_balance == 10
    assert permit.balance_unit == BALANCE_UNIT_MINUTE
    assert len(session.calls_to("/parking_session/cost_calculator")) == 1


async def test_start_before_permit_validity_moves_to_validity_start() -> None:
    product = {**CLIENT_PRODUCT, "validity": {"started_at": "2030-01-01T12:00:00+00:00"}}
    session = _RoutedSession(_routes(**{"GET|/api/v1/client_product/42": [_FakeResponse(product)]}))
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    start = datetime(2030, 1, 1, 10, tzinfo=UTC)
    await provider.start_reservation("ab-12-cd", start, start + timedelta(hours=4))

    payload = session.calls_to("/parking_session/start")[0]["kwargs"]["json"]
    assert payload["started_at"] == "Tue, 01 Jan 2030 12:00:00 GMT"


async def test_change_of_session_without_can_edit_is_rejected_before_patch() -> None:
    locked = {**STARTED_SESSION, "status": "ACTIVE", "can_edit": False}
    session = _RoutedSession(
        _routes(**{"GET|/api/v1/ssp/parking_session/list": [_FakeResponse({"data": [locked]})]})
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(ProviderError) as exc_info:
        await provider.end_reservation("9", datetime(2030, 1, 1, 10, 30, tzinfo=UTC))

    assert exc_info.value.error_code == ErrorCode.PROVIDER_REJECTED
    assert session.calls_to("/edit") == []


async def test_end_reservation_patches_editable_session() -> None:
    session = _RoutedSession(_routes())
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    await provider.end_reservation("9", datetime(2030, 1, 1, 10, 30, tzinfo=UTC))

    patch = session.calls_to("/parking_session/9/edit")[0]["kwargs"]["json"]
    assert patch == {"new_ended_at": "2030-01-01T10:30:00+00:00"}


@pytest.mark.parametrize("response", [{"parking_session_id": 9}, {"code": 201}])
async def test_start_reservation_reads_back_a_session_missing_from_the_response(
    response: dict[str, Any],
) -> None:
    session = _RoutedSession(
        _routes(**{"POST|/api/v1/ssp/parking_session/start": [_FakeResponse(response)]})
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    reservation = await provider.start_reservation("ab-12-cd", *_times())

    assert reservation.id == "9"
    assert reservation.license_plate == "AB12CD"
    assert reservation.end_time == "2030-01-01T11:00:00Z"


async def test_end_reservation_without_session_in_response_keeps_the_read_session() -> None:
    session = _RoutedSession(
        _routes(**{"PATCH|/api/v1/ssp/parking_session/9/edit": [_FakeResponse({"code": 200})]})
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    reservation = await provider.end_reservation("9", datetime(2030, 1, 1, 10, 30, tzinfo=UTC))

    assert reservation.id == "9"
    assert reservation.license_plate == "AB12CD"
    assert reservation.end_time == "2030-01-01T10:30:00Z"


async def test_add_favorite_reads_back_a_favorite_missing_from_the_response() -> None:
    listed = {"favorite_vrns": [{"id": 17, "vrn": "AB12CD", "description": "Family"}]}
    session = _RoutedSession(
        _routes(
            **{
                "POST|/api/v1/ssp/favorite_vrn/add": [_FakeResponse({"code": 201, "id": 17})],
                "GET|/api/v1/ssp/favorite_vrn/list": [_FakeResponse(listed)],
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    favorite = await provider.add_favorite("ab-12-cd", "Family")

    assert (favorite.id, favorite.license_plate, favorite.name) == ("17", "AB12CD", "Family")


async def _start_at(provider: Provider, target: str | None) -> None:
    await provider.start_reservation("ab-12-cd", *_times(), reservation_target_id=target)


async def test_default_machine_is_the_only_listed_target() -> None:
    session = _RoutedSession(_routes())
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    assert await provider.list_reservation_targets() == [ReservationTarget(id="1111", name="1111")]
    assert provider.info.reservation_target_selection == "free_input"


async def test_fetch_all_gives_the_default_target_the_permit_paid_hours() -> None:
    weekly = {"time_frame_data": [[{"startTime": "0900", "endTime": "2100"}] for _ in range(7)]}
    session = _RoutedSession(
        _routes(**{"POST|/api/v1/ssp/parking_session/cost_calculator": [_FakeResponse(weekly)]})
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    permit, _reservations, _favorites, targets = await provider.fetch_all()

    assert len(permit.paid_hours) == 15
    assert [target.id for target in targets] == ["1111"]
    assert targets[0].paid_hours == permit.paid_hours
    assert len(session.calls_to("/parking_session/cost_calculator")) == 1


def _weekly(start: str, end: str) -> _FakeResponse:
    return _FakeResponse({"time_frame_data": [[{"startTime": start, "endTime": end}]] * 7})


async def test_another_machine_target_has_its_own_paid_hours() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "POST|/get_by_machine_number": [_FakeResponse({"zone": {"zone_id": 77}})],
                "POST|/api/v1/ssp/parking_session/cost_calculator": [_weekly("0900", "2100")],
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    target = await provider.get_reservation_target(" 2222 ")

    assert target.id == "2222"
    assert len(target.paid_hours) == 15
    assert session.calls_to("/get_by_machine_number")[0]["kwargs"]["json"]["machine_number"] == 2222
    cost_payload = session.calls_to("/parking_session/cost_calculator")[0]["kwargs"]["json"]
    assert cost_payload["machine_number"] == 2222


async def test_unknown_machine_cannot_be_resolved_as_target() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "POST|/get_by_machine_number": [
                    _FakeResponse({"message": "This parking machine does not exist."}, status=400)
                ]
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(ValidationError):
        await provider.get_reservation_target("9999")
    assert session.calls_to("/parking_session/cost_calculator") == []


async def test_machines_of_open_sessions_are_listed_with_their_paid_hours() -> None:
    at_other_machine = {**STARTED_SESSION, "status": "ACTIVE", "machine_number": 2222}
    session = _RoutedSession(
        _routes(
            **{
                "GET|/api/v1/ssp/parking_session/list": [
                    _FakeResponse({"data": [at_other_machine]})
                ],
                # Default machine first, then machine 2222; later calls reuse the last.
                "POST|/api/v1/ssp/parking_session/cost_calculator": [
                    _weekly("0900", "0000"),
                    _weekly("0900", "2100"),
                ],
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    permit, _reservations, _favorites, targets = await provider.fetch_all()
    await provider.fetch_all()

    assert [target.id for target in targets] == ["1111", "2222"]
    assert targets[0].paid_hours == permit.paid_hours
    assert targets[1].paid_hours != permit.paid_hours
    machines = [
        call["kwargs"]["json"]["machine_number"]
        for call in session.calls_to("/parking_session/cost_calculator")
    ]
    # Machine 2222 is fetched once per day; the default machine on every refresh.
    assert machines == [1111, 2222, 1111]


async def test_permit_without_zone_selection_has_no_targets_and_rejects_one() -> None:
    product = {"client_product_id": 42, "config": {"can_select_zone": False}, "ssp": {}}
    session = _RoutedSession(_routes(**{"GET|/api/v1/client_product/42": [_FakeResponse(product)]}))
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    assert await provider.list_reservation_targets() == []
    with pytest.raises(ValidationError):
        await _start_at(provider, "2222")
    assert session.calls_to("/parking_session/start") == []


async def test_other_machine_target_resolves_zone_and_keeps_the_default() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "POST|/get_by_machine_number": [
                    _FakeResponse({"zone": {"zone_id": 77, "zone_description": "Zone"}})
                ]
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    await _start_at(provider, " 2222 ")
    await provider.get_permit()

    zone_lookup = session.calls_to("/get_by_machine_number")[0]["kwargs"]["json"]
    assert zone_lookup == {"client_product_id": 42, "machine_number": 2222}
    start_payload = session.calls_to("/parking_session/start")[0]["kwargs"]["json"]
    assert start_payload["machine_number"] == 2222
    assert start_payload["zone_id"] == 77
    assert start_payload["is_new_favorite_machine_number"] is False
    cost_payload = session.calls_to("/parking_session/cost_calculator")[0]["kwargs"]["json"]
    assert cost_payload["machine_number"] == 1111


async def test_default_machine_as_target_needs_no_zone_lookup() -> None:
    session = _RoutedSession(_routes())
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    await _start_at(provider, "1111")

    payload = session.calls_to("/parking_session/start")[0]["kwargs"]["json"]
    assert payload["machine_number"] == 1111
    assert "is_new_favorite_machine_number" not in payload


def test_reservation_maps_its_machine_to_the_target() -> None:
    provider = _provider(_RoutedSession({}))

    reservation = provider._map_reservation({**STARTED_SESSION, "machine_number": 2222})

    assert reservation.reservation_target_id == "2222"


@pytest.mark.parametrize(
    "message",
    [
        "This parking machine does not exist.",
        "The chosen parking machine is not within the allowed zones.",
    ],
)
async def test_unknown_machine_target_is_validation_error(message: str) -> None:
    session = _RoutedSession(
        _routes(
            **{"POST|/get_by_machine_number": [_FakeResponse({"message": message}, status=400)]}
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(ValidationError):
        await _start_at(provider, "9999")
    assert session.calls_to("/parking_session/start") == []


@pytest.mark.parametrize("value", ["abc", "0", "-5", "12.5", "١٢"])
async def test_malformed_machine_target_is_rejected_before_any_request(value: str) -> None:
    session = _RoutedSession(_routes())
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})
    calls_after_login = len(session.calls)

    with pytest.raises(ValidationError):
        await _start_at(provider, value)

    assert len(session.calls) == calls_after_login


async def test_other_provider_error_for_machine_lookup_is_not_masked() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "POST|/get_by_machine_number": [
                    _FakeResponse({"message": "Something went wrong."}, status=400)
                ]
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(ProviderError) as exc_info:
        await _start_at(provider, "2222")

    assert not isinstance(exc_info.value, ValidationError)
    assert exc_info.value.error_code == ErrorCode.PROVIDER_REJECTED


async def test_unavailable_parking_register_is_service_unavailable() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "POST|/get_by_machine_number": [
                    _FakeResponse({"message": "NPR is unavailable."}, status=400)
                ]
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await _start_at(provider, "2222")

    assert exc_info.value.error_code == ErrorCode.SERVICE_UNAVAILABLE


async def test_expired_token_reauthenticates_once() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "GET|/api/v1/client_product/42": [
                    _FakeResponse({}, status=401),
                    _FakeResponse(CLIENT_PRODUCT),
                ],
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    await provider.get_permit()

    assert len(session.calls_to("/login_check")) == 2


async def test_persistent_unauthorized_response_raises_auth_error() -> None:
    session = _RoutedSession(
        _routes(**{"GET|/api/v1/client_product/42": [_FakeResponse({}, status=401)]})
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(AuthError):
        await provider.get_permit()

    assert len(session.calls_to("/login_check")) == 2


async def test_unsupported_updates_carry_not_supported_code() -> None:
    provider = _provider(_RoutedSession({}))

    with pytest.raises(ProviderError) as exc_info:
        await provider.update_favorite("1", name="x")

    assert exc_info.value.error_code == ErrorCode.NOT_SUPPORTED
