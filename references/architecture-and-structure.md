# Architecture, Dependencies, Structure, and Migration Reference

Load this reference for architecture selection, major technical decisions, dependency admission, repository normalization, or migration design.

## Architecture comparison

Compare credible options on:
- objective fit
- simplicity
- maturity
- maintainability
- security/privacy
- reliability
- performance
- ecosystem/tooling
- operational burden
- total cost
- portability
- vendor lock-in
- migration complexity
- expected project lifetime
- team/organizational maintainability when known

Do not choose technology because it is fashionable.

If the best direction materially differs from current assumptions, present:
- Baseline approach: best path under current assumptions
- Recommended approach: stronger objective-serving path

## Reuse before reinvention

Before substantial common functionality is built from scratch:
1. inspect existing project capabilities
2. inspect existing dependencies
3. investigate maintained libraries/packages
4. inspect credible open-source implementations when useful
5. compare reuse versus custom implementation

Dependency admission checks:
- maintenance activity
- security history/advisories
- licensing compatibility
- transitive dependency burden
- API stability
- ecosystem fit
- performance/runtime/bundle impact
- lock-in
- integration complexity
- operational impact
- whether a small stable local implementation is simpler

Stars/popularity alone are not evidence of suitability.

## External research hierarchy

When current external information matters, prefer:
1. current official docs / primary sources
2. standards/specifications
3. maintainer docs
4. reputable technical analyses
5. production experience reports
6. community discussion

Record version/date when freshness matters.

## Repository structure

Do not impose a universal tree.

Derive structure from language/framework, architecture, boundaries, project size, deployment, tests, and ecosystem.

Optimize for ownership, cohesion, low coupling, discoverability, testability, maintainability, separation of concerns, simple build/deploy, and framework conventions.

Avoid speculative directory hierarchies, arbitrary nesting, giant generic utility folders, circular dependencies, duplicate implementations, mixed responsibilities, premature abstraction, and unrelated mass restructuring.

Classify existing items:
- Keep
- Adapt
- Move/Rename
- Create
- Consolidate
- Remove
- Decision Required

Never blindly delete user-authored/ambiguous files or silently alter legal/license files.

When moving code, update imports, package paths, tests, scripts, CI/CD, deployment references, and docs.

Use a dedicated repository-normalization milestone if restructuring carries meaningful regression risk.

## Migration-first design

For material changes to schemas, storage, APIs, protocols, authentication, infrastructure, or deployment architecture, design both destination and transition.

Consider migration sequence, compatibility, mixed-version period, rollback, partial failure, data backfill, reconciliation, observability during migration, cutover criteria, retirement of old path, and backup/recovery where relevant.

Do not design only the ideal final state.

## Large-codebase orientation

For large brownfield repositories, optimize discovery before broad reading:
- use available LSP/code intelligence, symbol/reference navigation, call hierarchy, type information, dependency graphs, targeted search, and test references
- identify architectural entry points and authoritative configuration first
- read only the surrounding code needed to establish behavior
- use fresh subagents for exploration that would flood the controller context
- create a compact repository/module map only when it will materially reduce repeated discovery

Do not repeatedly dump entire directories into context or maintain large static maps that become stale faster than they help.
