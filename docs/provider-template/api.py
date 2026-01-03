"""Provider template implementation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from pycityvisitorparking.exceptions import ProviderError, ValidationError
from pycityvisitorparking.models import Favorite, Permit, Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.base import BaseProvider


class Provider(BaseProvider):
    """Template provider implementation."""

    async def login(self, credentials: Mapping[str, str] | None = None, **kwargs: str) -> None:
        merged = self._merge_credentials(credentials, **kwargs)
        if not merged:
            raise ValidationError("Credentials are required.")
        raise ProviderError("Template provider does not implement login.")

    async def get_permit(self) -> Permit:
        raise ProviderError("Template provider does not implement get_permit.")

    async def list_reservations(self) -> list[Reservation]:
        raise ProviderError("Template provider does not implement list_reservations.")

    async def start_reservation(
        self,
        license_plate: str,
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ) -> Reservation:
        self._normalize_license_plate(license_plate)
        self._validate_reservation_times(start_time, end_time, require_both=True)
        raise ProviderError("Template provider does not implement start_reservation.")

    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        self._validate_reservation_times(start_time, end_time, require_both=False)
        raise ProviderError("Template provider does not implement update_reservation.")

    async def end_reservation(self, reservation_id: str, end_time: datetime) -> Reservation:
        self._normalize_datetime(end_time)
        raise ProviderError("Template provider does not implement end_reservation.")

    async def list_favorites(self) -> list[Favorite]:
        raise ProviderError("Template provider does not implement list_favorites.")

    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        self._normalize_license_plate(license_plate)
        raise ProviderError("Template provider does not implement add_favorite.")

    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        raise ProviderError("Template provider does not implement update_favorite.")

    async def remove_favorite(self, favorite_id: str) -> None:
        raise ProviderError("Template provider does not implement remove_favorite.")

    def _build_zone_validity(self) -> list[ZoneValidityBlock]:
        """Example helper for zone validity filtering."""
        entries: list[tuple[ZoneValidityBlock, bool]] = []
        return self._filter_chargeable_zone_validity(entries)
