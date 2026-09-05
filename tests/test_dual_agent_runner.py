from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "forge-run.py"
spec = importlib.util.spec_from_file_location("forge_runner", RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
sys.modules["forge_runner"] = runner
spec.loader.exec_module(runner)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def base_state() -> dict:
    return {
        "version": 3,
        "baseline_id": "RB-1",
        "baseline_revision": 1,
        "plan_revision": 1,
        "active_milestones": ["M1"],
        "active_work_packets": ["WP-1.1"],
        "resume_queue": [],
        "requirements": {
            "FR-001": {
                "status": "in_progress",
                "milestone": "M1",
                "work_packets": ["WP-1.1"],
                "evidence": [],
            }
        },
        "milestones": {"M1": {"status": "in_progress", "requirements": ["FR-001"]}},
        "work_packets": {
            "WP-1.1": {
                "status": "in_progress",
                "parent": "M1",
                "requirements": ["FR-001"],
                "baseline_revision": 1,
                "plan_revision": 1,
                "workstream": "core",
                "owner": "main",
                "dependencies": [],
                "return_to": "M1",
                "acceptance_status": "pending",
                "validation_status": "pending",
                "reconciled": False,
            }
        },
        "plan_deltas": [],
        "archived_plan_deltas": [],
        "canonicalized_through_plan_revision": 1,
        "gates": {
            "plan_consistency": {
                "status": "passed",
                "baseline_revision": 1,
                "plan_revision": 1,
                "notes": "test",
            },
            "convergence": {
                "status": "pending",
                "baseline_revision": 1,
                "plan_revision": 1,
                "notes": "test",
            },
        },
        "last_reconciliation": {
            "work_packet": None,
            "plan_revision": 1,
            "coverage_ok": True,
            "open_detours": [],
            "notes": "test",
        },
    }


def init_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Forge Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "forge@example.invalid"], cwd=repo, check=True)
    control = repo / ".claude" / "project-control.json"
    control.parent.mkdir(parents=True)
    control.write_text(json.dumps(base_state(), indent=2) + "\n", encoding="utf-8")
    (repo / "app.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    runner.ensure_runtime_excluded(repo)
    return repo, control


def profile(max_cycles: int = 3) -> dict:
    return {
        "version": 1,
        "profile": "dual-agent-local",
        "roles": {
            "implementer": {"adapter": "claude-code-cli", "authentication": "inherited"},
            "reviewer": {
                "adapter": "codex-cli",
                "authentication": "inherited",
                "write_access": False,
            },
        },
        "review": {
            "max_cycles": max_cycles,
            "checkpoint_required": True,
            "independent": True,
            "on_reviewer_unavailable": "stop",
        },
        "interaction": {"detail": "simple", "progress": "concise"},
        "history": {"enabled": True},
    }


def prompt_identity(prompt: str) -> dict[str, object]:
    def value(label: str) -> str:
        match = re.search(rf"- {label}: ([^\n]+)", prompt)
        assert match
        return match.group(1).strip()

    return {
        "packet_id": value("packet_id"),
        "baseline_revision": int(value("baseline_revision")),
        "plan_revision": int(value("plan_revision")),
        "base_commit": value("base_commit"),
        "reviewed_commit": value("reviewed_commit"),
        "cycle": int(value("cycle")),
    }


def finding(scope: str = "current_required", severity: str = "High") -> dict:
    return {
        "id": f"REV-{scope}-{severity}",
        "severity": severity,
        "confidence": "High",
        "scope_relevance": scope,
        "title": "test finding",
        "requirements": ["FR-001"],
        "evidence": [
            {"kind": "code", "source": "app.txt", "location": None, "detail": "test evidence"}
        ],
        "impact": "test impact",
        "root_cause": "test cause",
        "correction": "fix it",
        "validation": "test it",
    }


def review_payload(prompt: str, verdict: str = "PASS", findings: list[dict] | None = None) -> dict:
    return {
        "schema_version": 1,
        **prompt_identity(prompt),
        "verdict": verdict,
        "summary": "review summary",
        "findings": findings or [],
    }


class FakeRun:
    duration_s = 0.01

    def __init__(self) -> None:
        report = {
            "summary": "implemented",
            "acceptance_results": {},
            "validation": [],
            "discoveries": [],
            "known_uncertainties": [],
        }
        self.stdout = json.dumps({"result": json.dumps(report)})
        self.stderr = ""
        self.returncode = 0
        self.command: list[str] = []


class Implementer:
    name = "fake-implementer"

    def __init__(self, action=None) -> None:
        self.action = action
        self.calls = 0

    def doctor(self, cwd: Path) -> tuple[bool, str]:
        return True, "ready"

    def implement(self, prompt: str, cwd: Path) -> FakeRun:
        self.calls += 1
        if self.action:
            self.action(Path(cwd), prompt, self.calls)
        else:
            with (Path(cwd) / "app.txt").open("a", encoding="utf-8") as handle:
                handle.write("implemented\n")
        return FakeRun()


class Reviewer:
    name = "fake-reviewer"

    def __init__(self, verdicts=None, action=None) -> None:
        self.verdicts = list(verdicts or ["PASS"])
        self.action = action
        self.calls = 0

    def doctor(self, cwd: Path) -> tuple[bool, str]:
        return True, "ready"

    def review(self, prompt: str, cwd: Path, schema: Path):
        self.calls += 1
        if self.action:
            self.action(Path(cwd), prompt, self.calls)
        verdict = self.verdicts.pop(0)
        findings = [finding()] if verdict == "CHANGES_REQUIRED" else []
        return FakeRun(), review_payload(prompt, verdict, findings)


def install_fakes(monkeypatch, implementer: Implementer, reviewer: Reviewer) -> None:
    monkeypatch.setattr(runner, "ClaudeCodeImplementer", lambda: implementer)
    monkeypatch.setattr(runner, "CodexCLIReviewer", lambda: reviewer)


def execution(repo: Path, control: Path) -> dict:
    state = runner.load_valid_control(repo, control)
    return runner.load_execution_state(repo, state, "WP-1.1")


def test_review_schema_is_strict() -> None:
    schema = json.loads((ROOT / "templates" / "review-result.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"])
    item = schema["properties"]["findings"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["properties"]) == set(item["required"])
    evidence = item["properties"]["evidence"]["items"]
    assert evidence["additionalProperties"] is False
    assert set(evidence["properties"]) == set(evidence["required"])


def test_launcher_is_executable() -> None:
    assert os.access(ROOT / "scripts" / "forge", os.X_OK)


def test_linked_worktree_runtime_exclusion(tmp_path: Path) -> None:
    repo, _ = init_repo(tmp_path)
    worktree = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "linked", str(worktree)], cwd=repo, check=True)
    runner.ensure_runtime_excluded(worktree)
    raw = git(worktree, "rev-parse", "--git-path", "info/exclude")
    exclude = Path(raw) if Path(raw).is_absolute() else (worktree / raw).resolve()
    assert ".claude/forge/runtime/" in exclude.read_text(encoding="utf-8")


