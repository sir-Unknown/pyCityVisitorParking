# Changelog

## Unreleased

- Add the Rotterdam provider for the Mendix based visitor parking portal at
  `bezoek.rotterdam.nl`: `login`, `get_permit`, `list_reservations`,
  `start_reservation`, `update_reservation` (`start_time` of a planned
  reservation and `end_time`), `end_reservation`, `list_favorites`,
  `add_favorite`, `update_favorite`, and `remove_favorite`.
- Resolve microflow operation ids at runtime from the portal's page definitions
  instead of hardcoding them.
- Permit data and the successful parking-action path are based on the portal's
  published data model and have not been verified against an account with a
  permit; see the provider README.
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
