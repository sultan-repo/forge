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

## 4. Graceful degradation

Examples:
- collaboration unavailable -> independent workers or sequential controller
- isolated workers unavailable -> focused single-session packets
- worktree isolation unavailable -> sequential/non-overlapping editing
- lifecycle hooks unavailable -> explicit orientation/reconciliation
- native task system unavailable -> durable Forge Work Packets
- code intelligence unavailable -> targeted search/read navigation
- UI/browser verification unavailable -> structural/manual verification with disclosed limitation
- native batch mechanism unavailable -> manual partitioning

The methodology must remain usable when optional capabilities change or disappear.

## 5. Worker return contract

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

If controller revisions differ, reconcile before integration.

## 6. Information-value rule

Every additional worker must answer a distinct bounded question or own an independent deliverable. Stop adding workers when another perspective is unlikely to change the decision or confidence.

## 7. Large-codebase context economy

Prefer whatever current code-intelligence/navigation capabilities are available, plus targeted search, dependency relationships, test references, and small repository maps. Avoid repeated broad directory dumps or giant static repository encyclopedias.
