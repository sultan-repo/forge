"""Optional Forge TaskCompleted guard.

Only applies when the completed task explicitly references a Forge Work Packet
ID. If no Work Packet is referenced, the hook stays out of the way.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
WORK_PACKET_PATTERN = re.compile(r"\b(WP-[A-Za-z0-9._-]+)\b")
COMPLETED_STATUSES = {"passed", "satisfied", "accepted", "complete", "completed"}


def fail(message: str) -> int:
    """Write an actionable hook failure and return the blocking exit code."""
    print(message, file=sys.stderr)
    return 2


def read_event() -> JsonObject:
    """Read a lifecycle event, treating malformed input as an unrelated event."""
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_json_object(path: Path) -> JsonObject | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def review_state(cwd: Path, packet_id: str, packet: JsonObject) -> JsonObject | None:
    """Resolve review state without making dual-agent runtime state canonical project truth."""
    execution = packet.get("execution")
    if isinstance(execution, dict):
        profile = execution.get("profile")
        phase = execution.get("phase")
        if execution.get("review_required") is True or profile == "dual-agent-local" or phase in {
            "ready_for_review",
            "reviewing",
            "fixing",
            "approved",
            "escalated",
            "reconcile_required",
        }:
            return execution

    runtime_path = cwd / ".claude" / "forge" / "runtime" / "executions" / f"{packet_id}.json"
    runtime = read_json_object(runtime_path)
    if runtime is not None:
        return runtime
    return None


def main() -> int:
    """Hook entry point."""
    event = read_event()
    text = " ".join(str(event.get(key) or "") for key in ("task_subject", "task_description"))
    match = WORK_PACKET_PATTERN.search(text)
    if match is None:
        return 0

    packet_id = match.group(1)
    cwd = Path(str(event.get("cwd") or "."))
    state_path = cwd / ".claude" / "project-control.json"
    validator_candidates = (
        cwd / ".claude" / "hooks" / "validate-project-control.py",
        cwd / ".claude" / "control" / "validate-project-control.py",
    )

    if not state_path.exists():
        return fail(f"Forge: task references {packet_id}, but {state_path} is missing.")

    state_value = read_json_object(state_path)
    if state_value is None:
        return fail("Forge: cannot parse project control state as a JSON object.")

    packet_map = state_value.get("work_packets", {})
    packet = packet_map.get(packet_id) if isinstance(packet_map, dict) else None
    if not isinstance(packet, dict):
        return fail(f"Forge: task references unknown Work Packet {packet_id}.")

    validator = next((path for path in validator_candidates if path.exists()), None)
    if validator is not None:
        completed = subprocess.run(
            [sys.executable, str(validator), str(state_path)],
            capture_output=True,
            check=False,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return fail(f"Forge: control state invalid before completing {packet_id}: {detail}")

    execution = review_state(cwd, packet_id, packet)
    if execution is not None:
        if execution.get("phase") != "approved" or str(execution.get("review_status", "")) not in {
            "passed",
            "passed_with_deferred_findings",
        }:
            return fail(f"Forge: {packet_id} requires independent review before completion.")
        reviewed_commit = execution.get("reviewed_commit") or execution.get("implementation_commit")
        if not isinstance(reviewed_commit, str) or len(reviewed_commit) < 7:
            return fail(f"Forge: {packet_id} has no valid reviewed commit recorded.")

    if str(packet.get("acceptance_status", "")).lower() not in COMPLETED_STATUSES:
        return fail(f"Forge: {packet_id} acceptance_status is not complete.")
    if str(packet.get("validation_status", "")).lower() not in COMPLETED_STATUSES:
        return fail(f"Forge: {packet_id} validation_status is not complete.")
    if packet.get("reconciled") is not True:
        return fail(f"Forge: {packet_id} is not reconciled back to the project plan.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
