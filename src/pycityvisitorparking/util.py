"""Shared utilities for validation and normalization."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal, overload

from .exceptions import ValidationError
from .models import ZoneValidityBlock

_LICENSE_PLATE_RE = re.compile(r"[^A-Z0-9]")


def normalize_license_plate(plate: str) -> str:
    if not isinstance(plate, str):
        raise ValidationError("License plate must be a string.")
    normalized = _LICENSE_PLATE_RE.sub("", plate.upper())
    if not normalized:
        raise ValidationError("License plate is empty after normalization.")
    return normalized


def mask_license_plate(plate: str) -> str:
    if not isinstance(plate, str):
        return "***"
    normalized = _LICENSE_PLATE_RE.sub("", plate.upper())
    if not normalized:
        return "***"
    if len(normalized) <= 2:
        return "*" * len(normalized)
    if len(normalized) <= 4:
        return f"{normalized[:1]}{'*' * (len(normalized) - 2)}{normalized[-1:]}"
    masked = "*" * (len(normalized) - 4)
    return f"{normalized[:2]}{masked}{normalized[-2:]}"


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValidationError("Timestamp must be a non-empty string.")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError("Timestamp is not a valid ISO 8601 value.") from exc
    if parsed.tzinfo is None:
        raise ValidationError("Timestamp must include timezone information.")
    return parsed.astimezone(UTC)


def format_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValidationError("Timestamp must include timezone information.")
    normalized = value.astimezone(UTC).replace(microsecond=0)
    return normalized.isoformat().replace("+00:00", "Z")


def ensure_utc_timestamp(value: str) -> str:
    return format_utc_timestamp(parse_timestamp(value))


@overload
def validate_reservation_times(
    start_time: str,
    end_time: str,
    *,
    require_both: Literal[True],
) -> tuple[str, str]: ...


@overload
def validate_reservation_times(
    start_time: str | None,
    end_time: str | None,
    *,
    require_both: Literal[False],
) -> tuple[str | None, str | None]: ...


def validate_reservation_times(
    start_time: str | None,
    end_time: str | None,
    *,
    require_both: bool,
) -> tuple[str | None, str | None]:
    if require_both and (start_time is None or end_time is None):
        raise ValidationError("start_time and end_time are required.")
    start_dt = parse_timestamp(start_time) if start_time is not None else None
    end_dt = parse_timestamp(end_time) if end_time is not None else None
    if start_dt and end_dt and end_dt <= start_dt:
        raise ValidationError("end_time must be after start_time.")
    start_normalized = format_utc_timestamp(start_dt) if start_dt else None
    end_normalized = format_utc_timestamp(end_dt) if end_dt else None
    return start_normalized, end_normalized


def filter_chargeable_zone_validity(
    entries: Iterable[tuple[ZoneValidityBlock, bool]],
) -> list[ZoneValidityBlock]:
    return [block for block, is_chargeable in entries if is_chargeable]
