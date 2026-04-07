"""Public data models."""

from __future__ import annotations

from dataclasses import dataclass

BALANCE_UNIT_TIMES = "TIMES"
BALANCE_UNIT_MINUTE = "MINUTE"
BALANCE_UNIT_EURO = "EURO"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    id: str
    favorite_update_fields: tuple[str, ...]
    reservation_update_fields: tuple[str, ...]
    balance_units: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ZoneValidityBlock:
    start_time: str
    end_time: str


@dataclass(frozen=True, slots=True)
class Permit:
    id: str
    remaining_balance: float
    zone_validity: list[ZoneValidityBlock]
    balance_unit: str | None = None


@dataclass(frozen=True, slots=True)
class Reservation:
    id: str
    name: str
    license_plate: str
    start_time: str
    end_time: str


@dataclass(frozen=True, slots=True)
class Favorite:
    id: str
    name: str
    license_plate: str
