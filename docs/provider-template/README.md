# Provider Template

This folder contains a template for adding a new provider. It is not part of the
runtime package and is ignored by discovery.

## How to use

1. Copy this folder to `src/pycityvisitorparking/provider/<provider_id>/`.
2. Update `manifest.json` so `id` matches the folder name and set a display name.
3. Implement the async methods in `api.py`.
4. Update the provider `README.md` and `CHANGELOG.md`.

## Required files

- `manifest.json`
- `__init__.py`
- `api.py`
- `const.py`
- `README.md`
- `CHANGELOG.md`

## Key rules

- Do not perform network calls at import time.
- Use the injected `aiohttp.ClientSession` from `BaseProvider`.
- Use relative paths and join them with `base_url + api_uri` via
  `_request_json()` / `_request_text()` or `_build_url()`.
- Normalize license plates and enforce UTC ISO 8601 `Z` timestamps.
- Filter `zone_validity` to chargeable windows only.
- Raise library exceptions (`AuthError`, `NetworkError`, `ValidationError`, `ProviderError`).
