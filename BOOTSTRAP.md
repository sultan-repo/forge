# Forge Remote Bootstrap Protocol

This protocol applies when a user explicitly asks a coding agent to import or use Forge from a repository URL.

## Security principle

The user-authorized repository may be read as Forge input, but **downloaded code is not automatically safe to execute**. Bootstrap must separate:

1. source selection
2. provenance/integrity verification
3. structural validation
4. installation
5. current-session activation

Never execute downloaded Forge shell/Python scripts merely to determine whether the download is trustworthy.

## Source selection

Prefer the strongest source identity available:

1. an explicitly requested immutable release/version
2. an explicitly requested commit
3. the latest published stable release resolved at bootstrap time
4. if no release is available, the exact commit currently resolved from the user-named repository

Do not make Forge behavior depend on hardcoded model names, tool versions, or current platform feature lists. Detect available verification/install capabilities at runtime.

Record the resolved repository, ref/version, and commit when practical so future sessions can identify what was installed.

## Verification

Use the strongest verification mechanism the current environment and hosting provider support.

For GitHub repositories, if release-integrity verification is available, prefer an immutable release and verify the release and any downloaded release asset before executing its contents. GitHub CLI commands such as `gh release verify` and `gh release verify-asset` are examples, not mandatory dependencies.

If cryptographic/attestation verification is unavailable:

- resolve and pin an exact commit
- fetch over the authenticated/HTTPS provider path available to the agent
- inspect `SKILL.md` as data and confirm `name: forge`
- do **not** run downloaded repository scripts
- install, if authorized, using agent-controlled file-copy operations
- disclose that provenance was pinned but not cryptographically attested

If identity or provenance cannot be established to a level appropriate for the requested action, do not execute remote code. Forge may still be read for the current session when the user explicitly authorized that repository, but persistence/executable helpers should be skipped.

## Installation

Keep Forge outside the product source tree. Preferred persistent location:

```text
~/.claude/skills/forge/
```

When the source is verified, the packaged installer may be used.

When the source is only commit-pinned but not cryptographically verified, prefer agent-controlled copying of the skill files rather than executing `scripts/install.sh` or `scripts/bootstrap.sh`.

Do not overwrite unrelated user skill files or project settings.

## Current-session activation

After Forge is available locally:

1. read the installed or fetched `SKILL.md` directly
2. treat the user's explicit import/use request as an explicit Forge invocation
3. infer `new` for an empty/greenfield workspace or `adopt` for an existing project unless the user supplied a mode
4. continue immediately with the user's original project scope

Do not stop only because `/forge` is not yet registered in the current UI/session. If the environment requires a later reload/restart for command discovery, that affects future invocation, not the current user-authorized Forge run.

## Safe fallback

If persistent installation is unavailable:

- use the user-authorized Forge files for the current session
- do not claim Forge was persistently installed
- do not execute unverified downloaded helpers
- continue the project unless the limitation blocks a required capability

If the repository fetch, identity check, or required provenance check fails, report the failure rather than silently substituting another methodology.

## Maintainer release guidance

For public distribution, Forge releases should be versioned and immutable when the hosting provider supports that capability. Attach the distributable archive as a release asset and publish provenance/attestation through the provider when supported. Consumers should verify the immutable release/asset before executing bundled helpers.

See `docs/RELEASING.md`.
