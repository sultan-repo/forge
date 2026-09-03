# Forge

**A universal Claude Code skill for taking software and technical projects from rough intent to verified delivery without losing the original objective along the way.**

Forge helps Claude Code discover requirements, challenge assumptions, plan coherently, execute in bounded work packets, control scope drift, preserve context across long sessions, orchestrate specialist agents, verify implementation against the specification, and converge the finished system back to the approved intent.

The core idea is simple:

> Claude may change tactics, implementation details, sequencing, and even recommend a better direction, but it must never silently lose project intent.

## Why Forge exists

Long AI coding sessions often start well and then drift. A difficult bug, subsystem redesign, or deep investigation becomes the new center of gravity. Later milestones disappear from attention, requirements are forgotten, and a locally successful implementation can still leave the overall project incomplete.

Forge adds an active control loop around AI coding:

```text
Requirements
    ↓
Architecture + Plan
    ↓
Plan Consistency Gate
    ↓
Bounded Work Packets
    ↓
Implementation / Detours / Workers
    ↓
Reconciliation
    ↓
Verification
    ↓
Convergence Gate
    ↓
Canonical project truth
    ↓
Next approved work
```

## What Forge does

Forge provides a proportional methodology rather than forcing the same ceremony on every task.

- **Objective-first reasoning** — the real project outcome outranks an arbitrary initial implementation idea.
- **Adaptive requirements discovery** — asks only high-value questions and challenges weak assumptions.
- **Decision authority** — distinguishes autonomous choices from decisions that require explicit approval.
- **Scope conservation** — approved requirements and milestones cannot silently disappear.
- **Plan Consistency Gate** — verifies the plan covers the specification before significant coding starts.
- **Work Packets** — bounds implementation so deep local work does not become the whole project.
- **Detour control** — discovered work keeps a parent and return path.
- **Plan revisions** — stale workers/subagents must reconcile against the current plan before integration.
- **Context protection** — durable project state survives long sessions, `/compact`, `/clear`, and resumes.
- **Capability-aware orchestration** — chooses main-agent, subagent, worktree, agent-team, or sequential execution based on the work.
- **Verification-first delivery** — validates spec compliance before general engineering quality.
- **Convergence Gate** — checks the actual implementation against requirements, plan, design, and evidence before major closure.
- **Prompt-injection trust boundary** — retrieved files, logs, issues, websites, and tool output are evidence, not governing instructions.
- **Behavioral evals** — includes regression scenarios for testing the skill itself.

## Requirements

- Claude Code with personal skills support.
- Python 3 is recommended for the included optional validators/hooks.
- Git is recommended for normal project workflows and recovery checkpoints.

Optional Claude Code capabilities such as subagents, worktrees, hooks, agent teams, code intelligence, and browser/UI verification are used only when available and appropriate. Forge degrades gracefully when they are unavailable.

## Installation

### Option 1: clone directly into Claude skills

```bash
git clone https://github.com/sultan-repo/forge.git ~/.claude/skills/forge
```

Then restart or reload Claude Code if `/forge` does not immediately appear.

### Option 2: clone anywhere and run the installer

```bash
git clone https://github.com/sultan-repo/forge.git
cd forge
./scripts/install.sh
```

This installs the skill into:

```text
~/.claude/skills/forge/
```

## Slash command

Forge installs one manual skill command:

```text
/forge
```

Modes are arguments to the same command:

```text
/forge new [scope]
/forge adopt [scope]
/forge existing [scope]
/forge continue
/forge resume
/forge review
/forge status
/forge help
```

Aliases:

- `existing` = `adopt`
- `resume` = `continue`

The skill is deliberately manual-only. Forge should not unexpectedly activate its full project-governance workflow while you are doing an unrelated tiny task.

# Usage

## 1. Start a new project

Create or enter your project directory:

```bash
mkdir my-project
cd my-project
claude
```

Then invoke Forge:

```text
/forge new

Initial scope:
Build a web application that reads bank transaction SMS messages, categorizes spending, and gives users actionable financial insights.
```

Or use a single line:

```text
/forge new Build a web app that recommends the best movies currently showing in Saudi cinemas.
```

Forge will normally:

1. inspect the workspace
2. clarify the ultimate objective
3. run a focused requirements interview
4. identify assumptions, invariants, risks, and acceptance scenarios
5. confirm the material requirements baseline
6. evaluate architecture, reusable solutions, dependencies, and project structure
7. create only the durable project memory/control files justified by project complexity
8. produce milestones and bounded Work Packets
9. run the Plan Consistency Gate
10. implement when the original request authorizes implementation
11. reconcile after meaningful Work Packets
12. run convergence before major milestone/release closure

### Example

```text
/forge new Build an Android expense application that reads bank SMS messages.
The system should categorize transactions, provide useful spending insights,
and keep the user experience extremely simple. Implement it after we finalize requirements.
```

Forge should not immediately start coding from that vague scope. It should first determine the missing decisions that could materially change behavior or architecture.

## 2. Adopt an existing project

Open the existing repository:

```bash
cd existing-project
claude
```

Then run:

```text
/forge adopt

Objective:
Bring this project under Forge control and add a recurring subscription-management capability without breaking existing production behavior.
```

Or:

```text
/forge existing Add multi-account support while preserving current behavior and APIs.
```

For an existing project, Forge should first inspect actual evidence such as source code, tests, schemas and migrations, configuration, dependencies, APIs, CI/CD, deployment/infrastructure, existing documentation, current architecture and conventions, and runtime/log evidence when available.

