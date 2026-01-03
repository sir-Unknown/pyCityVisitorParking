# AGENTS.md — DVS Portal Provider Notes

This file supplements the shared provider guidance in
`src/pycityvisitorparking/provider/AGENTS.md`.

## Time handling

- Public reservation inputs must be timezone-aware `datetime` values.
- Outbound `reservation/create` payloads use Europe/Amsterdam local time with
  milliseconds and an explicit offset (`YYYY-MM-DDTHH:mm:ss.SSS±HH:MM`).
- Inbound timestamps with offsets are respected; without offsets they are
  interpreted as Europe/Amsterdam local time (fold=0) before converting to UTC.

## Behavior constraints

- Reservation updates are not supported.
- Favorite updates are not supported.
- Default `api_uri` is `/DVSWebAPI/api` when omitted.

## Favorite payloads

- Upsert expects `permitMediaTypeID`, `permitMediaCode`, `licensePlate` object, and `name`.
- Remove expects `permitMediaTypeID`, `permitMediaCode`, `licensePlate` string, and `name`.
