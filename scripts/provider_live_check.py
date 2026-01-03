"""Manual live check for a selected provider.

Run from the repository root with:
  API_URI=api USERNAME=... PASSWORD=... \
  PYTHONPATH=src PROVIDER_ID=the_hague BASE_URL=https://parkerendenhaag.denhaag.nl \
  python scripts/provider_live_check.py

  USERNAME=... PASSWORD=... \
  PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=https://parkeren.rijswijk.nl \
  python scripts/provider_live_check.py

Extra credentials can be added with `--extra`, for example:
  PYTHONPATH=src PROVIDER_ID=dvsportal BASE_URL=... \
    USERNAME=... PASSWORD=... \
    python scripts/provider_live_check.py \
    --extra permit_media_type_id=1

Optional environment variables:
  API_URI
  CREDENTIALS_FILE
  USERNAME
  PASSWORD

The script avoids printing full license plates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from pycityvisitorparking import Client
from pycityvisitorparking.models import Favorite, Reservation


def _require_value(name: str, value: str | None) -> str:
    if not value:
        print(f"Missing required value: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


def _mask_license_plate(plate: str) -> str:
    if not isinstance(plate, str):
        return "***"
    normalized = "".join(ch for ch in plate.upper() if ch.isascii() and ch.isalnum())
    if not normalized:
        return "***"
    if len(normalized) <= 2:
        return "*" * len(normalized)
    if len(normalized) <= 4:
        return f"{normalized[:1]}{'*' * (len(normalized) - 2)}{normalized[-1:]}"
    masked = "*" * (len(normalized) - 4)
    return f"{normalized[:2]}{masked}{normalized[-2:]}"


def _load_credentials(raw_json: str | None, file_path: str | None) -> dict[str, Any]:
    if raw_json:
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            print(f"Invalid credentials JSON: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if not isinstance(data, dict):
            print("Credentials JSON must be an object.", file=sys.stderr)
            raise SystemExit(2)
        return data
    if file_path:
        path = Path(file_path)
        if not path.exists():
            print(f"Credentials file not found: {path}", file=sys.stderr)
            raise SystemExit(2)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Invalid credentials JSON file: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if not isinstance(data, dict):
            print("Credentials JSON file must contain an object.", file=sys.stderr)
            raise SystemExit(2)
        return data
    print("Missing credentials. Use --credentials-json or --credentials-file.", file=sys.stderr)
    raise SystemExit(2)


def _format_reservation(reservation: Reservation) -> str:
    masked_plate = _mask_license_plate(reservation.license_plate)
    name = reservation.name or "-"
    return (
        f"{reservation.id} | {name} | {masked_plate} | "
        f"{reservation.start_time} -> {reservation.end_time}"
    )


def _format_favorite(favorite: Favorite) -> str:
    masked_plate = _mask_license_plate(favorite.license_plate)
    name = favorite.name or "-"
    return f"{favorite.id} | {name} | {masked_plate}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a provider live check.")
    parser.add_argument("--provider", dest="provider_id", help="Provider id (e.g. dvsportal).")
    parser.add_argument("--base-url", dest="base_url", help="Provider base URL.")
    parser.add_argument("--api-uri", dest="api_uri", help="Provider API URI.")
    parser.add_argument(
        "--credentials-json",
        dest="credentials_json",
        help="Credentials JSON string.",
    )
    parser.add_argument(
        "--credentials-file",
        dest="credentials_file",
        help="Path to a JSON file containing credentials.",
    )
    parser.add_argument("--username", dest="username", help="Username for login.")
    parser.add_argument("--password", dest="password", help="Password for login.")
    parser.add_argument(
        "--extra",
        dest="extra",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra credential key/value pairs.",
    )
    return parser.parse_args()


def _parse_extra(values: list[str]) -> dict[str, str]:
    extras: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            print(f"Invalid extra credential: {raw}", file=sys.stderr)
            raise SystemExit(2)
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            print(f"Invalid extra credential: {raw}", file=sys.stderr)
            raise SystemExit(2)
        extras[key] = value
    return extras


async def main() -> int:
    args = _parse_args()
    provider_id = args.provider_id or os.getenv("PROVIDER_ID")
    base_url = args.base_url or os.getenv("BASE_URL")
    api_uri = args.api_uri or os.getenv("API_URI")
    credentials_json = args.credentials_json or os.getenv("CREDENTIALS_JSON")
    credentials_file = args.credentials_file or os.getenv("CREDENTIALS_FILE")
    username = args.username or os.getenv("USERNAME")
    password = args.password or os.getenv("PASSWORD")
    extras = _parse_extra(args.extra or [])

    provider_id = _require_value("provider_id", provider_id)
    base_url = _require_value("base_url", base_url)
    if username and password:
        credentials = {"username": username, "password": password}
    else:
        credentials = _load_credentials(credentials_json, credentials_file)
    if extras:
        credentials.update(extras)

    try:
        async with Client(base_url=base_url, api_uri=api_uri) as client:
            provider = await client.get_provider(provider_id)
            await provider.login(credentials=credentials)
            permit = await provider.get_permit()
            reservations = await provider.list_reservations()
            favorites = await provider.list_favorites()
    except Exception as exc:
        print(f"Error: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Provider: {provider.provider_name} ({provider.provider_id})")
    print(f"Permit: {permit}")
    print(f"Reservations: {len(reservations)}")
    for reservation in reservations:
        print(f"- {_format_reservation(reservation)}")
    print(f"Favorites: {len(favorites)}")
    for favorite in favorites:
        print(f"- {_format_favorite(favorite)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
