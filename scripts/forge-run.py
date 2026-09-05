#!/usr/bin/env python3
"""Optional Forge external-agent runner.

This runner is intentionally separate from the Forge methodology. It coordinates
one implementation owner and one independent reviewer around immutable Git
checkpoints while leaving requirements, reconciliation, and authority rules to
Forge's canonical control model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from adapters import ClaudeCodeImplementer, CodexCLIReviewer  # noqa: E402
from adapters.base import AdapterError  # noqa: E402

CONTROL_DEFAULT = Path(".claude/project-control.json")
PROFILE_DEFAULT = Path(".claude/forge/execution-profile.json")
RUNTIME_DIR = Path(".claude/forge/runtime")
REVIEW_SCHEMA = PACKAGE_ROOT / "templates" / "review-result.schema.json"
PROFILE_TEMPLATE = PACKAGE_ROOT / "templates" / "execution-profile.example.json"
CONTROL_VALIDATOR = PACKAGE_ROOT / "templates" / "validate-project-control.py"

PHASES = {
    "pending",
    "implementing",
    "ready_for_review",
    "reviewing",
    "fixing",
    "approved",
    "escalated",
}
VERDICTS = {"PASS", "CHANGES_REQUIRED", "ESCALATE"}


class ForgeRunnerError(RuntimeError):
    """Safe user-facing runner failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_local(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def git(cwd: Path, *args: str, check: bool = True) -> str:
    completed = run_local(["git", *args], cwd)
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ForgeRunnerError(f"Git check failed: {detail[:400]}")
    return completed.stdout.strip()


def repo_root(start: Path) -> Path:
    completed = run_local(["git", "rev-parse", "--show-toplevel"], start)
    if completed.returncode != 0:
        raise ForgeRunnerError("Run Forge from inside the project Git repository.")
    return Path(completed.stdout.strip()).resolve()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ForgeRunnerError(f"Required file is missing: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ForgeRunnerError(f"Invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ForgeRunnerError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_history(root: Path, event: dict[str, Any], enabled: bool = True) -> None:
    if not enabled:
        return
    path = root / RUNTIME_DIR / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": utc_now(), **event}, sort_keys=True) + "\n")


def ensure_runtime_excluded(root: Path) -> None:
    exclude = root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    marker = ".claude/forge/runtime/"
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if marker not in current.splitlines():
        with exclude.open("a", encoding="utf-8") as handle:
            if current and not current.endswith("\n"):
                handle.write("\n")
            handle.write(marker + "\n")


def load_profile(root: Path) -> dict[str, Any]:
    project_profile = root / PROFILE_DEFAULT
    profile = read_json(project_profile if project_profile.exists() else PROFILE_TEMPLATE)
    if profile.get("version") != 1:
        raise ForgeRunnerError("Unsupported Forge execution-profile version.")
    roles = profile.get("roles", {})
    if roles.get("implementer", {}).get("adapter") != "claude-code-cli":
        raise ForgeRunnerError("This runner currently supports claude-code-cli as implementer.")
    if roles.get("reviewer", {}).get("adapter") != "codex-cli":
        raise ForgeRunnerError("This runner currently supports codex-cli as reviewer.")
    max_cycles = profile.get("review", {}).get("max_cycles", 3)
    if not isinstance(max_cycles, int) or max_cycles < 1 or max_cycles > 10:
        raise ForgeRunnerError("review.max_cycles must be between 1 and 10.")
    return profile


def validate_control(root: Path, control_path: Path) -> None:
    completed = run_local([sys.executable, str(CONTROL_VALIDATOR), str(control_path)], root)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ForgeRunnerError(f"Forge control state is invalid. {detail[:700]}")


def choose_packet(state: dict[str, Any], packet_id: str | None) -> str:
    packets = state.get("work_packets", {})
    if packet_id:
        if packet_id not in packets:
            raise ForgeRunnerError(f"Unknown Work Packet: {packet_id}")
        return packet_id
    active = state.get("active_work_packets", [])
    if len(active) != 1:
        raise ForgeRunnerError("Specify a Work Packet when there is not exactly one active packet.")
    return str(active[0])


def execution_for(state: dict[str, Any], packet_id: str) -> dict[str, Any]:
    packet = state["work_packets"][packet_id]
    execution = packet.setdefault(
        "execution",
        {"phase": "pending", "cycle": 0, "review_status": "not_started"},
    )
    if execution.get("phase") not in PHASES:
        raise ForgeRunnerError(f"{packet_id} has an invalid execution phase.")
    return execution


def save_control(root: Path, control_path: Path, state: dict[str, Any]) -> None:
    atomic_json(control_path, state)
    validate_control(root, control_path)


def commit_if_changed(root: Path, message: str) -> str:
    status = git(root, "status", "--porcelain")
    if status:
        git(root, "add", "-A")
        git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def changed_files(root: Path, base: str, head: str) -> list[str]:
    output = git(root, "diff", "--name-only", f"{base}..{head}")
    return [line for line in output.splitlines() if line.strip()]


def write_runtime_json(root: Path, relative: Path, value: dict[str, Any]) -> Path:
    path = root / RUNTIME_DIR / relative
    atomic_json(path, value)
    return path


def review_result_path(root: Path, packet_id: str, cycle: int) -> Path:
    return root / RUNTIME_DIR / "reviews" / f"{packet_id}-review-{cycle:02d}.json"


def latest_review(root: Path, packet_id: str, cycle: int) -> dict[str, Any]:
    return read_json(review_result_path(root, packet_id, cycle))


def implementation_prompt(packet_id: str, state: dict[str, Any], findings: list[dict[str, Any]] | None) -> str:
    packet = state["work_packets"][packet_id]
    prompt = f"""
You are the IMPLEMENTER for Forge Work Packet {packet_id}.
Work only inside the current project's approved scope. Read the project's canonical requirements,
architecture, plan, tests, and .claude/project-control.json before editing.

Packet snapshot:
{json.dumps(packet, indent=2)}

Rules:
- Make the smallest coherent implementation that satisfies the Work Packet.
- Run relevant tests/checks and fix failures caused by your work.
- Do not silently expand scope.
- Do not mark the packet approved, reviewed, reconciled, or done.
- Do not create Git commits; the Forge runner owns review checkpoints.
- Do not modify Work Packet execution.phase/review_status/cycle fields.
- Keep your final response concise; internal orchestration details are not user-facing.
"""
    if findings:
        prompt += f"""
This is a correction cycle. Independently verify and address the applicable review findings below.
Do not blindly accept a finding if primary evidence disproves it; preserve evidence for any genuine dispute.

Review findings:
{json.dumps(findings, indent=2)}
"""
    return prompt.strip()


def reviewer_prompt(packet_id: str, state: dict[str, Any], packet_base: str, reviewed_commit: str, cycle: int) -> str:
    packet = state["work_packets"][packet_id]
    return f"""
You are the independent REVIEWER for Forge Work Packet {packet_id}.

Review the actual repository at commit {reviewed_commit} against the approved project intent.
The packet began at {packet_base}. Inspect the complete diff {packet_base}..{reviewed_commit},
the current source, tests, configuration, requirements, architecture, and relevant project evidence.

Packet snapshot:
{json.dumps(packet, indent=2)}

Required output is constrained by the provided JSON Schema.
Use exactly:
- packet_id: {packet_id}
- baseline_revision: {state["baseline_revision"]}
- plan_revision: {state["plan_revision"]}
- base_commit: {packet_base}
- reviewed_commit: {reviewed_commit}
- cycle: {cycle}

Review order:
1. Specification compliance and scope.
2. Correctness and regressions.
3. Security/privacy/reliability/performance where relevant.
4. Test and failure-path adequacy.

Independence:
- Treat implementer summaries as claims, not evidence.
- Do not edit production files. Your sandbox is read-only.
- Ignore stylistic preference and low-value lint commentary unless it has credible engineering impact.
- Do not expand the current Work Packet merely because an adjacent improvement is attractive.
- Classify severity separately from scope relevance.
- PASS only when no unresolved current_required/current_blocking Critical or High issue remains and
  the implementation is sufficiently supported by evidence.
""".strip()


def validate_review(payload: dict[str, Any], *, packet_id: str, baseline_revision: int, plan_revision: int, packet_base: str, reviewed_commit: str, cycle: int) -> None:
    expected = {
        "packet_id": packet_id,
        "baseline_revision": baseline_revision,
        "plan_revision": plan_revision,
        "base_commit": packet_base,
        "reviewed_commit": reviewed_commit,
        "cycle": cycle,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ForgeRunnerError(f"Reviewer returned stale or mismatched {key}.")
    if payload.get("verdict") not in VERDICTS:
        raise ForgeRunnerError("Reviewer returned an invalid verdict.")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ForgeRunnerError("Reviewer findings are invalid.")
    if payload["verdict"] == "PASS":
        blocking = [
            finding
            for finding in findings
            if isinstance(finding, dict)
            and finding.get("severity") in {"Critical", "High"}
            and finding.get("scope_relevance") in {"current_required", "current_blocking"}
        ]
        if blocking:
            raise ForgeRunnerError("Reviewer returned PASS with unresolved blocking findings.")


def doctor(root: Path, control_path: Path, verbose: bool) -> int:
    checks: list[tuple[bool, str]] = [(True, "Git repository ready")]
    implementer = ClaudeCodeImplementer()
    reviewer = CodexCLIReviewer()
    checks.append(implementer.doctor(root))
    checks.append(reviewer.doctor(root))
    if control_path.exists():
        try:
            validate_control(root, control_path)
            checks.append((True, "Forge project state valid"))
        except ForgeRunnerError as exc:
            checks.append((False, str(exc)))
    bad = [message for ok, message in checks if not ok]
    if bad:
        print("Forge is not ready.")
        for message in bad:
            print(f"- {message}")
        return 2
    print("Everything is ready.")
    if verbose:
        for _, message in checks:
            print(f"- {message}")
    return 0


def status(root: Path, control_path: Path, packet_id: str | None, verbose: bool) -> int:
    state = read_json(control_path)
    packet_id = choose_packet(state, packet_id)
    execution = execution_for(state, packet_id)
    phase = execution.get("phase", "pending")
    friendly = {
        "pending": "ready to start",
        "implementing": "being implemented",
        "ready_for_review": "ready for review",
        "reviewing": "being independently reviewed",
        "fixing": "being corrected after review",
        "approved": "review passed",
        "escalated": "needs your decision",
    }[phase]
    print(f"{packet_id} is {friendly}.")
    if verbose:
        print(json.dumps(execution, indent=2))
    return 0


def run_packet(root: Path, control_path: Path, packet_id: str | None, profile: dict[str, Any], verbose: bool) -> int:
    if git(root, "status", "--porcelain"):
        raise ForgeRunnerError("Your project has uncommitted changes. Commit or stash them before Forge runs.")

    state = read_json(control_path)
    validate_control(root, control_path)
    packet_id = choose_packet(state, packet_id)
    execution = execution_for(state, packet_id)
    if execution.get("phase") == "approved":
        print("Review already passed. Forge reconciliation is next.")
        return 0
    if execution.get("phase") == "escalated":
        print("This Work Packet needs your decision before it can continue.")
        return 2

    ensure_runtime_excluded(root)
    implementer = ClaudeCodeImplementer()
    reviewer = CodexCLIReviewer()
    ok, message = implementer.doctor(root)
    if not ok:
        raise ForgeRunnerError(message)
    ok, message = reviewer.doctor(root)
    if not ok:
        raise ForgeRunnerError(message)

    max_cycles = int(profile["review"]["max_cycles"])
    history_enabled = bool(profile.get("history", {}).get("enabled", True))

    if not execution.get("packet_base_commit"):
        execution["packet_base_commit"] = git(root, "rev-parse", "HEAD")
    packet_base = str(execution["packet_base_commit"])

    cycle = int(execution.get("cycle", 0))
    phase = str(execution.get("phase", "pending"))

    while cycle < max_cycles:
        findings: list[dict[str, Any]] | None = None
        if phase == "fixing":
            if cycle < 1:
                raise ForgeRunnerError("Cannot resume fix cycle without a previous review.")
            previous = latest_review(root, packet_id, cycle)
            raw_findings = previous.get("findings", [])
            findings = [item for item in raw_findings if isinstance(item, dict)]

        if phase not in {"ready_for_review", "reviewing"}:
            cycle += 1
            execution["cycle"] = cycle
            execution["phase"] = "fixing" if findings else "implementing"
            execution["review_status"] = "pending"
            save_control(root, control_path, state)
            append_history(root, {"packet": packet_id, "cycle": cycle, "phase": execution["phase"], "agent": implementer.name}, history_enabled)
            if verbose:
                print(f"Implementation cycle {cycle} started.")
            result = implementer.implement(implementation_prompt(packet_id, state, findings), root)
            append_history(root, {"packet": packet_id, "cycle": cycle, "phase": "implementation_finished", "agent": implementer.name, "duration_s": round(result.duration_s, 3)}, history_enabled)

            if findings:
                changed_now = [
                    line for line in git(root, "diff", "--name-only").splitlines()
                    if line.strip() and line.strip() != str(control_path.relative_to(root))
                ]
                if not changed_now:
                    execution["phase"] = "escalated"
                    execution["review_status"] = "unresolved"
                    save_control(root, control_path, state)
                    commit_if_changed(root, f"Forge {packet_id} record unresolved review")
                    print("The review issue could not be resolved automatically and needs your decision.")
                    return 2

            reviewed_commit = commit_if_changed(root, f"Forge {packet_id} implementation cycle {cycle}")
            execution["implementation_commit"] = reviewed_commit
            execution["phase"] = "ready_for_review"
            save_control(root, control_path, state)

            handoff = {
                "schema_version": 1,
                "packet_id": packet_id,
                "baseline_revision": state["baseline_revision"],
                "plan_revision": state["plan_revision"],
                "base_commit": packet_base,
                "implementation_commit": reviewed_commit,
                "cycle": cycle,
                "files_changed": changed_files(root, packet_base, reviewed_commit),
                "acceptance_results": {},
                "validation": [],
                "discoveries": [],
                "known_uncertainties": [],
                "status": "READY_FOR_REVIEW",
            }
            write_runtime_json(root, Path("handoffs") / f"{packet_id}-cycle-{cycle:02d}.json", handoff)
        else:
            reviewed_commit = str(execution.get("implementation_commit") or git(root, "rev-parse", "HEAD"))
            if cycle < 1:
                cycle = 1
                execution["cycle"] = 1

        execution["phase"] = "reviewing"
        save_control(root, control_path, state)
        append_history(root, {"packet": packet_id, "cycle": cycle, "phase": "reviewing", "agent": reviewer.name}, history_enabled)
        if verbose:
            print(f"Independent review cycle {cycle} started.")

        result, review = reviewer.review(reviewer_prompt(packet_id, state, packet_base, reviewed_commit, cycle), root, REVIEW_SCHEMA)
        validate_review(
            review,
            packet_id=packet_id,
            baseline_revision=int(state["baseline_revision"]),
            plan_revision=int(state["plan_revision"]),
            packet_base=packet_base,
            reviewed_commit=reviewed_commit,
            cycle=cycle,
        )
        atomic_json(review_result_path(root, packet_id, cycle), review)
        append_history(root, {"packet": packet_id, "cycle": cycle, "phase": "review_finished", "agent": reviewer.name, "duration_s": round(result.duration_s, 3), "verdict": review["verdict"], "findings": len(review.get("findings", []))}, history_enabled)

        verdict = str(review["verdict"])
        if verdict == "PASS":
            execution["phase"] = "approved"
            execution["review_status"] = "passed"
            execution["reviewed_commit"] = reviewed_commit
            execution["approved_at"] = utc_now()
            save_control(root, control_path, state)
            commit_if_changed(root, f"Forge {packet_id} record independent review pass")
            print("Done. The implementation was independently reviewed and passed.")
            print("Forge reconciliation is next.")
            return 0

        if verdict == "ESCALATE":
            execution["phase"] = "escalated"
            execution["review_status"] = "escalated"
            save_control(root, control_path, state)
            commit_if_changed(root, f"Forge {packet_id} record review escalation")
            print("The review found something that needs your decision.")
            return 2

        execution["phase"] = "fixing"
        execution["review_status"] = "changes_required"
        save_control(root, control_path, state)
        phase = "fixing"
        if cycle >= max_cycles:
            execution["phase"] = "escalated"
            execution["review_status"] = "cycle_limit"
            save_control(root, control_path, state)
            commit_if_changed(root, f"Forge {packet_id} record review cycle limit")
            print("The automatic review limit was reached. Your decision is needed.")
            return 2
        if not verbose:
            print("The independent review found an important issue. It is being fixed.")

    raise ForgeRunnerError("Forge review loop ended unexpectedly.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge", description="Forge optional external-agent runner")
    parser.add_argument("--verbose", action="store_true", help="show internal execution details")
    parser.add_argument("--control", default=str(CONTROL_DEFAULT), help="project control-state path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="check local Forge/agent readiness")
    status_parser = sub.add_parser("status", help="show simple execution status")
    status_parser.add_argument("packet", nargs="?", help="Work Packet ID")
    run_parser = sub.add_parser("run", help="implement and independently review a Work Packet")
    run_parser.add_argument("packet", nargs="?", help="Work Packet ID")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repo_root(Path.cwd())
        control_path = (root / args.control).resolve()
        if args.command == "doctor":
            return doctor(root, control_path, args.verbose)
        if args.command == "status":
            return status(root, control_path, args.packet, args.verbose)
        profile = load_profile(root)
        return run_packet(root, control_path, args.packet, profile, args.verbose)
    except (ForgeRunnerError, AdapterError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
