# Forge core benchmark harness

Executable A/B instrument for Forge's four core behavioral benchmarks. It turns the protocol into real fixture repositories, hidden requirement tests, deterministic scoring, fresh agent sessions, preserved raw evidence, and an aggregate report.

**Status: instrument built and mock-self-tested. No real benchmark runs are published yet.** Mock results validate the harness, not Forge.

## What changed from the original protocol-only benchmark

The harness closes several validity gaps before real runs are allowed:

- real agent sessions run inside Docker or Podman with only the fixture repo and that run's Claude config mounted; scorer code, hidden tests, reference solutions, other conditions, and other outputs are not mounted
- the Forge arm is loaded only from a verified immutable GitHub release asset unless an explicitly marked local candidate run is requested
- Forge package validation is fail-closed
- a one-time activation preflight must prove the installed Forge skill is discoverable before the Forge arm starts
- B3 is a two-session context-loss test: Stage 1 investigates and leaves durable handoff state, then Stage 2 starts with a completely fresh Claude config and no Stage-1 conversation history
- condition order is paired and deterministically randomized from a recorded seed
- raw repo state, prompts, transcripts, diffs, timing, scoring, and manifest metadata are retained per run

## Requirements

Host/controller:

- bash
- git
- Python 3 + pytest
- GitHub CLI (`gh`) with release and asset verification support
- Docker or Podman for real runs
- Anthropic API credentials, or an existing Claude Code credential file copied into each isolated config

The default container image is built from `container/Containerfile`. It installs the current stable Claude Code channel at image-build time and records the actual `claude --version` plus image ID in `MANIFEST.json`. For stricter reproducibility, set `CLAUDE_CODE_CHANNEL` to an exact Claude Code version before building.

## Run

```bash
export ANTHROPIC_API_KEY=...
./run.sh --runs 5
FORGE_REF=v1.7.0 ./run.sh --runs 5
CLAUDE_CODE_CHANNEL=<exact-version> ./run.sh --runs 5
```

A normal 5-run matrix is 4 scenarios × 2 arms × 5 = 40 benchmark cells. B3 uses two fresh agent sessions per cell, so the number of Claude invocations is higher than the cell count.

Output goes to `results/<UTC timestamp>/REPORT.md` plus per-run evidence: final repo, diff, prompts, transcripts, stderr, metadata, deterministic score, and B3 Stage-1 handoff score where applicable.

## Isolation boundary

For a real run, the agent container receives only:

```text
/workspace  -> this run's fixture repo (rw)
/config     -> this run's isolated Claude config (rw)
```

It does not receive the benchmark controller directory. Hidden tests, the scorer, reference/mock agents, Forge source used by the baseline arm, and other runs therefore stay outside the agent filesystem boundary.

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
9. installs the verified package only into Forge-arm config dirs
10. runs an activation preflight that must return the exact installed Forge version

`FORGE_DIR` is supported only for candidate/ablation work and requires `ALLOW_UNVERIFIED_FORGE=1`. Its manifest is marked `local-unverified`; do not mix such runs with published stable-release claims.

## Scenarios

| Benchmark | Fixture | Main gating behavior |
|---|---|---|
| **B1 Scope retention** | M1 complete, M2 active, M3–M5 approved, tempting unapproved features visible | implement M2 without inserting adjacent work; keep later approved milestones traceable |
| **B2 Debugging tunnel vision** | M3 has a layered legacy-data defect; M4–M5 remain approved | solve the blocker without a broad rewrite; return to and continue the roadmap |
| **B3 Context-loss recovery** | same active M3 defect plus two-session handoff | Stage 1 leaves accurate durable state without solving; Stage 2 gets a fresh config, reconstructs from repo state, completes M3, and preserves/continues M4–M5 |
| **B4 Proportionality** | mature green repo; one-line low-risk request | make the tiny change without unnecessary control artifacts or requirements ceremony |

Every final scenario also gates on visible tests, hidden requirement/invariant tests, and no detected scope drift.

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

`assert_run.py` scores artifact state, not persuasive prose. It records REQ-tagged hidden tests, visible tests, invariants, dropped requirements, adjacent features, defect churn, later-work traceability/resumption, B3 handoff/recovery, B4 overhead, and token/time metrics where available.

Heuristic thresholds remain visible in source and are not ground truth. B2/B3 may need a harder fixture if a strong baseline saturates.

## Counterbalancing

Cells are paired by scenario/run so baseline and Forge happen close together. Within each pair, arm order is deterministically randomized from `BENCH_SEED`; scenario order is also shuffled per run. The seed and exact `RUN_ORDER.tsv` are preserved.

## Harness self-test

Mock agents do not call Claude and bypass remote/container requirements. They validate fixture/scorer behavior only:

```bash
BENCH_MOCK_AGENT=reference ./run.sh --conditions baseline --runs 1 --out /tmp/forge-ref
python3 selftest.py /tmp/forge-ref --expect pass

BENCH_MOCK_AGENT=noop ./run.sh --conditions baseline --runs 1 --out /tmp/forge-noop
python3 selftest.py /tmp/forge-noop --expect fail

BENCH_MOCK_AGENT=drifter ./run.sh --conditions baseline --runs 1 --out /tmp/forge-drift
python3 selftest.py /tmp/forge-drift --expect fail
```

The reference agent proves fixtures are satisfiable. No-op and drifting agents prove the scorer fails closed for missing work, scope drift, bad handoff behavior, and unnecessary bureaucracy.

## Known limits

- Single-turn headless sessions are used within each stage. Human interaction dynamics are not measured.
- Scope-drift/churn signals include explicit heuristics with documented thresholds.
- B2/B3 fixture difficulty is intentionally modest for the first empirical batch. If baseline saturates, increase difficulty before interpreting Forge effectiveness.
- The optional third candidate/ablation arm is represented by `FORGE_DIR`, not part of the default stable A/B matrix.
- A verified Forge release proves what package was loaded; it does not prove Forge helps. Only real A/B outcomes can answer that.

## Files

```text
run.sh               matrix runner, isolation, provenance, activation preflight, evidence capture
build_fixtures.py    materializes scenario repos from the compact bundle
fixture_bundle.json  reference fixture, overlays, hidden tests, and prompts
assert_run.py        deterministic scorer
aggregate.py         REPORT.md generator
selftest.py          validates expected mock outcomes
mock_agent.py        reference/noop/drifter agents used only for harness self-tests
container/           isolated real-agent runtime definition
```
