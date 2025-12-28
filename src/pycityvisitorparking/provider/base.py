"""Provider base class and shared behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, Literal, overload

import aiohttp

from ..exceptions import AuthError, NetworkError, ProviderError, ValidationError
from ..models import Favorite, Permit, ProviderInfo, Reservation, ZoneValidityBlock
from ..util import (
    ensure_utc_timestamp,
    filter_chargeable_zone_validity,
    mask_license_plate,
    normalize_license_plate,
    validate_reservation_times,
)
from .loader import ProviderManifest

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


class BaseProvider(ABC):
    """Base class for provider implementations."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        manifest: ProviderManifest,
        *,
        base_url: str | None = None,
        api_uri: str | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
        retry_count: int = 0,
    ) -> None:
        if session is None:
            raise ValidationError("Session is required.")
        self._session = session
        self._manifest = manifest
        self._base_url = self._normalize_base_url(base_url)
        self._api_uri = self._normalize_api_uri(api_uri)
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._retry_count = max(0, retry_count)

    @property
    def provider_id(self) -> str:
        return self._manifest.id

    @property
    def provider_name(self) -> str:
        return self._manifest.name

    @property
    def favorite_update_possible(self) -> bool:
        return self._manifest.favorite_update_possible

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self._manifest.id,
            favorite_update_possible=self._manifest.favorite_update_possible,
        )

    def _normalize_license_plate(self, plate: str) -> str:
        return normalize_license_plate(plate)

    def _mask_license_plate(self, plate: str) -> str:
        return mask_license_plate(plate)

    def _ensure_utc_timestamp(self, value: str) -> str:
        return ensure_utc_timestamp(value)

    def _build_url(self, path: str) -> str:
        if not isinstance(path, str) or not path:
            raise ValidationError("Path must be a non-empty string.")
        if path.startswith("http://") or path.startswith("https://"):
            raise ValidationError("Use relative paths when building provider requests.")
        if self._base_url is None:
            raise ValidationError("base_url is required to build provider requests.")
        normalized_path = path if path.startswith("/") else f"/{path}"
        return f"{self._base_url}{self._api_uri}{normalized_path}"

    @overload
    def _validate_reservation_times(
        self,
        start_time: str,
        end_time: str,
        *,
        require_both: Literal[True],
    ) -> tuple[str, str]: ...

    @overload
    def _validate_reservation_times(
        self,
        start_time: str | None,
        end_time: str | None,
        *,
        require_both: Literal[False],
    ) -> tuple[str | None, str | None]: ...

    def _validate_reservation_times(
        self,
        start_time: str | None,
        end_time: str | None,
        *,
        require_both: bool,
    ) -> tuple[str | None, str | None]:
        if require_both:
            if start_time is None or end_time is None:
                raise ValidationError("start_time and end_time are required.")
            return validate_reservation_times(start_time, end_time, require_both=True)
        return validate_reservation_times(start_time, end_time, require_both=False)

    def _filter_chargeable_zone_validity(
        self,
        entries: list[tuple[ZoneValidityBlock, bool]],
    ) -> list[ZoneValidityBlock]:
        return filter_chargeable_zone_validity(entries)

    def _merge_credentials(
        self,
        credentials: Mapping[str, str] | None,
        **kwargs: str,
    ) -> dict[str, str]:
        merged: dict[str, str] = {}
        if credentials is not None:
            if not isinstance(credentials, Mapping):
                raise ValidationError("credentials must be a mapping of strings.")
            for key, value in credentials.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise ValidationError("credentials must be a mapping of strings.")
                merged[key] = value
        for key, value in kwargs.items():
            if value is None:
                continue
            if not isinstance(value, str):
                raise ValidationError("credentials must be a mapping of strings.")
            merged[key] = value
        return merged

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self._build_url(path)
        return await self._request(method, url, expect_json=True, **kwargs)

    async def _request_text(self, method: str, path: str, **kwargs: Any) -> str:
        url = self._build_url(path)
        return await self._request(method, url, expect_json=False, **kwargs)

    async def _request(self, method: str, url: str, *, expect_json: bool, **kwargs: Any) -> Any:
        retries = self._retry_count if method.upper() == "GET" else 0
        attempts = retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                timeout = kwargs.pop("timeout", self._timeout)
                if timeout is None:
                    timeout = self._timeout
                async with self._session.request(
                    method,
                    url,
                    timeout=timeout,
                    ssl=True,
                    **kwargs,
                ) as response:
                    self._raise_for_status(response)
                    if expect_json:
                        try:
                            return await response.json()
                        except (aiohttp.ContentTypeError, ValueError) as exc:
                            raise ProviderError("Response did not contain valid JSON.") from exc
                    return await response.text()
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_error = exc
                if attempt >= attempts - 1:
                    raise NetworkError("Network request failed.") from exc
        if last_error is not None:
            raise NetworkError("Network request failed.") from last_error
        raise ProviderError("Request failed.")

    def _raise_for_status(self, response: aiohttp.ClientResponse) -> None:
        if 200 <= response.status < 300:
            return
        if response.status in (401, 403):
            raise AuthError("Authentication failed.")
        raise ProviderError(f"Provider request failed with status {response.status}.")

    def _normalize_base_url(self, base_url: str | None) -> str | None:
        if base_url is None:
            return None
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValidationError("base_url must be a non-empty string.")
        return base_url.strip().rstrip("/")

    def _normalize_api_uri(self, api_uri: str | None) -> str:
        if api_uri is None:
            return ""
        if not isinstance(api_uri, str):
            raise ValidationError("api_uri must be a string.")
        normalized = api_uri.strip().strip("/")
        if not normalized:
            return ""
        return f"/{normalized}"

    @abstractmethod
    async def login(self, credentials: Mapping[str, str] | None = None, **kwargs: str) -> None:
        """Authenticate against the provider."""

    @abstractmethod
    async def get_permit(self) -> Permit:
        """Return the active permit for the account."""

    @abstractmethod
    async def list_reservations(self) -> list[Reservation]:
        """Return active reservations."""

    @abstractmethod
    async def start_reservation(
        self,
        license_plate: str,
        start_time: str,
        end_time: str,
        name: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate."""

    @abstractmethod
    async def update_reservation(
        self,
        reservation_id: str,
        start_time: str | None = None,
        end_time: str | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""

    @abstractmethod
    async def end_reservation(self, reservation_id: str, end_time: str) -> Reservation:
        """End a reservation."""

    @abstractmethod
    async def list_favorites(self) -> list[Favorite]:
        """Return stored favorites."""

    @abstractmethod
    async def add_favorite(self, license_plate: str, name: str | None = None) -> Favorite:
        """Add a favorite."""

    async def update_favorite(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Update a favorite, with fallback for providers without native support."""
        if self.favorite_update_possible:
            return await self._update_favorite_native(
                favorite_id,
                license_plate=license_plate,
                name=name,
            )
        if license_plate is None:
            raise ValidationError("license_plate is required when update is not supported.")
        normalized = self._normalize_license_plate(license_plate)
        await self.remove_favorite(favorite_id)
        return await self.add_favorite(normalized, name=name)

    @abstractmethod
    async def _update_favorite_native(
        self,
        favorite_id: str,
        license_plate: str | None = None,
        name: str | None = None,
    ) -> Favorite:
        """Native favorite update implementation for providers that support it."""

    @abstractmethod
    async def remove_favorite(self, favorite_id: str) -> None:
        """Remove a favorite."""
