"""Cross-provider contract for the reservation target capability."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiohttp
import pytest

from pycityvisitorparking import Client, ValidationError


@pytest.mark.asyncio
async def test_providers_without_the_capability_reject_a_reservation_target_id() -> None:
    start = datetime.now(UTC) + timedelta(hours=1)
    async with aiohttp.ClientSession() as session:
        client = Client(session=session, base_url="https://example.invalid")
        provider_infos = await client.list_providers()
        checked: set[str] = set()
        for info in provider_infos:
            if info.reservation_target_selection is not None:
                continue
            provider = await client.get_provider(info.id)
            with pytest.raises(ValidationError, match="reservation_target_id"):
                await provider.start_reservation(
                    "AB12CD", start, start + timedelta(hours=1), reservation_target_id="target"
                )
            assert await provider.list_reservation_targets() == []
            checked.add(info.id)
    assert {"2park", "dvsportal", "the_hague"} <= checked
