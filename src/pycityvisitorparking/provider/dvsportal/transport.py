"""Transport helpers for the refactored DVS Portal provider."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Any

import aiohttp

from ...exceptions import AuthError, ProviderError
from ..logger import ProviderLogger
from .const import APP_ENV_SCRIPT, AUTH_HEADER, DEFAULT_HEADERS, RETRY_AFTER_HEADER, XSRF_HEADER

_XSRF_COOKIE_NAME_RE = re.compile(r"window\.__env\.xsrfCookieName\s*=\s*['\"]([^'\"]+)['\"]")

if TYPE_CHECKING:
    from .profile import PortalProfile
    from .session import PortalSessionState


class PortalTransport:
    """Encapsulate authenticated request behavior for portal variants."""

    def __init__(
        self,
        provider: Any,
        state: PortalSessionState,
        profile: PortalProfile,
        plogger: ProviderLogger,
    ) -> None:
        """Initialize transport helpers with shared provider state."""
        self._provider = provider
        self._state = state
        self._profile = profile
        self._plogger = plogger

    async def fetch_app_env(self) -> None:
        """Bootstrap the XSRF cookie before login.

        The DVSPortal Angular app reads window.__env.xsrfCookieName from
        app.env.js and then sends that cookie value as the X-XSRF-TOKEN
        header on every request.  In normal browser use the XSRF cookie is
        set by the server when the Angular HTML page (GET /DVSPortal/) is
        loaded — before any API call is made.  Because we never load that
        page, we have to replicate those two steps explicitly:

        1. GET app.env.js  — parse xsrfCookieName so we know which cookie
           to look for in the jar.
        2. GET the Angular HTML page — ask the server to issue the XSRF
           cookie so it lands in the aiohttp session cookie jar.

        Both steps are executed once per provider lifetime and any failure
        is silently ignored so the login flow is never blocked.
        """
        if self._state.app_env_fetched:
            return

        api_uri = self._provider._api_uri or ""
        base_url = self._provider._base_url or ""
        # Derive the app base path from the api_uri.
        # e.g. /DVSPortal/api  ->  /DVSPortal
        #      /DVSWebAPI/api  ->  /DVSWebAPI
        app_base = api_uri[:-4] if api_uri.endswith("/api") else api_uri.rstrip("/")
        timeout = aiohttp.ClientTimeout(total=10)

        step1_ok = False
        step2_ok = False

        # Step 1: fetch app.env.js to discover xsrfCookieName.
        env_url = f"{base_url}{app_base}/{APP_ENV_SCRIPT}"
        try:
            async with self._provider._session.request("GET", env_url, timeout=timeout) as response:
                if response.status == 200:
                    body = await response.text()
                    match = _XSRF_COOKIE_NAME_RE.search(body)
                    if match:
                        cookie_name = match.group(1)
                        self._profile.update_xsrf_cookie_name(cookie_name)
                        self._plogger.debug(
                            "discovered xsrfCookieName=%r from %s",
                            cookie_name,
                            env_url,
                        )
                        step1_ok = True
                    else:
                        self._plogger.debug(
                            "app.env.js missing xsrfCookieName url=%s",
                            env_url,
                        )
                else:
                    self._plogger.debug(
                        "app.env.js bootstrap status=%s url=%s",
                        response.status,
                        env_url,
                    )
        except Exception as exc:
            self._plogger.debug(
                "app.env.js bootstrap failed url=%s error=%s",
                env_url,
                exc.__class__.__name__,
            )

        # Step 2: load the Angular HTML page so the server sets the XSRF
        # cookie in the aiohttp session cookie jar.  This mirrors what a
        # browser does before making any API call.
        html_url = f"{base_url}{app_base}/"
        try:
            async with self._provider._session.request(
                "GET", html_url, timeout=timeout
            ) as response:
                self._plogger.debug(
                    "fetched app HTML status=%s url=%s",
                    response.status,
                    html_url,
                )
                await response.read()
                if response.status == 200:
                    step2_ok = True
        except Exception as exc:
            self._plogger.debug(
                "app HTML bootstrap failed url=%s error=%s",
                html_url,
                exc.__class__.__name__,
            )

        if step1_ok and step2_ok:
            self._state.app_env_fetched = True

    async def ensure_authenticated(self) -> None:
        """Ensure the provider has a valid session or token."""
        if self._state.token is None and not self._state.session_authenticated:
            if not self._state.credentials:
                raise AuthError("Authentication required.")
            await self._provider.login(self._state.credentials)

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
        allow_reauth: bool = False,
        include_auth: bool = False,
        operation: str | None = None,
    ) -> Any:
        """Perform a JSON request with optional auth and reauth handling."""
        url = self._provider._build_url(path)

        request_headers = self._compose_headers(
            url,
            extra=headers,
            include_auth=include_auth,
        )
        self._log_request_context(
            method,
            url,
            headers=request_headers,
            include_auth=include_auth,
        )

        async def perform_request() -> Any:
            return await self._request_with_backoff(
                method,
                url,
                expect_json=True,
                json=json,
                headers=request_headers,
                operation=operation,
            )

        async def handle_reauth() -> None:
            await self._reauthenticate()
            request_headers.clear()
            request_headers.update(
                self._compose_headers(url, extra=headers, include_auth=include_auth)
            )

        return await self._provider._request_with_optional_reauth(
            allow_reauth=allow_reauth,
            request=perform_request,
            on_reauth=handle_reauth,
        )

    async def request_json_auth(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        operation: str | None = None,
    ) -> Any:
        """Perform an authenticated JSON request."""
        await self.ensure_authenticated()
        return await self.request_json(
            method,
            path,
            json=json,
            allow_reauth=True,
            include_auth=True,
            operation=operation,
        )

    async def _request_with_backoff(
        self,
        method: str,
        url: str,
        *,
        expect_json: bool,
        json: Any,
        headers: dict[str, str],
        operation: str | None,
    ) -> Any:
        """Run a request and map response failures into provider exceptions."""

        async def handle_response(
            response: aiohttp.ClientResponse,
            attempt: int,
            attempts: int,
        ) -> Any:
            if response.status == 429:
                await self._handle_rate_limit(response, method, attempt, attempts)
                raise self._provider._RetryRequest()
            if not 200 <= response.status < 300:
                body = await response.text()
                content_type = response.headers.get("Content-Type")
                self._plogger.request_failure(
                    response.status,
                    method=method,
                    url=url,
                    operation=operation,
                    payload=json,
                    body=body,
                    content_type=content_type,
                )
                if response.status in (401, 403):
                    raise AuthError("Authentication failed.")
                if (
                    response.status >= 500
                    and "html" in (content_type or "").lower()
                    and self._state.credentials
                ):
                    raise AuthError("Session expired: HTML response to API call.")
                raise ProviderError(f"Provider request failed with status {response.status}.")
            self._plogger.response_status(response.status)
            if expect_json:
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    self._plogger.invalid_json(await response.text())
                    raise ProviderError("Response did not contain valid JSON.") from exc
                self._plogger.response_summary(data)
                return data
            return await response.text()

        return await self._provider._request_with_retries(
            method,
            url,
            request_kwargs={"headers": headers, "json": json},
            response_handler=handle_response,
        )

    async def _handle_rate_limit(
        self,
        response: aiohttp.ClientResponse,
        method: str,
        attempt: int,
        attempts: int,
    ) -> None:
        """Respect provider rate limit responses."""
        try:
            delay = int(response.headers.get(RETRY_AFTER_HEADER, 0))
        except ValueError:
            delay = 0
        if delay > 0:
            await asyncio.sleep(delay)
        if method.upper() != "GET" or attempt >= attempts - 1:
            raise ProviderError("Provider rate limit exceeded.")

    async def _reauthenticate(self) -> None:
        """Clear auth state and re-login using cached credentials."""
        self._plogger.warning_block(
            "reauthenticating",
            {
                "token-present": self._state.token is not None,
                "session-authenticated": self._state.session_authenticated,
                "credentials-present": bool(self._state.credentials),
            },
        )
        self._state.token = None
        self._state.auth_header_value = None
        self._state.session_authenticated = False
        self._state.app_env_fetched = False
        if not self._state.credentials:
            raise AuthError("Authentication required.")
        await self._provider.login(self._state.credentials)

    def _compose_headers(
        self,
        url: str,
        *,
        extra: dict[str, str] | None,
        include_auth: bool,
    ) -> dict[str, str]:
        """Compose request headers for a portal request."""
        merged_headers = {**DEFAULT_HEADERS, **(extra or {})}
        if include_auth and self._state.auth_header_value is not None:
            merged_headers[AUTH_HEADER] = self._state.auth_header_value
        cookie_jar = getattr(self._provider._session, "cookie_jar", None)
        merged_headers.update(self._profile.xsrf_headers(cookie_jar, url=url))
        return merged_headers

    def _log_request_context(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        include_auth: bool,
    ) -> None:
        """Log safe request-context flags for troubleshooting auth/session issues."""
        self._plogger.debug(
            "request context method=%s url=%s include_auth=%s "
            "auth_header_present=%s xsrf_header_present=%s "
            "session_authenticated=%s token_present=%s "
            "permit_media_code=%s",
            method.upper(),
            url,
            include_auth,
            AUTH_HEADER in headers,
            XSRF_HEADER in headers,
            self._state.session_authenticated,
            self._state.token is not None,
            self._plogger.mask_value(
                self._state.permit_media_code,
                parent_key="permit_media_code",
            ),
        )
