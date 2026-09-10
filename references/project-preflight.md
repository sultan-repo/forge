# Optional external execution preflight

Use preflight when the task will launch an external Claude/Codex CLI or when diagnosing that route. Work in the current agent session, including planned work and resume, does not need another login check, preference file, or model request.

## Start with the requested operation

```bash
scripts/forge preflight                         # local checks; planned task by default
scripts/forge preflight --task high_risk        # include configured high-risk review
scripts/forge preflight --review                # explicitly requested Codex review
scripts/forge preflight --json                  # machine-readable report
```

These commands check local CLI/authentication prerequisites without a model request. Missing preference files use adaptive execution, explicit-only Codex review, inherited authentication, and no required live probe. They do not create preference files or initiate a setup interview. Preflight only checks readiness; it does not dispatch implementation or silently downgrade a required reviewer.

| Saved review policy | Codex checked when |
| --- | --- |
| `never` | explicitly requested with `--review` |
| `explicit` | explicitly requested with `--review` |
| `high_risk` | `--task high_risk` or `--review` |
| `substantial` | planned/high-risk tasks or `--review` |

`claude_only` requires saved policy `never`; `dual_agent` requires `substantial`. An explicit `forge run` selects the dual-agent runner and checks saved preferences with `--review` before dispatch. Native independent review is also possible without that runner.

## Save preferences only when useful

`preflight --configure` is an optional interactive helper. Preserve choices and authorizations already provided by the user. Ask only about a missing choice that affects the requested external operation; do not repeat a questionnaire to continue a task.

Durable choices use `.claude/forge/project-preferences.json` ([example](../templates/project-preferences.example.json), [schema](../templates/project-preferences.schema.json)). Authentication intent is machine-local in `.claude/forge/runtime/local-preferences.json`. The helper excludes runtime files from Git locally and does not store credential values.

- `subscription`: block an active `ANTHROPIC_API_KEY` override. Resolve the environment explicitly; never fall back to API billing.
- `api`: require an API key.
- `inherit`: preserve the shell/CLI choice; warn if an API override is active.

Forge leaves model selection to the CLIs; it does not maintain a changing model catalog.

## Live probes are opt-in

`preflight --live` makes model requests and uses subscription allowance or API billing according to the selected authentication. Use it only when requested or authorized under an explicit saved requirement. Keep the same `--task`/`--review` options as the intended operation. A configured `live_preflight_required: true` blocks external readiness until successful matching evidence exists; ordinary preflight never starts a probe automatically.

The Claude probe disables built-in tools, skills, MCP configuration, hooks, and session persistence. Codex runs read-only and ephemeral with isolated configuration and high reasoning. A zero exit code alone is insufficient: Claude must return a valid successful JSON result with the expected answer; Codex must emit the expected answer and a completed turn without an error. Unsupported flags or provider failures remain failures.

## Read the result precisely

- `READY` (exit 0): local prerequisites pass, plus any explicitly required live evidence.
- `READY_WITH_WARNINGS` (exit 1): prerequisites pass with a non-blocking warning, such as inherited API authentication.
- `BLOCKED` (exit 2): the requested external route has an unresolved prerequisite or policy requirement. This does not block unrelated work in the current session.

Report version 2 records operation, preference sources, observed versions/models, and `live_checked_at`. A cached successful probe is historical evidence, not a guarantee that a future provider request will work. Reuse it only with matching operation, preferences, CLI versions, and API-override presence; failed local authentication invalidates it. Ordinary rechecks preserve the original probe time and reported model. Old report versions are not accepted as live proof because they used weaker validation. There is no timer that automatically spends allowance on another probe.
