"""Session state for the refactored DVS Portal provider."""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class PortalSessionState:
    """Mutable authentication and runtime state for the provider."""

    token: str | None = None
    auth_header_value: str | None = None
    session_authenticated: bool = False
    credentials: dict[str, str] | None = None
    permit_media_type_id: str | int | None = None
    permit_media_code: str | None = None
    api_timezone: ZoneInfo | None = None
    app_env_fetched: bool = False
