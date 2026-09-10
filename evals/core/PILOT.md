# Running a frozen three-arm pilot

The launcher compares a guided baseline (no skill), an attested Forge release, and a local candidate package. It records each started invocation before dispatch, preserves interrupted work, and verifies the same model, package contents, scoring criteria, network policy, images, and randomized order across attempts. It does not conclude that Forge is useful or ready to adopt.

A comparison of baseline, candidate.2 and v1.11.0 is a **product comparison**, because their wording and behavior differ. An instruction-loading ablation must separately establish that the semantic instructions are identical and only their loading changes. Older result totals under v3.1 must not be compared directly with new v4 results.

## Prepare and freeze

Use a clean committed harness checkout and a separate output directory outside `evals/core`. Prepare the release tag locally, validate the candidate package, and build the agent, scorer and network proxy images before freezing. The model identifier must be explicit and match the principal model actually reported by the CLI; an initialization message alone cannot override a different response model. No model or credential probing session is started by `verify`.

Set the following variables to the selected paths, release and locally built image tags. Do not use placeholder values for a live run:

```bash
python evals/core/pilot_manifest.py \
  --harness "$HARNESS_DIR" --candidate-dir "$CANDIDATE_DIR" \
  --forge-release "$FORGE_RELEASE" --model "$MODEL_ID" \
  --agent-image "$AGENT_IMAGE" --scorer-image "$SCORER_IMAGE" \
  --network-image "$NETWORK_IMAGE" --runtime docker \
  --scenarios b1 b2 b3 b4 b4n b4a q4 s2 v1 \
  --runs 2 --seed 7 --invocation-ceiling 75 \
  --out "$FROZEN_DIR"
```

This example schedules 54 cells and 62 initial invocations, including the two activation checks and B3's two sessions per cell. The ceiling also covers activation checks on later attempts, infrastructure retries and provider interruptions. Two repetitions are an initial screen, not enough to establish broad effectiveness or zero overhead. The manifest refuses a ceiling below its planned initial sessions. The local candidate may share the release's version string, but its runtime content hash must differ for a live comparison.

The resulting `pilot_manifest.json` and `RUN_ORDER.frozen.tsv` are immutable inputs. They pin the harness commit and source bytes, both package identities, all relevant prompts, per-scenario criteria, scorer sources including readable hidden tests, actual image IDs and scorer image contents, and the enforced provider-only network policy. The runner installs and rechecks package content after configuration. Do not edit frozen files to resume an existing experiment; use a new experiment for changed inputs.

```bash
python evals/core/pilot_launch.py verify \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
```

Verification performs offline Git and container checks. It does not call a model. The selected container runtime must match the manifest. Real pilots refuse local package overrides for the release arm, alternative network arguments, local scoring, mock injection and other inherited execution overrides.

## Execute, pause and resume

Only start the following after allocating the subscription usage and invocation budget:

```bash
env -u ANTHROPIC_API_KEY python evals/core/pilot_launch.py run \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
```

The default billing policy is subscription-only. Provider dollar estimates are informational and are neither charges nor a spending limit. Every started invocation counts, including attempts that never connect. A reservation survives a crash before a transcript is written. For an explicitly desired estimate ceiling, freeze both `--usd-ceiling` and `--reserve-usd`; unknown usage then consumes a full reserve. Enforcement is between sessions, so one session can exceed its reserve.

A subscription, authentication or network limit preserves the attempt, writes `PAUSED.json`, and exits. Resolve the reported condition and explicitly continue:

```bash
python evals/core/pilot_launch.py resume \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
```

Resume uses the same frozen order and skips scored cells. It does not switch models, accounts or billing. The exclusive launcher lock prevents concurrent attempts; Ctrl-C and termination propagate to the child process group and allow cleanup to finish.

B3 measures a genuine fresh-session handoff. If stage 1 finished and stage 2 did no agent work before a known interruption, resume restores the sealed stage-1 snapshot and runs only stage 2 with fresh configuration. Partial second-session work, unknown execution state, or legacy evidence without a verified snapshot stops for recovery or manual disposition. S2 is deliberately a single-session stale-status scenario and is not evidence of fresh-session recovery.

## Recover before retrying

```bash
python evals/core/pilot_launch.py recover \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
python evals/core/pilot_launch.py retry \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
```

`recover` scores complete unscored output offline in the isolated no-network scorer. It keeps raw files and writes separate recovered metadata/results. Unknown exit codes remain unknown, with an explicit zero-exit assumption for scoring; conditional results do not complete primary comparisons. B3 recovery that cannot establish both stages requires manual disposition and never silently reruns stage 1.

`retry` is an explicit action for infrastructure failures within the frozen allowance (one per cell by default). It does not rerun ordinary failing outcomes to obtain a pass. Prior attempts, unknown execution evidence and contradictory scores remain visible; the first ordinary outcome is preserved. A model mismatch stops further dispatch immediately.

## Reporting and credential cleanup

```bash
python evals/core/pilot_launch.py report \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
python evals/core/pilot_launch.py cleanup \
  --manifest "$FROZEN_DIR/pilot_manifest.json" --pilot-dir "$PILOT_DIR"
```

`ANALYSIS.json` and `ANALYSIS.md` account for every planned cell and attempt, distinguish missing/invalid/conditional evidence, and report each criteria label separately. Pairings are within the same scenario and run; ratios with incomplete evidence are labelled preliminary. Core B1–B4 use v4; B4n/B4a/Q4/S2/V1 use v4-supp1. Risk-routed Q4 results should not be pooled into a quick-task speed target. Semantic scope, state and process reviews remain pending, and readiness stays `NOT_ASSESSED` even for a complete matrix.

The launcher keeps refreshed subscription credentials in a private temporary cache outside result artifacts, never overwrites the user's original source credentials, and stores only the cache path in pilot metadata. The cache survives pauses and incomplete runs, and is removed after an ordinary complete matrix. Explicit cleanup removes that cache and credential copies from known harness configuration directories after interruptions. It does not traverse candidate repository contents. Cleanup is available even when result reconciliation fails. Use it before sharing artifacts or abandoning a run.

For offline harness validation, freeze with `--no-images` and use `--mock reference`, `--mock noop` or `--mock drifter` consistently on launcher commands. Such manifests cannot be used for live execution. Synthetic results are harness checks, not model performance evidence. No live comparison is part of the repository's deterministic test suite.
