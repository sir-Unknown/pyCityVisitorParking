"""Transport helpers for the refactored DVS Portal provider."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import aiohttp

from ...exceptions import AuthError, ProviderError
from ..logger import get_provider_logger
from .const import AUTH_HEADER, DEFAULT_HEADERS, RETRY_AFTER_HEADER, XSRF_HEADER

if TYPE_CHECKING:
    from .api import Provider
    from .profile import PortalProfile
    from .session import PortalSessionState

_LOGGER = get_provider_logger(__name__)


class PortalTransport:
    """Encapsulate authenticated request behavior for portal variants."""

    def __init__(
        self,
        provider: Provider,
        state: PortalSessionState,
        profile: PortalProfile,
    ) -> None:
        """Initialize transport helpers with shared provider state."""
        self._provider = provider
        self._state = state
        self._profile = profile

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
    ) -> Any:
        """Perform an authenticated JSON request."""
        await self.ensure_authenticated()
        return await self.request_json(
            method,
            path,
            json=json,
            allow_reauth=True,
            include_auth=True,
        )

    async def _request_with_backoff(
        self,
        method: str,
        url: str,
        *,
        expect_json: bool,
        json: Any,
        headers: dict[str, str],
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
                self._provider._log_request_failure(
                    response.status,
                    method=method,
                    url=url,
                    payload=json,
                    body=body,
                    content_type=content_type,
                )
                if response.status in (401, 403):
                    raise AuthError("Authentication failed.")
                raise ProviderError(f"Provider request failed with status {response.status}.")
            self._provider._log_response_status(response.status)
            if expect_json:
                try:
                    data = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    self._provider._log_invalid_json(await response.text())
                    raise ProviderError("Response did not contain valid JSON.") from exc
                self._provider._log_response_summary(data)
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
        self._provider._log_warning_block(
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
        _LOGGER.debug(
            "Provider %s request context method=%s url=%s include_auth=%s "
            "auth_header_present=%s xsrf_header_present=%s "
            "session_authenticated=%s token_present=%s "
            "permit_media_type_id=%s permit_media_code=%s",
            self._provider.provider_id,
            method.upper(),
            url,
            include_auth,
            AUTH_HEADER in headers,
            XSRF_HEADER in headers,
            self._state.session_authenticated,
            self._state.token is not None,
            self._state.permit_media_type_id,
            self._state.permit_media_code,
        )
