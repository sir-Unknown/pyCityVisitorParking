from __future__ import annotations

from datetime import UTC, datetime

import aiohttp
import pytest

from pycityvisitorparking.exceptions import AuthError, NetworkError, ProviderError, ValidationError
from pycityvisitorparking.models import Favorite, Permit, Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.base import BaseProvider
from pycityvisitorparking.provider.loader import ProviderManifest


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        json_data: object | None = None,
        text_data: str = "",
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
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
    def __init__(self, results: list[object]) -> None:
        self._results = results
        self.calls = 0

    def request(self, method: str, url: str, **kwargs) -> _FakeRequestContext:
        self.calls += 1
        result = self._results[self.calls - 1]
        if isinstance(result, Exception):
            raise result
        return _FakeRequestContext(result)


class _DummyProvider(BaseProvider):
    async def login(self, credentials=None, **kwargs):  # type: ignore[override]
        return None

    async def get_permit(self) -> Permit:
        return Permit(id="permit", remaining_balance=1, zone_validity=[])

    async def list_reservations(self) -> list[Reservation]:
        return []

    async def start_reservation(self, license_plate, start_time, end_time, name=None):
        return Reservation(
            id="res",
            name=name or "",
            license_plate=license_plate,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
        )

    async def update_reservation(self, reservation_id, start_time=None, end_time=None, name=None):
        return Reservation(
            id=reservation_id,
            name=name or "",
            license_plate="",
            start_time=start_time.isoformat() if start_time else "",
            end_time=end_time.isoformat() if end_time else "",
        )

    async def end_reservation(self, reservation_id, end_time):
        return Reservation(
            id=reservation_id,
            name="",
            license_plate="",
            start_time="",
            end_time=end_time.isoformat(),
        )

    async def list_favorites(self) -> list[Favorite]:
        return []

    async def add_favorite(self, license_plate, name=None):
        return Favorite(id="fav", name=name or "", license_plate=license_plate)

    async def _update_favorite_native(self, favorite_id, license_plate=None, name=None):
        return Favorite(
            id=favorite_id,
            name=name or "",
            license_plate=license_plate or "",
        )

    async def remove_favorite(self, favorite_id: str) -> None:
        return None


def _manifest(
    *,
    favorite_update_fields: tuple[str, ...] = (),
    reservation_update_fields: tuple[str, ...] = (),
) -> ProviderManifest:
    return ProviderManifest(
        id="dummy",
        name="Dummy",
        favorite_update_fields=favorite_update_fields,
        reservation_update_fields=reservation_update_fields,
    )


def test_build_url_validation() -> None:
    provider = _DummyProvider(
        _SequenceSession([]),
        _manifest(),
        base_url="https://example.com",
    )
    assert provider._build_url("/path") == "https://example.com/path"
    with pytest.raises(ValidationError):
        provider._build_url("")
    with pytest.raises(ValidationError):
        provider._build_url("https://example.com/absolute")


def test_build_url_requires_base_url() -> None:
    provider = _DummyProvider(_SequenceSession([]), _manifest(), base_url=None)
    with pytest.raises(ValidationError):
        provider._build_url("path")


def test_normalize_api_uri() -> None:
    provider = _DummyProvider(_SequenceSession([]), _manifest(), base_url="https://example.com")
    assert provider._normalize_api_uri(None) == ""
    assert provider._normalize_api_uri(" /api/v1/ ") == "/api/v1"
    with pytest.raises(ValidationError):
        provider._normalize_api_uri(123)


def test_merge_credentials() -> None:
    provider = _DummyProvider(_SequenceSession([]), _manifest(), base_url="https://example.com")
    merged = provider._merge_credentials({"user": "a"}, token="b")
    assert merged == {"user": "a", "token": "b"}
    with pytest.raises(ValidationError):
        provider._merge_credentials(["invalid"])  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        provider._merge_credentials({"user": 1})  # type: ignore[arg-type]


