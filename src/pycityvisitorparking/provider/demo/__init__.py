"""Demo provider — returns hardcoded mock data, no network calls."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime

from ...exceptions import ProviderError
from ...models import Favorite, Permit, Reservation, ZoneValidityBlock
from ...util import parse_timestamp
from ..base import BaseProvider

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
    "default": [
        {"id": "d1", "name": "Demo Gebruiker", "license_plate": "XX-000-X"},
    ],
}

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
        self._reservations: list[dict[str, str]] = [dict(r) for r in _RESERVATIONS]

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
        # fallback
        return {
            "remaining_balance": 100.0,
            "balance_unit": "EURO",
            "zone_start": "2026-04-15T08:00:00Z",
            "zone_end": "2026-04-15T20:00:00Z",
        }

    async def get_permit(self) -> Permit:
        cfg = self._demo_permit_config()
        return Permit(
            id="demo-permit",
            remaining_balance=cfg["remaining_balance"],
            balance_unit=cfg["balance_unit"],
            zone_validity=[
                ZoneValidityBlock(
                    start_time=cfg["zone_start"],
                    end_time=cfg["zone_end"],
                )
            ],
        )

    async def list_reservations(self) -> list[Reservation]:
        return [
            Reservation(
                id=r["id"],
                name=r["name"],
                license_plate=self._normalize_license_plate(r["license_plate"]),
                start_time=r["start_time"],
                end_time=r["end_time"],
            )
            for r in self._reservations
        ]

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ) -> Reservation:
        start_time, end_time = self._validate_reservation_times(
            start_time, end_time, require_both=True
        )
        reservation = Reservation(
            id=str(uuid.uuid4()),
            name=name or "",
            license_plate=self._normalize_license_plate(license_plate),
            start_time=self._format_utc_timestamp(self._normalize_datetime(start_time)),
            end_time=self._format_utc_timestamp(self._normalize_datetime(end_time)),
        )
        self._reservations.append(
            {
                "id": reservation.id,
                "name": reservation.name,
                "license_plate": reservation.license_plate,
                "start_time": reservation.start_time,
                "end_time": reservation.end_time,
            }
        )
        return reservation

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        for r in self._reservations:
            if r["id"] == reservation_id:
                effective_start = (
                    self._normalize_datetime(start_time)
                    if start_time is not None
                    else parse_timestamp(r["start_time"])
                )
                effective_end = (
                    self._normalize_datetime(end_time)
                    if end_time is not None
                    else parse_timestamp(r["end_time"])
                )
                self._validate_reservation_times(effective_start, effective_end, require_both=True)
                r["start_time"] = self._format_utc_timestamp(effective_start)
                r["end_time"] = self._format_utc_timestamp(effective_end)
                if name is not None:
                    r["name"] = name
                return Reservation(
                    id=r["id"],
                    name=r["name"],
                    license_plate=r["license_plate"],
                    start_time=r["start_time"],
                    end_time=r["end_time"],
                )
        raise ProviderError(f"Reservation {reservation_id!r} not found.")

    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
        for i, r in enumerate(self._reservations):
            if r["id"] == reservation_id:
                ended = Reservation(
                    id=r["id"],
                    name=r["name"],
                    license_plate=r["license_plate"],
                    start_time=r["start_time"],
                    end_time=self._format_utc_timestamp(self._normalize_datetime(end_time)),
                )
                self._reservations.pop(i)
                return ended
        raise ProviderError(f"Reservation {reservation_id!r} not found.")

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
