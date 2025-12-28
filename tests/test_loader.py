import pytest

from pycityvisitorparking.client import Client
from pycityvisitorparking.exceptions import ProviderError


@pytest.mark.asyncio
async def test_list_providers_includes_manifest() -> None:
    async with Client() as client:
        providers = await client.list_providers()
    provider_ids = {provider.id for provider in providers}
    assert "dvsportal" in provider_ids


@pytest.mark.asyncio
async def test_get_provider_missing() -> None:
    async with Client() as client:
        with pytest.raises(ProviderError):
            await client.get_provider("missing")
