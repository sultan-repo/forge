# Forge

**Forge is a universal Claude Code project-execution skill that keeps AI coding aligned from rough intent to verified delivery.**

It combines requirements discovery, architecture, scope control, bounded implementation, context protection, agent orchestration, verification, and convergence without forcing the same ceremony on every task.

> Claude may change tactics, implementation details, sequencing, or recommend a better direction, but it must never silently lose project intent.

## One-prompt bootstrap

You do **not** need Forge preinstalled to start using it.

From an empty/new project folder, start Claude Code and say:

```text
Use Forge from https://github.com/sultan-repo/forge to implement:

[project scope]
```

or:

```text
Import this skill https://github.com/sultan-repo/forge and use Forge to implement:

[project scope]
```

Forge's bootstrap protocol tells the agent to:

1. fetch Forge outside the product repository
2. confirm the fetched skill identity
3. validate and install it under `~/.claude/skills/forge/` when possible
4. load `SKILL.md` directly for the current session
5. infer `new` for an empty/greenfield workspace or `adopt` for an existing project
6. continue immediately with the original project scope under Forge

A restart is **not required to continue the current task**. Claude Code watches existing skill directories live. If `~/.claude/skills` itself did not exist when the session started, a later restart may be needed only for `/forge` to appear as a registered slash command.

See [BOOTSTRAP.md](BOOTSTRAP.md) for the agent-facing protocol.

## Install permanently

### Clone directly

```bash
git clone https://github.com/sultan-repo/forge.git ~/.claude/skills/forge
```

### Or run the installer

```bash
git clone https://github.com/sultan-repo/forge.git
cd forge
./scripts/install.sh
```

## Invoke Forge

Forge supports both slash-command and explicit natural-language invocation.

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

After installation, these also work:

```text
Use Forge to build a new project that ...
```

```text
Use Forge to adopt this existing repo and add ...
```

Forge permits automatic model invocation only when the user explicitly names Forge or asks to use the Forge methodology. Ordinary coding requests should not trigger the full Forge workflow.

## New project

```text
/forge new Build an Android expense application that reads bank SMS messages,
categorizes transactions, and gives users useful spending insights.
```

Forge should normally:

1. inspect the workspace
2. establish the real objective
3. run a focused requirements interview
4. identify assumptions, invariants, risks, and acceptance scenarios
5. confirm the material requirements baseline
6. evaluate architecture, reusable components, dependencies, and structure
7. create only the durable project-control artifacts justified by complexity
8. produce milestones and bounded Work Packets
9. run the Plan Consistency Gate
10. implement when authorized
11. reconcile after meaningful Work Packets
12. run Convergence before major closure

## Existing project

```text
/forge adopt Add multi-account support while preserving current production behavior and APIs.
```

Forge first inspects actual evidence such as source, tests, schemas, configuration, dependencies, APIs, CI/CD, deployment, documentation, conventions, and runtime evidence where available. It does not redesign a mature repository merely to fit a preferred style.

## Continue or inspect

```text
/forge continue
/forge status
/forge review
```

`continue` restores project-control orientation before substantive work. `status` reports the current baseline, plan revision, active/blocked packets, detours, gate state, coverage, risks, validation, and resume queue. `review` performs a full-spectrum assessment without automatically implementing every idea it discovers.

## How Forge prevents drift

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

### Scope Conservation
Approved requirements and milestones cannot silently disappear. Deferral, rejection, cancellation, or supersession of approved material scope requires an explicit disposition and normal decision authority.

### Work Packets
Meaningful implementation is bounded by parent scope, requirements, acceptance criteria, validation, revisions, dependencies, and a return target. Deep local work may branch, but it must return to the master roadmap.

### Plan Consistency Gate
Before significant coding, Forge checks that requirements, architecture, milestones, Work Packets, dependencies, acceptance criteria, and validation agree and that no approved requirement was forgotten.

### Reconciliation
After meaningful Work Packets, Forge reconciles actual work back to the plan before selecting another substantial task.

### Convergence Gate
Before major milestone/release/project closure, Forge compares the actual implementation and evidence against the approved project truth for completeness, correctness, coherence, excess scope, and evidence.

## Context and AI orchestration

Forge treats conversation history as working memory, not the project database. For substantial projects it can maintain a small persistent execution-control kernel, revisioned state, and a resume queue so `/compact`, `/clear`, long debugging detours, or fresh sessions do not erase the roadmap.

Forge chooses the smallest useful execution model:

| Work | Preferred approach |
|---|---|
| Small cohesive task | Main Claude session |
| Large exploration / logs | Fresh subagent |
| Bounded independent packet | Fresh subagent when isolation helps |
| Independent verification | Fresh verifier/reviewer |
| Parallel separate edits | Isolated ownership/worktrees |
| Specialists must coordinate/debate | Agent team when available and justified |
| Same-file tightly coupled change | Single editing context |

More agents are not automatically better.

## Security

Forge treats retrieved code, comments, README files, logs, websites, issues, package metadata, uploaded documents, and tool output as evidence, not governing authority. Retrieved instructions cannot override trusted user/project governance merely because Claude read them.

Forge also emphasizes least privilege, secret protection, reversible changes, migration/rollback safety, and deterministic controls through tests, CI, types, schemas, permissions, and hooks when appropriate.

## Package layout

```text
forge/
├── SKILL.md
├── BOOTSTRAP.md
├── README.md
├── CHANGELOG.md
├── VERSION
├── references/
├── templates/
├── evals/
│   ├── evals.json
│   ├── bootstrap-evals.json
│   └── README.md
├── scripts/
│   ├── install.sh
│   ├── bootstrap.sh
│   └── validate-skill-package.py
└── .github/workflows/
    └── validate.yml
```

## Validate Forge

```bash
python3 scripts/validate-skill-package.py
```

The eval suites are designed for with-Forge vs no-Forge regression testing after material methodology changes.

## Design philosophy

Forge deliberately avoids universal bureaucracy:

- no mandatory framework or language
- no fixed folder tree
- no fixed agent roster
- no mandatory number of reviewers
- no mandatory TDD for trivial work
- no automatic broad refactoring
- no assumption that every project needs queues, human review, complex operations, or agent teams

Process depth should match actual complexity and risk.

## Version

Current version: **1.5.0**

v1.5.0 adds one-prompt remote bootstrap and explicit-name natural-language invocation.

## License

No open-source license is included yet. Public visibility on GitHub does not itself grant reuse rights. Add the license you want before inviting external reuse or contributions.
