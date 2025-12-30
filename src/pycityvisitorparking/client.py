"""Client facade for provider discovery and instantiation."""

from __future__ import annotations

import asyncio
import importlib

import aiohttp

from .exceptions import ProviderError
from .models import ProviderInfo
from .provider.base import BaseProvider
from .provider.loader import ProviderManifest, get_manifest, list_providers

_DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)


def _load_provider_data(provider_id: str) -> tuple[ProviderManifest, type[BaseProvider]]:
    if not provider_id:
        raise ProviderError("Provider id is required.")
    manifest = get_manifest(provider_id)
    module_name = f"pycityvisitorparking.provider.{provider_id}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise ProviderError("Provider module could not be imported.") from exc
    provider_cls = getattr(module, "Provider", None)
    if provider_cls is None:
        raise ProviderError("Provider module does not export Provider.")
    if not isinstance(provider_cls, type) or not issubclass(provider_cls, BaseProvider):
        raise ProviderError("Provider must inherit from BaseProvider.")
    return manifest, provider_cls


class Client:
    """Facade for provider discovery and access."""

    def __init__(
        self,
        session: aiohttp.ClientSession | None = None,
        *,
        base_url: str | None = None,
        api_uri: str | None = None,
        timeout: aiohttp.ClientTimeout | None = None,
        retry_count: int = 0,
    ) -> None:
        self._session = session
        self._owns_session = session is None
        self._base_url = base_url
        self._api_uri = api_uri
        self._timeout = timeout or _DEFAULT_TIMEOUT
        self._retry_count = max(0, retry_count)

    async def __aenter__(self) -> Client:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def list_providers(self) -> list[ProviderInfo]:
        return await asyncio.to_thread(list_providers)

    async def get_provider(
        self,
        provider_id: str,
        *,
        base_url: str | None = None,
        api_uri: str | None = None,
    ) -> BaseProvider:
        manifest, provider_cls = await asyncio.to_thread(_load_provider_data, provider_id)
        session = self._ensure_session()
        return provider_cls(
            session,
            manifest,
            base_url=base_url if base_url is not None else self._base_url,
            api_uri=api_uri if api_uri is not None else self._api_uri,
            timeout=self._timeout,
            retry_count=self._retry_count,
        )

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session
