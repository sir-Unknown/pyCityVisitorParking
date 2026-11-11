# Changelog

## Unreleased

- Added the refactored `dvsportal_new` provider package with split session, profile,
  transport, and mapping modules.
- Fixed re-authentication on portals that report an expired session as an HTML HTTP 500
  response (seen on Nijmegen and Groningen). The provider now re-logs in once, including
  the XSRF bootstrap, and retries. A persistent HTML 500, or one during login, is raised as
  `ServiceUnavailableError` instead of an auth failure. Other 5xx responses are unchanged.
