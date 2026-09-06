# Optional Lifecycle Hooks for Forge Control

Hooks are project-specific enforcement. Detect lifecycle-hook capabilities at runtime and never assume they exist because of a model name/version.

## Session-start reorientation

When the environment supports a session-start/resume lifecycle hook and Control Mode is justified, this is Forge's preferred deterministic context-control hook.

Inject only a concise orientation summary:
- baseline ID/revision
- plan revision
- active milestones/packets
- blockers/detours
- gate state
- resume queue
- control-validator status

The packaged [session-start hook](../templates/session-start-control.py) is a starting point. It reports invalid or unchecked control state in the orientation but does not block startup; the controller must act on that warning.

Fallback when unavailable: explicitly reload the same durable state before substantive work.

## Task/work-item completion guard

Use only if the current environment exposes a native task/work-item lifecycle **and the project actually uses it**.

A completion guard may deterministically check:
- referenced Forge Work Packet exists
- control state validates
- required acceptance/validation fields are dispositioned
- reconciliation/return state is coherent

Do not make Forge correctness depend on a task system being present.

The packaged [task-completion hook](../templates/task-completed-control.py) is intentionally conservative: it acts only when the task subject/description explicitly references a Forge Work Packet using a `WP-...` identifier. It checks recorded acceptance, validation, reconciliation, and any required runner review; it does not run project tests or prove those records are true.

## Installing the examples

After reviewing the helpers, copy only the applicable hook scripts and [control validator](../templates/validate-project-control.py) into the project's `.claude/hooks/` directory. The examples read `.claude/project-control.json`; adapt their paths if your project uses another location.

Merge the applicable entries from [the settings example](../templates/settings-control-hooks.example.json) into `.claude/settings.json`, preserving existing settings and hooks. Omit `TaskCompleted` when the project does not use the native task lifecycle. Without the validator beside the hooks, full control-state validation is skipped.

## Stop/completion guards

A generic stop event may fire for ordinary pauses, questions, or intermediate turns. Do not universally block every stop merely because project work remains.

Only add a stop/completion guard when it can reliably distinguish a genuine completion/closure claim and the project has deterministic closure criteria. Prefer project tests, CI, schemas, and explicit Convergence checks for product correctness.

## Hook design rules

- capability detection over model/version detection
- fast and deterministic
- actionable failure messages
- no destructive side effects
- inspect project state, not narrative claims
- merge project settings intentionally
- do not overwrite existing hooks
- graceful fallback when hooks are unavailable or policy-disabled
