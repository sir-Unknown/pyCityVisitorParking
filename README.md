# pyCityVisitorParking

Async integration layer between Home Assistant and Dutch municipal visitor parking APIs.

## Status

This package ships the core client, provider interface, and discovery tooling,
plus the following providers:

- DVS Portal
- The Hague

`list_providers()` reads provider manifests under `src/pycityvisitorparking/provider/`.

Provider documentation:

- DVS Portal: [src/pycityvisitorparking/provider/dvsportal/README.md](src/pycityvisitorparking/provider/dvsportal/README.md)
- The Hague: [src/pycityvisitorparking/provider/the_hague/README.md](src/pycityvisitorparking/provider/the_hague/README.md)

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

## Provider framework

Providers are discovered via `manifest.json` files without importing provider
modules. To add a provider later, create:

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
