import pytest

from pycityvisitorparking.exceptions import (
    AuthError,
    ConfigError,
    ErrorCode,
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
    assert not hasattr(exc, "user_message")


def test_error_detail_fallback() -> None:
    exc = ProviderError(detail="short detail")
    assert str(exc) == "short detail"
    assert exc.detail == "short detail"
    assert exc.error_code == "provider_error"


def test_error_code_override() -> None:
    exc = ProviderError(
        "Favorite updates are not supported.",
        error_code=ErrorCode.NOT_SUPPORTED,
        detail="update_favorite",
    )
    assert exc.error_type == "provider"
    assert exc.error_code == "not_supported"
    assert exc.detail == "update_favorite"


@pytest.mark.parametrize(
    ("exc_type", "code"),
    [
        (AuthError, "auth_error"),
        (NetworkError, "network_error"),
        (ValidationError, "validation_error"),
        (ProviderError, "provider_error"),
        (RateLimitError, "rate_limit"),
        (ServiceUnavailableError, "service_unavailable"),
        (NotFoundError, "not_found"),
        (TimeoutError, "timeout"),
        (ConfigError, "config_error"),
    ],
)
def test_error_types_have_stable_codes(
    exc_type: type[PyCityVisitorParkingError], code: str
) -> None:
    error_code = exc_type("nope").error_code
    assert error_code == code
    assert isinstance(error_code, ErrorCode)


def test_documented_error_codes_are_stable() -> None:
    assert {code.value for code in ErrorCode} == {
        "auth_error",
        "network_error",
        "timeout",
        "validation_error",
        "config_error",
        "provider_error",
        "rate_limit",
        "service_unavailable",
        "not_found",
        "not_supported",
        "provider_rejected",
    }
