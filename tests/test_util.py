from datetime import UTC, datetime, timedelta, timezone

import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import ZoneValidityBlock
from pycityvisitorparking.util import (
    ensure_utc_timestamp,
    filter_chargeable_zone_validity,
    format_utc_timestamp,
    normalize_datetime,
    normalize_license_plate,
    validate_reservation_times,
)


def test_normalize_license_plate() -> None:
    assert normalize_license_plate(" ab-12 cd ") == "AB12CD"


def test_normalize_license_plate_invalid() -> None:
    with pytest.raises(ValidationError):
        normalize_license_plate("!!!")


def test_format_utc_timestamp_converts_offset() -> None:
    dt = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert format_utc_timestamp(dt) == "2024-01-01T10:00:00Z"


def test_ensure_utc_timestamp() -> None:
    assert ensure_utc_timestamp("2024-01-01T12:00:00+02:00") == "2024-01-01T10:00:00Z"


def test_ensure_utc_timestamp_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        ensure_utc_timestamp(datetime(2024, 1, 1, 12, 0))


def test_ensure_utc_timestamp_rejects_naive_string() -> None:
    with pytest.raises(ValidationError):
        ensure_utc_timestamp("2024-01-01T12:00:00")


def test_format_utc_timestamp_truncates_microseconds() -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
    assert format_utc_timestamp(dt) == "2024-01-01T12:00:00Z"


def test_validate_reservation_times() -> None:
    with pytest.raises(ValidationError):
        start = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
        validate_reservation_times(
            start,
            end,
            require_both=True,
        )


def test_validate_reservation_times_accepts_datetime() -> None:
    start = datetime(2024, 1, 1, 10, 0, tzinfo=timezone(timedelta(hours=1)))
    end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=1)))
    start_norm, end_norm = validate_reservation_times(start, end, require_both=True)
    assert start_norm == datetime(2024, 1, 1, 9, 0, tzinfo=UTC)
    assert end_norm == datetime(2024, 1, 1, 11, 0, tzinfo=UTC)


def test_validate_reservation_times_rejects_string() -> None:
    with pytest.raises(ValidationError):
        validate_reservation_times(
            "2024-01-01T10:00:00Z",
            datetime(2024, 1, 1, 12, 0, tzinfo=UTC),
            require_both=True,
        )


def test_normalize_datetime_truncates_microseconds() -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)
    assert normalize_datetime(dt) == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_normalize_datetime_rejects_naive() -> None:
    with pytest.raises(ValidationError):
        normalize_datetime(datetime(2024, 1, 1, 12, 0))


def test_filter_chargeable_zone_validity() -> None:
    blocks = [
        (ZoneValidityBlock("2024-01-01T08:00:00Z", "2024-01-01T10:00:00Z"), True),
        (ZoneValidityBlock("2024-01-01T10:00:00Z", "2024-01-01T12:00:00Z"), False),
    ]
    filtered = filter_chargeable_zone_validity(blocks)
    assert filtered == [blocks[0][0]]
