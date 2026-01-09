from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import pytest

from pycityvisitorparking.exceptions import AuthError, NetworkError, ProviderError, ValidationError
from pycityvisitorparking.models import Favorite
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.provider.the_hague.api import Provider
from pycityvisitorparking.provider.the_hague.const import PERMIT_MEDIA_TYPE_HEADER


class _DummySession:
    def request(self, *args, **kwargs):
        raise RuntimeError("Session should not be used in these tests.")


class _FakeResponse:
    def __init__(
        self,
        payload: Any,
        *,
        status: int = 200,
        text_data: str = "",
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
        self._payload = payload
        self._text_data = text_data
        self._json_error = json_error

    async def json(self) -> Any:
        if self._json_error is not None:
            raise self._json_error
        return self._payload

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
        self.calls: list[dict[str, Any]] = []
        self._index = 0

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeRequestContext:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        response = self._responses[self._index]
        self._index += 1
        if isinstance(response, Exception):
            raise response
        return _FakeRequestContext(response)


def _provider() -> Provider:
    return Provider(
        _DummySession(),  # type: ignore[arg-type]
        ProviderManifest(
            id="the_hague",
            name="The Hague",
            favorite_update_fields=("license_plate", "name"),
            reservation_update_fields=("end_time",),
        ),
        base_url="https://example",
    )


def _provider_with_session(session: object) -> Provider:
    provider = Provider(
        session,  # type: ignore[arg-type]
        ProviderManifest(
            id="the_hague",
            name="The Hague",
            favorite_update_fields=("license_plate", "name"),
            reservation_update_fields=("end_time",),
        ),
        base_url="https://example",
    )
    provider._logged_in = True
    return provider


def test_build_headers_includes_permit_media_type() -> None:
    provider = _provider()
    provider._permit_media_type_id = "ABC"
    headers = provider._build_headers()
    assert headers[PERMIT_MEDIA_TYPE_HEADER] == "ABC"


@pytest.mark.asyncio
async def test_error_message_from_response_uses_description() -> None:
    provider = _provider()
    response = _FakeResponse({"description": "pv76"})
    message = await provider._error_message_from_response(response)  # type: ignore[arg-type]
    assert message == "Provider error pv76: No paid parking at this time"


@pytest.mark.asyncio
async def test_request_with_reauth_retries_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    provider._credentials = {"username": "user", "password": "pass"}
    calls = {"count": 0, "reauth": 0}

    async def _fake_request(*_args, **_kwargs):
        if calls["count"] == 0:
            calls["count"] += 1
            raise AuthError("Authentication failed.")
        return {"ok": True}

    async def _fake_reauth() -> None:
        calls["reauth"] += 1

    monkeypatch.setattr(provider, "_request", _fake_request)
    monkeypatch.setattr(provider, "_reauthenticate", _fake_reauth)

    result = await provider._request_with_reauth(
        "GET",
        "/endpoint",
        expect_json=True,
        json=None,
        auth=None,
        allow_reauth=True,
    )
    assert result == {"ok": True}
    assert calls["reauth"] == 1


def test_normalize_permit_media_type_id_rejects_invalid() -> None:
    provider = _provider()
    with pytest.raises(ValidationError):
        provider._normalize_permit_media_type_id(True)
    with pytest.raises(ValidationError):
        provider._normalize_permit_media_type_id(" ")


def test_map_zone_validity_rejects_invalid_type() -> None:
    provider = _provider()
    with pytest.raises(ProviderError):
        provider._map_zone_validity("invalid")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_update_favorite_native_requires_fields() -> None:
    provider = _provider()
    with pytest.raises(ValidationError):
        await provider._update_favorite_native("fav")


@pytest.mark.asyncio
async def test_update_favorite_native_requires_id() -> None:
    provider = _provider()
    with pytest.raises(ValidationError):
        await provider._update_favorite_native("", name="Car")


@pytest.mark.asyncio
async def test_update_favorite_native_uses_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()

    async def _fake_list_favorites() -> list[Favorite]:
        return [Favorite(id="fav", name="Car", license_plate="AB12CD")]

    captured: dict[str, Any] = {}

    async def _fake_request_json(
        method: str,
        path: str,
        *,
        json: Any | None = None,
        allow_reauth: bool,
    ) -> Any:
        captured["json"] = json
        return {"id": "fav", "license_plate": "AB12CD", "name": "Car"}

    monkeypatch.setattr(provider, "list_favorites", _fake_list_favorites)
    monkeypatch.setattr(provider, "_request_json", _fake_request_json)

    favorite = await provider._update_favorite_native("fav", name="Car")
    assert favorite.license_plate == "AB12CD"
    assert captured["json"]["license_plate"] == "AB12CD"


@pytest.mark.asyncio
async def test_start_reservation_rejects_invalid_plate() -> None:
    provider = _provider()
    start = datetime.now(tz=UTC)
    end = start + timedelta(minutes=10)
    with pytest.raises(ValidationError):
        await provider.start_reservation("!!!", start_time=start, end_time=end)


@pytest.mark.asyncio
async def test_update_reservation_requires_end_time() -> None:
    provider = _provider()
    with pytest.raises(ValidationError):
        await provider.update_reservation("res", end_time=None)


@pytest.mark.asyncio
async def test_update_reservation_rejects_start_time_update() -> None:
    provider = _provider()
    with pytest.raises(ValidationError):
        await provider.update_reservation(
            "res",
            start_time=datetime.now(tz=UTC),
            end_time=datetime.now(tz=UTC) + timedelta(minutes=5),
        )


@pytest.mark.asyncio
async def test_end_reservation_requires_id() -> None:
    provider = _provider()
    with pytest.raises(ValidationError):
        await provider.end_reservation("", end_time=datetime.now(tz=UTC))


@pytest.mark.asyncio
async def test_end_reservation_requires_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()

    async def _fake_list_reservations() -> list:
        return []

    called = {"request": False}

    async def _fake_request_text(*_args, **_kwargs) -> str:
        called["request"] = True
        return ""

    monkeypatch.setattr(provider, "list_reservations", _fake_list_reservations)
    monkeypatch.setattr(provider, "_request_text", _fake_request_text)
    with pytest.raises(ValidationError):
        await provider.end_reservation("missing", end_time=datetime.now(tz=UTC))
    assert called["request"] is False


def test_error_message_for_invalid_code() -> None:
    provider = _provider()
    assert provider._error_message_for_code("###") is None


@pytest.mark.asyncio
async def test_get_permit_requests_account_endpoint() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                {
                    "id": 9,
                    "debit_minutes": 42,
                    "zone_validity": [
                        {
                            "is_free": False,
                            "start_time": "2024-01-02T09:00:00+01:00",
                            "end_time": "2024-01-02T18:00:00+01:00",
                        }
                    ],
                }
            )
        ]
    )
    provider = _provider_with_session(session)
    permit = await provider.get_permit()

    assert permit.id == "9"
    assert permit.remaining_balance == 42
    assert permit.zone_validity[0].start_time == "2024-01-02T08:00:00Z"
    assert session.calls[0]["url"].endswith("/api/account/0")


