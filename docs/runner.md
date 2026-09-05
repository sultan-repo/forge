# Optional local agent runner

The shell runner is for an existing Forge Control Mode project with a bounded, approved Work Packet. It runs Claude Code as the implementation owner and Codex CLI as an independent reviewer. The methodology remains usable without either adapter or this runner.

`/forge new`, `/forge adopt`, `/forge continue`, and `/forge review` are skill instructions. The shell executable has only `doctor`, `run`, and `status`; it does not create requirements, plan the project, or perform final reconciliation.

## Prerequisites

- A reviewed or verified local Forge package, outside the project being implemented. See [bootstrap](../BOOTSTRAP.md).
- macOS or Linux with Bash, Git, and Python 3.12, the version used in CI. The runtime uses the Python standard library; pytest and static-check tools are only for developing Forge.
- A project Git repository with an existing commit and a configured Git author identity. Start with a clean index and working tree, including intended control files.
- `claude` and `codex` available on `PATH`, authenticated through their own CLIs. The reviewer requires the Codex flags checked by `doctor`; Forge does not configure accounts or store credentials.
- Valid `.claude/project-control.json`, a current passed Plan Consistency gate, and an active packet with `status: in_progress`, current baseline/plan revisions, and completed dependencies. Its objective, scope, acceptance, and validation must be available in the packet or canonical project documents.
- Exclusive ownership of implementation edits while the runner is active. The repository lock prevents a second Forge runner across linked worktrees; it cannot prevent an editor, another agent, or a Git command from changing files.

`doctor` checks local readiness and Codex sign-in. Claude account/model access is tested only when an actual implementation request starts. Passing `doctor` does not prove that a provider request will succeed, that permissions allow every project command, or that tests pass.

## Setup and first run

Use Forge in the project to establish actual requirements and control state first. [The control example](../templates/project-control.example.json) is a starting shape, not evidence that your plan is ready.

From the **project repository**, set the path to the installed package or reviewed development checkout:

```bash
FORGE_DIR="$HOME/.claude/skills/forge"
mkdir -p .claude/forge
if [ ! -e .claude/forge/execution-profile.json ]; then
  cp "$FORGE_DIR/templates/execution-profile.example.json" .claude/forge/execution-profile.json
fi
python3 "$FORGE_DIR/templates/validate-project-control.py" .claude/project-control.json
```

The setup preserves an existing profile. Inspect its settings before running. Commit the intended project and control changes using the project's normal process before the first run.

```bash
"$FORGE_DIR/scripts/forge" --verbose doctor
"$FORGE_DIR/scripts/forge" run WP-1.1
"$FORGE_DIR/scripts/forge" --verbose status WP-1.1
```

Replace `WP-1.1` with your active packet. `run` and `status` may omit the ID only when exactly one packet is active. An explicit `status WP-ID` can also inspect an inactive or completed packet that remains in control state. `doctor` currently checks that single-active-packet case, so projects with several active packets should inspect them separately before passing an explicit ID to `run`.

Global options precede the subcommand:

```bash
"$FORGE_DIR/scripts/forge" --control .claude/control/project.json --verbose status WP-1.1
"$FORGE_DIR/scripts/forge" --help
```

A custom control path must remain inside the project's `.claude/` directory. Keep canonical document pointers consistent with that location.

If the project profile is absent, the runner uses the bundled example defaults: Claude Code implementation, Codex review, up to three review cycles, and no fallback when a reviewer is unavailable. A project profile makes these choices explicit. Set `interaction.progress` or `interaction.detail` to `verbose` for phase progress or approval evidence details; `--verbose` enables both. Only the currently supported adapters and inherited authentication are accepted; this is not a general provider configuration system.

## What a run changes

1. Validate project state and execution preconditions.
2. Ask Claude Code to implement the packet and run relevant checks in the project checkout. Claude uses non-interactive print mode with `acceptEdits`; its CLI permissions still govern tool execution.
3. Preserve valid implementation evidence and create a local Git checkpoint of pending project changes. The runner stages all changes with `git add -A`, including new files. Use an appropriate `.gitignore` and keep unrelated edits out of the checkout.
4. Review the immutable checkpoint in a temporary detached Git worktree using Codex's read-only sandbox. The reviewer sees the packet's cumulative diff from its original base and must inspect primary repository evidence.
5. Validate the review identity and finding contract; route current-scope corrections through bounded implementation/review cycles. Record out-of-scope findings separately and surface serious ones.
6. Stop on review approval, a required decision, stale source/revisions, or a provider error. Local checkpoints and recovery records remain available. The runner does not push, merge, deploy, or mark the packet done.

