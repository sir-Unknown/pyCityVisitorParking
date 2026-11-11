<h1 align="center">
  pyCityVisitorParking
  <br>
  <sub><span style="font-size: 0.7em;">Async Python library for Dutch municipal visitor parking providers</span></sub>
</h1>

<p align="center">
  Provider-agnostic async Python library for Dutch municipal visitor parking systems.
  <br>
  Designed for Home Assistant, but usable in any async Python application.
</p>

<p align="center">
  <a href="https://pypi.org/project/pycityvisitorparking/">
    <img src="https://img.shields.io/pypi/v/pycityvisitorparking" alt="PyPI version">
  </a>
  <a href="https://pypi.org/project/pycityvisitorparking/">
    <img src="https://img.shields.io/pypi/pyversions/pycityvisitorparking" alt="Python versions">
  </a>
  <a href="https://github.com/sir-Unknown/pyCityVisitorParking/actions/workflows/ci.yml">
    <img src="https://github.com/sir-Unknown/pyCityVisitorParking/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI">
  </a>
</p>

> [!TIP]
> Looking for the Home Assistant integration? See: [ha_City-Visitor-Parking](https://github.com/sir-Unknown/ha_City-Visitor-Parking)

---

## About this library

**pyCityVisitorParking** is an async Python library for Dutch municipal visitor parking providers.

It exposes a small provider-agnostic API for:

- provider discovery
- permit lookup
- reservation management
- favorites management

The library is designed primarily for Home Assistant use, but it can also be used directly in any async Python application.

---

## Status

Currently bundled providers:

- DVS Portal
- The Hague
- 2park

Provider manifests are discovered from `src/pycityvisitorparking/provider/` without importing all providers up front.

Provider-specific documentation:

- [DVS Portal](https://github.com/sir-Unknown/pyCityVisitorParking/blob/main/src/pycityvisitorparking/provider/dvsportal/README.md)
- [The Hague](https://github.com/sir-Unknown/pyCityVisitorParking/blob/main/src/pycityvisitorparking/provider/the_hague/README.md)
- [2park](https://github.com/sir-Unknown/pyCityVisitorParking/blob/main/src/pycityvisitorparking/provider/2park/README.md)

---

## Supported municipalities

For the exact `base_url`, `api_uri`, and provider-specific notes, see the provider README files.

- **DVS Portal**: Apeldoorn, Bloemendaal, Delft, Den Bosch, Doetinchem (via Buha), Groningen, Haarlem, Harlingen, Heemstede, Heerenveen, Heerlen, Hengelo, Katwijk, Leiden, Leidschendam-Voorburg, Middelburg, Nissewaard, Oldenzaal, Rijswijk, Roermond, Schouwen-Duiveland, Sittard-Geleen, Smallingerland, Sudwest-Fryslan, Veere, Venlo, Vlissingen, Waadhoeke, Waalwijk, Weert, Zaanstad, Zevenaar, Zutphen, Zwolle
- **The Hague**: The Hague
- **2park**: Amstelveen, Assen, Bergen op Zoom, Breda, Deventer, Dordrecht, Eindhoven, Emmen, Etten-Leur, Gorinchem, Hardenberg, Harderwijk, Maastricht, Oosterhout, Oss, Roosendaal, Sluis, Terneuzen, Tiel, Veenendaal, Vlaardingen

---

## Installation

Requires **Python 3.14** or newer.

```bash
pip install pycityvisitorparking
```

---

## Quickstart

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})

        permit = await provider.get_permit()
        reservations = await provider.list_reservations()

        print(permit)
        print(reservations)


asyncio.run(main())
```

---

## Public API

### Client

`Client` is the main entry point.

- `list_providers()` returns available `ProviderInfo` objects
- `get_provider(provider_id, ...)` loads a specific provider on demand
- `Client` accepts an optional injected `aiohttp.ClientSession`
- if you do not inject a session, the client creates and owns its own session

Configuration options:

- `base_url`: provider base URL
- `api_uri`: optional provider API path
- `timeout`: optional `aiohttp.ClientTimeout`
- `retry_count`: retry count for idempotent GET requests

### Data models

Public data models:

- `ProviderInfo`
- `Permit`
- `ZoneValidityBlock`
- `Reservation`
- `Favorite`

Model highlights:

- `ProviderInfo` includes `id`, `favorite_update_fields`, `reservation_update_fields`, and `balance_units`
- `Permit` includes `id`, `remaining_balance`, `balance_unit`, and `zone_validity`
- `ZoneValidityBlock` contains UTC ISO 8601 `start_time` and `end_time`
- `Reservation` includes `id`, `name`, `license_plate`, `start_time`, and `end_time`
- `Favorite` includes `id`, `name`, and `license_plate`

### Standardized behavior

- timestamps are returned as UTC ISO 8601 strings
- license plates are normalized and validated
- the public API stays provider-agnostic
- some update operations may be unsupported by a provider; inspect `favorite_update_fields` and `reservation_update_fields`

---

## Common usage

### List providers

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client() as client:
        for provider in await client.list_providers():
            print(provider.id, provider.reservation_update_fields)


asyncio.run(main())
```

### Manage a reservation

```python
import asyncio
from datetime import datetime, timedelta, timezone

from pycityvisitorparking import Client


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})

        start_time = datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(hours=2)

        reservation = await provider.start_reservation(
            "12AB34",
            start_time=start_time,
            end_time=end_time,
            name="Visitor",
        )

        print(reservation.id)


asyncio.run(main())
```

### Manage favorites

```python
import asyncio

from pycityvisitorparking import Client
from pycityvisitorparking.exceptions import ProviderError


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})

        favorite = await provider.add_favorite("12AB34", name="Visitor")

        try:
            updated = await provider.update_favorite(favorite.id, name="Visitor 2")
            print(updated)
        except ProviderError:
            print("Favorite updates are not supported by this provider")


asyncio.run(main())
```

---

## Error handling

Public methods raise library exceptions instead of raw `aiohttp` exceptions:

- `AuthError`
- `NetworkError`
- `ValidationError`
- `ProviderError`
- `RateLimitError`
- `ServiceUnavailableError`
- `NotFoundError`
- `TimeoutError`
- `ConfigError`

Each exception includes normalized metadata such as `error_code`, `detail`, and optional `user_message`.

Example:

```python
from pycityvisitorparking import Client
from pycityvisitorparking.exceptions import AuthError, NetworkError, ProviderError, ValidationError

async with Client(base_url=base_url, api_uri=api_uri) as client:
    try:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})
        permit = await provider.get_permit()
    except (AuthError, ValidationError) as exc:
        handle_auth_or_input_error(exc)
    except NetworkError as exc:
        handle_network_issue(exc)
    except ProviderError as exc:
        handle_provider_issue(exc)
```

---

## Logging

The library logs to the `pycityvisitorparking` logger using the standard Python `logging` module.

- credentials are not logged
- full license plates are not logged
- request context can be attached for clearer diagnostics

---

## Development

This repository uses `uv` for local development tasks.

Common checks:

```bash
uv run --group lint ruff check .
uv run --group lint ruff format --check .
uv run --group typecheck pyright
uv run --group test pytest
uv run --group schema python -m pytest -o addopts=-q tests/test_manifest_schema.py
uv build
uvx twine check dist/*
```

Release notes and publishing are handled through GitHub Actions. See [docs/RELEASING.md](docs/RELEASING.md).

---

## Provider development

Providers live under:

```text
src/pycityvisitorparking/provider/<provider_id>/
```

A provider folder typically contains:

```text
src/pycityvisitorparking/provider/<provider_id>/
  manifest.json
  __init__.py
  api.py
  const.py
  README.md
  CHANGELOG.md
```

Related documentation:

- [Provider framework](src/pycityvisitorparking/provider/README.md)
- [Provider template](docs/provider-template/README.md)
- [Provider development guide](docs/provider-development/README.md)

---

## License

MIT. See [LICENSE](LICENSE).
