#!/usr/bin/env python3
"""Optional Forge external-agent runner.

Coordinates one implementation owner and one independent reviewer around
immutable Git checkpoints. Project truth remains in Forge control state;
runner lifecycle state is kept separately under .claude/forge/runtime so
interrupted runs can resume without rewriting canonical project state.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

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

PACKET_ID_RX = re.compile(r"^WP-[A-Za-z0-9._-]+$")
PHASES = {
    "pending",
    "implementing",
    "ready_for_review",
    "reviewing",
    "fixing",
    "approved",
    "escalated",
    "reconcile_required",
}
VERDICTS = {"PASS", "CHANGES_REQUIRED", "ESCALATE"}
SEVERITIES = {"Critical", "High", "Medium", "Low"}
CONFIDENCE = {"High", "Medium", "Low"}
SCOPES = {"current_required", "current_blocking", "adjacent", "future", "unrelated"}
CURRENT_SCOPES = {"current_required", "current_blocking"}
SERIOUS = {"Critical", "High"}
ELIGIBLE_PACKET_STATUSES = {"in_progress"}


class ForgeRunnerError(RuntimeError):
    """Safe user-facing runner failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_local(
    command: list[str],
    cwd: Path,
    *,
    input_text: str | None = None,
    timeout_s: int | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


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


def resolve_control_path(root: Path, requested: str) -> Path:
    candidate = (root / requested).resolve()
    try:
        rel = candidate.relative_to(root)
    except ValueError as exc:
        raise ForgeRunnerError("Forge control state must be inside the project repository.") from exc
    if not rel.parts or rel.parts[0] != ".claude":
        raise ForgeRunnerError("Forge control state must live under the project's .claude directory.")
    return candidate


def validate_packet_id(packet_id: str) -> str:
    if not PACKET_ID_RX.fullmatch(packet_id):
        raise ForgeRunnerError("Invalid Work Packet ID.")
    return packet_id


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
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def git_path(root: Path, relative: str) -> Path:
    raw = git(root, "rev-parse", "--git-path", relative)
    path = Path(raw)
    return path if path.is_absolute() else (root / path).resolve()


def ensure_runtime_excluded(root: Path) -> None:
    exclude = git_path(root, "info/exclude")
    exclude.parent.mkdir(parents=True, exist_ok=True)
    marker = ".claude/forge/runtime/"
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if marker not in current.splitlines():
        with exclude.open("a", encoding="utf-8") as handle:
            if current and not current.endswith("\n"):
                handle.write("\n")
            handle.write(marker + "\n")


@contextmanager
def execution_lock(root: Path) -> Iterator[None]:
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (root / common).resolve()
    lock_path = common / "forge-run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, BlockingIOError) as exc:
            raise ForgeRunnerError("Another Forge runner is already active for this repository.") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()} {utc_now()}\n")
        handle.flush()
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        handle.close()


def runtime_state_path(root: Path, packet_id: str) -> Path:
    validate_packet_id(packet_id)
    return root / RUNTIME_DIR / "executions" / f"{packet_id}.json"


def review_result_path(root: Path, packet_id: str, cycle: int) -> Path:
    validate_packet_id(packet_id)
    return root / RUNTIME_DIR / "reviews" / f"{packet_id}-review-{cycle:02d}.json"


def handoff_path(root: Path, packet_id: str, cycle: int) -> Path:
    validate_packet_id(packet_id)
    return root / RUNTIME_DIR / "handoffs" / f"{packet_id}-cycle-{cycle:02d}.json"


def deferred_findings_path(root: Path, packet_id: str) -> Path:
    validate_packet_id(packet_id)
    return root / RUNTIME_DIR / "deferred-findings" / f"{packet_id}.json"


def append_history(root: Path, event: dict[str, Any], enabled: bool = True) -> None:
    if not enabled:
        return
    path = root / RUNTIME_DIR / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": utc_now(), **event}, sort_keys=True) + "\n")


