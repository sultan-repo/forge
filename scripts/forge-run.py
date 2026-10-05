#!/usr/bin/env python3
"""Optional Forge external-agent runner.

Coordinates one implementation owner and one independent reviewer around
immutable Git checkpoints. Project truth remains in Forge control state;
runner lifecycle state is kept separately under .claude/forge/runtime so
interrupted runs can resume without rewriting canonical project state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from adapters import ClaudeCodeImplementer, CodexCLIReviewer
from adapters.base import AdapterError
from implementation_report import REPORT_EXAMPLE, evidence_references, parse_implementation_report

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
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_text.encode("utf-8", "surrogateescape") if input_text is not None else None,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    return subprocess.CompletedProcess(
        command,
        completed.returncode,
        completed.stdout.decode("utf-8", "surrogateescape"),
        completed.stderr.decode("utf-8", "surrogateescape"),
    )


def git_bytes(cwd: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    if check and completed.returncode != 0:
        detail = os.fsdecode(completed.stderr or completed.stdout).strip()
        raise ForgeRunnerError(f"Git check failed: {detail[:400]}")
    return completed.stdout


def git(cwd: Path, *args: str, check: bool = True, strip: bool = True) -> str:
    output = os.fsdecode(git_bytes(cwd, *args, check=check))
    return output.strip() if strip else output


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
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


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
    try:
        import fcntl
    except ImportError as exc:
        raise ForgeRunnerError("Forge runner locking requires macOS or Linux (fcntl is unavailable).") from exc
    common = Path(git(root, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (root / common).resolve()
    lock_path = common / "forge-run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ForgeRunnerError("Another Forge runner is already active for this repository.") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()} {utc_now()}\n")
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()


def runtime_path(root: Path, *parts: str) -> Path:
    base = root.resolve() / RUNTIME_DIR
    path = base.joinpath(*parts)
    try:
        path.resolve().relative_to(base)
    except (ValueError, OSError, RuntimeError) as exc:
        raise ForgeRunnerError("Forge runtime paths must stay inside .claude/forge/runtime; inspect symbolic links.") from exc
    return path


def runtime_state_path(root: Path, packet_id: str) -> Path:
    validate_packet_id(packet_id)
    return runtime_path(root, "executions", f"{packet_id}.json")


def review_result_path(root: Path, packet_id: str, cycle: int) -> Path:
    validate_packet_id(packet_id)
    return runtime_path(root, "reviews", f"{packet_id}-review-{cycle:02d}.json")


def handoff_path(root: Path, packet_id: str, cycle: int) -> Path:
    validate_packet_id(packet_id)
    return runtime_path(root, "handoffs", f"{packet_id}-cycle-{cycle:02d}.json")


def deferred_findings_path(root: Path, packet_id: str) -> Path:
    validate_packet_id(packet_id)
    return runtime_path(root, "deferred-findings", f"{packet_id}.json")


def append_history(root: Path, event: dict[str, Any], enabled: bool = True) -> None:
    if not enabled:
        return
    path = runtime_path(root, "history.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"at": utc_now(), **event}, sort_keys=True) + "\n")


def validate_profile(profile: dict[str, Any]) -> None:
    allowed_top = {"version", "profile", "roles", "review", "interaction", "history"}
    if set(profile) != allowed_top:
        raise ForgeRunnerError("Execution profile has missing or unsupported options.")
    if type(profile.get("version")) is not int or profile["version"] != 1:
        raise ForgeRunnerError("Unsupported Forge execution profile version.")
    if not isinstance(profile.get("profile"), str) or not profile["profile"]:
        raise ForgeRunnerError("Unsupported Forge execution profile.")
    roles = profile.get("roles")
    if not isinstance(roles, dict) or set(roles) != {"implementer", "reviewer"}:
        raise ForgeRunnerError("Execution profile roles are invalid.")
    implementer = roles["implementer"]
    reviewer = roles["reviewer"]
    if not isinstance(implementer, dict) or not isinstance(reviewer, dict):
        raise ForgeRunnerError("Execution profile roles are invalid.")
    if set(implementer) != {"adapter", "authentication"} or set(reviewer) != {
        "adapter", "authentication", "write_access"
    }:
        raise ForgeRunnerError("Execution profile roles have missing or unsupported options.")
    if any(role.get("authentication") != "inherited" for role in (implementer, reviewer)):
        raise ForgeRunnerError("Agent authentication must be inherited from the local CLI.")
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
    if set(review) != allowed_review:
        raise ForgeRunnerError("Execution profile review settings contain unsupported options.")
    max_cycles = review.get("max_cycles")
    if not isinstance(max_cycles, int) or isinstance(max_cycles, bool) or not 1 <= max_cycles <= 10:
        raise ForgeRunnerError("review.max_cycles must be an integer between 1 and 10.")
    if review.get("checkpoint_required") is not True or review.get("independent") is not True:
        raise ForgeRunnerError("Dual-agent review requires independent checkpointed review.")
    if review.get("on_reviewer_unavailable") != "stop":
        raise ForgeRunnerError("Unsupported reviewer-unavailable policy.")
    interaction = profile["interaction"]
    if not isinstance(interaction, dict) or set(interaction) != {"detail", "progress"}:
        raise ForgeRunnerError("Execution profile interaction settings are invalid.")
    if interaction["detail"] not in ("simple", "verbose"):
        raise ForgeRunnerError("Unsupported interaction.detail setting.")
    if interaction["progress"] not in ("concise", "verbose"):
        raise ForgeRunnerError("Unsupported interaction.progress setting.")
    history = profile["history"]
    if not isinstance(history, dict) or set(history) != {"enabled"}:
        raise ForgeRunnerError("Execution profile history settings are invalid.")
    if not isinstance(history["enabled"], bool):
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


def choose_packet(state: dict[str, Any], packet_id: str | None, *, require_eligible: bool = True) -> str:
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
    if require_eligible and packet_id not in active:
        raise ForgeRunnerError(f"{packet_id} is not an active Work Packet.")
    if require_eligible and packet.get("status") not in ELIGIBLE_PACKET_STATUSES:
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
    if revisions(packet) != (baseline, plan):
        raise ForgeRunnerError(f"{packet_id} does not match the current baseline and plan. Reconcile it before running.")
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
    *,
    create: bool = True,
) -> dict[str, Any]:
    path = runtime_state_path(root, packet_id)
    if not path.exists():
        value = new_execution_state(root, state, packet_id)
        if create:
            atomic_json(path, value)
        return value
    value = read_json(path)
    if type(value.get("version")) is not int or value["version"] != 1 or value.get("packet_id") != packet_id:
        raise ForgeRunnerError("Forge execution recovery state is invalid.")
    phase = value.get("phase")
    if not isinstance(phase, str) or phase not in PHASES:
        raise ForgeRunnerError("Forge execution recovery phase is invalid.")
    for key in ("implementation_attempt", "review_cycle", "completed_reviews"):
        current = value.get(key)
        if not isinstance(current, int) or isinstance(current, bool) or current < 0:
            raise ForgeRunnerError("Forge execution recovery counters are invalid.")
    for key in ("baseline_revision", "plan_revision"):
        current = value.get(key)
        if type(current) is not int or current < 1:
            raise ForgeRunnerError("Forge execution recovery revisions are invalid.")
    if not isinstance(value.get("packet_base_commit"), str) or not re.fullmatch(
        r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value["packet_base_commit"]
    ):
        raise ForgeRunnerError("Forge execution recovery base checkpoint is invalid.")
    return value


def save_execution_state(root: Path, packet_id: str, execution: dict[str, Any]) -> None:
    atomic_json(runtime_state_path(root, packet_id), execution)


def check_execution_control_path(root: Path, packet_id: str, control_rel: Path, execution: dict[str, Any]) -> None:
    # Older records predate custom-path binding and belong to the canonical file.
    if runtime_state_path(root, packet_id).exists() and execution.get(
        "control_path", CONTROL_DEFAULT.as_posix()
    ) != control_rel.as_posix():
        raise ForgeRunnerError("This execution belongs to a different Forge control-state path.")


def worktree_changes(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ForgeRunnerError("Could not inspect repository changes.")
    raw = os.fsdecode(completed.stdout)
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


def worktree_fingerprint(root: Path) -> str:
    """Compare working contents, including partial edits from an interrupted attempt."""
    digest = hashlib.sha256()
    # HEAD..worktree includes both staged and unstaged tracked changes. Git's binary
    # format preserves content changes that a filename-only status would miss.
    digest.update(git_bytes(root, "diff", "--binary", "--no-ext-diff", "HEAD", "--"))
    for relative in sorted(worktree_changes(root)):
        path = root / relative
        digest.update(os.fsencode(relative) + b"\0")
        if path.is_symlink():
            digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def commit_all_changes(root: Path, message: str) -> str:
    if repository_is_clean(root):
        return git(root, "rev-parse", "HEAD")
    git(root, "add", "-A")
    git(root, "-c", "core.hooksPath=/dev/null", "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def changed_files(root: Path, base: str, head: str) -> list[str]:
    output = git_bytes(root, "diff", "--name-only", "--no-renames", "-z", f"{base}..{head}", "--")
    return [os.fsdecode(path) for path in output.split(b"\0") if path]


def capture_invalid_control(root: Path, packet_id: str, candidate: str) -> Path:
    path = runtime_path(root, "invalid-control", f"{packet_id}-{utc_now().replace(':', '')}.json.txt")
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


def persist_implementation_report(
    root: Path,
    packet_id: str,
    attempt: int,
    stdout: str,
    *,
    implementation_outcome: str = "adapter_completed",
) -> dict[str, Any]:
    """Save private, unique original output before parsing or post-agent checks.

    A repeated attempt never replaces an earlier report. Adapter completion is
    not a product-success assertion. Runtime artifacts remain controller-local.
    """
    validate_packet_id(packet_id)
    directory = runtime_path(root, "reports")
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=directory, prefix=f"{packet_id}-attempt-{attempt:02d}-", suffix=".stdout.txt",
    )
    raw_path = Path(name)
    data = stdout.encode("utf-8", "surrogateescape")
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    report = parse_implementation_report(stdout)
    # The exact original has its own private artifact, not a second embedded copy.
    report.pop("raw_report", None)
    report["raw_report_path"] = raw_path.relative_to(root).as_posix()
    report["raw_report_sha256"] = hashlib.sha256(data).hexdigest()
    report["implementation_outcome"] = implementation_outcome
    atomic_json(raw_path.with_suffix(".json"), report)
    return report


def implementation_prompt(
    packet_id: str,
    state: dict[str, Any],
    findings: list[dict[str, Any]] | None,
    control_rel: Path = CONTROL_DEFAULT,
) -> str:
    packet = state["work_packets"][packet_id]
    prompt = f"""
