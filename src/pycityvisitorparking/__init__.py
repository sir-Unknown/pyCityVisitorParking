"""pyCityVisitorParking package."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .client import Client
from .exceptions import AuthError, NetworkError, ProviderError, ValidationError
from .models import Favorite, Permit, ProviderInfo, Reservation, ZoneValidityBlock

try:
    __version__ = version("pycityvisitorparking")
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"

__all__ = [
    "AuthError",
    "Client",
    "Favorite",
    "NetworkError",
    "Permit",
    "ProviderError",
    "ProviderInfo",
    "Reservation",
    "ValidationError",
    "ZoneValidityBlock",
    "__version__",
]
