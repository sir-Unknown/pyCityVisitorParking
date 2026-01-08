from pycityvisitorparking.exceptions import (
    AuthError,
    ConfigError,
    NetworkError,
    NotFoundError,
    ProviderError,
    PyCityVisitorParkingError,
    RateLimitError,
    ServiceUnavailableError,
    TimeoutError,
    ValidationError,
)


def test_error_defaults() -> None:
    exc = PyCityVisitorParkingError("base error")
    assert exc.error_type == "unknown"
    assert exc.error_code is None
    assert exc.detail == "base error"
    assert exc.user_message is None


def test_error_detail_fallback() -> None:
    exc = ProviderError(detail="short detail")
    assert str(exc) == "short detail"
    assert exc.detail == "short detail"
    assert exc.error_code == "provider_error"


def test_error_overrides() -> None:
    exc = NetworkError(
        "network down",
        error_code="network_timeout",
        detail="timeout talking to provider",
        user_message="Network issue. Please try again later.",
    )
    assert exc.error_type == "network"
    assert exc.error_code == "network_timeout"
    assert exc.detail == "timeout talking to provider"
    assert exc.user_message == "Network issue. Please try again later."


def test_error_types_have_codes() -> None:
    assert AuthError("nope").error_code == "auth_error"
    assert NetworkError("nope").error_code == "network_error"
    assert ValidationError("nope").error_code == "validation_error"
    assert ProviderError("nope").error_code == "provider_error"
    assert RateLimitError("nope").error_code == "rate_limit"
    assert ServiceUnavailableError("nope").error_code == "service_unavailable"
    assert NotFoundError("nope").error_code == "not_found"
    assert TimeoutError("nope").error_code == "timeout"
    assert ConfigError("nope").error_code == "config_error"
