import aiohttp
import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import Favorite
from pycityvisitorparking.provider.base import BaseProvider
from pycityvisitorparking.provider.loader import ProviderManifest


class DummyProvider(BaseProvider):
    def __init__(self, session: aiohttp.ClientSession, manifest: ProviderManifest) -> None:
        super().__init__(session, manifest)
        self.added: list[tuple[str, str | None]] = []
        self.removed: list[str] = []

    async def login(self, credentials=None, **kwargs: str) -> None:
        return None

    async def get_permit(self):
        raise NotImplementedError

    async def list_reservations(self):
        raise NotImplementedError

    async def start_reservation(self, license_plate, start_time, end_time, name=None):
        raise NotImplementedError

    async def update_reservation(self, reservation_id, start_time=None, end_time=None, name=None):
        raise NotImplementedError

    async def end_reservation(self, reservation_id, end_time):
        raise NotImplementedError

    async def list_favorites(self):
        return []

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        self.added.append((license_plate, name))
        return Favorite(id="new", name=name or "", license_plate=license_plate)

    async def _update_favorite_native(self, favorite_id, license_plate=None, name=None):
        raise AssertionError("Native update should not be called in fallback mode.")

    async def remove_favorite(self, favorite_id: str) -> None:
        self.removed.append(favorite_id)


@pytest.mark.asyncio
async def test_update_favorite_fallback() -> None:
    manifest = ProviderManifest(id="dummy", name="Dummy", favorite_update_possible=False)
    async with aiohttp.ClientSession() as session:
        provider = DummyProvider(session, manifest)
        result = await provider.update_favorite("fav1", license_plate="ab-12", name="Home")

    assert provider.removed == ["fav1"]
    assert provider.added == [("AB12", "Home")]
    assert result.license_plate == "AB12"


@pytest.mark.asyncio
async def test_update_favorite_fallback_requires_plate() -> None:
    manifest = ProviderManifest(id="dummy", name="Dummy", favorite_update_possible=False)
    async with aiohttp.ClientSession() as session:
        provider = DummyProvider(session, manifest)
        with pytest.raises(ValidationError):
            await provider.update_favorite("fav1", name="Home")
