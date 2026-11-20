# Amsterdam

Amsterdam provider for visitor parking using the reverse engineered
Parkeervergunningen Amsterdam (EGIS Parking Services) API.

## Service name

- Official service name: Parkeervergunningen Amsterdam (EGIS Parking Services).

## Configuration

Home Assistant supplies `base_url` and optional `api_uri`. This provider
expects credentials with the following keys:

- `username` (string, required): the portal's *meldcode*.
- `password` (string, required): the portal's *pincode* (4 digits).
- `machine_number` (string, optional): see [Parking machine](#parking-machine).

The credentials are the ones used on the portal's "Inloggen met meld- en pincode"
page (`/login-ssp`); the provider logs in through the same `/ssp/login_check`
endpoint. The meldcode and pincode are shown on the permit page after logging in
with DigiD or eHerkenning. DigiD and eHerkenning logins themselves are not
supported.

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

## Parking machine

Permits whose configuration has `config.can_select_zone` set start a session
for a parking machine number, which determines the zone, tariff and paid
parking hours. By default the provider uses the permit's default machine
(`ssp.favorite_machine_number`). Like the portal, the provider sends no machine
for permits without `can_select_zone`. If a permit has `can_select_zone` but no
default machine, starting a session raises `ProviderError` until
`machine_number` is supplied.

Pass `machine_number` at login to use another machine instead, for example
`--extra machine_number=1234` with the live check script. The provider resolves
its zone through `paid_parking_zone/get_by_machine_number` and sends both
`machine_number` and `zone_id` when starting a session; it never marks the
machine as the new default. Paid parking windows reported in `paid_hours`
use the selected machine as well. The override is kept across automatic
re-authentication and is sent even when the permit lacks `can_select_zone`.

A machine that does not exist or lies outside the permit's allowed zones raises
`ValidationError` at login.

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
- `Permit.remaining_balance` uses `ssp.main_account.time_balance` (seconds,
  reported in whole minutes with `balance_unit=MINUTE`) when present, otherwise
  `money_balance` (cents, reported in euros with `balance_unit=EURO`). A
  balance of `0` counts as present, as in the portal.
- `Permit.paid_hours` comes from the `time_frame_data` of one
  `parking_session/cost_calculator` call for today. `time_frame_data` is a
  weekly schedule (index 0 is Monday, an empty day is free) and is repeated
  over today and the next 14 days. Whether public holidays deviate from this
  schedule is unknown. If the calculation fails, `paid_hours` is empty.
- `start_reservation` sends the parking machine fields described in
  [Parking machine](#parking-machine).
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
  - `ssp.main_account.time_balance`/`money_balance` -> `Permit.remaining_balance` and `Permit.balance_unit`.
  - `config.can_select_zone` -> whether a parking machine is sent.
  - `ssp.favorite_machine_number` -> cached `machine_number` for `start_reservation`.
  - `permit.zone_id` (if present) -> cached `zone_id` for `start_reservation`.
- `parking_session cost_calculator` (`/api/v1/ssp/parking_session/cost_calculator`)
  - `time_frame_data[weekday][].startTime`/`endTime` (`HHmm`, Europe/Amsterdam) -> `Permit.paid_hours`.
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

## Errors

- A rejected request that carries a provider message (HTTP 400) raises
  `ProviderError` with `error_code=provider_rejected`; `detail` contains the
  upstream message. Known messages when starting a session are
  `Client time balance is insufficient.`, `Client money balance is
  insufficient.` and `Time slot is overbooked.`.
- `NPR is unavailable.` (the national parking register is down) raises
  `ServiceUnavailableError`.
- Rejected credentials raise `AuthError`.
- An unknown `machine_number`, or one outside the permit's zones, raises
  `ValidationError`.
- Reservation updates other than `end_time`, and favorite updates, raise
  `ProviderError` with `error_code=not_supported`.

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

- Sessions for visitor accounts (`ROLE_VISITOR_SSP`, created by a permit holder
  for their visitors) are paid by the visitor through iDEAL. The provider sends
  `brand: IDEAL` for these accounts, but it cannot complete the payment, so the
  session is not guaranteed to become active. This path is untested.

- Reservation updates only support changing `end_time`.
- Favorite updates are not supported.

## Links

No official public documentation is available for this reverse engineered API.
