"""Demo provider — returns hardcoded mock data, no network calls."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ...exceptions import ProviderError, ValidationError
from ...models import Favorite, PaidHoursBlock, Permit, Reservation, ReservationTarget
from ...util import parse_timestamp
from ..base import BaseProvider

_LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

_FAVORITES_BY_CITY: dict[str, list[dict[str, str]]] = {
    "groningen": [
        {"id": "g1", "name": "Jan de Vries", "license_plate": "GN-24-XR"},
        {"id": "g2", "name": "Sophie Bakker", "license_plate": "TZ-881-V"},
        {"id": "g3", "name": "Lucas Dijkstra", "license_plate": "KL-55-BN"},
        {"id": "g4", "name": "Emma Hoffmann", "license_plate": "RX-19-ZT"},
        {"id": "g5", "name": "Noor van den Berg", "license_plate": "GH-072-K"},
        {"id": "g6", "name": "Thomas Mulder", "license_plate": "VB-334-J"},
        {"id": "g7", "name": "Roos Smit", "license_plate": "NP-61-GW"},
        {"id": "g8", "name": "Kevin Brouwer", "license_plate": "LS-48-FD"},
        {"id": "g9", "name": "Anouk Visser", "license_plate": "DP-909-X"},
        {"id": "g10", "name": "Daan Hendriks", "license_plate": "QT-77-MN"},
    ],
    "den haag": [
        {"id": "h1", "name": "Pieter de Groot", "license_plate": "SH-321-R"},
        {"id": "h2", "name": "Lena Jansen", "license_plate": "BK-06-WZ"},
        {"id": "h3", "name": "Fatima el-Amin", "license_plate": "ZG-188-P"},
        {"id": "h4", "name": "Boris Kuiper", "license_plate": "FK-867-T"},
        {"id": "h5", "name": "Mila Fonteijn", "license_plate": "PR-53-XJ"},
    ],
    "eindhoven": [
        {"id": "e1", "name": "Lars Martens", "license_plate": "EV-112-B"},
        {"id": "e2", "name": "Charlotte Prins", "license_plate": "HD-77-RP"},
        {"id": "e3", "name": "Naomi Scholten", "license_plate": "WL-84-GF"},
        {"id": "e4", "name": "Dylan Aerts", "license_plate": "NG-66-CT"},
        {"id": "e5", "name": "Zoë Hermans", "license_plate": "KV-43-WM"},
        {"id": "e6", "name": "Robin Claes", "license_plate": "PF-812-S"},
        {"id": "e7", "name": "Fleur Verstegen", "license_plate": "TX-37-HN"},
    ],
    "rotterdam": [
        {"id": "r1", "name": "Sanne Bosman", "license_plate": "RT-502-K"},
        {"id": "r2", "name": "Youssef Amrani", "license_plate": "MZ-118-D"},
        {"id": "r3", "name": "Bram Koster", "license_plate": "KX-73-PL"},
        {"id": "r4", "name": "Ilse Verbeek", "license_plate": "HB-904-S"},
    ],
    "default": [
        {"id": "d1", "name": "Demo Gebruiker", "license_plate": "XX-000-X"},
    ],
}

# Paid hours per weekday (Monday first) in Europe/Amsterdam; None means free all day.
# An end at or before the start ends on the next day.
type _WeekSchedule = tuple[tuple[time, time] | None, ...]

_DAY = (time(9), time(23))
# Rotterdam demo zones with deliberately different paid hours; the first one is the
# default zone. Zone 10 mirrors the real zone 10 (Friday and Saturday until 01:00).
_ROTTERDAM_ZONES: tuple[tuple[str, _WeekSchedule], ...] = (
    ("10", (_DAY, _DAY, _DAY, _DAY, (time(9), time(1)), (time(9), time(1)), (time(12), time(23)))),
    ("630", ((time(9), time(21)),) * 6 + ((time(13), time(18)),)),
    ("632", ((time(8), time(18)),) * 5 + ((time(10), time(17)), None)),
)

_RESERVATIONS: list[dict[str, str]] = [
    {
        "id": "res-1",
        "name": "Sophie Bakker",
        "license_plate": "TZ881V",
        "start_time": "2026-04-15T08:30:00Z",
        "end_time": "2026-04-15T14:00:00Z",
    },
    {
        "id": "res-2",
        "name": "Fatima el-Amin",
        "license_plate": "ZG188P",
        "start_time": "2026-04-15T10:00:00Z",
        "end_time": "2026-04-15T18:00:00Z",
    },
    {
        "id": "res-3",
        "name": "Dylan Aerts",
        "license_plate": "NG66CT",
        "start_time": "2026-04-15T09:15:00Z",
        "end_time": "2026-04-15T12:30:00Z",
    },
]


class Provider(BaseProvider):
    """Demo provider that returns hardcoded data without making network requests."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._favorites: list[dict[str, str]] | None = None
        self._reservations: list[dict[str, str | None]] | None = None

    def _get_favorites(self) -> list[dict[str, str]]:
        """Lazy-initialize favorites so the city context is available."""
        if self._favorites is None:
            city = (self._request_context_name or "").lower()
            source = next(
                (favs for key, favs in _FAVORITES_BY_CITY.items() if key in city),
                _FAVORITES_BY_CITY["default"],
            )
            self._favorites = [dict(f) for f in source]
        return self._favorites

    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        """No-op — demo provider needs no authentication."""

    def _demo_permit_config(self) -> dict:
        """Return per-city permit configuration based on municipality name."""
        city = (self._request_context_name or "").lower()
        if "groningen" in city:
            return {
                "remaining_balance": 237.50,
                "balance_unit": "EURO",
                "zone_start": "2026-04-15T08:00:00Z",
                "zone_end": "2026-04-15T20:00:00Z",
            }
        if "den haag" in city or "haag" in city:
            return {
                "remaining_balance": 480,
                "balance_unit": "MINUTE",
                "zone_start": "2026-04-15T09:00:00Z",
                "zone_end": "2026-04-15T23:00:00Z",
            }
        if "eindhoven" in city:
            return {
                "remaining_balance": 12.75,
                "balance_unit": "EURO",
                "zone_start": "2026-04-15T07:30:00Z",
                "zone_end": "2026-04-15T18:30:00Z",
            }
        if self._is_rotterdam():
            # Windows come from the zones (see ``_zones``).
            return {
                "remaining_balance": 10450,
                "balance_unit": "MINUTE",
                "zone_start": "",
                "zone_end": "",
            }
        # fallback
        return {
            "remaining_balance": 100.0,
            "balance_unit": "EURO",
            "zone_start": "2026-04-15T08:00:00Z",
            "zone_end": "2026-04-15T20:00:00Z",
        }

    async def get_permit(self) -> Permit:
        cfg = self._demo_permit_config()
        targets = await self.list_reservation_targets()
        return Permit(
            id="demo-permit",
            remaining_balance=cfg["remaining_balance"],
            balance_unit=cfg["balance_unit"],
            # With targets, the permit-level windows are those of the default target.
            paid_hours=targets[0].paid_hours
            if targets
            else [PaidHoursBlock(start_time=cfg["zone_start"], end_time=cfg["zone_end"])],
        )

    def _is_rotterdam(self) -> bool:
        return "rotterdam" in (self._request_context_name or "").lower()

    def _now(self) -> datetime:
        return datetime.now(UTC)

    async def list_reservation_targets(self) -> list[ReservationTarget]:
        """Return the demo targets; only the Rotterdam demo permit has any."""
        if not self._is_rotterdam():
            return []
        return [
            ReservationTarget(
                id=zone_id,
                name=zone_id,
                paid_hours=self._rotterdam_windows(schedule),
            )
            for zone_id, schedule in _ROTTERDAM_ZONES
        ]

    def _rotterdam_windows(self, schedule: _WeekSchedule) -> list[PaidHoursBlock]:
        """Return the upcoming paid windows of a Rotterdam demo zone for one week.

        ``schedule`` holds the paid hours per weekday (Monday first) in
        Europe/Amsterdam; an end at or before the start ends on the next day.
        """
        now = self._now()
        today = now.astimezone(_LOCAL_TZ).date()
        windows: list[PaidHoursBlock] = []
        for offset in range(8):
            day = today + timedelta(days=offset)
            hours = schedule[day.weekday()]
            if hours is None:
                continue
            start = datetime.combine(day, hours[0], _LOCAL_TZ)
            end_day = day + timedelta(days=1) if hours[1] <= hours[0] else day
            end = datetime.combine(end_day, hours[1], _LOCAL_TZ)
            if end > now:
                windows.append(
                    PaidHoursBlock(
                        start_time=self._format_utc_timestamp(start),
                        end_time=self._format_utc_timestamp(end),
                    )
                )
        return windows

    def _get_reservations(self) -> list[dict[str, str | None]]:
        """Lazy-initialize reservations so the city context is available."""
        if self._reservations is None:
            if self._is_rotterdam():
                now = self._now().replace(second=0, microsecond=0)
                self._reservations = [
                    {
                        "id": "rot-1",
                        "name": "Sanne Bosman",
                        "license_plate": "RT502K",
                        "start_time": self._format_utc_timestamp(now - timedelta(minutes=30)),
                        "end_time": self._format_utc_timestamp(now + timedelta(hours=2)),
                        "reservation_target_id": "630",
                    },
                    {
                        "id": "rot-2",
                        "name": "Youssef Amrani",
                        "license_plate": "MZ118D",
                        "start_time": self._format_utc_timestamp(now + timedelta(days=1)),
                        "end_time": self._format_utc_timestamp(now + timedelta(days=1, hours=3)),
                        "reservation_target_id": "10",
                    },
                ]
            else:
                self._reservations = [{**r, "reservation_target_id": None} for r in _RESERVATIONS]
        return self._reservations

    async def list_reservations(self) -> list[Reservation]:
        return [self._map_reservation(r) for r in self._get_reservations()]

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
        reservation_target_id: str | None = None,
    ) -> Reservation:
        requested_target = self._validate_reservation_target_id(reservation_target_id)
        target_ids = [target.id for target in await self.list_reservation_targets()]
        if requested_target is not None and requested_target not in target_ids:
            raise ValidationError("reservation_target_id is not a target of the permit.")
        start_time, end_time = self._validate_reservation_times(
            start_time, end_time, require_both=True
        )
        record: dict[str, str | None] = {
            "id": str(uuid.uuid4()),
            "name": name or "",
            "license_plate": self._normalize_license_plate(license_plate),
            "start_time": self._format_utc_timestamp(self._normalize_datetime(start_time)),
            "end_time": self._format_utc_timestamp(self._normalize_datetime(end_time)),
            # Without a requested target the default (first) target is used.
            "reservation_target_id": requested_target or (target_ids[0] if target_ids else None),
        }
        self._get_reservations().append(record)
        return self._map_reservation(record)

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        for r in self._get_reservations():
            if r["id"] == reservation_id:
                effective_start = (
                    self._normalize_datetime(start_time)
                    if start_time is not None
                    else parse_timestamp(str(r["start_time"]))
                )
                effective_end = (
                    self._normalize_datetime(end_time)
                    if end_time is not None
                    else parse_timestamp(str(r["end_time"]))
                )
                self._validate_reservation_times(effective_start, effective_end, require_both=True)
                r["start_time"] = self._format_utc_timestamp(effective_start)
                r["end_time"] = self._format_utc_timestamp(effective_end)
                if name is not None:
                    r["name"] = name
                return self._map_reservation(r)
        raise ProviderError(f"Reservation {reservation_id!r} not found.")

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        reservations = self._get_reservations()
        for i, r in enumerate(reservations):
            if r["id"] == reservation_id:
                r["end_time"] = self._format_utc_timestamp(self._normalize_datetime(end_time))
                reservations.pop(i)
                return self._map_reservation(r)
        raise ProviderError(f"Reservation {reservation_id!r} not found.")

    def _map_reservation(self, r: dict[str, str | None]) -> Reservation:
        return Reservation(
            id=str(r["id"]),
            name=str(r["name"]),
            license_plate=self._normalize_license_plate(str(r["license_plate"])),
            start_time=str(r["start_time"]),
            end_time=str(r["end_time"]),
            reservation_target_id=r["reservation_target_id"],
        )

    async def list_favorites(self) -> list[Favorite]:
        return [
            Favorite(id=f["id"], name=f["name"], license_plate=f["license_plate"])
            for f in self._get_favorites()
        ]

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        normalized = self._normalize_license_plate(license_plate)
        favorite = Favorite(
            id=normalized,
            name=name or "",
            license_plate=normalized,
        )
        self._get_favorites().append(
            {"id": favorite.id, "name": favorite.name, "license_plate": favorite.license_plate}
        )
        return favorite

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        for f in self._get_favorites():
            if f["id"] == favorite_id:
                if license_plate is not None:
                    f["license_plate"] = self._normalize_license_plate(license_plate)
                if name is not None:
                    f["name"] = name
                return Favorite(id=f["id"], name=f["name"], license_plate=f["license_plate"])
        raise ProviderError(f"Favorite {favorite_id!r} not found.")

    async def remove_favorite(self, favorite_id: str) -> None:
        self._favorites = [f for f in self._get_favorites() if f["id"] != favorite_id]
