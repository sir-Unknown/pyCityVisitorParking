"""Library exceptions."""


class PyCityVisitorParkingError(Exception):
    """Base exception for the library."""

    error_type = "unknown"
    default_error_code = None

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: str | None = None,
        detail: str | None = None,
        user_message: str | None = None,
    ) -> None:
        """Initialize exception metadata with safe, optional user messaging."""
        if message is None and detail is not None:
            message = detail
        if message is None:
            super().__init__()
        else:
            super().__init__(message)
        self.error_code = error_code or self.default_error_code
        self.detail = detail if detail is not None else (message or "")
        self.user_message = user_message


class AuthError(PyCityVisitorParkingError):
    """Raised when authentication fails."""

    error_type = "auth"
    default_error_code = "auth_error"


class NetworkError(PyCityVisitorParkingError):
    """Raised when network communication fails."""

    error_type = "network"
    default_error_code = "network_error"


class ValidationError(PyCityVisitorParkingError):
    """Raised when inputs fail validation."""

    error_type = "validation"
    default_error_code = "validation_error"


class ProviderError(PyCityVisitorParkingError):
    """Raised when a provider returns an error or is misconfigured."""

    error_type = "provider"
    default_error_code = "provider_error"


class RateLimitError(ProviderError):
    """Raised when a provider rate limit is exceeded."""

    error_type = "provider"
    default_error_code = "rate_limit"


class ServiceUnavailableError(ProviderError):
    """Raised when a provider is unavailable or in maintenance."""

    error_type = "provider"
    default_error_code = "service_unavailable"


class NotFoundError(ProviderError):
    """Raised when a provider resource is not found."""

    error_type = "provider"
    default_error_code = "not_found"


class TimeoutError(NetworkError):
    """Raised when a network operation times out."""

    error_type = "network"
    default_error_code = "timeout"


class ConfigError(ValidationError):
    """Raised when configuration inputs are invalid or missing."""

    error_type = "validation"
    default_error_code = "config_error"