Checkpoint commits bypass Git hooks. They are review snapshots, not release validation; the implementation and controller must run the applicable project checks explicitly. The runner does not itself sandbox the implementer. The reviewer sandbox is provided by Codex CLI, and a temporary worktree is not by itself a security boundary.

## Handoff, review, and completion

These records have different meanings:

| Record or state | Meaning |
|---|---|
| Implementation handoff | Commit, changed files, and implementer-reported acceptance, tests, discoveries, and uncertainty. These are claims for verification. |
| Structured review | Independent findings tied to packet ID, revisions, base commit, reviewed commit, and review cycle. |
| Execution `approved` | The recorded checkpoint passed the configured review. It is not approval of later source changes. |
| Packet reconciliation | The controller verifies acceptance/evidence, dispositions findings, updates requirements and packet state, and returns to the roadmap. |
| Convergence | At major closure, the controller compares the whole approved scope with the implemented system and evidence. |

Review approval can still include recorded non-blocking or out-of-scope findings. Inspect the review and give material gaps an explicit disposition during reconciliation; a passing review is not a claim of zero defects.

## State and recovery

Canonical project truth lives in `.claude/project-control.json` and the documents it references. Runtime records live under `.claude/forge/runtime/`:

| Path | Contents |
|---|---|
| `executions/WP-ID.json` | Latest phase, checkpoint identity, attempt/cycle counters, reason, approval state |
| `handoffs/WP-ID-cycle-NN.json` | Implementation evidence for a review cycle |
| `reviews/WP-ID-review-NN.json` | Completed structured reviews |
| `deferred-findings/WP-ID.json` | Findings outside current scope |
| `history.jsonl` | Concise execution events when history is enabled |
| `stale-reviews/`, `invalid-control/` | Preserved evidence from rejected transitions when applicable |

Runtime files are excluded using Git's local exclude file; they are not automatically shared with a clone or another machine. Preserve the needed evidence before moving the project or deleting a checkout. Export relevant findings into the project's normal durable issue/decision records during reconciliation.

For an interruption or temporary CLI failure:

1. Inspect `--verbose status WP-ID`, the actual Git diff, and any reported reason.
2. Resolve the CLI/authentication problem or restore the intended checkpoint if unrelated edits appeared. Preserve useful changes before any Git recovery operation.
3. Re-run `run WP-ID`. Interrupted implementation resumes from the remaining working tree; interrupted review targets the saved checkpoint. Do not erase runtime records simply to retry a provider error.

An interrupted implementation call may run again because the runner cannot prove what an incomplete external process finished. Project tests and migrations must tolerate the intended retry or be reconciled before resuming.

`escalated` and `reconcile_required` deliberately stop automatic execution. Resolve the stated issue and reconcile the source, requirements, and plan with the controller. For changed scope or a new bounded correction, create a new approved Work Packet and retain the old packet's evidence and disposition. There is currently no shell `reset`, `approve`, `resume`, or `reconcile` command, and editing the execution JSON to manufacture approval is not a recovery procedure.

`status` reports runtime phase without creating execution state. A changed source tree or baseline/plan revision makes a previous approval historical, and `status` returns 2 with the reason. Reconciliation-only changes to the configured control file are allowed when revisions and source remain unchanged; this does not authorize changing requirement meaning without updating its baseline. `status` does not verify business correctness. Exit code 0 from `run` means the current run's review passed, and exit code 2 means it cannot proceed or needs a decision. A successful `status` or `doctor` has its own narrower meaning.

## Validation limits

Deterministic tests use fake adapters and local subprocesses to exercise runner transitions, review contracts, and failure handling. They do not establish live Claude/Codex API compatibility, actual model review quality, or sandbox security. Validate live provider execution in an appropriately scoped project before depending on this optional integration operationally.
