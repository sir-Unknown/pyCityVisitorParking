# DVS Portal (Refactored)

Refactored DVS Portal provider for visitor parking systems using the reverse
engineered DVS Portal API.

## Service name

- Official service name: DVS Portal (reverse engineered).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider expects
credentials with the following keys:

- `username` (string, required)
- `password` (string, required)
- `permit_media_type_id` (string, optional)

If `api_uri` is omitted, the provider defaults to `/DVSWebAPI/api`.
If `permit_media_type_id` is omitted, the provider selects the first entry from
`GET /login`.

Example credential shape:

```python
{
    "username": "user-123",
    "password": "secret",
    "permit_media_type_id": "1",
}
```

## Supported operations

- `login`
- `get_permit`
- `list_reservations`
- `start_reservation` (requires `start_time` and `end_time`)
- `update_reservation` (end time only)
- `end_reservation`
- `list_favorites`
- `add_favorite`
- `remove_favorite`

Unsupported:

- Favorite updates (`update_favorite`)

## Architecture notes

This provider keeps the public behavior of `dvsportal`, but splits the internal
implementation into smaller modules:

- `api.py`: public provider facade
- `session.py`: auth and runtime state
- `profile.py`: variant-specific auth/request behavior
- `transport.py`: HTTP, auth headers, reauth, and XSRF support
- `mapping.py`: permit, reservation, favorite, and timestamp mapping

## Mapping notes

- Permit selection prefers the cached permit media code when multiple permits or
  permit media entries are present.
- `Permit.id` uses the selected permit media `Code` and falls back to `ZoneCode`.
- `Permit.remaining_balance` uses the selected permit media `Balance`.
- `Permit.zone_validity` includes only chargeable `BlockTimes` where `IsFree`
  is not `true`.
- Reservations come from `PermitMedias[*].ActiveReservations`.
- Favorites come from `PermitMedias[*].LicensePlates`.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds. When the API omits timezone offsets, timestamps are interpreted
as Europe/Amsterdam local time before conversion. DST transitions are resolved
deterministically using `fold=0` for ambiguous or non-existent local times.

Reservation creation payloads must use Europe/Amsterdam local time with
milliseconds and an explicit offset (for example,
`2026-01-02T23:57:00.000+01:00`); the public API accepts timezone-aware
`datetime` values and returns UTC strings.

## Auth and request handling

- The provider supports token-based auth and cookie/session-based auth.
- When an auth token is present, the provider sends the `Authorization` header.
- When an XSRF cookie is present, the provider also sends `X-XSRF-TOKEN`.
- Mutating calls that do not include permit data trigger a fallback refresh via
  `POST /login/getbase`.

## Limitations

- Reservation updates can adjust the end time only.
- Favorite updates are not supported.
- `login/info`, `upgrade`, and history endpoints are not implemented in this
  provider variant.

## Links

No official public documentation is available for this reverse engineered API.
