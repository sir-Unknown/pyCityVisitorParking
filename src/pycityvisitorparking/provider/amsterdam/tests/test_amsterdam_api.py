from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pycityvisitorparking.exceptions import AuthError, ProviderError, ValidationError
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
    "ssp": {"favorite_machine_number": 1111, "main_account": {"time_balance": 600}},
    "validity": {
        "started_at": "2024-01-01T08:00:00+01:00",
        "ended_at": "2024-01-01T18:00:00+01:00",
    },
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


async def test_machine_number_override_resolves_zone_and_survives_permit_refresh() -> None:
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
    await provider.login({"username": "u", "password": "p", "machine_number": " 2222 "})

    zone_lookup = session.calls_to("/get_by_machine_number")[0]["kwargs"]["json"]
    assert zone_lookup == {"client_product_id": 42, "machine_number": 2222}

    # get_permit re-reads the client product, whose favorite machine must not win.
    await provider.get_permit()
    await provider.start_reservation("ab-12-cd", *_times())

    start_payload = session.calls_to("/parking_session/start")[0]["kwargs"]["json"]
    assert start_payload["machine_number"] == 2222
    assert start_payload["zone_id"] == 77
    assert start_payload["is_new_favorite_machine_number"] is False
    for call in session.calls_to("/parking_session/cost_calculator"):
        assert call["kwargs"]["json"]["machine_number"] == 2222


@pytest.mark.parametrize(
    "message",
    [
        "This parking machine does not exist.",
        "The chosen parking machine is not within the allowed zones.",
    ],
)
async def test_unknown_machine_number_is_validation_error(message: str) -> None:
    session = _RoutedSession(
        _routes(
            **{"POST|/get_by_machine_number": [_FakeResponse({"message": message}, status=400)]}
        )
    )
    provider = _provider(session)

    with pytest.raises(ValidationError):
        await provider.login({"username": "u", "password": "p", "machine_number": "9999"})


@pytest.mark.parametrize("value", ["abc", "0", "-5", "12.5", "١٢"])
async def test_malformed_machine_number_is_rejected_before_any_request(value: str) -> None:
    session = _RoutedSession({})
    provider = _provider(session)

    with pytest.raises(ValidationError):
        await provider.login({"username": "u", "password": "p", "machine_number": value})

    assert session.calls == []


async def test_other_provider_error_for_machine_lookup_is_not_masked() -> None:
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

    with pytest.raises(ProviderError) as exc_info:
        await provider.login({"username": "u", "password": "p", "machine_number": "2222"})

    assert not isinstance(exc_info.value, ValidationError)


async def test_expired_token_reauthenticates_once_and_keeps_machine_override() -> None:
    session = _RoutedSession(
        _routes(
            **{
                "GET|/api/v1/client_product/42": [
                    _FakeResponse({}, status=401),
                    _FakeResponse(CLIENT_PRODUCT),
                ],
                "POST|/get_by_machine_number": [_FakeResponse({"zone": {"zone_id": 77}})],
            }
        )
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p", "machine_number": "2222"})

    await provider.get_permit()

    assert len(session.calls_to("/login_check")) == 2
    assert len(session.calls_to("/get_by_machine_number")) == 2
    await provider.start_reservation("ab-12-cd", *_times())
    assert session.calls_to("/parking_session/start")[0]["kwargs"]["json"]["machine_number"] == 2222


async def test_persistent_unauthorized_response_raises_auth_error() -> None:
    session = _RoutedSession(
        _routes(**{"GET|/api/v1/client_product/42": [_FakeResponse({}, status=401)]})
    )
    provider = _provider(session)
    await provider.login({"username": "u", "password": "p"})

    with pytest.raises(AuthError):
        await provider.get_permit()

    assert len(session.calls_to("/login_check")) == 2
