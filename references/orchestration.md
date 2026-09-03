# Orchestration and Capability Routing Reference

Use this reference when deciding whether work belongs in the main session, subagent, isolated worktree/session, agent team, or batch/fan-out mechanism.

## 1. Controller principle

The main/controller context owns:
- objective
- canonical requirements/invariants
- current baseline/plan revisions
- roadmap/control state
- approval decisions
- integration
- reconciliation
- convergence

Workers own bounded investigation or implementation.

The controller should receive compact conclusions and evidence pointers, not entire worker transcripts, giant logs, or broad file dumps unless integration requires them.

## 2. Routing table

### Main agent
Use for:
- quick/local work
- tightly coupled same-file changes
- decisions needing continuous user interaction
- integration/reconciliation

### Fresh subagent
Use for:
- large repository exploration
- log/root-cause analysis
- independent verification
- external research
- a bounded Work Packet likely to flood controller context

Subagent delegation must include parent packet, requirement/invariant IDs, baseline/plan revisions, allowed/prohibited scope, evidence sources, acceptance criteria, validation, and return expectations.

### Isolated worktree/session
Use when parallel editors might collide or need independent checkouts. Prefer explicit file/component ownership.

### Agent team
Use only when workers need peer-to-peer communication, coordinated shared tasks, competing hypotheses, cross-layer collaboration, or active debate. Agent teams may be experimental/disabled and add coordination/token cost. Do not require them for ordinary work.

### Batch/fan-out
When a supported native batch mechanism is available, consider it for large mechanical/repository-wide changes that can be split into many independent worktree-isolated units. Do not use it for highly coupled architectural work.

## 3. Information-value rule

Every additional worker must answer a distinct bounded question or own an independent deliverable. Stop adding workers when new perspectives are unlikely to change the decision or confidence.

## 4. Capability detection and graceful degradation

Before relying on a feature, determine whether it is available and appropriate.

Fallbacks:
- agent team unavailable -> subagents or sequential controller
- subagents unavailable -> focused single-session Work Packets
- worktrees unavailable -> sequential editing/non-overlapping ownership
- hooks/tasks unavailable -> explicit manual reconciliation/validation
- code intelligence unavailable -> targeted search/read navigation
- browser/UI tooling unavailable -> structural/manual verification and disclose limitation
- batch unavailable -> manually partition independent packets

The methodology must remain usable without optional Claude Code features.

## 5. Worker return contract

A worker returns:
- packet/question ID
- baseline + plan revisions used
- conclusion/result
- files/components changed or inspected
- evidence/test results
- unresolved uncertainty
- discovered adjacent work classified
- whether acceptance criteria are met
- any stale-context warning
- recommended `return_to`

If current controller revisions differ, reconcile before integrating.

## 6. Large-codebase context economy

Prefer symbol/reference navigation, LSP/code intelligence, targeted grep/search, dependency graphs, and small repository maps over repeatedly reading whole directories.

Create a durable repository map only when it materially reduces rediscovery. Do not maintain a giant static encyclopedia that immediately goes stale.
