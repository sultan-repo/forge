# Scope and Plan Control Reference

Load for Planned/High-Risk/multi-milestone work, deep detours, roadmap modifications, parallel workstreams, or suspected drift.

## 1. Control invariants

### Scope Conservation
No confirmed material requirement, approved milestone, or accepted work item disappears without an authorized terminal disposition.

### Authority Conservation
Changing a status does not authorize changing scope. For approved material items, `deferred`, `rejected`, `cancelled`, or `superseded` requires a Plan Delta and the same authority that the underlying scope change would require.

Required disposition metadata:
- reason/evidence
- Plan Delta ID
- affected requirements/milestones
- replacement mapping when applicable
- authority level
- approval evidence/decision reference when required

### Parent Conservation
Every Work Packet/detour has a parent milestone or packet unless explicitly approved as a new top-level roadmap item.

### Return Conservation
Every non-terminal child/detour has a valid `return_to`. Finishing local work returns control to the approved plan.

### Coverage Conservation
At milestone boundaries every approved material requirement maps to an allowed status and an owner/location/disposition.

### Revision Conservation
Every Work Packet/delegated worker records both the requirements-baseline revision and `plan_revision` it started against. Results from stale revisions must be reconciled/rebased before integration.

## 2. Canonical states

Requirement status:
- `planned`
- `in_progress`
- `satisfied`
- `deferred`
- `rejected`
- `superseded`

Milestone / Work Packet status:
- `planned`
- `in_progress`
- `blocked`
- `done`
- `deferred`
- `cancelled`
- `superseded`

Terminal requirement states: `satisfied`, `deferred`, `rejected`, `superseded`.
Terminal milestone/packet states: `done`, `deferred`, `cancelled`, `superseded`.

## 3. Revision model

Maintain:
- `baseline_id`
- `baseline_revision`
- `plan_revision`

Increment `baseline_revision` when confirmed material requirements change.
Increment `plan_revision` whenever an accepted Plan Delta changes roadmap structure/sequence/dependencies.

Every Work Packet stores:
- `baseline_revision`
- `plan_revision`

Every delegated worker should return the revisions it used.

If worker revision != current revision:
1. mark result stale-for-integration
2. compare what changed
3. determine whether conclusions remain valid
4. adapt/rebase/revalidate as needed
5. integrate only after reconciliation

Stale does not mean useless. It means "must be reconciled before integration."

## 4. Parallel-capable control state

Do not assume one active milestone or packet.

Recommended top-level fields:
- `active_milestones`: array
- `active_work_packets`: array
- `resume_queue`: ordered array of approved next actions

Each Work Packet may include:
- `workstream`
- `owner`
- `dependencies`
- `parent`
- `return_to`

The controller may have several active packets when independent work is genuinely parallel. Each editing context still owns a bounded packet and must reconcile its result.

## 5. Work Packet

Suggested shape:

```text
WP-3.4: Fix transaction reconciliation race
Parent: M3
Requirements: FR-014, NFR-006
Baseline revision: 3
Plan revision: 12
Workstream: payments
Owner: main / agent-id
Objective: Prevent duplicate reconciliation under concurrent callbacks.
In scope: locking + concurrency regression
Out of scope: general payment refactor, retry redesign
Acceptance: reproduce race, confirm root cause, regression passes
Validation: targeted concurrency + related suite
Return to: WP-3.5
```

Packets should be small enough to complete and reconcile coherently.

## 6. Discovery classifier

When implementation exposes new work:
- **Required child:** needed for current acceptance; create child packet.
- **Blocking detour:** current packet cannot proceed; create blocker child with return target.
- **Adjacent improvement:** useful but unnecessary now; record TODO/deferred.
- **Material direction change:** Plan Delta + decision authority.
- **Unrelated:** do not implement now.

## 7. Plan Delta

A Plan Delta changes the active plan lineage; it does not erase history.

Record:
- ID
- trigger/evidence
- previous plan revision
- new plan revision
- proposed/accepted change
- affected requirements/milestones/packets
- additions/moves/dispositions
- dependency/schedule impact
- replacement mapping
- decision authority
- approval reference when required

For a baseline-changing delta, also increment baseline revision and record the requirement change.

## 8. Reconciliation gate

After every meaningful packet:
- acceptance met/dispositioned?
- validation recorded?
- linked requirements/invariants updated?
- discovered work classified?
- Plan Delta needed/applied?
- baseline/plan revision current?
- stale worker results reconciled?
- all approved requirements still mapped?
- all approved milestones still present/dispositioned?
- children/detours closed/deferred/continued with parent+return?
- code/docs/control state agree?
- control validator passes where enabled?
- resume queue refreshed?

Do not begin another major packet before reconciliation.

## 9. Drift alarms

Force reconciliation when:
- more than one significant detour opens from a packet
- repeated failed approaches accumulate
- architecture changes outside packet scope
- new requirements appear during coding
- current work no longer maps to approved scope
- an approved item seems to vanish
- current baseline/plan revision is unclear
- a delegated result returns against an old revision
- resume queue cannot be stated immediately
- compaction happens during a detour

## 10. Controller / worker separation

Keep main controller context focused on objective, baseline, revisions, plan, active packets, decisions, integration, reconciliation, and resume queue.

Delegate verbose bounded work when useful. Delegation must include:
- parent/packet
- requirement/invariant IDs
- baseline + plan revisions
- scope/prohibited scope
- relevant primary evidence
- acceptance/validation
- return expectations

For parallel editors, use isolated ownership/worktrees.

## 11. Machine validation

Use the packaged control-state example/schema/validator as a starting point. Adapt when the project needs different fields, but preserve the invariants.

The generic validator checks structural accounting, not business truth. Passing it never proves requirements are correct.

## 12. Work Packet sizing

A packet is too large when any of these are true:
- it contains multiple independently testable objectives
- it spans materially unrelated system areas
- different parts can fail/ship independently
- acceptance cannot be expressed as one coherent outcome
- validation requires several unrelated strategies
- expected exploration/implementation is likely to exhaust worker context and obscure original acceptance criteria

Split before implementation. Do not split merely to satisfy an arbitrary task-count target.

## 13. Canonicalization and archival

Plan Deltas preserve history, but future sessions should not replay an ever-growing delta log to reconstruct current truth.

At sensible milestone/release boundaries after relevant convergence:
1. merge accepted requirement changes into canonical requirements
2. merge accepted design/architecture changes into canonical architecture/decisions
3. update the canonical active roadmap
4. confirm `baseline_revision` / `plan_revision`
5. archive closed Plan Deltas with their evidence/approval references
6. keep only active/open deltas prominent in current control state

Never destroy audit history. The goal is compact current truth plus preserved historical lineage.
