# Changelog

## Unreleased

- `login()` accepts an optional `permit_id` that selects the permit for `get_permit`, `list_reservations`, `list_reservation_targets`, `fetch_all`, and `start_reservation`. A selected permit that is no longer usable raises `NotFoundError` with `error_code="permit_not_found"` instead of falling back to another permit; without `permit_id` the first permit is used as before (D2). An account without a usable permit now also carries `error_code="permit_not_found"`.
- Add `list_permits()`: every usable permit of the account, with the authorization description as `Permit.name`.

## 0.6.0

- The "start now" rule of `start_reservation` (a start in the past becomes the current minute) now uses the shared `BaseProvider._start_not_before_now` helper; behavior is unchanged.
- Breaking: `fetch_all()` now returns `(permit, reservations, favorites, targets)`; the zones are fetched once for both the permit windows and the targets. Unpack four values instead of three.
- When a created reservation is not echoed by the portal, look it up by permit and match the license plate locally instead of putting the plate in the XPath.
- Add the Rotterdam provider for the Mendix based visitor parking portal at
  `bezoek.rotterdam.nl`: `login`, `get_permit`, `list_reservations`,
  `start_reservation`, `update_reservation` (`start_time` of a planned
  reservation and `end_time`), `end_reservation`, `list_favorites`,
  `add_favorite`, `update_favorite`, and `remove_favorite`.
- Resolve microflow operation ids at runtime from the portal's page definitions
  instead of hardcoding them.
- Verified with a real six-zone permit against the live portal: permit, balance,
  paid hours per zone, and start, update, end and cancel of reservations in the
  default and other zones; see the provider README.
- Document the deliberate design decisions (zones, first permit, runtime
  operation ids, minute resolution) in the README and mark them in the code.
- Support zone selection per reservation through the generic reservation target
  contract: `list_reservation_targets` lists the permit's zones (identified by
  name, default zone first) with their own parking times, `start_reservation`
  accepts a `reservation_target_id` and uses the default zone without one, and
  `Reservation.reservation_target_id` reports the zone of a parking action.
  The manifest declares `reservation_target_selection: "list"`. Permits with
  several zones are no longer refused.
- Merge overlapping and touching parking-time windows into one (for example
  `09:00-24:00` and `00:00-01:00` local become `09:00-01:00`), and report each
  zone's windows separately instead of combining all zones.
