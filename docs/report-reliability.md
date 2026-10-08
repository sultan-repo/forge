# Implementation reports and correction reviews

The optional local runner preserves what an implementer reports without turning
that report into proof. This change adds no project gate, service, telemetry,
provider request, or canonical-state migration. Quick Task routing, explicit
review policies, checkpoint isolation, and the independent reviewer's read-only
sandbox remain unchanged. Native Windows execution is a separate follow-on.

## Producer contract and normalization

The producer contract is [`implementation-report.schema.json`](../templates/implementation-report.schema.json).
The implementation prompt includes non-empty examples of validation and discovery
objects from the same example exercised by regression tests. Validation objects
require a `claim`; discovery objects require a `summary`. Commands and results are
optional when unknown. Empty arrays are valid when there is nothing to report.

The parser accepts direct JSON, the Claude JSON transport's `result` string, and
an exact surrounding JSON code fence. Legacy strings become `{"claim": "..."}`
or `{"summary": "..."}` individually. Valid siblings survive malformed entries.
Unsupported entries remain visible as `unparsed_value`, while the complete original
retains unknown fields and values that cannot fit the normalized contract.
Normalization never invents a command, exit code, outcome, provenance, or tested revision.

`agent_report_structured` and `report_format` describe the producer format, not
implementation success. `normalization_issues` explains compatibility conversions
and malformed fields. `implementation_outcome: adapter_completed` means only that
the implementation adapter returned without an execution error. It does not mean
the acceptance criteria or tests passed. All handoff results remain implementer claims.

## Private originals and report-only recovery

Before parsing or post-agent control/revision/eligibility checks, the runner saves
the exact stdout string returned by the adapter under
`.claude/forge/runtime/reports/WP-ID-attempt-NN-<unique>.stdout.txt`. Files are
created privately and flushed to disk. Each invocation has a unique filename, so
a resumed attempt cannot replace the previous original. A normalized `.stdout.json`
sidecar and the handoff carry a local path and SHA-256 content fingerprint.
These fingerprints detect content differences; they are not signatures or proof of origin.

Reported Claude failures retain returned stdout too. Abrupt termination before the
adapter returns a result is not a complete output-capture guarantee. Existing
process cleanup and interrupted-implementation recovery rules still apply.

Runtime is excluded from Git by the normal runner setup. Originals can contain
sensitive project or provider output. Keep them local; do not publish them as part
of a source commit. They are controller-local and are not copied into the detached
review checkout. The reviewer receives normalized claims, not a duplicate raw log.

For an older malformed handoff, recover a saved original without calling an agent:

```bash
python3 "$FORGE_DIR/scripts/implementation_report.py" path/to/original.stdout.txt
```

The command writes normalized JSON to stdout, including the original input. It
requires no provider, Git repository, profile, or canonical control state. It does
not modify the original file, replace a handoff, advance execution, or approve work.
The controller can inspect the recovered claims and reconcile evidence normally.
Already completed implementation is not rerun merely to fix report formatting.
Reports discarded by older versions cannot be reconstructed without an original.

## Evidence references and repeated checks

A validation entry may include an `evidence` object with `reported_origin`,
`tested_commit`, `command`, `cwd`, `environment_identity`, `dependency_identity`,
`result`, and `artifact`. Supply only actual known metadata. In particular, a test
run before later edits must not be labeled with the final implementation checkpoint.

The handoff's `validation_evidence` projection classifies references as:

- `stale_checkpoint`: the reported tested checkpoint differs from the checkpoint under review.
- `incomplete_metadata`: required applicability metadata is missing.
- `requires_verification`: metadata matches, but origin, artifact contents, environment, outcome, and limitations still need verification.

All three are explicitly **unverified implementer-supplied references**. The runner
does not fetch artifacts, execute referenced commands, grant verified status, or
automatically suppress tests. Matching metadata alone does not establish trust.
The reviewer may reuse an authoritative result after checking its primary artifact
and exact-checkpoint applicability. Cross-commit reuse and automatic test selection
are not implemented here.

Repeat checks for changed relevant inputs, unresolved failures, flakiness diagnosis,
or a distinct platform/boundary, rather than simply because another agent ran them.
A sandbox capability limitation is not a product defect. Use existing evidence or
an authorized executor when necessary, retaining independent judgment. Missing
material assurance still blocks approval; sandboxing is never relaxed to obtain it.

## Corrections and approval

A `PASS` with an unresolved `current_required` or `current_blocking` finding is
contradictory at any severity. The runtime validator rejects it. Severity does not
decide whether an approved requirement has been satisfied. Adjacent, future, and
unrelated findings remain deferred and do not silently enter implementation scope.
A changed requirement needs an authorized, recorded disposition.

Correction reviews receive the preceding validated review's current findings and
checkpoint, and start with the correction diff and affected contracts. The complete
packet diff remains available; review is not restricted to changed lines. A saved
review with mismatched identity is rejected. If an older execution has no preceding
review artifact, the runner falls back to a full independent review rather than
pretending the correction history is known. Cycle limits and reconciliation still apply.

## Compatibility and verification limits

Existing control state, execution state, and saved version-1 handoffs remain readable.
New handoff fields are optional additions to the version-1 handoff schema. Consumers
pinned to the previous strict schema must update that schema before validating new
handoffs. No bulk migration or runtime-history rewrite is required. Unversioned
reports are normalized as legacy input and are not labeled compliant with the new
producer contract.

Regression tests cover lossless normalization, private original preservation across
failure paths, report-only recovery, evidence applicability, approval contradictions,
and correction/review retries. Runner integration uses real local Git checkpoints
and fake adapters; it is not a live-provider evaluation. The three scenarios in
[`report-reliability.json`](../evals/report-reliability.json) specify behavioral
expectations and have not been executed as real-agent sessions. No lower cost,
shorter delivery time, or improved live-agent behavior is claimed from these tests.
