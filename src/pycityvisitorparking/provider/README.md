# Provider Authoring Guide

This document explains how to add a new provider to `pyCityVisitorParking`.
Provider PRs must touch only `src/pycityvisitorparking/provider/<provider_id>/...`.

## Required folder structure

Create a new folder under `src/pycityvisitorparking/provider/`:

```
src/pycityvisitorparking/provider/<provider_id>/
  manifest.json
  __init__.py
  api.py
  const.py
  README.md
  CHANGELOG.md
```

The `<provider_id>` must be lowercase and match the `id` field in `manifest.json`.

## Manifest requirements

Each provider must include a `manifest.json` with:

```json
{
  "id": "<provider_id>",
  "name": "Display Name",
  "favorite_update_possible": true
}
```

Manifests are validated against:
`src/pycityvisitorparking/provider/manifest.schema.json`.

## Provider class export

The provider package must export a class named `Provider` from
`src/pycityvisitorparking/provider/<provider_id>/__init__.py`:

```python
from .api import Provider

__all__ = ["Provider"]
```

The `Provider` class must inherit `pycityvisitorparking.provider.base.BaseProvider`
and implement all required async methods.

## Import safety

Discovery reads manifests without importing provider code. Avoid side effects on
import:

- No network requests
- No file writes
- No heavy computation

All setup should happen inside async methods.

## Base URL and API URI

Home Assistant supplies `base_url` and optionally `api_uri`. Provider code must
use relative paths and join them with `base_url + api_uri` via
`BaseProvider._build_url()` or `_request_json()` / `_request_text()`.

Do not hardcode `base_url` or `api_uri` in provider code.

## Authentication

`login()` must accept `Mapping[str, str]` or `**kwargs`. Validate required keys
and raise `ValidationError` for missing values. Raise `AuthError` for invalid
credentials or expired sessions.

Do not log credentials or tokens.

## Time handling (UTC required)

All public timestamps must be UTC ISO 8601 with a trailing `Z` and no
microseconds. Convert provider-local or offset timestamps to UTC internally.

Use utilities from `pycityvisitorparking.util`:

- `ensure_utc_timestamp()`
- `format_utc_timestamp()`
- `parse_timestamp()`

All timestamps must be timezone-aware and parseable.

## License plate normalization

Normalize plates to uppercase `A-Z0-9` and remove spaces/special characters.
Raise `ValidationError` for invalid or empty plates after normalization.

Use `normalize_license_plate()` from `pycityvisitorparking.util`.

## Zone validity filtering

`Permit.zone_validity` must include only chargeable windows.
Filter out free or non-chargeable windows. Use
`filter_chargeable_zone_validity()` from `pycityvisitorparking.util`.

## Reservation validation

`start_reservation()` requires both `start_time` and `end_time`.
Enforce `end_time > start_time` and raise `ValidationError` when violated.

Use `validate_reservation_times()` for shared validation and normalization.

## Favorites update behavior

Set `favorite_update_possible` in the manifest:

- `true` only if the provider supports a native update endpoint.
- `false` if updates require delete + add.

When `favorite_update_possible` is `false`, the core fallback removes and re-adds
the favorite. Providers should implement `_update_favorite_native()` even if the
fallback is used (it can raise `ProviderError` if called unexpectedly).

## Public models only

Map all provider responses to strict public dataclasses in
`pycityvisitorparking.models`:

- `ProviderInfo`
- `Permit`
- `ZoneValidityBlock`
- `Reservation`
- `Favorite`

Do not add provider-specific fields to public models.

## HTTP safety

Use the injected `aiohttp.ClientSession` from `BaseProvider`.
Enable TLS verification and enforce timeouts.
Translate network and HTTP errors into library exceptions.
Never leak raw `aiohttp` exceptions.

Retries are allowed only for idempotent GET requests and should be conservative
or disabled.

## Logging and PII

Do not log credentials, tokens, or full license plates. If logging is necessary,
mask plates using `mask_license_plate()`.

## Documentation and changelog

Each provider must include:

- `README.md` with auth requirements, supported operations, limitations,
  mapping notes, and links to official docs.
- `CHANGELOG.md` with an `Unreleased` section. Update it when auth, endpoints,
  mappings, or limitations change.

## Tests

Provider tests should use mocks/fixtures and avoid live services.
Add coverage for:

- license plate normalization
- UTC conversion from provider timestamps
- zone validity filtering
- mapping into public models

Run the test suite with:

```bash
hatch run test:run
```
