"""Provider discovery and manifest loading."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from importlib.metadata import PackageNotFoundError
from importlib.resources.abc import Traversable

from ..exceptions import ProviderError
from ..models import ProviderInfo

MANIFEST_FILENAME = "manifest.json"
SCHEMA_FILENAME = "manifest.schema.json"
_DEFAULT_CACHE_TTL_SECONDS = 300.0
_MANIFEST_CACHE: tuple[ProviderManifest, ...] | None = None
_MANIFEST_CACHE_EXPIRES_AT: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    id: str
    name: str
    favorite_update_possible: bool
    reservation_update_possible: bool


def _provider_root() -> Traversable:
    return resources.files("pycityvisitorparking.provider")


def load_manifest_schema() -> dict:
    schema_path = _provider_root() / SCHEMA_FILENAME
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _build_manifest(data: dict, folder_name: str) -> ProviderManifest:
    if not isinstance(data, dict):
        raise ProviderError("Provider manifest must be a JSON object.")
    missing = [
        key
        for key in ("id", "name", "favorite_update_possible", "reservation_update_possible")
        if key not in data
    ]
    if missing:
        raise ProviderError(f"Provider manifest missing keys: {', '.join(missing)}.")
    provider_id = data["id"]
    name = data["name"]
    favorite_update_possible = data["favorite_update_possible"]
    reservation_update_possible = data["reservation_update_possible"]
    if not isinstance(provider_id, str) or not provider_id:
        raise ProviderError("Provider manifest id must be a non-empty string.")
    if provider_id != folder_name:
        raise ProviderError("Provider manifest id must match its folder name.")
    if not isinstance(name, str) or not name:
        raise ProviderError("Provider manifest name must be a non-empty string.")
    if not isinstance(favorite_update_possible, bool):
        raise ProviderError("Provider manifest favorite_update_possible must be a boolean.")
    if not isinstance(reservation_update_possible, bool):
        raise ProviderError("Provider manifest reservation_update_possible must be a boolean.")
    return ProviderManifest(
        id=provider_id,
        name=name,
        favorite_update_possible=favorite_update_possible,
        reservation_update_possible=reservation_update_possible,
    )


def iter_manifest_files() -> Iterable[tuple[str, Traversable]]:
    root = _provider_root()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / MANIFEST_FILENAME
        if manifest_path.is_file():
            yield entry.name, manifest_path


def load_manifests(
    *,
    refresh: bool = False,
    cache_ttl: float | None = _DEFAULT_CACHE_TTL_SECONDS,
) -> list[ProviderManifest]:
    """Load provider manifests using a cache with an optional TTL."""
    global _MANIFEST_CACHE
    global _MANIFEST_CACHE_EXPIRES_AT
    if cache_ttl is not None and cache_ttl < 0:
        raise ProviderError("cache_ttl must be non-negative.")
    if not refresh and _MANIFEST_CACHE is not None:
        if cache_ttl is None:
            return list(_MANIFEST_CACHE)
        now = time.monotonic()
        if _MANIFEST_CACHE_EXPIRES_AT is not None and now < _MANIFEST_CACHE_EXPIRES_AT:
            return list(_MANIFEST_CACHE)
    if cache_ttl is None:
        _MANIFEST_CACHE = None
        _MANIFEST_CACHE_EXPIRES_AT = None
    manifests: list[ProviderManifest] = []
    try:
        for folder_name, manifest_path in iter_manifest_files():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ProviderError("Provider manifest is not valid JSON.") from exc
            manifests.append(_build_manifest(data, folder_name))
    except (ModuleNotFoundError, PackageNotFoundError) as exc:
        _MANIFEST_CACHE = None
        _MANIFEST_CACHE_EXPIRES_AT = None
        raise ProviderError("Provider package was not found.") from exc
    if cache_ttl is None:
        return manifests
    now = time.monotonic()
    _MANIFEST_CACHE = tuple(manifests)
    _MANIFEST_CACHE_EXPIRES_AT = now + cache_ttl
    return list(_MANIFEST_CACHE)


async def async_load_manifests(
    *,
    refresh: bool = False,
    cache_ttl: float | None = _DEFAULT_CACHE_TTL_SECONDS,
) -> list[ProviderManifest]:
    """Async wrapper for load_manifests to avoid blocking the event loop."""
    return await asyncio.to_thread(load_manifests, refresh=refresh, cache_ttl=cache_ttl)


def clear_manifest_cache() -> None:
    """Clear cached provider manifests (used in tests)."""
    global _MANIFEST_CACHE
    global _MANIFEST_CACHE_EXPIRES_AT
    _MANIFEST_CACHE = None
    _MANIFEST_CACHE_EXPIRES_AT = None


def list_providers(
    *,
    refresh: bool = False,
    cache_ttl: float | None = _DEFAULT_CACHE_TTL_SECONDS,
) -> list[ProviderInfo]:
    """Return provider info entries from cached manifests."""
    return [
        ProviderInfo(
            id=manifest.id,
            favorite_update_possible=manifest.favorite_update_possible,
            reservation_update_possible=manifest.reservation_update_possible,
        )
        for manifest in load_manifests(refresh=refresh, cache_ttl=cache_ttl)
    ]


async def async_list_providers(
    *,
    refresh: bool = False,
    cache_ttl: float | None = _DEFAULT_CACHE_TTL_SECONDS,
) -> list[ProviderInfo]:
    """Async wrapper for list_providers to avoid blocking the event loop."""
    return await asyncio.to_thread(list_providers, refresh=refresh, cache_ttl=cache_ttl)


def get_manifest(
    provider_id: str,
    *,
    refresh: bool = False,
    cache_ttl: float | None = _DEFAULT_CACHE_TTL_SECONDS,
) -> ProviderManifest:
    """Return the manifest for a provider id."""
    for manifest in load_manifests(refresh=refresh, cache_ttl=cache_ttl):
        if manifest.id == provider_id:
            return manifest
    raise ProviderError("Provider not found.")


async def async_get_manifest(
    provider_id: str,
    *,
    refresh: bool = False,
    cache_ttl: float | None = _DEFAULT_CACHE_TTL_SECONDS,
) -> ProviderManifest:
    """Async wrapper for get_manifest to avoid blocking the event loop."""
    return await asyncio.to_thread(
        get_manifest,
        provider_id,
        refresh=refresh,
        cache_ttl=cache_ttl,
    )
