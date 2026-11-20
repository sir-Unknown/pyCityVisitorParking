from datetime import UTC, date, datetime, time

import aiohttp
import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import (
    BALANCE_UNIT_EURO,
    BALANCE_UNIT_MINUTE,
    Favorite,
    PaidHoursBlock,
    Permit,
    Reservation,
)
from pycityvisitorparking.provider.amsterdam import api as amsterdam_api
from pycityvisitorparking.provider.amsterdam.api import Provider
from pycityvisitorparking.provider.amsterdam.const import DEFAULT_API_URI
from pycityvisitorparking.provider.loader import ProviderManifest
from pycityvisitorparking.util import format_utc_timestamp, parse_timestamp

# Frozen clock for start_reservation tests; the requested starts lie after it.
NOW = datetime(2026, 1, 24, 0, 0, tzinfo=UTC)

ACCOUNT_SAMPLE = {
    "client_product_id": 42,
    "ssp": {
        "main_account": {
            "time_balance": 7230,
        }
    },
}

RESERVATION_SAMPLE = {
    "parking_session_id": 123,
    "permit_name": "Visitor",
    "vrn": "ab-12 cd",
    "started_at": "2024-06-01T10:00:00+02:00",
    "ended_at": "2024-06-01T11:00:00+02:00",
}

FAVORITE_SAMPLE = {
    "favorite_vrn_id": 5,
    "vrn": "xy-99-zz",
    "description": "Family",
}


