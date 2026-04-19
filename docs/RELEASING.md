# RELEASING.md — Release & Publish Guide (pyCityVisitorParking)

✅ **Use the current release source of truth**
- The package version is derived from git tags via `hatch-vcs`.
- Do not edit a version string in the repository for releases.
- The release tag must match `vX.Y.Z`.

✅ **Use SemVer and keep changelogs accurate**
- Use SemVer for release tags.
- Bump MINOR for provider additions.
- Bump PATCH for bug fixes.
- Maintain an `Unreleased` section in:
  - root `CHANGELOG.md`
  - each provider `CHANGELOG.md`
- Move `Unreleased` entries into a versioned section before tagging a release.

✅ **Update documentation before releasing**
- Update root `README.md` when public behavior changes.
- Update root `CHANGELOG.md` for every release.
- Update provider `README.md` and provider `CHANGELOG.md` for provider changes:
  - auth flow changes
  - endpoint changes
  - mapping changes (UTC conversion, `zone_validity` filtering)
  - limitations or known issues

✅ **Validate the release locally with the current toolchain**
- Set up the project environment with `uv`.
- Run lint:
  - `uv run --group lint ruff check .`
  - `uv run --group lint ruff format --check .`
- Run type checking:
  - `uv run --group typecheck pyright`
- Run tests:
  - `uv run --group test pytest`
- Validate provider manifests:
  - `uv run --group schema python -m pytest -o addopts=-q tests/test_manifest_schema.py`
- Build artifacts:
  - `uv build`
- Validate artifacts:
  - `uvx twine check dist/*`

Do not push release tags before the local checks and artifact validation pass.

✅ **Use Release Drafter as a draft aid, not as the release source of truth**
- Release Drafter keeps a draft GitHub release up to date from merged pull requests.
- Review and edit the generated notes before publishing.
- The final published release must still be created from the real git tag you intend to publish.
- If the draft release points at the wrong commit, retarget it to the release tag before publishing.

✅ **Current release flow**
1. Update docs and changelogs on the release commit.
2. Run the local validation steps listed above.
3. Commit the release changes.
4. Create an annotated tag:
   - `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
5. Push the release commit and tag:
   - `git push`
   - `git push origin vX.Y.Z`
6. Confirm the `CI` workflow passes for the tag.
7. Publish the GitHub release for tag `vX.Y.Z`.
8. The `Release` workflow resolves that tag to an exact commit, verifies the `CI` workflow passed on that commit, and checks whether package-shipping files changed since the previous published release.
9. If package files changed, the workflow builds from that tagged commit and publishes to PyPI using OIDC. If not, it exits without publishing.

✅ **Understand what GitHub Actions does**
- `CI` runs on pull requests, pushes to `main`, manual dispatch, and tags matching `v*`.
- `Release Drafter` updates the draft release on `main` pushes and PR updates.
- `Release` runs when a GitHub release is published and can also be run manually for an existing tag via `workflow_dispatch`.
- The publish workflow:
  - validates that the requested tag matches `vX.Y.Z`
  - resolves the tag to its exact commit
  - verifies the `CI` workflow succeeded for that commit
  - compares the tagged commit with the previous published release and skips publishing when no package-shipping files changed
  - checks out the repository at that exact commit
  - logs the resolved package version
  - builds `sdist` and `wheel`
  - runs `twine check`
  - publishes to PyPI using `pypa/gh-action-pypi-publish`

✅ **Validate tag and version alignment**
- Because the version comes from VCS metadata, the tag is the version source of truth.
- Create the GitHub release from the intended `vX.Y.Z` tag on the release commit.
- Do not publish a GitHub release from an untagged commit or from the wrong tag.

✅ **Configure Trusted Publishing (OIDC)**
- Configure the PyPI project to trust this repository and workflow.
- Ensure the GitHub Actions environment used for publishing is authorized in PyPI.
- The publish workflow requires:
  - `id-token: write`

✅ **Verify release contents**
- Confirm the built distribution contains:
  - all provider `manifest.json` files
  - `manifest.schema.json`
  - provider `README.md` and provider `CHANGELOG.md`
  - root `README.md` and root `CHANGELOG.md`
  - `docs/RELEASING.md`

✅ **Troubleshoot publishing issues systematically**
- Fix lint, type-check, and test failures first.
- Fix packaging inclusion issues next.
- Re-run:
  - `uv build`
  - `uvx twine check dist/*`
- Prefer releasing a new PATCH version over deleting or reusing a broken tag.

❌ **Avoid these anti-patterns**
- Do not publish directly from a laptop when CI publishing is available.
- Do not skip changelog updates.
- Do not create a GitHub release before the intended tag exists on GitHub.
- Do not retag an existing version after publication.
- Do not introduce new runtime dependencies without reviewing Home Assistant compatibility.
- Do not break the provider PR scope rule unnecessarily.

✅ **Rollback safely using PyPI yanks**
- Yank a release when the published package is broken but should remain part of the public record.
- Prefer yanking over deleting because deletion harms reproducibility.

✅ **Choose the right recovery strategy**
- Yank a release when:
  - the package installs but has a critical bug
  - a provider mapping is wrong and causes incorrect behavior
  - the build is valid but runtime behavior is unsafe or broken
- Publish a new PATCH release when:
  - you have a fix ready
  - you want users to move forward automatically

✅ **Perform a yank on PyPI**
- Open the project on PyPI.
- Open the affected release.
- Mark the release files as yanked.
- Add a clear yank reason that tells users what to do next, for example `Use vX.Y.(Z+1)`.

✅ **Publish a follow-up PATCH release**
- Fix the issue on `main`.
- Update root `CHANGELOG.md` and the affected provider `CHANGELOG.md`.
- Repeat the same tag-driven release flow with the next PATCH version.

✅ **Communicate the rollback**
- Add a short note to root `CHANGELOG.md` explaining:
  - what was wrong
  - which versions are affected
  - which version contains the fix
- Add provider-specific notes in the provider `CHANGELOG.md` when applicable.

✅ **Prevent recurrence**
- Add or extend tests for the failure mode.
- Keep provider fixtures updated to cover the problematic payload.
