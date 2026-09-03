# Durable Context and Claude Code Governance Reference

Load this reference when establishing project memory, writing CLAUDE.md/rules/skills, handling compaction/resume, or diagnosing instruction/config behavior.

## Durable state

Conversation is working memory. Project files are durable memory.

Maintain authoritative information proportional to complexity:
- objective/scope
- requirements/invariants
- architecture
- master plan and Plan Deltas
- project control state
- concise current status/resume index
- decisions
- TODOs/deferred actions
- risks
- validation state

Avoid duplicate sources of truth.

## Resume index

Keep one concise place that answers:
- What is the objective and requirements baseline?
- What milestone and Work Packet are active?
- What was completed?
- What is partially implemented?
- What detours are open and where do they return?
- What is blocked?
- What important decisions changed recently?
- What user decisions remain?
- What validation passed/remains?
- What is the resume queue?
- Where are authoritative requirements, architecture, and control state?

## CLAUDE.md

Create/refine a concise project-level `CLAUDE.md` when useful.

Put only persistent project-specific information Claude needs often:
- non-obvious conventions
- verified install/build/test/run commands
- architecture boundaries
- critical invariants
- scope-conservation requirement
- source-of-truth locations
- context-preservation expectations

Do not copy the universal skill into CLAUDE.md.

## Choose the right Claude mechanism

Use:
- CLAUDE.md for persistent project-wide facts/instructions
- path-scoped rules for directory/file-specific guidance
- skills for reusable procedures/reference loaded on demand
- subagents for isolated specialist/exploration context
- hooks for deterministic lifecycle actions
- permissions for enforceable tool/security boundaries
- CI/tests/types/schema constraints for hard engineering guarantees

## Repeated mistakes

When the same project-specific error repeats, fix the system: improve docs, sharpen a rule, create/refine a skill, add a test/check/hook, or change architecture if the mistake is structurally encouraged.

## Compaction protocol

Persist material state continuously.

Before `/compact`, likely auto-compaction, handoff, or ending a long session, persist:
- objective/baseline
- requirements/invariants
- master plan
- active milestone/Work Packet
- parent/return_to
- implementation state
- Plan Deltas
- open detours
- decisions/reasoning
- blockers
- validation completed/pending
- resume queue

After compaction/resume:
1. reload persistent project instructions
2. read resume/control state
3. read active plan/Plan Deltas
4. read relevant requirements/architecture/decisions
5. inspect current code and diff
6. reconstruct from project evidence
7. compare with compacted summary
8. reconcile coverage and return_to
9. confirm resume queue

Do not continue from compacted summary alone.

For substantially unrelated work, persist state then prefer `/clear` or a fresh session.

If the skill's behavior appears weakened after compaction, re-invoke `/forge`.

## Configuration diagnosis

If Claude appears to ignore instructions, verify what actually loaded before assuming non-compliance:
- `/context`
- `/memory`
- `/skills`
- active agents
- hooks
- permissions/settings
- configuration errors/conflicts


## v1.2 Control Mode persistence

For Control Mode, do not rely on the manually invoked personal skill to be present in every future session.

Create/adapt a tiny unscoped project rule such as `.claude/rules/execution-control.md` from the packaged kernel. Keep it short and project-specific.

When stable control state exists, a project-specific `SessionStart` hook may inject a concise summary on `startup`, `resume`, `clear`, and `compact`. The packaged example reads `.claude/project-control.json`, validates it when a validator is present, and emits only a compact control summary.

Do not use SessionStart to inject the entire roadmap or skill. Inject only orientation state: baseline/revision, plan revision, active workstreams, blockers/detours, and resume queue.

If the hook or validator fails, do not silently assume control state is valid. Surface the failure and reconcile manually.

## Controller context budget

Treat controller context as scarce. Keep it focused on objective, canonical requirements, active plan/control state, decisions, integration, gate results, and concise evidence.

Workers should return compact summaries with evidence pointers rather than full transcripts/logs. Pull detailed worker evidence into the controller only when needed to make or verify an integration decision.

When context becomes dominated by one local problem, persist packet state and isolate/reset rather than allowing that local context to redefine project priority.
