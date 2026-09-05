"""Malformed state and completion checks for the standalone downstream templates."""
from __future__ import annotations

import copy
import importlib.util
import json
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


def test_runtime_review_overrides_example_pending_extension(reviewed_project):
    assert completion(reviewed_project[0]).returncode == 0


@pytest.mark.parametrize("change", ["source", "staged", "commit", "untracked", "revision", "malformed_runtime", "fictitious_commit", "wrong_packet", "implementation_only", "boolean_revision", "renamed_source", "wrong_control"])
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
    assert completion(root).returncode == 2


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
