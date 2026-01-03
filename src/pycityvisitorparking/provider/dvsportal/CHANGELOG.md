# Changelog

## Unreleased

## 0.5.0

- Require timezone-aware `datetime` values for reservation inputs.
- Send reservation creation timestamps in Europe/Amsterdam local time with
  offsets and milliseconds.

## 0.4.0

- Require `username` for login (no legacy identifier alias).
- Default `api_uri` to `/DVSWebAPI/api` when omitted.

## 0.2.0

- Initial DVS Portal provider implementation.
