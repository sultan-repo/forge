# Benchmark reliability repair validation

Date: 2026-09-10. Base: `130e71314269666ce31abee8afe84bd380a59c06`.
Local validation used macOS, Python 3.14.7 and Docker Desktop. CI repeats the
checks on Ubuntu with Python 3.12. These are instrument tests, not measured
Forge outcomes. No live Claude sessions, subscription usage or API spending
were used for this repair.

## Static and deterministic checks

The package validator reports `SKILL VALID: forge 1.11.0`; evaluation validation
reports 38 valid specifications and no model sessions. Ruff passes for
`scripts templates evals tests`. Strict mypy passes the 13 files enumerated in
the workflow. The full deterministic suite passes **542 tests with two known
macOS skips**. The separate Docker isolation suite passes **five tests**.
Reproduce them with:

```bash
python -m pytest -q tests \
  --ignore=tests/test_benchmark_isolation.py \
  --ignore=tests/test_benchmark_network_isolation.py
BENCH_SCORER_IMAGE=forge-bench-scorer:reliability-test \
BENCH_NETWORK_IMAGE=forge-bench-egress:reliability-test \
  python -m pytest -q tests/test_benchmark_isolation.py \
    tests/test_benchmark_network_isolation.py
```

The Docker suite passes all five tests. It checks scorer isolation and candidate
hook rejection, direct-network and public-source retrieval denial, read-only
proxy mounts, and success/timeout resource cleanup. It does not call provider
endpoints or use account credentials.

The new deterministic coverage includes budget reservations surviving crashes,
subscription pauses, actual response-model mismatches, missing execution
evidence, partial matrices, recovery before retry, repeated B3 stage-2 resumes
without another stage-1 invocation, frozen identity changes, runtime selection,
credential refresh and cleanup, and malformed/disallowed proxy requests.

## Executable mock matrices

All matrices use fresh output directories and explicit mock agents:

| Check | Result |
|---|---|
| Nine scenarios × three arms × one run, reference | 27/27 automated passes; 30 ledgered sessions; no pending reservations |
| Nine scenarios × baseline × one run, no-op | 9/9 expected automated failures |
| Nine scenarios × baseline × one run, drifter | 9/9 expected automated failures |
| Frozen launcher, reference, all nine scenarios and three arms | 27/27 automated passes; frozen order reproduced; v4 and v4-supp1 reported separately |

Mock preflights do not invoke a model, so the reference matrix has 30 actual
sessions: 27 cells plus three extra B3 first sessions. Its equivalent live
matrix plans 32 initial invocations, including two activation sessions.
The launcher leaves semantic review pending and readiness `NOT_ASSESSED`.
`selftest.py` checks the entire declared matrix and rejects missing, duplicate
or live-labelled inputs.

The preserved core fixture bundle is byte-identical to the base revision.
Reference B1–B4 outputs were checked against the base v4 scorer and produced
identical complete score dictionaries. Supplemental overlays and tests are
labelled `v4-supp1`; they do not rewrite core v4 scores or historical results.

## What remains unmeasured

- Live Max-subscription transport compatibility through the restricted proxy.
- Whether models load planned/risk references when required.
- Forge correctness, state accuracy, token/time overhead and real recovery quality.
- Generalization beyond these fixtures, including unseen natural requests.
- Semantic review accuracy, public-source training contamination and deliberate
  misuse of allowed provider APIs.

Run a small explicitly budgeted transport check before a live pilot. Then use
the [frozen protocol](PILOT.md), preserve the complete evidence, and adjudicate
claims before drawing adoption conclusions. Comparing candidate.2 with 1.11.0
is a product comparison; a loading-only experiment must hold the instructions'
meaning constant. Forge's shipped instructions and version are unchanged by
this repair.
