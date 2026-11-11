# Changelog

## Unreleased

## 0.5.28

- A 2xx HTML response (maintenance or WAF page) instead of JSON raises `ServiceUnavailableError` and is logged at debug level.
- Treat the `SESSION_TIMEOUT` status (HTTP 200, no data) as an expired session: reauthenticate and retry instead of reporting a zero balance and no favorites. `fetch_all` reauthenticates once for both of its parallel requests, and the reauth clears the provider's cookies first (a login sent with the expired session cookie does not revive it).
- All logins are serialized with a lock, and a request that timed out on an older session skips a reauth another task already completed. Concurrent requests (for example a reservation during a poll) no longer trigger parallel logins that invalidate each other's session.
- Initial implementation of the 2park provider.
- Implemented `update_reservation` (end_time only via `extend_action`).
- Implemented `add_favorite` and `remove_favorite` via `handle_favorite`.
- Fixed `_extract_location` to read `pgp_parameters` (not `pgr_parameters`) and filter on the `START` parameter group.
