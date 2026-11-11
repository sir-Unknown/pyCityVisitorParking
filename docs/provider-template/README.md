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
- Normalize license plates and enforce UTC ISO 8601 `Z` timestamps (second
  precision). Accept only timezone-aware `datetime` values for reservation
  inputs and reject naive timestamps.
- Require `start_time` and `end_time` for `start_reservation` and enforce
  `end_time > start_time`.
- Filter `zone_validity` to chargeable windows only.
- Raise library exceptions (`AuthError`, `NetworkError`, `ValidationError`, `ProviderError`).
  Use `raise_for_failed_status()` from `provider/base.py` for HTTP status mapping and
  set a specific `ErrorCode` where one applies (`not_supported`, `provider_rejected`).
- Keep provider-resolved login state (location, media type, tokens) internal and
  reuse it on reauthentication; do not expose it through the public API.
- If favorite updates are unsupported, set `capabilities.favorite_update_fields`
  to `[]` and ensure `update_favorite()` raises `ProviderError` with
  `error_code=ErrorCode.NOT_SUPPORTED`.
- If reservation updates are unsupported, set `capabilities.reservation_update_fields`
  to `[]` and ensure `update_reservation()` raises `ProviderError` with
  `error_code=ErrorCode.NOT_SUPPORTED`.
- Call `_validate_zone_id(zone_id)` first in `start_reservation()`. Only set
  `capabilities.zone_selection` to `true` when the provider fills `Permit.zones`
  and books in the chosen zone (see the provider development README).

## Testing

- Avoid live services; use mocked aiohttp responses.
- Cover request/response flows and error mapping (auth, non-2xx, invalid JSON).
