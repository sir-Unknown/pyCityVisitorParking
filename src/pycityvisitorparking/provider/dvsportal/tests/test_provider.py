import logging
from datetime import UTC, datetime
from typing import Any

import aiohttp
import pytest
from yarl import URL

from pycityvisitorparking.exceptions import AuthError, ProviderError
from pycityvisitorparking.models import Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.dvsportal.api import Provider
from pycityvisitorparking.provider.dvsportal.const import (
    DEFAULT_API_URI,
    LOGIN_ENDPOINT,
    RESERVATION_CREATE_ENDPOINT,
    RESERVATION_UPDATE_ENDPOINT,
    XSRF_HEADER,
)
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.util import format_utc_timestamp, parse_timestamp

PERMIT_SAMPLE = {
    "ZoneCode": "ZONE-1",
    "BlockTimes": [
        {
            "IsFree": True,
            "ValidFrom": "2024-01-01T09:00:00+01:00",
            "ValidUntil": "2024-01-01T18:00:00+01:00",
        },
        {
            "IsFree": False,
            "ValidFrom": "2024-01-02T09:00:00+01:00",
            "ValidUntil": "2024-01-02T18:00:00+01:00",
        },
    ],
    "PermitMedias": [
        {
            "TypeID": 1,
            "Code": "CARD-1",
            "Balance": "120",
            "ActiveReservations": [
                {
                    "ReservationID": "123",
                    "ValidFrom": "2024-01-01T10:00:00+01:00",
                    "ValidUntil": "2024-01-01T11:00:00+01:00",
                    "LicensePlate": {
                        "Value": "ab-12 cd",
                        "DisplayValue": "AB-12-CD",
                    },
                }
            ],
            "LicensePlates": [{"Value": "xy-99-zz", "Name": "Family"}],
        }
    ],
}

PERMIT_SAMPLE_NAIVE = {
    "ZoneCode": "ZONE-1",
    "BlockTimes": [
        {
            "IsFree": False,
            "ValidFrom": "2024-07-01T09:00:00",
            "ValidUntil": "2024-07-01T18:00:00",
        },
    ],
    "PermitMedias": [
        {
            "TypeID": 1,
            "Code": "CARD-1",
            "Balance": "120",
            "ActiveReservations": [
                {
                    "ReservationID": "456",
                    "ValidFrom": "2024-07-01T10:00:00",
                    "ValidUntil": "2024-07-01T11:00:00",
                    "LicensePlate": {
                        "Value": "ab-12 cd",
                        "DisplayValue": "AB-12-CD",
                    },
                }
            ],
            "LicensePlates": [],
        }
    ],
}


def _manifest() -> ProviderManifest:
    return ProviderManifest(
        id="dvsportal",
        name="DVS Portal (Refactored)",
        favorite_update_fields=(),
        reservation_update_fields=("end_time",),
    )


def assert_utc_timestamp(value: str) -> None:
    parsed = parse_timestamp(value)
    assert parsed.tzinfo == UTC
    assert format_utc_timestamp(parsed) == value


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int,
        text_data: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self._text_data = text_data
        self.headers = headers or {}

    async def json(self) -> object:
        raise ValueError("response is not JSON")

    async def text(self) -> str:
        return self._text_data

    async def read(self) -> bytes:
        return self._text_data.encode()


class _FakeRequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FailingSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.cookie_jar = None
        self._response = response

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeRequestContext:
        return _FakeRequestContext(self._response)


@pytest.mark.asyncio
async def test_map_permit_filters_free_blocks_and_converts_utc() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        permit = provider._map_permit(PERMIT_SAMPLE)

    assert permit.id == "CARD-1"
    assert permit.remaining_balance == 120
    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-01-02T08:00:00Z",
            end_time="2024-01-02T17:00:00Z",
        )
    ]
    for block in permit.zone_validity:
        assert_utc_timestamp(block.start_time)
        assert_utc_timestamp(block.end_time)


