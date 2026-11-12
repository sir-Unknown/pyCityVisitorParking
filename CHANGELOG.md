# CHANGELOG

## Unreleased

- Add Rotterdam provider for the visitor parking portal at `bezoek.rotterdam.nl`: permit and balance, reservations, and saved license plates (favorites). Favorites and login are verified against the live portal; permit and reservation mapping follows the portal's published data model and is verified with mocked responses only, see the provider README.
- Add per-reservation zone selection: `Permit.zones` (new public `Zone` model with `id`, `name`, and `zone_validity`), an optional `zone_id` argument on `start_reservation`, `Reservation.zone_id`, and the manifest capability `zone_selection` (exposed as `ProviderInfo.zone_selection`). All additions are optional with defaults; providers without zones reject a `zone_id` with `ValidationError`. Rotterdam supports it.
- Demo provider: a municipality name containing "Rotterdam" gets a test permit with zones 10, 630 and 632 and the Rotterdam paid hours for the coming week (zone 10 is paid until 01:00 on Friday and Saturday), plus a running and a planned reservation in different zones. The other demo permits have no zones, so both paths can be tested.

## 0.5.30

- DVS Portal: fix write requests (reservations, favorites) failing with HTTP 401 on portals that publish the XSRF token in the `__Host-Xsrf-DVSPortal` cookie and do not serve `app.env.js` (Rijswijk). The cookie value is now sent as `X-XSRF-TOKEN` by default ([#128](https://github.com/sir-Unknown/pyCityVisitorParking/issues/128)).

## 0.5.29

- Breaking: remove the provider-specific `RESOLVED_LOCATION` and `RESOLVED_PERMIT_MEDIA_TYPE_ID` exports (and the `pycityvisitorparking.const` module) and `BaseProvider.resolved_login_params`. Provider-resolved login state stays internal and is reused on reauthentication; callers no longer persist or replay it. 2park's `login()` no longer accepts `location` ([#63](https://github.com/sir-Unknown/pyCityVisitorParking/issues/63), [#64](https://github.com/sir-Unknown/pyCityVisitorParking/issues/64)).
- Breaking: remove `user_message` from library exceptions. Exceptions are technical; user-facing and translated messages belong to the integration ([#65](https://github.com/sir-Unknown/pyCityVisitorParking/issues/65)).
- Add the `ErrorCode` `StrEnum` with the supported, stable `error_code` values and document the code-based error contract in the README. Common failure paths now carry a specific code: HTTP 404 raises `NotFoundError`, HTTP 429 raises `RateLimitError`, HTTP 502/503/504 raise `ServiceUnavailableError` (was `NetworkError`), request timeouts raise `TimeoutError`, unsupported operations use `not_supported`, and provider rejections use `provider_rejected` ([#66](https://github.com/sir-Unknown/pyCityVisitorParking/issues/66)).
- Log expected, recoverable paths at debug instead of warning level: reauthentication, 401/403 responses that trigger it, transient network failures and timeouts, HTTP 429/502/503/504, and DVS Portal's HTML session-expiry response ([#67](https://github.com/sir-Unknown/pyCityVisitorParking/issues/67), [#68](https://github.com/sir-Unknown/pyCityVisitorParking/issues/68)).

## 0.5.28

- Security: update locked dependencies to fix open advisories: aiohttp 3.14.5, virtualenv 21.15.6, filelock 4.2.10, idna 3.20, and multidict 7.2.1 ([#107](https://github.com/sir-Unknown/pyCityVisitorParking/pull/107), [#108](https://github.com/sir-Unknown/pyCityVisitorParking/pull/108), [#115](https://github.com/sir-Unknown/pyCityVisitorParking/pull/115)).
- Refresh `uv.lock` so it matches `pyproject.toml` again (`uv lock --check` passes) and bump dev tooling: pylint 4.0.9, pytest 9.1.0, pytest-asyncio 1.4.0, ruff 0.15.18, pyright 1.1.410, pre-commit 4.6.0, and zizmor 1.25.2 ([#115](https://github.com/sir-Unknown/pyCityVisitorParking/pull/115)).
- Update pre-commit hooks (ruff-pre-commit 0.17.3, zizmor-pre-commit 1.32.0, codespell 2.4.3) and the GitHub Actions dependency group (11 updates) ([#113](https://github.com/sir-Unknown/pyCityVisitorParking/pull/113), [#109](https://github.com/sir-Unknown/pyCityVisitorParking/pull/109), [#95](https://github.com/sir-Unknown/pyCityVisitorParking/pull/95), [#97](https://github.com/sir-Unknown/pyCityVisitorParking/pull/97)).
- A 2xx response with an HTML body on a JSON endpoint (maintenance, WAF or error page) now raises `ServiceUnavailableError` instead of a generic `ProviderError` and is logged at debug level instead of warning, so callers can treat it as temporary. Applies to the shared base request, DVS Portal, 2park and The Hague.
- DVS Portal: an expired session that the portal reports as an HTML HTTP 500 response (Nijmegen, Groningen) now triggers one transparent re-login and retry. A persistent HTML 500 raises `ServiceUnavailableError` instead of an auth failure. Thanks [@WouterJN](https://github.com/WouterJN) for the original fix ([#76](https://github.com/sir-Unknown/pyCityVisitorParking/issues/76), [#93](https://github.com/sir-Unknown/pyCityVisitorParking/pull/93), [#119](https://github.com/sir-Unknown/pyCityVisitorParking/pull/119)).
- 2park: recover from an expired session. The provider answers it with HTTP 200 and status `SESSION_TIMEOUT`, which was mapped to a zero balance and no favorites until the integration was reloaded.
- Log the internal "reauth triggered" step at debug instead of warning level; an expired session that is renewed transparently is an expected path.

## 0.5.16

- Fix empty PyPI wheel: remove conflicting `sources` and `include` from hatch wheel build config. The 0.5.15 wheel contained only dist-info metadata due to `sources = ["src"]` conflicting with `packages`-based discovery when building via `uv build` (PEP 517). PyPI does not allow re-uploading the same version, so this fix ships as 0.5.16 ([#20](https://github.com/sir-Unknown/pyCityVisitorParking/issues/20), [#27](https://github.com/sir-Unknown/pyCityVisitorParking/pull/27)).
- Pin `gh-action-pypi-publish` to a commit hash and update to v1.13.0 to avoid supply chain risk from floating action tags.

## 0.5.15

- Add 2park provider: `get_permit`, `list_reservations`, `start_reservation`, `update_reservation` (end_time only), `end_reservation`, `list_favorites`, `add_favorite`, and `remove_favorite`. Thanks [@syphernl](https://github.com/syphernl) for the initial implementation ([#5](https://github.com/sir-Unknown/pyCityVisitorParking/pull/5)).
- DVS Portal / The Hague: align `_request_json`, `_request_text`, and `_request` signatures with `BaseProvider` (`**kwargs`).

## 0.5.14

- Publish releases directly on tag pushes to ensure PyPI publishing runs.

## 0.5.13

- Fix release workflow tag resolution to enable CI PyPI publishing.

## 0.5.12

- Publish GitHub releases automatically after successful tagged CI runs.

## 0.5.11

- Refactor provider request retry handling into the shared base provider.
- Consolidate provider ID helpers and align request tests with shared behavior.
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
