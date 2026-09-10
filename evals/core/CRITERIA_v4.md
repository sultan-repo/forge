# Core benchmark criteria v4

Status: prospective scorer revision. No live model results have been collected
under this revision in this change. Freeze this file, scorer source, fixture
bundle, editable hidden tests, prompts, runtime identities, model, and run order
before a comparison. A later criteria change needs a new version and separately
labelled results.

## What an automated pass means

Every cell requires a successful agent execution, completed hidden-test runner,
green visible tests, all hidden tests for the current requirements, all declared
invariant tests, and retention of approved requirement IDs in PLAN. B1–B3 also
check the requested later-work traceability and status update. B3 requires its
first-stage handoff checks before a genuinely fresh second session.

An automated pass is **not** a complete judgment of scope, state accuracy,
proportionality, or Forge effectiveness. Those review fields remain explicitly
unresolved. Do not call the candidate ready or a semantic claim verified solely
because these gates pass.

## Executable evidence

- `hidden/` is the editable source of scoring tests. The compressed fixture
  bundle's historical hidden section is retained as archival data and is no
  longer read by this scorer. Neither source is mounted into the candidate
  filesystem. The [network boundary](NETWORK.md) restricts retrieval during runs;
  public source and provider/model knowledge are not secret test material.
- Tests exercise contracts named in PLAN: public CLI operations, `Transaction`,
  `Store`, `report.monthly_totals`, and `budgets.load_budgets`. A private formatter,
  importer helper, module allowlist, or use of a particular internal design is
  not a requirement.
- Expected test names are enumerated from the source before execution. Missing,
  skipped, and errored tests cannot yield a passing requirement or invariant.
  Incomplete later-milestone evidence cannot yield completion, and does not by
  itself fail the current task. Hidden tests import optional later APIs inside
  their tests so an absent later module does not interrupt current-task collection.
- CSV evidence covers quoted embedded newlines and duplicate identity. INV-1
  checks the amount actually persisted by `ledger add`, as well as the loaded
  value. Budget checks include numeric JSON limits and an exact-cent excess.
- Passing later requirements describes final implementation evidence. It is not
  proof of work resumed in this session; compare the starting tree and changes.

These fixtures can contain an inherited invariant defect. A failing final check
is a defect left unresolved, not evidence that an arm introduced it. Attribute a
regression only after comparing the initial fixture with the resulting behavior.

## Scope, state, and process

Requirement-ID retention detects a narrow form of scope loss. It cannot establish
that requirement text or an invariant was preserved semantically. Code keywords,
new module names, file counts, and lines changed are measurements or review
signals, never semantic scope verdicts.

B3 handoff keywords establish only that specified subjects are mentioned. They
do not prove that the handoff is truthful. Review claims against observed checks,
source and diffs, including negation, uncertainty, stale claims, and approved
dispositions. A completion word or an updated status document cannot satisfy a
requirement. Record the evidence and disagreement when human review is needed.

B4's request authorizes the `$` to `USD` report-header change and its test.
Synchronizing directly contradicted requirement text in an existing document is
permitted. Preserve the invariant outside that specific change. The fixture has
no unconditional requirement to create a decision record. Relevant document
synchronization may touch four files and still be appropriate. Do not fail it
because PLAN changed or an arbitrary file threshold was exceeded.

Measure B4 turns, tool/token usage, elapsed time, changed files, new documents and
questions. Review whether each action serves correctness, the task or an existing
project rule. Neither zero documents nor few calls prove efficiency or correctness.
Predeclare targets and compare actual effort against baseline in fresh sessions.

## Comparisons and preservation

Every score and manifest declares `criteria_version: v4`. The isolated scorer
transport and aggregator refuse a different or missing version. Mixed versions
cannot be pooled. B3's final verdict also requires its first-stage score to
declare this version; a historical or unversioned handoff pass cannot satisfy it.
Historical results remain available through the repository
revision that produced their scorer; never overwrite them to apply these rules.

The aggregator rejects duplicate cell identities and reports matrix completeness.
Incomplete matrices are provisional and do not receive a headline overhead
comparison. Reported overhead is explicitly the **ratio of medians**, not the
median of paired ratios. Preserve per-cell evidence for separate paired analysis.
Missing usage is unknown, not zero. Summed reported tokens include cache categories;
they do not equal billed tokens. Provider dollar estimates are informational and
do not represent a subscription charge.

## Validation and remaining work

Reference/no-op/drifter self-tests exercise satisfiable contracts, missing work,
and actual approved-scope removal. They do not measure agent behavior. The
natural-request adaptive suite in `../adaptive-evals.json` is a specification for
fresh model evaluations, including risk discovery and a real two-session resume.
Its schema check does not execute those cases. The core fixtures remain small
synthetic tasks; stronger claims about long projects require representative work,
independent repetitions, and reviewed evidence.
