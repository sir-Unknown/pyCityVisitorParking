from datetime import UTC

import aiohttp
import pytest

from pycityvisitorparking.models import ZoneValidityBlock
from pycityvisitorparking.provider.dvsportal.api import Provider
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.util import format_utc_timestamp, parse_timestamp

PERMIT_SAMPLE = {
    "ZoneCode": "ZONE-1",
    "BlockTimes": [
        {
            "IsFree": True,
            "ValidFrom": "2024-01-01T09:00:00+01:00",
            "ValidUntil": "2024-01-01T18:00:00+01:00",
        },
        {
            "IsFree": False,
            "ValidFrom": "2024-01-02T09:00:00+01:00",
            "ValidUntil": "2024-01-02T18:00:00+01:00",
        },
    ],
    "PermitMedias": [
        {
            "TypeID": 1,
            "Code": "CARD-1",
            "Balance": "120",
            "ActiveReservations": [
                {
                    "ReservationID": "123",
                    "ValidFrom": "2024-01-01T10:00:00+01:00",
                    "ValidUntil": "2024-01-01T11:00:00+01:00",
                    "LicensePlate": {
                        "Value": "ab-12 cd",
                        "DisplayValue": "AB-12-CD",
                    },
                }
            ],
            "LicensePlates": [
                {"Value": "xy-99-zz", "Name": "Family"},
            ],
        }
    ],
}

PERMIT_SAMPLE_NAIVE = {
    "ZoneCode": "ZONE-1",
    "BlockTimes": [
        {
            "IsFree": False,
            "ValidFrom": "2024-07-01T09:00:00",
            "ValidUntil": "2024-07-01T18:00:00",
        },
    ],
    "PermitMedias": [
        {
            "TypeID": 1,
            "Code": "CARD-1",
            "Balance": "120",
            "ActiveReservations": [
                {
                    "ReservationID": "456",
                    "ValidFrom": "2024-07-01T10:00:00",
                    "ValidUntil": "2024-07-01T11:00:00",
                    "LicensePlate": {
                        "Value": "ab-12 cd",
                        "DisplayValue": "AB-12-CD",
                    },
                }
            ],
            "LicensePlates": [],
        }
    ],
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
                id="dvsportal",
                name="DVS Portal",
                favorite_update_possible=False,
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(PERMIT_SAMPLE)

    assert permit.id == "CARD-1"
    assert permit.remaining_balance == 120
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
async def test_map_reservations_normalizes_plate_and_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_possible=False,
            ),
            base_url="https://example",
        )
        permit_media = PERMIT_SAMPLE["PermitMedias"][0]
        reservations = provider._map_reservations(permit_media)

    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.id == "123"
    assert reservation.name == "AB-12-CD"
    assert reservation.license_plate == "AB12CD"
    assert reservation.start_time == "2024-01-01T09:00:00Z"
    assert reservation.end_time == "2024-01-01T10:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_map_permit_converts_naive_local_to_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_possible=False,
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(PERMIT_SAMPLE_NAIVE)

    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-07-01T07:00:00Z",
            end_time="2024-07-01T16:00:00Z",
        )
    ]
    for block in permit.zone_validity:
        assert_utc_timestamp(block.start_time)
        assert_utc_timestamp(block.end_time)


@pytest.mark.asyncio
async def test_map_reservations_converts_naive_local_to_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_possible=False,
            ),
            base_url="https://example",
        )
        permit_media = PERMIT_SAMPLE_NAIVE["PermitMedias"][0]
        reservations = provider._map_reservations(permit_media)

    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.start_time == "2024-07-01T08:00:00Z"
    assert reservation.end_time == "2024-07-01T09:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_map_favorites_normalizes_plate():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_possible=False,
            ),
            base_url="https://example",
        )
        permit_media = PERMIT_SAMPLE["PermitMedias"][0]
        favorites = provider._map_favorites(permit_media)

    assert len(favorites) == 1
    favorite = favorites[0]
    assert favorite.id == "XY99ZZ"
    assert favorite.license_plate == "XY99ZZ"
    assert favorite.name == "Family"