You implement Forge Work Packet {packet_id} within its authorized scope.
Start from this snapshot and {control_rel.as_posix()}; read relevant requirement,
invariant, source, and test sections. Expand for risk or gaps; reuse current evidence.

Packet snapshot:
{json.dumps(packet, indent=2)}

Rules:
- Make the smallest coherent solution; fix failures caused by your work.
- Tie acceptance/invariant claims to named checks and results. Label failures and
  unverified checks; reporting a defect does not satisfy a requirement.
- Preserve legitimate canonical state/evidence updates. Do not expand scope.
- Do not mark the packet approved, independently reviewed, reconciled, or done.
- Do not commit or edit .claude/forge/runtime; the runner owns checkpoints/evidence.

Finish with a JSON object only, following this versioned example. Replace example
text with actual results; empty objects/arrays are appropriate when there is nothing to report:
{json.dumps(REPORT_EXAMPLE, indent=2)}
Only report validation you actually ran. Do not invent commands, exit codes, or evidence.
An optional validation.evidence object may reference existing results using reported_origin,
tested_commit, command, cwd, environment_identity, dependency_identity, result, and artifact.
Omit unknown metadata. Never label the final checkpoint as tested if code changed after the check.
References are still implementer-supplied claims until their primary artifacts are verified.
"""
    if findings:
        prompt += f"""
