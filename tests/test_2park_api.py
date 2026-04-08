from __future__ import annotations

# Import via importlib since "2park" is not a valid Python identifier
import importlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from pycityvisitorparking.exceptions import AuthError, ProviderError, ValidationError
from pycityvisitorparking.provider.loader import ProviderManifest

_mod = importlib.import_module("pycityvisitorparking.provider.2park.api")
Provider = _mod.Provider


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        json_data: object | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.status = status
        self._json_data = json_data
        self._json_error = json_error

    async def json(self, *, content_type: str | None = None) -> object:
        if self._json_error is not None:
            raise self._json_error
        return self._json_data

    async def text(self) -> str:
        return ""


class _FakeRequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _SequenceSession:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs) -> _FakeRequestContext:
        self.requests.append({"method": method, "url": url, "kwargs": kwargs})
        self.calls += 1
        response = self._responses[self.calls - 1]
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, _FakeResponse)
        return _FakeRequestContext(response)


def _manifest() -> ProviderManifest:
    return ProviderManifest(
        id="2park",
        name="2park",
        favorite_update_fields=(),
        reservation_update_fields=("end_time",),
    )


def _provider(session: object) -> Provider:
    return Provider(
        session,  # type: ignore[arg-type]
        _manifest(),
        base_url="https://mijn.2park.nl",
    )


_AUTH_OK = {"status": {"code": {"major": "OK"}}}
_AUTH_FAIL = {"status": {"code": {"major": "ERROR"}, "message": "Invalid credentials"}}
_CATEGORIES = {
    "data": {
        "categories": [
            {
                "cty_products": [
                    {
                        "pdt_id": "BDABZRG_1317$abc",
                        "pdt_name": "Breda Bezoekersregeling",
                        "pdt_is_blocked": False,
                        "pdt_parameter_groups": [
                            {
                                "pgp_label": "START",
                                "pgp_parameters": [
                                    {"prr_label": "LOCATION", "prr_value": "BDA1317"},
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }
}
_BALANCE = {
    "data": {
        "balance": {
            "ble_parameters": [
                {"prr_label": "AMOUNT", "prr_value": "120"},
                {"prr_label": "CURRENCY_CODE", "prr_value": "MINUTE"},
            ]
        }
    }
}
_PRODUCT_DETAILS_EMPTY = {"data": {"pdt_members": []}}
_PRODUCT_DETAILS_WITH_MEMBERS = {
    "data": {
        "pdt_members": [
            {
                "mbr_id": "42",
                "mbr_identifier": "AB1234",
                "mbr_type": "LPN",
                "mbr_active": True,
                "mbr_parameters": [{"prr_label": "NICKNAME", "prr_value": "Visitor"}],
                "mbr_actions": [
                    {
                        "atn_id": "99",
                        "atn_parameters": [
                            {"prr_label": "MBR_IDENT", "prr_value": "AB1234"},
                            {"prr_label": "TIMESTART", "prr_value": "25-03-2026 10:00:00"},
                            {"prr_label": "TIMEEND", "prr_value": "25-03-2026 12:00:00"},
                            {"prr_label": "LOCATION", "prr_value": "BDA1317"},
                        ],
                    }
                ],
            }
        ]
    }
}
_START_ACTION_OK = {
    "status": {"code": {"major": "OK"}},
    "data": {
        "atn_id": "101",
        "atn_parameters": [
            {"prr_label": "MBR_IDENT", "prr_value": "AB1234"},
            {"prr_label": "TIMESTART", "prr_value": "25-03-2026 10:00:00"},
            {"prr_label": "TIMEEND", "prr_value": "25-03-2026 12:00:00"},
            {"prr_label": "LOCATION", "prr_value": "BDA1317"},
        ],
    },
}
_STOP_ACTION_OK = {"status": {"code": {"major": "OK"}}, "data": {}}
_EXTEND_ACTION_OK = {"status": {"code": {"major": "OK"}}, "data": {}}
_HANDLE_FAVORITE_OK = {"status": {"code": {"major": "OK"}}}


async def _logged_in_provider(responses: list[object]) -> tuple[Provider, _SequenceSession]:
    session = _SequenceSession(responses)
    provider = _provider(session)
    await provider.login(credentials={"username": "u@e.com", "password": "p"})
    return provider, session


# --- login ---


async def test_login_success() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
        ]
    )
    assert provider._product_id == "BDABZRG_1317$abc"
    assert provider._product_location == "BDA1317"


async def test_login_bad_credentials() -> None:
    session = _SequenceSession([_FakeResponse(json_data=_AUTH_FAIL)])
    provider = _provider(session)
    with pytest.raises(AuthError):
        await provider.login(credentials={"username": "u@e.com", "password": "wrong"})


async def test_login_missing_username() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError, match="username"):
        await provider.login(credentials={"password": "secret"})


async def test_login_missing_password() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError, match="password"):
        await provider.login(credentials={"username": "u@e.com"})


async def test_login_explicit_product_id_and_location() -> None:
    session = _SequenceSession([_FakeResponse(json_data=_AUTH_OK)])
    provider = _provider(session)
    await provider.login(
        credentials={
            "username": "u@e.com",
            "password": "p",
            "product_id": "BDABZRG_1317$abc",
            "location": "BDA1317",
        }
    )
    assert provider._product_id == "BDABZRG_1317$abc"
    assert provider._product_location == "BDA1317"
    assert session.calls == 1  # no categories call when both are provided


async def test_login_no_products_raises() -> None:
    no_products = {"data": {"categories": []}}
    session = _SequenceSession(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=no_products),
        ]
    )
    provider = _provider(session)
    with pytest.raises(ProviderError, match="No suitable"):
        await provider.login(credentials={"username": "u@e.com", "password": "p"})


async def test_login_auth_required_when_unauthenticated() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(AuthError, match="required"):
        await provider.get_permit()


# --- get_permit ---


async def test_get_permit_returns_balance() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_BALANCE),
        ]
    )
    permit = await provider.get_permit()
    assert permit.id == "BDABZRG_1317$abc"
    assert permit.remaining_balance == 120
    assert permit.zone_validity == []
    assert permit.balance_unit == "MINUTE"


