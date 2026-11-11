# Rotterdam

> [!WARNING]
> **Not yet tested with a real permit.** This provider was developed without
> access to an account that holds a permit. Login and saved license plates
> (favorites) were verified against the live portal. Permit, balance, zone
> validity, and every successful reservation action (start, update, end, cancel)
> are based on the portal's published data model and are only covered by tests
> with mocked portal responses. See "Verification status" below.

Rotterdam provider for visitor parking using the reverse engineered visitor
parking portal of the municipality of Rotterdam.

## Service name

- Official service name: the Rotterdam visitor parking portal at
  `bezoek.rotterdam.nl` (reverse engineered). The portal is a Mendix
  application; all data access goes through its runtime endpoint (`/xas/`).

## Configuration

Home Assistant supplies `base_url`. No `api_uri` is used. This provider expects
credentials with the following keys:

- `username` (string, required): the e-mail address of the portal account
- `password` (string, required)

Example credential shape:

```python
{
    "username": "user@example.com",
    "password": "secret",
}
```

Recommended endpoint:

- `base_url`: `https://bezoek.rotterdam.nl`

The portal authenticates with session cookies, so the injected
`aiohttp.ClientSession` must keep cookies (the default `aiohttp.CookieJar`).
A session with a dummy cookie jar cannot sign in.

## Supported operations

- `login`
- `get_permit`
- `list_reservations`
- `start_reservation` (requires `start_time` and `end_time`)
- `update_reservation` (`start_time` of a planned reservation, `end_time`)
- `end_reservation`
- `list_favorites`
- `add_favorite`
- `update_favorite` (`license_plate` and `name`)
- `remove_favorite`

## Mapping notes

- `Permit.id` is the id of the account's authorization for the permit.
- Only authorizations that are active, not removed by the user, and not revoked
  are considered. When an account has several, the first one ordered by
  description and id is used (see Limitations).
- `Permit.remaining_balance` is the current balance in minutes
  (`balance_unit` is `MINUTE`). The portal stores balances in units; the length
  of a unit is read from the portal's published configuration (10 minutes at the
  time of writing). Business-hours permits carry a balance per calendar month,
  other permits per year (Europe/Amsterdam). A missing balance row is reported
  as `0`.
- `Permit.zone_validity` contains the upcoming parking-time windows stored for
  the permit's zones. Every stored window is a chargeable window, so no free
  windows exist to filter out. Duplicate windows are merged.
- Reservations map to the permit's parking actions that are not cancelled and
  have not ended yet. Parking actions started by other users of the same permit
  are included. `Reservation.name` is the plate description, falling back to
  the plate.
- Favorites map to the account's saved license plates. The portal's "default
  plate" flag is preserved on update but never set by this library.

## Reservation behavior

- `start_reservation` uses the permit's only zone. A permit that covers several
  zones is refused with `ProviderError`, because the generic contract has no
  zone choice and a guess could park in the wrong zone.
- The portal works with minutes: seconds are dropped from start and end times,
  and a start in the past starts the reservation in the current minute.
- Like the portal's own client, the provider prices the parking action before
  saving it. The portal enforces its own limits (planning horizon, balance,
  permit validity); a rejection is raised as `ProviderError` with
  `error_code="provider_rejected"` and the portal's English message in `detail`
  (license plates are masked).
- `update_reservation` cannot change the start of a reservation that already
  started, and cannot change the name.
- `end_reservation` stops a running reservation at the later of `end_time` and
  the current time. A reservation that has not started yet is cancelled; the
  returned reservation is then the one as it was before cancelling.

## Time handling

Provider timestamps are converted to UTC and returned as ISO 8601 with `Z` and
no microseconds.
Reservation inputs must be timezone-aware `datetime` values; naive inputs are
rejected.

## License plate normalization

License plates are normalized to uppercase `A-Z0-9` without spaces or special
characters. The portal distinguishes Dutch plates (exactly six characters) from
foreign plates (up to ten characters); plates longer than ten characters are
rejected with `ValidationError`.

## How the provider talks to the portal

- Reads use the runtime's XPath retrieval on entity names, which are part of the
  portal's published data model.
- Writes call microflows. The runtime addresses microflows by opaque operation
  ids that are only published inside the portal's page definitions
  (`/pages/nl_NL/...`). The provider therefore resolves each id at runtime from
  the nanoflow that calls the microflow (by nanoflow name and parameter names)
  instead of hardcoding it, and refuses to guess when the match is ambiguous.
- Request bodies are sent pre-serialized so the shared request logger never sees
  license plates or credentials.

## Verification status

Login, saved plates (add, update, remove, list), operation resolution, the
rejection path of a parking action, and session renewal were verified against
the live portal. The development account had no permit, so permit data, zone
validity, and the successful parking-action path (start, update, end, cancel)
were implemented from the portal's published data model and client definitions
and are covered by tests with mocked portal responses only. Please report
differences seen on accounts that hold a permit.

