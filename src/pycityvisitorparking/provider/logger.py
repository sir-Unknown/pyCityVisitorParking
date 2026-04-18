"""Shared logging helpers for provider modules."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

_PROVIDER_LOGGER_NAME = "pycityvisitorparking.provider"

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


def get_provider_logger(module_name: str | None = None) -> logging.Logger:
    """Return a provider logger using a consistent logger hierarchy."""
    if not module_name:
        return logging.getLogger(_PROVIDER_LOGGER_NAME)
    if module_name == _PROVIDER_LOGGER_NAME:
        return logging.getLogger(module_name)
    if module_name.startswith(f"{_PROVIDER_LOGGER_NAME}."):
        return logging.getLogger(module_name)
    return logging.getLogger(f"{_PROVIDER_LOGGER_NAME}.{module_name}")


class ProviderLogger:
    """Structured logging helper bound to a specific provider instance.

    Encapsulates all formatted log output for provider operations so that
    ``BaseProvider`` and transport helpers stay focused on HTTP/API logic.
    Metadata (provider id, city, version strings) is fetched lazily on each
    call via *get_metadata*, which allows the context to evolve after
    construction (e.g. when ``set_request_context`` or
    ``set_runtime_versions`` is called on the provider).
    """

    def __init__(
        self,
        logger: logging.Logger,
        get_metadata: Callable[[], tuple[str, str, str, str]],
    ) -> None:
        """Initialise with a logger and a metadata callback.

        Args:
            logger: The :class:`logging.Logger` to emit records on.
            get_metadata: Callable that returns
                ``(provider_id, city, ha_cvp_version, pycvp_version)``.
        """
        self._logger = logger
        self._get_metadata = get_metadata

    # ------------------------------------------------------------------
    # Masking
    # ------------------------------------------------------------------

    def mask_value(self, value: Any, *, parent_key: str | None = None) -> Any:
        """Return a copy of *value* with sensitive fields replaced by ``'***'``."""
        if parent_key in _SENSITIVE_KEYS:
            return "***" if value is not None else None
        if isinstance(value, dict):
            return {
                key: ("***" if key in _SENSITIVE_KEYS else self.mask_value(item, parent_key=key))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.mask_value(item, parent_key=parent_key) for item in value]
        if parent_key in _SENSITIVE_OBJECT_KEYS:
            return "***" if value is not None else None
        if parent_key in _SENSITIVE_NESTED_KEYS:
            return "***" if value is not None else None
        return value

    def mask_payload(self, payload: Any) -> Any:
        """Return a masked copy of a request payload."""
        return self.mask_value(payload)

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    def summarize_text(self, value: str) -> str:
        """Compact whitespace and truncate *value* for safe log output."""
        compact = " ".join(value.split())
        if len(compact) > _MAX_LOG_BODY_CHARS:
            return compact[: _MAX_LOG_BODY_CHARS - 3] + "..."
        return compact

    def build_response_summary(self, data: Any) -> dict[str, Any]:
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
                summary["error-message"] = self.summarize_text(str(data["ErrorMessage"]))
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

    # ------------------------------------------------------------------
    # Core log emitters
    # ------------------------------------------------------------------

    def debug(self, message: str, *args: Any) -> None:
        """Emit a DEBUG line prefixed with ``Provider {id}``."""
        provider_id = self._get_metadata()[0]
        self._logger.debug("Provider %s " + message, provider_id, *args)

    def info(self, message: str, *args: Any) -> None:
        """Emit an INFO line prefixed with ``Provider {id}``."""
        provider_id = self._get_metadata()[0]
        self._logger.info("Provider %s " + message, provider_id, *args)

    def log(self, level: int, message: str, *args: Any) -> None:
        """Emit a log line at *level* appending full provider metadata."""
        provider, city, ha_cvp, pycvp = self._get_metadata()
        self._logger.log(
            level,
            f"{message} (provider=%s, city=%s, hacvp=%s, pycvp=%s)",
            *args,
            provider,
            city,
            ha_cvp,
            pycvp,
        )

    def warning_block(
        self,
        label: str,
        fields: dict[str, Any],
        *,
        detail: str | None = None,
    ) -> None:
        """Emit a WARNING as a labelled multi-line key=value block with metadata."""
        provider, city, ha_cvp, pycvp = self._get_metadata()
        all_fields = {k: v for k, v in fields.items() if v is not None}
        all_fields.update({"provider": provider, "city": city, "hacvp": ha_cvp, "pycvp": pycvp})
        width = max(len(k) for k in all_fields)
        lines = [label]
        if detail:
            lines.append(f"  {detail}")
        for key, value in all_fields.items():
            lines.append(f"  {key:<{width}} = {value}")
        self._logger.warning("%s", "\n".join(lines))

    # ------------------------------------------------------------------
    # Operation lifecycle
    # ------------------------------------------------------------------

    def operation_started(self, operation: str, **details: Any) -> None:
        """Log the start of a provider operation."""
        self.debug("%s started%s", operation, self._format_details(**details))

    def operation_completed(self, operation: str, **details: Any) -> None:
        """Log successful completion of a provider operation."""
        self.debug("%s completed%s", operation, self._format_details(**details))

    def operation_failed(self, operation: str, reason: str, **details: Any) -> None:
        """Log a provider operation failure before raising an error."""
        self.debug("%s failed: %s%s", operation, reason, self._format_details(**details))

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def reauth_triggered(self) -> None:
        """Log when a request falls back to reauthentication."""
        self.warning_block("reauth triggered", {})

    def reauthenticating(self) -> None:
        """Log when cached credentials are used to reauthenticate."""
        self.debug("reauthenticating with cached credentials")

    # ------------------------------------------------------------------
    # HTTP response / request
    # ------------------------------------------------------------------

    def response_status(self, status: int) -> None:
        """Log the HTTP response status."""
        self.debug("response status=%s", status)

    def response_summary(self, data: Any) -> None:
        """Log a safe debug summary of a successful JSON response."""
        self.debug("response summary %s", self.mask_value(self.build_response_summary(data)))

    def request_failure(
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
            fields["payload"] = self.mask_payload(payload)
        if fields["response_kind"] == "html" and body:
            fields.update(self._extract_html_log_fields(body))
        elif body:
            fields["body"] = self.summarize_text(body)
        self.warning_block(label, fields, detail=detail)

    def invalid_json(self, body: str) -> None:
        """Log an invalid JSON response body."""
        self.warning_block("invalid json response", {"body": self.summarize_text(body)})

    # ------------------------------------------------------------------
    # Domain events
    # ------------------------------------------------------------------

    def missing_response_data(
        self,
        label: str,
        fallback: str = "refetching",
        *,
        response_data: Any = None,
    ) -> None:
        """Log when a response is missing expected data and a fallback is used."""
        fields: dict[str, Any] = {"operation": label, "fallback": fallback}
        if isinstance(response_data, dict):
            summary = self.build_response_summary(response_data)
            if "response-keys" in summary:
                fields["response-keys"] = summary["response-keys"]
            if "error-message" in summary:
                fields["error-message"] = summary["error-message"]
            message = response_data.get("Message")
            if message and "error-message" not in fields:
                fields["error-message"] = self.summarize_text(str(message))
        self.warning_block("missing permit in response", fields)

    def provider_error_response(
        self,
        data: dict[str, Any],
        *,
        operation: str | None = None,
    ) -> None:
        """Log when a provider returns HTTP 200 with an ErrorMessage in the body.

        DVS Portal signals application-level failures via ``ErrorMessage`` +
        ``Result`` fields in an otherwise successful (2xx) response.  Logging
        this as its own warning makes the root cause immediately visible,
        before any subsequent ``missing_response_data`` fallback message.
        """
        fields: dict[str, Any] = {}
        if operation:
            fields["operation"] = operation
        result = data.get("Result")
        if result is not None:
            fields["result"] = result
        error_message = data.get("ErrorMessage") or data.get("Message")
        if error_message:
            fields["error-message"] = self.summarize_text(str(error_message))
        self.warning_block("provider error in response", fields)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
            title = self.summarize_text(title_match.group(1))
            if title:
                fields["html_title"] = title
        base_match = _HTML_BASE_RE.search(body)
        if base_match:
            base_href = self.summarize_text(base_match.group(1))
            if base_href:
                fields["html_base_href"] = base_href
        if not fields:
            fields["body_excerpt"] = self.summarize_text(body)
        return fields

    def _response_keys_summary(self, data: dict[str, Any]) -> str:
        """Return a compact summary of top-level response keys."""
        keys = sorted(str(key) for key in data)
        if len(keys) > 12:
            return ", ".join(keys[:12]) + ", ..."
        return ", ".join(keys)

    def _format_details(self, **details: Any) -> str:
        """Serialize optional details as a compact key=value suffix."""
        if not details:
            return ""
        return " " + " ".join(f"{key}={value}" for key, value in details.items())