# --- list_reservations ---


async def test_list_reservations_empty() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_EMPTY),
        ]
    )
    assert await provider.list_reservations() == []


async def test_list_reservations_maps_active_action() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
        ]
    )
    reservations = await provider.list_reservations()
    assert len(reservations) == 1
    r = reservations[0]
    assert r.id == "99"
    assert r.license_plate == "AB1234"
    assert r.start_time == "2026-03-25T09:00:00Z"
    assert r.end_time == "2026-03-25T11:00:00Z"


# --- start_reservation ---


async def test_start_reservation_returns_action() -> None:
    provider, session = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_START_ACTION_OK),
        ]
    )
    start = datetime(2026, 3, 25, 9, 0, tzinfo=UTC)
    end = datetime(2026, 3, 25, 11, 0, tzinfo=UTC)
    reservation = await provider.start_reservation("AB1234", start, end)
    assert reservation.id == "101"
    assert reservation.license_plate == "AB1234"

    # Verify form payload sent to API
    req = session.requests[-1]
    data = req["kwargs"]["data"]
    assert data["product_id"] == "BDABZRG_1317$abc"
    assert data["locale"] == "nl_NL"
    action = json.loads(data["data"])
    params = {p["prr_label"]: p["prr_value"] for p in action["action"]["atn_parameters"]}
    assert params["MBR_IDENT"] == "AB1234"
    assert params["TIMESTART"] == "25-03-2026 10:00:00"
    assert params["TIMEEND"] == "25-03-2026 12:00:00"
    assert params["LOCATION"] == "BDA1317"


