"""pyCityVisitorParking package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .client import Client
from .exceptions import (
    AuthError,
    ConfigError,
    ErrorCode,
    NetworkError,
    NotFoundError,
    ProviderError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
    ValidationError,
)
from .models import (
    BALANCE_UNIT_EURO,
    BALANCE_UNIT_MINUTE,
    BALANCE_UNIT_TIMES,
    RESERVATION_TARGET_SELECTION_FREE_INPUT,
    RESERVATION_TARGET_SELECTION_LIST,
    Favorite,
    Permit,
    ProviderInfo,
    Reservation,
    ReservationTarget,
    ZoneValidityBlock,
)

try:
    __version__ = version("pycityvisitorparking")
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"

__all__ = [
    "BALANCE_UNIT_EURO",
    "BALANCE_UNIT_MINUTE",
    "BALANCE_UNIT_TIMES",
    "RESERVATION_TARGET_SELECTION_FREE_INPUT",
    "RESERVATION_TARGET_SELECTION_LIST",
    "AuthError",
    "Client",
    "ConfigError",
    "ErrorCode",
    "Favorite",
    "NetworkError",
    "NotFoundError",
    "Permit",
    "ProviderError",
    "ProviderInfo",
    "RateLimitError",
    "Reservation",
    "ReservationTarget",
    "ServiceUnavailableError",
    "TimeoutError",
    "ValidationError",
    "ZoneValidityBlock",
    "__version__",
]
