"""Response mapping helpers for the refactored DVS Portal provider."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...exceptions import ProviderError, ValidationError
from ...models import BALANCE_UNIT_MINUTE, Favorite, Permit, Reservation, ZoneValidityBlock
from ...util import format_utc_timestamp
from .const import API_TIMEZONE

if TYPE_CHECKING:
    from .api import Provider
    from .session import PortalSessionState


class PortalMapper:
    """Map provider payloads into strict public models."""

    def __init__(self, provider: Provider, state: PortalSessionState) -> None:
        """Initialize the mapper with provider helpers and shared session state."""
        self._provider = provider
        self._state = state

    def extract_permit(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract the relevant permit from a provider response."""
        permit = data.get("Permit")
        if isinstance(permit, dict):
            return permit
        permits = data.get("Permits")
        if isinstance(permits, list):
            selected = self._select_permit_from_list(permits)
            if selected is not None:
                return selected
        raise ProviderError("Provider response did not include permit data.")

    def response_includes_permit(self, data: dict[str, Any]) -> bool:
        """Return whether the response contains permit details."""
        permit = data.get("Permit")
        if isinstance(permit, dict):
            return True
        permits = data.get("Permits")
        return isinstance(permits, list) and any(isinstance(item, dict) for item in permits)

    def select_permit_media(self, permit: dict[str, Any]) -> dict[str, Any]:
        """Select the active permit media from a permit payload."""
        media_items = permit.get("PermitMedias")
        if not isinstance(media_items, list) or not media_items:
            raise ProviderError("Provider response did not include permit media.")
        cached_code = self._state.permit_media_code
        if cached_code:
            for media in media_items:
                if (
                    isinstance(media, dict)
                    and isinstance(media.get("Code"), str)
                    and media["Code"].strip() == cached_code
                ):
                    return media
        media = media_items[0]
        if not isinstance(media, dict):
            raise ProviderError("Provider response included invalid permit media.")
        return media

    def cache_defaults(self, permit: dict[str, Any]) -> None:
        """Cache permit media defaults for later provider operations."""
        media = self.select_permit_media(permit)
        type_id = media.get("TypeID")
        code = media.get("Code")
        if type_id is not None:
            self._provider._validate_media_type_id(type_id)
            self._state.permit_media_type_id = type_id
        if isinstance(code, str) and code.strip():
            self._state.permit_media_code = code.strip()

    def map_permit(self, permit: dict[str, Any]) -> Permit:
        """Map provider permit data to the public Permit model."""
        media = self.select_permit_media(permit)
        permit_id = (
            self._provider._coerce_id(media.get("Code"))
            or self._provider._coerce_id(permit.get("ZoneCode"))
            or "permit"
        )
        remaining_balance = self._provider._parse_int(media.get("Balance"))
        zone_validity = self.map_zone_validity(permit.get("BlockTimes"))
        return Permit(
            id=permit_id,
            remaining_balance=remaining_balance,
            zone_validity=zone_validity,
            balance_unit=BALANCE_UNIT_MINUTE,
        )

    def map_zone_validity(self, block_times: Any) -> list[ZoneValidityBlock]:
        """Map provider block times into chargeable zone validity windows."""
        if block_times is None:
            return []
        if not isinstance(block_times, list):
            raise ProviderError("Provider response included invalid block times.")
        entries: list[tuple[ZoneValidityBlock, bool]] = []
        for block in block_times:
            if not isinstance(block, dict):
                continue
            is_free = block.get("IsFree") is True
            start_raw = block.get("ValidFrom")
            end_raw = block.get("ValidUntil")
            if not start_raw or not end_raw:
                continue
            try:
                start = self.parse_provider_timestamp(start_raw)
                end = self.parse_provider_timestamp(end_raw)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid block time data.") from exc
            entries.append((ZoneValidityBlock(start_time=start, end_time=end), not is_free))
        return self._provider._filter_chargeable_zone_validity(entries)

    def reservations_from_permit(self, permit: dict[str, Any]) -> list[Reservation]:
        """Cache defaults and return mapped active reservations."""
        self.cache_defaults(permit)
        return self.map_reservations(self.select_permit_media(permit))

    def favorites_from_permit(self, permit: dict[str, Any]) -> list[Favorite]:
        """Cache defaults and return mapped stored favorites."""
        self.cache_defaults(permit)
        return self.map_favorites(self.select_permit_media(permit))

    def map_reservations(self, permit_media: dict[str, Any]) -> list[Reservation]:
        """Map active reservations from permit media data."""
        raw = permit_media.get("ActiveReservations")
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ProviderError("Provider response included invalid reservations.")
        reservations: list[Reservation] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            reservation_id = item.get("ReservationID")
            start_raw = item.get("ValidFrom")
            end_raw = item.get("ValidUntil")
            plate_info = item.get("LicensePlate")
            if (
                reservation_id is None
                or not start_raw
                or not end_raw
                or not isinstance(plate_info, dict)
            ):
                continue
            plate_value = plate_info.get("Value") or plate_info.get("DisplayValue")
            if not plate_value:
                continue
            try:
                normalized_plate = self._provider._normalize_license_plate(plate_value)
                start = self.parse_provider_timestamp(start_raw)
                end = self.parse_provider_timestamp(end_raw)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid reservation data.") from exc
            name = plate_info.get("DisplayValue") or plate_value
            reservations.append(
                Reservation(
                    id=self._provider._coerce_id(reservation_id),
                    name=name,
                    license_plate=normalized_plate,
                    start_time=start,
                    end_time=end,
                )
            )
        return reservations

    def map_favorites(self, permit_media: dict[str, Any]) -> list[Favorite]:
        """Map stored license plates into public Favorite models."""
        raw = permit_media.get("LicensePlates")
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise ProviderError("Provider response included invalid favorites.")
        favorites: list[Favorite] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            value = item.get("Value")
            if not value:
                continue
            try:
                normalized = self._provider._normalize_license_plate(value)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid favorite data.") from exc
            favorites.append(
                Favorite(
                    id=normalized,
                    name=item.get("Name") or "",
                    license_plate=normalized,
                )
            )
        return favorites

    def parse_provider_timestamp(self, value: str) -> str:
        """Parse a provider timestamp and return a normalized UTC timestamp."""
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Provider timestamp must be a non-empty string.")
        raw = value.strip()
        if raw.endswith("Z"):
            return self._provider._ensure_utc_timestamp(raw)
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValidationError("Provider timestamp is not a valid ISO 8601 value.") from exc
        if parsed.tzinfo is None:
            # DVS Portal returns local timestamps without offsets; assume Europe/Amsterdam.
            # fold=0 gives deterministic handling for DST transition edge cases.
            parsed = parsed.replace(tzinfo=self.provider_timezone(), fold=0)
        return format_utc_timestamp(parsed)

    def format_provider_timestamp(self, value: datetime) -> str:
        """Format a UTC datetime as a provider-local timestamp with milliseconds."""
        if value.tzinfo is None:
            raise ValidationError("Timestamp must include timezone information.")
        if value.tzinfo == UTC and value.microsecond == 0:
            normalized = value
        else:
            normalized = self._provider._normalize_datetime(value)
        localized = normalized.astimezone(self.provider_timezone())
        return localized.isoformat(timespec="milliseconds")

    def provider_timezone(self) -> ZoneInfo:
        """Return the provider timezone, caching the ZoneInfo lookup."""
        try:
            if self._state.api_timezone is None:
                self._state.api_timezone = ZoneInfo(API_TIMEZONE)
            return self._state.api_timezone
        except ZoneInfoNotFoundError as exc:
            raise ProviderError(f"Timezone data for {API_TIMEZONE} is unavailable.") from exc

    def select_reservation(
        self,
        reservations: list[Reservation],
        *,
        reservation_id: str | None = None,
        license_plate: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> Reservation | None:
        """Return the first reservation matching the provided filters."""
        return next(
            (
                reservation
                for reservation in reservations
                if (reservation_id is None or reservation.id == reservation_id)
                and (license_plate is None or reservation.license_plate == license_plate)
                and (start_time is None or reservation.start_time == start_time)
                and (end_time is None or reservation.end_time == end_time)
            ),
            None,
        )

    def select_favorite(self, favorites: list[Favorite], plate: str) -> Favorite | None:
        """Return the favorite for a normalized license plate."""
        return next((favorite for favorite in favorites if favorite.license_plate == plate), None)

    def _select_permit_from_list(self, permits: list[Any]) -> dict[str, Any] | None:
        """Pick the most relevant permit from a list of provider permits."""
        cached_media_code = self._state.permit_media_code
        if cached_media_code:
            for permit in permits:
                if not isinstance(permit, dict):
                    continue
                media_items = permit.get("PermitMedias")
                if not isinstance(media_items, list):
                    continue
                for media in media_items:
                    if (
                        isinstance(media, dict)
                        and isinstance(media.get("Code"), str)
                        and media["Code"].strip() == cached_media_code
                    ):
                        return permit
        for permit in permits:
            if isinstance(permit, dict):
                return permit
        return None
