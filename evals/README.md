# Forge Skill Evals

Forge should evolve from measured behavior, not from accumulating more prompt rules.

## Benchmark principle

A skill trigger is not evidence that the skill improves project execution. Material methodology changes should be compared in fresh sessions against a baseline.

For each benchmark condition, record:
- Forge version / source commit
- coding-agent/runtime version
- model selected by the environment
- date
- fixture revision
- number of runs
- pass/fail by expectation
- token usage when available
- wall-clock/runtime when available
- qualitative false-bureaucracy or drift notes

Do not hardcode model names into Forge behavior. Model identity belongs only in benchmark metadata so results are reproducible.

## Core benchmark set

Run at least these four before another broad methodology expansion:

1. **Scope retention**: approved later scope must not silently disappear.
2. **Debugging tunnel vision**: a deep blocking detour must return to the parent/master roadmap.
3. **Compaction recovery**: after context compaction/reset, durable state must restore the active detour, parent, revisions, and later work.
4. **Proportionality**: a tiny reversible change must not trigger heavyweight project bureaucracy.

Prefer 5 or more independent runs per condition when practical.

## Conditions

For methodology evaluation use at least:

- **Baseline**: same agent/runtime, no Forge.
- **Current Forge**: released Forge version.
- **Candidate/Ablation**: when slimming/removing rules, compare the candidate against both baseline and current Forge.

A baseline comparison tells whether Forge as a whole helps. An ablation comparison is needed to learn whether a specific section is useful or dead weight.

## Test quality

The highest-value benchmarks should use fixture repositories and observable state transitions rather than prompts that simply name the expected Forge concept.

Good:
- repo contains M3/M4/M5 and an injected M3 failure; grade whether M4/M5 remain accounted for after the fix
- establish a real control file, compact/reset context, then grade resumed behavior
- provide an uncovered requirement and inspect generated plan artifacts

Weaker:
- ask "what should a Plan Delta do?" and grade whether the answer repeats the definition

`evals.json` remains the broad behavioral regression suite. `bootstrap-evals.json` covers remote bootstrap and explicit-name invocation. `CORE-BENCHMARKS.md` defines the high-value empirical benchmark protocol.

## Published results

No with-Forge vs no-Forge benchmark results are published yet.

Do not claim effectiveness percentages until the benchmark runs are actually executed and recorded here.
