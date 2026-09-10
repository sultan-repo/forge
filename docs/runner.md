# Optional local agent runner

Forge's shell helper has four commands:

```text
preflight   configure/verify project execution readiness
doctor      check the configured runner and current Work Packet
run         implement a Work Packet with Claude and independent Codex review
status      inspect one packet's execution/review state
```

The methodology remains usable without the shell runner. `/forge preflight`, `/forge new`, `/forge adopt`, `/forge continue`, `/forge review`, and `/forge status` are Claude Code skill flows; the shell executable is an optional local execution helper.

## Optional external execution preflight

Work in the current agent session needs no extra readiness gate. Before requested external execution, local diagnostics are available without model requests or first-use configuration:

```bash
FORGE_DIR="$HOME/.claude/skills/forge"
"$FORGE_DIR/scripts/forge" preflight --review
```

Use `--task quick`, `--task planned` (default), or `--task high_risk` to apply a saved task-specific review policy. `--review` explicitly checks Codex. Missing preferences default to adaptive execution, explicit-only review, inherited authentication, and no required live probe. No preference file is created implicitly.

`preflight --configure` optionally saves durable choices in `.claude/forge/project-preferences.json` and local authentication intent in `.claude/forge/runtime/local-preferences.json`. Existing user choices should be reused. See [the preference example](../templates/project-preferences.example.json), [schema](../templates/project-preferences.schema.json), and [full preflight reference](../references/project-preflight.md).

The helper excludes runtime files from Git locally and stores no credential values. Local reports return:

- `READY` (exit 0): local prerequisites and any explicitly required live evidence pass.
- `READY_WITH_WARNINGS` (exit 1): usable prerequisites with a non-blocking warning.
- `BLOCKED` (exit 2): the requested external route cannot proceed under its current policy.

`--live` opts in to provider requests that use model allowance. It is never automatic. A saved `live_preflight_required: true` remains binding: run the authorized probe with the same `--task`/`--review` options before external execution. The runner checks saved preferences offline with `--review` before dispatch; a missing required probe blocks rather than secretly spending allowance.

### What live preflight verifies

Claude must return the exact requested answer in a valid successful JSON result; Codex must emit that answer and a successful completed turn. Exit code zero alone is insufficient. Claude's probe disables tools, skills, MCP configuration, hooks, and session persistence. Codex uses read-only, ephemeral execution with isolated configuration and high reasoning.

Report version 2 includes the requested operation, preference sources, observed versions/models, and original `live_checked_at`. Matching historical evidence can be reused while operation, preferences, CLI versions, and API-key override presence match. Failed local authentication invalidates it. An ordinary recheck preserves the original probe time and does not assert a new provider connection. Historical success never guarantees future provider access; no timer causes automatic reprobes. Earlier report versions are not reused as live proof.

## Prerequisites for the dual-agent runner

- reviewed or verified local Forge package outside the project being implemented
- macOS or Linux with Bash, Git, and Python 3.12+
- project Git repository with an existing commit and configured Git identity
- `claude` and `codex` available on `PATH` (this optional runner always uses both)
- valid `.claude/project-control.json`
- current passed Plan Consistency gate
- active Work Packet with current revisions, completed dependencies, bounded scope, acceptance, and validation
- clean working tree before a new packet starts

The repository lock prevents a second Forge runner across linked worktrees. It cannot prevent a human editor, another unrelated agent, or an external Git command from changing files while a run is active.

## Setup and first run

Use Forge to establish real requirements/control state first. The default control example supports single-agent work; invoking the runner opts the selected packet into independent review.

```bash
FORGE_DIR="$HOME/.claude/skills/forge"
python3 "$FORGE_DIR/templates/validate-project-control.py" .claude/project-control.json
"$FORGE_DIR/scripts/forge" --verbose doctor
"$FORGE_DIR/scripts/forge" run WP-1.1
"$FORGE_DIR/scripts/forge" --verbose status WP-1.1
```

Replace `WP-1.1` with the active packet. `run` and `status` may omit the ID only when exactly one packet is active. `status WP-ID` can inspect an inactive or completed packet that remains in control state.

`doctor` validates the execution profile, local CLI prerequisites, and current Work Packet without a model request. It is optional; `run` performs its own checks. Use `preflight --review` to diagnose saved authentication policy, and an authorized `preflight --review --live` only when a provider probe is needed.

## Execution profile

If `.claude/forge/execution-profile.json` is absent, the runner uses the bundled defaults:

- Claude Code implementation
- independent Codex review
- up to three review cycles
- no silent reviewer fallback
- simple/concise user output

