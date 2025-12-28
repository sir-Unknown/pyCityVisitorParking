# AGENT.md — Development Guide (pyCityVisitorParking)

✅ **Build an async Home Assistant–friendly API library (Python 3.13)**
- Build an async Python library that standardizes Dutch municipal “visitor parking” operations for Home Assistant.
- Target Python 3.13 and set `requires-python = ">=3.13"`.

✅ **Use English as the primary project language**
- Write all documentation, comments, docstrings, commit messages, and changelogs in English.
- Use Dutch only when quoting provider UI text or official municipality wording, and label it clearly.

✅ **Maintain root documentation and changelog**
- Maintain root `README.md`.
- Maintain root `CHANGELOG.md`.
- Keep an “Unreleased” section and move entries into a versioned section on release.
- Update root `CHANGELOG.md` on every release.

✅ **Require docstrings and clear comments**
- Add docstrings for all public modules, classes, and methods.
- Add clear inline comments for non-obvious logic (e.g., time/UTC conversion, normalization, fallback behavior).
- Keep comments/docstrings free of credentials, tokens, or other PII.

✅ **Enforce project rules without exceptions**
- Use an async-only public API.
- Use `aiohttp` for all HTTP communication.
- ❌ Avoid third-party provider plugins.
- ❌ Avoid entry points.
- Keep providers inside `src/pycityvisitorparking/provider/<provider_id>/`.
- Allow adding a provider by changing only `provider/<provider_id>/...`.
- Discover providers without importing provider code.
- Keep public models strict and ❌ avoid provider-specific fields.

✅ **Use the required repository layout**
- Use `src/` layout.
- Keep core code in `src/pycityvisitorparking/`.
- Keep provider code in `src/pycityvisitorparking/provider/<provider_id>/`.
- Keep `manifest.schema.json` in `src/pycityvisitorparking/provider/`.
- Keep root `README.md` and `CHANGELOG.md` at repository root.
- Keep per-provider `README.md` and `CHANGELOG.md` inside each provider folder.

✅ **Implement the public Client facade**
- Expose `Client` in `client.py`.
- Implement `list_providers()` by reading manifests without importing provider modules.
- Implement `get_provider(provider_id, ...)` by importing only the selected provider on-demand.
- Support injecting an `aiohttp.ClientSession`.
- ❌ Avoid closing an injected session.
- Create an internal session only when not injected.
- Provide `async with Client(...)` and/or `await client.aclose()` for internal cleanup.
* Take `base_url` and `api_uri` as config inputs and pass them into providers.
* ❌ Avoid hardcoded endpoints; keep only relative paths/constants.

✅ **Define and enforce the provider interface**
- Define `BaseProvider` in `provider/base.py`.
- Require providers to implement standardized async methods for login, permit, reservations, and favorites.
- Implement core fallback behavior for `update_favorite` when native update is not supported.

✅ **Standardize time, license plates, and zone_validity**
- Return public timestamps as UTC ISO 8601 with `Z` and without microseconds.
- Convert provider-local/offset timestamps to UTC internally.
- Normalize license plates to uppercase `A–Z0–9` and remove spaces/special chars.
- Raise `ValidationError` for invalid or empty plates after normalization.
- Filter `zone_validity` to include only chargeable windows and filter out free windows.

✅ **Keep public dataclasses strict**
- Define public dataclasses only in `models.py`.
- Expose only:
  - `ProviderInfo`
  - `Permit`
  - `ZoneValidityBlock`
  - `Reservation`
  - `Favorite`
- ❌ Avoid adding provider-specific metadata to public models.

✅ **Enforce validation rules**
- Require `start_time` and `end_time` for `start_reservation` and ❌ avoid defaults.
- Enforce `end_time > start_time` and raise `ValidationError` when violated.
- Treat IDs as opaque strings and ❌ avoid format assumptions.
- Ensure timestamps are parseable as timezone-aware UTC datetimes.

✅ **Use secure HTTP standards**
- Enable TLS verification.
- Enforce request timeouts.
- Map HTTP and provider errors to custom exceptions.
- ❌ Avoid leaking raw `aiohttp` exceptions into the public API.
- Apply retries only to idempotent GET requests and keep defaults conservative or disabled.

✅ **Implement controlled errors and safe logging**
- Define exceptions in `exceptions.py`.
- Provide at minimum: `AuthError`, `NetworkError`, `ValidationError`, `ProviderError`.
- ❌ Avoid including credentials, tokens, or PII in logs or exception messages.
- Mask license plates in logs when logging is necessary.

✅ **Implement provider discovery via manifests without imports**
- Require each provider to include `manifest.json` with `id`, `name`, and `favorite_update_possible`.
- Read manifests using `importlib.resources` without importing provider modules.
- Import provider modules only when selected by `get_provider()`.

✅ **Validate manifests via schema and fail CI on errors**
- Add `manifest.schema.json` in `src/pycityvisitorparking/provider/`.
- Validate every provider `manifest.json` against the schema.
- Add a test that validates all manifests and fail CI on schema errors.

✅ **Test without live calls**
- ❌ Avoid live municipal services in tests.
- Use fixtures and mocked HTTP responses.
- Add tests for normalization, UTC conversion, loader discovery, schema validation, and fallback behaviors.

✅ **Use Hatch for development, build, and publishing**
- Use Hatch as the single entrypoint for dev workflows.
- Run lint and format using Hatch environments.
- Run tests using Hatch environments.
- Build artifacts using `hatch build`.
- Validate artifacts using `python -m twine check dist/*`.

✅ **Verify documentation and pinned versions and correct assumptions**
- Check the current project documentation and the versions pinned in our lockfiles and CI.
- Update any assumptions immediately when documentation, lockfiles, and CI disagree.
- Align `requires-python`, Hatch environments, and CI matrices to the pinned versions.
- Prefer the repository as the source of truth for supported versions and tooling.
- Avoid “latest” installs in CI and keep dev tooling versions pinned.

✅ **Publish releases to PyPI in a controlled way (Hatch)**
- Bump versions using `hatch version <new>` or `hatch version <major|minor|patch>`.
- Update root `CHANGELOG.md` and move “Unreleased” entries into the new version section.
- Create a git tag `vX.Y.Z` and push it.
- Publish from CI on tags using trusted publishing (OIDC) when possible.
- ❌ Avoid manual local publishing when CI publish is available.
- Verify release contents include manifests, schema, and provider docs in `sdist`.

✅ **Apply release rules**
- Use SemVer and keep root `CHANGELOG.md` updated.
- Bump MINOR for provider additions.
- Bump PATCH for bug fixes.
- Tag releases and maintain a clear changelog history.