def test_filter_chargeable_zone_validity_invalid() -> None:
    provider = _DummyProvider(_SequenceSession([]), _manifest(), base_url="https://example.com")
    blocks = [
        (ZoneValidityBlock("invalid", "2024-01-01T12:00:00Z"), True),
    ]
    with pytest.raises(ProviderError):
        provider._filter_chargeable_zone_validity(blocks)


@pytest.mark.asyncio
async def test_update_favorite_not_supported() -> None:
    provider = _DummyProvider(_SequenceSession([]), _manifest(), base_url="https://example.com")
    with pytest.raises(ProviderError):
        await provider.update_favorite("fav", name="x")


@pytest.mark.asyncio
async def test_update_favorite_rejects_fields() -> None:
    provider = _DummyProvider(
        _SequenceSession([]),
        _manifest(favorite_update_fields=("name",)),
        base_url="https://example.com",
    )
    with pytest.raises(ValidationError):
        await provider.update_favorite("fav", license_plate="AA11BB")


@pytest.mark.asyncio
async def test_update_favorite_calls_native() -> None:
    provider = _DummyProvider(
        _SequenceSession([]),
        _manifest(favorite_update_fields=("license_plate", "name")),
        base_url="https://example.com",
    )
    favorite = await provider.update_favorite("fav", license_plate="AA11BB", name="Car")
    assert favorite.id == "fav"
    assert favorite.license_plate == "AA11BB"


@pytest.mark.asyncio
async def test_request_json_retries_get() -> None:
    session = _SequenceSession(
        [
            aiohttp.ClientError("boom"),
            _FakeResponse(json_data={"ok": True}),
        ]
    )
    provider = _DummyProvider(
        session,
        _manifest(),
        base_url="https://example.com",
        retry_count=1,
    )
    result = await provider._request_json("GET", "/path")
    assert result == {"ok": True}
    assert session.calls == 2


@pytest.mark.asyncio
async def test_request_json_no_retry_on_post() -> None:
    session = _SequenceSession([aiohttp.ClientError("boom")])
    provider = _DummyProvider(
        session,
        _manifest(),
        base_url="https://example.com",
        retry_count=2,
    )
    with pytest.raises(NetworkError):
        await provider._request_json("POST", "/path")
    assert session.calls == 1


@pytest.mark.asyncio
async def test_request_json_invalid_response() -> None:
    session = _SequenceSession([_FakeResponse(json_error=ValueError("bad"))])
    provider = _DummyProvider(session, _manifest(), base_url="https://example.com")
    with pytest.raises(ProviderError):
        await provider._request_json("GET", "/path")


@pytest.mark.asyncio
async def test_request_text_auth_error() -> None:
    session = _SequenceSession([_FakeResponse(status=401)])
    provider = _DummyProvider(session, _manifest(), base_url="https://example.com")
    with pytest.raises(AuthError):
        await provider._request_text("GET", "/path")


@pytest.mark.asyncio
async def test_request_text_provider_error() -> None:
    session = _SequenceSession([_FakeResponse(status=500)])
    provider = _DummyProvider(session, _manifest(), base_url="https://example.com")
    with pytest.raises(ProviderError):
        await provider._request_text("GET", "/path")


@pytest.mark.asyncio
async def test_request_text_success() -> None:
    session = _SequenceSession([_FakeResponse(text_data="ok")])
    provider = _DummyProvider(session, _manifest(), base_url="https://example.com")
    assert await provider._request_text("GET", "/path") == "ok"


def test_validate_reservation_times_require_both() -> None:
    provider = _DummyProvider(_SequenceSession([]), _manifest(), base_url="https://example.com")
    start = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    end = datetime(2024, 1, 1, 11, 0, tzinfo=UTC)
    start_norm, end_norm = provider._validate_reservation_times(
        start,
        end,
        require_both=True,
    )
    assert start_norm == start
    assert end_norm == end
