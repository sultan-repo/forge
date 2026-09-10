"""Optional Forge TaskCompleted guard.

Only applies when the completed task explicitly references a Forge Work Packet
ID. If no Work Packet is referenced, the hook stays out of the way.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
WORK_PACKET_PATTERN = re.compile(r"\b(WP-[A-Za-z0-9._-]+)\b")
ITEM_STATUSES = {"planned", "in_progress", "blocked", "done", "deferred", "cancelled", "superseded"}
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
    if "execution" in packet:
        if not isinstance(execution, dict):
            return {"phase": "invalid"}
        if "review_required" in execution and type(execution["review_required"]) is not bool:
            return {"phase": "invalid"}
    runtime_path = cwd / ".claude" / "forge" / "runtime" / "executions" / f"{packet_id}.json"
    if runtime_path.exists():
        # A malformed recovery record must not silently downgrade required review.
        return read_json_object(runtime_path) or {"phase": "invalid"}
    if isinstance(execution, dict):
        profile = execution.get("profile")
        phase = execution.get("phase")
        if phase is not None and not isinstance(phase, str):
            return {"phase": "invalid"}
        if execution.get("review_required") is True or profile == "dual-agent-local" or phase in {
            "ready_for_review",
            "reviewing",
            "fixing",
            "approved",
            "escalated",
            "reconcile_required",
        }:
            return execution

    return None


def approval_matches_project(cwd: Path, state: JsonObject, execution: JsonObject) -> bool:
    """Allow reconciliation metadata changes, but never approve changed source."""
    if execution.get("control_path", ".claude/project-control.json") != ".claude/project-control.json":
        return False
    reviewed = execution.get("reviewed_commit")
    if not isinstance(reviewed, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", reviewed):
        return False
    for key in ("baseline_revision", "plan_revision"):
        revision = execution.get(key)
        if type(revision) is not int or revision < 1 or type(state.get(key)) is not int or revision != state[key]:
            return False
    try:
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", reviewed, "HEAD"],
            cwd=cwd, capture_output=True, check=False, timeout=5,
        )
        if ancestor.returncode != 0:
            return False
        for command in (
            ["git", "diff", "--no-renames", "--name-only", "-z", reviewed, "--"],
            ["git", "diff", "--cached", "--no-renames", "--name-only", "-z", reviewed, "--"],
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        ):
            completed = subprocess.run(command, cwd=cwd, capture_output=True, check=False, timeout=5)
            if completed.returncode != 0:
                return False
            paths = completed.stdout.split(b"\0")
            if any(path and path != b".claude/project-control.json" and not path.startswith(b".claude/forge/runtime/") for path in paths):
                return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def main() -> int:
    """Hook entry point."""
    event = read_event()
    text = " ".join(str(event.get(key) or "") for key in ("task_subject", "task_description"))
    packet_ids = list(dict.fromkeys(WORK_PACKET_PATTERN.findall(text)))
    if not packet_ids:
        return 0

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or str(event.get("cwd") or "."))
    state_path = cwd / ".claude" / "project-control.json"
    validator_candidates = (
        cwd / ".claude" / "hooks" / "validate-project-control.py",
        cwd / ".claude" / "control" / "validate-project-control.py",
    )

    if not state_path.exists():
        return fail(f"Forge: task references {', '.join(packet_ids)}, but {state_path} is missing.")

    state_value = read_json_object(state_path)
    if state_value is None:
        return fail("Forge: cannot parse project control state as a JSON object.")

    validator = next((path for path in validator_candidates if path.exists()), None)
    if validator is not None:
        try:
            completed = subprocess.run(
                [sys.executable, str(validator), str(state_path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return fail(f"Forge: cannot validate control state before completion ({type(exc).__name__}).")
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            return fail(f"Forge: control state invalid before completion: {detail}")

    packet_map = state_value.get("work_packets", {})
    for packet_id in packet_ids:
        packet = packet_map.get(packet_id) if isinstance(packet_map, dict) else None
        if not isinstance(packet, dict):
            return fail(f"Forge: task references unknown Work Packet {packet_id}.")
        result = validate_completion(cwd, state_value, packet_id, packet)
        if result:
            return result
    return 0


def validate_completion(cwd: Path, state_value: JsonObject, packet_id: str, packet: JsonObject) -> int:
    """Check every referenced packet, including when no full validator is installed."""
    status = packet.get("status")
    if not isinstance(status, str) or status not in ITEM_STATUSES:
        return fail(f"Forge: {packet_id} has an invalid status; reconcile before completion.")
    if status in {"deferred", "cancelled", "superseded"}:
        return fail(f"Forge: {packet_id} is {status}; it cannot be reported as completed work.")
    for key in ("baseline_revision", "plan_revision"):
        revision = packet.get(key)
        if type(revision) is not int or revision < 1 or type(state_value.get(key)) is not int or revision != state_value[key]:
            return fail(f"Forge: {packet_id} has a stale or invalid {key}; reconcile before completion.")

    execution = review_state(cwd, packet_id, packet)
    if execution is not None:
        if execution.get("packet_id", packet_id) != packet_id:
            return fail(f"Forge: {packet_id} review belongs to another Work Packet.")
        if execution.get("phase") != "approved" or str(execution.get("review_status", "")) not in {
            "passed",
            "passed_with_deferred_findings",
        }:
            return fail(f"Forge: {packet_id} requires independent review before completion.")
        if not approval_matches_project(cwd, state_value, execution):
            return fail(f"Forge: {packet_id} review does not match the current source and plan; reconcile and review again.")

    if str(packet.get("acceptance_status", "")).lower() not in COMPLETED_STATUSES:
        return fail(f"Forge: {packet_id} acceptance_status is not complete.")
    if str(packet.get("validation_status", "")).lower() not in COMPLETED_STATUSES:
        return fail(f"Forge: {packet_id} validation_status is not complete.")
    if packet.get("reconciled") is not True:
        return fail(f"Forge: {packet_id} is not reconciled back to the project plan.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
