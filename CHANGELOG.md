# Changelog

## 1.6.0

Evidence-first and capability-first hardening.

- slims `SKILL.md` so the always-loaded control core stays compact and delegates detail to references
- adds `references/example-walkthrough.md` with concrete control state, Work Packet, detour, Plan Delta, reconciliation, and resume example
- adds `references/claude-code-integration.md` to position Forge as a control methodology over native capabilities rather than a replacement for them
- makes capability detection a universal rule: no model-name, model-generation, fixed tool, or platform-version allowlists in Forge behavior
- hardens remote bootstrap: separate source selection, provenance verification, structural validation, installation, and activation
- forbids executing downloaded Forge scripts before source provenance is established
- prefers immutable/versioned release verification when available, with exact-commit/no-script fallback
- expands deterministic Control Mode guidance: session-start orientation preferred when lifecycle hooks exist; task completion guard only when a task lifecycle exists
- adds optional `templates/task-completed-control.py`
- updates hook example to include current session-start lifecycle cases while remaining capability-driven
- adds empirical core benchmark protocol for scope retention, debugging tunnel vision, compaction recovery, and proportionality
- explicitly distinguishes baseline testing from ablation testing
- publishes no benchmark claims until real runs are recorded
- adds MIT license
- shortens and repositions README around value, built-in integration, safety, and evidence

## 1.5.0

Adds one-prompt remote bootstrap and explicit-name natural-language invocation.

- adds `BOOTSTRAP.md` with an agent-facing remote installation/activation protocol
- adds `scripts/bootstrap.sh` for validate + install + current-session activation guidance
- changes `disable-model-invocation` to `false` while narrowing the skill description so Claude should auto-invoke Forge only when the user explicitly names Forge or requests the Forge methodology
- allows prompts such as `Use Forge from https://github.com/sultan-repo/forge to implement: ...`
- requires remote bootstrap to keep Forge outside the product source tree
- loads Forge directly in the bootstrap session so command-registration restart is not a blocker
- hardens `scripts/install.sh` for direct-in-place installations
- adds `evals/bootstrap-evals.json`

## 1.4.0

Renamed the skill and public command from **Project Execution** / `/project-execution` to **Forge** / `/forge`.

## 1.3.0

Added Plan Consistency, Convergence, trust boundaries, capability-aware orchestration, review triage, assumption checkpoints, Work Packet sizing, Plan Delta canonicalization, and behavioral evals.

## 1.2.0

Hardened plan continuity, persistent execution control, revisioning, parallel work state, validation, and session reorientation.

## 1.1.0

Added Scope Conservation, Work Packets, detours, Plan Deltas, reconciliation gates, requirement coverage, and controller/worker separation.

## 1.0.0

Initial universal project execution skill.