def validate_profile(profile: dict[str, Any]) -> None:
    allowed_top = {"version", "profile", "roles", "review", "interaction", "history"}
    if set(profile) - allowed_top:
        raise ForgeRunnerError("Execution profile contains unsupported options.")
    if profile.get("version") != 1 or not isinstance(profile.get("profile"), str):
        raise ForgeRunnerError("Unsupported Forge execution profile.")
    roles = profile.get("roles")
    if not isinstance(roles, dict) or set(roles) != {"implementer", "reviewer"}:
        raise ForgeRunnerError("Execution profile roles are invalid.")
    implementer = roles["implementer"]
    reviewer = roles["reviewer"]
    if not isinstance(implementer, dict) or not isinstance(reviewer, dict):
        raise ForgeRunnerError("Execution profile roles are invalid.")
    if implementer.get("adapter") != "claude-code-cli":
        raise ForgeRunnerError("This runner currently supports claude-code-cli as implementer.")
    if reviewer.get("adapter") != "codex-cli":
        raise ForgeRunnerError("This runner currently supports codex-cli as reviewer.")
    if reviewer.get("write_access") is not False:
        raise ForgeRunnerError("The independent reviewer must have write_access=false.")
    review = profile.get("review")
    if not isinstance(review, dict):
        raise ForgeRunnerError("Execution profile review settings are invalid.")
    allowed_review = {
        "max_cycles",
        "checkpoint_required",
        "independent",
        "on_reviewer_unavailable",
    }
    if set(review) - allowed_review:
        raise ForgeRunnerError("Execution profile review settings contain unsupported options.")
    max_cycles = review.get("max_cycles")
    if not isinstance(max_cycles, int) or isinstance(max_cycles, bool) or not 1 <= max_cycles <= 10:
        raise ForgeRunnerError("review.max_cycles must be an integer between 1 and 10.")
    if review.get("checkpoint_required") is not True or review.get("independent") is not True:
        raise ForgeRunnerError("Dual-agent review requires independent checkpointed review.")
    if review.get("on_reviewer_unavailable") != "stop":
        raise ForgeRunnerError("Unsupported reviewer-unavailable policy.")
    interaction = profile.get("interaction", {})
    if not isinstance(interaction, dict) or set(interaction) - {"detail", "progress"}:
        raise ForgeRunnerError("Execution profile interaction settings are invalid.")
    if interaction.get("detail", "simple") not in {"simple", "verbose"}:
        raise ForgeRunnerError("Unsupported interaction.detail setting.")
    if interaction.get("progress", "concise") not in {"concise", "verbose"}:
        raise ForgeRunnerError("Unsupported interaction.progress setting.")
    history = profile.get("history", {})
    if not isinstance(history, dict) or set(history) - {"enabled"}:
        raise ForgeRunnerError("Execution profile history settings are invalid.")
    if not isinstance(history.get("enabled", True), bool):
        raise ForgeRunnerError("history.enabled must be boolean.")


def load_profile(root: Path) -> dict[str, Any]:
    project_profile = root / PROFILE_DEFAULT
    profile = read_json(project_profile if project_profile.exists() else PROFILE_TEMPLATE)
    validate_profile(profile)
    return profile


def validate_control(root: Path, control_path: Path) -> None:
    completed = run_local([sys.executable, str(CONTROL_VALIDATOR), str(control_path)], root)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise ForgeRunnerError(f"Forge control state is invalid. {detail[:700]}")


def load_valid_control(root: Path, control_path: Path) -> dict[str, Any]:
    validate_control(root, control_path)
    return read_json(control_path)


def revisions(state: dict[str, Any]) -> tuple[int, int]:
    baseline = state.get("baseline_revision")
    plan = state.get("plan_revision")
    if not isinstance(baseline, int) or isinstance(baseline, bool):
        raise ForgeRunnerError("Invalid baseline revision.")
    if not isinstance(plan, int) or isinstance(plan, bool):
        raise ForgeRunnerError("Invalid plan revision.")
    return baseline, plan


def choose_packet(state: dict[str, Any], packet_id: str | None) -> str:
    packets = state.get("work_packets")
    if not isinstance(packets, dict):
        raise ForgeRunnerError("Forge work_packets state is invalid.")
    active = state.get("active_work_packets")
    if not isinstance(active, list):
        raise ForgeRunnerError("Forge active_work_packets state is invalid.")
    if packet_id is None:
        if len(active) != 1:
            raise ForgeRunnerError("Specify a Work Packet when there is not exactly one active packet.")
        packet_id = str(active[0])
    validate_packet_id(packet_id)
    packet = packets.get(packet_id)
    if not isinstance(packet, dict):
        raise ForgeRunnerError(f"Unknown Work Packet: {packet_id}")
    if packet_id not in active:
        raise ForgeRunnerError(f"{packet_id} is not an active Work Packet.")
    if packet.get("status") not in ELIGIBLE_PACKET_STATUSES:
        raise ForgeRunnerError(f"{packet_id} is not eligible to run in its current status.")
    return packet_id


def check_execution_preconditions(state: dict[str, Any], packet_id: str) -> None:
    baseline, plan = revisions(state)
    gate = state.get("gates", {}).get("plan_consistency", {})
    if not isinstance(gate, dict):
        raise ForgeRunnerError("Plan Consistency gate is missing.")
    if gate.get("status") not in {"passed", "passed_with_explicit_gaps"}:
        raise ForgeRunnerError("The current plan is not approved for implementation.")
    if gate.get("baseline_revision") != baseline or gate.get("plan_revision") != plan:
        raise ForgeRunnerError("The plan changed since the last consistency check. Reconcile it before running.")
    packet = state["work_packets"][packet_id]
    for dependency in packet.get("dependencies", []):
        target = state.get("work_packets", {}).get(dependency) or state.get("milestones", {}).get(dependency)
        if not isinstance(target, dict) or target.get("status") != "done":
            raise ForgeRunnerError(f"{packet_id} is waiting for dependency {dependency}.")


