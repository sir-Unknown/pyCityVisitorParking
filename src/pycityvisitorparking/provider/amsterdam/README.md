# Amsterdam

Amsterdam provider for visitor parking using the reverse engineered
Parkeervergunningen Amsterdam (EGIS Parking Services) API.

## Service name

- Official service name: Parkeervergunningen Amsterdam (EGIS Parking Services).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider
expects credentials with the following keys:

- `username` (string, required)
- `password` (string, required)
- `client_product_id` (string, optional, parsed from the JWT when omitted)

Example credential shape:

```python
{
    "username": "user@example.com",
    "password": "secret",
    "client_product_id": "12345",
}
```

Recommended endpoints:

- `base_url`: `https://api.parkeervergunningen.egisparkingservices.nl`
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
- `remove_favorite`

## Mapping notes

- `Permit.id` uses `client_product_id` from the permit response or token.
- `Permit.remaining_balance` uses `ssp.main_account.time_balance` when present
  (seconds), falling back to `money_balance` or `balance`.
- `Permit.zone_validity` uses the permit `validity.started_at`/`validity.ended_at`
  window when available. The API does not expose explicit paid/free windows, so
  the provider treats the validity window as chargeable.
- If a `zone_validity` list is present, entries with `is_free` set to `true`
  are filtered out.
- Reservations map from `parking_session_id`, `vrn`, `started_at`, and `ended_at`.
- Favorites map from `favorite_vrn_id`, `vrn`, and `description`.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds. Reservation inputs must be timezone-aware `datetime` values;
naive inputs are rejected.

Outbound reservation payloads use RFC 1123 (`... GMT`) timestamps for
`start_reservation` and ISO 8601 with `+00:00` offsets for reservation updates,
matching the portal behavior.

If the API returns timestamps without offsets, the provider assumes they are in
Europe/Amsterdam local time and normalizes them to UTC.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters.

## Limitations

- Reservation updates only support changing `end_time`.
- Favorite updates are not supported.

## Links

No official public documentation is available for this reverse engineered API.
