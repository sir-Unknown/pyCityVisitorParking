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


def normalize_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationError("Timestamp must be a datetime.")
    if value.tzinfo is None:
        raise ValidationError("Timestamp must include timezone information.")
    return value.astimezone(UTC).replace(microsecond=0)


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValidationError("Timestamp must be a non-empty string.")
    raw = value.strip()
    if not raw:
        raise ValidationError("Timestamp must be a non-empty string.")
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError("Timestamp is not a valid ISO 8601 value.") from exc
    return normalize_datetime(parsed)


def format_utc_timestamp(value: datetime) -> str:
    normalized = normalize_datetime(value)
    return normalized.isoformat().replace("+00:00", "Z")


def ensure_utc_timestamp(value: str) -> str:
    normalized = parse_timestamp(value)
    return normalized.isoformat().replace("+00:00", "Z")


@overload
def validate_reservation_times(
    start_time: datetime,
    end_time: datetime,
    *,
    require_both: Literal[True],
) -> tuple[datetime, datetime]: ...


@overload
def validate_reservation_times(
    start_time: datetime | None,
    end_time: datetime | None,
    *,
    require_both: Literal[False],
) -> tuple[datetime | None, datetime | None]: ...


def validate_reservation_times(
    start_time: datetime | None,
    end_time: datetime | None,
    *,
    require_both: bool,
) -> tuple[datetime | None, datetime | None]:
    if require_both and (start_time is None or end_time is None):
        raise ValidationError("start_time and end_time are required.")
    if start_time is not None and not isinstance(start_time, datetime):
        raise ValidationError("start_time must be a timezone-aware datetime.")
    if end_time is not None and not isinstance(end_time, datetime):
        raise ValidationError("end_time must be a timezone-aware datetime.")
    start_dt = normalize_datetime(start_time) if start_time is not None else None
    end_dt = normalize_datetime(end_time) if end_time is not None else None
    if start_dt and end_dt and end_dt <= start_dt:
        raise ValidationError("end_time must be after start_time.")
    return start_dt, end_dt


def filter_chargeable_zone_validity(
    entries: Iterable[tuple[ZoneValidityBlock, bool]],
) -> list[ZoneValidityBlock]:
    return [block for block, is_chargeable in entries if is_chargeable]
