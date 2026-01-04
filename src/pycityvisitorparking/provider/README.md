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
  "capabilities": {
    "favorite_update_fields": ["license_plate", "name"],
    "reservation_update_fields": ["start_time", "end_time", "name"]
  }
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

`login()` must accept `Mapping[str, str]` or `**kwargs`. Require `username` and
`password` as the public credential keys and translate them to provider-specific
fields when needed. Validate required keys and raise `ValidationError` for
missing values. Raise `AuthError` for invalid credentials or expired sessions.

Do not log credentials or tokens.

## Time handling (UTC required)

All public timestamps must be UTC ISO 8601 with a trailing `Z` and no
microseconds. Public APIs accept only timezone-aware `datetime` values and must
reject naive timestamps with `ValidationError`. Convert provider-local or
offset timestamps to UTC internally.
Normalize inputs to UTC `datetime` values and serialize to strings only when
building payloads or public models.
Use `normalize_datetime()` for API inputs and `parse_timestamp()` for provider
timestamp strings.

Use utilities from `pycityvisitorparking.util`:

- `ensure_utc_timestamp()`
- `format_utc_timestamp()`
- `normalize_datetime()`
- `parse_timestamp()`

All timestamps must be timezone-aware and parseable and are truncated to second
precision.

## License plate normalization

Normalize plates to uppercase `A-Z0-9` and remove spaces/special characters.
Raise `ValidationError` for invalid or empty plates after normalization.

Use `normalize_license_plate()` from `pycityvisitorparking.util`.

## Zone validity filtering

`Permit.zone_validity` must include only chargeable windows.
Filter out free or non-chargeable windows. Use
`filter_chargeable_zone_validity()` from `pycityvisitorparking.util`.

## Reservation validation

`start_reservation()` requires both `start_time` and `end_time` as timezone-aware
`datetime` values. `update_reservation()` and `end_reservation()` accept only
timezone-aware `datetime` values for any provided times.
Enforce `end_time > start_time` and raise `ValidationError` when violated.

Use `validate_reservation_times()` for shared validation and normalization.

## Favorites update behavior

Set `capabilities.favorite_update_fields` in the manifest:

- Use `[]` when updates are not supported.
- Include `license_plate` and/or `name` when updates are supported.

When `favorite_update_fields` is empty, `update_favorite()` raises
`ProviderError`. Providers should still implement `_update_favorite_native()` to
raise `ProviderError` if called unexpectedly.

## Reservation update behavior

Set `capabilities.reservation_update_fields` in the manifest:

- Use `[]` when updates are not supported.
- Include any supported fields: `start_time`, `end_time`, `name`.

When `reservation_update_fields` is empty, `update_reservation()` should raise
`ProviderError`.

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
mask plates when logging (avoid full values in logs).

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
