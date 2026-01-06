from datetime import UTC, datetime
from typing import Any

import aiohttp
import pytest

from pycityvisitorparking.exceptions import ValidationError
from pycityvisitorparking.models import Favorite, Reservation, ZoneValidityBlock
from pycityvisitorparking.provider.dvsportal.api import Provider
from pycityvisitorparking.provider.dvsportal.const import (
    DEFAULT_API_URI,
    LOGIN_ENDPOINT,
    RESERVATION_UPDATE_ENDPOINT,
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
            "LicensePlates": [
                {"Value": "xy-99-zz", "Name": "Family"},
            ],
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


def assert_utc_timestamp(value: str) -> None:
    parsed = parse_timestamp(value)
    assert parsed.tzinfo == UTC
    assert format_utc_timestamp(parsed) == value


@pytest.mark.asyncio
async def test_map_permit_filters_free_blocks_and_converts_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
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
async def test_map_reservations_normalizes_plate_and_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit_media = PERMIT_SAMPLE["PermitMedias"][0]
        reservations = provider._map_reservations(permit_media)

    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.id == "123"
    assert reservation.name == "AB-12-CD"
    assert reservation.license_plate == "AB12CD"
    assert reservation.start_time == "2024-01-01T09:00:00Z"
    assert reservation.end_time == "2024-01-01T10:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_map_permit_converts_naive_local_to_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit = provider._map_permit(PERMIT_SAMPLE_NAIVE)

    assert permit.zone_validity == [
        ZoneValidityBlock(
            start_time="2024-07-01T07:00:00Z",
            end_time="2024-07-01T16:00:00Z",
        )
    ]
    for block in permit.zone_validity:
        assert_utc_timestamp(block.start_time)
        assert_utc_timestamp(block.end_time)


@pytest.mark.asyncio
async def test_map_reservations_converts_naive_local_to_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit_media = PERMIT_SAMPLE_NAIVE["PermitMedias"][0]
        reservations = provider._map_reservations(permit_media)

    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation.start_time == "2024-07-01T08:00:00Z"
    assert reservation.end_time == "2024-07-01T09:00:00Z"
    assert_utc_timestamp(reservation.start_time)
    assert_utc_timestamp(reservation.end_time)


@pytest.mark.asyncio
async def test_format_provider_timestamp_converts_utc_to_local():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        formatted = provider._format_provider_timestamp(datetime(2026, 1, 2, 22, 57, tzinfo=UTC))

    assert formatted == "2026-01-02T23:57:00.000+01:00"


@pytest.mark.asyncio
async def test_parse_provider_timestamp_uses_fold_zero_for_ambiguous_time():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        parsed = provider._parse_provider_timestamp("2024-10-27T02:30:00")

    assert parsed == "2024-10-27T00:30:00Z"


@pytest.mark.asyncio
async def test_parse_provider_timestamp_uses_fold_zero_for_nonexistent_time():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        parsed = provider._parse_provider_timestamp("2024-03-31T02:30:00")

    assert parsed == "2024-03-31T01:30:00Z"


@pytest.mark.asyncio
async def test_parse_provider_timestamp_with_offset_is_converted_to_utc():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        parsed = provider._parse_provider_timestamp("2024-01-01T09:00:00+01:00")

    assert parsed == "2024-01-01T08:00:00Z"


@pytest.mark.asyncio
async def test_map_favorites_normalizes_plate():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        permit_media = PERMIT_SAMPLE["PermitMedias"][0]
        favorites = provider._map_favorites(permit_media)

    assert len(favorites) == 1
    favorite = favorites[0]
    assert favorite.id == "XY99ZZ"
    assert favorite.license_plate == "XY99ZZ"
    assert favorite.name == "Family"


@pytest.mark.asyncio
async def test_login_requires_username():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

        with pytest.raises(ValidationError):
            await provider.login(credentials={"password": "secret"})


@pytest.mark.asyncio
async def test_default_api_uri_is_applied():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )

        expected = f"https://example{DEFAULT_API_URI}{LOGIN_ENDPOINT}"
        assert provider._build_url(LOGIN_ENDPOINT) == expected


@pytest.mark.asyncio
async def test_extract_permit_falls_back_to_permits_list():
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        extracted = provider._extract_permit({"Permits": [PERMIT_SAMPLE]})

    assert extracted == PERMIT_SAMPLE


