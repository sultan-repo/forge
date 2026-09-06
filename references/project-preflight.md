# Project preflight

Forge project preflight prevents a substantial project from discovering too late that its intended Claude/Codex/authentication path was never actually ready.

## When it applies

Planned, High-Risk, and multi-milestone work should complete preflight before significant implementation. Quick reversible tasks may skip persistent preflight unless they depend on an external agent.

## First-use questions

If `.claude/forge/project-preferences.json` is missing, ask only the choices that change execution:

1. **Execution mode**
   - `adaptive` (recommended): Claude normally; Codex according to review policy
   - `claude_only`: never require Codex
   - `dual_agent`: Planned and High-Risk implementation requires Claude + Codex

2. **Claude model**
   - confirm the current Claude Code model selection is acceptable
   - Forge does not maintain a hardcoded model catalog
   - if the user wants a different model, change/select it in Claude Code before completing preflight

3. **Codex review policy** when adaptive
   - `high_risk` (recommended)
   - `substantial`
   - `explicit`
   - `never`

4. **Local Claude authentication intent**
   - `subscription` (recommended for subscription users)
   - `api`
   - `inherit`

5. **Live readiness**
   - recommend requiring a small live no-edit probe before substantial implementation

Keep durable project execution/review choices in `.claude/forge/project-preferences.json`. Authentication choice and live evidence are machine-local under `.claude/forge/runtime/` and should not be committed.

The bundled example is `templates/project-preferences.example.json`; the schema is `templates/project-preferences.schema.json`.

## Execution routing

| Project setting | Route |
| --- | --- |
| `claude_only` | Claude only |
| `dual_agent` | Claude + Codex for Planned/High-Risk implementation |
| `adaptive` + `substantial` | Codex review for Planned/High-Risk implementation |
| `adaptive` + `high_risk` | Codex review for High-Risk implementation only |
| `adaptive` + `explicit` | Codex only when the user explicitly requests it |
| `adaptive` + `never` | Claude only |

Codex review uses the provider-selected model, read-only execution, and Forge-requested `high` reasoning. Do not silently downgrade a route that the project requires.

## Readiness states

- `READY`: the requested route is verified.
- `READY_WITH_WARNINGS`: local checks are usable, but a configured live probe or another non-fatal condition still needs attention. When live verification is required, substantial implementation waits.
- `BLOCKED`: resolve the blocker before substantial implementation.

## Local shell helper

```bash
scripts/forge preflight --configure
scripts/forge preflight --live
scripts/forge preflight --json
```

`--configure` is interactive. When Claude Code is driving Forge, it may ask the same questions itself and write the preferences instead of requiring terminal interaction.

`--live` performs minimal no-edit provider probes. It checks:

- Claude CLI availability
- configured Claude authentication intent
- API-key override conflicts without printing secret values
- a real Claude provider request
- Codex installation/sign-in/required isolated-review flags when the project may use Codex
- a real Codex read-only ephemeral request with `model_reasoning_effort="high"`

For `subscription`, an active `ANTHROPIC_API_KEY` is `BLOCKED` because it can override subscription authentication in non-interactive Claude Code. For `api`, a missing API key is `BLOCKED`. `inherit` reports an active API override as a warning rather than guessing which billing mode the user intended.

## Reusing live readiness

A prior `READY` live report may be reused only while these remain unchanged:

- durable and local preference content
- Claude CLI version
- Codex CLI version when Codex may be used
- presence/absence of the Anthropic API-key override

Otherwise refresh with `scripts/forge preflight --live`.

The live report may record model names only when the CLI actually reports them. Never infer missing model identity.

## Continuing a project

On `/forge continue`:

1. restore project state and prior readiness evidence
2. run a cheap local preflight check when Planned/High-Risk work will continue
3. reuse prior live verification only when the environment fingerprint still matches
4. rerun live verification when it does not
5. stop rather than silently changing the project's execution/review route

User-facing output should normally be a short readiness summary. Show detailed environment evidence only when requested or when a blocker needs explanation.
