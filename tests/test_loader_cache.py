import pytest

from pycityvisitorparking.provider import loader as loader_module


def test_load_manifests_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    loader_module.clear_manifest_cache()
    calls = {"count": 0}
    original = loader_module.iter_manifest_files

    def wrapped():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(loader_module, "iter_manifest_files", wrapped)

    first = loader_module.load_manifests(cache_ttl=3600.0)
    second = loader_module.load_manifests(cache_ttl=3600.0)

    assert calls["count"] == 1
    assert first == second


def test_clear_manifest_cache_forces_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    loader_module.clear_manifest_cache()
    calls = {"count": 0}
    original = loader_module.iter_manifest_files

    def wrapped():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(loader_module, "iter_manifest_files", wrapped)

    loader_module.load_manifests(cache_ttl=3600.0)
    loader_module.clear_manifest_cache()
    loader_module.load_manifests(cache_ttl=3600.0)

    assert calls["count"] == 2


def test_load_manifests_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    loader_module.clear_manifest_cache()
    calls = {"count": 0}
    original = loader_module.iter_manifest_files
    times = iter([0.0, 0.5, 2.0, 2.0])

    def wrapped():
        calls["count"] += 1
        return original()

    def fake_monotonic():
        return next(times)

    monkeypatch.setattr(loader_module, "iter_manifest_files", wrapped)
    monkeypatch.setattr(loader_module.time, "monotonic", fake_monotonic)

    loader_module.load_manifests(cache_ttl=1.0)
    loader_module.load_manifests(cache_ttl=1.0)
    loader_module.load_manifests(cache_ttl=1.0)

    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_async_load_manifests_uses_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    async def fake_to_thread(func, /, *args, **kwargs):
        calls["count"] += 1
        return func(*args, **kwargs)

    monkeypatch.setattr(loader_module.asyncio, "to_thread", fake_to_thread)

    await loader_module.async_load_manifests()

    assert calls["count"] == 1
