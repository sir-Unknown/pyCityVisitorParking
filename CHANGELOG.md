# CHANGELOG

## Unreleased

## 0.5.10

- Add structured exception metadata (`error_code`, `detail`, optional `user_message`) for safer client handling.
- Add specialized exception types for rate limits, timeouts, config, not found, and service availability.

## 0.5.9

- Fix release workflow version guard regex to correctly parse `__version__`.

## 0.5.8

- Add Release Drafter configuration and workflow for automated release notes.

## 0.5.7

- Fix DVS Portal reservation update/end and favorite add control flow to ensure consistent returns.
- Add coverage-focused provider tests and negative input validation scenarios.
- Add coverage defaults for pytest, update schema validation to ignore coverage addopts, and add ignore entries for coverage artifacts.

## 0.5.6

- DVS Portal: serialize provider operations with a re-entrant async lock to avoid race conditions.

## 0.5.5

- Add PII-safe logging across client/provider flows with extra diagnostics for retries, reauth, and fallbacks.

## 0.5.4

- DVS Portal: rely on the stored favorite name in remove payloads and reject duplicate plates when adding favorites.
- README/test updates describe the favorite name handling and the live check helper now derives a distinct favorite name.
- The Hague: fallback to `zone.start_time`/`zone.end_time` when `zone_validity` is missing and document the behavior; tests now cover the fallback.

## 0.5.3

- Breaking: replace manifest capability flags with a `capabilities` object and
  expose `favorite_update_fields` / `reservation_update_fields` in `ProviderInfo`.
- DVS Portal: support reservation updates via `reservation/update` with minute-delta conversion.

## 0.5.2

- Add `reservation_update_possible` to provider manifests and `ProviderInfo`.

## 0.5.1

- Breaking: `update_favorite()` now raises `ProviderError` when updates are unsupported.
- Breaking: drop legacy `permitMediaTypeID`/`permitMediaTypeId` credential aliases.
- Breaking: remove The Hague `zone` fallback when `zone_validity` is empty.
- Breaking: remove DVS reservation selection fallback.
- Breaking: reservation start/end inputs now require timezone-aware `datetime` values; string inputs are rejected.
- DVS Portal: fix favorite upsert/remove payloads and accept `Permits[0]` when `Permit` is omitted.
- DVS Portal reservation creation payloads now use Europe/Amsterdam local time with offsets and milliseconds to match API expectations.
- The Hague: map PV error codes to readable `ProviderError` messages.
- Remove the `mask_license_plate` helper from core utilities; the live check script now masks plates locally.
- Dev tooling: pin pip/Hatch/ruff/pytest/twine versions in Hatch envs, CI, and devcontainer.

## 0.4.1

- Default The Hague `api_uri` to `/api` when omitted.

## 0.4.0

- Add async loader helpers for non-blocking manifest access.
- Add a TTL to the manifest cache with refresh controls.
- Document manifest cache behavior and async loader helpers.
- Require `username`/`password` credentials across providers.
- Default DVS Portal `api_uri` to `/DVSWebAPI/api` when omitted.
- Use `zone.start_time`/`zone.end_time` for The Hague when `zone_validity` is empty.

## 0.3.1

- Run provider discovery/import in background threads to avoid blocking the event loop.
- Cache provider manifests to avoid repeated filesystem scans.
- Add UTC normalization assertions for provider timestamp mappings.
- Publish `py.typed` for improved type checking in integrations.
- Document async-safe provider discovery behavior.

## 0.3.0

- Rename `Permit.remaining_time` to `Permit.remaining_balance`.

## 0.2.1

- Add a dedicated PyPI publishing environment to the release workflow.

## 0.2.0

- Add async client facade, provider interface, and provider discovery without imports.
- Add strict public models, normalization utilities, and validation helpers.
- Add manifest schema, loader utilities, and schema validation test.
- Add fallback behavior for favorite updates and zero-provider tests.
- Add documentation updates and pre-commit config for Ruff.
- Add base_url and api_uri support for provider requests using relative paths.
- Add The Hague provider implementation.
- Document DVS Portal municipality endpoints.
