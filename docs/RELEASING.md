# Releasing Forge Safely

Forge distribution should prefer immutable, verifiable release artifacts when the hosting provider supports them.

## Release policy

1. make the intended release changes
2. update `CHANGELOG.md` with the new version at the top
3. validate Forge locally and in CI
4. update `VERSION` last
5. let the repository's generic release workflow derive the tag and asset name from `VERSION`
6. build the distributable archive from the exact release commit
7. create the release as a draft and attach all assets before publication
8. publish under immutable-release protection when available
9. verify the published release and local asset from a clean environment
10. only then advertise the release as executable bootstrap material

The release workflow must not hardcode a specific Forge version or release commit. Release identity comes from the committed `VERSION` file and the workflow run's exact commit.

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
