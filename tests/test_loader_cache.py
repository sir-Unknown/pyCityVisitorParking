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

    first = loader_module.load_manifests()
    second = loader_module.load_manifests()

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

    loader_module.load_manifests()
    loader_module.clear_manifest_cache()
    loader_module.load_manifests()

    assert calls["count"] == 2
