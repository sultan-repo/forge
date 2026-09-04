"""Validate generic Forge control-state invariants.

Usage:
    python3 validate-project-control.py [.claude/project-control.json]

This validates accounting and structure, not business correctness or requirement truth.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

Requirement = dict[str, Any]
ControlState = dict[str, Any]

REQ_STATUSES = {"planned", "in_progress", "satisfied", "deferred", "rejected", "superseded"}
ITEM_STATUSES = {"planned", "in_progress", "blocked", "done", "deferred", "cancelled", "superseded"}
REQ_DISPOSITIONS = {"deferred", "rejected", "superseded"}
ITEM_DISPOSITIONS = {"deferred", "cancelled", "superseded"}
GATE_STATUSES = {"pending", "passed", "passed_with_explicit_gaps", "failed", "invalidated"}
ACTIVE_ITEM_STATUSES = {"in_progress", "blocked"}


def add_disposition_errors(obj: Requirement, label: str, errors: list[str]) -> None:
    """Validate the audit record for terminal scope disposition."""
    disposition = obj.get("disposition")
    if not isinstance(disposition, dict):
        errors.append(f"{label}: terminal scope disposition requires disposition object")
        return

    for key in ("reason", "plan_delta", "authority_level"):
        if not disposition.get(key):
            errors.append(f"{label}: disposition.{key} is required")

    if disposition.get("authority_level") == "explicit_approval" and not disposition.get("approval_ref"):
        errors.append(f"{label}: explicit approval disposition requires disposition.approval_ref")


def load_state(path: Path) -> ControlState:
    """Read the project control state or exit with a deterministic error."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"CONTROL INVALID: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if not isinstance(raw, dict):
        print(f"CONTROL INVALID: {path} must contain a JSON object", file=sys.stderr)
        raise SystemExit(2)
    return raw


