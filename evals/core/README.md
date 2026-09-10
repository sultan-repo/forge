# Forge core benchmark harness

Executable baseline/Forge/candidate instrument for four core and five supplemental behavioral benchmarks. It turns the protocol into real fixture repositories, hidden requirement tests, deterministic scoring, fresh agent sessions, preserved raw evidence, and an aggregate report.

**Status: core criteria v4 plus prospective v4-supp1 supplements; no new live comparison is included.** Mock results validate the harness, not Forge. See [core criteria](CRITERIA_v4.md), [supplemental criteria](CRITERIA_v4-supp1.md), and the [frozen pilot launcher](PILOT.md).

## What changed from the original protocol-only benchmark

The harness closes several validity gaps before real runs are allowed:

- real agents have no direct network access; a provider-only Unix-socket proxy and disabled web tools restrict retrieval while the fixture and isolated config remain the only writable project inputs; scorer/tests/reference outputs are not mounted
- the Forge arm is loaded only from a verified immutable GitHub release asset unless an explicitly marked local candidate run is requested
- Forge package validation is fail-closed
- each Forge/candidate arm has an accounted activation preflight that must return its installed package version without being told its value
- B3 is a two-session context-loss test: Stage 1 investigates and leaves durable handoff state, then Stage 2 starts with a completely fresh Claude config and no Stage-1 conversation history
- condition order is paired and deterministically randomized from a recorded seed
- raw evidence is preserved across attempts; a ledger reserves invocations before dispatch, and explicit pause/resume/recovery/retry operations avoid overwriting or silently repeating completed work

## Requirements

Host/controller:

