from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta

import aiohttp
import pytest

from pycityvisitorparking.exceptions import AuthError, NetworkError, ProviderError, ValidationError
from pycityvisitorparking.models import ZoneValidityBlock
from pycityvisitorparking.provider.dvsportal.api import Provider
from pycityvisitorparking.provider.dvsportal.const import AUTH_PREFIX, RETRY_AFTER_HEADER
from pycityvisitorparking.provider.loader import ProviderManifest


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        json_data: object | None = None,
        text_data: str = "",
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._json_data = json_data
        self._text_data = text_data
        self._json_error = json_error

    async def json(self) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data

    async def text(self) -> str:
        return self._text_data


class _FakeRequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _SequenceSession:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.calls = 0
        self.requests: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs) -> _FakeRequestContext:
        self.requests.append({"method": method, "url": url, "kwargs": kwargs})
        self.calls += 1
        response = self._responses[self.calls - 1]
        if isinstance(response, Exception):
            raise response
        return _FakeRequestContext(response)


def _provider(session: object) -> Provider:
    return Provider(
        session,  # type: ignore[arg-type]
        ProviderManifest(
            id="dvsportal",
            name="DVS Portal",
            favorite_update_fields=(),
            reservation_update_fields=("end_time",),
        ),
        base_url="https://example",
        retry_count=1,
    )


def _permit_payload(
    *,
    balance: int = 30,
    reservations: list[dict[str, object]] | None = None,
    favorites: list[dict[str, object]] | None = None,
    block_times: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "Permit": {
            "ZoneCode": "Z1",
            "BlockTimes": block_times
            if block_times is not None
            else [
                {
                    "IsFree": False,
                    "ValidFrom": "2024-01-01T09:00:00+01:00",
                    "ValidUntil": "2024-01-01T17:00:00+01:00",
                }
            ],
            "PermitMedias": [
                {
                    "TypeID": 7,
                    "Code": "CODE",
                    "Balance": balance,
                    "ActiveReservations": reservations or [],
                    "LicensePlates": favorites or [],
                }
            ],
        }
    }


def test_build_auth_header() -> None:
    provider = _provider(_SequenceSession([]))
    token = "secret"
    encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
    assert provider._build_auth_header(token) == f"{AUTH_PREFIX}{encoded}"


def test_cache_defaults_sets_media_fields() -> None:
    provider = _provider(_SequenceSession([]))
    permit = {"PermitMedias": [{"TypeID": 7, "Code": " CODE "}]}
    provider._cache_defaults(permit)
    assert provider._permit_media_type_id == 7
    assert provider._permit_media_code == "CODE"


def test_parse_int_handles_strings_and_bools() -> None:
    provider = _provider(_SequenceSession([]))
    assert provider._parse_int(True) == 0
    assert provider._parse_int(" 10 ") == 10
    assert provider._parse_int("bad") == 0


def test_validate_media_type_id_rejects_invalid() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError):
        provider._validate_media_type_id(True)
    with pytest.raises(ValidationError):
        provider._validate_media_type_id(" ")


@pytest.mark.asyncio
async def test_handle_rate_limit_raises_for_post() -> None:
    provider = _provider(_SequenceSession([]))
    response = _FakeResponse(status=429, headers={RETRY_AFTER_HEADER: "0"})
    with pytest.raises(ProviderError):
        await provider._handle_rate_limit(response, "POST", attempt=0, attempts=2)


@pytest.mark.asyncio
async def test_request_with_backoff_rate_limit_retries_get(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _SequenceSession(
        [
            _FakeResponse(status=429, headers={RETRY_AFTER_HEADER: "0"}),
            _FakeResponse(status=200, json_data={"ok": True}),
        ]
    )
    provider = _provider(session)

    async def _noop_sleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    result = await provider._request_with_backoff(
        "GET",
        "https://example/api",
        expect_json=True,
        json=None,
        headers={},
    )
    assert result == {"ok": True}
    assert session.calls == 2


@pytest.mark.asyncio
async def test_request_with_backoff_auth_error() -> None:
    session = _SequenceSession([_FakeResponse(status=401)])
    provider = _provider(session)
    with pytest.raises(AuthError):
        await provider._request_with_backoff(
            "GET",
            "https://example/api",
            expect_json=True,
            json=None,
            headers={},
        )


@pytest.mark.asyncio
async def test_request_with_backoff_invalid_json_without_status() -> None:
    session = _SequenceSession([_FakeResponse(status=200, json_error=ValueError("bad"))])
    provider = _provider(session)
    with pytest.raises(ProviderError):
        await provider._request_with_backoff(
            "GET",
            "https://example/api",
            expect_json=True,
            json=None,
            headers={},
        )


@pytest.mark.asyncio
async def test_start_reservation_rejects_invalid_plate() -> None:
    provider = _provider(_SequenceSession([]))
    start = datetime.now(tz=UTC)
    end = start + timedelta(minutes=5)
    with pytest.raises(ValidationError):
        await provider.start_reservation(
            "!!!",
            start_time=start,
            end_time=end,
        )


@pytest.mark.asyncio
async def test_start_reservation_rejects_invalid_times() -> None:
    provider = _provider(_SequenceSession([]))
    start = datetime.now(tz=UTC)
    end = start - timedelta(minutes=1)
    with pytest.raises(ValidationError):
        await provider.start_reservation("AB12CD", start_time=start, end_time=end)


@pytest.mark.asyncio
async def test_update_reservation_requires_end_time() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError):
        await provider.update_reservation("res", end_time=None)


