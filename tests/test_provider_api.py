from datetime import datetime

import aiohttp
import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.provider.dvsportal.api import Provider as DvsProvider
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.provider.the_hague.api import Provider as HagueProvider


@pytest.mark.asyncio
async def test_dvs_start_reservation_rejects_naive_datetime() -> None:
    async with aiohttp.ClientSession() as session:
        provider = DvsProvider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        with pytest.raises(ValidationError):
            await provider.start_reservation(
                "AB12CD",
                datetime(2026, 1, 2, 10, 0),
                datetime(2026, 1, 2, 11, 0),
            )


@pytest.mark.asyncio
async def test_dvs_end_reservation_rejects_naive_datetime() -> None:
    async with aiohttp.ClientSession() as session:
        provider = DvsProvider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        with pytest.raises(ValidationError):
            await provider.end_reservation("1", datetime(2026, 1, 2, 11, 0))


@pytest.mark.asyncio
async def test_dvs_update_reservation_rejects_naive_datetime() -> None:
    async with aiohttp.ClientSession() as session:
        provider = DvsProvider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        with pytest.raises(ValidationError):
            await provider.update_reservation("1", end_time=datetime(2026, 1, 2, 11, 0))


@pytest.mark.asyncio
async def test_the_hague_start_reservation_rejects_naive_datetime() -> None:
    async with aiohttp.ClientSession() as session:
        provider = HagueProvider(
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
            await provider.start_reservation(
                "AB12CD",
                datetime(2026, 1, 2, 10, 0),
                datetime(2026, 1, 2, 11, 0),
            )


@pytest.mark.asyncio
async def test_the_hague_update_reservation_rejects_naive_end_time() -> None:
    async with aiohttp.ClientSession() as session:
        provider = HagueProvider(
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
            await provider.update_reservation("1", end_time=datetime(2026, 1, 2, 11, 0))
