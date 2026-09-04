# Worked Example: Forge Control in Practice

This example is illustrative, not a mandatory project structure or naming scheme.

## Scenario

A user asks:

> Build a small service that imports CSV expenses, categorizes them, and shows a monthly summary. Unknown categories must be reviewable.

After requirements enrichment, Forge confirms:

- FR-001: import valid CSV expense rows
- FR-002: categorize recognized merchants
- FR-003: place uncertain rows into Review
- FR-004: show monthly category totals
- INV-001: never silently discard an imported row

Plan:
- M1 Import pipeline
- M2 Categorization and Review
- M3 Monthly summary

## Control state after planning

```json
{
  "version": 3,
  "baseline_id": "RB-1",
  "baseline_revision": 1,
  "plan_revision": 1,
  "active_milestones": ["M1"],
  "active_work_packets": ["WP-1.1"],
  "resume_queue": ["WP-1.2", "M2", "M3"],
  "requirements": {
    "FR-001": {"status": "in_progress", "milestone": "M1", "work_packets": ["WP-1.1"]},
    "FR-002": {"status": "planned", "milestone": "M2", "work_packets": []},
    "FR-003": {"status": "planned", "milestone": "M2", "work_packets": []},
    "FR-004": {"status": "planned", "milestone": "M3", "work_packets": []}
  },
  "milestones": {
    "M1": {"status": "in_progress", "requirements": ["FR-001"]},
    "M2": {"status": "planned", "requirements": ["FR-002", "FR-003"]},
    "M3": {"status": "planned", "requirements": ["FR-004"]}
  },
  "work_packets": {
    "WP-1.1": {
      "status": "in_progress",
      "parent": "M1",
      "requirements": ["FR-001"],
      "baseline_revision": 1,
      "plan_revision": 1,
      "dependencies": [],
      "return_to": "WP-1.2",
      "acceptance_status": "pending",
      "validation_status": "pending",
      "reconciled": false
    }
  },
  "plan_deltas": [],
  "archived_plan_deltas": [],
  "canonicalized_through_plan_revision": 1,
  "gates": {
    "plan_consistency": {"status": "passed", "baseline_revision": 1, "plan_revision": 1},
    "convergence": {"status": "pending", "baseline_revision": 1, "plan_revision": 1}
  },
  "last_reconciliation": {"work_packet": null, "plan_revision": 1, "coverage_ok": true, "open_detours": []}
}
```

## Work Packet

`WP-1.1` objective: parse CSV rows and persist every valid row.

Acceptance:
- valid rows are imported once
- malformed rows produce an explicit import error
- zero valid rows are silently lost
- regression tests cover duplicates and malformed rows

Validation:
- parser tests
- import integration test
- row-count reconciliation

Return target: `WP-1.2`.

## Discovery during implementation

During `WP-1.1`, a production-sized fixture reveals that some CSV exports contain duplicate transaction IDs.

Do not let the discovery replace M2 and M3.

Classify it:

- it blocks FR-001 acceptance because duplicate handling affects import correctness
- create child/blocking detour `WP-1.1.1`
- parent: `WP-1.1`
- return_to: `WP-1.1`
- same baseline revision 1 / plan revision 1

The detour determines that duplicates should be idempotently ignored while conflicting duplicate IDs must be surfaced as errors.

That changes intended import behavior, so Forge proposes a Plan Delta.

## Plan Delta

```json
{
  "id": "PD-001",
  "from_plan_revision": 1,
  "to_plan_revision": 2,
  "reason": "Define duplicate transaction-ID behavior required for FR-001 correctness",
  "affected_requirements": ["FR-001"],
  "decision": "Ignore byte-equivalent duplicate rows; surface conflicting duplicate IDs",
  "authority_level": "proceed_and_record"
}
```

After acceptance, `plan_revision` becomes 2. Any worker still operating against revision 1 is stale for integration until reconciled.

## Reconciliation

After `WP-1.1.1`:

1. regression tests pass
2. FR-001 acceptance now includes duplicate behavior
3. `WP-1.1.1` is marked done and reconciled
4. control returns to `WP-1.1`
5. `WP-1.1` completes its remaining validation
6. M2 and M3 remain present in the resume queue

The local problem was solved without becoming the new roadmap.

## Resume index before compaction

```text
Forge orientation
Baseline: RB-1 rev 1
Plan: rev 2
Current milestone: M1
Active packet: WP-1.1
Closed detour: WP-1.1.1 -> returned to WP-1.1
Plan consistency: rechecked for PD-001 and passed
Next: finish WP-1.1 validation, then WP-1.2
Later milestones preserved: M2, M3
```

After compaction or a fresh session, Forge reloads durable state, checks the current code/diff, verifies revisions, then resumes from that orientation instead of relying on conversational memory.

## What this example teaches

- a Work Packet is bounded implementation, not just a task name
- a detour has a parent and return path
- material plan change is explicit and revisioned
- stale workers are detectable
- reconciliation returns control to the roadmap
- durable state preserves later milestones across context loss