Correction attempt: verify these current-scope findings against primary evidence.
Address them without implementing adjacent/future/unrelated findings.

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
    handoff: dict[str, Any] | None = None,
    previous_review: dict[str, Any] | None = None,
) -> str:
    packet = state["work_packets"][packet_id]
    scope = (
        f"The packet began at {packet_base}. Inspect the complete diff {packet_base}..{reviewed_commit}, "
        "then inspect affected contracts, relevant source/tests, and supporting evidence."
    )
    if previous_review is not None:
        previous_commit = previous_review["reviewed_commit"]
        scope = (
            f"Correction review: start with the fix {previous_commit}..{reviewed_commit}, "
            "the prior current-scope findings below, and affected contracts. "
            f"The complete packet diff {packet_base}..{reviewed_commit} remains available. "
            "Broaden inspection for regressions, risk, or missing evidence; do not review only changed lines.\n"
            f"Prior findings (review cycle {previous_review['cycle']} at {previous_commit}):\n"
            f"{json.dumps(current_findings(previous_review), indent=2)}"
        )
    if handoff is not None:
        handoff = {key: value for key, value in handoff.items() if key != "raw_report"}
        handoff["validation_evidence"] = evidence_references(handoff.get("validation"), reviewed_commit)
    return f"""
You are the independent REVIEWER for Forge Work Packet {packet_id}.

Review the repository at commit {reviewed_commit} against approved project intent.
{scope}
Expand investigation when risk or missing evidence warrants it.

Packet snapshot:
{json.dumps(packet, indent=2)}

Implementation handoff (unverified implementer claims; verify against primary evidence):
{json.dumps(handoff, indent=2) if handoff is not None else "No implementation handoff is available."}

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
- Treat implementer summaries and supplied evidence metadata as claims, not verified evidence.
- Reuse an existing result only after verifying its primary artifact, actual executor/origin,
  exact tested checkpoint, command, working directory, dependency and environment identity,
  outcome, and limitations. Matching metadata alone is insufficient. Missing metadata is not equivalence.
- Do not repeat a covered check merely because another agent ran it. Explain repeats by changed
  inputs, unresolved failures, flakiness diagnosis, or a distinct platform/boundary.
- Runtime raw-report paths are controller-local, not files in this isolated checkout.
  A sandbox capability limit is not a product defect; request authorized execution or existing
  evidence when it materially prevents assurance. Never weaken sandboxing to obtain it.
- Do not edit production files.
- Ignore stylistic preference and low-value lint commentary unless it has credible impact.
- Classify severity separately from scope relevance.
- Adjacent/future/unrelated findings do not automatically enter current implementation.
- Use current_required for demonstrated unmet acceptance requirements, and current_blocking
  for demonstrated blockers. Suggestions are not requirements merely because of their severity.
- PASS only when no unresolved current_required/current_blocking finding remains at any severity
  and the implementation is sufficiently supported by evidence. Record authorized scope changes;
  do not silently reinterpret required behavior as an optional improvement.
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
        if type(payload.get(key)) is not type(expected_value) or payload[key] != expected_value:
            raise ForgeRunnerError(f"Reviewer returned stale or mismatched {key}.")
    if not isinstance(payload.get("verdict"), str) or payload["verdict"] not in VERDICTS:
        raise ForgeRunnerError("Reviewer returned an invalid verdict or summary.")
    if not isinstance(payload.get("summary"), str):
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
    finding_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ForgeRunnerError("Reviewer finding is not an object.")
        require_exact_keys(finding, finding_keys, "Review finding")
        if not isinstance(finding["id"], str) or not finding["id"]:
            raise ForgeRunnerError("Review finding ID is invalid.")
        if finding["id"] in finding_ids:
            raise ForgeRunnerError("Review finding IDs must be unique.")
        finding_ids.add(finding["id"])
        if (
            not isinstance(finding["severity"], str) or finding["severity"] not in SEVERITIES
            or not isinstance(finding["confidence"], str) or finding["confidence"] not in CONFIDENCE
        ):
            raise ForgeRunnerError("Review finding classification is invalid.")
        if not isinstance(finding["scope_relevance"], str) or finding["scope_relevance"] not in SCOPES:
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
            if evidence["kind"] not in ("code", "test", "runtime", "config", "requirement", "other"):
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
            if finding["scope_relevance"] in CURRENT_SCOPES
        ]
        if blocking:
            raise ForgeRunnerError("Reviewer returned PASS with unresolved blocking findings.")
    if payload["verdict"] == "CHANGES_REQUIRED" and not findings:
        raise ForgeRunnerError("Reviewer requested changes without identifying any findings.")


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
    seen = {(item.get("cycle"), str(item.get("id"))) for item in existing}
    for finding in findings:
        identity = (review["cycle"], str(finding.get("id")))
        if identity not in seen:
            existing.append({**finding, "cycle": review["cycle"]})
            seen.add(identity)
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


def assert_approval_current(root: Path, control_rel: Path, execution: dict[str, Any]) -> None:
    """Allow reconciliation metadata without carrying approval onto changed source."""
    reviewed = execution.get("reviewed_commit")
    if not isinstance(reviewed, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", reviewed):
        raise ForgeRunnerError("Approval is missing a valid reviewed checkpoint.")
    ancestry = run_local(["git", "merge-base", "--is-ancestor", reviewed, "HEAD"], root)
    changed = changed_files(root, reviewed, "HEAD") if ancestry.returncode == 0 else []
    changed.extend(worktree_changes(root))
    if ancestry.returncode != 0 or any(path != control_rel.as_posix() for path in changed):
        raise ForgeRunnerError("The source changed since approval. The current implementation needs a new review.")


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
    if type(number) is not int or number < 1 or number != execution.get("completed_reviews"):
        raise ForgeRunnerError("Cannot resume correction without a completed review.")
    checkpoint = execution.get("implementation_commit")
    if not isinstance(checkpoint, str) or not checkpoint:
        raise ForgeRunnerError("Cannot resume correction without its implementation checkpoint.")
    review = read_json(review_result_path(root, packet_id, number))
    validate_review_contract(
        review,
        packet_id=packet_id,
        baseline_revision=execution["baseline_revision"],
        plan_revision=execution["plan_revision"],
        packet_base=execution["packet_base_commit"],
        reviewed_commit=checkpoint,
        cycle=number,
    )
    if review["verdict"] != "CHANGES_REQUIRED":
        raise ForgeRunnerError("The saved review does not authorize an automatic correction.")
    return review


def correction_review_context(
    root: Path, packet_id: str, execution: dict[str, Any],
) -> dict[str, Any] | None:
    """Load the actual preceding review, validating its own checkpoint identity."""
    cycle = execution["review_cycle"]
    if cycle == 1:
        return None
    previous_cycle = cycle - 1
    if execution.get("last_completed_review") != previous_cycle:
        raise ForgeRunnerError("Correction review is missing its preceding completed review.")
    previous_path = review_result_path(root, packet_id, previous_cycle)
    if not previous_path.exists():
        # Older or partially retained runtime records can still receive a full
        # independent review; absent history must not masquerade as reviewed fixes.
        return None
    previous = read_json(previous_path)
    checkpoint = previous.get("reviewed_commit")
    if not isinstance(checkpoint, str) or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", checkpoint):
        raise ForgeRunnerError("Correction review has an invalid preceding checkpoint.")
    validate_review_contract(
        previous, packet_id=packet_id,
        baseline_revision=execution["baseline_revision"], plan_revision=execution["plan_revision"],
        packet_base=execution["packet_base_commit"], reviewed_commit=checkpoint, cycle=previous_cycle,
    )
    if previous["verdict"] != "CHANGES_REQUIRED" or not current_findings(previous):
        raise ForgeRunnerError("The preceding review does not identify a current-scope correction.")
    ancestry = run_local(
        ["git", "merge-base", "--is-ancestor", checkpoint, execution["implementation_commit"]], root,
    )
    if ancestry.returncode != 0:
        raise ForgeRunnerError("The correction checkpoint does not descend from the preceding review.")
    return previous


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
            "report_format": report.get("report_format", "legacy"),
            "normalization_issues": report.get("normalization_issues", []),
            "raw_report_path": report.get("raw_report_path"),
            "raw_report_sha256": report.get("raw_report_sha256"),
            "implementation_outcome": report.get("implementation_outcome", "unknown"),
            "report_origin": "implementer_claim",
            "validation_evidence": evidence_references(report["validation"], implementation_commit),
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
    packet_id = choose_packet(state, packet_id, require_eligible=False)
    execution = load_execution_state(root, state, packet_id, create=False)
    check_execution_control_path(root, packet_id, control_path.relative_to(root), execution)
    approval_issue: str | None = None
    if execution["phase"] == "approved":
        try:
            assert_approval_current(root, control_path.relative_to(root), execution)
            if revisions(state) != (execution["baseline_revision"], execution["plan_revision"]):
                raise ForgeRunnerError("The project plan changed since approval.")
        except ForgeRunnerError as exc:
            approval_issue = str(exc)
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
    if approval_issue:
        friendly = "holding a historical review; the current state needs a new review"
    print(f"{packet_id} is {friendly}.")
    if approval_issue:
        print(approval_issue)
    if execution.get("reason"):
        print(str(execution["reason"]))
    if verbose:
        print(json.dumps(execution, indent=2))
    return 2 if approval_issue else 0


def enforce_saved_execution_preferences(root: Path) -> None:
    """Honor explicit auth/live-probe policy without dispatching a probe."""
    saved = (root / ".claude/forge/project-preferences.json", runtime_path(root, "local-preferences.json"))
    if not any(path.exists() for path in saved):
        return
    result = run_local(
        [sys.executable, str(SCRIPT_DIR / "forge-preflight.py"), "--json", "--review"],
        root,
        timeout_s=150,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ForgeRunnerError("Saved external execution preferences could not be checked. Run `forge preflight --review`.") from exc
    if not isinstance(report, dict) or result.returncode not in {0, 1} or report.get("status") not in {"READY", "READY_WITH_WARNINGS"}:
        blockers = report.get("blockers", []) if isinstance(report, dict) else []
        detail = "; ".join(str(item) for item in blockers)[:700] if isinstance(blockers, list) else ""
        raise ForgeRunnerError(f"External execution preferences block this run. {detail}")
    for warning in report.get("warnings", []):
        print(f"WARNING: {warning}")


def run_packet(
    root: Path,
    control_path: Path,
    packet_id: str | None,
    profile: dict[str, Any],
    verbose: bool,
) -> int:
    validate_profile(profile)
    progress_verbose = verbose or profile["interaction"]["progress"] == "verbose"
    detail_verbose = verbose or profile["interaction"]["detail"] == "verbose"
    state = load_valid_control(root, control_path)
    packet_id = choose_packet(state, packet_id)
    check_execution_preconditions(state, packet_id)
    execution = load_execution_state(root, state, packet_id, create=False)
    control_rel = control_path.relative_to(root)
    check_execution_control_path(root, packet_id, control_rel, execution)
    execution["control_path"] = control_rel.as_posix()

    if execution["phase"] == "pending":
        if not repository_is_clean(root):
            raise ForgeRunnerError("Your project has uncommitted changes. Commit them before starting this Work Packet.")
        # A status query or rejected start must not pin an obsolete packet baseline.
        execution = new_execution_state(root, state, packet_id)
        execution["control_path"] = control_rel.as_posix()
        save_execution_state(root, packet_id, execution)
    elif revisions(state) != (execution["baseline_revision"], execution["plan_revision"]):
        execution["phase"] = "reconcile_required"
        execution["reason"] = "The requirements or plan revision changed since this execution started."
        save_execution_state(root, packet_id, execution)

    if execution["phase"] == "approved":
        assert_approval_current(root, control_rel, execution)
        print("Review already passed. Forge reconciliation is next.")
        if detail_verbose:
            print(f"Reviewed checkpoint: {execution['reviewed_commit']}")
            print(f"Execution evidence: {runtime_state_path(root, packet_id).relative_to(root)}")
        return 0
    if execution["phase"] == "escalated":
        print("This Work Packet needs your decision before it can continue.")
        if execution.get("reason"):
            print(str(execution["reason"]))
        return 2
    if execution["phase"] == "reconcile_required":
        print("The project plan changed during implementation. Reconcile it before review.")
        return 2

    enforce_saved_execution_preferences(root)
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
    packet_base = str(execution["packet_base_commit"])

    while True:
        phase = str(execution["phase"])
        if phase in {"pending", "implementing", "fixing"}:
            if execution["completed_reviews"] >= max_cycles:
                execution["phase"] = "escalated"
                execution["review_status"] = "cycle_limit"
                execution["reason"] = "The automatic review limit was reached."
                save_execution_state(root, packet_id, execution)
                print("The automatic review limit was reached. Your decision is needed.")
                return 2
            findings: list[dict[str, Any]] | None = None
            if phase == "fixing":
                previous = latest_completed_review(root, packet_id, execution)
                findings = current_findings(previous)
                if not findings:
                    raise ForgeRunnerError("Cannot resume correction without current-scope review findings.")
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
                if correction_review is not None:
                    if type(correction_review) is not int or correction_review != execution.get("last_completed_review"):
                        raise ForgeRunnerError("The saved correction review identity is invalid.")
                    findings = current_findings(latest_completed_review(root, packet_id, execution))
                    if not findings:
                        raise ForgeRunnerError("Cannot resume correction without current-scope review findings.")

            dispatch_state = load_valid_control(root, control_path)
            choose_packet(dispatch_state, packet_id)
            check_execution_preconditions(dispatch_state, packet_id)
            dispatch_revisions = revisions(dispatch_state)
            if dispatch_revisions != (execution["baseline_revision"], execution["plan_revision"]):
                execution["phase"] = "reconcile_required"
                execution["reason"] = "The requirements or plan revision changed before implementation dispatch."
                save_execution_state(root, packet_id, execution)
                print(execution["reason"])
                return 2
            previous_control_text = control_path.read_text(encoding="utf-8")
            before_head = git(root, "rev-parse", "HEAD")
            before_changes = worktree_fingerprint(root)

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
            if progress_verbose:
                print(f"Implementation attempt {execution['implementation_attempt']} started.")

            try:
                result = implementer.implement(
                    implementation_prompt(packet_id, dispatch_state, findings, control_rel),
                    root,
                )
            except AdapterError as exc:
                if exc.run is not None:
                    persist_implementation_report(
                        root, packet_id, execution["implementation_attempt"], exc.run.stdout,
                        implementation_outcome="adapter_failed",
                    )
                validate_control_after_agent(root, control_path, packet_id, previous_control_text)
                raise
            except (KeyboardInterrupt, SystemExit):
                validate_control_after_agent(root, control_path, packet_id, previous_control_text)
                raise
            report = persist_implementation_report(
                root, packet_id, execution["implementation_attempt"], result.stdout,
            )
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

            try:
                choose_packet(post_state, packet_id)
                check_execution_preconditions(post_state, packet_id)
                if post_state["work_packets"][packet_id].get("reconciled") is True:
                    raise ForgeRunnerError("The implementer marked the packet reconciled before independent review.")
            except ForgeRunnerError as exc:
                execution["phase"] = "reconcile_required"
                execution["reason"] = str(exc)
                save_execution_state(root, packet_id, execution)
                print(f"Forge project state needs reconciliation before review. {exc}")
                return 2

            after_changes = worktree_fingerprint(root)
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
            write_handoff(
                root,
                packet_id,
                post_state,
                packet_base,
                implementation_commit,
                next_cycle,
                report,
            )
            save_execution_state(root, packet_id, execution)
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
            previous_review = correction_review_context(root, packet_id, execution)
            execution["phase"] = "reviewing"
            save_execution_state(root, packet_id, execution)
            append_history(
                root,
                {"packet": packet_id, "phase": "reviewing", "cycle": cycle, "agent": reviewer.name},
                history_enabled,
            )
            if progress_verbose:
                print(f"Independent review cycle {cycle} started.")

            with isolated_review_checkout(root, reviewed_commit) as checkout:
                review_state = control_from_checkout(checkout, control_rel)
                review_baseline, review_plan = revisions(review_state)
                handoff_file = handoff_path(root, packet_id, cycle)
                result, review = reviewer.review(
                    reviewer_prompt(
                        packet_id,
                        review_state,
                        packet_base,
                        reviewed_commit,
                        cycle,
                        read_json(handoff_file) if handoff_file.exists() else None,
                        previous_review,
                    ),
                    checkout,
                    REVIEW_SCHEMA,
                )
                assert_review_target_unchanged(checkout, reviewed_commit)

            try:
                assert_review_target_unchanged(root, reviewed_commit)
            except ForgeRunnerError as exc:
                stale_path = runtime_path(root, "stale-reviews", f"{packet_id}-review-{cycle:02d}.json")
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
                print("Independent review passed. Reconcile requirement evidence before marking the Work Packet done.")
                if detail_verbose:
                    print(f"Reviewed checkpoint: {reviewed_commit}")
                    print(f"Review evidence: {review_result_path(root, packet_id, cycle).relative_to(root)}")
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
            if not progress_verbose:
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
        if args.command == "status":
            return status(root, control_path, args.packet, args.verbose)
        with execution_lock(root):
            if args.command == "doctor":
                return doctor(root, control_path, args.verbose)
            ensure_runtime_excluded(root)
            profile = load_profile(root)
            return run_packet(root, control_path, args.packet, profile, args.verbose)
    except KeyboardInterrupt:
        print("Forge was interrupted. Inspect status before retrying the Work Packet.", file=sys.stderr)
        return 130
    except (ForgeRunnerError, AdapterError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
