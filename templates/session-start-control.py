"""SessionStart hook that injects a concise Forge execution orientation.

Copy or adapt this file to a project hook location and configure it for the
session lifecycle events supported by the current environment. The hook is
non-blocking by design.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]


def read_event() -> JsonObject:
    """Read a hook event from stdin, returning an empty event on malformed input."""
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_control(root: Path, control: Path) -> str:
    """Return a concise validation status without blocking session startup."""
    validator_candidates = (
        root / ".claude" / "hooks" / "validate-project-control.py",
        root / ".claude" / "control" / "validate-project-control.py",
    )
    validator = next((path for path in validator_candidates if path.exists()), None)
    if validator is None:
        return "not checked"

    completed = subprocess.run(
        [sys.executable, str(validator), str(control)],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode == 0:
        return "valid"

    stderr_lines = completed.stderr.strip().splitlines()
    detail = stderr_lines[-1] if stderr_lines else "validator failed"
    return f"INVALID: {detail}"


def orientation_message(state: JsonObject, validation: str) -> str:
    """Build the concise context injected into the new session."""
    active_milestones = ", ".join(map(str, state.get("active_milestones", []))) or "none"
    active_packets = ", ".join(map(str, state.get("active_work_packets", []))) or "none"
    resume_queue = ", ".join(map(str, state.get("resume_queue", []))) or "none"

    packet_map = state.get("work_packets", {})
    blockers: list[str] = []
    if isinstance(packet_map, dict):
        blockers = [
            str(packet_id)
            for packet_id, packet in packet_map.items()
            if isinstance(packet, dict) and packet.get("status") == "blocked"
        ]

    gates = state.get("gates", {})
    if not isinstance(gates, dict):
        gates = {}
    plan_gate = gates.get("plan_consistency", {})
    convergence_gate = gates.get("convergence", {})
    if not isinstance(plan_gate, dict):
        plan_gate = {}
    if not isinstance(convergence_gate, dict):
        convergence_gate = {}

    return "\n".join(
        (
            "EXECUTION CONTROL ORIENTATION",
            f"Baseline: {state.get('baseline_id')} rev {state.get('baseline_revision')}",
            f"Plan revision: {state.get('plan_revision')}",
            f"Plan consistency: {plan_gate.get('status', 'unknown')}",
            f"Convergence: {convergence_gate.get('status', 'unknown')}",
            f"Active milestones: {active_milestones}",
            f"Active work packets: {active_packets}",
            f"Blocked packets: {', '.join(blockers) or 'none'}",
            f"Resume queue: {resume_queue}",
            f"Control validation: {validation}",
            "Before substantive implementation, load/reconcile the active packet and current plan state. Do not let local work replace the approved roadmap.",
        )
    )


def main() -> int:
    """Hook entry point."""
    event = read_event()
    root = Path(str(event.get("cwd") or "."))
    control = root / ".claude" / "project-control.json"
    if not control.exists():
        return 0

    try:
        raw_state = json.loads(control.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        message = (
            f"EXECUTION CONTROL WARNING: cannot parse {control}: {exc}. "
            "Reconcile control state before substantive implementation."
        )
    else:
        if not isinstance(raw_state, dict):
            message = (
                f"EXECUTION CONTROL WARNING: {control} must contain a JSON object. "
                "Reconcile control state before substantive implementation."
            )
        else:
            message = orientation_message(raw_state, validate_control(root, control))

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
