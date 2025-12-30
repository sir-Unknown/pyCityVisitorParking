# CHANGELOG

## Unreleased

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