- bash (including macOS's bundled Bash 3.2)
- git
- Python 3.12 or newer + pytest
- GitHub CLI (`gh`) with release and asset verification support
- Docker for the tested isolation path; Podman uses the same interface but has not been validated for this revision
- an existing Claude Code subscription credential file for the pilot launcher; it refuses API-key overrides

The default agent image is built from `container/Containerfile`. It installs the selected Claude Code channel at image-build time and records the actual `claude --version` plus image ID in `MANIFEST.json`. For stricter reproducibility, set `CLAUDE_CODE_CHANNEL` to an exact Claude Code version before building. Cached stable-channel images are reused; rebuilding them is an explicit choice. The default scorer image tag includes a hash of its source so controller changes cannot silently reuse an older scorer. Agent, scorer, and provider-proxy images are frozen by immutable local image IDs before sessions start. The pilot verifies the scorer image contains the frozen source and fixtures; the proxy verifies its baked policy and helper sources.

The live pilot requires an explicit model identity. Every session must report that identity; mismatched or unknown models stop further dispatch. Requested and observed identities remain separate evidence. Proxy setup and agent elapsed time are recorded separately in each session's `network.json`; reported total wall time includes harness/container overhead.

Deadlines and elapsed time use Python, so GNU `timeout` and nanosecond `date` extensions are not required. Each agent, post-agent Git command, and scorer container receives a unique name and is explicitly removed on completion, timeout, or handled interruption.

## Run a comparison

Use [PILOT.md](PILOT.md) to build the images, freeze a manifest, verify its identities, and then deliberately start a run. The launcher requires the release, candidate directory, model, images, run order, and invocation ceiling to be explicit. It starts no model sessions during manifest creation or verification. A Max subscription uses session allowance; provider dollar estimates are informational by default.

The default core matrix has 4 scenarios × 2 arms × 5 repeats = 40 cells. Enabling the candidate arm gives 60 cells. B3 uses two fresh sessions per cell, and activation preflights are additional invocations. Always set a ceiling based on sessions, including authorized retries.

A provider/authentication limit pauses the pilot and returns control. Resume is explicit; successful work is recovered offline before any rerun. Ordinary model failures are outcomes, not automatic retry opportunities. A completed B3 first stage is retained across a zero-work second-stage pause. Incomplete or ambiguous attempts remain disclosed rather than silently replaced.

`run.sh` is the lower-level matrix executor. Real calls require a ledger, explicit ceiling and pinned model; raw nonempty output directories are rejected. The launcher manages separate attempt directories and cell filters. `AGENT_TIMEOUT` defaults to 2400 seconds; `SCORER_TIMEOUT` defaults to 1500 seconds. Captured credentials are removed from session configs on normal exit/handled interruption; token refreshes stay in a private cache outside result artifacts and never overwrite the user's original credential file. The launcher retains that cache while recovery/resume is needed and provides explicit cleanup.

## Isolation boundary

For a real run, the agent container receives only:

```text
/workspace  -> this run's fixture repo (rw)
/config     -> this run's isolated Claude config (rw)
/forge-egress -> provider socket and forwarding helper (ro)
```

The agent runs with `--network none`. The socket proxy allows only reviewed provider TLS destinations; direct IP, DNS, host-network access, and GitHub/raw retrieval are blocked. The CLI disables WebFetch and WebSearch. See [NETWORK.md](NETWORK.md) for the exact policy, offline tests and limits, including provider-mediated retrieval and training contamination. Public tests remain readable; encoding them is not an access control.

It does not receive the benchmark controller directory. Hidden tests, the scorer, reference/mock agents, Forge source used by the baseline arm, and other runs therefore stay outside the agent filesystem boundary.

Agent-modified code is then scored in a separate non-root, read-only container with no network or credentials, limited memory/CPU/processes, and a disposable writable copy of the candidate repository. Post-agent Git commands also run in this container boundary. Hidden tests are materialized outside the candidate tree and ignore candidate pytest settings, root conftest hooks, and local `pytest.py` shadowing. The B3 repository handed to Stage 2 therefore contains no scoring files.

This boundary protects the controller host. It is not an adversarial evaluator: imported candidate Python still runs in the same interpreter as its hidden tests and can deliberately interfere with pytest. Audit suspicious changes and raw evidence before interpreting results; passing automated scores alone does not establish tamper resistance.

`--dangerously-skip-permissions` is acceptable here only inside this disposable container boundary. Do not replace container isolation with an unrestricted host run and call the result publishable.

## Forge provenance and activation

For publishable Forge-arm runs, `run.sh`:

1. resolves the requested release, or current latest stable release
2. rejects drafts/prereleases
3. verifies the immutable GitHub release attestation
4. downloads the versioned Forge ZIP asset
5. verifies the local asset against the release attestation
6. safely extracts the archive
7. runs Forge's package validator and fails on any error
8. confirms release tag matches package `VERSION`
9. installs the verified package's runtime files only into Forge-arm config dirs
10. runs an activation preflight that must return the exact installed Forge version in a successful result; the prompt does not disclose the expected version

This checks package discovery/readability in the preflight session. It does not establish that every later cell follows Forge's instructions.

The runtime projection includes `SKILL.md`, `README.md`, `BOOTSTRAP.md`, `VERSION`, `LICENSE`, `references/`, `templates/`, `scripts/`, and `docs/runner.md` when present. The complete release is validated first; `MANIFEST.json` records the projection paths. Evaluation material, regression tests, Git metadata, and other developer files are excluded, because the release also contains the hidden scorer and reference fixture. Evaluation links in the skill are intentionally unavailable inside benchmark sessions.

The native `candidate` arm loads `CANDIDATE_DIR`, records its runtime content hash, and checks installed contents before sessions. It is labelled `local-unverified`. The lower-level executor retains the older `FORGE_DIR` override with `ALLOW_UNVERIFIED_FORGE=1`; the frozen pilot refuses this override for its release arm. Arm identity includes content, not just a version string; a loading ablation may retain the same version but must have different content. Do not present local candidates as immutable published packages.

## Scenarios

| Benchmark | Fixture | Main gating behavior |
|---|---|---|
| **B1 Scope retention** | M1 complete, M2 active, M3–M5 approved, tempting unapproved features visible | implement M2 without inserting adjacent work; keep later approved milestones traceable |
| **B2 Debugging tunnel vision** | M3 has a layered legacy-data defect; M4–M5 remain approved | solve the blocker and retain the approved roadmap; source churn remains review evidence |
| **B3 Context-loss recovery** | same active M3 defect plus two-session handoff | Stage 1 leaves accurate durable state without solving; Stage 2 gets a fresh config, reconstructs from repo state, completes M3, and preserves/continues M4–M5 |
| **B4 Proportionality** | mature green repo; one-line low-risk request | make the requested export change and retain invariants; ceremony is measured for review |

Core gates remain v4. Supplements use v4-supp1 and are reported separately:

| Supplement | Purpose |
|---|---|
| B4n | A quick export-format edit without a specification conflict. |
| B4a | A change record is required only when approved requirement text changes; broader invariant edits remain visible for review. |
| Q4 | A destructive clear command must preserve its confirmation safeguard; report its effort separately from quick-task speed. |
| S2 | Single-session recovery over a stale “FIX APPLIED” claim; this is not a fresh-session B3 replacement. |
| V1 | Distinguish observed invariant checks and honest disclosure from unsupported completion claims; inherited INV-1 is measured rather than automatically gated. |

See each criteria document for required tests and remaining manual judgments.

### B3 boundary

B3 intentionally uses a stronger and more reproducible boundary than pretending to trigger a specific UI compaction command:

```text
Stage 1 agent
  -> investigate blocker
  -> write durable handoff state
  -> stop

conversation/config discarded

Stage 2 agent
  -> fresh CLAUDE_CONFIG_DIR
  -> same repo only
  -> recover active work
  -> complete and return to roadmap
```

This measures recovery from actual context loss without depending on a temporary command name or platform-specific compaction implementation.

## Scoring

`assert_run.py` records complete expected-test evidence, visible tests, invariants,
requirement-ID loss, later-work traceability, B3 handoff checks, and effort metrics.
Agent execution errors and incomplete required/invariant tests fail the cell.
Missing later tests cannot count as completed work. Hidden tests use PLAN's public
contracts and live as reviewable source under `hidden/`. B3 Stage 1 checks for
correction of its stale partial-fix claim, but all prose-accuracy judgments still
require review. Stage-1 evidence is compared with the original fixture, including
agent commits, and its cumulative diff is retained before the fresh Stage-2 session.

File counts, new modules, keyword hits, and churn are review signals, not semantic
verdicts. A B4 implementation may synchronize related PLAN/status text. Automatic
passes leave scope, state-accuracy and process review unresolved. An observed
defect must be compared with fixture HEAD before attributing it to an arm.
The aggregator refuses mixed criteria unless `--by-criteria` writes separate label reports. It labels ratios of medians and withholds headline comparisons for an incomplete matrix. The pilot analysis separately reports within-scenario paired ratios on complete ordinary blocks; recovered and interrupted attempts are disclosed without silently entering the primary comparison. B2/B3 may need a harder fixture if
a strong baseline saturates.

## Counterbalancing

Cells are paired by scenario/run so all requested arms happen close together. Within each block, arm order is deterministically randomized from `BENCH_SEED`; scenario order is also shuffled per run. The seed and exact `RUN_ORDER.tsv` are preserved.

## Harness self-test

Mock agents do not call Claude and bypass remote/container requirements. They validate fixture/scorer behavior only:

```bash
BENCH_MOCK_AGENT=reference bash evals/core/run.sh --conditions baseline --runs 1 --out /tmp/forge-ref
python3 evals/core/selftest.py /tmp/forge-ref --expect pass

BENCH_MOCK_AGENT=noop bash evals/core/run.sh --conditions baseline --runs 1 --out /tmp/forge-noop
python3 evals/core/selftest.py /tmp/forge-noop --expect fail

BENCH_MOCK_AGENT=drifter bash evals/core/run.sh --conditions baseline --runs 1 --out /tmp/forge-drift
python3 evals/core/selftest.py /tmp/forge-drift --expect fail
```

The reference agent demonstrates fixture satisfiability. No-op and drifting
agents exercise missing work, actual removal of approved scope, and failed
handoff checks. They do not establish the accuracy of prose review or measure
unnecessary bureaucracy.

Use fresh output directories. `tests/test_pilot_controls.py` exercises the ledger, frozen identities and attempt recovery; `tests/test_benchmark_harness.py` covers matrix execution. The separate Docker suites are `tests/test_benchmark_isolation.py` and `tests/test_benchmark_network_isolation.py`, with built scorer/proxy images. CI checks all nine scenarios, including the three-arm reference matrix, and rejects missing or duplicate mock cells. See [contributor checks](../../CONTRIBUTING.md) and the [repair validation record](RELIABILITY_VALIDATION.md).

## Known limits

- Single-turn headless sessions are used within each stage. Human interaction dynamics are not measured.
- Requirement IDs and handoff keywords measure traceability. Semantic scope and truthful completion claims need evidence-based review.
- B2/B3 fixture difficulty is intentionally modest for the first empirical batch. If baseline saturates, increase difficulty before interpreting Forge effectiveness.
- Comparing candidate.2 with released 1.11.0 is a product comparison. A loading-only ablation must keep wording, routing, verification and synchronization semantics identical while changing only instruction loading.
- A small pilot is an initial screen, not proof of equivalence, broad effectiveness, or zero overhead. Include true fresh-session recovery and high-risk guardrails; review claims independently before adoption.
- A verified Forge release proves what package was loaded; it does not prove Forge helps. Only real A/B outcomes can answer that.

## Files

```text
pilot_*.py                    frozen manifest, session accounting, pause/resume/recovery and analysis
network_*.py                  provider-only socket transport, policy/identity validation and cleanup
credential_cache.py           private token-refresh continuity without source credential writes
run.sh                         matrix executor, provenance, activation and evidence capture
build_fixtures.py              materializes scenario repos from the compact bundle
fixture_bundle.py              reads the compact bundle without shared writable files
fixture_bundle.json.gz.b64     compressed reference fixture, overlays, legacy hidden archive, and prompts
fixture_supplements.json       separately versioned supplemental overlays and prompts
hidden/                       editable public-contract scoring tests
CRITERIA_v4.md                 automated gates, manual review boundary, comparison contract
assert_run.py                  deterministic scorer
score_entrypoint.py            disposable scoring copy and structured result transport
container_run.py               portable container deadline and cleanup
aggregate.py                   REPORT.md generator
selftest.py                    validates expected mock outcomes
mock_agent.py                  reference/noop/drifter agents used only for harness self-tests
container/                     isolated real-agent runtime definition
```
