# Changelog

## 1.5.0

Adds one-prompt remote bootstrap and explicit-name natural-language invocation.

- adds `BOOTSTRAP.md` with an agent-facing remote installation/activation protocol
- adds `scripts/bootstrap.sh` for validate + install + current-session activation guidance
- changes `disable-model-invocation` to `false` while narrowing the skill description so Claude should auto-invoke Forge only when the user explicitly names Forge or requests the Forge methodology
- allows prompts such as `Use Forge from https://github.com/sultan-repo/forge to implement: ...`
- requires remote bootstrap to keep Forge outside the product source tree
- loads Forge directly in the bootstrap session so command-registration restart is not a blocker
- documents Claude Code's live skill discovery caveat when the top-level skills directory did not exist at session start
- hardens `scripts/install.sh` for direct-in-place installations
- adds `evals/bootstrap-evals.json` with remote-bootstrap and installed natural-language invocation regressions

## 1.4.0

Renames the skill and public command from **Project Execution** / `/project-execution` to **Forge** / `/forge`.

- renames skill frontmatter to `forge`
- renames package/install directory to `forge`
- updates all command examples and internal references
- updates behavioral eval identity to `forge`
- updates structural validator identity/version
- adds public-repository README with new-project, existing-project, resume, status, and review usage
- adds `scripts/install.sh` for personal Claude Code installation
- adds GitHub Actions package validation
- adds contribution guidance and repository hygiene
- preserves the v1.3 methodology and control model unchanged

### Breaking command change

Previous:

```text
/project-execution ...
```

Current:

```text
/forge ...
```

## 1.3.0

Extends plan-control into the full intent-to-code lifecycle:

- adds explicit invocation modes: `new`, `adopt/existing`, `continue/resume`, `review`, `status`, `help`
- adds Plan Consistency Gate before significant implementation
- adds Convergence Gate at major milestone/release/project closure
- adds prompt-injection/untrusted retrieved-content trust boundary
- adds review-finding scope triage separate from severity
- adds capability-aware orchestration routing across main agent, subagents, isolated worktrees/sessions, agent teams, and batch/fan-out mechanisms
- adds controller context-budget rule and compact worker return contracts
- adds high-impact assumption checkpoint
- adds Work Packet sizing/splitting criteria
- adds large-codebase code-intelligence/orientation guidance
- adds Plan Delta canonicalization/archive so current truth stays compact while history is preserved
- adds important user-facing acceptance-scenario guidance
- adds v3 project-control state with Plan Consistency/Convergence gate tracking
- updates SessionStart orientation to include gate state
- expands control validator for v3 state and stale gate warnings
- adds `evals/evals.json` behavioral regression suite
- adds structural package validator under `scripts/validate-skill-package.py`

## 1.2.0

Hardens plan continuity and context recovery:

- requires a small persistent Execution Control Kernel for Control Mode
- closes the scope-disposition loophole: terminal status does not authorize scope removal
- adds requirements-baseline and plan revisioning
- adds stale-worker/subagent detection and reconcile-before-integration rule
- replaces singular active milestone/packet with parallel-capable arrays and `resume_queue`
- normalizes requirement/milestone/work-packet status enums
- adds generic project-control JSON Schema and Python validator
- adds optional SessionStart context injection for startup/resume/clear/compact
- updates optional task-hook guidance
- adds recoverable checkpoint guidance for risky exploration
- trims the core SKILL.md and pushes deep mechanics into references/templates

## 1.1.0

Added Scope Conservation, Work Packets, detours, Plan Deltas, reconciliation gates, requirement coverage, controller/worker separation, and optional Claude Tasks integration.

## 1.0.0

Initial universal forge skill.
