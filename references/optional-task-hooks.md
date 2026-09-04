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

The packaged `templates/session-start-control.py` is a starting point.

Fallback when unavailable: explicitly reload the same durable state before substantive work.

## Task/work-item completion guard

Use only if the current environment exposes a native task/work-item lifecycle **and the project actually uses it**.

A completion guard may deterministically check:
- referenced Forge Work Packet exists
- control state validates
- required acceptance/validation fields are dispositioned
- reconciliation/return state is coherent

Do not make Forge correctness depend on a task system being present.

The packaged `templates/task-completed-control.py` is intentionally conservative: it acts only when the task subject/description explicitly references a Forge Work Packet.

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
