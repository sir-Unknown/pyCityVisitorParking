# pyCityVisitorParking

[![PyPI version](https://img.shields.io/pypi/v/pycityvisitorparking)](https://pypi.org/project/pycityvisitorparking/)
[![Python versions](https://img.shields.io/pypi/pyversions/pycityvisitorparking)](https://pypi.org/project/pycityvisitorparking/)
[![CI](https://github.com/sir-Unknown/pyCityVisitorParking/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sir-Unknown/pyCityVisitorParking/actions/workflows/ci.yml)

Async integration layer between Home Assistant and Dutch municipal visitor parking APIs.

## Status

This package ships the core client, provider interface, and discovery tooling,
plus the following providers:

- DVS Portal
- The Hague

`list_providers()` reads provider manifests under `src/pycityvisitorparking/provider/`.

Provider documentation:

- DVS Portal: https://github.com/sir-Unknown/pyCityVisitorParking/blob/main/src/pycityvisitorparking/provider/dvsportal/README.md
- The Hague: https://github.com/sir-Unknown/pyCityVisitorParking/blob/main/src/pycityvisitorparking/provider/the_hague/README.md

## Supported municipalities

For exact `base_url` and `api_uri` values, see the provider READMEs.

- DVS Portal: Apeldoorn, Bloemendaal, Delft, Den Bosch, Doetinchem (via Buha), Groningen,
  Haarlem, Harlingen, Heemstede, Heerenveen, Heerlen, Hengelo, Katwijk, Leiden,
  Leidschendam-Voorburg, Middelburg, Nissewaard, Oldenzaal, Rijswijk, Roermond,
  Schouwen-Duiveland, Sittard-Geleen, Smallingerland, Sudwest-Fryslan, Veere, Venlo,
  Vlissingen, Waadhoeke, Waalwijk, Weert, Zaanstad, Zevenaar, Zutphen, Zwolle
- The Hague: The Hague

## Installation

Requires Python 3.13+.

```bash
pip install pycityvisitorparking
```

## Quickstart

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client(base_url="https://example") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})
        permit = await provider.get_permit()
        print(permit)


asyncio.run(main())
```

## Usage

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client() as client:
        providers = await client.list_providers()
        print(providers)


asyncio.run(main())
```

## Configuration

- `base_url` is required for provider requests.
- `api_uri` is optional; providers may define a default (see provider README).
- Credentials are standardized: `username` and `password` are required.
- Provider-specific optional fields (for example `permit_media_type_id`) are
  documented in each provider README.

## Async behavior

Provider discovery (`list_providers()`, `get_provider()`) runs in background
threads so async callers avoid blocking the event loop.

## Available data

The public API exposes a small, provider-agnostic set of models and operations.
Provider READMEs list credential requirements and any unsupported operations.

- Providers: `list_providers()` returns `ProviderInfo` with `id`,
  `favorite_update_fields`, and `reservation_update_fields`.
- Permit: `get_permit()` returns `Permit` with `id`, `remaining_balance` (minutes), and `zone_validity`.
- Zone validity: each `ZoneValidityBlock` includes `start_time` and `end_time` (UTC ISO 8601).
- Reservations: `list_reservations()`, `start_reservation()`, `update_reservation()`, and
  `end_reservation()` return `Reservation` with `id`, `name`, `license_plate`,
  `start_time`, and `end_time`.
  Some providers only support updating `end_time` (see `reservation_update_fields`).
- Favorites: `list_favorites()` and `add_favorite()` return `Favorite` with `id`, `name`,
  and `license_plate`. `update_favorite()` returns `Favorite` when supported
  (`favorite_update_fields` is non-empty), otherwise it raises `ProviderError`.
  `remove_favorite()` removes the entry without returning data.

### Examples

Providers (`list_providers()`):

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client() as client:
        providers = await client.list_providers()
        for info in providers:
            print(info.id, info.favorite_update_fields, info.reservation_update_fields)


asyncio.run(main())
```

Permit (`get_permit()`):

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})
        permit = await provider.get_permit()
        print(permit.id, permit.remaining_balance)


asyncio.run(main())
```

Zone validity (`ZoneValidityBlock`):

```python
import asyncio

from pycityvisitorparking import Client


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})
        permit = await provider.get_permit()
        for block in permit.zone_validity:
            print(block.start_time, block.end_time)


asyncio.run(main())
```

Reservations (`list_reservations()`, `start_reservation()`, `update_reservation()`, `end_reservation()`):

```python
import asyncio
from datetime import datetime, timedelta, timezone

from pycityvisitorparking import Client


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})

        reservations = await provider.list_reservations()
        print([reservation.id for reservation in reservations])

        start_time = datetime(2024, 5, 1, 9, 0, tzinfo=timezone.utc)
        end_time = start_time + timedelta(hours=2)
        reservation = await provider.start_reservation(
            "12AB34",
            start_time=start_time,
            end_time=end_time,
            name="Visitor",
        )

        if "end_time" in provider.reservation_update_fields:
            new_end_time = end_time + timedelta(hours=1)
            reservation = await provider.update_reservation(
                reservation.id,
                end_time=new_end_time,
            )
            end_time = new_end_time

        ended = await provider.end_reservation(reservation.id, end_time=end_time)
        print(ended.id, ended.start_time, ended.end_time)


asyncio.run(main())
```

Favorites (`list_favorites()`, `add_favorite()`, `update_favorite()`, `remove_favorite()`):

```python
import asyncio

from pycityvisitorparking import Client
from pycityvisitorparking.exceptions import ProviderError


async def main() -> None:
    async with Client(base_url="https://example", api_uri="/api") as client:
        provider = await client.get_provider("dvsportal")
        await provider.login(credentials={"username": "user", "password": "secret"})

        favorites = await provider.list_favorites()
        print([favorite.id for favorite in favorites])

        favorite = await provider.add_favorite("12AB34", name="Visitor")
        try:
            favorite = await provider.update_favorite(favorite.id, name="Visitor 2")
            print(favorite.id, favorite.name, favorite.license_plate)
        except ProviderError:
            pass

        await provider.remove_favorite(favorite.id)


asyncio.run(main())
```

## Provider framework

Providers are discovered via `manifest.json` files without importing provider
modules. Discovery runs in a background thread to avoid blocking the event loop.
To add a provider later, create:

```
src/pycityvisitorparking/provider/<provider_id>/
  manifest.json
  __init__.py
  api.py
  const.py
  README.md
  CHANGELOG.md
```

Only files under `src/pycityvisitorparking/provider/<provider_id>/` should change
in a provider PR.

Manifest loading is cached (5-minute TTL); pass `refresh=True` or call
`clear_manifest_cache()` to force a reload. If you use loader helpers directly,
prefer their `async_*` variants to avoid blocking the event loop.

Credential inputs are standardized: pass `username` and `password` to
`login()` for all providers. Provider READMEs list any optional fields such as
`permit_media_type_id`.

## Error handling

Public methods raise library exceptions instead of raw `aiohttp` errors:

- `AuthError`: authentication failures (HTTP 401/403 or provider auth rejection).
- `NetworkError`: network/timeout failures.
- `ValidationError`: invalid inputs (timestamps, plates, missing fields).
- `ProviderError`: provider responses or request failures not covered above.

Exception messages avoid credentials and full license plates.

Example handling:

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

## Logging

The library logs diagnostic events to the `pycityvisitorparking` logger using
the standard Python `logging` module. Configure handlers and levels in your
application to enable debugging output. Logs avoid credentials and full license
plates.

## Normalization rules

- Public APIs accept only timezone-aware `datetime` values; naive timestamps raise
  `ValidationError`.
- All public timestamps are normalized to UTC ISO 8601 with `Z` and second
  precision (microseconds are truncated).
- Internally, reservation times are handled as timezone-aware UTC `datetime`
  values and serialized to strings only at provider and model boundaries.
- License plates are normalized to uppercase `A-Z0-9` without spaces/symbols.
- Adding a favorite that already exists by license plate raises `ValidationError`.
- `zone_validity` must include only chargeable windows.

## Development

Run checks with Hatch:

```bash
hatch run lint:check
hatch run lint:format-check
hatch run test:run
```

Build artifacts:

```bash
hatch build
python -m twine check dist/*
```

## License

MIT. See `LICENSE`.