def assert_utc_timestamp(value: str) -> None:
    parsed = parse_timestamp(value)
    assert parsed.tzinfo == UTC
    assert format_utc_timestamp(parsed) == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("main_account", "expected_balance", "expected_unit"),
    [
        ({"time_balance": 7230}, 120, BALANCE_UNIT_MINUTE),
        ({"time_balance": 0, "money_balance": 500}, 0, BALANCE_UNIT_MINUTE),
        ({"time_balance": None, "money_balance": 1250}, 12.5, BALANCE_UNIT_EURO),
        ({}, 0, None),
    ],
)
async def test_map_permit_balance_uses_portal_units(
    main_account: dict[str, object], expected_balance: float, expected_unit: str | None
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(
            {"client_product_id": 42, "ssp": {"main_account": main_account}},
            client_product_id="42",
            paid_hours=[],
        )

    assert isinstance(permit, Permit)
    assert permit.id == "42"
    assert permit.remaining_balance == expected_balance
    assert permit.balance_unit == expected_unit


@pytest.mark.asyncio
async def test_map_reservation_normalizes_plate_and_time():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        reservation = provider._map_reservation(RESERVATION_SAMPLE)

    assert isinstance(reservation, Reservation)
    assert reservation.id == "123"
    assert reservation.license_plate == "AB12CD"
    assert reservation.start_time == "2024-06-01T08:00:00Z"
    assert reservation.end_time == "2024-06-01T09:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_map_favorite_normalizes_plate():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        favorite = provider._map_favorite(FAVORITE_SAMPLE)

    assert isinstance(favorite, Favorite)
    assert favorite.id == "5"
    assert favorite.license_plate == "XY99ZZ"
    assert favorite.name == "Family"


@pytest.mark.asyncio
async def test_parse_provider_timestamp_assumes_local_time():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        timestamp = provider._parse_provider_timestamp("2024-01-01T10:00:00")

    assert timestamp == "2024-01-01T09:00:00Z"
    assert_utc_timestamp(timestamp)


@pytest.mark.asyncio
async def test_start_reservation_rejects_naive_datetime():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._client_product_id = "1"
        provider._auth_header_value = "Bearer token"
        provider._logged_in = True

        with pytest.raises(ValidationError):
            await provider.start_reservation(
                "ab-12-cd",
                start_time=datetime(2024, 1, 1, 10, 0),
                end_time=datetime(2024, 1, 1, 11, 0, tzinfo=UTC),
            )


@pytest.mark.asyncio
async def test_extract_client_product_id_handles_alternate_shapes():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

    assert provider._extract_client_product_id({"clientProductId": "99"}) == "99"
    assert provider._extract_client_product_id({"client_product_ids": [123]}) == "123"
    assert provider._extract_client_product_id({"client_products": [{"id": "42"}]}) == "42"


@pytest.mark.asyncio
async def test_extract_client_product_id_from_product_list():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

    data = {"data": [{"type": "client_product", "id": 55}]}
    assert provider._extract_client_product_id_from_product_list(data) == "55"


@pytest.mark.asyncio
async def test_extract_client_product_id_from_permit_list():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

    data = {"permit": [{"permit_id": 77}]}
    assert provider._extract_client_product_id_from_permit_list(data) == "77"


def test_default_api_uri():
    assert DEFAULT_API_URI == "/api"


@pytest.mark.asyncio
async def test_paid_hours_repeat_the_weekly_schedule_from_one_calculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monday = date(2026, 1, 19)
    time_frame_data = [[] for _ in range(7)]
    time_frame_data[monday.weekday()] = [{"startTime": "0900", "endTime": "1900"}]
    calls: list[object] = []

    async def fake_request_json(
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: object | None = None,
        allow_reauth: bool,
        auth_required: bool,
    ) -> object:
        assert method == "POST"
        calls.append(json)
        return {"time_frame_data": time_frame_data}

    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._client_product_id = "123"
        provider._auth_header_value = "Bearer token"
        provider._logged_in = True
        provider._parking_context_loaded = True
        provider._can_select_zone = True
        provider._machine_number = 18773
        monkeypatch.setattr(provider, "_request_json", fake_request_json)
        monkeypatch.setattr(
            provider,
            "_now",
            lambda: datetime.combine(monday, time(12), tzinfo=amsterdam_api._LOCAL_TZ),
        )

        blocks = await provider._build_paid_zone_validity(days=7)

    assert len(calls) == 1
    assert isinstance(calls[0], dict)
    assert calls[0]["machine_number"] == 18773
    expected = []
    for day in (monday, date(2026, 1, 26)):
        start = datetime.combine(day, time(9, 0), tzinfo=amsterdam_api._LOCAL_TZ)
        end = datetime.combine(day, time(19, 0), tzinfo=amsterdam_api._LOCAL_TZ)
        expected.append(
            PaidHoursBlock(
                start_time=format_utc_timestamp(start.astimezone(UTC)),
                end_time=format_utc_timestamp(end.astimezone(UTC)),
            )
        )
    assert blocks == expected


@pytest.mark.asyncio
async def test_start_reservation_includes_machine_number(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_request_json(
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: object | None = None,
        allow_reauth: bool,
        auth_required: bool,
    ) -> object:
        captured["json"] = json
        return {
            "parking_session_id": 1,
            "vrn": "AB12CD",
            "started_at": "2026-01-24T01:00:00+00:00",
            "ended_at": "2026-01-24T02:00:00+00:00",
        }

    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._client_product_id = "123"
        provider._auth_header_value = "Bearer token"
        provider._logged_in = True
        provider._parking_context_loaded = True
        provider._can_select_zone = True
        provider._machine_number = 18773
        monkeypatch.setattr(provider, "_request_json", fake_request_json)
        monkeypatch.setattr(provider, "_now", lambda: NOW)

        await provider.start_reservation(
            "ab-12-cd",
            start_time=datetime(2026, 1, 24, 1, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 24, 2, 0, tzinfo=UTC),
        )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["machine_number"] == 18773


@pytest.mark.asyncio
async def test_start_reservation_start_now_uses_the_current_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_request_json(
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: object | None = None,
        allow_reauth: bool,
        auth_required: bool,
    ) -> object:
        captured["json"] = json
        return {
            "parking_session_id": 1,
            "vrn": "AB12CD",
            "started_at": "2026-01-24T00:00:00+00:00",
            "ended_at": "2026-01-24T02:00:00+00:00",
        }

    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._client_product_id = "123"
        provider._auth_header_value = "Bearer token"
        provider._logged_in = True
        provider._parking_context_loaded = True
        provider._can_select_zone = True
        provider._machine_number = 18773
        monkeypatch.setattr(provider, "_request_json", fake_request_json)
        monkeypatch.setattr(provider, "_now", lambda: NOW)

        await provider.start_reservation(
            "ab-12-cd",
            start_time=datetime(2026, 1, 23, 23, 0, tzinfo=UTC),
            end_time=datetime(2026, 1, 24, 2, 0, tzinfo=UTC),
        )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["started_at"] == provider._format_rfc1123(NOW)


@pytest.mark.asyncio
async def test_start_reservation_without_target_requires_a_default_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request_json(*args: object, **kwargs: object) -> object:
        raise AssertionError("start_reservation should fail before calling the API")

    async def fake_ensure_context() -> None:
        return None

    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="amsterdam",
                name="Amsterdam",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._client_product_id = "123"
        provider._auth_header_value = "Bearer token"
        provider._logged_in = True
        provider._can_select_zone = True
        provider._machine_number = None
        monkeypatch.setattr(provider, "_request_json", fake_request_json)
        monkeypatch.setattr(provider, "_ensure_parking_context", fake_ensure_context)
        monkeypatch.setattr(provider, "_now", lambda: NOW)

        with pytest.raises(ValidationError):
            await provider.start_reservation(
                "ab-12-cd",
                start_time=datetime(2026, 1, 24, 1, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 24, 2, 0, tzinfo=UTC),
            )
