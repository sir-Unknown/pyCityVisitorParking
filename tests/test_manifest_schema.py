import json
from importlib import resources

import jsonschema
import pytest


def test_manifest_schema_validation() -> None:
    root = resources.files("pycityvisitorparking.provider")
    schema = json.loads((root / "manifest.schema.json").read_text(encoding="utf-8"))
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file():
            continue
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)


def test_manifest_schema_rejects_legacy_capability_flags() -> None:
    root = resources.files("pycityvisitorparking.provider")
    schema = json.loads((root / "manifest.schema.json").read_text(encoding="utf-8"))
    legacy = {
        "id": "legacy",
        "name": "Legacy",
        "capabilities": {
            "favorite_update_fields": [],
            "reservation_update_fields": [],
        },
        "favorite_update_possible": False,
        "reservation_update_possible": True,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=legacy, schema=schema)
