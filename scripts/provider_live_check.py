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

When --sanitize-output is enabled, the script avoids printing full license plates.
Debug helpers:
  --debug-http prints request/response summaries (sanitized with --sanitize-output).
  --dump-json prints request/response JSON payloads (sanitized with --sanitize-output).
  --dump-dir writes request/response JSON to a single run file
              (sanitized with --sanitize-output).
  --traceback prints full tracebacks on errors.
  --sanitize-output sanitizes privacy-sensitive output.

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
import logging
import os
import sys
import time
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from sanitize import mask_license_plate as _mask_license_plate
from sanitize import sanitize_data as _sanitize_data
from sanitize import sanitize_headers as _sanitize_headers

from pycityvisitorparking import Client
from pycityvisitorparking.exceptions import ProviderError, ValidationError
from pycityvisitorparking.models import Favorite, Reservation

_LOGGER = logging.getLogger(__name__)
_TEXT_TRUNCATE = 2000
_ANSI_STYLES = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "cyan": "\x1b[36m",
    "magenta": "\x1b[35m",
}
_COLOR_ENABLED = False


def _require_value(name: str, value: str | None) -> str:
    if not value:
        print(f"Missing required value: {name}", file=sys.stderr)
        raise SystemExit(2)
    return value


def _style(text: str, color: str | None = None, *, bold: bool = False) -> str:
    if not _COLOR_ENABLED or not color:
        return text
    color_code = _ANSI_STYLES.get(color)
    if not color_code:
        return text
    prefix = _ANSI_STYLES["bold"] if bold else ""
    return f"{prefix}{color_code}{text}{_ANSI_STYLES['reset']}"


def _format_action(label: str, value: str, *, color: str | None = None) -> str:
    return f"{_style(label, color, bold=True)}: {value}"


def _truncate_text(value: str, limit: int) -> str:
    if limit <= 0 or len(value) <= limit:
        return value
    return f"{value[:limit]}... [truncated]"


