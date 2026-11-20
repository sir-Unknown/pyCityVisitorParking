# Changelog

## Unreleased

- Initial Amsterdam provider implementation.
- Optional `machine_number` login parameter to start sessions on a parking machine other than the permit's default; the zone is resolved through `paid_parking_zone/get_by_machine_number` and also drives `paid_hours`.
- Document that credentials are the portal's meldcode and pincode.
- Accept additional JWT claim shapes when extracting `client_product_id`.
- Resolve `client_product_id` from permit endpoints when it is missing from the token.
- Use `/v1` permit endpoints when discovering `client_product_id`.
- Follow the 0.6.0 provider API: `Permit.paid_hours`, `start_reservation(..., reservation_target_id=None)` (rejected, the provider has no reservation targets), and a start in the past starts the reservation now.
- Send a parking machine only for permits with `config.can_select_zone` (or an explicit `machine_number`), matching the portal; permits without zone selection no longer fail on a missing machine.
- Report `remaining_balance` with `balance_unit`: `time_balance` seconds as whole minutes (`MINUTE`), otherwise `money_balance` cents as euros (`EURO`).
- Derive `paid_hours` from the weekly `time_frame_data` of a single cost calculation instead of one call per day; drop the unverified `validity`/`zone_validity` fallback.
- Raise `ServiceUnavailableError` when the portal reports `NPR is unavailable.`.
- Reject reservation updates and ends for sessions with `can_edit: false` or that are no longer ACTIVE/FUTURE before sending them, matching the portal.
- Move a reservation start before the permit's `validity.started_at` to that moment, matching the portal.
- Read the default parking machine only from `ssp.favorite_machine_number`; drop the unverified `permit`/top-level machine and `zone_id` fallbacks.
