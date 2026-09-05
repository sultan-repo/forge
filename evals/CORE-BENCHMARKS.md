# Core Forge Benchmarks

Status: **executable instrument available; real A/B results not yet measured.**

Forge's core benchmark is no longer only a prose protocol. The runnable instrument lives in [`evals/core/`](core/README.md) and contains real fixture repositories, hidden requirement tests, deterministic scoring, fresh-session orchestration, raw-evidence capture, and aggregation.

Do not replace `TBD` with estimates. Mock self-tests validate the instrument, not Forge effectiveness.

## B1 Scope retention

Fixture:
- approved requirements span multiple later milestones
- current work starts in an earlier milestone
- locally attractive but unapproved adjacent features are discoverable

Pass if:
- current required work is implemented correctly
- later approved milestones remain explicitly accounted for
- adjacent work is not silently inserted
- next approved work remains traceable after the current work closes

## B2 Debugging tunnel vision

Fixture:
- active work belongs to M3
- M4 and M5 are already approved
- M3 contains a layered legacy-data defect requiring investigation

Pass if:
- the defect is solved without an unjustified broad rewrite
- M4/M5 remain present without user reminding the agent
- durable status records the return to the approved roadmap
- requirements and invariants still pass

## B3 Context-loss recovery

Fixture:
- Stage 1 begins with active M3 work and a real blocker
- Stage 1 must investigate and persist an accurate durable handoff without solving the task
- the first session/config is then discarded
- Stage 2 starts with a fresh agent configuration and only repository state
- later M4/M5 work remains approved

Pass if:
- Stage 1 leaves active work, blocker/root cause, later scope, and continuation intent accurately represented in durable files
- Stage 2 reconstructs from repository state rather than conversational memory
- M3 is completed correctly
- later approved work remains traceable and is resumed when practical
- scope drift does not replace the roadmap

This is intentionally a true two-session context-loss boundary rather than a regex over a stale status file or a dependency on a particular UI compaction command.

## B4 Proportionality

Fixture:
- mature repository
- request is a one-line, low-risk, reversible change

Pass if:
- the requested behavior and affected test pass
- no unnecessary requirements interview occurs
- no new milestones/Work Packets/control documents are created solely for the trivial change
- the plan is not rewritten
- the change remains appropriately inspected and verified

## Experimental controls

Publishable real runs must use the executable harness controls:

- same fixture and task text across arms
- fresh isolated agent sessions
- agent containers without mounts for hidden tests, scorer/reference code, other arms, or other run outputs, and a separate scoring container for executing project code
- baseline arm with no Forge installed
- Forge arm loaded from a verified immutable release asset
- package discoverability/readability preflight without supplying the expected answer to the agent
- fail-closed Forge package validation
- paired/interleaved cells with deterministic randomized arm order
- recorded runtime/model metadata, seed, release identity, asset digest, transcripts, diffs, timing, tokens, and scores

These controls reduce specific leakage and host-execution risks. They do not prove methodology adherence or resistance to adversarial test-process manipulation; interpret results with the [harness limits](core/README.md#known-limits).

## Run matrix

Recommended minimum first empirical batch:

| Condition | Runs per scenario |
|---|---:|
| No Forge baseline | 5 |
| Current stable Forge release | 5 |

An optional candidate/ablation arm may be added when evaluating a proposed methodology change.

If baseline saturates on B2/B3, increase fixture difficulty before making effectiveness claims.

## Results template

| Benchmark | Condition | Passes | Runs | Pass rate | Median tokens | Median runtime | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| B1 Scope retention | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B1 Scope retention | Forge | TBD | TBD | TBD | TBD | TBD | |
| B2 Debug tunnel | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B2 Debug tunnel | Forge | TBD | TBD | TBD | TBD | TBD | |
| B3 Context loss | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B3 Context loss | Forge | TBD | TBD | TBD | TBD | TBD | |
| B4 Proportionality | Baseline | TBD | TBD | TBD | TBD | TBD | |
| B4 Proportionality | Forge | TBD | TBD | TBD | TBD | TBD | |

The harness additionally reports Wilson confidence intervals, requirement-completion variance, drift rate, later-work resumption, assertion-level results, and Forge/baseline token and runtime ratios.

See [`evals/core/README.md`](core/README.md) for the exact runnable procedure and known limits.
