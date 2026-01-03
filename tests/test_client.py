import aiohttp
import pytest

from pycityvisitorparking import Client


@pytest.mark.asyncio
async def test_client_does_not_close_injected_session() -> None:
    session = aiohttp.ClientSession()
    client = Client(session=session)
    await client.aclose()

    assert session.closed is False
    await session.close()
