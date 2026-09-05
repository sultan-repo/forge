# Orchestration and Capability Routing Reference

Use this reference to choose an execution mechanism without coupling Forge to model names or temporary platform assumptions.

## 1. Capability-first routing

Never hardcode behavior to:
- a model family/name/generation
- an assumed permanent tool name
- a specific platform version
- the presence of an experimental feature
- a fixed agent roster

Detect capabilities when needed. Route by what the environment actually supports and what the work requires.

## 2. Controller principle

The main/controller context owns objective, canonical requirements/invariants, current revisions, roadmap/control state, approval decisions, integration, reconciliation, and convergence.

Workers own bounded investigation or implementation.

The controller should receive compact conclusions and evidence pointers, not full transcripts or giant logs unless integration requires them.

Worker/reviewer communication is controller-facing evidence. Translate it into concise user-relevant outcomes rather than automatically exposing internal transcripts, phase names, or agent disagreements.

## 3. Routing by capability

### Cohesive local execution
Use the main agent/context for quick changes, tightly coupled edits, user-facing decisions, integration, and reconciliation.

### Context-isolated worker
When supported, use a fresh worker/subagent for large exploration, log/root-cause analysis, independent verification, external research, or a Work Packet likely to flood controller context.

Delegation includes parent packet, requirement/invariant IDs, baseline/plan revisions, allowed/prohibited scope, evidence sources, acceptance, validation, and return expectations.

### Isolated checkout/worktree
When supported, use isolation for parallel editors that might collide. Partition ownership explicitly.

### Collaborative multi-agent mechanism
Use only when workers need peer-to-peer communication, competing hypotheses, cross-layer coordination, or active debate. Do not use collaboration merely because it exists.

### Batch/fan-out mechanism
When supported, consider it for large mechanical changes that split cleanly into independent units. Avoid it for tightly coupled architecture.

## 4. External-agent execution

Forge may optionally invoke external local coding-agent CLIs as bounded execution adapters. This is an execution mechanism under the existing controller, not a second source of project truth.

Keep Forge core role-based:
- `CONTROLLER`
- `IMPLEMENTER`
- `REVIEWER`

Specific agent products belong in execution profiles/adapters, not universal methodology rules.

For implementer/reviewer execution:
- one Work Packet has one implementation owner at a time
- reviewer independence is preserved; the implementer does not select findings or approve itself
- reviewer write access should be denied where the platform supports it
- review targets an immutable Git checkpoint/commit
- baseline and plan revisions travel with the handoff/review
- structured findings return to the controller
- bounded correction/re-review cycles prevent infinite agent ping-pong
- material unresolved disagreement escalates to the human authority
- authentication remains owned by the external CLI; Forge does not copy or store credentials
- if a required reviewer is unavailable, fail visibly or use an explicitly configured risk-appropriate fallback; never silently lower assurance

The bundled local runner is optional. Single-agent Forge must remain usable without any external reviewer installed.

## 5. Graceful degradation

Examples:
- collaboration unavailable -> independent workers or sequential controller
- isolated workers unavailable -> focused single-session packets
- worktree isolation unavailable -> sequential/non-overlapping editing
- lifecycle hooks unavailable -> explicit orientation/reconciliation
- native task system unavailable -> durable Forge Work Packets
- code intelligence unavailable -> targeted search/read navigation
- UI/browser verification unavailable -> structural/manual verification with disclosed limitation
- native batch mechanism unavailable -> manual partitioning
- external reviewer unavailable -> stop when independent review is required, or use only an explicitly approved/configured fallback appropriate to risk

The methodology must remain usable when optional capabilities change or disappear.

## 6. External execution state and recovery

External orchestration may store execution-specific state as an optional extension beside normal Work Packet state, for example:

`pending | implementing | ready_for_review | reviewing | fixing | approved | escalated | reconcile_required`

Delivery status and execution phase are separate concepts. A packet can remain `in_progress` while the external review phase changes.

Persist enough information to recover after interruption:
- packet ID
- baseline/plan revisions
- packet base commit
- implementation/review commit
- review cycle
- latest verdict/findings pointer
- next execution phase

On resume, inspect durable state and actual Git state before restarting work. A saved implementation checkpoint should proceed to review; an external implementation call interrupted before its checkpoint may need to run again. Escalations and revision changes require controller reconciliation. See the [bundled runner guide](../docs/runner.md) for its supported commands and limits.

## 7. Worker return contract

Return:
- packet/question ID
- baseline + plan revisions used
- conclusion/result
- files/components changed or inspected
- evidence/test results
- unresolved uncertainty
- classified adjacent discoveries
- acceptance status
- stale-context warning
- recommended `return_to`

External implementation handoffs additionally record the immutable implementation commit. External review results record the reviewed commit, review cycle, verdict, and structured findings.

If controller revisions differ, reconcile before integration.

## 8. Information-value rule

Every additional worker must answer a distinct bounded question or own an independent deliverable. Stop adding workers when another perspective is unlikely to change the decision or confidence.

## 9. Large-codebase context economy

Prefer whatever current code-intelligence/navigation capabilities are available, plus targeted search, dependency relationships, test references, and small repository maps. Avoid repeated broad directory dumps or giant static repository encyclopedias.
