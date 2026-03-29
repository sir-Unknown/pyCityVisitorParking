# Changelog

## Unreleased

- Initial implementation of the 2park provider.
- Implemented `update_reservation` (end_time only via `extend_action`).
- Implemented `add_favorite` and `remove_favorite` via `handle_favorite`.
- Fixed `_extract_location` to read `pgp_parameters` (not `pgr_parameters`) and filter on the `START` parameter group.
