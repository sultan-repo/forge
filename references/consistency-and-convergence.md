# Plan Consistency and Implementation Convergence Reference

Use this reference for Planned/High-Risk work before coding and at major milestone/release/project closure.

## 1. Why two gates exist

Packet reconciliation prevents implementation from drifting away from the plan.

The **Plan Consistency Gate** prevents the plan from drifting away from the specification before coding.

The **Convergence Gate** checks the implemented system against the approved specification and design using the available evidence. Its confidence is limited by that evidence; a recorded gate status is not proof by itself.

Together:

`Requirements -> Consistent Plan -> Bounded Implementation -> Reconciliation -> Converged System`

## 2. Plan Consistency Gate

Run after material requirements, architecture, milestones/tasks/Work Packets, acceptance criteria, and validation strategy are available but before significant implementation.

Read-only checks:

### Requirement coverage
- every approved material requirement maps to at least one milestone/packet or explicit terminal disposition
- no requirement exists only in prose with no delivery path
- non-functional/security/operational requirements are included where applicable

### Invariant protection
- every invariant has an enforcement/verification strategy
- architecture does not make an invariant impossible or ambiguous

### Plan integrity
- every milestone maps to objective/requirements
- every implementation packet has a parent and legitimate requirement/technical rationale
- no orphan implementation tasks
- dependencies and sequence are coherent
- migrations/compatibility/rollback are represented where required

### Acceptance and verification
- every material packet has measurable acceptance criteria
- acceptance criteria are actually verifiable
- required user-facing journeys have acceptance scenarios where useful
- required validation is feasible with available tools/environment

### Decision consistency
- architecture and plan do not contradict confirmed requirements/decisions
- approval-required decisions are resolved before dependent work
- high-impact assumptions are explicit

### Scope discipline
- plan contains no material unapproved feature expansion
- proposed optimizations/cleanup are either linked to requirements or classified separately

## 3. Gate result

Return:
- `PASS`
- `PASS_WITH_EXPLICIT_GAPS`
- `FAIL`

A material contradiction, uncovered requirement, unprotected invariant, or unresolved approval-required dependency fails the gate.

Record the gate against the current `baseline_revision` and `plan_revision`. A later material baseline/plan change invalidates the old gate for affected work and requires targeted re-analysis before dependent implementation.

## 4. Assumption checkpoint

Before a large/expensive milestone, summarize only assumptions capable of invalidating substantial planned work.

For each high-impact assumption record:
- assumption
- evidence/confidence
- impact if false
- how/when it will be validated
- whether user approval is required

Do not create an assumption ceremony for low-risk reversible details.

## 5. Convergence Gate

At major milestone, release, or project completion compare:
- canonical requirements/invariants
- applicable architecture/decisions
- approved current plan
- actual source/config/schema/infrastructure/UI
- tests/runtime/operational evidence

Evaluate five dimensions:

### Completeness
Every approved requirement is implemented or explicitly dispositioned with proper authority.

### Correctness
Actual behavior satisfies the requirement and acceptance scenario, not merely a task description.

### Coherence
Implementation respects applicable architecture decisions, invariants, data contracts, operational model, and migration decisions.

### Excess scope
Identify material behavior/capability introduced without approved requirement or legitimate technical necessity.

### Evidence
Claims are supported by appropriate tests, runtime observations, static checks, UI verification, logs/metrics, or other evidence proportional to risk.

## 6. Gap handling

Classify gaps:
- Missing implementation
- Partial implementation
- Contradictory implementation
- Missing evidence
- Architecture divergence
- Unapproved excess scope
- Stale documentation/control state

A gap does not authorize silent scope change.

For material gaps:
- create linked Work Packet, or
- create approval-controlled Plan Delta if the requirement/design should change, or
- explicitly accept/defer according to authority rules

Then rerun targeted convergence.

## 7. Convergence result

Return:
- `CONVERGED`
- `CONVERGED_WITH_EXPLICIT_ACCEPTED_GAPS`
- `NOT_CONVERGED`

Do not claim completion because all planned packets are done if the actual system still fails the canonical requirements.
