# AGENTS.md — Development Guide (pyCityVisitorParking)

## 1) Purpose

This repository contains `pycityvisitorparking`, an async Python library specifically intended to support the Home Assistant integration `city_visitor_parking`.

The library exists to provide a small, provider-agnostic contract for:

- provider discovery
- permit lookup
- reservation management
- favorites management
- normalization of provider-native API behavior into a Home Assistant-friendly generic contract

The library is Home Assistant-oriented by design. Keep implementation choices, API boundaries, naming, and maintenance decisions aligned with Home Assistant developer expectations.

## 2) Current repo shape

Treat this repository as five connected surfaces that must stay aligned:

- Python library code in `src/pycityvisitorparking/`
- Provider implementations in `src/pycityvisitorparking/provider/<provider_id>/`
- Public package docs such as `README.md`, `CHANGELOG.md`, and `docs/RELEASING.md`
- Provider development docs and templates under `docs/provider-development/` and `docs/provider-template/`
- GitHub automation for CI, release drafting, release publishing, and packaging validation

Changes in one surface often require follow-up updates in the others.

## 3) Core goals

The library must remain:

- async-only
- provider-agnostic at the public API boundary
- aligned with Home Assistant integration needs
- strict about validation and error normalization
- careful about privacy and logging
- easy to extend with additional providers without changing the public contract unnecessarily

## 4) Runtime baseline

- Target Python `3.14`.
- Keep `requires-python = ">=3.14"` aligned with:
  - `pyproject.toml`
  - Ruff target version
  - Pyright version
  - Pylint version
  - CI configuration
  - PyPI metadata

If supported Python versions change, update all of those surfaces together.

## 5) Home Assistant alignment

Treat Home Assistant developer guidance as the compatibility baseline for this library.

The library should support Home Assistant integration patterns by default:

- async dependency behavior
- injected `aiohttp.ClientSession` support
- normalized exceptions suitable for integration-side mapping
- generic terminology suitable for translations and user-facing HA UX
- minimal log noise during expected retry, reauth, or temporary outage flows

If a local library convention conflicts with what is most likely to be acceptable in a Home Assistant integration dependency, resolve the conflict in favor of the Home Assistant-friendly option.

## 6) Provider boundary

All provider-native API behavior must be implemented inside `pycityvisitorparking`.

This includes:

- authentication quirks
- endpoint structure
- request and response parsing
- municipality-specific payload handling
- provider-specific fallback behavior
- native identifiers, temporary tokens, and intermediate fields required only for provider communication
- provider-specific availability, balance, permit, reservation, and favorite mapping
- normalization of provider-native concepts into the generic public contract

The Home Assistant integration must not become the place where provider quirks are implemented.

If behavior is specific to one provider, municipality, backend, or API implementation, it belongs in the library.

## 7) User-facing contract

Anything shown to users must remain generic.

This applies to:

- config flow text
- options flow text
- reauthentication text
- entity names
- entity attributes intended for users
- service names and service fields
- service validation errors
- diagnostics summaries
- websocket payloads exposed to the frontend
- frontend labels, messages, actions, and errors
- documentation aimed at end users

Do not expose provider-native terminology, raw provider field names, municipality-specific backend wording, or API-specific concepts to users unless they have first been normalized into a generic library concept.

## 8) Public API contract

The public API is intentionally small and stable.

### Client

`Client` in `src/pycityvisitorparking/client.py` is the public entry point.

It must:

- support async provider discovery with `list_providers()`
- support lazy provider loading with `get_provider(provider_id, ...)`
- accept an optional injected `aiohttp.ClientSession`
- create and own an internal session only when no session is injected
- never close an injected session
- support `async with Client(...)`
- support explicit cleanup with `await client.aclose()`

### Provider loading

Provider discovery must:

- load provider manifests without importing all provider modules
- import only the selected provider module when `get_provider()` is called
- validate manifest structure and values
- keep discovery logic in the loader, not in the integration layer

### Public models

Public dataclasses must live in `src/pycityvisitorparking/models.py`.

Current public models are:

- `ProviderInfo`
- `Permit`
- `ZoneValidityBlock`
- `Reservation`
- `Favorite`

Keep the models provider-agnostic.

Current model expectations:

- `ProviderInfo` exposes:
  - `id`
  - `favorite_update_fields`
  - `reservation_update_fields`
  - `balance_units`
- `Permit` exposes:
  - `id`
  - `remaining_balance`
  - `zone_validity`
  - `balance_unit`
- `ZoneValidityBlock` exposes:
  - `start_time`
  - `end_time`
- `Reservation` exposes:
  - `id`
  - `name`
  - `license_plate`
  - `start_time`
  - `end_time`
- `Favorite` exposes:
  - `id`
  - `name`
  - `license_plate`

Do not add provider-specific metadata to these public models unless the field is generic across providers and justified by multiple real implementations.

## 9) Public API anti-leak rule

Do not expose provider-native details through the public library surface unless they have been normalized into a generic concept.

In particular:

