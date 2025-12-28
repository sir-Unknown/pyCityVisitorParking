"""Manual live check for the DVS Portal provider.

Run from the repository root with:
  PYTHONPATH=src DVS_BASE_URL=... DVS_IDENTIFIER=... DVS_PASSWORD=... \
  python scripts/dvsportal_live_check.py

Optional environment variables:
  DVS_API_URI
  DVS_PERMIT_MEDIA_TYPE_ID

The script avoids printing full license plates.
"""

from __future__ import annotations

import asyncio
import os
import sys

from pycityvisitorparking import Client
from pycityvisitorparking.models import Favorite, Reservation
from pycityvisitorparking.util import mask_license_plate


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


def _format_reservation(reservation: Reservation) -> str:
    masked_plate = mask_license_plate(reservation.license_plate)
    name = reservation.name or "-"
    return (
        f"{reservation.id} | {name} | {masked_plate} | "
        f"{reservation.start_time} -> {reservation.end_time}"
    )


def _format_favorite(favorite: Favorite) -> str:
    masked_plate = mask_license_plate(favorite.license_plate)
    name = favorite.name or "-"
    return f"{favorite.id} | {name} | {masked_plate}"


async def main() -> int:
    base_url = _require_env("DVS_BASE_URL")
    identifier = _require_env("DVS_IDENTIFIER")
    password = _require_env("DVS_PASSWORD")
    api_uri = os.getenv("DVS_API_URI")
    permit_media_type_id = os.getenv("DVS_PERMIT_MEDIA_TYPE_ID")

    credentials = {
        "identifier": identifier,
        "password": password,
    }
    if permit_media_type_id:
        credentials["permit_media_type_id"] = permit_media_type_id

    try:
        async with Client(base_url=base_url, api_uri=api_uri) as client:
            provider = await client.get_provider("dvsportal")
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