def validate_state(state: ControlState) -> tuple[list[str], list[str]]:
    """Return validation errors and warnings for a Forge control state."""
    errors: list[str] = []
    warnings: list[str] = []

    if state.get("version") != 3:
        errors.append("version must be 3")

    for key in ("baseline_revision", "plan_revision"):
        value = state.get(key)
        if not isinstance(value, int) or value < 1:
            errors.append(f"{key} must be integer >= 1")

    for key in (
        "active_milestones",
        "active_work_packets",
        "resume_queue",
        "plan_deltas",
        "archived_plan_deltas",
    ):
        if not isinstance(state.get(key), list):
            errors.append(f"{key} must be an array")

    for key in ("requirements", "milestones", "work_packets", "gates"):
        if not isinstance(state.get(key), dict):
            errors.append(f"{key} must be an object")

    requirements = state.get("requirements", {})
    milestones = state.get("milestones", {})
    work_packets = state.get("work_packets", {})

    if not isinstance(requirements, dict) or not isinstance(milestones, dict) or not isinstance(work_packets, dict):
        return errors, warnings

    for requirement_id, requirement_value in requirements.items():
        if not isinstance(requirement_value, dict):
            errors.append(f"requirement {requirement_id}: must be an object")
            continue
        status = requirement_value.get("status")
        if status not in REQ_STATUSES:
            errors.append(f"requirement {requirement_id}: invalid status {status!r}")
        if status in REQ_DISPOSITIONS:
            add_disposition_errors(requirement_value, f"requirement {requirement_id}", errors)

        milestone = requirement_value.get("milestone")
        if milestone is not None and milestone not in milestones:
            errors.append(f"requirement {requirement_id}: unknown milestone {milestone}")

        packet_ids = requirement_value.get("work_packets", [])
        if isinstance(packet_ids, list):
            for packet_id in packet_ids:
                if packet_id not in work_packets:
                    errors.append(f"requirement {requirement_id}: unknown work packet {packet_id}")
        else:
            errors.append(f"requirement {requirement_id}: work_packets must be an array")
            packet_ids = []

        if status in {"planned", "in_progress"} and not milestone and not packet_ids:
            warnings.append(
                f"requirement {requirement_id}: active/planned requirement has no milestone/work-packet mapping"
            )

    for milestone_id, milestone_value in milestones.items():
        if not isinstance(milestone_value, dict):
            errors.append(f"milestone {milestone_id}: must be an object")
            continue
        status = milestone_value.get("status")
        if status not in ITEM_STATUSES:
            errors.append(f"milestone {milestone_id}: invalid status {status!r}")
        if status in ITEM_DISPOSITIONS:
            add_disposition_errors(milestone_value, f"milestone {milestone_id}", errors)
        requirement_ids = milestone_value.get("requirements", [])
        if isinstance(requirement_ids, list):
            for requirement_id in requirement_ids:
                if requirement_id not in requirements:
                    errors.append(f"milestone {milestone_id}: unknown requirement {requirement_id}")
        else:
            errors.append(f"milestone {milestone_id}: requirements must be an array")

    current_baseline = state.get("baseline_revision", 1)
    current_plan = state.get("plan_revision", 1)

    for packet_id, packet_value in work_packets.items():
        if not isinstance(packet_value, dict):
            errors.append(f"work packet {packet_id}: must be an object")
            continue
        status = packet_value.get("status")
        if status not in ITEM_STATUSES:
            errors.append(f"work packet {packet_id}: invalid status {status!r}")
        if status in ITEM_DISPOSITIONS:
            add_disposition_errors(packet_value, f"work packet {packet_id}", errors)

        parent = packet_value.get("parent")
        if parent not in milestones and parent not in work_packets:
            errors.append(f"work packet {packet_id}: unknown parent {parent!r}")

        for requirement_id in packet_value.get("requirements", []):
            if requirement_id not in requirements:
                errors.append(f"work packet {packet_id}: unknown requirement {requirement_id}")

        for dependency in packet_value.get("dependencies", []):
            if dependency not in work_packets and dependency not in milestones:
                errors.append(f"work packet {packet_id}: unknown dependency {dependency}")

        return_to = packet_value.get("return_to")
        if return_to is not None and return_to not in work_packets and return_to not in milestones:
            errors.append(f"work packet {packet_id}: unknown return_to {return_to!r}")

        baseline_revision = packet_value.get("baseline_revision")
        plan_revision = packet_value.get("plan_revision")
        if not isinstance(baseline_revision, int) or baseline_revision < 1:
            errors.append(f"work packet {packet_id}: baseline_revision must be >=1")
        if not isinstance(plan_revision, int) or plan_revision < 1:
            errors.append(f"work packet {packet_id}: plan_revision must be >=1")

        if (
            isinstance(baseline_revision, int)
            and isinstance(current_baseline, int)
            and baseline_revision < current_baseline
            and status in {"planned", "in_progress", "blocked"}
        ):
            warnings.append(
                f"work packet {packet_id}: stale baseline revision {baseline_revision} < current {current_baseline}"
            )
        if (
            isinstance(plan_revision, int)
            and isinstance(current_plan, int)
            and plan_revision < current_plan
            and status in {"planned", "in_progress", "blocked"}
        ):
            warnings.append(f"work packet {packet_id}: stale plan revision {plan_revision} < current {current_plan}")

    for milestone_id in state.get("active_milestones", []):
        if milestone_id not in milestones:
            errors.append(f"active milestone {milestone_id}: not found")
        elif milestones[milestone_id].get("status") not in ACTIVE_ITEM_STATUSES:
            warnings.append(f"active milestone {milestone_id}: status is {milestones[milestone_id].get('status')}")

    for packet_id in state.get("active_work_packets", []):
        if packet_id not in work_packets:
            errors.append(f"active work packet {packet_id}: not found")
        elif work_packets[packet_id].get("status") not in ACTIVE_ITEM_STATUSES:
            warnings.append(f"active work packet {packet_id}: status is {work_packets[packet_id].get('status')}")

    for target in state.get("resume_queue", []):
        if target not in work_packets and target not in milestones:
            errors.append(f"resume_queue: unknown target {target}")

    seen_delta_ids: set[str] = set()
    last_to = 0
    for delta in state.get("plan_deltas", []):
        if not isinstance(delta, dict):
            errors.append("plan delta must be an object")
            continue
        delta_id = delta.get("id")
        if not delta_id:
            errors.append("plan delta missing id")
        elif str(delta_id) in seen_delta_ids:
            errors.append(f"duplicate active plan delta id {delta_id}")
        else:
            seen_delta_ids.add(str(delta_id))

        from_revision = delta.get("from_plan_revision")
        to_revision = delta.get("to_plan_revision")
        if (
            not isinstance(from_revision, int)
            or not isinstance(to_revision, int)
            or to_revision != from_revision + 1
        ):
            errors.append(f"plan delta {delta_id or '?'}: revisions must be consecutive integers")
        if isinstance(to_revision, int):
            last_to = max(last_to, to_revision)

    for delta in state.get("archived_plan_deltas", []):
        delta_id = delta.get("id") if isinstance(delta, dict) else delta
        if delta_id is not None and str(delta_id) in seen_delta_ids:
            errors.append(f"plan delta {delta_id}: appears in both active and archived lists")
        if delta_id:
            seen_delta_ids.add(str(delta_id))

    if isinstance(current_plan, int) and last_to > current_plan:
        errors.append("plan_deltas reference a revision newer than current plan_revision")

    canonicalized = state.get("canonicalized_through_plan_revision")
    if canonicalized is not None:
        if not isinstance(canonicalized, int) or canonicalized < 1:
            errors.append("canonicalized_through_plan_revision must be >=1")
        elif isinstance(current_plan, int) and canonicalized > current_plan:
            errors.append("canonicalized_through_plan_revision cannot exceed plan_revision")

    gates = state.get("gates", {})
    if isinstance(gates, dict):
        for name in ("plan_consistency", "convergence"):
            gate = gates.get(name)
            if not isinstance(gate, dict):
                errors.append(f"gates.{name} must be an object")
                continue
            if gate.get("status") not in GATE_STATUSES:
                errors.append(f"gates.{name}: invalid status {gate.get('status')!r}")
            for revision_key in ("baseline_revision", "plan_revision"):
                revision = gate.get(revision_key)
                if not isinstance(revision, int) or revision < 1:
                    errors.append(f"gates.{name}.{revision_key} must be >=1")

        plan_consistency = gates.get("plan_consistency", {})
        if state.get("active_work_packets") and isinstance(plan_consistency, dict):
            if plan_consistency.get("status") not in {"passed", "passed_with_explicit_gaps"}:
                warnings.append("active work exists but current plan_consistency gate is not passed")
            if (
                plan_consistency.get("baseline_revision") != state.get("baseline_revision")
                or plan_consistency.get("plan_revision") != state.get("plan_revision")
            ):
                warnings.append(
                    "plan_consistency gate revisions differ from current baseline/plan; targeted re-analysis may be required"
                )

    return errors, warnings


def main(argv: list[str]) -> int:
    """CLI entry point."""
    path = Path(argv[1] if len(argv) > 1 else ".claude/project-control.json")
    state = load_state(path)
    errors, warnings = validate_state(state)

    for warning in warnings:
        print("CONTROL WARNING:", warning, file=sys.stderr)
    if errors:
        for error in errors:
            print("CONTROL ERROR:", error, file=sys.stderr)
        print(f"CONTROL INVALID: {len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
        return 2

    print(f"CONTROL VALID: {path} ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