@pytest.mark.asyncio
async def test_start_reservation_posts_normalized_payload() -> None:
    session = _SequenceSession(
        [
            _FakeResponse(
                {
                    "id": "abc",
                    "name": "AB12CD",
                    "license_plate": "AB12CD",
                    "start_time": "2024-01-01T10:00:00Z",
                    "end_time": "2024-01-01T11:00:00Z",
                }
            )
        ]
    )
    provider = _provider_with_session(session)
    reservation = await provider.start_reservation(
        "ab-12 cd",
        start_time=datetime(2024, 1, 1, 10, 0, tzinfo=UTC),
        end_time=datetime(2024, 1, 1, 11, 0, tzinfo=UTC),
    )

    payload = session.calls[0]["kwargs"]["json"]
    assert payload["license_plate"] == "AB12CD"
    assert payload["name"] == "AB12CD"
    assert reservation.license_plate == "AB12CD"


@pytest.mark.asyncio
async def test_remove_favorite_sends_delete() -> None:
    session = _SequenceSession([_FakeResponse({}, text_data="ok")])
    provider = _provider_with_session(session)
    await provider.remove_favorite("fav-1")

    assert session.calls[0]["method"] == "DELETE"
    assert session.calls[0]["url"].endswith("/api/favorite/fav-1")


@pytest.mark.asyncio
async def test_request_handles_provider_error_message() -> None:
    session = _SequenceSession([_FakeResponse({"description": "pv76"}, status=400)])
    provider = _provider_with_session(session)
    with pytest.raises(ProviderError, match="pv76"):
        await provider._request("GET", "https://example/api/account/0", expect_json=True)


@pytest.mark.asyncio
async def test_request_invalid_json_raises_provider_error() -> None:
    session = _SequenceSession([_FakeResponse({}, json_error=ValueError("bad"))])
    provider = _provider_with_session(session)
    with pytest.raises(ProviderError, match="valid JSON"):
        await provider._request("GET", "https://example/api/account/0", expect_json=True)


@pytest.mark.asyncio
async def test_request_network_error_raises_network_error() -> None:
    session = _SequenceSession([aiohttp.ClientError("boom")])
    provider = _provider_with_session(session)
    with pytest.raises(NetworkError):
        await provider._request("GET", "https://example/api/account/0", expect_json=True)


@pytest.mark.asyncio
async def test_request_json_requires_authentication() -> None:
    session = _SequenceSession([])
    provider = Provider(
        session,  # type: ignore[arg-type]
        ProviderManifest(
            id="the_hague",
            name="The Hague",
            favorite_update_fields=("license_plate", "name"),
            reservation_update_fields=("end_time",),
        ),
        base_url="https://example",
    )
    with pytest.raises(AuthError):
        await provider._request_json("GET", "/account/0", allow_reauth=True)
