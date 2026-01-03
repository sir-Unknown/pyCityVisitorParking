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
  LICENSE_PLATE

The script avoids printing full license plates.

Run live reservation/favorite flows (requires LICENSE_PLATE):
  PYTHONPATH=src PROVIDER_ID=the_hague BASE_URL=... \
    USERNAME=... PASSWORD=... LICENSE_PLATE=AB12CD \
    python scripts/provider_live_check.py --run-all --post-create-wait 5

Note: the default reservation window is next-day 02:00-03:00 in the selected
timezone. For The Hague, this often falls outside paid parking windows and can
return PV00076 (no paid parking at this time). Use `--start-time`/`--end-time`
to pick a chargeable window instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pycityvisitorparking import Client
from pycityvisitorparking.exceptions import ProviderError, ValidationError
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
        "--run-all",
        dest="run_all",
        action="store_true",
        help="Run live reservation + favorite create/update/end flows.",
    )
    parser.add_argument(
        "--run-reservations",
        dest="run_reservations",
        action="store_true",
        help="Run live reservation create/update/end flow.",
    )
    parser.add_argument(
        "--run-favorites",
        dest="run_favorites",
        action="store_true",
        help="Run live favorite add/update/remove flow.",
    )
    parser.add_argument(
        "--license-plate",
        dest="license_plate",
        help="License plate used for reservation/favorite flows.",
    )
    parser.add_argument(
        "--reservation-name",
        dest="reservation_name",
        help="Optional reservation name.",
    )
    parser.add_argument(
        "--favorite-name",
        dest="favorite_name",
        help="Optional favorite name.",
    )
    parser.add_argument(
        "--start-time",
        dest="start_time",
        help="Reservation start time (ISO 8601 with offset or Z).",
    )
    parser.add_argument(
        "--end-time",
        dest="end_time",
        help="Reservation end time (ISO 8601 with offset or Z).",
    )
    parser.add_argument(
        "--extend-minutes",
        dest="extend_minutes",
        type=int,
        default=15,
        help="Minutes to extend when attempting reservation updates.",
    )
    parser.add_argument(
        "--post-create-wait",
        dest="post_create_wait",
        type=int,
        default=0,
        help="Seconds to wait after creating reservations/favorites before next step.",
    )
    parser.add_argument(
        "--timezone",
        dest="timezone",
        default="Europe/Amsterdam",
        help="Timezone for generated local times (e.g. Europe/Amsterdam).",
    )
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


def _parse_datetime(value: str, timezone_name: str | None) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValidationError("Timestamp must be a non-empty string.")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError("Timestamp is not a valid ISO 8601 value.") from exc
    if parsed.tzinfo is None:
        if not timezone_name:
            raise ValidationError("Timestamp must include timezone information.")
        try:
            tz = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError(f"Timezone '{timezone_name}' is unavailable.") from exc
        parsed = parsed.replace(tzinfo=tz, fold=0)
    return parsed


