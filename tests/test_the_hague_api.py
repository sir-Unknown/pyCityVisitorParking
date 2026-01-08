from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from pycityvisitorparking.exceptions import AuthError, ProviderError, ValidationError
from pycityvisitorparking.models import Favorite
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.provider.the_hague.api import Provider
from pycityvisitorparking.provider.the_hague.const import PERMIT_MEDIA_TYPE_HEADER


class _DummySession:
    def request(self, *args, **kwargs):
        raise RuntimeError("Session should not be used in these tests.")


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    async def json(self) -> Any:
        return self._payload


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
