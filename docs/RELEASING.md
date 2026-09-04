# Releasing Forge Safely

Forge distribution should prefer immutable, verifiable release artifacts when the hosting provider supports them.

## Release policy

1. validate Forge locally/CI
2. create a version-specific release candidate
3. build the distributable archive
4. enable/use immutable release protection when available
5. attach the archive before publishing an immutable release
6. publish provider-generated provenance/attestation when supported
7. verify the published release and asset from a clean environment
8. only then advertise the release as executable bootstrap material

For GitHub, current platform documentation supports immutable releases and release/asset integrity verification. Maintainers should use those capabilities rather than relying only on a checksum stored in the same mutable repository.

## Do not hardcode platform assumptions into Forge

The release procedure may document current provider commands as examples, but Forge runtime behavior must detect available integrity-verification capabilities.

## Fallback distribution

If immutable release infrastructure is unavailable:
- publish an exact commit identifier
- avoid telling consumers to execute downloaded repository scripts before trust is established
- allow current-session use by reading the user-authorized `SKILL.md`
- use agent-controlled copy/install operations
- clearly disclose the weaker provenance level