@pytest.mark.asyncio
async def test_map_reservations_converts_naive_local_to_utc() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        permit_media = PERMIT_SAMPLE_NAIVE["PermitMedias"][0]
        reservations = provider._map_reservations(permit_media)

    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.start_time == "2024-07-01T08:00:00Z"
    assert reservation.end_time == "2024-07-01T09:00:00Z"


@pytest.mark.asyncio
async def test_extract_permit_prefers_cached_media_from_permits_list() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._permit_media_code = "CARD-2"
        permit = provider._extract_permit(
            {
                "Permits": [
                    {"ZoneCode": "ZONE-1", "PermitMedias": [{"Code": "CARD-1", "TypeID": 1}]},
                    {"ZoneCode": "ZONE-2", "PermitMedias": [{"Code": "CARD-2", "TypeID": 2}]},
                ]
            }
        )

    assert permit["ZoneCode"] == "ZONE-2"


@pytest.mark.asyncio
async def test_default_api_uri_is_applied() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")

    assert (
        provider._build_url(LOGIN_ENDPOINT) == f"https://example{DEFAULT_API_URI}{LOGIN_ENDPOINT}"
    )


@pytest.mark.asyncio
async def test_request_json_auth_includes_auth_and_xsrf_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        session.cookie_jar.update_cookies(
            {"XSRF-TOKEN": "xsrf-cookie"},
            response_url=URL("https://example/"),
        )
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._session_authenticated = True
        provider._auth_header_value = "Token token-value"
        captured: dict[str, Any] = {}

        async def _fake_request_with_retries(
            method: str,
            url: str,
            *,
            request_kwargs: dict[str, Any],
            response_handler: Any,
        ) -> Any:
            captured["method"] = method
            captured["url"] = url
            captured["request_kwargs"] = request_kwargs
            return {"ok": True}

        monkeypatch.setattr(provider, "_request_with_retries", _fake_request_with_retries)
        response = await provider._request_json_auth("POST", RESERVATION_CREATE_ENDPOINT, json={})

    assert response == {"ok": True}
    headers = captured["request_kwargs"]["headers"]
    assert headers["Authorization"] == "Token token-value"
    assert headers[XSRF_HEADER] == "xsrf-cookie"


@pytest.mark.asyncio
async def test_request_json_auth_omits_xsrf_header_without_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._session_authenticated = True
        provider._auth_header_value = "Token token-value"
        captured: dict[str, Any] = {}

        async def _fake_request_with_retries(
            method: str,
            url: str,
            *,
            request_kwargs: dict[str, Any],
            response_handler: Any,
        ) -> Any:
            captured["method"] = method
            captured["url"] = url
            captured["request_kwargs"] = request_kwargs
            return {"ok": True}

        monkeypatch.setattr(provider, "_request_with_retries", _fake_request_with_retries)
        await provider._request_json_auth("POST", RESERVATION_CREATE_ENDPOINT, json={})

    headers = captured["request_kwargs"]["headers"]
    assert headers["Authorization"] == "Token token-value"
    assert XSRF_HEADER not in headers


@pytest.mark.asyncio
async def test_request_json_auth_logs_safe_request_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with aiohttp.ClientSession() as session:
        session.cookie_jar.update_cookies(
            {"XSRF-TOKEN": "xsrf-cookie"},
            response_url=URL("https://example/"),
        )
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._session_authenticated = True
        provider._token = "raw-token"
        provider._auth_header_value = "Token token-value"
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"

        async def _fake_request_with_retries(
            method: str,
            url: str,
            *,
            request_kwargs: dict[str, Any],
            response_handler: Any,
        ) -> Any:
            return {"ok": True}

        monkeypatch.setattr(provider, "_request_with_retries", _fake_request_with_retries)
        caplog.set_level(logging.DEBUG, logger="pycityvisitorparking.provider")

        await provider._request_json_auth("POST", RESERVATION_CREATE_ENDPOINT, json={})

    assert "request context" in caplog.text
    assert "auth_header_present=True" in caplog.text
    assert "xsrf_header_present=True" in caplog.text
    assert "permit_media_code=***" in caplog.text
    assert "permit_media_type_id" not in caplog.text
    assert "raw-token" not in caplog.text
    assert "token-value" not in caplog.text
    assert "CARD-1" not in caplog.text


