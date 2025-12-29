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
- `api_uri`: `api`

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
- `Permit.zone_validity` is empty because the public API does not expose
  chargeable windows. If an undocumented `zone_validity` list is present,
  entries with `is_free` set to `true` are filtered out.
- Reservations map directly to `Reservation` fields.
- Favorites map directly to `Favorite` fields.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters.

## Limitations

- Reservation updates only support changing `end_time`.
- `end_reservation` uses the delete endpoint and returns the supplied
  `end_time` in the response model.

## Links

No official public documentation is available for this reverse engineered API.