def _normalize_debug_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalize_debug_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_debug_value(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_debug_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", "backslashreplace")
    if isinstance(value, Path):
        return str(value)
    return value


def _print_exception(label: str, exc: Exception, *, trace: bool) -> None:
    styled_label = _style(label, "red", bold=True)
    print(f"{styled_label}: {exc.__class__.__name__}: {exc}", file=sys.stderr)
    if trace:
        traceback.print_exc()


def _normalize_plate_for_compare(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.upper() if ch.isascii() and ch.isalnum())


def _build_favorite_name(license_plate: str, favorite_name: str | None) -> str:
    normalized_plate = _normalize_plate_for_compare(license_plate)
    name_value = favorite_name.strip() if isinstance(favorite_name, str) else ""
    if not name_value:
        suffix = normalized_plate[-4:] if normalized_plate else ""
        name_value = f"Favorite {suffix}".strip()
    if _normalize_plate_for_compare(name_value) == normalized_plate:
        name_value = f"{name_value}-fav"
    return name_value


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


def _format_reservation(reservation: Reservation, *, sanitize: bool = False) -> str:
    data = {
        "id": reservation.id,
        "name": reservation.name or "-",
        "license_plate": reservation.license_plate,
        "start_time": reservation.start_time,
        "end_time": reservation.end_time,
    }
    if sanitize:
        data = _sanitize_data(data)
    return (
        f"{data['id']} | {data['name']} | {data['license_plate']} | "
        f"{data['start_time']} -> {data['end_time']}"
    )


def _format_favorite(favorite: Favorite, *, sanitize: bool = False) -> str:
    data = {
        "id": favorite.id,
        "name": favorite.name or "-",
        "license_plate": favorite.license_plate,
    }
    if sanitize:
        data = _sanitize_data(data)
    return f"{data['id']} | {data['name']} | {data['license_plate']}"


class _DebugRecorder:
    def __init__(
        self,
        *,
        enabled: bool,
        dump_json: bool,
        dump_dir: Path | None,
        max_text: int,
        sanitize_output: bool,
    ) -> None:
        self._enabled = enabled
        self._dump_json = dump_json
        self._dump_dir = dump_dir
        self._max_text = max_text
        self._sanitize_output = sanitize_output
        self._counter = 0
        self._run_id = time.strftime("%Y%m%d-%H%M%S")
        if dump_dir:
            self._run_id = f"{self._run_id}-{os.getpid()}"
        self._requests: dict[str, dict[str, Any]] = {}
        self._run_entries: dict[str, dict[str, Any]] = {}
        if self._dump_dir:
            self._dump_dir.mkdir(parents=True, exist_ok=True)

    def start_request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, Any],
        params: Mapping[str, Any] | None,
        json_payload: Any | None,
        data_payload: Any | None,
    ) -> str:
        self._counter += 1
        request_id = f"{self._counter:04d}"
        if self._sanitize_output:
            headers_value = _sanitize_headers(headers)
            params_value = _sanitize_data(params) if params else None
            json_value = _sanitize_data(json_payload) if json_payload is not None else None
            data_value = _sanitize_data(data_payload) if data_payload is not None else None
        else:
            headers_value = _normalize_debug_value(headers)
            params_value = _normalize_debug_value(params) if params else None
            json_value = _normalize_debug_value(json_payload) if json_payload is not None else None
            data_value = _normalize_debug_value(data_payload) if data_payload is not None else None
        entry = {
            "id": request_id,
            "method": method,
            "url": url,
            "headers": headers_value,
            "params": params_value,
            "json": json_value,
            "data": data_value,
            "started_at": time.monotonic(),
        }
        self._requests[request_id] = entry
        if self._enabled:
            print(f"[HTTP] -> {method} {url}", file=sys.stderr)
        if self._dump_json:
            self._print_json(request_id, "request", entry)
        self._write_dump(request_id, "request", entry)
        return request_id

    def record_response(
        self,
        request_id: str,
        *,
        status: int,
        headers: Mapping[str, Any],
        json_body: Any | None = None,
        text_body: str | None = None,
        error: Exception | None = None,
    ) -> None:
        entry = self._requests.get(request_id, {})
        elapsed_ms = None
        if "started_at" in entry:
            elapsed_ms = int((time.monotonic() - entry["started_at"]) * 1000)
        if self._sanitize_output:
            headers_value = _sanitize_headers(headers)
            json_value = _sanitize_data(json_body) if json_body is not None else None
        else:
            headers_value = _normalize_debug_value(headers)
            json_value = _normalize_debug_value(json_body) if json_body is not None else None
        response_entry = {
            "id": request_id,
            "status": status,
            "headers": headers_value,
            "elapsed_ms": elapsed_ms,
            "json": json_value,
            "text": _truncate_text(text_body, self._max_text) if text_body else None,
            "error": f"{error.__class__.__name__}: {error}" if error else None,
        }
        if self._enabled:
            status_text = f"{status}" if status is not None else "unknown"
            duration = f"{elapsed_ms}ms" if elapsed_ms is not None else "n/a"
            print(f"[HTTP] <- {status_text} ({duration})", file=sys.stderr)
        if self._dump_json:
            self._print_json(request_id, "response", response_entry)
        self._write_dump(request_id, "response", response_entry)

    def _print_json(self, request_id: str, label: str, payload: dict[str, Any]) -> None:
        dumped = json.dumps(payload, indent=2, sort_keys=True)
        mode = "sanitized" if self._sanitize_output else "raw"
        print(f"[RAW] {request_id} {label} ({mode}):\n{dumped}", file=sys.stderr)

    def _write_dump(self, request_id: str, label: str, payload: dict[str, Any]) -> None:
        if not self._dump_dir:
            return
        path = self._dump_dir / f"{self._run_id}.json"
        entry = self._run_entries.get(request_id)
        if not entry:
            entry = {"id": request_id}
            self._run_entries[request_id] = entry
        entry[label] = payload
        entries = [self._run_entries[key] for key in sorted(self._run_entries)]
        output = {"run_id": self._run_id, "entries": entries}
        path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")