def new_execution_state(
    root: Path,
    state: dict[str, Any],
    packet_id: str,
) -> dict[str, Any]:
    baseline, plan = revisions(state)
    return {
        "version": 1,
        "packet_id": packet_id,
        "phase": "pending",
        "packet_base_commit": git(root, "rev-parse", "HEAD"),
        "implementation_attempt": 0,
        "review_cycle": 0,
        "completed_reviews": 0,
        "last_completed_review": None,
        "implementation_commit": None,
        "baseline_revision": baseline,
        "plan_revision": plan,
        "review_status": "not_started",
        "correction_from_review": None,
        "reason": None,
        "approved_at": None,
    }


def load_execution_state(
    root: Path,
    state: dict[str, Any],
    packet_id: str,
) -> dict[str, Any]:
    path = runtime_state_path(root, packet_id)
    if not path.exists():
        value = new_execution_state(root, state, packet_id)
        atomic_json(path, value)
        return value
    value = read_json(path)
    if value.get("version") != 1 or value.get("packet_id") != packet_id:
        raise ForgeRunnerError("Forge execution recovery state is invalid.")
    phase = value.get("phase")
    if phase not in PHASES:
        raise ForgeRunnerError("Forge execution recovery phase is invalid.")
    for key in ("implementation_attempt", "review_cycle", "completed_reviews"):
        current = value.get(key)
        if not isinstance(current, int) or isinstance(current, bool) or current < 0:
            raise ForgeRunnerError("Forge execution recovery counters are invalid.")
    return value


def save_execution_state(root: Path, packet_id: str, execution: dict[str, Any]) -> None:
    atomic_json(runtime_state_path(root, packet_id), execution)


