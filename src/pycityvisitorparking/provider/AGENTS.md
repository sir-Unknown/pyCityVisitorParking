# AGENTS.md — Provider Authoring Guide (pyCityVisitorParking)

✅ **Limit the PR to the provider folder only**
- Add a provider by adding files only under:
  `src/pycityvisitorparking/provider/<provider_id>/...`
- ❌ Avoid modifying core code, models, loader, or shared tests for a provider PR.

✅ **Use English as the primary project language**
- Write all documentation, comments, docstrings, commit messages, and changelogs in English.
- Use Dutch only when quoting provider UI text or official municipality wording, and label it clearly.

✅ **Create the required provider structure**
- Create `src/pycityvisitorparking/provider/<provider_id>/`.
- Add these required files:
  - `manifest.json`
  - `__init__.py`
  - `api.py`
  - `const.py`
  - `README.md`
  - `CHANGELOG.md`
- Add provider-specific tests and fixtures inside the provider folder when possible.

✅ **Maintain provider documentation and changelog**
- Write `README.md` inside the provider folder and include:
  - provider description and official service name
  - required login keys and example credential shapes
  - supported operations and known limitations
  - mapping notes for `zone_validity` and time handling
  - links to official provider documentation where available
- Write `CHANGELOG.md` inside the provider folder.
- Keep an “Unreleased” section in the provider changelog.
- Update provider `CHANGELOG.md` whenever endpoints, auth flow, mapping behavior, or limitations change.

✅ **Verify documentation and pinned versions and correct assumptions**
- Check the current project documentation and the versions pinned in our lockfiles and CI.
- Update any assumptions immediately when documentation, lockfiles, and CI disagree.
- Align any provider docs, examples, and test expectations with the pinned versions.
- Avoid “latest” installs in CI and keep dev tooling versions pinned.

✅ **Require docstrings and clear comments**
- Add docstrings for all public modules, classes, and methods.
- Add clear inline comments for non-obvious logic (e.g., time/UTC conversion, normalization, fallback behavior).
- Keep comments/docstrings free of credentials, tokens, or other PII.

✅ **Create a valid provider manifest**
- Create `manifest.json` and include:
  - `id` and match it exactly to the folder name
  - `name`
  - `favorite_update_possible`
- Validate `manifest.json` against:
  `src/pycityvisitorparking/provider/manifest.schema.json`
- ❌ Avoid imports or side effects when defining the manifest.
* Use integration-provided `base_url` and `api_uri` to build request URLs.
* ❌ Do not embed municipality base URLs in provider code or manifests.

✅ **Export the Provider class without side effects**
- Export a class named `Provider` from `<provider_id>/__init__.py`.
- Implement `pycityvisitorparking.provider.base.BaseProvider`.
- ❌ Avoid network calls, file writes, or heavy work at import time.

✅ **Map strictly to public dataclasses**
- Map provider responses only into strict public dataclasses:
  - `ProviderInfo`
  - `Permit`
  - `ZoneValidityBlock`
  - `Reservation`
  - `Favorite`
- ❌ Avoid adding provider-specific fields to public models.

✅ **Normalize license plates (mandatory)**
- Normalize every plate to uppercase `A–Z0–9`.
- Remove spaces and special characters.
- Raise `ValidationError` for invalid or empty plates after normalization.

✅ **Convert all timestamps to UTC**
- Convert all provider timestamps to UTC before returning them.
- Format all public timestamps as ISO 8601 with `Z` and without microseconds.
- Ensure every returned timestamp is parseable as a timezone-aware UTC datetime.

✅ **Filter zone_validity to chargeable windows**
- Build `Permit.zone_validity` using only chargeable windows.
- Filter out free windows.
- Include windows only when reservation is required/chargeable.

✅ **Implement login and auth safely**
- Accept credentials via `Mapping[str, str]` or `**kwargs`.
- Validate required keys and raise `ValidationError` when missing.
- Raise `AuthError` for invalid credentials or expired sessions.
- ❌ Avoid logging credentials or tokens.

✅ **Use aiohttp and map errors safely**
- Use the injected `aiohttp.ClientSession`.
- Enforce timeouts and keep TLS verification enabled.
- Translate errors into library exceptions.
- ❌ Avoid leaking raw `aiohttp` exceptions.
- Use relative paths and build requests from `base_url + api_uri`.

✅ **Respect favorite update behavior**
- Set `favorite_update_possible` to `true` only when native update is supported.
- Set `favorite_update_possible` to `false` when native update is not supported.
- Rely on core fallback behavior (remove+add) when update is not supported.

✅ **Enforce reservation rules**
- Require `end_time` for `start_reservation` and ❌ avoid defaults.
- Enforce `end_time > start_time` and raise `ValidationError` when violated.

✅ **Add tests without live calls**
- ❌ Avoid live services.
- Use fixtures and mocks.
- Add tests that verify:
  - license plate normalization
  - UTC conversion from an offset timestamp
  - `zone_validity` filtering to chargeable windows
  - mapping into strict public dataclasses

✅ **Make provider changes release-ready**
- Update provider `CHANGELOG.md` when provider behavior changes.
- Keep provider `README.md` accurate for required login keys and limitations.
- ❌ Avoid adding new runtime dependencies without maintainer approval.

✅ **Run the checklist before opening a PR**
- Confirm adding files only under `provider/<provider_id>/`.
- Confirm `manifest.json` validates against the schema.
- Confirm `Provider` exports and ❌ avoid network calls on import.
- Confirm UTC ISO 8601 `Z` timestamps in all public outputs.
- Confirm license plate normalization and validation.
- Confirm chargeable-only `zone_validity`.
- Confirm `end_time` required and `end_time > start_time`.
- Confirm provider `README.md` and `CHANGELOG.md` exist and are updated.
- Confirm `pytest` passes.
