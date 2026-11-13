"""Public data models."""

from __future__ import annotations

from dataclasses import dataclass, field

BALANCE_UNIT_TIMES = "TIMES"
BALANCE_UNIT_MINUTE = "MINUTE"
BALANCE_UNIT_EURO = "EURO"

# How a provider lets the caller choose where a reservation is booked.
# "list": choose from ``list_reservation_targets()``.
# "free_input": the caller may also pass an id the provider can resolve itself.
RESERVATION_TARGET_SELECTION_LIST = "list"
RESERVATION_TARGET_SELECTION_FREE_INPUT = "free_input"


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    id: str
    favorite_update_fields: tuple[str, ...]
    reservation_update_fields: tuple[str, ...]
    balance_units: tuple[str, ...] = ()
    reservation_target_selection: str | None = None


@dataclass(frozen=True, slots=True)
class PaidHoursBlock:
    start_time: str
    end_time: str


@dataclass(frozen=True, slots=True)
class ReservationTarget:
    id: str
    name: str
    description: str | None = None
    # Paid hours of this target; empty when the provider reports none per target.
    paid_hours: list[PaidHoursBlock] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Permit:
    id: str
    remaining_balance: float
    paid_hours: list[PaidHoursBlock]
    balance_unit: str | None = None


@dataclass(frozen=True, slots=True)
class Reservation:
    id: str
    name: str
    license_plate: str
    start_time: str
    end_time: str
    reservation_target_id: str | None = None


@dataclass(frozen=True, slots=True)
class Favorite:
    id: str
    name: str
    license_plate: str
