# Changelog

## Unreleased

- Map permit zone validity from `zone` when `zone_validity` is missing.

## 0.5.3

- Move manifest update flags into `capabilities` with field lists.

## 0.5.2

- Add `reservation_update_possible` to the provider manifest.

## 0.5.1

- Map PV error codes to readable `ProviderError` messages.
- Drop legacy `permitMediaTypeId` credential alias (use `permit_media_type_id`).
- Remove `zone` fallback when `zone_validity` is empty.
- Require timezone-aware `datetime` values for reservation inputs.

## 0.4.1

- Default `api_uri` to `/api` when omitted.

## 0.4.0

- Require `username` for login (no legacy identifier alias).
- Use `zone.start_time`/`zone.end_time` when `zone_validity` is empty.

## 0.2.0

- Initial The Hague provider implementation.