@pytest.mark.asyncio
async def test_update_reservation_rejects_name_update() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError):
        await provider.update_reservation(
            "res",
            end_time=datetime.now(tz=UTC),
            name="Car",
        )


@pytest.mark.asyncio
async def test_update_reservation_rejects_start_time_update() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError):
        await provider.update_reservation(
            "res",
            start_time=datetime.now(tz=UTC),
            end_time=datetime.now(tz=UTC) + timedelta(minutes=5),
        )


@pytest.mark.asyncio
async def test_end_reservation_rejects_unknown_id(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(_SequenceSession([]))

    async def _fake_list_reservations() -> list:
        return []

    async def _noop_defaults() -> None:
        return None

    monkeypatch.setattr(provider, "list_reservations", _fake_list_reservations)
    monkeypatch.setattr(provider, "_ensure_defaults", _noop_defaults)
    with pytest.raises(ValidationError):
        await provider.end_reservation("missing", end_time=datetime.now(tz=UTC))


@pytest.mark.asyncio
async def test_request_json_auth_requires_auth() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(AuthError):
        await provider._request_json_auth("GET", "/path")


@pytest.mark.asyncio
async def test_get_permit_maps_chargeable_block_times() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                json_data=_permit_payload(
                    balance=15,
                    block_times=[
                        {
                            "IsFree": True,
                            "ValidFrom": "2024-01-01T08:00:00+01:00",
                            "ValidUntil": "2024-01-01T09:00:00+01:00",
                        },
                        {
                            "IsFree": False,
                            "ValidFrom": "2024-01-01T09:00:00+01:00",
                            "ValidUntil": "2024-01-01T17:00:00+01:00",
                        },
                    ],
                )
            )
        ]
    )
    provider = _provider(session)
    provider._token = "token"
    provider._auth_header_value = "Token abc"

    permit = await provider.get_permit()

    assert permit.remaining_balance == 15
    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-01-01T08:00:00Z",
            end_time="2024-01-01T16:00:00Z",
        )
    ]
    assert session.requests[0]["url"].endswith("/DVSWebAPI/api/login/getbase")


@pytest.mark.asyncio
async def test_start_reservation_posts_payload_and_returns_match() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                json_data=_permit_payload(
                    reservations=[
                        {
                            "ReservationID": "R1",
                            "ValidFrom": "2024-01-01T10:00:00+01:00",
                            "ValidUntil": "2024-01-01T11:00:00+01:00",
                            "LicensePlate": {"Value": "AB12CD", "DisplayValue": "AB12CD"},
                        }
                    ]
                )
            )
        ]
    )
    provider = _provider(session)
    provider._token = "token"
    provider._auth_header_value = "Token abc"
    provider._permit_media_type_id = 7
    provider._permit_media_code = "CODE"

    reservation = await provider.start_reservation(
        "ab-12 cd",
        start_time=datetime(2024, 1, 1, 9, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        name="Car",
    )

    payload = session.requests[0]["kwargs"]["json"]
    assert payload["LicensePlate"]["Value"] == "AB12CD"
    assert payload["LicensePlate"]["Name"] == "Car"
    assert payload["DateFrom"].startswith("2024-01-01T10:00:00")
    assert payload["DateFrom"].endswith("+01:00")
    assert reservation.id == "R1"
    assert reservation.license_plate == "AB12CD"


@pytest.mark.asyncio
async def test_update_reservation_updates_minutes_delta() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                json_data=_permit_payload(
                    reservations=[
                        {
                            "ReservationID": "R1",
                            "ValidFrom": "2024-01-01T10:00:00+01:00",
                            "ValidUntil": "2024-01-01T11:00:00+01:00",
                            "LicensePlate": {"Value": "AB12CD", "DisplayValue": "AB12CD"},
                        }
                    ]
                )
            ),
            _FakeResponse(
                json_data=_permit_payload(
                    reservations=[
                        {
                            "ReservationID": "R1",
                            "ValidFrom": "2024-01-01T10:00:00+01:00",
                            "ValidUntil": "2024-01-01T11:15:00+01:00",
                            "LicensePlate": {"Value": "AB12CD", "DisplayValue": "AB12CD"},
                        }
                    ]
                )
            ),
        ]
    )
    provider = _provider(session)
    provider._token = "token"
    provider._auth_header_value = "Token abc"

    updated = await provider.update_reservation(
        "R1",
        end_time=datetime(2024, 1, 1, 10, 15, tzinfo=UTC),
    )

    payload = session.requests[1]["kwargs"]["json"]
    assert payload["Minutes"] == 15
    assert updated.end_time == "2024-01-01T10:15:00Z"


