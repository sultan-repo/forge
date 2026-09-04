# Claude Code Integration Reference

Forge is a project-control methodology layered on top of the coding agent's native capabilities. It should reuse current platform primitives instead of recreating them in prose.

## Capability-first rule

Never choose behavior because of a hardcoded model name, model generation, Claude Code version, or an assumed permanent tool name.

At the point of use:

1. inspect/detect what the current environment supports
2. prefer the native capability that best fits the work
3. use it only when it improves correctness or context economy
4. fall back to a simpler mechanism when unavailable
5. record any limitation only when it materially affects confidence or execution

Examples below describe capability classes. Product names may change over time.

## Planning / read-only planning capability

Use a native plan/read-only mode when available for investigation and architecture work that should not modify product files.

Forge adds requirements readiness, objective/requirement traceability, Plan Consistency, and explicit authority for material plan changes.

Fallback: perform the same planning discipline in the main session without edits until planning is approved.

## Task/work-item capability

When a native task system is available and useful, map tasks to Forge milestones/Work Packets instead of creating a competing task universe.

Forge adds requirement linkage, baseline/plan revision awareness, parent and `return_to`, detour classification, and reconciliation.

Fallback: keep Work Packets in durable Forge control state.

## Persistent instructions / memory

Use project instructions/rules for concise durable invariants and operating constraints. Do not dump the full Forge skill into project memory.

Forge defines the project truth worth preserving: objective, requirements/invariants, decisions, current plan/revisions, active work/resume state, and validation/gate state.

## Lifecycle hooks

When supported, hooks can deterministically inject orientation or block invalid lifecycle transitions.

Forge prefers:
- session-start reorientation for Control Mode
- task-completion guards only when a task lifecycle exists
- stop/completion guards only when genuine closure can be distinguished from normal pauses
- tests/CI/schema/permissions for domain correctness

Fallback: explicit orientation and reconciliation steps in the controller.

## Context-isolated workers

Use isolated workers for bounded exploration, verification, or implementation when they reduce controller pollution.

Forge adds Work Packet boundaries, revision stamps, stale-result detection, compact return contracts, and controller reconciliation.

Fallback: one focused main-session packet at a time.

## Worktree / parallel-edit isolation

Use native isolation when multiple editors can proceed independently. Forge adds scope ownership and convergence back into one canonical plan.

Fallback: sequential editing or explicit non-overlapping ownership.

## Agent collaboration

Use collaborative multi-agent mechanisms only when workers genuinely need peer communication, competing hypotheses, or cross-layer debate. Forge adds the stopping rule and controller responsibility.

Fallback: independent workers returning to one controller, or sequential analysis.

## Verification / review / goal capabilities

Use native verification, review, or goal mechanisms when available, but define their target from Forge requirements and acceptance criteria.

Forge adds spec compliance before general quality, requirement coverage, Convergence at major closure, and scope-aware review triage.

Fallback: run repository checks, inspect runtime behavior, and perform explicit Forge convergence review.

## Principle

Native capabilities are execution primitives. Forge supplies the control model that keeps those primitives aligned with project intent.
