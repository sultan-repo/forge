# Optional Claude Code Hooks for Execution Control

These are project-specific enforcement options. Do not install them blindly. Stabilize the project's control-state format and commands first.

Claude Code exposes `SessionStart`, `TaskCreated`, and `TaskCompleted` lifecycle hooks. SessionStart can add context; TaskCreated/TaskCompleted can enforce task linkage/completion rules.

## 1. SessionStart orientation hook

Useful for multi-milestone projects where context loss/drift is costly.

Run on:
- startup
- resume
- clear
- compact

Inject only a concise orientation summary:
- baseline ID/revision
- plan revision
- active milestones/packets/workstreams
- open blockers/detours
- resume queue
- control validation status

The packaged `templates/session-start-control.py` is a starting point. It reads `.claude/project-control.json` and optionally invokes a sibling validator.

Do not inject the entire plan into context.

## 2. TaskCreated guard

Use when Claude Tasks are actively used and task conventions are stable.

Purpose:
- reject orphan implementation tasks
- require milestone/Work Packet linkage
- optionally require requirement linkage
- optionally record the active plan revision in description/metadata conventions

Example subject:
`[M3][FR-014][WP-3.4] Fix reconciliation race`

Do not assume one regex fits every task type. Investigation/docs/ops tasks may use explicit alternate conventions.

## 3. TaskCompleted guard

TaskCompleted hooks can block closure when deterministic criteria are not met.

Possible checks:
- task maps to an existing Work Packet
- acceptance criteria have a disposition
- required project validation succeeded
- requirement/control state updated
- discovered work classified
- packet reconciled
- return/resume state resolved
- control validator passes

The hook must inspect project state, not trust the completion narrative.

## 4. Hook design rules

Treat hooks as code:
- review/version them
- keep them fast
- fail with actionable feedback
- avoid destructive actions
- check dependencies before use
- never turn a weak schema into rigid bureaucracy

Hooks enforce only deterministic facts. They do not replace requirements reasoning, architecture judgement, or independent review.

## 5. Example settings

See `templates/settings-control-hooks.example.json` and adapt paths/runtime to the project. Never overwrite existing `.claude/settings.json` blindly; merge intentionally.

## v1.3 gate-awareness

When Control Mode uses gate state, project-specific hooks may additionally check:
- the active packet was planned against a Plan Consistency Gate covering the current baseline/plan revision
- TaskCompleted does not mark a milestone/release complete when Convergence is failed/pending where convergence is required

Do not force a global Convergence check on every small task. Gate enforcement should match project risk and lifecycle boundaries.
