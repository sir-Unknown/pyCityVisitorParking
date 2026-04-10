"""Profile-specific request behavior for DVS Portal variants."""

from __future__ import annotations

import base64
from collections.abc import Iterable
from http.cookies import Morsel
from typing import Any, Protocol

from yarl import URL

from .const import (
    AUTH_PREFIX,
    DEFAULT_XSRF_COOKIE_NAMES,
    LOGIN_METHOD_PAS,
    XSRF_HEADER,
)


class _CookieJarLike(Protocol):
    """Minimal cookie-jar interface needed for XSRF header extraction."""

    def filter_cookies(self, url: URL) -> dict[str, Morsel[str]]:
        """Return cookies applicable to the provided URL."""
        ...


class PortalProfile:
    """Describe auth and request conventions for a portal variant."""

    def __init__(
        self,
        *,
        login_method: int = LOGIN_METHOD_PAS,
        xsrf_cookie_names: Iterable[str] = DEFAULT_XSRF_COOKIE_NAMES,
    ) -> None:
        """Initialize immutable profile settings."""
        self._login_method = login_method
        self._xsrf_cookie_names = tuple(name for name in xsrf_cookie_names if name)

    def build_login_payload(
        self,
        *,
        username: str,
        password: str,
        permit_media_type_id: str | int,
    ) -> dict[str, Any]:
        """Build the provider login payload."""
        return {
            "identifier": username,
            "loginMethod": self._login_method,
            "password": password,
            "otp": None,
            "resetCode": None,
            "asIdentifier": None,
            "zipCode": None,
            "permitMediaTypeID": permit_media_type_id,
        }

    def normalize_login_status(self, value: Any) -> int | Any:
        """Normalize mixed-type login status values from the provider."""
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return value

    def build_auth_header(self, token: str) -> str:
        """Return the provider Authorization header value for a raw token."""
        encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
        return f"{AUTH_PREFIX}{encoded}"

    def is_login_error(self, data: dict[str, Any], status_value: Any) -> bool:
        """Return whether the login response represents an auth failure."""
        return status_value == 2 or bool(data.get("ErrorMessage"))

    def xsrf_headers(
        self,
        cookie_jar: _CookieJarLike | None,
        *,
        url: str,
    ) -> dict[str, str]:
        """Return XSRF headers for a request when a matching cookie exists."""
        if cookie_jar is None:
            return {}
        cookies = cookie_jar.filter_cookies(URL(url))
        for cookie_name in self._xsrf_cookie_names:
            cookie = cookies.get(cookie_name)
            if cookie is not None and cookie.value:
                return {XSRF_HEADER: cookie.value}
        return {}


class DvsPortalProfile(PortalProfile):
    """Default DVS Portal profile using the observed PAS login flow."""
