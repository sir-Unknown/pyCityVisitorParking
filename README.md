# pyCityVisitorParking

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