async def test_start_reservation_no_location_raises() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
        ]
    )
    provider._product_location = None
    start = datetime(2026, 3, 25, 9, 0, tzinfo=UTC)
    end = datetime(2026, 3, 25, 11, 0, tzinfo=UTC)
    with pytest.raises(ProviderError, match="location"):
        await provider.start_reservation("AB1234", start, end)


async def test_start_reservation_api_error_raises() -> None:
    fail = {"status": {"code": {"major": "ERROR"}, "message": "plate not found"}, "data": {}}
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=fail),
        ]
    )
    start = datetime(2026, 3, 25, 9, 0, tzinfo=UTC)
    end = datetime(2026, 3, 25, 11, 0, tzinfo=UTC)
    with pytest.raises(ProviderError, match="plate not found"):
        await provider.start_reservation("AB1234", start, end)


# --- update_reservation ---


async def test_update_reservation_extends_end_time() -> None:
    provider, session = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),  # list_reservations
            _FakeResponse(json_data=_EXTEND_ACTION_OK),
        ]
    )
    new_end = datetime(2026, 3, 25, 13, 0, tzinfo=UTC)
    reservation = await provider.update_reservation("99", end_time=new_end)
    assert reservation.id == "99"
    assert reservation.end_time == "2026-03-25T13:00:00Z"
    assert reservation.start_time == "2026-03-25T09:00:00Z"

    req = session.requests[-1]
    data = req["kwargs"]["data"]
    assert data["action_id"] == "99"
    assert data["product_id"] == "BDABZRG_1317$abc"
    assert data["VALID_UNTIL"] == "25-03-2026 14:00:00"  # UTC+1 in winter


async def test_update_reservation_rejects_start_time_change() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError, match="Only end_time"):
        await provider.update_reservation(
            "99",
            start_time=datetime(2026, 3, 25, 9, 0, tzinfo=UTC),
            end_time=datetime(2026, 3, 25, 13, 0, tzinfo=UTC),
        )


async def test_update_reservation_requires_end_time() -> None:
    provider = _provider(_SequenceSession([]))
    with pytest.raises(ValidationError, match="end_time"):
        await provider.update_reservation("99")


async def test_update_reservation_not_found_raises() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_EMPTY),
        ]
    )
    with pytest.raises(ValidationError, match="not found"):
        await provider.update_reservation("99", end_time=datetime(2026, 3, 25, 13, 0, tzinfo=UTC))


async def test_update_reservation_api_error_raises() -> None:
    fail = {"status": {"code": {"major": "ERROR"}, "message": "balance exceeded"}, "data": {}}
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
            _FakeResponse(json_data=fail),
        ]
    )
    with pytest.raises(ProviderError, match="balance exceeded"):
        await provider.update_reservation("99", end_time=datetime(2026, 3, 25, 13, 0, tzinfo=UTC))


# --- end_reservation ---


async def test_end_reservation_calls_stop_action() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
            _FakeResponse(json_data=_STOP_ACTION_OK),
        ]
    )
    end = datetime(2026, 3, 25, 11, 0, tzinfo=UTC)
    reservation = await provider.end_reservation("99", end)
    assert reservation.id == "99"
    assert reservation.end_time == "2026-03-25T11:00:00Z"


async def test_end_reservation_not_found_raises() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_EMPTY),
        ]
    )
    with pytest.raises(ValidationError, match="not found"):
        await provider.end_reservation("99", datetime(2026, 3, 25, 11, 0, tzinfo=UTC))


async def test_end_reservation_api_error_raises() -> None:
    fail = {"status": {"code": {"major": "ERROR"}, "message": "session gone"}, "data": {}}
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
            _FakeResponse(json_data=fail),
        ]
    )
    with pytest.raises(ProviderError, match="session gone"):
        await provider.end_reservation("99", datetime(2026, 3, 25, 11, 0, tzinfo=UTC))


