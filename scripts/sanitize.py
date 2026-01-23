"""Sanitize JSON payloads for safe sharing."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

REDACTED = "***"
_SENSITIVE_KEYS = {
    "password",
    "token",
    "authorization",
    "access_token",
    "refresh_token",
    "secret",
    "pin",
    "permitmediacode",
    "permit_media_code",
    "permitmediatypeid",
    "permit_media_type_id",
    "identifier",
}
_PII_KEYS = {
    "email",
    "phone",
    "username",
    "user_name",
    "first_name",
    "last_name",
    "name",
}
_PLATE_KEYS = {
    "license_plate",
    "licenseplate",
    "vrn",
    "vehicle_plate",
    "plate",
}
_PERMIT_MEDIA_CONTAINER_KEYS = {
    "permitmedias",
    "permit_medias",
}


def mask_license_plate(plate: str) -> str:
    """Return a masked representation of a license plate."""
    if not isinstance(plate, str):
        return REDACTED
    normalized = "".join(ch for ch in plate.upper() if ch.isascii() and ch.isalnum())
    if not normalized:
        return REDACTED
    if len(normalized) <= 2:
        return "*" * len(normalized)
    if len(normalized) <= 4:
        return f"{normalized[:1]}{'*' * (len(normalized) - 2)}{normalized[-1:]}"
    masked = "*" * (len(normalized) - 4)
    return f"{normalized[:2]}{masked}{normalized[-2:]}"


def _mask_value_for_key(key: str, value: Any) -> Any:
    key_lower = key.lower()
    if any(fragment in key_lower for fragment in _SENSITIVE_KEYS):
        return REDACTED
    if any(fragment in key_lower for fragment in _PII_KEYS):
        return REDACTED
    if any(fragment in key_lower for fragment in _PLATE_KEYS):
        if isinstance(value, str):
            return mask_license_plate(value)
        return REDACTED
    return value


def sanitize_data(value: Any, *, key: str | None = None) -> Any:
    """Return a sanitized representation of a value."""
    if key is not None:
        value = _mask_value_for_key(key, value)
    if isinstance(value, dict):
        return {str(k): sanitize_data(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        if key is not None and key.lower() in _PERMIT_MEDIA_CONTAINER_KEYS:
            return [_sanitize_permit_media(item) for item in value]
        return [sanitize_data(item, key=key) for item in value]
    if isinstance(value, str) and key and key.lower() in _PLATE_KEYS:
        return mask_license_plate(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return "<bytes>"
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sanitize_permit_media(value: Any) -> Any:
    if not isinstance(value, dict):
        return sanitize_data(value)
    sanitized = {str(k): sanitize_data(v, key=str(k)) for k, v in value.items()}
    for item_key in list(sanitized.keys()):
        if item_key.lower() == "code":
            sanitized[item_key] = REDACTED
    return sanitized


def sanitize_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """Return sanitized headers."""
    sanitized: dict[str, Any] = {}
    for key, value in headers.items():
        if key.lower() == "authorization":
            sanitized[key] = REDACTED
        else:
            sanitized[key] = sanitize_data(value, key=key)
    return sanitized


def sanitize_file(path: Path) -> Any:
    """Load and sanitize a JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    return sanitize_data(data)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanitize a JSON file for sharing.")
    parser.add_argument("input", help="Path to the JSON file.")
    parser.add_argument(
        "--output",
        dest="output",
        help="Write sanitized JSON to this file (default: stdout).",
    )
    parser.add_argument(
        "--in-place",
        dest="in_place",
        action="store_true",
        help="Overwrite the input file with sanitized JSON.",
    )
    parser.add_argument(
        "--indent",
        dest="indent",
        type=int,
        default=2,
        help="Indent level for JSON output (default: 2).",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for sanitizing JSON files."""
    args = _parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        return 2
    if args.in_place and args.output:
        print("Use --in-place or --output, not both.", file=sys.stderr)
        return 2
    try:
        sanitized = sanitize_file(input_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output_text = json.dumps(
        sanitized,
        indent=args.indent,
        sort_keys=True,
        ensure_ascii=True,
    )
    if args.in_place:
        input_path.write_text(output_text, encoding="utf-8")
        return 0
    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        return 0
    print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