@pytest.mark.asyncio
async def test_login_without_token_falls_back_to_fetch_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        calls: list[tuple[str, str]] = []

        async def _fake_fetch_media_type(*, operation: str = "login") -> str | int:
            return 7

        async def _fake_request_json(
            method: str,
            path: str,
            *,
            json: Any | None = None,
            headers: dict[str, str] | None = None,
            allow_reauth: bool = False,
            include_auth: bool = False,
            operation: str | None = None,
        ) -> Any:
            calls.append((method, path))
            return {"LoginStatus": 1}

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            calls.append(("POST", "/login/getbase"))
            provider._permit_media_code = "CARD-7"
            return {
                "ZoneCode": "ZONE-1",
                "PermitMedias": [{"TypeID": 7, "Code": "CARD-7", "ActiveReservations": []}],
                "BlockTimes": [],
            }

        monkeypatch.setattr(provider, "_fetch_permit_media_type_id", _fake_fetch_media_type)
        monkeypatch.setattr(provider, "_request_json", _fake_request_json)
        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)

        await provider.login(credentials={"username": "user", "password": "secret"})

    assert provider._session_authenticated is True
    assert provider._token is None
    assert provider._permit_media_type_id == 7
    assert provider._permit_media_code == "CARD-7"
    assert calls == [("POST", LOGIN_ENDPOINT), ("POST", "/login/getbase")]


@pytest.mark.asyncio
async def test_login_with_permit_caches_defaults_without_fetch_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        fetched_base = {"called": False}

        async def _fake_fetch_media_type(*, operation: str = "login") -> str | int:
            return 3

        async def _fake_request_json(
            method: str,
            path: str,
            *,
            json: Any | None = None,
            headers: dict[str, str] | None = None,
            allow_reauth: bool = False,
            include_auth: bool = False,
            operation: str | None = None,
        ) -> Any:
            return {
                "LoginStatus": 1,
                "Token": "token-123",
                "Permit": {
                    "ZoneCode": "ZONE-1",
                    "PermitMedias": [{"TypeID": 3, "Code": "CARD-3", "ActiveReservations": []}],
                    "BlockTimes": [],
                },
            }

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            fetched_base["called"] = True
            return {}

        monkeypatch.setattr(provider, "_fetch_permit_media_type_id", _fake_fetch_media_type)
        monkeypatch.setattr(provider, "_request_json", _fake_request_json)
        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)

        await provider.login(credentials={"username": "user", "password": "secret"})

    assert provider._session_authenticated is True
    assert provider._token == "token-123"
    assert provider._permit_media_type_id == 3
    assert provider._permit_media_code == "CARD-3"
    assert fetched_base["called"] is False


@pytest.mark.asyncio
async def test_login_with_partial_permit_falls_back_to_fetch_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        fetched_base = {"called": False}

        async def _fake_fetch_media_type(*, operation: str = "login") -> str | int:
            return 3

        async def _fake_request_json(
            method: str,
            path: str,
            *,
            json: Any | None = None,
            headers: dict[str, str] | None = None,
            allow_reauth: bool = False,
            include_auth: bool = False,
            operation: str | None = None,
        ) -> Any:
            return {
                "LoginStatus": 1,
                "Token": "token-123",
                "Permit": {},
                "Permits": [{"ZoneCode": "ZONE-1"}],
            }

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            fetched_base["called"] = True
            provider._permit_media_type_id = 3
            provider._permit_media_code = "CARD-3"
            return {
                "ZoneCode": "ZONE-1",
                "PermitMedias": [{"TypeID": 3, "Code": "CARD-3", "ActiveReservations": []}],
                "BlockTimes": [],
            }

        monkeypatch.setattr(provider, "_fetch_permit_media_type_id", _fake_fetch_media_type)
        monkeypatch.setattr(provider, "_request_json", _fake_request_json)
        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)

        await provider.login(credentials={"username": "user", "password": "secret"})

    assert provider._session_authenticated is True
    assert provider._token == "token-123"
    assert provider._permit_media_type_id == 3
    assert provider._permit_media_code == "CARD-3"
    assert fetched_base["called"] is True


