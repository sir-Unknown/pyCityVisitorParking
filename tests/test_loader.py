import pytest

import pycityvisitorparking.client as client_module
from pycityvisitorparking.exceptions import ProviderError
from pycityvisitorparking.provider import loader as loader_module


@pytest.mark.asyncio
async def test_list_providers_includes_manifest() -> None:
    async with client_module.Client() as client:
        providers = await client.list_providers()
    provider_ids = {provider.id for provider in providers}
    assert "dvsportal" in provider_ids
    dvs_provider = next(provider for provider in providers if provider.id == "dvsportal")
    assert dvs_provider.reservation_update_fields == ("end_time",)


@pytest.mark.asyncio
async def test_get_provider_missing() -> None:
    async with client_module.Client() as client:
        with pytest.raises(ProviderError):
            await client.get_provider("missing")


@pytest.mark.asyncio
async def test_list_providers_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_to_thread(func, /, *args, **kwargs):
        calls["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(client_module.asyncio, "to_thread", fake_to_thread)  # type: ignore[attr-defined]

    async with client_module.Client() as client:
        await client.list_providers()

    assert calls["count"] == 1


@pytest.mark.asyncio
async def test_get_provider_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_to_thread(func, /, *args, **kwargs):
        calls["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(client_module.asyncio, "to_thread", fake_to_thread)  # type: ignore[attr-defined]

    async with client_module.Client(base_url="https://example") as client:
        provider = await client.get_provider("dvsportal")

    assert calls["count"] == 1
    assert provider.provider_id == "dvsportal"


def _manifest_data(**capabilities: object) -> dict:
    return {
        "id": "dummy",
        "name": "Dummy",
        "capabilities": {
            "favorite_update_fields": [],
            "reservation_update_fields": [],
            **capabilities,
        },
    }


def test_zone_selection_defaults_to_false_and_must_be_boolean() -> None:
    assert loader_module._build_manifest(_manifest_data(), "dummy").zone_selection is False
    manifest = loader_module._build_manifest(_manifest_data(zone_selection=True), "dummy")
    assert manifest.zone_selection is True
    with pytest.raises(ProviderError, match="zone_selection"):
        loader_module._build_manifest(_manifest_data(zone_selection="yes"), "dummy")
