# RELEASING.md — Release & Publish Guide (pyCityVisitorParking)

✅ **Publish via CI using Trusted Publishing (OIDC)**
- Publish releases from GitHub Actions using OIDC.
- ❌ Avoid publishing from local machines when CI publishing is available.
- ❌ Avoid PyPI API tokens when OIDC is available.

✅ **Use SemVer and keep changelogs accurate**
- Use SemVer for the package version.
- Bump MINOR for provider additions.
- Bump PATCH for bug fixes.
- Maintain an “Unreleased” section in:
  - root `CHANGELOG.md`
  - each provider `CHANGELOG.md`
- Move “Unreleased” entries into a versioned section on release.

✅ **Update documentation before releasing**
- Update root `README.md` when public behavior changes.
- Update root `CHANGELOG.md` for every release.
- Update provider `README.md` and provider `CHANGELOG.md` for provider changes:
  - auth flow changes
  - endpoint changes
  - mapping changes (UTC conversion, zone_validity filtering)
  - limitations or known issues

✅ **Run all checks locally using Hatch**
- Run formatting checks:
  - `hatch run lint:format-check`
- Run lint:
  - `hatch run lint:check`
- Run tests:
  - `hatch run test:run`
- Build artifacts:
  - `hatch build`
- Validate artifacts:
  - `python -m twine check dist/*`

✅ **Bump the version using Hatch**
- Bump patch/minor/major:
  - `hatch version patch`
  - `hatch version minor`
  - `hatch version major`
- Or set an explicit version:
  - `hatch version X.Y.Z`

✅ **Commit and tag the release**
- Commit release changes:
  - `git commit -am "Release vX.Y.Z"`
- Create a version tag:
  - `git tag vX.Y.Z`
- Push commits and tags:
  - `git push --follow-tags`

✅ **Publish to PyPI from GitHub Actions**
- Push a tag `vX.Y.Z` to trigger the publish workflow.
- Ensure the workflow:
  - builds `sdist` and `wheel`
  - verifies artifacts (`twine check`)
  - publishes using `pypa/gh-action-pypi-publish` with OIDC

✅ **Use TestPyPI for a dry run**
- Trigger the publish workflow manually with `workflow_dispatch`.
- Choose `testpypi` as the target.
- Verify installation from TestPyPI in a clean environment before publishing to PyPI.

✅ **Configure Trusted Publishing (OIDC) on PyPI/TestPyPI**
- Open PyPI/TestPyPI → project settings → trusted publishers.
- Add:
  - GitHub owner/repo
  - workflow name
  - optional environment restrictions
- Ensure GitHub Actions has:
  - `permissions: id-token: write`

✅ **Verify release contents (sdist)**
- Confirm the `sdist` contains:
  - all provider `manifest.json` files
  - `manifest.schema.json`
  - provider `README.md` and provider `CHANGELOG.md`
  - root `README.md` and root `CHANGELOG.md`

✅ **Enforce schema validation in CI**
- Keep the manifest schema validation test enabled.
- Fail CI if any provider manifest violates the schema.

✅ **Troubleshoot publishing issues systematically**
- Fix lint/test failures first.
- Fix packaging inclusion issues next (missing files in `sdist`).
- Re-run:
  - `hatch build`
  - `python -m twine check dist/*`
- Prefer releasing a new PATCH version over re-tagging.

❌ **Avoid these anti-patterns**
- Do not publish directly from a laptop if CI publish exists.
- Do not skip changelog updates.
- Do not introduce new runtime dependencies without reviewing Home Assistant compatibility.
- Do not break the “provider PR scope rule” (provider changes should remain provider-folder-only).

✅ **Rollback safely using PyPI yanks**
- Use a **yank** when a release is broken but you want to keep the version recorded.
- Prefer yanking over deleting, because deleting can break reproducibility for users.

✅ **Choose the right recovery strategy**
- Yank a release when:
  - the package installs but has a critical bug
  - a provider mapping is wrong and causes incorrect behavior
  - the build is valid but runtime behavior is unsafe or broken
- Publish a new PATCH release when:
  - you have a fix ready
  - you want users to move forward automatically
- Avoid deleting releases unless PyPI policy requires it.

✅ **Perform a yank on PyPI**
- Open the project on PyPI.
- Open the specific release/version.
- Mark the release files as **yanked**.
- Add a clear yank reason that tells users what to do next (e.g. “Use vX.Y.(Z+1)”).

✅ **Publish a follow-up PATCH release**
- Fix the issue on `main`.
- Update root `CHANGELOG.md` and the affected provider `CHANGELOG.md`.
- Bump the version with Hatch:
  - `hatch version patch`
- Tag and push:
  - `git tag vX.Y.(Z+1)`
  - `git push --follow-tags`
- Let CI publish the new version via OIDC.

✅ **Communicate the rollback**
- Add a short note to root `CHANGELOG.md` explaining:
  - what was wrong
  - which versions are affected
  - which version contains the fix
- Add provider-specific notes in the provider `CHANGELOG.md` when applicable.

✅ **Prevent recurrence**
- Add or extend tests for the failure mode (mapping, parsing, schema, etc.).
- Keep provider fixtures updated to cover the problematic payload.
