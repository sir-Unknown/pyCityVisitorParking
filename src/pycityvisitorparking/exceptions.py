"""Library exceptions."""


class PyCityVisitorParkingError(Exception):
    """Base exception for the library."""


class AuthError(PyCityVisitorParkingError):
    """Raised when authentication fails."""


class NetworkError(PyCityVisitorParkingError):
    """Raised when network communication fails."""


class ValidationError(PyCityVisitorParkingError):
    """Raised when inputs fail validation."""


class ProviderError(PyCityVisitorParkingError):
    """Raised when a provider returns an error or is misconfigured."""
