# Planned work

Read for work with dependent outcomes, material uncertainty, substantial detours, or continuity across sessions. Do not load every linked reference. Each is for the condition named below.

## Establish enough direction to act

Read the relevant existing requirements, project instructions, status, code, and checks. Reuse sound conventions. Identify the outcome, scope, acceptance evidence, and decisions that actually block work. Existing user instructions can already supply the baseline and authorization; do not ask for a ceremonial approval.

For a rough idea or a material requirement gap, use [requirements discovery](requirements.md). For consequential architecture, migration, or restructuring decisions, use [architecture and structure](architecture-and-structure.md). Broaden discovery when the request calls for it, without turning an ordinary feature into a full project audit.

Make safe reversible assumptions explicit when useful and proceed. Ask only about ambiguity that would change the outcome, material risk, scope, or authorization. Continue independent work while waiting where possible.

## Keep one current account of the work

Prefer the project's existing plan/status or native task surface. Record only the context another session would otherwise have to rediscover:

- intended outcome and relevant requirements/invariants;
- current work, what is complete, and evidence pointers;
- unresolved decisions, blockers, and detours with a return target;
- the next action and still-approved later work.

For short planned work, a compact checklist in the existing surface is sufficient. Do not create parallel STATUS, TODO, decision, JSON, and resume files describing the same state. Do not discard valid existing state to lower a file count. Read [durable context](context-and-governance.md) when preparing a handoff or diagnosing stale state.

Use structured Control Mode only when dependencies, parallel ownership, material plan changes, or automated guards justify it. The bundled external runner requires its structured state. Then read [scope and plan control](scope-and-plan-control.md); its schemas, Work Packets, revisions, and gates apply to that mode. The [worked example](example-walkthrough.md) illustrates it without prescribing a universal folder structure.

## Execute and return to the outcome

Choose one coherent unit of work with acceptance evidence and a known next step. Inspect, implement, verify, and reconcile the changed facts in the existing state. Avoid rewriting unchanged documents and rerunning unrelated checks without a reason. No arbitrary cap should prevent necessary investigation or verification.

Before taking a detour, state why it is required for the current outcome and where work resumes. Necessary local fixes remain part of the work; optional discoveries are recorded when useful. A detour must not replace the approved roadmap. A material change to the user's requirements or commitments needs the appropriate authority, which may already have been given.

Synchronizing a contradicted requirement line with an authorized change does not require a separate Plan Delta or revision bump by itself. Preserve unrelated requirements/invariants and follow any explicit project rule for recording changes. Material changes to scope, dependencies, or intended behavior use the project's change control.

Use [execution and quality](execution-and-quality.md) for nontrivial debugging, verification design, or independent review. Prefer deterministic checks before extra agents. Use [orchestration](orchestration.md) only when independent work or required review justifies another worker; use [Claude integration](claude-code-integration.md) when configuring that platform's mechanisms. Do not probe external providers simply because the current task is substantial.

## Verify claims and preserve the next step

Tie claims to the relevant behavior and actual evidence. A test for reading data does not verify writing it; a status line saying "fixed" is not a passing check. For each affected requirement or invariant claimed verified, identify the check and result. Record failed or unavailable checks as such. Check suspected pre-existing defects against the starting state before calling them regressions.

At a meaningful milestone, compare the requested outcomes with implementation and evidence. Use [consistency and convergence](consistency-and-convergence.md) for major closure or a material plan change; recheck only what new evidence invalidates. A completed checklist, validator result, or accepted gap cannot establish behavior it did not verify.

Update the current state after meaningful changes and before handoff; keep evidence links instead of copying logs. Finish the requested scope, or report what remains and why. Read [user interaction](user-interaction.md) when a decision or handoff needs more explanation; ordinary progress and completion should remain concise.
