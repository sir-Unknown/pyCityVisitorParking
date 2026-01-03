# AGENTS.md — The Hague Provider Notes

This file supplements the shared provider guidance in
`src/pycityvisitorparking/provider/AGENTS.md`.

## Time handling

- Public reservation inputs must be timezone-aware `datetime` values.
- Outbound reservation payloads use UTC ISO 8601 `Z` strings.
- Inbound provider timestamps are normalized to UTC before returning models.

## Behavior constraints

- Reservation updates only support changing `end_time`.
- PV error codes from 400 responses are mapped to readable `ProviderError` messages.
- Default `api_uri` is `/api` when omitted.
