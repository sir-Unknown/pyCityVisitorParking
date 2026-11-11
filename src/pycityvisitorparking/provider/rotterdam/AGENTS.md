# AGENTS.md — Rotterdam provider

Rules specific to `src/pycityvisitorparking/provider/rotterdam/`. The shared
rules in `../AGENTS.md` and the repository `AGENTS.md` still apply.

- The README section "Design decisions" (D1-D4) lists deliberate behavior choices
  that are marked `DESIGN DECISION Dn` in `api.py`. Do not change one casually:
  update the marked code, the named tests, the README section, and
  `CHANGELOG.md` together.

- The portal is a Mendix application. Keep protocol details in `mendix.py` and
  provider-native names (Dutch entity and attribute names) in `const.py` and
  `api.py`. Never expose them through the public models or exception messages.
- Never hardcode microflow operation ids. Add new microflow calls to
  `OPERATIONS` in `const.py` (page, nanoflow name, parameter names) so they are
  resolved from the published page definitions.
- Send runtime request bodies as pre-serialized `data=`, not `json=`. The shared
  request logger only masks `json=` payloads by key, and these bodies carry
  license plates in `{"value": ...}` objects.
- Entity XPath constraints are not validated by the runtime: an unknown
  attribute silently returns no rows. Check attribute names against the
  published metamodel (`get_session_data` → `metadata`) when changing queries.
- Values embedded in XPath literals must be object ids from the portal
  (`xpath_guid`) or caller ids checked by `xpath_opaque_id`. Never interpolate
  other caller input.
- The permit, zone validity, and successful reservation paths were built without
  an account that holds a permit. When one becomes available, verify them live
  and update the README "Verification status" section.
- Test with the scripted fake portal in `tests/`; never call the live portal
  from tests.
