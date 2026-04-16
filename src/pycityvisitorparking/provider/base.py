"""Provider base class and shared behavior."""

from __future__ import annotations

import asyncio
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, Protocol, TypeVar, overload
from urllib.parse import urlparse

import aiohttp

from ..exceptions import AuthError, NetworkError, ProviderError, ValidationError
from ..models import Favorite, Permit, ProviderInfo, Reservation, ZoneValidityBlock
from ..util import (
    ensure_utc_timestamp,
    filter_chargeable_zone_validity,
    format_utc_timestamp,
    normalize_datetime,
    normalize_license_plate,
    validate_reservation_times,
)
from .loader import ProviderManifest
from .logger import get_provider_logger

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
_MAX_LOG_BODY_CHARS = 600
_HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_BASE_RE = re.compile(
    r"""<base[^>]+href\s*=\s*["']?([^"'\s>]+)""",
    re.IGNORECASE | re.DOTALL,
)
_SENSITIVE_KEYS = frozenset(
    {
        "Authorization",
        "Token",
        "asIdentifier",
        "identifier",
        "otp",
        "password",
        "permitId",
        "permitMediaCode",
        "permit_id",
        "permit_media_code",
        "resetCode",
        "token",
        "username",
        "zipCode",
    }
)
_SENSITIVE_OBJECT_KEYS = frozenset({"LicensePlate", "licensePlate", "updateLicensePlate"})
_SENSITIVE_NESTED_KEYS = frozenset({"DisplayValue", "Name", "Value"})
_T = TypeVar("_T")

try:
    PACKAGE_VERSION = version("pycityvisitorparking")
except PackageNotFoundError:  # pragma: no cover - source tree fallback
    PACKAGE_VERSION = "0.0.0"


