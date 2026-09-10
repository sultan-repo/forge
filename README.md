# Forge

**Keep the whole project in view.**

A Claude Code skill for preserving requirements, recovering context, and checking completion across coding sessions. Quick changes follow a direct path. Larger projects gain structure when the work calls for it.

[![Validate Forge](https://github.com/sultan-repo/forge/actions/workflows/validate.yml/badge.svg)](https://github.com/sultan-repo/forge/actions/workflows/validate.yml)
[Latest release](https://github.com/sultan-repo/forge/releases/latest) · [Changelog](CHANGELOG.md) · [MIT license](LICENSE)

## Start with the outcome

Open Claude Code in your project folder and describe what you want:

```text
Use Forge from https://github.com/sultan-repo/forge to:

[Build, change, or finish something. Include the constraints that matter.]
```

This works for a new idea or an existing repository. The [bootstrap instructions](BOOTSTRAP.md) guide the agent through selecting and verifying the latest stable release, loading Forge, and continuing your request. First use needs repository access. You can use Forge for the current session before deciding to install it permanently.

Already installed? Start with `/forge new …`, `/forge adopt …`, or `/forge continue`.

## Where Forge helps

Long projects ask an agent to remember more than the next edit: what was approved, why a decision changed, which checks ran, and what remains after a detour.

Forge gives that work a consistent method:

- **Preserve scope.** Keep approved requirements and later milestones accounted for while fixing the immediate problem.
- **Resume from evidence.** Check the plan, status, code changes, and test results before trusting an old “done” note or repeating an investigation.
- **Handle changes deliberately.** Synchronize requirements affected by the request while preserving unrelated constraints and project rules.
- **Explain completion.** Connect claims to observed checks and identify failed or unverified work. Reporting a gap does not make it complete.

Its intended fit is work with dependencies, interruptions, evolving requirements, or multiple contributors. These are design goals; [evidence and limits](#evidence-and-limits) describes what has been verified.

## Structure follows the task

Forge's instructions route work by scope and consequences:

| Situation | Expected approach |
|---|---|
| A bounded change with a clear check | Inspect, edit, verify, finish. No setup interview, formal plan, extra agents, or new control files by default. |
| Dependent work, a substantial detour, or a project spanning sessions | Reuse the existing plan and status; record requirements, decisions, blockers, evidence, and the next action. |
| A consequential security, privacy, data, production, or compatibility change | Add safeguards and required review before the affected action, even if the edit is small. |

Planning and risk references load only when relevant. The agent reuses authorization already given and asks when a material decision is missing or an action exceeds that authority.

For example, if a CSV import bug interrupts an approved import-and-export feature, fixing the parser should not erase the export requirement. On resumption, Forge should check saved claims against the code and evidence, then continue the work your request includes.

### State that fits your project

Forge prefers the plan or status document you already use. A quick task may add no persistent state. Longer work needs enough context to answer: what is approved, what is verified, what is blocked, and what comes next?

Structured state such as `.claude/project-control.json`, lifecycle hooks, and revisioned work packets are available when dependencies or automation justify them. A work packet is a bounded unit of planned work with acceptance checks. These mechanisms are optional for ordinary skill use; the external runner requires structured state.

## Use Forge in Claude Code

| Skill command | Purpose |
|---|---|
| `/forge new [request]` | Develop a new project from the requested outcome. |
| `/forge adopt [request]` | Work with an existing repository and its conventions. |
| `/forge continue` | Reconcile saved state with evidence and resume approved work. |
| `/forge review [scope]` | Assess work against its requirements and checks. |
| `/forge status` | Summarize progress, blockers, and next steps without implementation. |
| `/forge help` | Explain usage without starting implementation. |
| `/forge preflight` | Check readiness for a requested external-agent workflow. |

Natural language works too: “Use Forge to add CSV export to this repository.” Forge's description asks Claude to load it only when explicitly requested; natural-language loading depends on the agent following that instruction. `/forge` invokes it directly.

Skill commands run inside Claude Code. They are distinct from the optional [shell runner commands](docs/runner.md).

## Install or update

For repeated use, ask Claude Code:

```text
Install or update Forge to the latest stable release from:
https://github.com/sultan-repo/forge

Verify the release and downloaded asset before installing it.
Report the installed version and location.
```

The preferred location is `~/.claude/skills/forge/`, outside your product source tree. The bundled installer uses Bash and Python 3 to validate the package before replacing an existing copy.

An installed copy stays at its version until you update it. Invoking `/forge` does not fetch a new release. Specify a release tag or commit when reproducibility matters; prefer a verified stable release for everyday use.

If command discovery needs a reload, the agent can read `SKILL.md` directly and continue the current request. The [bootstrap guide](BOOTSTRAP.md) covers verification, installation, and fallbacks.

## Optional: independent review

For a planned work packet, Forge's local runner can use Claude Code to implement and Codex CLI to review an immutable Git checkpoint, with bounded correction cycles and interruption recovery. After the runner stops, the agent using Forge still needs to reconcile requirements and evidence. Review approval alone does not mark the project complete.

Normal skill use needs neither Codex, Docker, nor this runner. The runner requires macOS or Linux, both authenticated CLIs, Git, Bash, Python 3.12+, and valid project-control state. Review requests high reasoning effort and fails if the active setup cannot honor it; no model name is pinned.

After installing Forge, check the external route from your project directory:

```bash
"$HOME/.claude/skills/forge/scripts/forge" preflight --review
```

This performs local checks. `--configure` optionally saves preferences; `--live` explicitly makes provider calls. External sessions and live probes consume model allowance. When subscription authentication is selected, preflight blocks an `ANTHROPIC_API_KEY` override instead of silently switching billing routes.

See the [runner guide](docs/runner.md) for setup, authentication, execution, and recovery, and the [preflight reference](references/project-preflight.md) for readiness policies.

## Evidence and limits

Automated checks cover package validation, installation, state handling, runner recovery, and specific benchmark-isolation properties. The [validation record](docs/VALIDATION.md) documents the adaptive revision's checks and two limited behavioral smoke tests. The [runner guide](docs/runner.md#validation-limits) records one observed live Claude Code → Codex integration path.

**These checks do not establish a general quality advantage or lower total tokens and time.** Extra context, state maintenance, and agents can add overhead. A shorter instruction file alone does not prove session savings, and completion claims still need evidence from your project.

The [comparison harness](evals/core/README.md) covers scope retention, debugging detours, context recovery, and small-task proportionality. Its mock runs test the scoring instrument. Separate behavioral scenario files describe cases that require model execution. No reviewed with-Forge versus no-Forge performance results for this revision are published here. See the [evaluation guide](evals/README.md) for criteria and reporting limits.

## Explore or contribute

| Resource | What it covers |
|---|---|
| [Skill instructions](SKILL.md) | The entrypoint the agent reads. |
| [Worked example](references/example-walkthrough.md) | A larger project using structured control and recovery. |
| [End-to-end assessment](docs/ASSESSMENT.md) | Problems addressed and what still needs measurement. |
| [Contributing](CONTRIBUTING.md) | Development setup, checks, and evidence standards. |
| [Release process](docs/RELEASING.md) | Versioning, publication, and artifact verification. |

Forge is available under the [MIT license](LICENSE).
