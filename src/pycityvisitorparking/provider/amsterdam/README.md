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

The provider derives `client_product_id` automatically from the login token or
permit metadata; it should not be supplied manually.

Example credential shape:

```python
{
    "username": "user@example.com",
    "password": "secret",
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

- `Permit.id` uses the login `username` to keep Home Assistant entity identity stable
  across permit renewals; falls back to `client_product_id` when unavailable.
- `Permit.remaining_balance` uses `ssp.main_account.time_balance` when present
  (seconds), falling back to `money_balance` or `balance`.
- `Permit.zone_validity` uses the permit `validity.started_at`/`validity.ended_at`
  window when available. The API does not expose explicit paid/free windows, so
  the provider treats the validity window as chargeable.
- If a `zone_validity` list is present, entries with `is_free` set to `true`
  are filtered out.
- `start_reservation` requires `machine_number` or `zone_id`. The provider
  caches `ssp.favorite_machine_number` (or `permit.zone_id` when present) and
  raises a provider error if neither is available.
- Reservations map from `parking_session_id`, `vrn`, `started_at`, and `ended_at`.
- Favorites map from `favorite_vrn_id`, `vrn`, and `description`.

Mapping table (based on `amsterdam.json` sample):

- `login` (`/api/ssp/login_check`)
  - `response.token` -> auth header and JWT payload parsing for roles/client_product_id.
- `permit overview` (`/api/v1/permit_overview/product_list`)
  - `response.data[].id` or `response.data[].client_product_id` -> fallback source for `client_product_id`.
- `client_product` (`/api/v1/client_product/{client_product_id}`)
  - `username` (login credential) -> `Permit.id` for stable entity identity.
  - `client_product_id` -> fallback for `Permit.id` when `username` is unavailable.
  - `ssp.main_account.time_balance`/`money_balance` -> `Permit.remaining_balance`.
  - `validity.started_at`/`validity.ended_at` -> `Permit.zone_validity` fallback.
  - `ssp.favorite_machine_number` -> cached `machine_number` for `start_reservation`.
  - `permit.zone_id` (if present) -> cached `zone_id` for `start_reservation`.
- `parking_session list` (`/api/v1/ssp/parking_session/list`)
  - `parking_session_id` -> `Reservation.id`.
  - `vrn` -> `Reservation.license_plate`.
  - `started_at`/`ended_at` -> `Reservation.start_time`/`Reservation.end_time`.
  - `permit_name`/`zone_description` -> `Reservation.name` fallback.
- `favorite_vrn list` (`/api/v1/ssp/favorite_vrn/list`)
  - `id` -> `Favorite.id`.
  - `vrn` -> `Favorite.license_plate`.
  - `description` -> `Favorite.name`.
- `favorite_vrn add` (`/api/v1/ssp/favorite_vrn/add`)
  - `favorite_vrn_id` -> `Favorite.id` (if returned by the API).

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
