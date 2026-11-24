# Changelog

## Unreleased

- Initial Amsterdam provider implementation.
- Expose the parking machine as a `free_input` reservation target: the permit's default machine is listed, any other machine number is resolved to its zone through `paid_parking_zone/get_by_machine_number`, and `Reservation.reservation_target_id` carries the session's machine.
- Document that credentials are the portal's meldcode and pincode.
- Accept additional JWT claim shapes when extracting `client_product_id`.
- Resolve `client_product_id` from permit endpoints when it is missing from the token.
- Use `/v1` permit endpoints when discovering `client_product_id`.
- Follow the 0.6.0 provider API: `Permit.paid_hours`, `start_reservation(..., reservation_target_id=None)`, and a start in the past starts the reservation now.
- Send a parking machine only for permits with `config.can_select_zone`, matching the portal; permits without zone selection no longer fail on a missing machine.
- Report every balance in `Permit.balances`: `time_balance` seconds as whole minutes (`MINUTE`) and `money_balance` cents as euros (`EURO`). A permit with both now reports both; before, the money balance was dropped.
- Derive `paid_hours` from the weekly `time_frame_data` of a single cost calculation instead of one call per day; drop the unverified `validity`/`zone_validity` fallback.
- Raise `ServiceUnavailableError` when the portal reports `NPR is unavailable.`.
- Reject reservation updates and ends for sessions with `can_edit: false` or that are no longer ACTIVE/FUTURE before sending them, matching the portal.
- Move a reservation start before the permit's `validity.started_at` to that moment, matching the portal.
- Read the default parking machine only from `ssp.favorite_machine_number`; drop the unverified `permit`/top-level machine and `zone_id` fallbacks.
- List the machines of open sessions as reservation targets after the default machine, and resolve any machine through `get_reservation_target()`, each with its own `paid_hours`.
- Read a started session or added favorite back from the list when the portal's response lacks its license plate; an ended or edited session is returned from the session read before the change. Previously these succeeded upstream but raised `License plate is empty after normalization.`.
- Request parking sessions newest first (`sort=parking_session_id:desc`), like the portal, so open sessions stay on the first page.
- Calculate `paid_hours` for a one-hour period from now instead of today from midnight; the portal never calculates a period in the past. Log why the paid hours could not be fetched at debug level.
- Use `client_product_id` as `Permit.id` instead of the login `username`, which is the meldcode and therefore a credential.
- Log at debug level why `paid_hours` stay empty: the keys of a cost calculation response without `time_frame_data`, or the shape of a weekly schedule without readable blocks (day sizes, block keys, clock times).
