from datetime import UTC, datetime

import aiohttp
import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import Favorite, Permit, Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.amsterdam.api import Provider
from pycityvisitorparking.provider.amsterdam.const import DEFAULT_API_URI
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.util import format_utc_timestamp, parse_timestamp

ACCOUNT_SAMPLE = {
    "client_product_id": 42,
    "ssp": {
        "main_account": {
            "time_balance": 7200,
        }
    },
    "validity": {
        "started_at": "2024-01-01T08:00:00+01:00",
        "ended_at": "2024-01-01T18:00:00+01:00",
    },
}

ZONE_VALIDITY_SAMPLE = {
    "client_product_id": 7,
    "zone_validity": [
        {
            "is_free": True,
            "start_time": "2024-01-02T09:00:00+01:00",
            "end_time": "2024-01-02T18:00:00+01:00",
        },
        {
            "is_free": False,
            "start_time": "2024-01-03T09:00:00+01:00",
            "end_time": "2024-01-03T18:00:00+01:00",
        },
    ],
}

RESERVATION_SAMPLE = {
    "parking_session_id": 123,
    "permit_name": "Visitor",
    "vrn": "ab-12 cd",
    "started_at": "2024-06-01T10:00:00+02:00",
    "ended_at": "2024-06-01T11:00:00+02:00",
}

FAVORITE_SAMPLE = {
    "favorite_vrn_id": 5,
    "vrn": "xy-99-zz",
    "description": "Family",
}


def assert_utc_timestamp(value: str) -> None:
    parsed = parse_timestamp(value)
    assert parsed.tzinfo == UTC
    assert format_utc_timestamp(parsed) == value


@pytest.mark.asyncio
async def test_map_permit_uses_validity_and_balance():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(ACCOUNT_SAMPLE, client_product_id="42")

    assert isinstance(permit, Permit)
    assert permit.id == "42"
    assert permit.remaining_balance == 7200
    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-01-01T07:00:00Z",
            end_time="2024-01-01T17:00:00Z",
        )
    ]
    for block in permit.zone_validity:
        assert_utc_timestamp(block.start_time)
        assert_utc_timestamp(block.end_time)


@pytest.mark.asyncio
async def test_map_permit_filters_free_zone_validity():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(ZONE_VALIDITY_SAMPLE, client_product_id="7")

    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-01-03T08:00:00Z",
            end_time="2024-01-03T17:00:00Z",
        )
    ]


@pytest.mark.asyncio
async def test_map_reservation_normalizes_plate_and_time():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        reservation = provider._map_reservation(RESERVATION_SAMPLE)

    assert isinstance(reservation, Reservation)
    assert reservation.id == "123"
    assert reservation.license_plate == "AB12CD"
    assert reservation.start_time == "2024-06-01T08:00:00Z"
    assert reservation.end_time == "2024-06-01T09:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_map_favorite_normalizes_plate():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        favorite = provider._map_favorite(FAVORITE_SAMPLE)

    assert isinstance(favorite, Favorite)
    assert favorite.id == "5"
    assert favorite.license_plate == "XY99ZZ"
    assert favorite.name == "Family"


@pytest.mark.asyncio
async def test_parse_provider_timestamp_assumes_local_time():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        timestamp = provider._parse_provider_timestamp("2024-01-01T10:00:00")

    assert timestamp == "2024-01-01T09:00:00Z"
    assert_utc_timestamp(timestamp)


@pytest.mark.asyncio
async def test_start_reservation_rejects_naive_datetime():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._client_product_id = "1"
        provider._auth_header_value = "Bearer token"
        provider._logged_in = True

        with pytest.raises(ValidationError):
            await provider.start_reservation(
                "ab-12-cd",
                start_time=datetime(2024, 1, 1, 10, 0),
                end_time=datetime(2024, 1, 1, 11, 0, tzinfo=UTC),
            )


@pytest.mark.asyncio
async def test_extract_client_product_id_handles_alternate_shapes():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

    assert provider._extract_client_product_id({"clientProductId": "99"}) == "99"
    assert provider._extract_client_product_id({"client_product_ids": [123]}) == "123"
    assert provider._extract_client_product_id({"client_products": [{"id": "42"}]}) == "42"


@pytest.mark.asyncio
async def test_extract_client_product_id_from_product_list():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

    data = {"data": [{"type": "client_product", "id": 55}]}
    assert provider._extract_client_product_id_from_product_list(data) == "55"


@pytest.mark.asyncio
async def test_extract_client_product_id_from_permit_list():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

    data = {"permit": [{"permit_id": 77}]}
    assert provider._extract_client_product_id_from_permit_list(data) == "77"


def test_default_api_uri():
    assert DEFAULT_API_URI == "/api"