class _DebugResponse:
    def __init__(
        self,
        response: aiohttp.ClientResponse,
        recorder: _DebugRecorder | None,
        request_id: str,
    ) -> None:
        self._response = response
        self._recorder = recorder
        self._request_id = request_id
        self._json_cache: Any | None = None
        self._text_cache: str | None = None
        self._json_cached = False
        self._text_cached = False
        self._recorded = False

    @property
    def status(self) -> int:
        return self._response.status

    @property
    def headers(self) -> Mapping[str, Any]:
        return self._response.headers

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    async def json(self, *args: Any, **kwargs: Any) -> Any:
        if self._json_cached:
            return self._json_cache
        try:
            data = await self._response.json(*args, **kwargs)
        except Exception as exc:
            if self._recorder:
                self._recorder.record_response(
                    self._request_id,
                    status=self._response.status,
                    headers=self._response.headers,
                    error=exc,
                )
                self._recorded = True
            raise
        self._json_cached = True
        self._json_cache = data
        if self._recorder and not self._recorded:
            self._recorder.record_response(
                self._request_id,
                status=self._response.status,
                headers=self._response.headers,
                json_body=data,
            )
            self._recorded = True
        return data

    async def text(self, *args: Any, **kwargs: Any) -> str:
        if self._text_cached:
            return self._text_cache or ""
        try:
            text = await self._response.text(*args, **kwargs)
        except Exception as exc:
            if self._recorder:
                self._recorder.record_response(
                    self._request_id,
                    status=self._response.status,
                    headers=self._response.headers,
                    error=exc,
                )
                self._recorded = True
            raise
        self._text_cached = True
        self._text_cache = text
        if self._recorder and not self._recorded:
            self._recorder.record_response(
                self._request_id,
                status=self._response.status,
                headers=self._response.headers,
                text_body=text,
            )
            self._recorded = True
        return text

    def record_if_missing(self) -> None:
        if self._recorded or not self._recorder:
            return
        self._recorder.record_response(
            self._request_id,
            status=self._response.status,
            headers=self._response.headers,
        )
        self._recorded = True


class _DebugResponseContext:
    def __init__(
        self,
        context: Any,
        recorder: _DebugRecorder | None,
        request_id: str,
    ) -> None:
        self._context = context
        self._recorder = recorder
        self._request_id = request_id

    async def __aenter__(self) -> _DebugResponse:
        response = await self._context.__aenter__()
        self._debug_response = _DebugResponse(response, self._recorder, self._request_id)
        return self._debug_response

    async def __aexit__(self, exc_type, exc, tb) -> Literal[False]:
        if getattr(self, "_debug_response", None):
            self._debug_response.record_if_missing()
        return await self._context.__aexit__(exc_type, exc, tb)