- avoid exporting provider-specific constants from `pycityvisitorparking.__init__`
- avoid making provider-specific login resolution details part of the public contract
- avoid requiring the integration to understand provider-native field names
- avoid forcing the integration to persist provider-native state unless there is a generic contract for it

If a piece of data only exists to talk to a specific provider API, it should stay internal to the provider implementation unless and until it is promoted into a generic library concept.

## 10) Base provider contract

`BaseProvider` in `src/pycityvisitorparking/provider/base.py` defines the shared provider behavior.

Providers must follow the current base contract and shared helpers for:

- authentication flow
- request building
- timeout handling
- retry behavior
- reservation time validation
- UTC normalization
- license plate normalization
- chargeable `zone_validity` filtering
- normalized exceptions
- structured logging

Provider implementations should reuse base helpers instead of duplicating validation or normalization logic.

## 11) Time, balance, and identifier rules

### Timestamps

- Return public timestamps as UTC ISO 8601 strings.
- Keep them timezone-aware and normalized.
- Do not expose raw provider-local timestamps in the public API.

### Zone validity

- Public `zone_validity` must contain chargeable windows only.
- Free windows must be filtered out before public exposure.
- Invalid or ambiguous provider time data must raise normalized library errors rather than leaking raw parsing failures.

### Reservation times

- `start_reservation` requires both `start_time` and `end_time`.
- Enforce `end_time > start_time`.
- Treat update operations separately from create operations; partial updates are allowed only when the provider contract supports them.

### License plates

- Normalize license plates consistently.
- Validate inputs strictly.
- Raise `ValidationError` for invalid or empty values after normalization.
- Never log full license plates when avoidable.

### IDs

- Treat provider IDs, permit IDs, reservation IDs, and favorite IDs as opaque strings.
- Do not make format assumptions unless strictly required by that provider internally.

### Balance

- Support generic balance reporting through:
  - `remaining_balance`
  - `balance_unit`
  - `balance_units`
- Restrict balance units to the supported generic set defined by the library.

## 12) Error handling

All public errors must be normalized through `src/pycityvisitorparking/exceptions.py`.

Current exception hierarchy includes at least:

- `PyCityVisitorParkingError`
- `AuthError`
- `NetworkError`
- `ValidationError`
- `ProviderError`
- `RateLimitError`
- `ServiceUnavailableError`
- `NotFoundError`
- `TimeoutError`
- `ConfigError`

### Rules

- Do not leak raw `aiohttp` exceptions through the public API.
- Prefer mapping network and provider failures to the library exception hierarchy.
- Preserve safe metadata when useful:
  - `error_code`
  - `detail`
- Keep exception messages technical and integration-facing, not end-user-facing.
- Do not rely on library exception text as user-facing copy.
- Keep exception messages free of credentials, tokens, and PII.

## 13) Logging and privacy

The library must be safe to use in Home Assistant environments with sensitive user data.

### Never log

- passwords
- tokens
- raw credentials
- full license plates
- raw provider payloads containing PII unless explicitly redacted

### Do log carefully

- provider id
- request context
- normalized error types
- safe runtime version information
- safe diagnostics helpful for debugging provider behavior

### Logging behavior

- avoid warning-level noise for expected retry paths
- avoid warning-level noise for expected reauthentication paths
- prefer debug logging for routine transport failures that the integration will recover from
- reserve warning and error logs for truly unexpected or actionable situations

Use the provider logger infrastructure instead of ad-hoc logging patterns.

## 14) Provider manifests

Each provider must include `manifest.json` in its provider folder.

Current manifest expectations include:

- `id`
- `name`
- `capabilities.favorite_update_fields`
- `capabilities.reservation_update_fields`
- optional `capabilities.balance_units`

### Rules

- Manifest `id` must match the provider folder name.
- Manifest values must be validated against the supported schema and allowed values.
- Discovery must read manifests via `importlib.resources`.
- Manifest loading must not require importing every provider module.
- Keep manifest loading and cache behavior in the loader layer.

## 15) Loader and cache behavior

Provider discovery currently uses a loader/cache layer.

Maintain these principles:

- manifest loading is centralized in `provider/loader.py`
- cache behavior is explicit and testable
- cache invalidation is available for tests
- async wrappers exist for blocking loader operations
- loader errors surface as normalized library errors

When changing loader behavior, update tests for:

- discovery
- cache hit/miss behavior
- refresh behavior
- schema validation
- provider lookup failures

## 16) Repository layout

Keep the repository aligned with the current layout:

- root docs:
  - `README.md`
  - `CHANGELOG.md`
  - `AGENTS.md`
  - `SECURITY.md`
  - `docs/RELEASING.md`
- source package:
  - `src/pycityvisitorparking/`
- provider root:
  - `src/pycityvisitorparking/provider/`
- provider-specific docs:
  - `README.md`
  - `CHANGELOG.md`
  - optional provider-specific `AGENTS.md`
- provider docs and templates:
  - `docs/provider-development/`
  - `docs/provider-template/`

