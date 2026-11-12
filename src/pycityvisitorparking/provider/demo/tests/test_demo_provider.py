"""Tests for the demo provider's zone behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import Zone
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
            zone_selection=True,
        ),
    )
    provider.set_request_context(city)
    provider._now = lambda: NOW  # type: ignore[method-assign]
    return provider


@pytest.mark.asyncio
async def test_rotterdam_demo_zones_have_their_own_paid_hours() -> None:
    permit = await _provider("Rotterdam Demo").get_permit()
    assert [zone.id for zone in permit.zones] == ["10", "630", "632"]
    zone_10, zone_630, zone_632 = permit.zones

    def windows(zone: Zone, count: int) -> list[tuple[str, str]]:
        return [(w.start_time, w.end_time) for w in zone.zone_validity[:count]]

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
    assert permit.zone_validity == zone_10.zone_validity


@pytest.mark.asyncio
async def test_rotterdam_demo_books_in_the_requested_or_default_zone() -> None:
    provider = _provider("Rotterdam Demo")
    start, end = NOW + timedelta(hours=1), NOW + timedelta(hours=2)
    chosen = await provider.start_reservation("AB12CD", start, end, zone_id="630")
    default = await provider.start_reservation("AB12CD", start, end)
    assert (chosen.zone_id, default.zone_id) == ("630", "10")
    with pytest.raises(ValidationError):
        await provider.start_reservation("AB12CD", start, end, zone_id="999")
    assert {r.zone_id for r in await provider.list_reservations()} >= {"630", "10"}


@pytest.mark.asyncio
async def test_other_demo_permits_have_no_zones() -> None:
    provider = _provider("Den Haag Demo")
    permit = await provider.get_permit()
    assert permit.zones == []
    assert all(r.zone_id is None for r in await provider.list_reservations())
    with pytest.raises(ValidationError):
        await provider.start_reservation(
            "AB12CD", NOW + timedelta(hours=1), NOW + timedelta(hours=2), zone_id="10"
        )
