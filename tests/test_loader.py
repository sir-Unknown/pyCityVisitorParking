import pytest

import pycityvisitorparking.client as client_module
from pycityvisitorparking.client import Client
from pycityvisitorparking.exceptions import ProviderError


@pytest.mark.asyncio
async def test_list_providers_includes_manifest() -> None:
    async with Client() as client:
        providers = await client.list_providers()
    provider_ids = {provider.id for provider in providers}
    assert "dvsportal" in provider_ids
    dvs_provider = next(provider for provider in providers if provider.id == "dvsportal")
    assert dvs_provider.reservation_update_fields == ("end_time",)


@pytest.mark.asyncio
async def test_get_provider_missing() -> None:
    async with Client() as client:
        with pytest.raises(ProviderError):
            await client.get_provider("missing")


@pytest.mark.asyncio
async def test_list_providers_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_to_thread(func, /, *args, **kwargs):
        calls["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(client_module.asyncio, "to_thread", fake_to_thread)

    async with Client() as client:
        await client.list_providers()

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_get_provider_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_to_thread(func, /, *args, **kwargs):
        calls["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(client_module.asyncio, "to_thread", fake_to_thread)

    async with Client(base_url="https://example") as client:
        provider = await client.get_provider("dvsportal")

    assert calls["count"] == 1
    assert provider.provider_id == "dvsportal"
