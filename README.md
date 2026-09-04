# Forge

**AI coding agents are great at finishing the task in front of them. Forge helps them finish the project.**

Forge is a Claude Code project-execution skill that turns rough ideas into validated requirements, keeps implementation aligned with the master plan, protects context across long sessions, coordinates available agent capabilities, and verifies the finished system against the original intent.

```text
Requirements -> Architecture -> Plan -> Build -> Verify
     ^                                         |
     |____________ Forge keeps it aligned _____|
```

## Why Forge exists

Long AI coding sessions often drift:

- rough scope becomes code before requirements are mature
- deep debugging becomes the new project
- approved requirements disappear from later work
- context compaction weakens the roadmap
- workers return results based on stale assumptions
- unrelated review findings hijack scope
- tests pass while parts of the intended product were never built

Forge adds a control layer so **local progress cannot silently replace the project objective**.

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
| Tests pass = "done" | Convergence checks the whole approved product |
| Context loss blurs the roadmap | Durable state + resume orientation |

## 10-second start

From a project folder, start Claude Code and say:

```text
Use Forge from https://github.com/sultan-repo/forge to implement:

[project scope]
```

No version number is required for normal use. Unless the user explicitly requests a release or commit, bootstrap resolves the latest published stable release at runtime and records the resolved identity when practical.

Forge can load the methodology for the current session even when it was not preinstalled.

### Bootstrap security

A repository URL authorizes Forge to be **read**, not blindly executed. Forge bootstrap separates source selection, provenance verification, structural validation, installation, and activation.

When verifiable immutable/versioned release provenance is available, Forge prefers it. Otherwise it pins the resolved commit and avoids executing downloaded repository scripts, using agent-controlled file operations instead.

See [BOOTSTRAP.md](BOOTSTRAP.md).

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
| Methodology QA | Behavioral evals and benchmark protocol |

## Your first prompt is not the specification

Forge treats initial scope as a starting point. Before significant work it can:

- identify missing requirements
- challenge weak assumptions
- detect contradictions
- surface edge cases/failure modes
- recommend simpler or stronger approaches
- identify relevant security/privacy/non-functional requirements
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
At major closure, compares actual implementation/evidence back to the approved requirements and plan. Completing all tasks is not enough if approved product behavior is missing.

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

See [the worked example](references/example-walkthrough.md) for actual control state, a Work Packet, a mid-packet discovery, Plan Delta, reconciliation, and post-compaction resume state.

## Forge and Claude Code built-ins

Forge does not try to replace Claude Code's native capabilities. It supplies the project-control methodology that connects them.

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

## Install permanently

```bash
git clone https://github.com/sultan-repo/forge.git ~/.claude/skills/forge
```

For stronger supply-chain assurance, prefer a verified immutable/versioned release when available. See [release guidance](docs/RELEASING.md).

## Evaluation status

Forge includes behavioral regression scenarios and a core benchmark protocol.

**No with-Forge vs no-Forge performance claims are published yet.** We will not invent pass rates.

The initial core benchmark set covers:

1. scope retention
2. debugging tunnel vision
3. compaction recovery
4. proportionality on tiny changes

See [evals/README.md](evals/README.md) and [CORE-BENCHMARKS.md](evals/CORE-BENCHMARKS.md).

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
├── scripts/
└── docs/
```

Validate:

```bash
python3 scripts/validate-skill-package.py
```

## Version

Current version: **1.6.2**

## License

MIT. See [LICENSE](LICENSE).
