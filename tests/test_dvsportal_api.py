from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta

import pytest

from pycityvisitorparking.exceptions import AuthError, ProviderError, ValidationError
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
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.calls = 0

    def request(self, method: str, url: str, **kwargs) -> _FakeRequestContext:
        self.calls += 1
        response = self._responses[self.calls - 1]
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
async def test_request_with_backoff_invalid_json() -> None:
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
