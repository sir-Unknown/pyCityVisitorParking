# Changelog

## Unreleased

- The Rotterdam demo zones keep the still-running overnight paid window of the previous day, so `Permit.paid_hours` and the target `paid_hours` include it between midnight and the end of the window (for example Saturday 00:30 for a window that ends at 01:00).