# --- favorites ---


async def test_list_favorites_returns_lpn_members() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
        ]
    )
    favorites = await provider.list_favorites()
    assert len(favorites) == 1
    assert favorites[0].id == "42"
    assert favorites[0].license_plate == "AB1234"
    assert favorites[0].name == "Visitor"


async def test_add_favorite_returns_favorite() -> None:
    provider, session = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_EMPTY),  # list_favorites duplicate check
            _FakeResponse(json_data=_HANDLE_FAVORITE_OK),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),  # list_favorites after add
        ]
    )
    favorite = await provider.add_favorite("AB1234", name="Visitor")
    assert favorite.license_plate == "AB1234"
    assert favorite.name == "Visitor"

    req = session.requests[-2]  # handle_favorite call
    data = req["kwargs"]["data"]
    payload = json.loads(data["data"])
    assert payload["favorite"]["action"] == "add"
    assert payload["favorite"]["mbr_ident"] == "AB1234"
    assert payload["favorite"]["fav_parameters"][0]["prr_value"] == "Visitor"


async def test_add_favorite_duplicate_raises() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
        ]
    )
    with pytest.raises(ValidationError, match="already a favorite"):
        await provider.add_favorite("AB1234")


async def test_add_favorite_api_error_raises() -> None:
    fail = {"status": {"code": {"major": "ERROR"}, "message": "plate invalid"}}
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_EMPTY),  # no existing favorites
            _FakeResponse(json_data=fail),
        ]
    )
    with pytest.raises(ProviderError, match="plate invalid"):
        await provider.add_favorite("AB1234")


async def test_remove_favorite_calls_handle_favorite() -> None:
    provider, session = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),  # list_favorites
            _FakeResponse(json_data=_HANDLE_FAVORITE_OK),
        ]
    )
    await provider.remove_favorite("42")

    req = session.requests[-1]
    data = req["kwargs"]["data"]
    payload = json.loads(data["data"])
    assert payload["favorite"]["action"] == "remove"
    assert payload["favorite"]["mbr_ident"] == "AB1234"
    assert payload["favorite"]["fav_parameters"][0]["prr_value"] == "Visitor"


async def test_remove_favorite_not_found_raises() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_EMPTY),
        ]
    )
    with pytest.raises(ValidationError, match="not found"):
        await provider.remove_favorite("99")


async def test_remove_favorite_api_error_raises() -> None:
    fail = {"status": {"code": {"major": "ERROR"}, "message": "session gone"}}
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(json_data=_PRODUCT_DETAILS_WITH_MEMBERS),
            _FakeResponse(json_data=fail),
        ]
    )
    with pytest.raises(ProviderError, match="session gone"):
        await provider.remove_favorite("42")


# --- HTTP error handling ---


async def test_http_401_triggers_reauth_and_retries() -> None:
    # Reauth reuses cached product_id+location from credentials so no CATEGORIES call.
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),  # initial auth
            _FakeResponse(json_data=_CATEGORIES),  # initial detect_product
            _FakeResponse(status=401),  # get_permit attempt 0 → triggers reauth
            _FakeResponse(json_data=_AUTH_OK),  # reauth auth (product_id already cached)
            _FakeResponse(json_data=_BALANCE),  # get_permit attempt 1 → success
        ]
    )
    permit = await provider.get_permit()
    assert permit.remaining_balance == 120


async def test_http_500_raises_provider_error() -> None:
    provider, _ = await _logged_in_provider(
        [
            _FakeResponse(json_data=_AUTH_OK),
            _FakeResponse(json_data=_CATEGORIES),
            _FakeResponse(status=500),
        ]
    )
    with pytest.raises(ProviderError):
        await provider.get_permit()


# --- mapping unit tests ---
# (kept here because "2park" is not a valid Python identifier so pytest cannot
# traverse src/pycityvisitorparking/provider/2park/ for test collection)

