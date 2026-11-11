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
- Document the deliberate design decisions (single zone, first permit, runtime
  operation ids, minute resolution) in the README and mark them in the code.
