# Forge

**Keep AI coding agents aligned with the project, not just the task in front of them.**

[![Validate Forge](https://github.com/sultan-repo/forge/actions/workflows/validate.yml/badge.svg)](https://github.com/sultan-repo/forge/actions/workflows/validate.yml)
[Latest release](https://github.com/sultan-repo/forge/releases/latest) · [MIT License](LICENSE)

Forge is a Claude Code skill that helps turn a rough idea into a structured project, preserve scope across long coding sessions, recover after context loss, and check that the finished implementation still matches what you originally asked for.

You do not need to learn Forge's internal workflow before using it.

## Start with your project idea

From your project folder, open Claude Code and say:

```text
Use Forge from https://github.com/sultan-repo/forge to build:

[your project idea]
```

Claude Code follows Forge's [bootstrap instructions](BOOTSTRAP.md) to select and load the latest published stable release, then chooses how much structure the project needs. First-time loading requires repository access. Small tasks should stay small; larger projects can use stronger project-control features.

## Project preflight

For a substantial project, Forge now verifies how you want it to work **before implementation starts** instead of assuming your agent setup is ready.

On first setup Forge can ask a short set of project questions:

- Claude only, Claude + Codex, or adaptive execution
- whether the current Claude Code model selection is acceptable
- when Codex should independently review work
- whether this machine should use a Claude subscription login, API-key billing, or inherited authentication
- whether a small live readiness probe is required before substantial work

Project execution preferences are stored under:

```text
.claude/forge/project-preferences.json
```

Machine-local authentication/readiness evidence stays under `.claude/forge/runtime/` and should not be committed.

The optional shell helper provides the same readiness check:

```bash
scripts/forge preflight --configure
scripts/forge preflight --live
```

Preflight reports one of:

```text
READY
READY_WITH_WARNINGS
BLOCKED
```

If your project requires Codex review, Forge verifies Codex before significant implementation and does not silently fall back to Claude-only execution. If Claude subscription use is selected, an active `ANTHROPIC_API_KEY` override is treated as a blocker rather than being discovered halfway through the project.

Quick low-risk tasks can still stay lightweight and do not need persistent preflight unless they actually depend on an external agent.

## What Forge does

Forge helps Claude Code with four things:

1. **Clarify what you are building**  
   It challenges missing requirements, weak assumptions, contradictions, and important edge cases before significant implementation.

2. **Keep the project on track**  
   Approved features and decisions stay connected to the project objective even during debugging, research, long sessions, or parallel work.

3. **Recover after context loss**  
   Important project state can be stored durably instead of depending only on conversation history.

4. **Check the finished result**  
   Forge looks beyond "the tests passed" and asks whether the approved project was actually completed.

For substantial projects, Forge may use Work Packets, revisioned control state, reconciliation, lifecycle hooks, or independent review. You do not need to configure those concepts manually for normal use.

## When Forge is useful

Use Forge when your project:

- will take more than one coding session
- has multiple features or milestones
- has requirements that may evolve as you learn more
- involves debugging or research that could derail the roadmap
- uses multiple agents, workers, or worktrees
- needs reliable handoff or context recovery
- needs completion checked against the original project objective, not only the current task

For a tiny reversible change, Forge should stay lightweight.

## What Forge may add to your project

Forge does **not** impose a universal folder structure.

For small tasks, it may add no persistent project-control files at all. For larger projects, it may maintain a compact control area such as:

```text
.claude/
├── project-control.json
└── forge/
    └── project-preferences.json
```

That state can keep track of requirements, milestones, active work, revisions, blockers, execution preferences, validation status, and where to resume next.

Forge should add only the control surface justified by the project.

## Common commands

After Forge is installed, you can use natural language or the skill commands below.

```text
/forge preflight
/forge new [scope]
/forge adopt [scope]       # existing project
/forge continue            # resume
/forge review
/forge status
/forge help
```

These commands run inside Claude Code. `/forge preflight` establishes or checks project readiness; `/forge status` summarizes the project. The optional shell runner provides `preflight`, `doctor`, `run`, and `status`; see the [runner guide](docs/runner.md).

Natural language works too:

```text
Use Forge to build ...
```

```text
Use Forge to adopt this existing repository and add ...
```

Forge's skill description tells Claude to load it only when you explicitly request its use. Natural-language loading relies on Claude following that instruction; it is not an enforced invocation boundary. Use `/forge` for direct invocation. See [Claude Code's skill invocation controls](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill).

## Install Forge permanently

The easiest approach is to ask Claude Code:

```text
Install the latest stable Forge release persistently from:
https://github.com/sultan-repo/forge

Verify the release and asset before installing it.
```

The preferred location is:

```text
~/.claude/skills/forge/
```

For normal use, prefer a verified stable release rather than cloning mutable `main` into your permanent skill directory.

See [BOOTSTRAP.md](BOOTSTRAP.md) for the security and provenance details.

## Updating Forge

- **Loading Forge from the repository URL:** the bootstrap instructions select the latest stable release unless you explicitly request a version or commit. The loaded instructions remain in use for the current session; subsequent `/forge` commands do not themselves fetch updates.
- **Already installed locally:** Claude Code uses the installed copy until you deliberately update it.
- **Need exact reproducibility:** specify an immutable release or commit.

Forge does not silently force existing projects to upgrade when a newer release appears.

## Advanced: independent Codex review

Forge can optionally use a local runner for an already-planned unit of work:

```text
Claude Code  -> implementation
Codex        -> independent review
Forge        -> reconciliation and continuation
```

This is **optional**. You do not need Codex, Docker, or the local runner for normal Forge usage.

The runner is intended for projects already using Forge's durable project-control mode. It uses your locally authenticated Claude Code and Codex CLIs, creates Git checkpoints, and keeps review tied to the exact implementation checkpoint.

For reviewer quality, Forge does not pin a Codex model name. It uses the model selected by the current Codex CLI/provider and explicitly requests **high reasoning effort** for each independent review. If the active Codex setup cannot honor that request, the review fails instead of silently dropping to a lower effort.

A real disposable-project smoke test has successfully exercised the Claude Code -> Codex review path. That proves one observed integration path, not a universal provider/version compatibility guarantee.

If you use Claude Pro or Max, note that an exported `ANTHROPIC_API_KEY` can override subscription authentication for non-interactive Claude Code. Project preflight detects that mismatch when subscription use is selected. See the [runner setup and recovery guide](docs/runner.md) for authentication, CLI compatibility, permissions, recovery, and commands.

## Evidence

Forge includes automated regression tests and an executable A/B benchmark designed to measure:

- scope retention
- debugging tunnel vision
- context-loss recovery
- proportionality on small changes

The implementation, benchmark harness, release controls, and one real Claude Code -> Codex integration path have been tested.

**Real with-Forge vs without-Forge performance results have not yet been published.** Mock and deterministic tests validate the implementation and measuring instrument; they do not prove comparative effectiveness.

See [Evaluation](evals/README.md) for the benchmark design and evidence rules.

## What Forge is not

Forge is not a guarantee that every requirement is complete, every agent decision is correct, or every finished product meets its business goal.

It is a project-control method and set of optional helpers that make important scope, state, review, readiness, and completion checks more explicit and durable.

Forge does not prescribe a fixed framework, mandatory folder tree, fixed agent roster, or universal TDD process.

A one-line low-risk change should still feel like a one-line low-risk change.

## Learn more

- [How Forge works](SKILL.md)
- [Worked example](references/example-walkthrough.md)
- [Scope and plan control](references/scope-and-plan-control.md)
- [Claude Code integration](references/claude-code-integration.md)
- [Runner setup and recovery](docs/runner.md)
- [Bootstrap and installation security](BOOTSTRAP.md)
- [Evaluation and benchmarks](evals/README.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT. See [LICENSE](LICENSE).