def worktree_changes(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ForgeRunnerError("Could not inspect repository changes.")
    raw = completed.stdout.decode("utf-8", errors="replace")
    items = [item for item in raw.split("\0") if item]
    paths: list[str] = []
    index = 0
    while index < len(items):
        entry = items[index]
        path = entry[3:] if len(entry) >= 4 else entry
        paths.append(path)
        if entry[:2] and entry[0] in {"R", "C"} and index + 1 < len(items):
            index += 1
            paths.append(items[index])
        index += 1
    return paths


def repository_is_clean(root: Path) -> bool:
    return not worktree_changes(root)


def commit_all_changes(root: Path, message: str) -> str:
    if repository_is_clean(root):
        return git(root, "rev-parse", "HEAD")
    git(root, "add", "-A")
    git(root, "-c", "core.hooksPath=/dev/null", "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def changed_files(root: Path, base: str, head: str) -> list[str]:
    output = git(root, "diff", "--name-only", f"{base}..{head}")
    return [line for line in output.splitlines() if line.strip()]


def capture_invalid_control(root: Path, packet_id: str, candidate: str) -> Path:
    path = root / RUNTIME_DIR / "invalid-control" / f"{packet_id}-{utc_now().replace(':', '')}.json.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(candidate, encoding="utf-8")
    return path


def validate_control_after_agent(
    root: Path,
    control_path: Path,
    packet_id: str,
    previous_text: str,
) -> dict[str, Any]:
    candidate = control_path.read_text(encoding="utf-8", errors="replace") if control_path.exists() else ""
    try:
        validate_control(root, control_path)
        return read_json(control_path)
    except ForgeRunnerError:
        evidence = capture_invalid_control(root, packet_id, candidate)
        control_path.write_text(previous_text, encoding="utf-8")
        validate_control(root, control_path)
        raise ForgeRunnerError(
            f"The implementation produced invalid Forge project state. "
            f"The last valid state was restored; the invalid candidate is saved at {evidence.relative_to(root)}."
        )


def parse_implementation_report(stdout: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "summary": "",
        "acceptance_results": {},
        "validation": [],
        "discoveries": [],
        "known_uncertainties": [],
        "structured": False,
    }
    try:
        outer = json.loads(stdout)
    except json.JSONDecodeError:
        result["summary"] = stdout[-2000:]
        return result
    if not isinstance(outer, dict):
        result["summary"] = str(outer)[-2000:]
        return result
    inner = outer.get("result")
    if not isinstance(inner, str):
        result["summary"] = json.dumps(outer)[-2000:]
        return result
    try:
        payload = json.loads(inner)
    except json.JSONDecodeError:
        result["summary"] = inner[-2000:]
        return result
    if not isinstance(payload, dict):
        result["summary"] = inner[-2000:]
        return result
    result["summary"] = str(payload.get("summary") or "")[-2000:]
    if isinstance(payload.get("acceptance_results"), dict):
        result["acceptance_results"] = payload["acceptance_results"]
    if isinstance(payload.get("validation"), list):
        result["validation"] = payload["validation"]
    if isinstance(payload.get("discoveries"), list):
        result["discoveries"] = payload["discoveries"]
    if isinstance(payload.get("known_uncertainties"), list):
        result["known_uncertainties"] = payload["known_uncertainties"]
    result["structured"] = True
    return result


def implementation_prompt(
    packet_id: str,
    state: dict[str, Any],
    findings: list[dict[str, Any]] | None,
) -> str:
    packet = state["work_packets"][packet_id]
    prompt = f"""
You are the IMPLEMENTER for Forge Work Packet {packet_id}.
Work only inside the current project's approved scope. Read the canonical requirements,
architecture, plan, tests, and .claude/project-control.json before editing.

Packet snapshot:
{json.dumps(packet, indent=2)}

Rules:
- Make the smallest coherent implementation that satisfies the Work Packet.
- Run relevant tests/checks and fix failures caused by your work.
- Preserve legitimate canonical Forge state updates such as requirement evidence.
- Do not silently expand scope.
- Do not mark the packet approved, independently reviewed, reconciled, or done.
- Do not create Git commits; the Forge runner owns review checkpoints.
- Keep user-facing text concise.

Finish with a JSON object only:
{{
  "summary": "short outcome",
  "acceptance_results": {{}},
  "validation": [],
  "discoveries": [],
  "known_uncertainties": []
}}
Only report validation you actually ran.
"""
    if findings:
        prompt += f"""
This is a correction attempt. Address only the current-scope review findings below.
Independently verify them against primary evidence; do not implement adjacent/future/unrelated findings.

Current-scope review findings:
{json.dumps(findings, indent=2)}
"""
    return prompt.strip()


def reviewer_prompt(
    packet_id: str,
    state: dict[str, Any],
    packet_base: str,
    reviewed_commit: str,
    cycle: int,
) -> str:
    packet = state["work_packets"][packet_id]
    return f"""
You are the independent REVIEWER for Forge Work Packet {packet_id}.

Review the repository at commit {reviewed_commit} against approved project intent.
The packet began at {packet_base}. Inspect the complete diff {packet_base}..{reviewed_commit},
current source, tests, configuration, requirements, architecture, and relevant evidence.

Packet snapshot:
{json.dumps(packet, indent=2)}

Required identity:
- packet_id: {packet_id}
- baseline_revision: {state["baseline_revision"]}
- plan_revision: {state["plan_revision"]}
- base_commit: {packet_base}
- reviewed_commit: {reviewed_commit}
- cycle: {cycle}

Review specification compliance first, then correctness/regressions, then security/privacy/
reliability/performance and test/failure-path adequacy where relevant.

Rules:
- Treat implementer summaries as claims, not evidence.
- Do not edit production files.
- Ignore stylistic preference and low-value lint commentary unless it has credible impact.
- Classify severity separately from scope relevance.
- Adjacent/future/unrelated findings do not automatically enter current implementation.
- PASS only when no unresolved current_required/current_blocking Critical or High issue remains
  and the implementation is sufficiently supported by evidence.
""".strip()


def require_exact_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    if set(value) != required:
        raise ForgeRunnerError(f"{label} does not match the required structured review contract.")


def validate_review_contract(
    payload: dict[str, Any],
    *,
    packet_id: str,
    baseline_revision: int,
    plan_revision: int,
    packet_base: str,
    reviewed_commit: str,
    cycle: int,
) -> None:
    root_keys = {
        "schema_version",
        "packet_id",
        "baseline_revision",
        "plan_revision",
        "base_commit",
        "reviewed_commit",
        "cycle",
        "verdict",
        "summary",
        "findings",
    }
    require_exact_keys(payload, root_keys, "Review result")
    expected = {
        "schema_version": 1,
        "packet_id": packet_id,
        "baseline_revision": baseline_revision,
        "plan_revision": plan_revision,
        "base_commit": packet_base,
        "reviewed_commit": reviewed_commit,
        "cycle": cycle,
    }
    for key, expected_value in expected.items():
        if payload.get(key) != expected_value:
            raise ForgeRunnerError(f"Reviewer returned stale or mismatched {key}.")
    if payload.get("verdict") not in VERDICTS or not isinstance(payload.get("summary"), str):
        raise ForgeRunnerError("Reviewer returned an invalid verdict or summary.")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise ForgeRunnerError("Reviewer findings are invalid.")
    finding_keys = {
        "id",
        "severity",
        "confidence",
        "scope_relevance",
        "title",
        "requirements",
        "evidence",
        "impact",
        "root_cause",
        "correction",
        "validation",
    }
    evidence_keys = {"kind", "source", "location", "detail"}
    for finding in findings:
        if not isinstance(finding, dict):
            raise ForgeRunnerError("Reviewer finding is not an object.")
        require_exact_keys(finding, finding_keys, "Review finding")
        if not isinstance(finding["id"], str) or not finding["id"]:
            raise ForgeRunnerError("Review finding ID is invalid.")
        if finding["severity"] not in SEVERITIES or finding["confidence"] not in CONFIDENCE:
            raise ForgeRunnerError("Review finding classification is invalid.")
        if finding["scope_relevance"] not in SCOPES:
            raise ForgeRunnerError("Review finding scope relevance is invalid.")
        if not isinstance(finding["title"], str) or not finding["title"]:
            raise ForgeRunnerError("Review finding title is invalid.")
        if not isinstance(finding["requirements"], list) or not all(
            isinstance(item, str) for item in finding["requirements"]
        ):
            raise ForgeRunnerError("Review finding requirements are invalid.")
        if not isinstance(finding["evidence"], list):
            raise ForgeRunnerError("Review finding evidence is invalid.")
        for evidence in finding["evidence"]:
            if not isinstance(evidence, dict):
                raise ForgeRunnerError("Review evidence is invalid.")
            require_exact_keys(evidence, evidence_keys, "Review evidence")
            if evidence["kind"] not in {"code", "test", "runtime", "config", "requirement", "other"}:
                raise ForgeRunnerError("Review evidence kind is invalid.")
            if not isinstance(evidence["source"], str) or not isinstance(evidence["detail"], str):
                raise ForgeRunnerError("Review evidence source/detail is invalid.")
            if evidence["location"] is not None and not isinstance(evidence["location"], str):
                raise ForgeRunnerError("Review evidence location is invalid.")
        for key in ("impact", "root_cause", "correction", "validation"):
            if not isinstance(finding[key], str):
                raise ForgeRunnerError(f"Review finding {key} is invalid.")
    if payload["verdict"] == "PASS":
        blocking = [
            finding
            for finding in findings
            if finding["severity"] in SERIOUS and finding["scope_relevance"] in CURRENT_SCOPES
        ]
        if blocking:
            raise ForgeRunnerError("Reviewer returned PASS with unresolved blocking findings.")


def current_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding
        for finding in review.get("findings", [])
        if isinstance(finding, dict) and finding.get("scope_relevance") in CURRENT_SCOPES
    ]


def deferred_findings(review: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding
        for finding in review.get("findings", [])
        if isinstance(finding, dict) and finding.get("scope_relevance") not in CURRENT_SCOPES
    ]


def persist_deferred_findings(root: Path, packet_id: str, review: dict[str, Any]) -> int:
    findings = deferred_findings(review)
    if not findings:
        return 0
    path = deferred_findings_path(root, packet_id)
    existing: list[dict[str, Any]] = []
    if path.exists():
        value = read_json(path)
        raw = value.get("findings", [])
        if isinstance(raw, list):
            existing = [item for item in raw if isinstance(item, dict)]
    seen = {str(item.get("id")) for item in existing}
    for finding in findings:
        if str(finding.get("id")) not in seen:
            existing.append(finding)
    atomic_json(
        path,
        {
            "version": 1,
            "packet_id": packet_id,
            "updated_at": utc_now(),
            "findings": existing,
        },
    )
    return sum(1 for item in findings if item.get("severity") in SERIOUS)


@contextmanager
def isolated_review_checkout(root: Path, reviewed_commit: str) -> Iterator[Path]:
    temp_parent = Path(tempfile.mkdtemp(prefix="forge-review-"))
    checkout = temp_parent / "repo"
    try:
        git(root, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", str(checkout), reviewed_commit)
        yield checkout
    finally:
        run_local(
            ["git", "-c", "core.hooksPath=/dev/null", "worktree", "remove", "--force", str(checkout)],
            root,
        )
        try:
            temp_parent.rmdir()
        except OSError:
            pass


def assert_review_target_unchanged(root: Path, reviewed_commit: str) -> None:
    current_head = git(root, "rev-parse", "HEAD")
    if current_head != reviewed_commit or not repository_is_clean(root):
        raise ForgeRunnerError(
            "The repository changed while it was being reviewed. Nothing was approved; "
            "review the new repository state before continuing."
        )


def control_from_checkout(checkout: Path, control_rel: Path) -> dict[str, Any]:
    path = (checkout / control_rel).resolve()
    try:
        path.relative_to(checkout.resolve())
    except ValueError as exc:
        raise ForgeRunnerError("Review control path escaped the isolated checkout.") from exc
    if not path.exists():
        raise ForgeRunnerError("The reviewed commit does not contain Forge control state.")
    return read_json(path)


def latest_completed_review(root: Path, packet_id: str, execution: dict[str, Any]) -> dict[str, Any]:
    number = execution.get("last_completed_review")
    if not isinstance(number, int) or number < 1:
        raise ForgeRunnerError("Cannot resume correction without a completed review.")
    return read_json(review_result_path(root, packet_id, number))


def write_handoff(
    root: Path,
    packet_id: str,
    state: dict[str, Any],
    packet_base: str,
    implementation_commit: str,
    cycle: int,
    report: dict[str, Any],
) -> None:
    atomic_json(
        handoff_path(root, packet_id, cycle),
        {
            "schema_version": 1,
            "packet_id": packet_id,
            "baseline_revision": state["baseline_revision"],
            "plan_revision": state["plan_revision"],
            "base_commit": packet_base,
            "implementation_commit": implementation_commit,
            "cycle": cycle,
            "files_changed": changed_files(root, packet_base, implementation_commit),
            "agent_report_structured": report["structured"],
            "summary": report["summary"],
            "acceptance_results": report["acceptance_results"],
            "validation": report["validation"],
            "discoveries": report["discoveries"],
            "known_uncertainties": report["known_uncertainties"],
            "status": "READY_FOR_REVIEW",
        },
    )


def doctor(root: Path, control_path: Path, verbose: bool) -> int:
    checks: list[tuple[bool, str]] = [(True, "Git repository available")]
    try:
        load_profile(root)
        checks.append((True, "Execution profile valid"))
    except ForgeRunnerError as exc:
        checks.append((False, str(exc)))
    implementer = ClaudeCodeImplementer()
    reviewer = CodexCLIReviewer()
    checks.append(implementer.doctor(root))
    checks.append(reviewer.doctor(root))
    if not control_path.exists():
        checks.append((False, "Forge project state is missing."))
    else:
        try:
            state = load_valid_control(root, control_path)
            packet_id = choose_packet(state, None)
            check_execution_preconditions(state, packet_id)
            checks.append((True, "Forge project state ready"))
        except ForgeRunnerError as exc:
            checks.append((False, str(exc)))
    bad = [message for ok, message in checks if not ok]
    if bad:
        print("Forge is not ready.")
        for message in bad:
            print(f"- {message}")
        return 2
    print("Forge prerequisites look ready.")
    if verbose:
        for _, message in checks:
            print(f"- {message}")
        print("- Claude account access is verified when an implementation request actually starts.")
    return 0


def status(root: Path, control_path: Path, packet_id: str | None, verbose: bool) -> int:
    state = load_valid_control(root, control_path)
    packet_id = choose_packet(state, packet_id)
    execution = load_execution_state(root, state, packet_id)
    phase = execution["phase"]
    friendly = {
        "pending": "ready to start",
        "implementing": "being implemented",
        "ready_for_review": "ready for review",
        "reviewing": "being independently reviewed",
        "fixing": "being corrected after review",
        "approved": "review passed",
        "escalated": "waiting for your decision",
        "reconcile_required": "waiting for Forge reconciliation",
    }[phase]
    print(f"{packet_id} is {friendly}.")
    if execution.get("reason"):
        print(str(execution["reason"]))
    if verbose:
        print(json.dumps(execution, indent=2))
    return 0


def run_packet(
    root: Path,
    control_path: Path,
    packet_id: str | None,
    profile: dict[str, Any],
    verbose: bool,
) -> int:
    state = load_valid_control(root, control_path)
    packet_id = choose_packet(state, packet_id)
    check_execution_preconditions(state, packet_id)
    execution = load_execution_state(root, state, packet_id)

    if execution["phase"] == "approved":
        print("Review already passed. Forge reconciliation is next.")
        return 0
    if execution["phase"] == "escalated":
        print("This Work Packet needs your decision before it can continue.")
        if execution.get("reason"):
            print(str(execution["reason"]))
        return 2
    if execution["phase"] == "reconcile_required":
        print("The project plan changed during implementation. Reconcile it before review.")
        return 2

    if execution["phase"] == "pending" and not repository_is_clean(root):
        raise ForgeRunnerError("Your project has uncommitted changes. Commit them before starting this Work Packet.")

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
    control_rel = control_path.relative_to(root)
    packet_base = str(execution["packet_base_commit"])

    while True:
        phase = str(execution["phase"])
        if phase in {"pending", "implementing", "fixing"}:
            findings: list[dict[str, Any]] | None = None
            if phase == "fixing":
                previous = latest_completed_review(root, packet_id, execution)
                findings = current_findings(previous)
                if not findings:
                    execution["phase"] = "approved"
                    execution["review_status"] = "passed_with_deferred_findings"
                    execution["approved_at"] = utc_now()
                    save_execution_state(root, packet_id, execution)
                    print("Review passed for the current scope.")
                    return 0
                execution["implementation_attempt"] = int(execution["implementation_attempt"]) + 1
                execution["correction_from_review"] = int(execution["last_completed_review"])
                execution["phase"] = "implementing"
                save_execution_state(root, packet_id, execution)
            elif phase == "pending":
                execution["implementation_attempt"] = 1
                execution["correction_from_review"] = None
                execution["phase"] = "implementing"
                save_execution_state(root, packet_id, execution)
            elif phase == "implementing":
                correction_review = execution.get("correction_from_review")
                if isinstance(correction_review, int) and correction_review > 0:
                    findings = current_findings(
                        read_json(review_result_path(root, packet_id, correction_review))
                    )

            dispatch_state = load_valid_control(root, control_path)
            dispatch_revisions = revisions(dispatch_state)
            previous_control_text = control_path.read_text(encoding="utf-8")
            before_head = git(root, "rev-parse", "HEAD")
            before_changes = set(worktree_changes(root))

            append_history(
                root,
                {
                    "packet": packet_id,
                    "phase": execution["phase"],
                    "attempt": execution["implementation_attempt"],
                    "agent": implementer.name,
                },
                history_enabled,
            )
            if verbose:
                print(f"Implementation attempt {execution['implementation_attempt']} started.")

            result = implementer.implement(
                implementation_prompt(packet_id, dispatch_state, findings),
                root,
            )
            report = parse_implementation_report(result.stdout)
            post_state = validate_control_after_agent(
                root,
                control_path,
                packet_id,
                previous_control_text,
            )
            post_revisions = revisions(post_state)
            if post_revisions != dispatch_revisions:
                checkpoint = commit_all_changes(
                    root,
                    f"Forge {packet_id} checkpoint before reconciliation",
                )
                execution["implementation_commit"] = checkpoint
                execution["phase"] = "reconcile_required"
                execution["reason"] = "The requirements or plan revision changed during implementation."
                save_execution_state(root, packet_id, execution)
                print("The project plan changed during implementation. Changes were preserved; reconcile before review.")
                return 2

            after_changes = set(worktree_changes(root))
            changed_during_attempt = before_head != git(root, "rev-parse", "HEAD") or after_changes != before_changes
            if findings and not changed_during_attempt:
                execution["phase"] = "escalated"
                execution["review_status"] = "unresolved"
                execution["reason"] = "The requested review correction produced no repository change."
                save_execution_state(root, packet_id, execution)
                print("The review issue could not be resolved automatically and needs your decision.")
                return 2

            implementation_commit = commit_all_changes(
                root,
                f"Forge {packet_id} implementation attempt {execution['implementation_attempt']}",
            )
            next_cycle = int(execution["completed_reviews"]) + 1
            execution["implementation_commit"] = implementation_commit
            execution["review_cycle"] = next_cycle
            execution["phase"] = "ready_for_review"
            execution["review_status"] = "pending"
            execution["correction_from_review"] = None
            execution["baseline_revision"], execution["plan_revision"] = post_revisions
            execution["reason"] = None
            save_execution_state(root, packet_id, execution)
            write_handoff(
                root,
                packet_id,
                post_state,
                packet_base,
                implementation_commit,
                next_cycle,
                report,
            )
            append_history(
                root,
                {
                    "packet": packet_id,
                    "phase": "implementation_finished",
                    "attempt": execution["implementation_attempt"],
                    "implementation_commit": implementation_commit,
                    "agent": implementer.name,
                    "duration_s": round(result.duration_s, 3),
                },
                history_enabled,
            )
            phase = "ready_for_review"

        if phase in {"ready_for_review", "reviewing"}:
            reviewed_commit = execution.get("implementation_commit")
            cycle = execution.get("review_cycle")
            if not isinstance(reviewed_commit, str) or not reviewed_commit:
                raise ForgeRunnerError("Recovery state is missing the implementation checkpoint.")
            if not isinstance(cycle, int) or cycle < 1:
                raise ForgeRunnerError("Recovery state is missing the review cycle.")
            if cycle > max_cycles:
                execution["phase"] = "escalated"
                execution["review_status"] = "cycle_limit"
                execution["reason"] = "The automatic review limit was reached."
                save_execution_state(root, packet_id, execution)
                print("The automatic review limit was reached. Your decision is needed.")
                return 2

            assert_review_target_unchanged(root, reviewed_commit)
            execution["phase"] = "reviewing"
            save_execution_state(root, packet_id, execution)
            append_history(
                root,
                {"packet": packet_id, "phase": "reviewing", "cycle": cycle, "agent": reviewer.name},
                history_enabled,
            )
            if verbose:
                print(f"Independent review cycle {cycle} started.")

            with isolated_review_checkout(root, reviewed_commit) as checkout:
                review_state = control_from_checkout(checkout, control_rel)
                review_baseline, review_plan = revisions(review_state)
                result, review = reviewer.review(
                    reviewer_prompt(
                        packet_id,
                        review_state,
                        packet_base,
                        reviewed_commit,
                        cycle,
                    ),
                    checkout,
                    REVIEW_SCHEMA,
                )

            try:
                assert_review_target_unchanged(root, reviewed_commit)
            except ForgeRunnerError as exc:
                stale_path = root / RUNTIME_DIR / "stale-reviews" / f"{packet_id}-review-{cycle:02d}.json"
                atomic_json(stale_path, review)
                execution["phase"] = "escalated"
                execution["review_status"] = "stale"
                execution["reason"] = str(exc)
                save_execution_state(root, packet_id, execution)
                print(str(exc))
                return 2

            current_state = load_valid_control(root, control_path)
            if revisions(current_state) != (review_baseline, review_plan):
                execution["phase"] = "reconcile_required"
                execution["review_status"] = "stale"
                execution["reason"] = "The requirements or plan revision changed during review."
                save_execution_state(root, packet_id, execution)
                print("The project plan changed during review. Nothing was approved; reconcile before continuing.")
                return 2

            validate_review_contract(
                review,
                packet_id=packet_id,
                baseline_revision=review_baseline,
                plan_revision=review_plan,
                packet_base=packet_base,
                reviewed_commit=reviewed_commit,
                cycle=cycle,
            )
            atomic_json(review_result_path(root, packet_id, cycle), review)
            execution["completed_reviews"] = cycle
            execution["last_completed_review"] = cycle
            serious_deferred = persist_deferred_findings(root, packet_id, review)
            append_history(
                root,
                {
                    "packet": packet_id,
                    "phase": "review_finished",
                    "cycle": cycle,
                    "agent": reviewer.name,
                    "duration_s": round(result.duration_s, 3),
                    "verdict": review["verdict"],
                    "findings": len(review["findings"]),
                },
                history_enabled,
            )

            verdict = str(review["verdict"])
            current = current_findings(review)
            if verdict == "PASS" or (verdict == "CHANGES_REQUIRED" and not current):
                execution["phase"] = "approved"
                execution["review_status"] = (
                    "passed_with_deferred_findings" if deferred_findings(review) else "passed"
                )
                execution["reviewed_commit"] = reviewed_commit
                execution["approved_at"] = utc_now()
                execution["reason"] = None
                save_execution_state(root, packet_id, execution)
                print("Done. The implementation was independently reviewed and passed.")
                if serious_deferred:
                    pointer = deferred_findings_path(root, packet_id).relative_to(root)
                    print(
                        f"The review also found {serious_deferred} serious issue(s) outside the current scope. "
                        f"Details: {pointer}"
                    )
                print("Forge reconciliation is next.")
                return 0

            if verdict == "ESCALATE":
                execution["phase"] = "escalated"
                execution["review_status"] = "escalated"
                execution["reason"] = str(review.get("summary") or "The review needs a human decision.")
                save_execution_state(root, packet_id, execution)
                print("The review found something that needs your decision.")
                print(execution["reason"])
                return 2

            if cycle >= max_cycles:
                execution["phase"] = "escalated"
                execution["review_status"] = "cycle_limit"
                execution["reason"] = "The automatic review limit was reached."
                save_execution_state(root, packet_id, execution)
                print("The automatic review limit was reached. Your decision is needed.")
                return 2

            execution["phase"] = "fixing"
            execution["review_status"] = "changes_required"
            execution["reason"] = None
            save_execution_state(root, packet_id, execution)
            if not verbose:
                print("The independent review found an important issue. It is being fixed.")
            continue

        raise ForgeRunnerError("Forge execution state cannot continue automatically.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge", description="Forge optional external-agent runner")
    parser.add_argument("--verbose", action="store_true", help="show internal execution details")
    parser.add_argument("--control", default=str(CONTROL_DEFAULT), help="control-state path under .claude/")
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
        control_path = resolve_control_path(root, args.control)
        ensure_runtime_excluded(root)
        with execution_lock(root):
            if args.command == "doctor":
                return doctor(root, control_path, args.verbose)
            if args.command == "status":
                return status(root, control_path, args.packet, args.verbose)
            profile = load_profile(root)
            return run_packet(root, control_path, args.packet, profile, args.verbose)
    except (ForgeRunnerError, AdapterError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
