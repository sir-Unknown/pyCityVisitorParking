# Changelog

## Unreleased

- Add an Amsterdam demo permit ("Amsterdam Demo"): balance in minutes, one reservation target (default parking machine `19850`) whose paid hours (Monday–Saturday 09:00–24:00, Sunday 12:00–24:00) are also the permit's.

## 0.6.0

- A `start_reservation` start in the past ("start now") starts at the current time.
- The Rotterdam demo zones keep the still-running overnight paid window of the previous day, so `Permit.paid_hours` and the target `paid_hours` include it between midnight and the end of the window (for example Saturday 00:30 for a window that ends at 01:00).