@pytest.mark.asyncio
async def test_permit_from_response_falls_back_to_fetch_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        fallback_called = {"called": False}

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            fallback_called["called"] = True
            return {
                "ZoneCode": "ZONE-1",
                "PermitMedias": [{"TypeID": 1, "Code": "CARD-1", "ActiveReservations": []}],
                "BlockTimes": [],
            }

        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)
        permit = await provider._permit_from_response({"Result": 1}, "reservation create")

    assert fallback_called["called"] is True
    assert permit["PermitMedias"][0]["Code"] == "CARD-1"


@pytest.mark.asyncio
async def test_extract_permit_treats_empty_permit_as_missing() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        permit = provider._extract_permit(
            {
                "Permit": {},
                "Permits": [
                    {"ZoneCode": "ZONE-1", "PermitMedias": [{"Code": "CARD-1", "TypeID": 1}]}
                ],
            }
        )

    assert permit["ZoneCode"] == "ZONE-1"


@pytest.mark.asyncio
async def test_fetch_app_env_only_marks_success_after_both_bootstrap_steps() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        responses = [
            _FakeResponse(status=404, text_data="missing"),
            _FakeResponse(status=200, text_data="<html></html>"),
        ]

        class _Session:
            def __init__(self, values: list[_FakeResponse]) -> None:
                self.cookie_jar = session.cookie_jar
                self._values = values

            def request(self, method: str, url: str, **kwargs: Any) -> _FakeRequestContext:
                return _FakeRequestContext(self._values.pop(0))

        provider._session = _Session(responses)  # type: ignore[assignment]

        await provider._transport.fetch_app_env()

    assert provider._state.app_env_fetched is False


@pytest.mark.asyncio
async def test_fetch_app_env_marks_success_after_cookie_name_and_html_success() -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        responses = [
            _FakeResponse(
                status=200,
                text_data='window.__env.xsrfCookieName = "XSRF-TOKEN";',
            ),
            _FakeResponse(status=200, text_data="<html></html>"),
        ]

        class _Session:
            def __init__(self, values: list[_FakeResponse]) -> None:
                self.cookie_jar = session.cookie_jar
                self._values = values

            def request(self, method: str, url: str, **kwargs: Any) -> _FakeRequestContext:
                return _FakeRequestContext(self._values.pop(0))

        provider._session = _Session(responses)  # type: ignore[assignment]

        await provider._transport.fetch_app_env()

    assert provider._state.app_env_fetched is True


@pytest.mark.asyncio
async def test_request_json_auth_reauthenticates_once_on_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._session_authenticated = True
        provider._auth_header_value = "Token old-token"
        provider._state.credentials = {
            "username": "user",
            "password": "secret",
            "permit_media_type_id": "1",
        }
        attempts = {"count": 0}
        reauth_calls = {"count": 0}

        async def _fake_request_with_backoff(
            method: str,
            url: str,
            *,
            expect_json: bool,
            json: Any,
            headers: dict[str, str],
            operation: str | None,
        ) -> Any:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise AuthError("Authentication failed.")
            return {"ok": True}

        async def _fake_reauthenticate() -> None:
            reauth_calls["count"] += 1
            provider._auth_header_value = "Token new-token"
            provider._session_authenticated = True

        monkeypatch.setattr(
            provider._transport, "_request_with_backoff", _fake_request_with_backoff
        )
        monkeypatch.setattr(provider._transport, "_reauthenticate", _fake_reauthenticate)

        response = await provider._request_json_auth("POST", RESERVATION_CREATE_ENDPOINT, json={})

    assert response == {"ok": True}
    assert attempts["count"] == 2
    assert reauth_calls["count"] == 1


