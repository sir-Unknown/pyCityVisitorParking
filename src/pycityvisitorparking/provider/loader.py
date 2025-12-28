"""Provider discovery and manifest loading."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable

from ..exceptions import ProviderError
from ..models import ProviderInfo

MANIFEST_FILENAME = "manifest.json"
SCHEMA_FILENAME = "manifest.schema.json"


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    id: str
    name: str
    favorite_update_possible: bool


def _provider_root() -> Traversable:
    return resources.files("pycityvisitorparking.provider")


def load_manifest_schema() -> dict:
    schema_path = _provider_root() / SCHEMA_FILENAME
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _build_manifest(data: dict, folder_name: str) -> ProviderManifest:
    if not isinstance(data, dict):
        raise ProviderError("Provider manifest must be a JSON object.")
    missing = [key for key in ("id", "name", "favorite_update_possible") if key not in data]
    if missing:
        raise ProviderError(f"Provider manifest missing keys: {', '.join(missing)}.")
    provider_id = data["id"]
    name = data["name"]
    favorite_update_possible = data["favorite_update_possible"]
    if not isinstance(provider_id, str) or not provider_id:
        raise ProviderError("Provider manifest id must be a non-empty string.")
    if provider_id != folder_name:
        raise ProviderError("Provider manifest id must match its folder name.")
    if not isinstance(name, str) or not name:
        raise ProviderError("Provider manifest name must be a non-empty string.")
    if not isinstance(favorite_update_possible, bool):
        raise ProviderError("Provider manifest favorite_update_possible must be a boolean.")
    return ProviderManifest(
        id=provider_id,
        name=name,
        favorite_update_possible=favorite_update_possible,
    )


def iter_manifest_files() -> Iterable[tuple[str, Traversable]]:
    root = _provider_root()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / MANIFEST_FILENAME
        if manifest_path.is_file():
            yield entry.name, manifest_path


def load_manifests() -> list[ProviderManifest]:
    manifests: list[ProviderManifest] = []
    for folder_name, manifest_path in iter_manifest_files():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderError("Provider manifest is not valid JSON.") from exc
        manifests.append(_build_manifest(data, folder_name))
    return manifests


def list_providers() -> list[ProviderInfo]:
    return [
        ProviderInfo(id=manifest.id, favorite_update_possible=manifest.favorite_update_possible)
        for manifest in load_manifests()
    ]


def get_manifest(provider_id: str) -> ProviderManifest:
    for manifest in load_manifests():
        if manifest.id == provider_id:
            return manifest
    raise ProviderError("Provider not found.")
