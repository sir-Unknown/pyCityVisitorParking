"""Tests for the demo provider's reservation target behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import ReservationTarget
from pycityvisitorparking.provider.demo import Provider
from pycityvisitorparking.provider.loader import ProviderManifest

# Friday 13 November 2026, 10:00 in Amsterdam.
NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _provider(city: str) -> Provider:
    provider = Provider(
        object(),  # type: ignore[arg-type]
        ProviderManifest(
            id="demo",
            name="Demo",
            favorite_update_fields=("license_plate", "name"),
            reservation_update_fields=("start_time", "end_time"),
            reservation_target_selection="list",
        ),
    )
    provider.set_request_context(city)
    provider._now = lambda: NOW  # type: ignore[method-assign]
    return provider


@pytest.mark.asyncio
async def test_rotterdam_demo_targets_have_their_own_paid_hours() -> None:
    provider = _provider("Rotterdam Demo")
    targets = await provider.list_reservation_targets()
    assert [target.id for target in targets] == ["10", "630", "632"]
    zone_10, zone_630, zone_632 = targets

    def windows(target: ReservationTarget, count: int) -> list[tuple[str, str]]:
        return [(w.start_time, w.end_time) for w in target.paid_hours[:count]]

    # Friday to Sunday; local times are UTC+1. Zone 10 is paid until 01:00 on Friday
    # and Saturday, 630 has shorter days, 632 is free on Sunday.
    assert windows(zone_10, 3) == [
        ("2026-11-13T08:00:00Z", "2026-11-14T00:00:00Z"),
        ("2026-11-14T08:00:00Z", "2026-11-15T00:00:00Z"),
        ("2026-11-15T11:00:00Z", "2026-11-15T22:00:00Z"),
    ]
    assert windows(zone_630, 3) == [
        ("2026-11-13T08:00:00Z", "2026-11-13T20:00:00Z"),
        ("2026-11-14T08:00:00Z", "2026-11-14T20:00:00Z"),
        ("2026-11-15T12:00:00Z", "2026-11-15T17:00:00Z"),
    ]
    assert windows(zone_632, 3) == [
        ("2026-11-13T07:00:00Z", "2026-11-13T17:00:00Z"),
        ("2026-11-14T09:00:00Z", "2026-11-14T16:00:00Z"),
        ("2026-11-16T07:00:00Z", "2026-11-16T17:00:00Z"),
    ]
    assert (await provider.get_permit()).paid_hours == zone_10.paid_hours


@pytest.mark.asyncio
async def test_rotterdam_demo_books_in_the_requested_or_default_target() -> None:
    provider = _provider("Rotterdam Demo")
    start, end = NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    chosen = await provider.start_reservation("AB12CD", start, end, reservation_target_id="630")
    default = await provider.start_reservation("AB12CD", start, end)
    assert (chosen.reservation_target_id, default.reservation_target_id) == ("630", "10")
    with pytest.raises(ValidationError):
        await provider.start_reservation("AB12CD", start, end, reservation_target_id="999")
    reservations = await provider.list_reservations()
    assert {r.reservation_target_id for r in reservations} >= {"630", "10"}


@pytest.mark.asyncio
async def test_other_demo_permits_have_no_targets() -> None:
    provider = _provider("Den Haag Demo")
    assert await provider.list_reservation_targets() == []
    assert all(r.reservation_target_id is None for r in await provider.list_reservations())
    with pytest.raises(ValidationError):
        await provider.start_reservation(
            "AB12CD",
            NOW + timedelta(hours=1),
            NOW + timedelta(hours=2),
            reservation_target_id="10",
        )
