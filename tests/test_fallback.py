from datetime import datetime

import aiohttp
import pytest

from pycityvisitorparking.exceptions import ProviderError
from pycityvisitorparking.models import Favorite
from pycityvisitorparking.provider.base import BaseProvider
from pycityvisitorparking.provider.loader import ProviderManifest


class DummyProvider(BaseProvider):
    def __init__(self, session: aiohttp.ClientSession, manifest: ProviderManifest) -> None:
        super().__init__(session, manifest)

    async def login(self, credentials=None, **kwargs: str) -> None:
        return None

    async def get_permit(self):
        raise NotImplementedError

    async def list_reservations(self):
        raise NotImplementedError

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ):
        raise NotImplementedError

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ):
        raise NotImplementedError

    async def end_reservation(self, reservation_id: str, end_time: datetime):
        raise NotImplementedError

    async def list_favorites(self):
        return []

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        return Favorite(id="new", name=name or "", license_plate=license_plate)

    async def _update_favorite_native(self, favorite_id, license_plate=None, name=None):
        raise AssertionError("Native update should not be called when unsupported.")

    async def remove_favorite(self, favorite_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_update_favorite_not_supported() -> None:
    manifest = ProviderManifest(
        id="dummy",
        name="Dummy",
        favorite_update_possible=False,
        reservation_update_possible=False,
    )
    async with aiohttp.ClientSession() as session:
        provider = DummyProvider(session, manifest)
        with pytest.raises(ProviderError):
            await provider.update_favorite("fav1", license_plate="ab-12", name="Home")