@pytest.mark.asyncio
async def test_start_reservation_payload_uses_local_offset_with_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"

        async def _noop_defaults(*, operation: str = "ensure_defaults") -> None:
            return None

        monkeypatch.setattr(provider, "_ensure_defaults", _noop_defaults)
        captured: dict[str, Any] = {}

        async def _fake_request_json_auth(
            method: str,
            path: str,
            *,
            json: Any,
            operation: str | None = None,
        ) -> Any:
            captured["method"] = method
            captured["path"] = path
            captured["json"] = json
            return {
                "Permit": {
                    "PermitMedias": [
                        {
                            "TypeID": 1,
                            "Code": "CARD-1",
                            "ActiveReservations": [
                                {
                                    "ReservationID": "123",
                                    "ValidFrom": json["DateFrom"],
                                    "ValidUntil": json["DateUntil"],
                                    "LicensePlate": {
                                        "Value": "AB12CD",
                                        "DisplayValue": "AB-12-CD",
                                    },
                                }
                            ],
                            "LicensePlates": [],
                        }
                    ],
                    "BlockTimes": [],
                }
            }

        monkeypatch.setattr(provider, "_request_json_auth", _fake_request_json_auth)

        reservation = await provider.start_reservation(
            "ab-12 cd",
            datetime(2026, 1, 2, 22, 57, tzinfo=UTC),
            datetime(2026, 1, 2, 23, 57, tzinfo=UTC),
            name="Visitor",
        )

    payload = captured["json"]
    assert payload["permitMediaTypeID"] == 1
    assert payload["permitMediaCode"] == "CARD-1"
    assert payload["DateFrom"] == "2026-01-02T23:57:00.000+01:00"
    assert payload["DateUntil"] == "2026-01-03T00:57:00.000+01:00"
    assert payload["LicensePlate"]["Value"] == "AB12CD"
    assert payload["LicensePlate"]["Name"] == "Visitor"
    assert reservation.id == "123"


@pytest.mark.asyncio
async def test_update_reservation_payload_uses_minute_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"
        existing_permit = {
            "PermitMedias": [
                {
                    "TypeID": 1,
                    "Code": "CARD-1",
                    "ActiveReservations": [
                        {
                            "ReservationID": "123",
                            "ValidFrom": "2026-01-02T09:00:00Z",
                            "ValidUntil": "2026-01-02T10:00:00Z",
                            "LicensePlate": {
                                "Value": "AB12CD",
                                "DisplayValue": "AB-12-CD",
                            },
                        }
                    ],
                    "LicensePlates": [],
                }
            ],
            "BlockTimes": [],
        }
        updated_permit = {
            "PermitMedias": [
                {
                    "TypeID": 1,
                    "Code": "CARD-1",
                    "ActiveReservations": [
                        {
                            "ReservationID": "123",
                            "ValidFrom": "2026-01-02T09:00:00Z",
                            "ValidUntil": "2026-01-02T10:10:00Z",
                            "LicensePlate": {
                                "Value": "AB12CD",
                                "DisplayValue": "AB-12-CD",
                            },
                        }
                    ],
                    "LicensePlates": [],
                }
            ],
            "BlockTimes": [],
        }

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            return existing_permit

        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)
        captured: dict[str, Any] = {}

        async def _fake_request_json_auth(
            method: str,
            path: str,
            *,
            json: Any,
            operation: str | None = None,
        ) -> Any:
            captured["method"] = method
            captured["path"] = path
            captured["json"] = json
            return {"Permit": updated_permit}

        monkeypatch.setattr(provider, "_request_json_auth", _fake_request_json_auth)
        reservation = await provider.update_reservation(
            "123",
            end_time=datetime(2026, 1, 2, 10, 10, tzinfo=UTC),
        )

    payload = captured["json"]
    assert captured["method"] == "POST"
    assert captured["path"] == RESERVATION_UPDATE_ENDPOINT
    assert payload["Minutes"] == 10
    assert payload["ReservationID"] == "123"
    assert payload["permitMediaTypeID"] == 1
    assert payload["permitMediaCode"] == "CARD-1"
    assert reservation == Reservation(
        id="123",
        name="AB-12-CD",
        license_plate="AB12CD",
        start_time="2026-01-02T09:00:00Z",
        end_time="2026-01-02T10:10:00Z",
    )


