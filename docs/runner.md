# Optional local agent runner

Forge's shell helper has four commands:

```text
preflight   configure/verify project execution readiness
doctor      check the configured runner and current Work Packet
run         implement a Work Packet with Claude and independent Codex review
status      inspect one packet's execution/review state
```

The methodology remains usable without the shell runner. `/forge preflight`, `/forge new`, `/forge adopt`, `/forge continue`, `/forge review`, and `/forge status` are Claude Code skill flows; the shell executable is an optional local execution helper.

## Project preflight

For Planned or High-Risk work, run preflight before relying on the local agent setup:

```bash
FORGE_DIR="$HOME/.claude/skills/forge"
"$FORGE_DIR/scripts/forge" preflight --configure
"$FORGE_DIR/scripts/forge" preflight --live
```

Interactive configuration asks only choices that materially affect execution:

- adaptive / Claude-only / dual-agent execution
- whether the current Claude Code model selection is acceptable
- when Codex review should be required
- local Claude authentication intent: subscription / API key / inherit
- whether live readiness must be proven before substantial work

Durable project preferences live at:

```text
.claude/forge/project-preferences.json
```

The default shape is documented in [project-preferences.example.json](../templates/project-preferences.example.json) and [its schema](../templates/project-preferences.schema.json).

Authentication choice and readiness evidence are machine-local and live under:

```text
.claude/forge/runtime/local-preferences.json
.claude/forge/runtime/preflight.json
```

The preflight helper adds `.claude/forge/runtime/` to Git's local exclude file. It never stores or prints secret values.

Preflight returns:

- `READY` with exit code 0: the requested execution route is usable
- `READY_WITH_WARNINGS` with exit code 1: local checks pass, but a configured live probe or another non-fatal condition still needs attention
- `BLOCKED` with exit code 2: the configured route must not be used yet

When live verification is required, a prior successful live report can be reused only while project/local preferences, Claude/Codex CLI versions, and API-key override presence remain unchanged. If those inputs change, run `preflight --live` again.

### What live preflight verifies

The live probe is deliberately tiny and no-edit:

- Claude Code can make a real provider request with the selected local auth mode
- subscription mode is blocked when `ANTHROPIC_API_KEY` is present, because that variable can override subscription login in non-interactive Claude Code
- API mode is blocked when no API key is present
- Codex sign-in and required isolated-review flags are checked whenever the project may use Codex
- Codex receives a real read-only ephemeral request with `model_reasoning_effort="high"`

Forge does not pin a transient Claude or Codex model name. The current Claude Code model selection remains the project model policy; the live report records a model ID only when the CLI actually reports one.

If a project is configured for Codex review and Codex cannot be verified, preflight is `BLOCKED`. Forge must not silently downgrade that project to Claude-only execution.

## Prerequisites for the dual-agent runner

- reviewed or verified local Forge package outside the project being implemented
- macOS or Linux with Bash, Git, and Python 3.12+
- project Git repository with an existing commit and configured Git identity
- `claude` and, when review is configured, `codex` available on `PATH`
- valid `.claude/project-control.json`
- current passed Plan Consistency gate
- active Work Packet with current revisions, completed dependencies, bounded scope, acceptance, and validation
- clean working tree before a new packet starts

The repository lock prevents a second Forge runner across linked worktrees. It cannot prevent a human editor, another unrelated agent, or an external Git command from changing files while a run is active.

## Setup and first run

Use Forge to establish real requirements/control state first. The default control example supports single-agent work; invoking the runner opts the selected packet into independent review.

```bash
FORGE_DIR="$HOME/.claude/skills/forge"
mkdir -p .claude/forge

if [ ! -e .claude/forge/execution-profile.json ]; then
  cp "$FORGE_DIR/templates/execution-profile.example.json" .claude/forge/execution-profile.json
fi

python3 "$FORGE_DIR/templates/validate-project-control.py" .claude/project-control.json
"$FORGE_DIR/scripts/forge" preflight
"$FORGE_DIR/scripts/forge" --verbose doctor
"$FORGE_DIR/scripts/forge" run WP-1.1
"$FORGE_DIR/scripts/forge" --verbose status WP-1.1
```

Replace `WP-1.1` with the active packet. `run` and `status` may omit the ID only when exactly one packet is active. `status WP-ID` can inspect an inactive or completed packet that remains in control state.

`doctor` validates the execution profile, Claude/Codex CLI readiness, and the current Forge Work Packet. It is narrower than project preflight: use `preflight --live` when you need proof that provider/auth settings actually work before substantial execution.

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

`dual_agent` means Planned and High-Risk implementation requires the runner; `claude_only` means Codex is not required.

Codex review is read-only and ephemeral, ignores user/project Codex rules/configuration for isolation, leaves model selection to the current provider, and explicitly requests `high` reasoning. Unsupported reasoning fails the review instead of silently lowering effort.

## Authentication

Forge inherits the environment and authenticated CLI sessions it launches.

For subscription-authenticated Claude Code, an exported `ANTHROPIC_API_KEY` can take precedence and use API billing. Preflight catches this when the project is configured for subscription use.

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

1. Validate project state and execution preconditions.
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
3. rerun preflight if CLI/auth/preferences changed
4. rerun `run WP-ID`

Interrupted implementation can execute again because Forge cannot prove what an incomplete external process finished. Tests/migrations should tolerate the intended retry or be reconciled before resuming.

`escalated` and `reconcile_required` intentionally stop automation. Resolve the reason through the Forge controller instead of editing runtime JSON to manufacture approval.

## Validation limits

Deterministic tests exercise runner/preflight transitions, contracts, isolation properties, and failure handling with fake/local processes. They do not prove universal live-provider compatibility, model review quality, or sandbox security.

A macOS smoke test on 2026-09-06 used Claude Code 2.1.259 with a Max login and Codex CLI 0.153.4 for one bounded implementation/review path. Treat that as one observed integration result, not a supported-version matrix or evidence that Forge improves outcomes.
