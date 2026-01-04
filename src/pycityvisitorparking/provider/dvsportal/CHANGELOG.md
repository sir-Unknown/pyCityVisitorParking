# Changelog

## Unreleased

## 0.5.3

- Move manifest update flags into `capabilities` with field lists.
- Add reservation updates via `reservation/update` with minute-delta conversion.

## 0.5.2

- Add `reservation_update_possible` to the provider manifest.

## 0.5.1

- Fix favorite upsert/remove payloads and accept `Permits[0]` when `Permit` is omitted.
- `update_favorite()` now raises `ProviderError` (unsupported).
- Drop legacy `permitMediaTypeID` credential alias (use `permit_media_type_id`).
- Remove reservation selection fallback.
- Require timezone-aware `datetime` values for reservation inputs.
- Send reservation creation timestamps in Europe/Amsterdam local time with
  offsets and milliseconds.

## 0.4.0

- Require `username` for login (no legacy identifier alias).
- Default `api_uri` to `/DVSWebAPI/api` when omitted.

## 0.2.0

- Initial DVS Portal provider implementation.
