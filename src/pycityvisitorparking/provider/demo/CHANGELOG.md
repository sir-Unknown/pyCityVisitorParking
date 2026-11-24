# Changelog

## Unreleased

- Add an Amsterdam demo permit ("Amsterdam Demo"): a `MINUTE` and a `EURO` balance, default parking machine `19850` as the listed reservation target with paid hours (Monday–Saturday 09:00–24:00, Sunday 12:00–24:00) that are also the permit's. Like the real provider it uses `free_input`: any other parking machine number is accepted as `reservation_target_id`, is listed once a reservation uses it, and is paid until 21:00 (Sunday from noon).
- `ProviderInfo.reservation_target_selection` from `BaseProvider.info` follows the provider's `reservation_target_selection` property.
- Breaking: balances are reported in `Permit.balances` instead of `remaining_balance` and `balance_unit`; amounts and units are unchanged.

## 0.6.1

- The Rotterdam demo account has a second permit ("Shared permit", zones 700 and 701, its own balance and reservation), so permit selection can be tried without a real account. `list_permits()` returns both permits with their names, `login(permit_id=...)` selects one, and an unknown `permit_id` raises `NotFoundError` with `error_code="permit_not_found"`. Without `permit_id` the first permit (`demo-permit`) is used as before.

## 0.6.0

- A `start_reservation` start in the past ("start now") starts at the current time.
- The Rotterdam demo zones keep the still-running overnight paid window of the previous day, so `Permit.paid_hours` and the target `paid_hours` include it between midnight and the end of the window (for example Saturday 00:30 for a window that ends at 01:00).