def _build_reservation_window(
    start_time: str | None,
    end_time: str | None,
    *,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    if start_time or end_time:
        if not start_time or not end_time:
            raise ValidationError("start_time and end_time must be provided together.")
        start_dt = _parse_datetime(start_time, timezone_name)
        end_dt = _parse_datetime(end_time, timezone_name)
        return start_dt, end_dt
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValidationError(f"Timezone '{timezone_name}' is unavailable.") from exc
    now_local = datetime.now(tz)
    start_dt = datetime(
        now_local.year,
        now_local.month,
        now_local.day,
        2,
        0,
        tzinfo=tz,
    ) + timedelta(days=1)
    end_dt = start_dt + timedelta(hours=1)
    return start_dt, end_dt


async def _run_reservation_flow(
    provider: Any,
    *,
    license_plate: str,
    reservation_name: str | None,
    start_time: str | None,
    end_time: str | None,
    extend_minutes: int,
    timezone_name: str,
    post_create_wait: int,
) -> None:
    try:
        start_dt, end_dt = _build_reservation_window(
            start_time,
            end_time,
            timezone_name=timezone_name,
        )
    except ValidationError as exc:
        print(f"Reservation time error: {exc}", file=sys.stderr)
        return

    try:
        created = await provider.start_reservation(
            license_plate,
            start_dt,
            end_dt,
            name=reservation_name,
        )
        print(f"Reservation created: {_format_reservation(created)}")
    except Exception as exc:
        print(f"Reservation create failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return
    if post_create_wait > 0:
        await asyncio.sleep(post_create_wait)
    try:
        active = await provider.list_reservations()
        print(f"Reservations after create: {len(active)}")
        for reservation in active:
            print(f"- {_format_reservation(reservation)}")
    except Exception as exc:
        print(f"Reservation list failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)

    updated_end = end_dt + timedelta(minutes=extend_minutes)
    try:
        updated = await provider.update_reservation(created.id, end_time=updated_end)
        print(f"Reservation updated: {_format_reservation(updated)}")
        created = updated
        end_dt = updated_end
    except ProviderError as exc:
        print(f"Reservation update skipped: {exc}")
    except Exception as exc:
        print(f"Reservation update failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    try:
        ended = await provider.end_reservation(created.id, end_dt)
        print(f"Reservation ended: {_format_reservation(ended)}")
    except Exception as exc:
        print(f"Reservation end failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)


async def _run_favorite_flow(
    provider: Any,
    *,
    license_plate: str,
    favorite_name: str | None,
    post_create_wait: int,
) -> None:
    async def _print_favorites(label: str) -> None:
        try:
            favorites = await provider.list_favorites()
        except Exception as exc:
            print(
                f"Favorite list failed ({label}): {exc.__class__.__name__}: {exc}", file=sys.stderr
            )
            return
        print(f"Favorites {label}: {len(favorites)}")
        for favorite in favorites:
            print(f"- {_format_favorite(favorite)}")

    try:
        created = await provider.add_favorite(license_plate, name=favorite_name)
        print(f"Favorite created: {_format_favorite(created)}")
    except Exception as exc:
        print(f"Favorite create failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        return
    if post_create_wait > 0:
        await asyncio.sleep(post_create_wait)
    await _print_favorites("after create")

    updated_name = f"{created.name or favorite_name or 'Favorite'} (updated)"
    if getattr(provider, "favorite_update_possible", False):
        try:
            updated = await provider.update_favorite(
                created.id,
                license_plate=created.license_plate,
                name=updated_name,
            )
            print(f"Favorite updated: {_format_favorite(updated)}")
            created = updated
        except Exception as exc:
            print(f"Favorite update failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    else:
        print("Favorite update skipped: updates are not supported.")
    await _print_favorites("after update")

    try:
        await provider.remove_favorite(created.id)
        print(f"Favorite removed: {created.id}")
    except Exception as exc:
        print(f"Favorite remove failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    await _print_favorites("after remove")


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
    run_reservations = args.run_all or args.run_reservations
    run_favorites = args.run_all or args.run_favorites
    license_plate = args.license_plate or os.getenv("LICENSE_PLATE")

    provider_id = _require_value("provider_id", provider_id)
    base_url = _require_value("base_url", base_url)
    if username and password:
        credentials = {"username": username, "password": password}
    else:
        credentials = _load_credentials(credentials_json, credentials_file)
    if extras:
        credentials.update(extras)
    if (run_reservations or run_favorites) and not license_plate:
        print("Missing required value: license_plate", file=sys.stderr)
        return 2

    try:
        async with Client(base_url=base_url, api_uri=api_uri) as client:
            provider = await client.get_provider(provider_id)
            await provider.login(credentials=credentials)
            permit = await provider.get_permit()
            reservations = await provider.list_reservations()
            favorites = await provider.list_favorites()
            if run_reservations:
                await _run_reservation_flow(
                    provider,
                    license_plate=license_plate,
                    reservation_name=args.reservation_name,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    extend_minutes=args.extend_minutes,
                    timezone_name=args.timezone,
                    post_create_wait=args.post_create_wait,
                )
            if run_favorites:
                await _run_favorite_flow(
                    provider,
                    license_plate=license_plate,
                    favorite_name=args.favorite_name,
                    post_create_wait=args.post_create_wait,
                )
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
