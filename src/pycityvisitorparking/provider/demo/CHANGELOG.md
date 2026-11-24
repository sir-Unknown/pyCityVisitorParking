# Changelog

## Unreleased

- Breaking: balances are reported in `Permit.balances` instead of `remaining_balance` and `balance_unit`; amounts and units are unchanged.
- The Amsterdam demo permit has a `MINUTE` and a `EURO` balance, so the two-balance case can be tried without a real account.

## 0.6.1

- The Rotterdam demo account has a second permit ("Shared permit", zones 700 and 701, its own balance and reservation), so permit selection can be tried without a real account. `list_permits()` returns both permits with their names, `login(permit_id=...)` selects one, and an unknown `permit_id` raises `NotFoundError` with `error_code="permit_not_found"`. Without `permit_id` the first permit (`demo-permit`) is used as before.

## 0.6.0

- A `start_reservation` start in the past ("start now") starts at the current time.
- The Rotterdam demo zones keep the still-running overnight paid window of the previous day, so `Permit.paid_hours` and the target `paid_hours` include it between midnight and the end of the window (for example Saturday 00:30 for a window that ends at 01:00).
