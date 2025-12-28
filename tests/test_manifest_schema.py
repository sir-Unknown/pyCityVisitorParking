import json
from importlib import resources

import jsonschema


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
