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

- Providers: `list_providers()` returns `ProviderInfo` with `id` and `favorite_update_possible`.
- Permit: `get_permit()` returns `Permit` with `id`, `remaining_balance` (minutes), and `zone_validity`.
- Zone validity: each `ZoneValidityBlock` includes `start_time` and `end_time` (UTC ISO 8601).
- Reservations: `list_reservations()`, `start_reservation()`, `update_reservation()`, and
  `end_reservation()` return `Reservation` with `id`, `name`, `license_plate`,
  `start_time`, and `end_time`.
- Favorites: `list_favorites()` and `add_favorite()` return `Favorite` with `id`, `name`,
  and `license_plate`. `update_favorite()` returns `Favorite`, while
  `remove_favorite()` removes the entry without returning data.

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

## Normalization rules

- All public timestamps must be UTC ISO 8601 with `Z` and no microseconds.
- License plates are normalized to uppercase `A-Z0-9` without spaces/symbols.
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