Do not introduce alternate layouts without a strong reason.

## 17) Documentation policy

Use English as the primary project language.

Maintain these docs as part of the product surface:

- root `README.md`
- root `CHANGELOG.md`
- `docs/RELEASING.md`
- provider `README.md`
- provider `CHANGELOG.md`
- provider development docs and templates when provider authoring changes

Update docs whenever public behavior changes, especially for:

- new providers
- auth flow changes
- request parameter changes
- manifest changes
- public model changes
- exception behavior changes
- release flow changes
- Home Assistant integration boundary changes

## 18) Tooling and local workflow

### Branch workflow

- Treat `dev` as the default working branch for day-to-day changes and small fixes.
- Use a dedicated feature branch only for larger, clearly scoped change sets, especially when work spans multiple maintained surfaces such as library code, provider implementations, docs, packaging, or CI.
- Do not put partial, half-reviewed, or long-running multi-commit work directly on `dev` when isolated review would be safer or clearer.
- Keep feature branches focused on one clustered change set and do not use long-lived catch-all branches for unrelated work.
- Feature branches SHOULD use a conventional prefix such as `feat/`, `fix/`, `refactor/`, `docs/`, `ci/`, `deps/`, `test/`, or `tests/`.
- Do not add agent-related prefixes or suffixes such as `[codex]`, `[agent]`, or similar markers in branch names, commit titles, or pull request titles.
- Keep feature branches current with `dev` as needed, but do not rewrite shared history once review is in progress unless explicitly requested.
- After a feature branch is merged, delete it on GitHub and clean up the local branch as soon as it is no longer needed unless there is an explicit reason to keep it temporarily.

Use `uv` for local development commands.

Common commands:

- `uv run --group lint ruff check .`
- `uv run --group lint ruff format --check .`
- `uv run --group typecheck pyright`
- `uv run --group test pytest`
- `uv run --group schema python -m pytest -o addopts=-q tests/test_manifest_schema.py`
- `uv build`
- `uvx twine check dist/*`

### Build backend

The project uses:

- `hatchling` as the build backend
- `hatch-vcs` for version derivation from git tags

That does not change the local developer workflow rule: use `uv` for development tasks.

## 19) Commit and PR titles

Commits and pull requests must use the repository title convention.

Use a recognized conventional prefix such as:

- `feat:`
- `fix:`
- `docs:`
- `chore:`
- `refactor:`
- `perf:`
- `ci:`
- `deps:`
- `test:`
- `tests:`

Rules:

- every pull request title must use one of these prefixes
- commits should use the same title structure whenever practical
- do not add agent-related prefixes or suffixes such as `[codex]`, `[agent]`, or similar markers in commit titles or pull request titles
- keep titles concise and descriptive
- align the title with the actual change scope
- avoid vague titles such as `update stuff` or `fix issues`

This convention is required for CI labeling, release categorization, and changelog automation.

## 20) Versioning and releases

### Source of truth

The package version is derived from git tags through `hatch-vcs`.

Hard rules:

- do not manually edit a version string for releases
- use release tags matching `vX.Y.Z`
- keep changelogs aligned with the released version
- publish GitHub releases from the intended tag

### Release process

Before release:

- update docs and changelogs
- run local validation
- build artifacts
- run `twine check`

Release flow:

1. Commit the release changes.
2. Create an annotated tag `vX.Y.Z`.
3. Push the commit and tag.
4. Confirm CI passes for the tag.
5. Publish the GitHub release for that tag.
6. Let the release workflow publish to PyPI when package-shipping files changed.

Keep this aligned with `docs/RELEASING.md` and GitHub Actions workflows.

## 21) Testing policy

Tests must not call live municipal services.

Use mocked or stubbed behavior for:

- HTTP requests
- provider responses
- manifest loading
- loader cache behavior
- exceptions
- fallback behavior

Minimum expected coverage includes:

- client session ownership
- provider discovery
- lazy provider loading
- manifest schema validation
- time normalization
- license plate normalization
- exception mapping
- reservation validation
- favorites behavior
- fallback behavior
- provider-specific mapping tests where relevant
- integration-boundary regression risks when public fields or errors change

When changing shared behavior, update shared tests first.
When changing provider-specific behavior, update provider tests and provider docs together.

## 22) Adding or changing providers

A provider addition or major provider change must keep the repository consistent.

Expected updates usually include:

- provider implementation code
- `manifest.json`
- provider `README.md`
- provider `CHANGELOG.md`
- provider tests
- root docs when public behavior changes

If a provider has unique development or maintenance rules, add a provider-specific `AGENTS.md` in that provider folder.

## 23) Change discipline

When making changes:

- keep the public contract generic
- keep provider quirks local
- keep async and session ownership correct
- keep docs and tests in sync
- keep packaging and release behavior correct
- keep privacy guarantees intact
- keep the Home Assistant integration boundary clear

If a proposed change conflicts with those priorities, prefer the option that preserves a stable, provider-agnostic, Home Assistant-friendly library contract.