@pytest.mark.asyncio
async def test_add_and_remove_favorite_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"
        add_captured: dict[str, Any] = {}
        remove_captured: dict[str, Any] = {}
        current_permit: dict[str, Any] = {
            "PermitMedias": [
                {
                    "TypeID": 1,
                    "Code": "CARD-1",
                    "ActiveReservations": [],
                    "LicensePlates": [],
                }
            ],
            "BlockTimes": [],
        }

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            return current_permit

        async def _fake_request_json_auth(
            method: str,
            path: str,
            *,
            json: Any,
            operation: str | None = None,
        ) -> Any:
            if path.endswith("upsert"):
                add_captured["json"] = json
                return {
                    "Permit": {
                        "PermitMedias": [
                            {
                                "TypeID": 1,
                                "Code": "CARD-1",
                                "ActiveReservations": [],
                                "LicensePlates": [{"Value": "AB12CD", "Name": "Visitor"}],
                            }
                        ]
                    }
                }
            remove_captured["json"] = json
            return {}

        monkeypatch.setattr(provider, "_request_json_auth", _fake_request_json_auth)
        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)
        favorite = await provider.add_favorite("ab-12 cd", name="Visitor")
        current_permit = {
            "PermitMedias": [
                {
                    "TypeID": 1,
                    "Code": "CARD-1",
                    "ActiveReservations": [],
                    "LicensePlates": [{"Value": "AB12CD", "Name": "Visitor"}],
                }
            ],
            "BlockTimes": [],
        }
        await provider.remove_favorite("ab-12 cd")

    assert add_captured["json"]["licensePlate"]["Value"] == "AB12CD"
    assert add_captured["json"]["licensePlate"]["Name"] == "Visitor"
    assert add_captured["json"]["name"] == "Visitor"
    assert favorite.id == "AB12CD"
    assert remove_captured["json"]["licensePlate"] == "AB12CD"
    assert remove_captured["json"]["name"] == "Visitor"


@pytest.mark.asyncio
async def test_start_reservation_failure_logs_operation_context_and_masked_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Provider(
        _FailingSession(
            _FakeResponse(
                status=500,
                text_data="Backend reservation failure",
                headers={"Content-Type": "text/plain; charset=utf-8"},
            )
        ),
        _manifest(),
        base_url="https://example",
    )
    provider._session_authenticated = True
    provider._auth_header_value = "Token token-value"
    provider._permit_media_type_id = 1
    provider._permit_media_code = "CARD-1"

    async def _noop_defaults(*, operation: str = "ensure_defaults") -> None:
        return None

    monkeypatch.setattr(provider, "_ensure_defaults", _noop_defaults)
    caplog.set_level(logging.WARNING, logger="pycityvisitorparking.provider")

    with pytest.raises(ProviderError, match="status 500"):
        await provider.start_reservation(
            "ab-12 cd",
            datetime(2026, 1, 2, 22, 57, tzinfo=UTC),
            datetime(2026, 1, 2, 23, 57, tzinfo=UTC),
        )

    assert "operation" in caplog.text
    assert "start_reservation" in caplog.text
    assert f"POST https://example{DEFAULT_API_URI}{RESERVATION_CREATE_ENDPOINT}" in caplog.text
    assert "status" in caplog.text
    assert "500" in caplog.text
    assert "content-type" in caplog.text
    assert "text/plain; charset=utf-8" in caplog.text
    assert "response_kind" in caplog.text
    assert "text" in caplog.text
    assert "Backend reservation failure" in caplog.text
    assert "AB12CD" not in caplog.text
    assert "CARD-1" not in caplog.text
    assert "token-value" not in caplog.text


