# Forge Skill Evals

Forge should evolve from measured behavior, not from accumulating more prompt rules.

## Benchmark principle

A skill trigger is not evidence that the skill improves project execution. Material methodology changes should be compared in fresh sessions against a baseline using observable repository state and preserved evidence.

For each benchmark condition, record:
- Forge version / source commit / release provenance
- coding-agent/runtime version
- model selected by the environment
- date
- fixture revision
- deterministic randomization seed and run order
- number of runs
- pass/fail by assertion
- requirement completion
- scope drift
- later-work resumption/traceability
- token usage when available
- wall-clock/runtime when available
- bureaucracy or drift notes
- raw transcript/diff/repository evidence

Do not hardcode model names into Forge behavior. Model identity belongs only in benchmark metadata so results are reproducible.

## Core benchmark set

Run at least these four before another broad methodology expansion:

1. **Scope retention**: approved later scope must not silently disappear.
2. **Debugging tunnel vision**: a deep blocking defect must be solved without replacing the approved roadmap.
3. **Context-loss recovery**: a first session must persist a valid handoff, then a completely fresh second session must reconstruct and continue from repository state alone.
4. **Proportionality**: a tiny reversible change must not trigger heavyweight project bureaucracy.

Prefer 5 or more independent runs per condition for the first empirical batch. If a baseline saturates, strengthen the fixture before drawing conclusions.

## Executable instrument

The runnable benchmark lives in [`core/`](core/README.md). It provides:

- real fixture repositories derived from one reference application
- hidden REQ-tagged tests and invariant tests
- deterministic scorer and report generator
- container isolation for real agent runs
- verified immutable Forge-release loading
- Forge activation preflight
- paired/interleaved cells with deterministic randomized arm ordering
- genuine two-session B3 context-loss boundary
- raw evidence retention
- reference/no-op/drifter mock agents for harness self-testing

CI runs only the deterministic mock self-tests. Mock outcomes prove that the instrument can pass satisfiable fixtures and fail missing/drifting/bureaucratic behavior; they are **not** Forge benchmark results.

## Conditions

For methodology evaluation use at least:

- **Baseline**: same agent/runtime, no Forge.
- **Current Forge**: released Forge version loaded from verified immutable release provenance.
- **Candidate/Ablation**: optional, for testing a proposed change against both baseline and current Forge. Candidate runs must be labelled as unverified/local unless they also use a published release.

A baseline comparison tells whether Forge as a whole helps. An ablation comparison is needed to learn whether a specific section is useful or dead weight.

## Test quality

The highest-value benchmarks use fixture repositories and observable state transitions rather than prompts that simply name the expected Forge concept.

Good:
- repo contains M3/M4/M5 and an injected M3 failure; grade whether M4/M5 remain accounted for after the fix
- first session investigates a blocker and must leave durable state; discard its context/config and grade recovery by a fresh second session
- provide unapproved adjacent ideas and grade whether they leak into implementation
- ask for a one-line change in a mature repo and grade unnecessary control artifacts

Weaker:
- ask "what should a Plan Delta do?" and grade whether the answer repeats the definition
- give both arms Forge-native terminology that leaks the expected strategy
- let agents read hidden tests or scorer code
- claim a fresh baseline from a conversation that already knows Forge

`evals.json` remains the broad behavioral regression suite. `bootstrap-evals.json` covers remote bootstrap and explicit-name invocation. `CORE-BENCHMARKS.md` defines the empirical benchmark contract, and `core/` implements it.

## Published results

No with-Forge vs no-Forge performance results are published yet.

Do not claim effectiveness percentages until real isolated benchmark runs are executed, preserved, reviewed, and recorded here.