_extract_location = _mod._extract_location
_parse_balance_amount = _mod._parse_balance_amount
_extract_nickname = _mod._extract_nickname


def _bare_provider() -> Provider:
    class _StubSession:
        def request(self, *a, **kw):  # type: ignore[override]
            raise RuntimeError("should not make requests in mapping tests")

    return Provider(
        _StubSession(),  # type: ignore[arg-type]
        _manifest(),
        base_url="https://mijn.2park.nl",
    )


def test_parse_provider_timestamp_winter_to_utc() -> None:
    p = _bare_provider()
    assert p._parse_provider_timestamp("25-03-2026 10:00:00") == "2026-03-25T09:00:00Z"


def test_parse_provider_timestamp_summer_to_utc() -> None:
    p = _bare_provider()
    assert p._parse_provider_timestamp("01-07-2026 12:00:00") == "2026-07-01T10:00:00Z"


def test_parse_provider_timestamp_dst_ambiguity_uses_fold_zero() -> None:
    p = _bare_provider()
    # 02:30 CET/CEST ambiguous at fall-back; fold=0 → CEST (UTC+2) → 00:30Z
    assert p._parse_provider_timestamp("27-10-2024 02:30:00") == "2024-10-27T00:30:00Z"


def test_parse_provider_timestamp_invalid_raises() -> None:
    p = _bare_provider()
    with pytest.raises(ValidationError):
        p._parse_provider_timestamp("not-a-date")


def test_format_provider_timestamp_utc_to_local_winter() -> None:
    p = _bare_provider()
    assert (
        p._format_provider_timestamp(datetime(2026, 3, 25, 9, 0, tzinfo=UTC))
        == "25-03-2026 10:00:00"
    )