class _DebugSession:
    def __init__(self, session: aiohttp.ClientSession, recorder: _DebugRecorder | None) -> None:
        self._session = session
        self._recorder = recorder

    def request(self, method: str, url: str, **kwargs: Any) -> _DebugResponseContext:
        headers = kwargs.get("headers") or {}
        params = kwargs.get("params")
        json_payload = kwargs.get("json")
        data_payload = kwargs.get("data")
        request_id = "0000"
        if self._recorder:
            request_id = self._recorder.start_request(
                method=method,
                url=str(url),
                headers=headers,
                params=params,
                json_payload=json_payload,
                data_payload=data_payload,
            )
        context = self._session.request(method, url, **kwargs)
        return _DebugResponseContext(context, self._recorder, request_id)

    async def close(self) -> None:
        await self._session.close()

    @property
    def closed(self) -> bool:
        return self._session.closed

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


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
    parser.add_argument(
        "--debug-http",
        dest="debug_http",
        action="store_true",
        help="Print HTTP request/response summaries (sanitized with --sanitize-output).",
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        help="Print extra script debug details.",
    )
    parser.add_argument(
        "--dump-json",
        dest="dump_json",
        action="store_true",
        help="Print request/response JSON payloads (sanitized with --sanitize-output).",
    )
    parser.add_argument(
        "--dump-dir",
        dest="dump_dir",
        help="Write request/response JSON run files (sanitized with --sanitize-output).",
    )
    parser.add_argument(
        "--dump-limit",
        dest="dump_limit",
        type=int,
        default=_TEXT_TRUNCATE,
        help="Max characters for captured text responses (default: 2000).",
    )
    parser.add_argument(
        "--traceback",
        dest="traceback",
        action="store_true",
        help="Print full tracebacks on errors.",
    )
    parser.add_argument(
        "--color",
        dest="color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize output (default: auto).",
    )
    parser.add_argument(
        "--sanitize-output",
        dest="sanitize_output",
        action="store_true",
        help="Sanitize privacy-sensitive values in standard output.",
    )
    parser.add_argument(
        "--log-level",
        dest="log_level",
        default="INFO",
        help="Python log level for the script (default: INFO).",
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
    traceback_enabled: bool,
    debug_enabled: bool,
    sanitize_output: bool,
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

    if debug_enabled:
        start_utc = start_dt.astimezone(UTC)
        end_utc = end_dt.astimezone(UTC)
        plate_value = _mask_license_plate(license_plate) if sanitize_output else license_plate
        print(
            f"Reservation window (local): {start_dt.isoformat()} -> {end_dt.isoformat()}",
            file=sys.stderr,
        )
        print(
            f"Reservation window (UTC): {start_utc.isoformat()} -> {end_utc.isoformat()}",
            file=sys.stderr,
        )
        print(f"Reservation plate: {plate_value}", file=sys.stderr)

    try:
        created = await provider.start_reservation(
            license_plate,
            start_dt,
            end_dt,
            name=reservation_name,
        )
        print(
            _format_action(
                "Reservation created",
                _format_reservation(created, sanitize=sanitize_output),
                color="green",
            )
        )
    except Exception as exc:
        _print_exception("Reservation create failed", exc, trace=traceback_enabled)
        return
    if post_create_wait > 0:
        await asyncio.sleep(post_create_wait)
    try:
        active = await provider.list_reservations()
        print(_format_action("Reservations after create", str(len(active)), color="cyan"))
        for reservation in active:
            print(f"- {_format_reservation(reservation, sanitize=sanitize_output)}")
    except Exception as exc:
        _print_exception("Reservation list failed", exc, trace=traceback_enabled)

    updated_end = end_dt + timedelta(minutes=extend_minutes)
    try:
        updated = await provider.update_reservation(created.id, end_time=updated_end)
        print(
            _format_action(
                "Reservation updated",
                _format_reservation(updated, sanitize=sanitize_output),
                color="green",
            )
        )
        created = updated
        end_dt = updated_end
    except ProviderError as exc:
        print(_format_action("Reservation update skipped", str(exc), color="yellow"))
    except Exception as exc:
        _print_exception("Reservation update failed", exc, trace=traceback_enabled)
    try:
        ended = await provider.end_reservation(created.id, end_dt)
        print(
            _format_action(
                "Reservation ended",
                _format_reservation(ended, sanitize=sanitize_output),
                color="green",
            )
        )
    except Exception as exc:
        _print_exception("Reservation end failed", exc, trace=traceback_enabled)


async def _run_favorite_flow(
    provider: Any,
    *,
    license_plate: str,
    favorite_name: str | None,
    post_create_wait: int,
    traceback_enabled: bool,
    debug_enabled: bool,
    sanitize_output: bool,
) -> None:
    async def _print_favorites(label: str) -> None:
        try:
            favorites = await provider.list_favorites()
        except Exception as exc:
            _print_exception(
                f"Favorite list failed ({label})",
                exc,
                trace=traceback_enabled,
            )
            return
        print(_format_action(f"Favorites {label}", str(len(favorites)), color="cyan"))
        for favorite in favorites:
            print(f"- {_format_favorite(favorite, sanitize=sanitize_output)}")

    name_for_create = _build_favorite_name(license_plate, favorite_name)
    if debug_enabled:
        plate_value = _mask_license_plate(license_plate) if sanitize_output else license_plate
        print(f"Favorite plate: {plate_value}", file=sys.stderr)
    try:
        created = await provider.add_favorite(license_plate, name=name_for_create)
        print(
            _format_action(
                "Favorite created",
                _format_favorite(created, sanitize=sanitize_output),
                color="green",
            )
        )
    except Exception as exc:
        _print_exception("Favorite create failed", exc, trace=traceback_enabled)
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
            print(
                _format_action(
                    "Favorite updated",
                    _format_favorite(updated, sanitize=sanitize_output),
                    color="green",
                )
            )
            created = updated
        except Exception as exc:
            _print_exception("Favorite update failed", exc, trace=traceback_enabled)
    else:
        print(
            _format_action("Favorite update skipped", "updates are not supported", color="yellow")
        )
    await _print_favorites("after update")

    try:
        await provider.remove_favorite(created.id)
        print(_format_action("Favorite removed", created.id, color="green"))
    except Exception as exc:
        _print_exception("Favorite remove failed", exc, trace=traceback_enabled)
    await _print_favorites("after remove")


async def main() -> int:
    args = _parse_args()
    log_level = args.log_level.upper()
    if args.debug and log_level == "INFO":
        log_level = "DEBUG"
    logging.basicConfig(level=log_level)
    global _COLOR_ENABLED
    if args.color == "always":
        _COLOR_ENABLED = True
    elif args.color == "never":
        _COLOR_ENABLED = False
    else:
        _COLOR_ENABLED = sys.stdout.isatty() or sys.stderr.isatty()
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

    if args.debug:
        plate_value = (
            _mask_license_plate(license_plate or "") if args.sanitize_output else license_plate
        )
        if not plate_value:
            plate_value = "-"
        print(
            "Debug config: "
            f"provider_id={provider_id} base_url={base_url} api_uri={api_uri} "
            f"run_reservations={run_reservations} run_favorites={run_favorites} "
            f"license_plate={plate_value}",
            file=sys.stderr,
        )
        key_list = ", ".join(sorted(credentials.keys())) if credentials else "-"
        print(f"Credential keys: {key_list}", file=sys.stderr)

    recorder = _DebugRecorder(
        enabled=args.debug_http or args.dump_json or bool(args.dump_dir),
        dump_json=args.dump_json,
        dump_dir=Path(args.dump_dir) if args.dump_dir else None,
        max_text=args.dump_limit,
        sanitize_output=args.sanitize_output,
    )
    debug_session: _DebugSession | None = None
    if recorder._enabled:
        session = aiohttp.ClientSession()
        debug_session = _DebugSession(session, recorder)
        mode = "sanitized" if args.sanitize_output else "raw"
        _LOGGER.info("HTTP debug enabled (%s output).", mode)

    try:
        async with Client(
            session=debug_session,
            base_url=base_url,
            api_uri=api_uri,
        ) as client:
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
                    traceback_enabled=args.traceback,
                    debug_enabled=args.debug,
                    sanitize_output=args.sanitize_output,
                )
            if run_favorites:
                await _run_favorite_flow(
                    provider,
                    license_plate=license_plate,
                    favorite_name=args.favorite_name,
                    post_create_wait=args.post_create_wait,
                    traceback_enabled=args.traceback,
                    debug_enabled=args.debug,
                    sanitize_output=args.sanitize_output,
                )
    except Exception as exc:
        _print_exception("Error", exc, trace=args.traceback)
        return 1
    finally:
        if debug_session:
            await debug_session.close()

    provider_info = provider.info
    print(
        _format_action(
            "Provider",
            f"{provider.provider_name} ({provider.provider_id}) | "
            f"favorite_update_fields={provider_info.favorite_update_fields} | "
            f"reservation_update_fields={provider_info.reservation_update_fields}",
            color="cyan",
        )
    )
    print(_format_action("Permit", str(permit), color="cyan"))
    print(_format_action("Reservations", str(len(reservations)), color="cyan"))
    for reservation in reservations:
        print(f"- {_format_reservation(reservation, sanitize=args.sanitize_output)}")
    print(_format_action("Favorites", str(len(favorites)), color="cyan"))
    for favorite in favorites:
        print(f"- {_format_favorite(favorite, sanitize=args.sanitize_output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
