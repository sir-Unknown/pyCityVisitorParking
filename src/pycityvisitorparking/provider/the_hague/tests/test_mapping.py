from datetime import UTC

import aiohttp
import pytest

from pycityvisitorparking.models import Favorite, Permit, Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.provider.the_hague.api import Provider
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
                favorite_update_possible=True,
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
async def test_map_reservation_normalizes_plate_and_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_possible=True,
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
async def test_map_favorite_normalizes_plate():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="the_hague",
                name="The Hague",
                favorite_update_possible=True,
            ),
            base_url="https://example",
        )
        favorite = provider._map_favorite(FAVORITE_SAMPLE)

    assert isinstance(favorite, Favorite)
    assert favorite.id == "9"
    assert favorite.name == "Family"
    assert favorite.license_plate == "XY99ZZ"
