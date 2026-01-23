"""Sanitize JSON payloads for safe sharing."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "token",
    "jwt",
    "authorization",
    "access_token",
    "refresh_token",
    "secret",
    "pin",
    "iban",
    "socialsecurity",
    "social_security",
    "bsn",
    "kvk",
    "permitmediacode",
    "permit_media_code",
    "permitmediatypeid",
    "permit_media_type_id",
    "identifier",
    "client_id",
    "client_product_id",
    "ps_right_id",
    "parking_session_id",
}
_PII_KEYS = {
    "email",
    "phone",
    "username",
    "user_name",
    "first_name",
    "last_name",
    "name",
    "address",
    "postal",
    "zip",
    "postcode",
    "city",
    "house_letter",
    "account_holder",
    "accountholder",
    "description",
}
_PLATE_KEYS = {
    "license_plate",
    "licenseplate",
    "vrn",
    "vehicle_plate",
    "plate",
}
_PLATE_VALUE_KEYS = {
    "displayvalue",
    "display_value",
    "normalizedvalue",
    "normalized_value",
    "value",
}
_PERMIT_MEDIA_CONTAINER_KEYS = {
    "permitmedias",
    "permit_medias",
}
_NON_SENSITIVE_KEYS = {
    "validfrom",
    "validuntil",
}


def mask_value(value: Any) -> Any:
    """Return a length-preserving mask for a value."""
    if value is None:
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, bytes):
        return "*" * len(value)
    if isinstance(value, str):
        return "*" * len(value)
    return "*" * len(str(value))


def mask_license_plate(plate: str) -> str:
    """Return a masked representation of a license plate."""
    if not isinstance(plate, str):
        return mask_value(plate)
    masked_chars: list[str] = []
    has_maskable = False
    for ch in plate:
        if ch.isalnum():
            masked_chars.append("*")
            has_maskable = True
        else:
            masked_chars.append(ch)
    if not has_maskable:
        return plate
    return "".join(masked_chars)


def _mask_container(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _mask_container(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_container(item) for item in value]
    return mask_value(value)


def _mask_plate_value(value: Any) -> Any:
    if isinstance(value, str):
        return mask_license_plate(value)
    if isinstance(value, list):
        return [_mask_plate_value(item) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for item_key, item_value in value.items():
            key_text = str(item_key)
            if key_text.lower() in _PLATE_VALUE_KEYS:
                if isinstance(item_value, str):
                    sanitized[key_text] = mask_license_plate(item_value)
                else:
                    sanitized[key_text] = mask_value(item_value)
                continue
            sanitized[key_text] = sanitize_data(item_value, key=key_text)
        return sanitized
    return mask_value(value)


def _mask_value_for_key(key: str, value: Any) -> Any:
    key_lower = key.lower()
    if any(fragment in key_lower for fragment in _NON_SENSITIVE_KEYS):
        return value
    if any(fragment in key_lower for fragment in _SENSITIVE_KEYS):
        return _mask_container(value)
    if any(fragment in key_lower for fragment in _PII_KEYS):
        return _mask_container(value)
    if any(fragment in key_lower for fragment in _PLATE_KEYS):
        return _mask_plate_value(value)
    return value


def sanitize_data(value: Any, *, key: str | None = None) -> Any:
    """Return a sanitized representation of a value."""
    if key is not None:
        masked = _mask_value_for_key(key, value)
        if masked is not value:
            return masked
    if isinstance(value, dict):
        return {str(k): sanitize_data(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        if key is not None and key.lower() in _PERMIT_MEDIA_CONTAINER_KEYS:
            return [_sanitize_permit_media(item) for item in value]
        return [sanitize_data(item, key=key) for item in value]
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
            sanitized[item_key] = mask_value(sanitized[item_key])
    return sanitized


def sanitize_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """Return sanitized headers."""
    sanitized: dict[str, Any] = {}
    for key, value in headers.items():
        if key.lower() == "authorization":
            sanitized[key] = mask_value(value)
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
        output_data = sanitize_file(input_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    output_text = json.dumps(
        output_data,
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
