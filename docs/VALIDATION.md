# Adaptive revision validation

Recorded 2026-09-09 for the implementation in `7ba5034` and `a9e7eec`, based on GitHub main `db120ae`. Local tests used Python 3.14.7 on macOS; the scorer image uses Python 3.12. GitHub's validation workflow checks Python 3.12 on Linux. See [PR #8 checks](https://github.com/sultan-repo/forge/pull/8/checks) for the exact current PR commit.

## Deterministic checks

| Check | Observed result |
|---|---|
| Package validator | `SKILL VALID: forge 1.10.0`; unshipped work remains under Unreleased |
| Ruff, all scripts/templates/evals/tests | Pass |
| Strict mypy, all nine workflow-selected files | Pass |
| Shell syntax: installer, bootstrap, dispatch, benchmark runner | Pass |
| Full suite excluding Docker isolation | **381 passed, 2 skipped** in 82.19 s |
| Docker isolation on final rebuilt scorer | **3 passed** |
| Reference mock, B1–B4 | **4/4 automated passes** |
| No-op mock, B1–B4 | **4/4 automated failures** |
| Scope-removing drifter mock, B1–B4 | **4/4 automated failures** |
| Final B3 criteria-compatibility tests | **3 passed**; B3 reference/no-op/drifter outcomes rechecked |
| Behavioral evaluation specification validation | **38 cases valid**; this does not execute their model behavior |
| Whitespace/diff checks | Pass |

The two skips are the known macOS non-UTF-8 filename runner checks. Docker checks actually executed; they were not counted as skipped coverage.

GitHub's first full Linux suite passed (**383 tests**, 49.98 s). Its isolation job exposed a platform-dependent test assumption: a host-shaped `/tmp` path can be writable inside the container's private tmpfs without touching the host. The corrected test checks host-file isolation in both successful and deliberately failing hook cases. The successful case also requires visible tests, including secret-environment assertions, to execute. All three corrected Docker checks passed locally; the PR checks link above identifies the final Linux result.

Earlier full-suite attempts encountered one or two ten-second timeouts in the local fake-GitHub release scaffolding. Release tests passed alone (37/37), ordered subsets passed, and the final **unchanged** full suite passed using an explicit temporary root. The cause of the earlier timeouts remains unconfirmed. No assertions, deadlines, or production checks were weakened to obtain the passing result.

Commands, after installing `requirements-dev.txt` into an isolated development environment:

```bash
python scripts/validate-skill-package.py
python evals/validate_evals.py
python -m ruff check scripts templates evals tests
python -m mypy --strict \
  templates/validate-project-control.py templates/session-start-control.py \
  templates/task-completed-control.py scripts/adapters/base.py \
  scripts/adapters/claude_code.py scripts/adapters/codex_cli.py \
  scripts/forge-run.py scripts/forge-preflight.py scripts/validate-skill-package.py
bash -n scripts/install.sh scripts/bootstrap.sh scripts/forge evals/core/run.sh
python -m pytest -q tests --ignore=tests/test_benchmark_isolation.py \
  --durations=10 --basetemp=/private/tmp/forge-release-full-repro-2

docker build -f evals/core/container/ScorerContainerfile \
  -t forge-bench-scorer:adaptive-pr evals/core
BENCH_SCORER_IMAGE=forge-bench-scorer:adaptive-pr \
  python -m pytest -q tests/test_benchmark_isolation.py
```

Use a fresh disposable path for `--basetemp`; pytest manages its contents. The final local scorer image ID was `sha256:0a1f3c8db9a73cfab1942e07cf9ce1adb87fbb85c6d5312a2f383ca96434c53c`. This records the local build, not a claim of reproducible upstream image/dependency resolution.

The mock commands and their interpretation are documented in [the harness guide](../evals/core/README.md). They validate the scorer and workflow, not model effectiveness.

## Independent behavioral smoke checks

Two fresh Codex subagents received only a realistic request, the revised Forge entrypoint, and a disposable repository. They did not receive the intended solution or the parent's findings. These are limited model-assisted checks, not a matched Claude benchmark or human adjudication.

1. **Bounded receipt-label change:** updated the implementation and existing assertion, synchronized the directly contradicted requirement, preserved the unrelated item-format invariant and later work, and finished with two passing tests. It read only the Forge entrypoint and relevant project files; no setup, additional agents, or new control files were introduced.
2. **Resume over stale completion text:** the repository's status claimed persistence was fixed, while its two tests checked only the in-memory return value. The agent reopened the file, demonstrated that persistence was still broken, added behavioral checks (four initially failed), fixed persistence, finished the approved filtering feature, and updated the existing status with evidence. Seven tests passed; unknown-ID no-write behavior and unrelated task fields were preserved. The unapproved web UI remained untouched.

These observations support the intended routing and evidence behavior on those examples. They do not establish a general correctness advantage, latency improvement, or performance equivalence.

## Limits

Initial `SKILL.md` bytes fall from **9,743 to 4,447 (54%)**. Planned/high-risk references are conditional additional context. This is a source-size measurement, not total session tokens or cost.

No new live Claude/provider comparison or external readiness probe was run. No installed skill was updated and no release was published. Representative multi-session comparisons, risk behavior across models, and the net benefit of Forge remain empirical work described in [the assessment](ASSESSMENT.md).