## Design decisions

These are deliberate choices, not accidents. Each one is marked in the code with
`DESIGN DECISION Dn`. If one of them must change later, change the code at the
marked place, the tests named here, and this section together, and add a line to
`CHANGELOG.md` (a behavior change is visible to integrations).

### D1: A permit with several zones cannot start a reservation

- **Behavior**: `start_reservation` raises `ProviderError("The permit covers
  multiple zones; zone selection is not supported.")` when the permit has more
  than one zone. A permit without zones also raises `ProviderError`.
- **Why**: the generic public contract has no zone parameter, and the portal
  requires a zone for every parking action. Silently taking the first zone could
  let a visitor park in a zone the visitor did not choose.
- **Where**: `Provider._single_zone_name` in `api.py`.
- **Tests**: `test_start_reservation_refuses_ambiguous_zone`.
- **If this changes**: either pick a zone by a documented rule (for example the
  first by name), or add a generic zone concept to the public contract first
  (repository `AGENTS.md`: no provider-specific fields on public models).

### D2: With several usable permits the first one is used

- **Behavior**: `get_permit`, `list_reservations`, `fetch_all`, and
  `start_reservation` all act on one permit: the first usable authorization
  (active, not removed by the user, not revoked) ordered by its description and
  then its id. No error is raised when more exist.
- **Why**: the public contract returns a single `Permit`. The order is stable, so
  every operation of one account uses the same permit.
- **Where**: `Provider._load_authorizations` (ordering) and
  `Provider._select_authorization` (choice) in `api.py`.
- **Tests**: no test pins the ordering of several permits.
- **If this changes**: add a way to choose the permit (for example a login
  keyword, which would then have to be a generic concept), or return one `Permit`
  per authorization. Note that `update_reservation` and `end_reservation` already
  look up the permit a reservation belongs to (`Provider._authorization_for`)
  and do not depend on this choice.

### D3: Microflow operation ids are resolved at runtime

- **Behavior**: ids of the microflows used for writes are never hardcoded. They
  are read from the portal's page definitions, from the nanoflow that calls the
  microflow (matched on nanoflow name and the exact set of parameter names). An
  ambiguous or missing match raises `ProviderError("Provider operation could not
  be resolved.")`; the provider never guesses.
- **Why**: the ids are opaque and only published inside page definitions, so a
  hardcoded id may break silently when the portal is redeployed.
- **Where**: `OPERATIONS` in `const.py`, `find_operation_id` in `mendix.py`, and
  `Provider._operation_id` in `api.py`. Ids and page definitions are cached per
  provider instance.
- **Tests**: `test_find_operation_id_requires_an_unambiguous_parameter_match`,
  `test_unresolvable_operation_raises_provider_error`.
- **If this changes**: hardcoding ids is only a fallback worth adding if page
  definitions turn out to be unavailable; it would need a way to detect stale
  ids. When the portal renames a nanoflow or changes its parameters, update the
  matching `OperationSpec` in `const.py`.

### D4: Minute resolution, and a running reservation keeps its start

- **Behavior**:
  - Seconds are dropped from start and end times sent to the portal (the portal
    only works with minutes), so an end time can end up up to 59 seconds earlier
    than requested.
  - On `start_reservation` and on `update_reservation` of a planned reservation,
    a start in the past becomes the current minute ("start now").
  - `update_reservation` of a reservation that already started never sends a new
    start: the stored start is kept as it is, and a different `start_time` raises
    `ValidationError`. A start that differs only in seconds is accepted.
  - `end_reservation` stops a running reservation at the later of `end_time` and
    the current time (never in the past) and does not drop seconds.
- **Why**: the portal's own client trims to minutes and refuses starts in the
  past, and for a parking action that is already running it only offers
  changing the end (whether the server would reject a new start was not tried).
- **Where**: `Provider._reservation_window`, `Provider.update_reservation`, and
  `Provider.end_reservation` in `api.py`.
- **Tests**: `test_start_reservation_prices_then_saves_like_the_web_client`,
  `test_update_reservation_cannot_move_the_start_of_a_running_reservation`,
  `test_update_reservation_extends_the_end_and_rereads`,
  `test_end_reservation_stops_a_running_reservation_at_the_current_time`.
- **If this changes**: rounding the end up instead of down means changing
  `_reservation_window` (the end is then billed longer, not shorter than
  requested). Letting a running reservation change its start is only possible if
  the portal accepts it; this has not been tried.

## Limitations

- Only one permit is used when an account has several.
- Permits with several zones cannot start reservations.
- `Permit.zone_validity` stays empty when the portal has not stored parking
  times for the permit's zones.
- Reservation updates cannot change the license plate or name.
- The portal can change its page definitions or data model at any time. A
  changed nanoflow surfaces as `ProviderError("Provider operation could not be
  resolved.")`.