@pytest.mark.asyncio
async def test_add_favorite_uses_upsert_and_selects_favorite() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                json_data=_permit_payload(favorites=[{"Value": "CD34EF", "Name": "Other"}])
            ),
            _FakeResponse(
                json_data=_permit_payload(favorites=[{"Value": "AB12CD", "Name": "Car"}])
            ),
        ]
    )
    provider = _provider(session)
    provider._token = "token"
    provider._auth_header_value = "Token abc"

    favorite = await provider.add_favorite("ab-12 cd", name="Car")

    payload = session.requests[1]["kwargs"]["json"]
    assert payload["licensePlate"]["Value"] == "AB12CD"
    assert payload["licensePlate"]["Name"] == "Car"
    assert favorite.license_plate == "AB12CD"


@pytest.mark.asyncio
async def test_remove_favorite_uses_stored_name() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                json_data=_permit_payload(favorites=[{"Value": "AB12CD", "Name": "Family"}])
            ),
            _FakeResponse(json_data={"ok": True}),
        ]
    )
    provider = _provider(session)
    provider._token = "token"
    provider._auth_header_value = "Token abc"

    await provider.remove_favorite("ab-12 cd")

    payload = session.requests[1]["kwargs"]["json"]
    assert payload["licensePlate"] == "AB12CD"
    assert payload["name"] == "Family"


@pytest.mark.asyncio
async def test_fetch_permit_media_type_id_requires_list() -> None:
    session = _SequenceSession([_FakeResponse(json_data={})])
    provider = _provider(session)
    with pytest.raises(ProviderError, match="permit media types"):
        await provider._fetch_permit_media_type_id()


@pytest.mark.asyncio
async def test_fetch_permit_media_type_id_requires_id() -> None:
    session = _SequenceSession([_FakeResponse(json_data={"PermitMediaTypes": [{}]})])
    provider = _provider(session)
    with pytest.raises(ProviderError, match="permit media type ID"):
        await provider._fetch_permit_media_type_id()


@pytest.mark.asyncio
async def test_request_with_backoff_non_2xx_status() -> None:
    session = _SequenceSession([_FakeResponse(status=500)])
    provider = _provider(session)
    with pytest.raises(ProviderError, match="status 500"):
        await provider._request_with_backoff(
            "GET",
            "https://example/api",
            expect_json=True,
            json=None,
            headers={},
        )


@pytest.mark.asyncio
async def test_request_with_backoff_invalid_json() -> None:
    session = _SequenceSession([_FakeResponse(json_error=ValueError("bad"))])
    provider = _provider(session)
    with pytest.raises(ProviderError, match="valid JSON"):
        await provider._request_with_backoff(
            "GET",
            "https://example/api",
            expect_json=True,
            json=None,
            headers={},
        )


@pytest.mark.asyncio
async def test_request_with_backoff_network_error() -> None:
    session = _SequenceSession([aiohttp.ClientError("boom"), aiohttp.ClientError("boom")])
    provider = _provider(session)
    with pytest.raises(NetworkError, match="Network request failed"):
        await provider._request_with_backoff(
            "GET",
            "https://example/api",
            expect_json=True,
            json=None,
            headers={},
        )


@pytest.mark.asyncio
async def test_request_reauth_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(_SequenceSession([]))
    provider._credentials = {"username": "user", "password": "pass", "permit_media_type_id": "1"}
    calls = {"request": 0, "reauth": 0}

    async def _fake_request_with_backoff(*_args, **_kwargs):
        if calls["request"] == 0:
            calls["request"] += 1
            raise AuthError("Authentication failed.")
        return {"ok": True}

    async def _fake_reauth() -> None:
        calls["reauth"] += 1

    monkeypatch.setattr(provider, "_request_with_backoff", _fake_request_with_backoff)
    monkeypatch.setattr(provider, "_reauthenticate", _fake_reauth)

    result = await provider._request(
        "GET",
        "https://example/api",
        expect_json=True,
        json=None,
        headers={},
        allow_reauth=True,
    )
    assert result == {"ok": True}
    assert calls["reauth"] == 1


@pytest.mark.asyncio
async def test_update_reservation_rejects_non_minute_delta() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                json_data=_permit_payload(
                    reservations=[
                        {
                            "ReservationID": "R1",
                            "ValidFrom": "2024-01-01T10:00:00+01:00",
                            "ValidUntil": "2024-01-01T11:00:30+01:00",
                            "LicensePlate": {"Value": "AB12CD", "DisplayValue": "AB12CD"},
                        }
                    ]
                )
            )
        ]
    )
    provider = _provider(session)
    provider._token = "token"
    provider._auth_header_value = "Token abc"

    with pytest.raises(ValidationError, match="whole minutes"):
        await provider.update_reservation(
            "R1",
            end_time=datetime(2024, 1, 1, 10, 1, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_parse_provider_timestamp_handles_local_time() -> None:
    provider = _provider(_SequenceSession([]))
    timestamp = provider._parse_provider_timestamp("2024-01-01T10:00:00")
    assert timestamp == "2024-01-01T09:00:00Z"
