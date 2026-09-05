# Releasing Forge Safely

Forge distribution should prefer immutable, verifiable release artifacts when the hosting provider supports them.

## Release policy

1. make the intended release changes
2. update `CHANGELOG.md` with the new version at the top
3. update `VERSION` as the final release-content edit
4. validate Forge locally
5. let the full `Validate Forge` push workflow pass for that exact main-branch commit; a failed or cancelled run cannot release
6. build the distributable archive from the exact release commit
7. create the release as a draft and attach all assets before publication
8. publish under immutable-release protection when available
9. verify the published release and local asset from a clean environment
10. only then advertise the release as executable bootstrap material

The release workflow must not hardcode a specific Forge version or release commit. Release identity comes from the committed `VERSION` file and the workflow run's exact commit.

`Release Forge` is triggered by successful completion of `Validate Forge` on a push to this repository's `main` branch. It checks whether the validated `VERSION` has already been published, then checks out `workflow_run.head_sha` for packaging and release creation. This also supports multi-commit pushes and a follow-up fix after cancelled or failed validation. PR runs cannot trigger publication. The workflow serializes publication and refuses to replace an existing release or reuse an unpublished tag. If a failed publication left a draft, inspect it before retrying. Versions with suffixes are published as prereleases and never marked latest.

Require `validation-gate` in the repository's main-branch ruleset. Change detection and static checks must succeed; only inapplicable expensive test jobs may be skipped. Repository rulesets are a maintainer setting, separate from these workflow files.

The validated commit must still be the current main head at eligibility and immediately before draft creation. Delayed completions therefore cannot publish an older version after a newer main commit. A new main push must pass its own validation.

For a failed validation, fix the failure while retaining the intended unpublished `VERSION`; the next successful push validation can release it. For a transient workflow failure, re-run validation on the intended commit. Do not change an already published version's files or assets.

For GitHub, immutable releases automatically bind the published tag, commit, and assets through provider-generated release attestation. Current GitHub verification commands such as `gh release verify` and `gh release verify-asset` are provider-specific implementation details, not Forge runtime dependencies.

## Version consistency

`scripts/validate-skill-package.py` checks that:
- `VERSION` is present and syntactically valid
- the first version heading in `CHANGELOG.md` matches `VERSION`
- when validation runs on a tag, the tag matches `v${VERSION}`

This keeps release validation version-agnostic.

## Do not hardcode platform assumptions into Forge

Release automation may use provider-specific commands because it runs inside that provider. Forge runtime behavior must still detect available integrity-verification, installation, orchestration, and lifecycle capabilities rather than routing from model names, tool versions, or temporary platform feature lists.

## Fallback distribution

If immutable release infrastructure is unavailable:
- publish or resolve an exact commit identifier
- avoid telling consumers to execute downloaded repository scripts before trust is established
- allow current-session use by reading the user-authorized `SKILL.md`
- use agent-controlled copy/install operations
- clearly disclose the weaker provenance level