@pytest.mark.asyncio
async def test_start_reservation_payload_uses_local_offset_with_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"

        async def _noop_defaults() -> None:
            return None

        monkeypatch.setattr(provider, "_ensure_defaults", _noop_defaults)
        captured: dict[str, Any] = {}

        async def _fake_request_json_auth(method: str, path: str, *, json: Any) -> Any:
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

        start_dt = datetime(2026, 1, 2, 22, 57, tzinfo=UTC)
        end_dt = datetime(2026, 1, 2, 23, 57, tzinfo=UTC)
        reservation = await provider.start_reservation(
            "ab-12 cd",
            start_dt,
            end_dt,
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
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
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

        async def _fake_fetch_base() -> dict[str, Any]:
            return existing_permit

        monkeypatch.setattr(provider, "_fetch_base", _fake_fetch_base)
        captured: dict[str, Any] = {}

        async def _fake_request_json_auth(method: str, path: str, *, json: Any) -> Any:
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
async def test_add_favorite_payload_contains_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"
        captured: dict[str, Any] = {}

        async def _fake_list_favorites() -> list[Favorite]:
            return []

        async def _fake_request_json_auth(method: str, path: str, *, json: Any) -> Any:
            captured["json"] = json
            return {
                "Permit": {
                    "PermitMedias": [
                        {
                            "TypeID": 1,
                            "Code": "CARD-1",
                            "ActiveReservations": [],
                            "LicensePlates": [
                                {"Value": "AB12CD", "Name": "Visitor"},
                            ],
                        }
                    ]
                }
            }

        monkeypatch.setattr(provider, "list_favorites", _fake_list_favorites)
        monkeypatch.setattr(provider, "_request_json_auth", _fake_request_json_auth)
        favorite = await provider.add_favorite("ab-12 cd", name="Visitor")

    payload = captured["json"]
    assert payload["permitMediaTypeID"] == 1
    assert payload["permitMediaCode"] == "CARD-1"
    assert payload["licensePlate"]["Value"] == "AB12CD"
    assert payload["licensePlate"]["Name"] == "Visitor"
    assert payload["updateLicensePlate"] is None
    assert payload["name"] == "Visitor"
    assert favorite.id == "AB12CD"


@pytest.mark.asyncio
async def test_add_favorite_rejects_duplicate_plate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"

        async def _fake_list_favorites() -> list[Favorite]:
            return [Favorite(id="AB12CD", name="Family", license_plate="AB12CD")]

        called = {"request": False}

        async def _fake_request_json_auth(method: str, path: str, *, json: Any) -> Any:
            called["request"] = True
            return {}

        monkeypatch.setattr(provider, "list_favorites", _fake_list_favorites)
        monkeypatch.setattr(provider, "_request_json_auth", _fake_request_json_auth)

        with pytest.raises(ValidationError):
            await provider.add_favorite("ab-12 cd", name="Other")

    assert called["request"] is False


@pytest.mark.asyncio
async def test_remove_favorite_payload_contains_required_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with aiohttp.ClientSession() as session:
        provider = Provider(
            session,
            ProviderManifest(
                id="dvsportal",
                name="DVS Portal",
                favorite_update_fields=(),
                reservation_update_fields=("end_time",),
            ),
            base_url="https://example",
        )
        provider._permit_media_type_id = 1
        provider._permit_media_code = "CARD-1"
        captured: dict[str, Any] = {}

        async def _fake_list_favorites() -> list[Favorite]:
            return [Favorite(id="AB12CD", name="Visitor", license_plate="AB12CD")]

        async def _fake_request_json_auth(method: str, path: str, *, json: Any) -> Any:
            captured["json"] = json
            return {}

        monkeypatch.setattr(provider, "list_favorites", _fake_list_favorites)
        monkeypatch.setattr(provider, "_request_json_auth", _fake_request_json_auth)
        await provider.remove_favorite("ab-12 cd")

    payload = captured["json"]
    assert payload["permitMediaTypeID"] == 1
    assert payload["permitMediaCode"] == "CARD-1"
    assert payload["licensePlate"] == "AB12CD"
    assert payload["name"] == "Visitor"