The execution profile configures the runner mechanism. Project preflight preferences decide whether Forge should route a given project/task through that mechanism at all.

For adaptive projects:

- `substantial` review policy: Planned + High-Risk implementation uses Codex review
- `high_risk`: only High-Risk implementation requires Codex
- `explicit`: only when the user explicitly asks
- `never`: Claude-only execution

`dual_agent` requests Claude/Codex review for Planned and High-Risk implementation; `claude_only` does not require Codex. Calling `forge run` explicitly selects the dual-agent mechanism, including its independent reviewer.

Codex review is read-only and ephemeral, ignores user/project Codex rules/configuration for isolation, leaves model selection to the current provider, and explicitly requests `high` reasoning. Unsupported reasoning fails the review instead of silently lowering effort.

## Authentication

Forge inherits the environment and authenticated CLI sessions it launches.

For subscription-authenticated Claude Code, an exported `ANTHROPIC_API_KEY` can take precedence and use API billing. A saved local `subscription` preference blocks this conflict in preflight and before `run` dispatch. `api` requires a key; `inherit` preserves the current route and warns about an active override. Forge never silently switches billing modes or credentials.

Manual checks remain useful when diagnosing a machine:

```bash
env -u ANTHROPIC_API_KEY claude auth status
codex login status
command -v claude
command -v codex
claude --version
codex --version
```

If Codex reports model-metadata decoding errors, update the Codex CLI and verify that the binary Forge finds on `PATH` is the one you intended to update.

CLI permissions still apply after authentication succeeds. A successful login does not prove that project tests or every implementation command can run.

## What `run` changes

1. Validate project state, execution preconditions, and any saved authentication/live-probe policy using local checks.
2. Ask Claude Code to implement the packet and run relevant checks.
3. Preserve implementation evidence and create a local Git checkpoint with `git add -A`.
4. Review the immutable checkpoint in a temporary detached worktree with Codex's read-only sandbox.
5. Validate review identity/findings and route current-scope corrections through bounded cycles.
6. Stop on approval, a required decision, stale source/revisions, cycle limit, or provider failure.

The runner does not push, merge, deploy, or mark the project complete. Review approval covers the reviewed checkpoint only. Forge reconciliation still verifies acceptance/evidence and returns to the roadmap.

Checkpoint commits bypass Git hooks and are review snapshots, not release validation. Keep unrelated edits out of the checkout.

On macOS/Linux, agent CLIs run in owned process groups. Forge cleans remaining children on normal completion, timeout, Ctrl+C, or SIGTERM before checkpointing/releasing the lock. Deliberately detached sessions are outside that guarantee.

## Runtime state

Canonical project truth lives in `.claude/project-control.json` plus referenced project documents. Runner/preflight runtime evidence lives under `.claude/forge/runtime/`:

| Path | Purpose |
|---|---|
| `preflight.json` | latest local readiness evidence |
| `local-preferences.json` | machine-local Claude auth choice |
| `executions/WP-ID.json` | latest packet execution phase/checkpoint/counters |
| `handoffs/WP-ID-cycle-NN.json` | implementation handoff claims |
| `reviews/WP-ID-review-NN.json` | structured independent reviews |
| `deferred-findings/WP-ID.json` | out-of-scope findings with cycle provenance |
| `history.jsonl` | concise execution events |
| `stale-reviews/`, `invalid-control/` | preserved rejected-transition evidence |

Runtime files are local evidence, not tamper-proof approvals. Export durable findings/decisions into the project's normal records before deleting or moving the checkout.

## Recovery

For interruption or temporary CLI failure:

1. inspect `status WP-ID`, the Git diff, and the saved reason
2. fix the environment/auth issue or preserve/restore the intended checkpoint
3. check saved external preferences with `preflight --review` if CLI/auth/preferences changed; authorize a new live probe only if needed
4. rerun `run WP-ID`

Interrupted implementation can execute again because Forge cannot prove what an incomplete external process finished. Tests/migrations should tolerate the intended retry or be reconciled before resuming.

`escalated` and `reconcile_required` intentionally stop automation. Resolve the reason through the Forge controller instead of editing runtime JSON to manufacture approval.

## Validation limits

Deterministic tests exercise runner/preflight transitions, contracts, isolation properties, and failure handling with fake/local processes. They do not prove universal live-provider compatibility, model review quality, or sandbox security.

A macOS smoke test on 2026-09-06 used Claude Code 2.1.259 with a Max login and Codex CLI 0.153.4 for one bounded implementation/review path. Treat that as one observed integration result, not a supported-version matrix or evidence that Forge improves outcomes.
