# DVS Portal

DVS Portal provider for visitor parking systems using the reverse engineered
DVS Portal API.

## Service name

- Official service name: DVS Portal (reverse engineered).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider expects
credentials with the following keys:

- `identifier` (string, required)
- `password` (string, required)
- `permit_media_type_id` (string, optional)

If `permit_media_type_id` is omitted, the provider selects the first entry from
`GET /login`.

Example credential shape:

```python
{
    "identifier": "user-123",
    "password": "secret",
    "permit_media_type_id": "1",
}
```

## Supported operations

- `login`
- `get_permit`
- `list_reservations`
- `start_reservation` (requires `start_time` and `end_time`)
- `end_reservation`
- `list_favorites`
- `add_favorite`
- `remove_favorite`

Unsupported:

- Reservation updates (`update_reservation`)
- Native favorite updates (`update_favorite` uses remove + add fallback)

## Mapping notes

- Permit selection uses the first `Permit`/`Permits[0]` and `PermitMedias[0]`.
- `Permit.id` uses `PermitMedias[0].Code` (fallback to `ZoneCode`).
- `Permit.remaining_time` uses `PermitMedias[0].Balance`.
- `Permit.zone_validity` includes only chargeable `BlockTimes` where
  `IsFree` is not `true`.
- Reservations come from `PermitMedias[0].ActiveReservations`.
- Favorites come from `PermitMedias[0].LicensePlates`.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds. When the API omits timezone offsets, timestamps are interpreted
as Europe/Amsterdam local time before conversion.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters.

## Limitations

- Only the first permit and permit media are used.
- Reservation updates are not supported.
- Favorite updates rely on the core remove + add fallback.

## Links

No official public documentation is available for this reverse engineered API.