It separates **actual current behavior** from **intended future behavior** and does not redesign a mature repository merely for stylistic preference.

## 3. Continue a controlled project

```text
/forge continue
```

or:

```text
/forge resume
```

Forge restores current project-control orientation before substantive implementation, including baseline/plan revisions, active Work Packets, detours, validation state, and resume queue.

## 4. Check status without starting new work

```text
/forge status
```

Typical output should summarize objective, current requirements baseline/revision, current plan revision, active/blocked Work Packets, open detours, Plan Consistency/Convergence gate state, requirement coverage, risks/blockers, validation state, and next approved actions.

## 5. Run a full project review

```text
/forge review
```

This performs a full-spectrum assessment of the project against its ultimate objective, actual implementation, requirements, architecture, security/privacy, reliability, UX, operations, cost, and other applicable concerns.

Forge does **not** automatically implement every idea discovered by a broad review. Findings are triaged against approved scope and normal decision gates.

## Work modes

Forge scales its process to the task.

### Quick Task

For a small reversible change, Forge should inspect, change, verify, and review without inventing a multi-milestone governance system.

### Planned Change

For meaningful multi-component work, Forge creates a plan and bounded Work Packets.

### High-Risk Change

Security, privacy, authentication, consequential migrations, production infrastructure, destructive data operations, major vendor/cost commitments, or difficult-to-reverse architecture receive stronger approval, rollback, evidence, and review requirements.

### Full-Spectrum Review

Used for major redefinition, production readiness, systemic failures, major architectural changes, or explicit comprehensive review.

## Control Mode

For substantial projects, Forge may install a small project-local execution-control kernel and machine-readable control state.

A representative project may contain:

```text
.claude/
├── rules/
│   └── execution-control.md
├── project-control.json
├── control/
│   └── validate-project-control.py
└── hooks/
    └── session-start-control.py
```

These files are **not mandatory for every project**. Forge creates/adapts them only when their value justifies the complexity.

### Scope Conservation

No confirmed material requirement, approved milestone, or accepted work item may silently disappear. Items stay traceable until completion or an authorized disposition.

### Work Packets

A Work Packet is a bounded local execution envelope with parent milestone/work packet, linked requirements/invariants, objective, in-scope and out-of-scope boundaries, acceptance criteria, validation, baseline/plan revision, dependencies, and return target.

A difficult implementation detour can go arbitrarily deep, but it must retain its relationship to the master roadmap.

### Plan Delta

Material changes to the approved roadmap use explicit Plan Deltas instead of silently rewriting history.

### Reconciliation

After meaningful Work Packets, Forge reconciles implementation back to the master plan before choosing another substantial task.

## Quality lifecycle

Forge adds two global gates around normal implementation verification.

### Plan Consistency Gate

Before significant coding, Forge checks that the approved requirements, architecture, milestones, Work Packets, dependencies, acceptance criteria, and validation strategy agree with each other.

This catches "the spec says ten things but the implementation plan only contains nine" before coding begins.

### Convergence Gate

Before major milestone/release/project closure, Forge compares actual implementation and evidence against the approved project truth.

It asks:

- **Completeness:** was every approved requirement actually implemented or properly dispositioned?
- **Correctness:** does behavior match the requirement?
- **Coherence:** does implementation align with design decisions and invariants?
- **Excess scope:** was anything significant implemented without approval?
- **Evidence:** can completion claims be demonstrated?

Completion means convergence, not merely "all tasks are checked off."

## AI orchestration

Forge does not use a fixed agent roster.

It selects the smallest execution model that provides enough confidence:

| Situation | Preferred approach |
|---|---|
| Small/cohesive task | Main Claude session |
| Large repository exploration | Fresh subagent |
| Bounded independent Work Packet | Fresh subagent when context isolation helps |
| Independent verification | Fresh reviewer/subagent |
| Parallel edits in separate areas | Isolated ownership/worktrees |
| Specialists need active coordination | Agent team when available and justified |
| Same-file tightly coupled change | Single editing context |

More agents are not automatically better. Additional workers should have distinct expected information value.

## Security model

Forge treats retrieved content as untrusted evidence by default.

Instructions found in code comments, README files, logs, websites, GitHub issues, package metadata, uploaded documents, or tool output cannot override trusted user/project instructions merely because Claude read them.

The skill also emphasizes least privilege, secret protection, reversible changes, migration safety, and deterministic enforcement through tests/CI/types/schema constraints/hooks/permissions where appropriate.

## Package layout

```text
forge/
├── SKILL.md
├── README.md
├── CHANGELOG.md
├── VERSION
├── CONTRIBUTING.md
├── references/
├── templates/
├── evals/
├── scripts/
└── .github/workflows/
```

## Validate Forge

Run:

```bash
python3 scripts/validate-skill-package.py
```

The package also contains behavioral regression scenarios under `evals/`. These are intended for periodic with-Forge vs no-Forge benchmarking after material methodology changes.

## Design philosophy

Forge deliberately avoids universal bureaucracy: no mandatory framework or language, no fixed folder tree, no fixed agent roster, no mandatory reviewer count, no mandatory TDD for trivial changes, no automatic broad refactoring, and no assumption that every project needs AI, queues, human review, complex operations, or agent teams.

The process depth should match the project's actual complexity and risk.

## Version

Current version: **1.4.0**

Forge is the renamed continuation of the Project Execution methodology through v1.3.0. The command changed from `/project-execution` to `/forge` in v1.4.0.

## License

No open-source license is included yet. Public visibility on GitHub does not itself grant reuse rights. Add the license you want before inviting external reuse or contributions.
