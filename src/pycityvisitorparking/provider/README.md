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

`balance_units` and `reservation_target_selection` are optional. Manifests are validated against:
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

Anything resolved during login (product, location, permit media type, tokens) is
provider state: keep it internal, cache it for reauthentication, and do not expose
it through the public API.

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

## Paid hours filtering

`Permit.paid_hours` must include only paid hours.
Filter out free windows. Use
`filter_paid_hours()` from `pycityvisitorparking.util`.

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
`ProviderError` with `error_code=ErrorCode.NOT_SUPPORTED`. Providers should still
implement `_update_favorite_native()` to raise the same error if called unexpectedly.

## Reservation update behavior

Set `capabilities.reservation_update_fields` in the manifest:

- Use `[]` when updates are not supported.
- Include any supported fields: `start_time`, `end_time`, `name`.

When `reservation_update_fields` is empty, `update_reservation()` should raise
`ProviderError` with `error_code=ErrorCode.NOT_SUPPORTED`.

## Reservation targets

Some providers need a user choice before `start_reservation()` can succeed, for
example a zone or a parking machine. Never expose that choice as a provider-specific
login key or `start_reservation()` argument. Model it as a reservation target:

- Set `capabilities.reservation_target_selection` to `"list"` when only the targets
  from `list_reservation_targets()` are valid, or to `"free_input"` when the provider
  also accepts other ids it can resolve itself (for example a number read from a
  machine). Omit it when there is nothing to choose.
- Override `list_reservation_targets()`: default target first, `[]` when the active
  permit has nothing to choose. Fill `ReservationTarget.paid_hours` when targets
  have their own paid hours, and keep `Permit.paid_hours` equal to the
  default target's windows.
- Call `self._validate_reservation_target_id(reservation_target_id)` at the start of
  `start_reservation()`, use the default target when it is `None`, and raise
  `ValidationError` for an id the provider cannot resolve. Without the capability the
  helper rejects every id.
- Set `Reservation.reservation_target_id` to the target a reservation is booked for.
  `update_reservation()` never changes the target.
- Keep provider-native fields (`location`, `machine_id`, zone numbers) internal; the
  target `id` is an opaque string.

## Public models only

Map all provider responses to strict public dataclasses in
`pycityvisitorparking.models`:

- `ProviderInfo`
- `Permit`
- `PaidHoursBlock`
- `ReservationTarget`
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

`BaseProvider.request_context_name` returns the municipality/context label set via
`set_request_context()` (`None` when unset).

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
- paid hours filtering
- mapping into public models
- request/response flows for provider methods with mocked aiohttp responses
- HTTP/auth/error mapping for non-2xx and invalid JSON responses

Run the test suite with:

```bash
hatch run test:run
```