@pytest.mark.asyncio
async def test_start_reservation_failure_logs_compact_html_summary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Provider(
        _FailingSession(
            _FakeResponse(
                status=500,
                text_data=(
                    "<!DOCTYPE html><html lang='nl'><head><title>Bezoekers App</title>"
                    "<base href='/DVSPortal/' />"
                    "<script>window.marker='GRONINGEN-HTML-MARKER';</script>"
                    "</head><body>Portal</body></html>"
                ),
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
        ),
        _manifest(),
        base_url="https://example",
    )
    provider._session_authenticated = True
    provider._auth_header_value = "Token token-value"
    provider._permit_media_type_id = 1
    provider._permit_media_code = "CARD-1"

    async def _noop_defaults(*, operation: str = "ensure_defaults") -> None:
        return None

    monkeypatch.setattr(provider, "_ensure_defaults", _noop_defaults)
    caplog.set_level(logging.WARNING, logger="pycityvisitorparking.provider")

    with pytest.raises(ProviderError, match="status 500"):
        await provider.start_reservation(
            "ab-12 cd",
            datetime(2026, 1, 2, 22, 57, tzinfo=UTC),
            datetime(2026, 1, 2, 23, 57, tzinfo=UTC),
        )

    assert "response_kind" in caplog.text
    assert "html" in caplog.text
    assert "html_title" in caplog.text
    assert "Bezoekers App" in caplog.text
    assert "html_base_href" in caplog.text
    assert "/DVSPortal/" in caplog.text
    assert "GRONINGEN-HTML-MARKER" not in caplog.text
    assert "body_excerpt" not in caplog.text


@pytest.mark.asyncio
async def test_fetch_app_env_does_not_set_flag_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """app_env_fetched must stay False when either bootstrap step raises."""

    class _ErrorContext:
        async def __aenter__(self) -> _ErrorContext:
            raise aiohttp.ClientError("network error")

        async def __aexit__(self, *_: object) -> bool:
            return False

    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")

        monkeypatch.setattr(session, "request", lambda *a, **kw: _ErrorContext())
        await provider._transport.fetch_app_env()

    assert not provider._transport._state.app_env_fetched


@pytest.mark.asyncio
async def test_fetch_app_env_sets_flag_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """app_env_fetched must be True only after both bootstrap steps succeed."""

    class _OkContext:
        def __init__(self, status: int, text: str) -> None:
            self.status = status
            self._text = text
            self.headers: dict[str, str] = {}

        async def __aenter__(self) -> _OkContext:
            return self

        async def __aexit__(self, *_: object) -> bool:
            return False

        async def text(self) -> str:
            return self._text

        async def read(self) -> bytes:
            return self._text.encode()

    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")

        def _ok_request(method: str, url: str, **kwargs: Any) -> _OkContext:
            return _OkContext(status=200, text="window.__env.xsrfCookieName = 'XSRF-TOKEN';")

        monkeypatch.setattr(session, "request", _ok_request)
        await provider._transport.fetch_app_env()

    assert provider._transport._state.app_env_fetched


@pytest.mark.asyncio
async def test_fetch_all_uses_single_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(session, _manifest(), base_url="https://example")
        fetch_base_calls = {"count": 0}

        async def _fake_fetch_base(
            *, operation: str = "fetch_base", allow_reauth: bool = True
        ) -> dict[str, Any]:
            fetch_base_calls["count"] += 1
            return PERMIT_SAMPLE

        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)

        permit, reservations, favorites = await provider.fetch_all()

    assert fetch_base_calls["count"] == 1
    assert permit.id == "CARD-1"
    assert permit.remaining_balance == 120
    assert len(reservations) == 1
    assert reservations[0].id == "123"
    assert len(favorites) == 1
    assert favorites[0].id == "XY99ZZ"
