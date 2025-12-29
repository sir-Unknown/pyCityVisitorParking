"""Public data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    id: str
    favorite_update_possible: bool


@dataclass(frozen=True, slots=True)
class ZoneValidityBlock:
    start_time: str
    end_time: str


@dataclass(frozen=True, slots=True)
class Permit:
    id: str
    remaining_balance: int
    zone_validity: list[ZoneValidityBlock]


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
