# Forge

**AI coding agents are great at finishing the task in front of them. Forge helps them finish the project.**

[![Validate Forge](https://github.com/sultan-repo/forge/actions/workflows/validate.yml/badge.svg)](https://github.com/sultan-repo/forge/actions/workflows/validate.yml)
[Latest release](https://github.com/sultan-repo/forge/releases/latest) · [MIT License](LICENSE)

Forge is a Claude Code project-execution skill that turns rough ideas into validated requirements, keeps implementation aligned with the master plan, protects context across long sessions, coordinates available agent capabilities, and verifies the finished system against the original intent.

```text
Requirements -> Architecture -> Plan -> Build -> Verify
     ^                                         |
     |____________ Forge keeps it aligned _____|
```

> **Evidence status**
>
> Forge includes an executable, isolated A/B benchmark for scope retention, debugging tunnel vision, context-loss recovery, and proportionality. The benchmark instrument is CI-self-tested, but **real with-Forge vs no-Forge performance results have not yet been published**. Forge does not claim effectiveness percentages without measured runs.

## 10-second start

From a project folder, start Claude Code and say:

```text
Use Forge from https://github.com/sultan-repo/forge to implement:

[project scope]
```

No version number is required for normal use. Unless you explicitly request a release or commit, bootstrap resolves the latest published stable release at runtime and records the resolved identity when practical.

Forge can load the methodology for the current session even when it was not preinstalled.

## Why Forge exists

Long AI coding sessions often drift:

- rough scope becomes code before requirements are mature
- deep debugging becomes the new project
- approved requirements disappear from later work
- context loss or compaction weakens the roadmap
- workers return results based on stale assumptions
- unrelated review findings hijack scope
- tests pass while parts of the intended product were never built

Forge adds a control layer so **local progress cannot silently replace the project objective**.

## When to use Forge

Forge is most useful when:

- a project spans multiple milestones, sessions, or contributors
- requirements are incomplete, ambiguous, or likely to evolve
- debugging or research can derail later approved scope
- multiple workers, agents, worktrees, or task systems may be involved
- context loss, compaction, or handoff matters
- completion must be checked against an approved product objective rather than only a passing test suite

Forge intentionally stays lightweight for small reversible changes. If the task is simply “change this label and run the test,” Forge should behave accordingly.

## Typical AI coding vs Forge

| Typical AI coding | With Forge |
|---|---|
| Starts from rough scope | Challenges and enriches requirements |
| Optimizes the current task | Preserves the ultimate objective |
| Plan can silently drift | Explicit revisions and Plan Deltas |
| Deep debugging dominates | Bounded Work Packets with parent/return |
| Requirements can disappear | Scope Conservation |
| Worker context can go stale | Revision-aware reconciliation |
| More agents can create more noise | Capability-aware orchestration |
| Tests pass = “done” | Convergence checks the whole approved product |
| Context loss blurs the roadmap | Durable state + resume orientation |

## What Forge does

| Phase | Capability |
|---|---|
| Discovery | Objective clarification, requirements challenge/enrichment, assumptions, edge cases |
| Specification | Invariants, acceptance scenarios, traceability |
| Architecture | Alternatives, reuse, dependencies, migration/rollback |
| Planning | Milestones, Work Packets, validation, Plan Consistency |
| Execution | Scope Conservation, detours, Plan Deltas, revision control |
| Context | Durable state, resume queue, compaction/session recovery |
| Orchestration | Uses available workers/worktrees/tasks/hooks/collaboration only when useful |
| Debugging | Root-cause discipline with return to the roadmap |
| Review | Spec compliance first, scope-aware finding triage |
| Security | Trust boundary, least privilege, risky-change safeguards |
| Completion | Requirement coverage and Convergence |
| Methodology QA | Behavioral evals plus an executable isolated A/B benchmark harness |

## Your first prompt is not the specification

Forge treats initial scope as a starting point. Before significant work it can:

- identify missing requirements
- challenge weak assumptions
- detect contradictions
- surface edge cases and failure modes
- recommend simpler or stronger approaches
- identify relevant security, privacy, and non-functional requirements
- define invariants and acceptance scenarios
- distinguish blocking decisions from safe assumptions
- confirm a decision-ready requirements baseline

The goal is a **decision-ready specification instead of an enthusiastic guess**.

## Three protection layers

```text
1. REQUIREMENTS
Are we building the right thing?
        |
        v
2. PLAN CONSISTENCY
Did we plan everything approved?
        |
        v
   IMPLEMENTATION
        |
        v
3. CONVERGENCE
Did we actually build all of it?
```

### Requirements challenge

Validates and enriches the rough scope before significant planning.

### Plan Consistency Gate

Checks that requirements, invariants, architecture, milestones, Work Packets, dependencies, acceptance criteria, and validation agree before significant implementation.

### Convergence Gate

At major closure, compares actual implementation and evidence back to the approved requirements and plan. Completing all tasks is not enough if approved product behavior is missing.

## The anti-tunnel-vision mechanism

A difficult local problem is allowed to become important without becoming the whole project.

```text
M3
 └─ WP-3.4
     └─ blocking detour WP-3.4.1
          fix + verify
              |
          reconcile
              |
          return to WP-3.4
              |
          continue master roadmap -> M4 -> M5
```

See [the worked example](references/example-walkthrough.md) for concrete control state, a Work Packet, a mid-packet discovery, Plan Delta, reconciliation, and resume state.

## What Forge may add to your project

Forge does **not** impose a universal project structure.

For a small or low-risk task, it may add no persistent project-control files at all. For substantial projects using Control Mode, Forge may create or maintain a compact project-local control area such as:

```text
.claude/
├── project-control.json        # optional durable project-control state
└── hooks/ or control/          # optional lifecycle helpers when useful
```

Depending on project complexity and available Claude Code capabilities, durable state can track:

- requirements and milestone mappings
- active Work Packets
- baseline and plan revisions
- blocking detours, parents, and return targets
- gate status and validation state
- resume queue and reconciliation state

Lifecycle hooks and helper scripts are optional. Forge should add only the control surface justified by the project.

The bundled Python governance templates are conventional typed Python and are CI-checked with Ruff and strict mypy, so downstream repositories should not need blanket `.claude/` lint exclusions for Forge's own scripts.

## Forge and Claude Code built-ins

Forge does not replace Claude Code's native capabilities. It supplies the project-control methodology that connects them.

| Native capability class | Forge adds |
|---|---|
| Planning/read-only mode | Requirements readiness + Plan Consistency |
| Task/work-item system | Requirement linkage, revisions, parent/return, reconciliation |
| Persistent instructions/memory | Defines the durable project truth worth preserving |
| Lifecycle hooks | Defines which control invariants should be deterministic |
| Context-isolated workers | Work Packet boundaries + stale-result detection |
| Worktree/parallel isolation | Scope ownership + controlled integration |
| Agent collaboration | Decides when collaboration is worth the overhead |
| Verification/review/goal tools | Drives them from requirements + acceptance + Convergence |

Forge is deliberately **capability-first**. It does not hardcode model names, model generations, or temporary tool availability. It detects what the current environment can do and falls back gracefully.

See [Claude Code integration](references/claude-code-integration.md).

## Control Mode

For substantial projects Forge can maintain revisioned project state, Work Packets, Plan Deltas, gate state, and a resume queue.

When lifecycle hooks are available, Forge prefers a deterministic session-start orientation hook for Control Mode. Task-completion guards are optional and only apply when a native task lifecycle exists.

See:

- [scope and plan control](references/scope-and-plan-control.md)
- [optional lifecycle hooks](references/optional-task-hooks.md)

## Bootstrap security

A repository URL authorizes Forge to be **read**, not blindly executed. Forge bootstrap separates source selection, provenance verification, structural validation, installation, and activation.

When verifiable immutable/versioned release provenance is available, Forge prefers it. Otherwise it pins the resolved commit and avoids executing downloaded repository scripts, using agent-controlled file operations instead.

See [BOOTSTRAP.md](BOOTSTRAP.md).

## Usage

```text
/forge new [scope]
/forge adopt [scope]       # alias: existing
/forge continue            # alias: resume
/forge review
/forge status
/forge help
```

Natural language also works after installation:

```text
Use Forge to build ...
```

```text
Use Forge to adopt this existing repository and add ...
```

Forge auto-invocation is intentionally limited to explicit Forge requests.

## Install once

For normal use, prefer the latest verified stable release rather than cloning mutable `main` into your permanent skill directory.

The easiest persistent install is to ask Claude Code:

```text
Use the latest stable Forge release from:
https://github.com/sultan-repo/forge

Verify the release and asset, then install Forge persistently for Claude Code.
```

The preferred persistent location is:

```text
~/.claude/skills/forge/
```

For development or contributing to Forge itself, cloning `main` is appropriate:

```bash
git clone https://github.com/sultan-repo/forge.git
```

See [BOOTSTRAP.md](BOOTSTRAP.md) and [release guidance](docs/RELEASING.md) for provenance and fallback behavior.

### Which Forge version gets used?

- **Repository URL invocation:** bootstrap resolves the latest published stable release available at that time unless you explicitly request a version or commit.
- **Already installed locally:** Claude Code uses the installed copy until you deliberately update it.
- **Exact reproducibility:** specify an immutable release or commit when you need the same Forge identity across environments or experiments.

Forge does not silently require every existing project to upgrade when a newer release appears.

## Evaluation status

Forge includes behavioral regression scenarios and an **executable core benchmark instrument**.

The A/B harness provides real fixture repositories, hidden REQ-tagged tests, deterministic scoring, raw evidence capture, container-isolated fresh agent sessions, verified immutable Forge loading, activation preflight, paired/randomized arm order, and a genuine two-session context-loss test.

**No with-Forge vs no-Forge performance claims are published yet.** Mock self-tests validate the benchmark instrument only. We will not invent pass rates.

The core benchmark set covers:

1. scope retention
2. debugging tunnel vision
3. context-loss recovery across fresh sessions
4. proportionality on tiny changes

See [evals/README.md](evals/README.md), [CORE-BENCHMARKS.md](evals/CORE-BENCHMARKS.md), and the [executable harness](evals/core/README.md).

## What Forge is not

Forge is not a fixed framework, mandatory folder tree, fixed agent roster, universal TDD regime, or excuse to spawn many agents.

A one-line low-risk change should still feel like a one-line low-risk change.

## Package

```text
forge/
├── SKILL.md
├── BOOTSTRAP.md
├── README.md
├── LICENSE
├── references/
├── templates/
├── evals/
│   └── core/          # executable benchmark instrument
├── scripts/
└── docs/
```

Validate locally:

```bash
python3 scripts/validate-skill-package.py
```

## Development

Changes to Forge should preserve proportionality and be driven by observed failures rather than by accumulating universal rules. Methodology changes should be benchmarked when practical; release engineering and template-quality changes should be covered by deterministic CI.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Version

Current version: **1.7.1**

## License

MIT. See [LICENSE](LICENSE).
