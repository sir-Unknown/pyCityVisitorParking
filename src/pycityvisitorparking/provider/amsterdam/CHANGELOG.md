# Changelog

## Unreleased

- Initial Amsterdam provider implementation.
- Accept additional JWT claim shapes when extracting `client_product_id`.
- Resolve `client_product_id` from permit endpoints when it is missing from the token.
- Use `/v1` permit endpoints when discovering `client_product_id`.