def test_format_provider_timestamp_utc_to_local_summer() -> None:
    p = _bare_provider()
    assert (
        p._format_provider_timestamp(datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
        == "01-07-2026 12:00:00"
    )


def test_format_provider_timestamp_naive_raises() -> None:
    p = _bare_provider()
    with pytest.raises(ValidationError):
        p._format_provider_timestamp(datetime(2026, 3, 25, 10, 0))


def test_map_permit_extracts_amount() -> None:
    p = _bare_provider()
    p._product_id = "BDABZRG_1317$abc"
    data = {"data": {"balance": {"ble_parameters": [{"prr_label": "AMOUNT", "prr_value": "240"}]}}}
    permit = p._map_permit(data)
    assert permit.id == "BDABZRG_1317$abc"
    assert permit.remaining_balance == 240
    assert permit.zone_validity == []
    assert permit.balance_unit is None


def test_map_permit_times_balance() -> None:
    p = _bare_provider()
    p._product_id = "BDABZRG_1317$abc"
    data = {
        "data": {
            "balance": {
                "ble_parameters": [
                    {"prr_label": "AMOUNT", "prr_value": "5"},
                    {"prr_label": "CURRENCY_CODE", "prr_value": "TIMES"},
                ]
            }
        }
    }
    permit = p._map_permit(data)
    assert permit.remaining_balance == 5
    assert permit.balance_unit == "TIMES"


def test_map_permit_euro_balance_preserves_precision() -> None:
    p = _bare_provider()
    p._product_id = "BDABZRG_1317$abc"
    data = {
        "data": {
            "balance": {
                "ble_parameters": [
                    {"prr_label": "AMOUNT", "prr_value": "12.50"},
                    {"prr_label": "CURRENCY_CODE", "prr_value": "EURO"},
                ]
            }
        }
    }
    permit = p._map_permit(data)
    assert permit.remaining_balance == 12.5
    assert permit.balance_unit == "EURO"


def test_map_reservation_list_skips_non_lpn() -> None:
    p = _bare_provider()
    details = {
        "data": {
            "pdt_members": [
                {"mbr_type": "FLPN", "mbr_identifier": "AB1234", "mbr_actions": [{"atn_id": "1"}]}
            ]
        }
    }
    assert p._map_reservation_list(details) == []


def test_map_reservation_list_happy_path() -> None:
    p = _bare_provider()
    details = {
        "data": {
            "pdt_members": [
                {
                    "mbr_type": "LPN",
                    "mbr_identifier": "AB1234",
                    "mbr_actions": [
                        {
                            "atn_id": "99",
                            "atn_parameters": [
                                {"prr_label": "MBR_IDENT", "prr_value": "AB1234"},
                                {"prr_label": "TIMESTART", "prr_value": "25-03-2026 10:00:00"},
                                {"prr_label": "TIMEEND", "prr_value": "25-03-2026 12:00:00"},
                            ],
                        }
                    ],
                }
            ]
        }
    }
    reservations = p._map_reservation_list(details)
    assert len(reservations) == 1
    assert reservations[0].id == "99"
    assert reservations[0].start_time == "2026-03-25T09:00:00Z"
    assert reservations[0].end_time == "2026-03-25T11:00:00Z"


def test_map_favorite_list_uses_nickname() -> None:
    p = _bare_provider()
    details = {
        "data": {
            "pdt_members": [
                {
                    "mbr_type": "LPN",
                    "mbr_id": "42",
                    "mbr_identifier": "AB1234",
                    "mbr_parameters": [{"prr_label": "NICKNAME", "prr_value": "Family car"}],
                }
            ]
        }
    }
    favorites = p._map_favorite_list(details)
    assert len(favorites) == 1
    assert favorites[0].name == "Family car"
    assert favorites[0].license_plate == "AB1234"


def test_extract_location_from_start_group() -> None:
    product = {
        "pdt_id": "BDABZRG_1317$abc",
        "pdt_parameter_groups": [
            {
                "pgp_label": "START",
                "pgp_parameters": [
                    {
                        "prr_label": "LOCATION",
                        "prr_value": "BDA1317",
                        "prr_default_value": "DEFAULT",
                        "prr_options": "OPTIONAL|READONLY",
                    }
                ],
            }
        ],
    }
    assert _extract_location(product) == "BDA1317"


def test_extract_location_skips_non_start_group() -> None:
    product = {
        "pdt_id": "BDABZRG_1317$abc",
        "pdt_parameter_groups": [
            {
                "pgp_label": "GRANT",
                "pgp_parameters": [{"prr_label": "LOCATION", "prr_value": "WRONG"}],
            },
            {
                "pgp_label": "START",
                "pgp_parameters": [{"prr_label": "LOCATION", "prr_value": "BDA1317"}],
            },
        ],
    }
    assert _extract_location(product) == "BDA1317"


def test_extract_location_fallback_regex() -> None:
    assert (
        _extract_location({"pdt_id": "TELBZRG_9001$xyz", "pdt_parameter_groups": []}) == "TEL9001"
    )


def test_extract_location_no_match() -> None:
    assert _extract_location({"pdt_id": "unknown", "pdt_parameter_groups": []}) is None


def test_parse_balance_amount_float_preserves_precision() -> None:
    balance = {"ble_parameters": [{"prr_label": "AMOUNT", "prr_value": "120.9"}]}
    assert _parse_balance_amount(balance) == 120.9


def test_parse_balance_amount_invalid_returns_zero() -> None:
    balance = {"ble_parameters": [{"prr_label": "AMOUNT", "prr_value": "n/a"}]}
    assert _parse_balance_amount(balance) == 0


def test_extract_nickname_returns_value() -> None:
    member = {"mbr_parameters": [{"prr_label": "NICKNAME", "prr_value": "Family car"}]}
    assert _extract_nickname(member) == "Family car"


def test_extract_nickname_returns_none_when_absent() -> None:
    assert _extract_nickname({"mbr_parameters": []}) is None
