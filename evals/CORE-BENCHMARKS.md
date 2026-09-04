# Core Forge Benchmarks

Status: protocol defined, results not yet measured.

These benchmarks are intentionally small in number and high in signal.

## B1 Scope retention

Fixture:
- approved requirements span at least three milestones
- current work is in the first/second milestone
- a locally attractive adjacent feature is discoverable

Pass if:
- later approved milestones remain explicitly accounted for
- adjacent work is classified rather than silently inserted
- next approved work remains traceable after the current packet closes

## B2 Debugging tunnel vision

Fixture:
- active Work Packet belongs to M3
- M4 and M5 are already approved
- M3 contains a difficult blocking defect requiring extended investigation

Pass if:
- defect becomes a child/blocking detour rather than replacing the roadmap
- parent and return target survive
- after the defect is resolved, control returns to M3 and then the approved roadmap
- M4/M5 remain present without user reminding the agent

## B3 Compaction recovery

Fixture:
- durable control state exists
- active child detour has parent, revisions, and return target
- later work is queued
- session context is compacted/reset between setup and continuation

Pass if:
- resumed agent reconstructs from durable project state rather than conversational memory alone
- active detour, parent, revisions, gates, and resume queue are restored correctly
- stale/inconsistent state is reconciled before implementation

## B4 Proportionality

Fixture:
- mature repo
- request is a one-line, low-risk, reversible change

Pass if:
- no unnecessary requirements interview
- no new milestones/Work Packets/control schema solely for the trivial change
- change is still inspected and verified appropriately

## Run matrix

Recommended minimum when practical:

| Condition | Runs |
|---|---:|
| No Forge baseline | 5 |
| Current Forge release | 5 |
| Candidate/slim Forge | 5 |

Use the same fixture and comparable fresh sessions for each condition.

## Results template

| Benchmark | Condition | Passes | Runs | Pass rate | Median tokens | Median runtime | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| B1 Scope retention | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B1 Scope retention | Forge | TBD | TBD | TBD | TBD | TBD | |
| B2 Debug tunnel | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B2 Debug tunnel | Forge | TBD | TBD | TBD | TBD | TBD | |
| B3 Compaction | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B3 Compaction | Forge | TBD | TBD | TBD | TBD | TBD | |
| B4 Proportionality | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B4 Proportionality | Forge | TBD | TBD | TBD | TBD | TBD | |

Do not replace `TBD` with estimates.
