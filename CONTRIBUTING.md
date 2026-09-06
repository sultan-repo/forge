# Contributing to Forge

Forge is a methodology skill with optional runtime helpers. Improve observed behavior, correctness, and usability; avoid prompt expansion or framework abstraction for its own sake.

## Principles

- Preserve proportionality: a small reversible task should require a small amount of process.
- Prefer enforceable invariants and focused regression tests when strict behavior matters.
- Keep universal methodology independent of model names, platform versions, and provider rosters. Adapter code may enforce the concrete capabilities it requires.
- Keep `SKILL.md` compact; load deeper references only when applicable.
- Preserve approved scope, user authority, trust boundaries, evidence, and reconciliation.
- Document what is implemented separately from intended behavior and measured effectiveness.

## Local validation

Use Python 3.12 or newer; CI runs Python 3.12. Runtime scripts use the standard library. Install the pinned development tools in an isolated virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Start with the package check:

```bash
python3 scripts/validate-skill-package.py
```

Run the deterministic suite for code changes. Runner tests use fake adapters and local subprocess checks and do not require Claude/Codex credentials:

```bash
python -m pytest -q tests --ignore=tests/test_benchmark_isolation.py
```

The [validation workflow](.github/workflows/validate.yml) is the source of truth for current test selections and lint/type-check commands. The harness supports Docker or Podman; the separate [benchmark isolation tests](tests/test_benchmark_isolation.py) use Docker. Build their scorer image before running them:

```bash
docker build -f evals/core/container/ScorerContainerfile -t forge-bench-scorer:ci evals/core
python -m pytest -q tests/test_benchmark_isolation.py
```

Do not treat a skipped container suite as proof that isolation passed.

For fixture/scorer changes, run all three deterministic mock conditions:

```bash
BENCH_MOCK_AGENT=reference bash evals/core/run.sh --conditions baseline --runs 1 --out /tmp/forge-reference
python3 evals/core/selftest.py /tmp/forge-reference --expect pass
BENCH_MOCK_AGENT=noop bash evals/core/run.sh --conditions baseline --runs 1 --out /tmp/forge-noop
python3 evals/core/selftest.py /tmp/forge-noop --expect fail
BENCH_MOCK_AGENT=drifter bash evals/core/run.sh --conditions baseline --runs 1 --out /tmp/forge-drifter
python3 evals/core/selftest.py /tmp/forge-drifter --expect fail
```

Use fresh output directories for each batch. These mocks verify the instrument, not Forge effectiveness or real provider execution. The [harness guide](evals/core/README.md) describes real runs and their prerequisites.

## Methodology and documentation changes

For changed methodology, update a [behavioral regression scenario](evals/evals.json) and explain the observed failure the change addresses. Those JSON scenarios are specifications; package validation does not execute them against an agent.

For broad control changes, compare the relevant real benchmark conditions when practical: no Forge, current released Forge, and candidate/ablation. Preserve results and evidence, and disclose when those runs were not performed. Do not infer improvement from wording, added rules, passing mocks, or package checks alone.

Keep examples executable or clearly mark excerpts. Check documented commands against their actual parser, distinguish skill modes from shell commands, and describe approval/recovery limits accurately. Link to [VERSION](VERSION) instead of duplicating a current version in multiple documents.

## Pull requests and releases

Describe the concrete problem, resulting behavior, validation actually performed, and remaining limitations. Use focused changes and retain regression evidence for failure paths; avoid broad rewrites that make correctness harder to review.

Release/version changes follow [release guidance](docs/RELEASING.md). A package version or changelog entry is not itself evidence that CI or a live benchmark passed.
