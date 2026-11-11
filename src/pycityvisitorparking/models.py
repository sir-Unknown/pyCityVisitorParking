"""Public data models."""

from __future__ import annotations

from dataclasses import dataclass, field

BALANCE_UNIT_TIMES = "TIMES"
BALANCE_UNIT_MINUTE = "MINUTE"
BALANCE_UNIT_EURO = "EURO"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    id: str
    favorite_update_fields: tuple[str, ...]
    reservation_update_fields: tuple[str, ...]
    balance_units: tuple[str, ...] = ()
    zone_selection: bool = False


@dataclass(frozen=True, slots=True)
class ZoneValidityBlock:
    start_time: str
    end_time: str


@dataclass(frozen=True, slots=True)
class Zone:
    id: str
    name: str
    zone_validity: list[ZoneValidityBlock]


@dataclass(frozen=True, slots=True)
class Permit:
    id: str
    remaining_balance: float
    zone_validity: list[ZoneValidityBlock]
    balance_unit: str | None = None
    # Zones a reservation can be started in; the first one is the default zone and its
    # windows equal ``zone_validity``. Empty when the provider has no zone selection.
    zones: list[Zone] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Reservation:
    id: str
    name: str
    license_plate: str
    start_time: str
    end_time: str
    zone_id: str | None = None


@dataclass(frozen=True, slots=True)
class Favorite:
    id: str
    name: str
    license_plate: str