class _HttpSession(Protocol):
    """Minimal interface required from an HTTP session."""

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Make an HTTP request."""
        pass


class BaseProvider(ABC):
    """Base class for provider implementations."""

    class _RetryRequest(Exception):
        """Internal signal to retry a request."""

    def __init__(
        self,
        session: _HttpSession,
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
        self._request_context_name: str | None = None
        self._ha_cvp_version = "unknown"
        self._pycvp_version = PACKAGE_VERSION
        self._logger = get_provider_logger(type(self).__module__)
        self._logger.debug(
            "Provider %s initialized base_url=%s api_uri=%s",
            self._manifest.id,
            self._base_url,
            self._api_uri or "(none)",
        )

    def set_request_context(self, context_name: str | None) -> None:
        """Set a human-readable context label for request diagnostics."""
        if context_name is None:
            self._request_context_name = None
            return
        value = context_name.strip()
        self._request_context_name = value or None

    def set_runtime_versions(
        self,
        *,
        ha_cvp_version: str | None = None,
        pycvp_version: str | None = None,
    ) -> None:
        """Set runtime version metadata for provider logging."""
        if ha_cvp_version is not None:
            value = ha_cvp_version.strip()
            self._ha_cvp_version = value or "unknown"
        if pycvp_version is not None:
            value = pycvp_version.strip()
            self._pycvp_version = value or "unknown"

    def _request_target_label(self) -> str:
        """Return a stable target label for diagnostics and logs."""
        if self._base_url is None:
            return "unknown"
        parsed = urlparse(self._base_url)
        return parsed.netloc or self._base_url

    def _request_context_label(self) -> str:
        """Return city/context label for diagnostics and logs."""
        if self._request_context_name:
            return self._request_context_name
        return self._request_target_label()

    def _request_city_label(self) -> str:
        """Return city label for diagnostics and logs."""
        if self._request_context_name:
            return self._request_context_name
        return "unknown"

    def _request_log_metadata(self) -> tuple[str, str, str, str]:
        """Return provider logging metadata."""
        return (
            self.provider_id,
            self._request_city_label(),
            self._ha_cvp_version,
            self._pycvp_version,
        )

    def _log_with_metadata(self, level: int, message: str, *args: Any) -> None:
        """Log a message with the standard provider metadata suffix."""
        provider, city, ha_cvp, pycvp = self._request_log_metadata()
        self._logger.log(
            level,
            f"{message} (provider=%s, city=%s, hacvp=%s, pycvp=%s)",
            *args,
            provider,
            city,
            ha_cvp,
            pycvp,
        )

    def _log_warning_block(
        self,
        label: str,
        fields: dict[str, Any],
        *,
        detail: str | None = None,
    ) -> None:
        """Log a warning as a labelled multi-line key=value block with provider metadata."""
        provider, city, ha_cvp, pycvp = self._request_log_metadata()
        all_fields = {k: v for k, v in fields.items() if v is not None}
        all_fields.update({"provider": provider, "city": city, "hacvp": ha_cvp, "pycvp": pycvp})
        width = max(len(k) for k in all_fields)
        lines = [label]
        if detail:
            lines.append(f"  {detail}")
        for key, value in all_fields.items():
            lines.append(f"  {key:<{width}} = {value}")
        self._logger.warning("%s", "\n".join(lines))

    def _format_log_details(self, **details: Any) -> str:
        """Serialize optional log details as a compact key=value suffix."""
        if not details:
            return ""
        return " " + " ".join(f"{key}={value}" for key, value in details.items())

    def _log_operation_started(self, operation: str, **details: Any) -> None:
        """Log the start of a provider operation."""
        self._logger.debug(
            "Provider %s %s started%s",
            self.provider_id,
            operation,
            self._format_log_details(**details),
        )

    def _log_operation_completed(self, operation: str, **details: Any) -> None:
        """Log successful completion of a provider operation."""
        self._logger.debug(
            "Provider %s %s completed%s",
            self.provider_id,
            operation,
            self._format_log_details(**details),
        )

    def _log_operation_failed(self, operation: str, reason: str, **details: Any) -> None:
        """Log a provider operation failure before raising a validation/provider error."""
        self._logger.debug(
            "Provider %s %s failed: %s%s",
            self.provider_id,
            operation,
            reason,
            self._format_log_details(**details),
        )

    def _log_reauth_triggered(self) -> None:
        """Log when a provider request falls back to reauthentication."""
        self._log_warning_block("reauth triggered", {})

    def _log_reauthenticating(self) -> None:
        """Log when cached credentials are used to reauthenticate."""
        self._logger.debug(
            "Provider %s reauthenticating with cached credentials",
            self.provider_id,
        )

    def _log_missing_response_data(self, label: str, fallback: str = "refetching") -> None:
        """Log when a response is missing expected data and a fallback is used."""
        self._log_warning_block(
            "missing permit in response", {"operation": label, "fallback": fallback}
        )

    def _log_response_status(self, status: int) -> None:
        """Log the HTTP response status returned by a provider."""
        self._logger.debug("Provider %s response status=%s", self.provider_id, status)

    def _summarize_log_text(self, value: str) -> str:
        """Normalize and truncate response text for safe logging."""
        compact = " ".join(value.split())
        if len(compact) > _MAX_LOG_BODY_CHARS:
            return compact[: _MAX_LOG_BODY_CHARS - 3] + "..."
        return compact

    def _response_kind(self, content_type: str | None, body: str | None) -> str:
        """Classify a failed response body for compact diagnostics."""
        if not body:
            return "empty"

        lowered_type = (content_type or "").lower()
        if "html" in lowered_type:
            return "html"

        compact = body.lstrip().lower()
        if compact.startswith("<!doctype html") or compact.startswith("<html"):
            return "html"

        return "text"

    def _extract_html_log_fields(self, body: str) -> dict[str, str]:
        """Return compact HTML diagnostics without logging the full page body."""
        fields: dict[str, str] = {}

        title_match = _HTML_TITLE_RE.search(body)
        if title_match:
            title = self._summarize_log_text(title_match.group(1))
            if title:
                fields["html_title"] = title

        base_match = _HTML_BASE_RE.search(body)
        if base_match:
            base_href = self._summarize_log_text(base_match.group(1))
            if base_href:
                fields["html_base_href"] = base_href

        if not fields:
            fields["body_excerpt"] = self._summarize_log_text(body)

        return fields

    def _mask_payload(self, payload: Any) -> Any:
        """Return a copy of payload with sensitive values replaced by '***'."""
        return self._mask_log_value(payload)

    def _mask_log_value(self, value: Any, *, parent_key: str | None = None) -> Any:
        """Return a masked copy of structured log data."""
        if parent_key in _SENSITIVE_KEYS:
            return "***" if value is not None else None
        if isinstance(value, dict):
            return {
                key: (
                    "***" if key in _SENSITIVE_KEYS else self._mask_log_value(item, parent_key=key)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._mask_log_value(item, parent_key=parent_key) for item in value]
        if parent_key in _SENSITIVE_OBJECT_KEYS:
            return "***" if value is not None else None
        if parent_key in _SENSITIVE_NESTED_KEYS:
            return "***" if value is not None else None
        return value

    def _response_keys_summary(self, data: dict[str, Any]) -> str:
        """Return a compact summary of top-level response keys."""
        keys = sorted(str(key) for key in data)
        if len(keys) > 12:
            return ", ".join(keys[:12]) + ", ..."
        return ", ".join(keys)

    def _build_response_summary(self, data: Any) -> dict[str, Any]:
        """Return a safe summary of provider response structure and metadata."""
        if isinstance(data, dict):
            summary: dict[str, Any] = {
                "response-type": "dict",
                "response-keys": self._response_keys_summary(data),
            }
            if "Result" in data:
                summary["result"] = data.get("Result")
            if "LoginStatus" in data:
                summary["login-status"] = data.get("LoginStatus")
            if "RequiresOtp" in data:
                summary["requires-otp"] = data.get("RequiresOtp")
            if "Redirect" in data:
                summary["redirect"] = data.get("Redirect")
            if "ErrorMessage" in data and data.get("ErrorMessage"):
                summary["error-message"] = self._summarize_log_text(str(data["ErrorMessage"]))
            if "Token" in data:
                summary["token-present"] = bool(data.get("Token"))
            if "Permit" in data:
                summary["has-permit"] = isinstance(data.get("Permit"), dict)
            permits = data.get("Permits")
            if isinstance(permits, list):
                summary["permits-count"] = len(permits)
            permit_medias = data.get("PermitMedias")
            if isinstance(permit_medias, list):
                summary["permit-medias-count"] = len(permit_medias)
            reservations = data.get("ActiveReservations")
            if isinstance(reservations, list):
                summary["active-reservations-count"] = len(reservations)
            return summary
        if isinstance(data, list):
            return {"response-type": "list", "items": len(data)}
        return {"response-type": type(data).__name__}

    def _log_response_summary(self, data: Any) -> None:
        """Log a safe debug summary of a successful JSON response."""
        self._logger.debug(
            "Provider %s response summary %s",
            self.provider_id,
            self._mask_log_value(self._build_response_summary(data)),
        )

    def _log_request_failure(
        self,
        status: int,
        *,
        method: str | None = None,
        url: str | None = None,
        operation: str | None = None,
        payload: Any = None,
        body: str | None = None,
        content_type: str | None = None,
    ) -> None:
        """Log an unsuccessful provider HTTP response."""
        is_auth = status in (401, 403)
        label = "auth request failed" if is_auth else "request failed"
        detail = f"{method.upper()} {url}" if method and url else url
        fields: dict[str, Any] = {"status": status}
        if operation:
            fields["operation"] = operation
        if content_type:
            fields["content-type"] = content_type
        fields["response_kind"] = self._response_kind(content_type, body)
        if payload is not None:
            fields["payload"] = self._mask_payload(payload)
        if fields["response_kind"] == "html" and body:
            fields.update(self._extract_html_log_fields(body))
        elif body:
            fields["body"] = self._summarize_log_text(body)
        self._log_warning_block(label, fields, detail=detail)

    def _log_invalid_json(self, body: str) -> None:
        """Log an invalid JSON response body."""
        self._log_warning_block("invalid json response", {"body": self._summarize_log_text(body)})

    async def _request_with_optional_reauth(
        self,
        *,
        allow_reauth: bool,
        request: Callable[[], Awaitable[_T]],
        on_reauth: Callable[[], Awaitable[None]] | None = None,
    ) -> _T:
        """Execute a request and retry once after reauthentication when allowed."""
        attempts = 2 if allow_reauth else 1
        for attempt in range(attempts):
            try:
                return await request()
            except AuthError:
                if allow_reauth and attempt == 0:
                    self._log_reauth_triggered()
                    if on_reauth is None:
                        raise
                    await on_reauth()
                    continue
                raise
        raise ProviderError("Request failed.")

    @property
    def provider_id(self) -> str:
        return self._manifest.id

    @property
    def provider_name(self) -> str:
        return self._manifest.name

    @property
    def favorite_update_possible(self) -> bool:
        return bool(self._manifest.favorite_update_fields)

    @property
    def favorite_update_fields(self) -> tuple[str, ...]:
        return self._manifest.favorite_update_fields

    @property
    def reservation_update_possible(self) -> bool:
        return bool(self._manifest.reservation_update_fields)

    @property
    def reservation_update_fields(self) -> tuple[str, ...]:
        return self._manifest.reservation_update_fields

    @property
    def info(self) -> ProviderInfo:
        return ProviderInfo(
            id=self._manifest.id,
            favorite_update_fields=self._manifest.favorite_update_fields,
            reservation_update_fields=self._manifest.reservation_update_fields,
        )

    def _normalize_license_plate(self, plate: str) -> str:
        return normalize_license_plate(plate)

    def _ensure_utc_timestamp(self, value: str) -> str:
        return ensure_utc_timestamp(value)

    def _normalize_datetime(self, value: datetime) -> datetime:
        return normalize_datetime(value)

    def _format_utc_timestamp(self, value: datetime) -> str:
        return format_utc_timestamp(value)

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
        start_time: datetime,
        end_time: datetime,
        *,
        require_both: Literal[True],
    ) -> tuple[datetime, datetime]:
        pass

    @overload
    def _validate_reservation_times(
        self,
        start_time: datetime | None,
        end_time: datetime | None,
        *,
        require_both: Literal[False],
    ) -> tuple[datetime | None, datetime | None]:
        pass

    def _validate_reservation_times(
        self,
        start_time: datetime | None,
        end_time: datetime | None,
        *,
        require_both: bool,
    ) -> tuple[datetime | None, datetime | None]:
        if require_both:
            if start_time is None or end_time is None:
                raise ValidationError("start_time and end_time are required.")
            return validate_reservation_times(start_time, end_time, require_both=True)
        return validate_reservation_times(start_time, end_time, require_both=False)

    def _filter_chargeable_zone_validity(
        self,
        entries: list[tuple[ZoneValidityBlock, bool]],
    ) -> list[ZoneValidityBlock]:
        filtered = filter_chargeable_zone_validity(entries)
        normalized: list[ZoneValidityBlock] = []
        for block in filtered:
            try:
                start = self._ensure_utc_timestamp(block.start_time)
                end = self._ensure_utc_timestamp(block.end_time)
            except ValidationError as exc:
                raise ProviderError("Provider returned invalid zone validity data.") from exc
            normalized.append(ZoneValidityBlock(start_time=start, end_time=end))
        return normalized

    def _parse_int(self, value: Any) -> int:
        if value is None or isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return 0
            try:
                return int(stripped)
            except ValueError:
                return 0
        return 0

    def _require_id(self, value: Any, field: str) -> str:
        if value is None:
            raise ValidationError(f"{field} is required.")
        text = str(value).strip()
        if not text:
            raise ValidationError(f"{field} is required.")
        return text

    def _coerce_response_id(self, value: Any, field: str) -> str:
        if value is None:
            raise ProviderError(f"Provider response missing {field}.")
        text = str(value).strip()
        if not text:
            raise ProviderError(f"Provider response missing {field}.")
        return text

    def _coerce_id(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def _find_by_id(self, items: Iterable[_T], item_id: str) -> _T | None:
        for item in items:
            if getattr(item, "id", None) == item_id:
                return item
        return None

    def _merge_credentials(
        self,
        credentials: Mapping[str, object] | None,
        **kwargs: object,
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

    async def _request_with_retries(
        self,
        method: str,
        url: str,
        *,
        request_kwargs: dict[str, Any],
        response_handler: Callable[[aiohttp.ClientResponse, int, int], Awaitable[Any]],
    ) -> Any:
        retries = self._retry_count if method.upper() == "GET" else 0
        attempts = retries + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            if attempts > 1:
                self._logger.debug(
                    "Provider %s request %s %s (attempt %s/%s)",
                    self.provider_id,
                    method.upper(),
                    url,
                    attempt + 1,
                    attempts,
                )
            else:
                self._logger.debug(
                    "Provider %s request %s %s",
                    self.provider_id,
                    method.upper(),
                    url,
                )
            payload = request_kwargs.get("json")
            if payload is not None:
                self._logger.debug(
                    "Provider %s request payload %s",
                    self.provider_id,
                    self._mask_payload(payload),
                )
            try:
                timeout = request_kwargs.get("timeout", self._timeout)
                if timeout is None:
                    timeout = self._timeout
                merged_kwargs = dict(request_kwargs)
                merged_kwargs.setdefault("ssl", True)
                merged_kwargs["timeout"] = timeout
                async with self._session.request(method, url, **merged_kwargs) as response:
                    return await response_handler(response, attempt, attempts)
            except self._RetryRequest:
                if attempt >= attempts - 1:
                    raise ProviderError("Request failed.") from None
                continue
            except (aiohttp.ClientError, TimeoutError) as exc:
                last_error = exc
                self._log_warning_block("network error", {"error": exc.__class__.__name__})
                if attempt >= attempts - 1:
                    raise NetworkError("Network request failed.") from exc
        if last_error is not None:
            raise NetworkError("Network request failed.") from last_error
        raise ProviderError("Request failed.")

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self._build_url(path)
        return await self._request(method, url, expect_json=True, **kwargs)

    async def _request_text(self, method: str, path: str, **kwargs: Any) -> str:
        url = self._build_url(path)
        return await self._request(method, url, expect_json=False, **kwargs)

    async def _request(self, method: str, url: str, *, expect_json: bool, **kwargs: Any) -> Any:
        request_kwargs = dict(kwargs)
        operation = request_kwargs.pop("operation", None)
        payload = request_kwargs.get("json")

        async def handle_response(
            response: aiohttp.ClientResponse,
            _attempt: int,
            _attempts: int,
        ) -> Any:
            self._log_response_status(response.status)
            if not 200 <= response.status < 300:
                self._raise_for_status(
                    response,
                    method=method,
                    url=url,
                    operation=operation,
                    payload=payload,
                    body=await response.text(),
                    content_type=response.headers.get("Content-Type"),
                )
            if expect_json:
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    self._log_invalid_json(await response.text())
                    raise ProviderError("Response did not contain valid JSON.") from exc
                self._log_response_summary(data)
                return data
            return await response.text()

        return await self._request_with_retries(
            method,
            url,
            request_kwargs=request_kwargs,
            response_handler=handle_response,
        )

    def _raise_for_status(
        self,
        response: aiohttp.ClientResponse,
        *,
        method: str | None = None,
        url: str | None = None,
        operation: str | None = None,
        payload: Any = None,
        body: str | None = None,
        content_type: str | None = None,
    ) -> None:
        if 200 <= response.status < 300:
            return
        self._log_request_failure(
            response.status,
            method=method,
            url=url,
            operation=operation,
            payload=payload,
            body=body,
            content_type=content_type,
        )
        if response.status in (401, 403):
            raise AuthError("Authentication failed.")
        if response.status in (502, 503, 504):
            raise NetworkError(f"Provider temporarily unavailable (status {response.status}).")
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

    async def fetch_all(self) -> tuple[Permit, list[Reservation], list[Favorite]]:
        """Return permit, reservations, and favorites in a single batch.

        Providers that serve all three from a single HTTP response should override
        this method for efficiency. The default implementation calls the three
        individual methods concurrently.
        """
        permit, reservations, favorites = await asyncio.gather(
            self.get_permit(),
            self.list_reservations(),
            self.list_favorites(),
        )
        return permit, reservations, favorites

    @abstractmethod
    async def login(
        self,
        credentials: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> None:
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
        start_time: datetime,
        end_time: datetime,
        name: str | None = None,
    ) -> Reservation:
        """Start a reservation for a license plate."""

    @abstractmethod
    async def update_reservation(
        self,
        reservation_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        name: str | None = None,
    ) -> Reservation:
        """Update a reservation."""

    @abstractmethod
    async def end_reservation(
        self,
        reservation_id: str,
        end_time: datetime,
    ) -> Reservation:
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
        """Update a favorite."""
        if not self.favorite_update_possible:
            self._logger.info(
                "Provider %s favorite update requested but not supported",
                self.provider_id,
            )
            raise ProviderError("Favorite updates are not supported.")
        if license_plate is not None and "license_plate" not in self.favorite_update_fields:
            raise ValidationError("license_plate updates are not supported.")
        if name is not None and "name" not in self.favorite_update_fields:
            raise ValidationError("name updates are not supported.")
        self._log_operation_started("update_favorite")
        return await self._update_favorite_native(
            favorite_id,
            license_plate=license_plate,
            name=name,
        )

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
