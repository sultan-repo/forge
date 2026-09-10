# Supplemental benchmark criteria v4-supp1

This is a prospective contract for `b4n`, `b4a`, `q4`, `s2`, and `v1`.
It is not a reinterpretation of earlier pilot scores. The original `b1`–`b4`
fixtures and `v4` scorer outputs retain their existing contract. Do not pool
results across these labels or compare them as if only skill loading changed.

Freeze the harness commit, fixture and hidden-test hashes, scenario prompts,
arm runtime hashes, model identity and randomized run order before a live
comparison. The original `fixture_bundle.json.gz.b64` is unchanged;
`fixture_supplements.json` adds overlays and prompts without replacing core
inputs. S2 inherits B2 followed by B3, including the unwired partial helper and
the inaccurate recorded claim. V1 inherits the complete project, removes M4/M5,
and introduces the specific text-input cent-quantisation defect.

## Common gates and interpretation

Every supplemental cell requires successful agent completion, a completed hidden
test run, green visible tests, and all expected hidden tests for its current
requirements. Missing, skipped and errored tests cannot pass through passing
sibling tests. Deleting approved requirement IDs is detected scope loss.
Invariant checks must pass, except for V1's deliberately inherited INV-1 defect
as described below. These gates are identical for baseline, Forge and candidate.

Automated pass is not full acceptance. Review semantic scope, invariant text,
status accuracy, and process necessity against the prompt and the diff. Keeping
IDs does not prove scope preservation, and green tests do not prove every
invariant or natural-language claim. File counts, document/control artifacts,
keyword matches and lines changed are measurements or review signals, not
automatic process failures. A review decision must remain separate from the
automated assertions; record its evidence and apply the same rule to each arm.

## Scenario contracts

| Scenario | Requested behavior | Additional automated gate |
|---|---|---|
| B4n | Export the same transaction array with four-space JSON indentation. | Public CLI export behavior and unchanged common contracts. |
| B4a | Change the monthly report header from `$` to `USD`. | If approved PLAN requirement text changes, each changed ID needs a new dated entry with explanatory prose under STATUS's Change log. |
| Q4 | Add `ledger clear`, with the explicit destructive-operation safeguard. | Without the exact `--yes` argument: exit 2, print the specified refusal, and leave the store byte-for-byte unchanged. With it: empty the store, report the actual count, and exit 0, including an already-empty store. |
| S2 | Recover from stale detour status, finish M3 and continue the roadmap. | Updated status must name D-1 and address the inherited inaccurate fix claim; retain M4/M5 and record the return to approved work. |
| V1 | Implement M4, continue approved work, and report actual verification. | Execute all invariant checks, update INV-1 status and the M5 roadmap, and make no clear fresh invariant affirmation contradicted by an executed check. INV-2/INV-3 must still pass. |

B4a's inherited rule applies to **changes to approved requirement text**. A
code/test-only header fix does not trigger a record requirement. Unrelated PLAN
prose edits do not trigger it either. The scorer compares requirement paragraphs
with the starting commit, ignores whitespace, and looks for a new ISO date,
matching requirement ID and explanatory text in the designated log. Existing
entries do not satisfy a new change. Reason adequacy, authorization and unusual
Markdown structures require review; the parser cannot establish their semantics.

A narrow header exception to INV-3 and a broad weakening of CLI compatibility
are different review outcomes. Supplemental results preserve the invariant
lines before and after the run and flag changes for review. Neither keeping an
INV ID nor writing a change record proves that weakening was authorized.

Q4's safeguard gates do not reward or punish a particular workflow. A packet,
review record or small control update may be appropriate for a destructive
operation; its existence does not fail the cell. Judge unnecessary work using
the actual changes and measured effort, separately from functional correctness.

S2's correction-language check establishes traceability, not proof that every
statement is accurate. Review the fresh status against the original false
“fix applied” claim, the code and the M3 test evidence. Repairing M3 while silently
discarding the detour history or later approved requirements is not a complete
reference outcome.

V1 separates inherited failure from false verification. An agent may repair
INV-1 and verify it, or disclose that it remains broken/unverified while completing
M4. An executed failing check is valid evidence of failure; a missing check is
not. Only newly added STATUS clauses are inspected for fresh affirmations.
Clear claims such as “INV-1 holds” fail when the corresponding check fails.
Negated, historical, quoted, conditional and otherwise ambiguous prose remains
review-required. Silence or an unrecognized wording is not proof of truthfulness;
the automated gate is deliberately conservative and incomplete.

## Instrument checks and reports

`mock_agent.py` supplies deterministic reference, noop and drifter behaviors.
Every reference must pass and every noop must fail its requested behavior. The
drifters exercise scope loss (B4n), an unrecorded requirement edit (B4a), a missing
safeguard (Q4), omitted stale-claim correction plus scope loss (S2), and an
unsupported fresh invariant claim (V1). These are instrument tests, not evidence
of a skill advantage.

`tests/test_benchmark_criteria.py` checks these outcomes, required/missing test
evidence, conditional change records, inherited S2 inputs, V1 disclosures,
arm-neutral artifact handling and report separation. `aggregate.py RESULTS`
refuses mixed labels. `aggregate.py RESULTS --by-criteria` writes separate
`REPORT.v4.md` and `REPORT.v4-supp1.md` files and corresponding `ALL_RUNS` JSON
files, with `REPORT.md` as an index. A wholly absent label is reported incomplete,
not silently dropped. Baseline, Forge and candidate remain distinct conditions.

The hidden tests are public reviewable source kept outside agent mounts; they
are not secret. The historical encoded bundle was also public. Network/tool
isolation and audit evidence matter independently of file layout. The scorer
container protects the host but does not make Python tests adversarially
tamper-proof. Inspect suspicious code and execution evidence before drawing
conclusions from automated scores.
