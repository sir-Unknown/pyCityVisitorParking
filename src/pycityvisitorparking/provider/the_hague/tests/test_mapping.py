from datetime import UTC

import aiohttp
import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import Favorite, Permit, Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.provider.the_hague.api import Provider
from pycityvisitorparking.provider.the_hague.const import (
    DEFAULT_API_URI,
    PERMIT_MEDIA_TYPE_HEADER,
    SESSION_ENDPOINT,
)
from pycityvisitorparking.util import format_utc_timestamp, parse_timestamp

ACCOUNT_SAMPLE = {
    "id": 42,
    "debit_minutes": 90,
    "reservation_count": 1,
    "zone_validity": [
        {
            "is_free": True,
            "start_time": "2024-01-01T09:00:00+01:00",
            "end_time": "2024-01-01T18:00:00+01:00",
        },
        {
            "is_free": False,
            "start_time": "2024-01-02T09:00:00+01:00",
            "end_time": "2024-01-02T18:00:00+01:00",
        },
    ],
}


RESERVATION_SAMPLE = {
    "id": 123,
    "name": "Visitor",
    "license_plate": "ab-12 cd",
    "start_time": "2024-01-01T10:00:00+02:00",
    "end_time": "2024-01-01T11:00:00+02:00",
}

ZONE_FALLBACK_SAMPLE = {
    "id": 7,
    "debit_minutes": 120,
    "zone": {
        "id": "10",
        "name": "Benoordenhout",
        "start_time": "2025-12-19T08:00:00Z",
        "end_time": "2025-12-19T23:00:00Z",
    },
}

FAVORITE_SAMPLE = {
    "id": 9,
    "name": "Family",
    "license_plate": "xy-99-zz",
}


def assert_utc_timestamp(value: str) -> None:
    parsed = parse_timestamp(value)
    assert parsed.tzinfo == UTC
    assert format_utc_timestamp(parsed) == value


@pytest.mark.asyncio
async def test_map_permit_filters_free_blocks_and_converts_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(ACCOUNT_SAMPLE)

    assert isinstance(permit, Permit)
    assert permit.id == "42"
    assert permit.remaining_balance == 90
    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-01-02T08:00:00Z",
            end_time="2024-01-02T17:00:00Z",
        )
    ]
    for block in permit.zone_validity:
        assert_utc_timestamp(block.start_time)
        assert_utc_timestamp(block.end_time)


@pytest.mark.asyncio
async def test_map_permit_uses_zone_fallback_when_zone_validity_missing():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(ZONE_FALLBACK_SAMPLE)

    assert isinstance(permit, Permit)
    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2025-12-19T08:00:00Z",
            end_time="2025-12-19T23:00:00Z",
        )
    ]
    for block in permit.zone_validity:
        assert_utc_timestamp(block.start_time)
        assert_utc_timestamp(block.end_time)


@pytest.mark.asyncio
async def test_map_reservation_normalizes_plate_and_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        reservation = provider._map_reservation(RESERVATION_SAMPLE)

    assert isinstance(reservation, Reservation)
    assert reservation.id == "123"
    assert reservation.name == "Visitor"
    assert reservation.license_plate == "AB12CD"
    assert reservation.start_time == "2024-01-01T08:00:00Z"
    assert reservation.end_time == "2024-01-01T09:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_error_code_mapping():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        message = provider._error_message_for_code("PV00076")

    assert message == "Provider error pv76: No paid parking at this time"


@pytest.mark.asyncio
async def test_error_code_mapping_lowercase_with_zeros():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        message = provider._error_message_for_code("pv00076")

    assert message == "Provider error pv76: No paid parking at this time"


@pytest.mark.asyncio
async def test_error_code_mapping_unknown_code_is_generic():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        message = provider._error_message_for_code("pv999")

    assert message == "Provider error pv999."


@pytest.mark.asyncio
async def test_map_favorite_normalizes_plate():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        favorite = provider._map_favorite(FAVORITE_SAMPLE)

    assert isinstance(favorite, Favorite)
    assert favorite.id == "9"
    assert favorite.name == "Family"


@pytest.mark.asyncio
async def test_add_favorite_rejects_duplicate_plate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

        async def _fake_list_favorites() -> list[Favorite]:
            return [Favorite(id="9", name="Family", license_plate="AB12CD")]

        called = {"request": False}

        async def _fake_request_json(
            method: str,
            path: str,
            *,
            json: object | None = None,
            allow_reauth: bool,
        ) -> object:
            called["request"] = True
            return {}

        monkeypatch.setattr(provider, "list_favorites", _fake_list_favorites)
        monkeypatch.setattr(provider, "_request_json", _fake_request_json)

        with pytest.raises(ValidationError):
            await provider.add_favorite("ab-12 cd", name="Other")

    assert called["request"] is False


@pytest.mark.asyncio
async def test_request_includes_permit_media_type_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._permit_media_type_id = "1"
        captured: dict[str, dict[str, str]] = {}

        async def _fake_request(
            method: str, url: str, *, expect_json: bool, **kwargs: object
        ) -> object:
            headers = kwargs.get("headers")
            if isinstance(headers, dict):
                captured["headers"] = headers
            return {}

        monkeypatch.setattr(provider, "_request", _fake_request)
        await provider._request_json("GET", "/noop", allow_reauth=False)

    headers = captured["headers"]
    assert headers[PERMIT_MEDIA_TYPE_HEADER] == "1"


@pytest.mark.asyncio
async def test_login_requires_username():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

        with pytest.raises(ValidationError):
            await provider.login(credentials={"password": "secret"})


@pytest.mark.asyncio
async def test_default_api_uri_is_applied():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_fields=("license_plate", "name"),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

        expected = f"https://example{DEFAULT_API_URI}{SESSION_ENDPOINT}"
        assert provider._build_url(SESSION_ENDPOINT) == expected
