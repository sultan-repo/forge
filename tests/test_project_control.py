"""Malformed state and completion checks for the standalone downstream templates."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("control_validator", ROOT / "templates/validate-project-control.py")
assert spec and spec.loader
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
EXAMPLE = json.loads((ROOT / "templates/project-control.example.json").read_text())


@pytest.mark.parametrize("path", [
    ("active_work_packets",), ("active_milestones",), ("resume_queue",), ("plan_deltas",),
    ("archived_plan_deltas",), ("work_packets",), ("gates",), ("last_reconciliation",),
    ("requirements", "FR-001", "status"), ("requirements", "FR-001", "milestone"),
    ("work_packets", "WP-1.1", "dependencies"), ("work_packets", "WP-1.1", "requirements"),
    ("work_packets", "WP-1.1", "parent"), ("gates", "plan_consistency", "status"),
])
@pytest.mark.parametrize("invalid", [None, [None], [{}], True])
def test_malformed_shapes_report_errors_without_crashing(path, invalid):
    state = copy.deepcopy(EXAMPLE)
    node = state
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = invalid
    # A null milestone/parent is legal JSON shape; semantic parent checking still applies.
    errors, _ = validator.validate_state(state)
    if path == ("requirements", "FR-001", "milestone") and invalid is None:
        return
    assert errors


@pytest.mark.parametrize("field", ["baseline_revision", "plan_revision", "canonicalized_through_plan_revision"])
def test_booleans_are_not_revisions(field):
    state = copy.deepcopy(EXAMPLE)
    state[field] = True
    assert validator.validate_state(state)[0]


@pytest.mark.parametrize("field", ["baseline_id", "last_reconciliation"])
def test_schema_required_fields_are_checked(field):
    state = copy.deepcopy(EXAMPLE)
    del state[field]
    assert validator.validate_state(state)[0]


@pytest.mark.parametrize("relation", ["parent", "dependencies"])
def test_reference_cycles_are_rejected(relation):
    state = copy.deepcopy(EXAMPLE)
    for left, right in (("WP-1.1", "WP-1.2"), ("WP-1.2", "WP-1.1")):
        state["work_packets"][left][relation] = right if relation == "parent" else [right]
    assert any("cycle" in error for error in validator.validate_state(state)[0])


@pytest.mark.parametrize("delta", [
    {"id": ["PD-1"], "from_plan_revision": 1, "to_plan_revision": 2},
    {"id": " ", "from_plan_revision": 1, "to_plan_revision": 2},
    {"id": "PD-1", "from_plan_revision": 0, "to_plan_revision": 1},
    {"id": "PD-1", "from_plan_revision": -1, "to_plan_revision": 0},
])
def test_plan_delta_requires_text_identity_and_positive_revisions(delta):
    state = copy.deepcopy(EXAMPLE)
    state["plan_revision"] = 2
    state["plan_deltas"] = [delta]
    assert validator.validate_state(state)[0]


def test_session_orientation_survives_bad_arrays():
    spec = importlib.util.spec_from_file_location("orientation", ROOT / "templates/session-start-control.py")
    assert spec and spec.loader
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    state = copy.deepcopy(EXAMPLE)
    state.update(active_work_packets=None, resume_queue=3)
    assert "invalid; reconcile" in hook.orientation_message(state, "INVALID")


@pytest.fixture
def reviewed_project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    git("init", "-qb", "main")
    git("config", "user.name", "Forge test")
    git("config", "user.email", "test@example.invalid")
    git("config", "commit.gpgsign", "false")
    control = root / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"].update(acceptance_status="passed", validation_status="passed", reconciled=True)
    state["work_packets"]["WP-1.1"]["execution"] = {"profile": "dual-agent-local", "phase": "pending"}
    control.write_text(json.dumps(state))
    (root / "app.txt").write_text("reviewed source")
    git("add", "-A")
    git("commit", "-qm", "review checkpoint")
    runtime = root / ".claude/forge/runtime/executions/WP-1.1.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text(json.dumps({"phase": "approved", "review_status": "passed",
                                   "reviewed_commit": git("rev-parse", "HEAD"),
                                   "baseline_revision": 1, "plan_revision": 1}))
    return root, control, runtime, git


def completion(root):
    return subprocess.run([sys.executable, str(ROOT / "templates/task-completed-control.py")],
                          input=json.dumps({"cwd": str(root), "task_subject": "Complete WP-1.1"}),
                          text=True, capture_output=True, check=False)


def test_runtime_review_overrides_pending_opt_in(reviewed_project):
    assert completion(reviewed_project[0]).returncode == 0


@pytest.mark.parametrize("review_required", [False, True])
def test_completed_default_example_supports_optional_review(tmp_path, review_required):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    packet = state["work_packets"]["WP-1.1"]
    packet.update(acceptance_status="passed", validation_status="passed", reconciled=True)
    if review_required:
        packet["execution"] = {"review_required": True}
    control.write_text(json.dumps(state))
    result = completion(tmp_path)
    assert result.returncode == (2 if review_required else 0), result.stderr
    if review_required:
        assert "requires independent review" in result.stderr


@pytest.mark.parametrize("execution", [
    None, [], "dual-agent-local", 0,
    {"review_required": "true"}, {"review_required": "false"},
    {"review_required": 1}, {"review_required": None}, {"review_required": []},
])
@pytest.mark.parametrize("has_runtime", [False, True])
def test_malformed_review_policy_cannot_disable_completion_guard(reviewed_project, execution, has_runtime):
    root, control, runtime, _ = reviewed_project
    if not has_runtime:
        runtime.unlink()
    state = json.loads(control.read_text())
    state["work_packets"]["WP-1.1"]["execution"] = execution
    control.write_text(json.dumps(state))
    errors, _ = validator.validate_state(state)
    assert any("execution" in error for error in errors)
    # No installed validator: the completion hook must still fail closed.
    result = completion(root)
    assert result.returncode == 2, result.stderr
    assert "requires independent review" in result.stderr
    assert "Traceback" not in result.stderr


def test_explicit_false_review_policy_preserves_single_agent_completion(tmp_path):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"].update(
        acceptance_status="passed", validation_status="passed", reconciled=True,
        execution={"review_required": False},
    )
    control.write_text(json.dumps(state))
    assert not validator.validate_state(state)[0]
    result = completion(tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change", ["source", "staged", "commit", "untracked", "non_utf8_path", "revision", "malformed_runtime", "fictitious_commit", "wrong_packet", "implementation_only", "boolean_revision", "renamed_source", "wrong_control"])
def test_completion_rejects_stale_or_invalid_review(reviewed_project, change):
    root, control, runtime, git = reviewed_project
    if change in {"source", "staged", "commit"}:
        (root / "app.txt").write_text("unreviewed source")
        if change in {"staged", "commit"}:
            git("add", "app.txt")
        if change == "commit":
            git("commit", "-qm", "later edit")
    elif change == "untracked":
        (root / "new.py").write_text("unreviewed = True")
    elif change == "non_utf8_path":
        # A Git index can carry byte paths even where the filesystem requires UTF-8.
        name = os.fsdecode(b"unreviewed-\xff.txt")
        git("update-index", "--add", "--cacheinfo", f"100644,{git('rev-parse', 'HEAD:app.txt')},{name}")
    elif change == "revision":
        state = json.loads(control.read_text())
        state["plan_revision"] = 2
        control.write_text(json.dumps(state))
    elif change == "malformed_runtime":
        runtime.write_text("not JSON")
    elif change == "renamed_source":
        git("mv", "app.txt", ".claude/forge/runtime/renamed-source.txt")
    else:
        state = json.loads(runtime.read_text())
        if change == "wrong_packet":
            state["packet_id"] = "WP-1.2"
        elif change == "wrong_control":
            state["control_path"] = ".claude/another-project-control.json"
        elif change == "implementation_only":
            state["implementation_commit"] = state.pop("reviewed_commit")
        elif change == "boolean_revision":
            state["baseline_revision"] = True
        else:
            state["reviewed_commit"] = "f" * 40
        runtime.write_text(json.dumps(state))
    result = completion(root)
    assert result.returncode == 2, result.stderr
    assert "Traceback" not in result.stderr


def test_reconciliation_only_edits_keep_review_valid(reviewed_project):
    root, control, _, _ = reviewed_project
    state = json.loads(control.read_text())
    state["last_reconciliation"]["notes"] = "Evidence reconciled after review"
    control.write_text(json.dumps(state))
    assert completion(root).returncode == 0


def test_malformed_embedded_review_blocks_without_traceback(reviewed_project):
    root, control, runtime, _ = reviewed_project
    runtime.unlink()
    state = json.loads(control.read_text())
    state["work_packets"]["WP-1.1"]["execution"] = {"phase": []}
    control.write_text(json.dumps(state))
    result = completion(root)
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("subject", ["Complete WP-1.1 and WP-1.2", "Complete WP-1.1 and WP-unknown"])
def test_completion_checks_every_referenced_packet(tmp_path, subject):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"].update(acceptance_status="passed", validation_status="passed", reconciled=True)
    control.write_text(json.dumps(state))
    result = subprocess.run([sys.executable, str(ROOT / "templates/task-completed-control.py")],
                            input=json.dumps({"cwd": str(tmp_path), "task_subject": subject}),
                            text=True, capture_output=True, check=False)
    assert result.returncode == 2, result.stderr
    assert subject.split()[-1] in result.stderr


@pytest.mark.parametrize("hook_name", ["session-start-control", "task-completed-control"])
def test_hooks_use_project_root_when_session_cwd_is_nested(tmp_path, monkeypatch, hook_name):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"].update(acceptance_status="passed", validation_status="passed", reconciled=True)
    control.write_text(json.dumps(state))
    nested = tmp_path / "src"
    nested.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    result = subprocess.run([sys.executable, str(ROOT / "templates" / f"{hook_name}.py")],
                            input=json.dumps({"cwd": str(nested), "task_subject": "Complete WP-1.1"}),
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    if hook_name == "session-start-control":
        assert "Active work packets: WP-1.1" in json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("field", ["acceptance_status", "validation_status", "reconciled"])
def test_done_packet_cannot_contradict_recorded_completion(field):
    state = copy.deepcopy(EXAMPLE)
    packet = state["work_packets"]["WP-1.1"]
    packet.update(status="done", acceptance_status="passed", validation_status="passed", reconciled=True)
    packet[field] = False if field == "reconciled" else "pending"
    errors, _ = validator.validate_state(state)
    assert any(f"done contradicts {field}" in error for error in errors)


def test_legacy_completion_without_evidence_remains_readable_with_warnings():
    state = copy.deepcopy(EXAMPLE)
    state["requirements"]["FR-001"]["status"] = "satisfied"
    packet = state["work_packets"]["WP-1.1"]
    packet["status"] = "done"
    for key in ("acceptance_status", "validation_status", "reconciled"):
        packet.pop(key)
    errors, warnings = validator.validate_state(state)
    assert not errors
    assert any("satisfied without named evidence" in warning for warning in warnings)
    assert any("done without acceptance_status" in warning for warning in warnings)


@pytest.mark.parametrize("field", ["baseline_revision", "plan_revision"])
def test_packet_cannot_claim_a_future_revision(field):
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"][field] = 2
    assert any("exceeds the current" in error for error in validator.validate_state(state)[0])


@pytest.mark.parametrize("field", ["baseline_revision", "plan_revision"])
def test_completion_requires_current_packet_revision_even_without_validator(tmp_path, field):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"].update(acceptance_status="passed", validation_status="passed", reconciled=True)
    state[field] = 2
    control.write_text(json.dumps(state))
    result = completion(tmp_path)
    assert result.returncode == 2
    assert f"stale or invalid {field}" in result.stderr


@pytest.mark.parametrize("status", [[], "not_a_status", ""])
def test_malformed_packet_status_blocks_without_traceback(tmp_path, status):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    state = copy.deepcopy(EXAMPLE)
    state["work_packets"]["WP-1.1"].update(
        status=status, acceptance_status="passed", validation_status="passed", reconciled=True,
    )
    control.write_text(json.dumps(state))
    result = completion(tmp_path)
    assert result.returncode == 2
    assert "invalid status" in result.stderr
    assert "Traceback" not in result.stderr


def import_hook(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "templates" / f"{name}.py")
    assert spec and spec.loader
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


@pytest.mark.parametrize("failure", [OSError("cannot execute"), subprocess.TimeoutExpired("validator", 5)])
def test_hook_validator_failures_are_bounded_and_actionable(tmp_path, monkeypatch, failure):
    control = tmp_path / ".claude/project-control.json"
    control.parent.mkdir()
    control.write_text(json.dumps(EXAMPLE))
    validator_path = tmp_path / ".claude/hooks/validate-project-control.py"
    validator_path.parent.mkdir()
    validator_path.touch()
    def unavailable(*args, **kwargs):
        assert kwargs["timeout"] == 5
        raise failure
    monkeypatch.setattr(subprocess, "run", unavailable)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    orientation = import_hook("session-start-control")
    assert "not checked" in orientation.validate_control(tmp_path, control)
    completion_hook = import_hook("task-completed-control")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": str(tmp_path), "task_subject": "Complete WP-1.1"})))
    assert completion_hook.main() == 2


def test_session_orientation_surfaces_validation_warnings(tmp_path, monkeypatch):
    validator_path = tmp_path / ".claude/hooks/validate-project-control.py"
    validator_path.parent.mkdir(parents=True)
    validator_path.touch()
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args, 0, stdout="CONTROL VALID", stderr="CONTROL WARNING: requirement FR-1: satisfied without named evidence\n",
    ))
    result = import_hook("session-start-control").validate_control(tmp_path, tmp_path / "state.json")
    assert "satisfied without named evidence" in result