def test_canonical_requirement_evidence_survives(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    def act(cwd: Path, prompt: str, call: int) -> None:
        state = json.loads(control.read_text(encoding="utf-8"))
        state["requirements"]["FR-001"]["evidence"].append("impl-evidence")
        control.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        (cwd / "app.txt").write_text("implemented\n", encoding="utf-8")

    impl = Implementer(act)
    review = Reviewer()
    install_fakes(monkeypatch, impl, review)
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    state = json.loads(control.read_text(encoding="utf-8"))
    assert state["requirements"]["FR-001"]["evidence"] == ["impl-evidence"]


def test_external_change_during_review_is_not_approved(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    def external_change(checkout: Path, prompt: str, call: int) -> None:
        (repo / "external.txt").write_text("not reviewed\n", encoding="utf-8")

    install_fakes(monkeypatch, Implementer(), Reviewer(action=external_change))
    with pytest.raises(runner.ForgeRunnerError, match="changed while it was being reviewed"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert execution(repo, control)["phase"] != "approved"


def test_changed_source_on_resume_is_rejected(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    state = runner.new_execution_state(repo, runner.load_valid_control(repo, control), "WP-1.1")
    state.update({"phase": "reviewing", "implementation_commit": head, "review_cycle": 1})
    runner.save_execution_state(repo, "WP-1.1", state)
    (repo / "app.txt").write_text("changed after checkpoint\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "external change"], cwd=repo, check=True)
    install_fakes(monkeypatch, Implementer(), Reviewer())
    with pytest.raises(runner.ForgeRunnerError, match="changed while it was being reviewed"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)


def test_reviewer_failure_resumes_without_reimplementation(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    class FailingReviewer(Reviewer):
        def review(self, prompt: str, cwd: Path, schema: Path):
            self.calls += 1
            raise runner.AdapterError("review interrupted")

    impl = Implementer()
    install_fakes(monkeypatch, impl, FailingReviewer())
    with pytest.raises(runner.AdapterError):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert execution(repo, control)["phase"] == "reviewing"
    assert impl.calls == 1

    second_impl = Implementer(lambda *_: pytest.fail("implementation repeated"))
    install_fakes(monkeypatch, second_impl, Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    assert second_impl.calls == 0


def test_final_allowed_review_can_resume(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    state = runner.new_execution_state(repo, runner.load_valid_control(repo, control), "WP-1.1")
    state.update(
        {
            "phase": "reviewing",
            "implementation_attempt": 2,
            "review_cycle": 3,
            "completed_reviews": 2,
            "last_completed_review": 2,
            "implementation_commit": head,
        }
    )
    runner.save_execution_state(repo, "WP-1.1", state)
    impl = Implementer(lambda *_: pytest.fail("implementation repeated"))
    install_fakes(monkeypatch, impl, Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(max_cycles=3), False) == 0
    assert impl.calls == 0


@pytest.mark.parametrize("correction", ["untracked", "staged"])
def test_staged_or_untracked_correction_gets_next_review(
    tmp_path: Path, monkeypatch, correction: str
) -> None:
    repo, control = init_repo(tmp_path)

    def act(cwd: Path, prompt: str, call: int) -> None:
        if call == 1:
            (cwd / "app.txt").write_text("first implementation\n", encoding="utf-8")
        elif correction == "untracked":
            (cwd / "fix.py").write_text("fixed = True\n", encoding="utf-8")
        else:
            (cwd / "app.txt").write_text("fixed\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.txt"], cwd=cwd, check=True)

    impl = Implementer(act)
    review = Reviewer(verdicts=["CHANGES_REQUIRED", "PASS"])
    install_fakes(monkeypatch, impl, review)
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    assert execution(repo, control)["completed_reviews"] == 2
    assert review.calls == 2


def test_only_current_findings_enter_automatic_correction() -> None:
    review = {
        "findings": [
            finding("current_required"),
            finding("current_blocking"),
            finding("adjacent"),
            finding("future"),
            finding("unrelated"),
        ]
    }
    assert {item["scope_relevance"] for item in runner.current_findings(review)} == {
        "current_required",
        "current_blocking",
    }
    assert {item["scope_relevance"] for item in runner.deferred_findings(review)} == {
        "adjacent",
        "future",
        "unrelated",
    }


def test_high_adjacent_finding_is_surfaced(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, control = init_repo(tmp_path)

    class AdjacentReviewer(Reviewer):
        def review(self, prompt: str, cwd: Path, schema: Path):
            self.calls += 1
            return FakeRun(), review_payload(prompt, "PASS", [finding("adjacent", "High")])

    install_fakes(monkeypatch, Implementer(), AdjacentReviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    assert "serious issue(s) outside the current scope" in capsys.readouterr().out


def test_failed_plan_gate_blocks_dispatch(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    state = json.loads(control.read_text(encoding="utf-8"))
    state["gates"]["plan_consistency"]["status"] = "failed"
    control.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "failed gate"], cwd=repo, check=True)
    impl = Implementer(lambda *_: pytest.fail("implementation should not dispatch"))
    install_fakes(monkeypatch, impl, Reviewer())
    with pytest.raises(runner.ForgeRunnerError, match="not approved for implementation"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert impl.calls == 0


def test_task_guard_requires_completed_review(tmp_path: Path) -> None:
    repo, control = init_repo(tmp_path)
    state = json.loads(control.read_text(encoding="utf-8"))
    packet = state["work_packets"]["WP-1.1"]
    packet["acceptance_status"] = "passed"
    packet["validation_status"] = "passed"
    packet["reconciled"] = True
    control.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    runtime = repo / ".claude" / "forge" / "runtime" / "executions" / "WP-1.1.json"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text(
        json.dumps({"phase": "reviewing", "review_status": "pending", "implementation_commit": "abcdef123"}),
        encoding="utf-8",
    )
    event = json.dumps({"cwd": str(repo), "task_subject": "Complete WP-1.1"})
    hook = ROOT / "templates" / "task-completed-control.py"
    blocked = subprocess.run([sys.executable, str(hook)], input=event, text=True, capture_output=True)
    assert blocked.returncode == 2
    runtime.write_text(
        json.dumps({"phase": "approved", "review_status": "passed", "reviewed_commit": "abcdef123"}),
        encoding="utf-8",
    )
    allowed = subprocess.run([sys.executable, str(hook)], input=event, text=True, capture_output=True)
    assert allowed.returncode == 0
