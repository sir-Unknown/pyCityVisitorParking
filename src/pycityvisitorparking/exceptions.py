"""Library exceptions.

Exceptions are technical and integration-facing. Callers should branch on the
exception type and/or :attr:`PyCityVisitorParkingError.error_code`, never on the
message text. User-facing (translated) messages are owned by the integration.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable, machine-readable error codes carried by library exceptions."""

    AUTH_ERROR = "auth_error"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    VALIDATION_ERROR = "validation_error"
    CONFIG_ERROR = "config_error"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMIT = "rate_limit"
    SERVICE_UNAVAILABLE = "service_unavailable"
    NOT_FOUND = "not_found"
    NOT_SUPPORTED = "not_supported"
    PROVIDER_REJECTED = "provider_rejected"


class PyCityVisitorParkingError(Exception):
    """Base exception for the library."""

    error_type = "unknown"
    default_error_code: ErrorCode | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: ErrorCode | None = None,
        detail: str | None = None,
    ) -> None:
        """Initialize the exception with a technical message and safe metadata."""
        if message is None and detail is not None:
            message = detail
        if message is None:
            super().__init__()
        else:
            super().__init__(message)
        self.error_code = error_code or self.default_error_code
        self.detail = detail if detail is not None else (message or "")


class AuthError(PyCityVisitorParkingError):
    """Raised when authentication fails."""

    error_type = "auth"
    default_error_code = ErrorCode.AUTH_ERROR


class NetworkError(PyCityVisitorParkingError):
    """Raised when network communication fails."""

    error_type = "network"
    default_error_code = ErrorCode.NETWORK_ERROR


class ValidationError(PyCityVisitorParkingError):
    """Raised when inputs fail validation."""

    error_type = "validation"
    default_error_code = ErrorCode.VALIDATION_ERROR


class ProviderError(PyCityVisitorParkingError):
    """Raised when a provider returns an error or is misconfigured."""

    error_type = "provider"
    default_error_code = ErrorCode.PROVIDER_ERROR


class RateLimitError(ProviderError):
    """Raised when a provider rate limit is exceeded."""

    error_type = "provider"
    default_error_code = ErrorCode.RATE_LIMIT


class ServiceUnavailableError(ProviderError):
    """Raised when a provider is temporarily unavailable or in maintenance."""

    error_type = "provider"
    default_error_code = ErrorCode.SERVICE_UNAVAILABLE


class NotFoundError(ProviderError):
    """Raised when a provider resource is not found."""

    error_type = "provider"
    default_error_code = ErrorCode.NOT_FOUND


class TimeoutError(NetworkError):
    """Raised when a network operation times out."""

    error_type = "network"
    default_error_code = ErrorCode.TIMEOUT


class ConfigError(ValidationError):
    """Raised when configuration inputs are invalid or missing."""

    error_type = "validation"
    default_error_code = ErrorCode.CONFIG_ERROR
