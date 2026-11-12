# Changelog

## Unreleased

- Initial Amsterdam provider implementation.
- Optional `machine_number` login parameter to start sessions on a parking machine other than the permit's default; the zone is resolved through `paid_parking_zone/get_by_machine_number` and also drives `zone_validity`.
- Document that credentials are the portal's meldcode and pincode.
- Accept additional JWT claim shapes when extracting `client_product_id`.
- Resolve `client_product_id` from permit endpoints when it is missing from the token.
- Use `/v1` permit endpoints when discovering `client_product_id`.
