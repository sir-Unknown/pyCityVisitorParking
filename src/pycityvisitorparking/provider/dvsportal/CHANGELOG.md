# Changelog

## Unreleased

## 0.5.31

- Send `X-XSRF-TOKEN` when the portal issues its request-forgery cookie under a name that `app.env.js` does not declare: if no configured or discovered name matches, any applicable cookie whose name contains `xsrf` is used.

## 0.5.30

- Fixed write requests failing with HTTP 401 on portals that publish the XSRF token in the `__Host-Xsrf-DVSPortal` cookie and do not serve `app.env.js` (seen on Rijswijk). The provider now sends that cookie's value as `X-XSRF-TOKEN` by default.

## 0.5.29

- Breaking: the provider no longer exposes `resolved_login_params`. The resolved `permit_media_type_id` is cached internally and reused on reauthentication. The optional `permit_media_type_id` login key is unchanged.
- Log reauthentication, 401/403 responses, the HTML 500 session-expiry signal and HTTP 429/502/503/504 at debug level instead of warning.
- HTTP 429 raises `RateLimitError`, HTTP 502/503/504 raise `ServiceUnavailableError`, and HTTP 404 raises `NotFoundError`. Unsupported updates raise `ProviderError` with `error_code="not_supported"`.

## 0.5.28

- Added the refactored `dvsportal_new` provider package with split session, profile,
  transport, and mapping modules.
- Fixed re-authentication on portals that report an expired session as an HTML HTTP 500
  response (seen on Nijmegen and Groningen). The provider now re-logs in once, including
  the XSRF bootstrap, and retries. A persistent HTML 500, or one during login, is raised as
  `ServiceUnavailableError` instead of an auth failure. Other 5xx responses are unchanged.
