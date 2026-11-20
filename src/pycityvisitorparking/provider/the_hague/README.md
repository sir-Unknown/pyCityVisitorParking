# The Hague

The Hague provider for visitor parking using the reverse engineered
Parkeren Den Haag API.

## Service name

- Official service name: Parkeren Den Haag (reverse engineered).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider
expects credentials with the following keys:

- `username` (string, required)
- `password` (string, required)
- `permit_media_type_id` (string, optional, sends `x-permit-media-type-id`)

Example credential shape:

```python
{
    "username": "user@example.com",
    "password": "secret",
    "permit_media_type_id": "1",
}
```

Recommended endpoints:

- `base_url`: `https://parkerendenhaag.denhaag.nl`
- `api_uri`: `api` (defaults to `/api` when omitted)

## Supported operations

- `login`
- `get_permit`
- `list_reservations`
- `start_reservation` (requires `start_time` and `end_time`)
- `update_reservation` (end time only)
- `end_reservation`
- `list_favorites`
- `add_favorite`
- `update_favorite`
- `remove_favorite`

## Migration notes

- Since v0.3.0, `Permit.remaining_time` is renamed to `Permit.remaining_balance`
  (minutes). Update integrations that read the permit balance.

## Mapping notes

- `Permit.id` uses `Account.id`.
- `Permit.remaining_balance` uses `Account.debit_minutes`.
- `Permit.paid_hours` is empty because the public API does not expose
  paid hours. When the account has no `zone_validity` list, the provider reads
  `zone.start_time`/`zone.end_time` as the paid hours if available and logs one
  debug line with the raw type/count and the fallback timestamps.
- If an undocumented `zone_validity` list is present, entries with `is_free`
  set to `true` are filtered out.
- Reservations map directly to `Reservation` fields.
- Favorites map directly to `Favorite` fields.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds.
Reservation inputs must be timezone-aware `datetime` values; naive inputs are
rejected.
Outbound reservation payloads use UTC ISO 8601 `Z` timestamps.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters.

## Limitations

- Reservation updates only support changing `end_time`.
- `end_reservation` uses the delete endpoint and returns the supplied
  `end_time` in the response model.
- 400 responses with PV error codes are mapped to readable `ProviderError`
  messages.
- A "start now" reservation is sent with the current time (D1); this is not
  verified against the live backend.

## Design decisions

These are deliberate choices, marked in the code with `DESIGN DECISION Dn`. If
one must change, change the code at the marked place, the tests named here, and
this section together, and add a line to `CHANGELOG.md`.

### D1: "Start now" starts at the current time

- **Behavior**: a `start_reservation` start in the past ("start now") is sent as
  the current time; a later start is sent unchanged.
- **Why**: the reservation should start when the user asks for it, without a
  lead. The official web app's start flow was not captured, so this is not
  verified against the live backend. If the API refuses the start it answers
  with `PV00074` (`pv74`, "Invalid start time"), which raises `ProviderError`
  with `error_code="provider_rejected"`: a rejection surfaces as a provider
  error, never silently.
- **Where**: `Provider.start_reservation` in `api.py`
  (`_start_not_before_now(..., whole_minute=False)`).
- **Tests**: `tests/test_the_hague_api.py::test_start_reservation_start_now_uses_the_current_time`.

## Links

No official public documentation is available for this reverse engineered API.
