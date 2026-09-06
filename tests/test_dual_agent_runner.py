from __future__ import annotations

import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

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
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 2
    state = execution(repo, control)
    assert state["phase"] == "escalated"
    assert state["review_status"] == "stale"


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


@pytest.mark.parametrize("committed", [False, True])
def test_cached_approval_rejects_changed_source(tmp_path: Path, monkeypatch, committed: bool) -> None:
    repo, control = init_repo(tmp_path)
    install_fakes(monkeypatch, Implementer(), Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    (repo / "app.txt").write_text("unreviewed source\n", encoding="utf-8")
    if committed:
        git(repo, "add", "app.txt")
        git(repo, "commit", "-qm", "unreviewed")
    with pytest.raises(runner.ForgeRunnerError, match="changed since approval"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert runner.status(repo, control, "WP-1.1", False) == 2


def test_cached_approval_allows_control_reconciliation(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    install_fakes(monkeypatch, Implementer(), Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    state = json.loads(control.read_text(encoding="utf-8"))
    state["last_reconciliation"]["notes"] = "Reviewed evidence reconciled."
    control.write_text(json.dumps(state), encoding="utf-8")
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "reconcile")
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0


def test_status_and_rejected_start_do_not_capture_a_packet_baseline(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    assert runner.status(repo, control, "WP-1.1", False) == 0
    runtime = runner.runtime_state_path(repo, "WP-1.1")
    assert not runtime.exists()
    (repo / "app.txt").write_text("user preparation\n", encoding="utf-8")
    with pytest.raises(runner.ForgeRunnerError, match="uncommitted changes"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert not runtime.exists()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "prepare")
    expected_base = git(repo, "rev-parse", "HEAD")
    install_fakes(monkeypatch, Implementer(), Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    assert execution(repo, control)["packet_base_commit"] == expected_base


def test_interrupted_correction_recognizes_edits_to_already_dirty_file(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    def partial(cwd: Path, prompt: str, call: int) -> None:
        (cwd / "app.txt").write_text(f"attempt {call}\n", encoding="utf-8")
        if call == 2:
            raise runner.AdapterError("interrupted correction")

    install_fakes(monkeypatch, Implementer(partial), Reviewer(["CHANGES_REQUIRED"]))
    with pytest.raises(runner.AdapterError, match="interrupted correction"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert execution(repo, control)["phase"] == "implementing"

    def finish(cwd: Path, prompt: str, call: int) -> None:
        assert "Current-scope review findings" in prompt
        (cwd / "app.txt").write_text("correction complete\n", encoding="utf-8")

    review = Reviewer()
    install_fakes(monkeypatch, Implementer(finish), review)
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    assert review.calls == 1
    assert execution(repo, control)["completed_reviews"] == 2


def test_failed_implementer_preserves_last_valid_control_and_partial_source(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    original_control = control.read_text(encoding="utf-8")

    def fail(cwd: Path, prompt: str, call: int) -> None:
        control.write_text("{interrupted JSON", encoding="utf-8")
        (cwd / "app.txt").write_text("partial implementation\n", encoding="utf-8")
        raise runner.AdapterError("provider failed")

    install_fakes(monkeypatch, Implementer(fail), Reviewer())
    with pytest.raises(runner.ForgeRunnerError, match="last valid state was restored"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert control.read_text(encoding="utf-8") == original_control
    assert (repo / "app.txt").read_text(encoding="utf-8") == "partial implementation\n"
    assert execution(repo, control)["phase"] == "implementing"
    invalid = list((repo / runner.RUNTIME_DIR / "invalid-control").glob("*"))
    assert len(invalid) == 1
    assert invalid[0].read_text(encoding="utf-8") == "{interrupted JSON"


def test_changed_plan_on_resume_requires_reconciliation(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    saved = execution(repo, control)
    saved["phase"] = "implementing"
    runner.save_execution_state(repo, "WP-1.1", saved)
    state = json.loads(control.read_text(encoding="utf-8"))
    state["baseline_revision"] = 2
    state["work_packets"]["WP-1.1"]["baseline_revision"] = 2
    for gate in state["gates"].values():
        gate["baseline_revision"] = 2
    control.write_text(json.dumps(state), encoding="utf-8")
    install_fakes(monkeypatch, Implementer(lambda *_: pytest.fail("stale execution dispatched")), Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 2
    assert execution(repo, control)["phase"] == "reconcile_required"


def test_current_gate_does_not_authorize_a_stale_packet(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    state = json.loads(control.read_text(encoding="utf-8"))
    state["baseline_revision"] = 2
    for gate in state["gates"].values():
        gate["baseline_revision"] = 2
    control.write_text(json.dumps(state), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "revised baseline without packet reconciliation")
    install_fakes(monkeypatch, Implementer(lambda *_: pytest.fail("stale packet dispatched")), Reviewer())
    with pytest.raises(runner.ForgeRunnerError, match="does not match the current baseline and plan"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)


def test_implementer_cannot_reconcile_before_review(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    def reconcile(cwd: Path, prompt: str, call: int) -> None:
        state = json.loads(control.read_text(encoding="utf-8"))
        state["work_packets"]["WP-1.1"]["reconciled"] = True
        control.write_text(json.dumps(state), encoding="utf-8")

    reviewer = Reviewer()
    install_fakes(monkeypatch, Implementer(reconcile), reviewer)
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 2
    assert reviewer.calls == 0
    assert execution(repo, control)["phase"] == "reconcile_required"


def test_reviewer_must_not_change_isolated_checkout(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    def edit(checkout: Path, prompt: str, call: int) -> None:
        assert checkout != repo
        (checkout / "app.txt").write_text("reviewer changed source\n", encoding="utf-8")

    install_fakes(monkeypatch, Implementer(), Reviewer(action=edit))
    with pytest.raises(runner.ForgeRunnerError, match="changed while it was being reviewed"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert execution(repo, control)["phase"] == "reviewing"
    assert "reviewer changed source" not in (repo / "app.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("field", ["schema_version", "baseline_revision", "plan_revision", "cycle"])
def test_review_contract_rejects_boolean_identity(field: str) -> None:
    identity = {
        "packet_id": "WP-1.1", "baseline_revision": 1, "plan_revision": 1,
        "packet_base": "a" * 40, "reviewed_commit": "b" * 40, "cycle": 1,
    }
    payload = {"schema_version": 1, **identity, "base_commit": identity["packet_base"],
               "verdict": "PASS", "summary": "test", "findings": []}
    del payload["packet_base"]
    payload[field] = True
    with pytest.raises(runner.ForgeRunnerError, match="stale or mismatched"):
        runner.validate_review_contract(payload, **identity)


def test_changes_required_without_findings_cannot_become_approval(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)

    class EmptyReviewer(Reviewer):
        def review(self, prompt: str, cwd: Path, schema: Path):
            return FakeRun(), review_payload(prompt, "CHANGES_REQUIRED")

    install_fakes(monkeypatch, Implementer(), EmptyReviewer())
    with pytest.raises(runner.ForgeRunnerError, match="without identifying any findings"):
        runner.run_packet(repo, control, "WP-1.1", profile(), False)
    assert execution(repo, control)["phase"] != "approved"


@pytest.mark.parametrize("mutation", [
    lambda p: p.pop("history"),
    lambda p: p["interaction"].pop("detail"),
    lambda p: p["roles"]["implementer"].update(authentication="api-key"),
    lambda p: p["roles"]["reviewer"].update(api_key="must-not-be-accepted"),
    lambda p: p.update(version=True),
    lambda p: p.update(profile=""),
    lambda p: p["interaction"].update(detail=[]),
])
def test_profile_rejects_missing_unsupported_or_malformed_settings(mutation) -> None:
    candidate = profile()
    mutation(candidate)
    with pytest.raises(runner.ForgeRunnerError):
        runner.validate_profile(candidate)


def test_handoff_contract_and_custom_control_path(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    renamed = control.with_name("custom-state.json")
    control.rename(renamed)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "custom control")

    def implement(cwd: Path, prompt: str, call: int) -> None:
        assert ".claude/custom-state.json before editing" in prompt
        (cwd / "app.txt").write_text("implemented\n", encoding="utf-8")

    def inspect_handoff(checkout: Path, prompt: str, call: int) -> None:
        assert "Implementation handoff (unverified implementer claims" in prompt
        assert '"agent_report_structured": true' in prompt

    install_fakes(monkeypatch, Implementer(implement), Reviewer(action=inspect_handoff))
    assert runner.run_packet(repo, renamed, "WP-1.1", profile(), False) == 0
    handoff = json.loads(runner.handoff_path(repo, "WP-1.1", 1).read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "templates" / "implementation-handoff.schema.json").read_text(encoding="utf-8"))
    assert set(handoff) == set(schema["properties"])
    assert set(schema["required"]) <= set(handoff)
    assert handoff["agent_report_structured"] is True
    assert execution(repo, renamed)["control_path"] == ".claude/custom-state.json"


def test_malformed_implementation_evidence_is_not_labeled_structured() -> None:
    report = runner.parse_implementation_report(json.dumps({"result": json.dumps({
        "summary": "done", "acceptance_results": {"FR-001": True}, "validation": ["passed"],
        "discoveries": ["found"], "known_uncertainties": [False],
    })}))
    assert report["structured"] is False
    assert report["acceptance_results"] == {}
    assert report["validation"] == []
    assert report["discoveries"] == []
    assert report["known_uncertainties"] == []


def test_status_cannot_reuse_approval_for_another_control_file(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    alternate = control.with_name("alternate.json")
    other_state = base_state()
    other_state["requirements"]["FR-001"]["description"] = "A different requirement at the same revision"
    alternate.write_text(json.dumps(other_state), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "independent control state")
    install_fakes(monkeypatch, Implementer(), Reviewer())
    assert runner.run_packet(repo, alternate, "WP-1.1", profile(), False) == 0
    assert runner.status(repo, alternate, "WP-1.1", False) == 0
    with pytest.raises(runner.ForgeRunnerError, match="different Forge control-state path"):
        runner.status(repo, control, "WP-1.1", False)


@pytest.mark.parametrize("command", ["run", "status"])
def test_legacy_execution_is_bound_to_canonical_control(tmp_path: Path, command: str) -> None:
    repo, control = init_repo(tmp_path)
    alternate = control.with_name("alternate.json")
    alternate.write_text(control.read_text(encoding="utf-8"), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "second control path")
    saved = execution(repo, control)
    assert "control_path" not in saved
    with pytest.raises(runner.ForgeRunnerError, match="different Forge control-state path"):
        if command == "run":
            runner.run_packet(repo, alternate, "WP-1.1", profile(), False)
        else:
            runner.status(repo, alternate, "WP-1.1", False)


def test_changed_filenames_preserve_spaces_and_newlines(tmp_path: Path) -> None:
    repo, _ = init_repo(tmp_path)
    before = git(repo, "rev-parse", "HEAD")
    name = " spaced\nfilename.txt "
    (repo / name).write_text("new\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "odd filename")
    assert runner.changed_files(repo, before, "HEAD") == [name]


def test_status_can_inspect_an_inactive_packet(tmp_path: Path, monkeypatch) -> None:
    repo, control = init_repo(tmp_path)
    install_fakes(monkeypatch, Implementer(), Reviewer())
    assert runner.run_packet(repo, control, "WP-1.1", profile(), False) == 0
    state = json.loads(control.read_text(encoding="utf-8"))
    state["active_work_packets"] = []
    control.write_text(json.dumps(state), encoding="utf-8")
    assert runner.status(repo, control, "WP-1.1", True) == 0


@pytest.mark.parametrize("setting", ["detail", "progress"])
def test_profile_interaction_settings_control_output(tmp_path: Path, monkeypatch, capsys, setting: str) -> None:
    repo, control = init_repo(tmp_path)
    install_fakes(monkeypatch, Implementer(), Reviewer())
    configured = profile()
    configured["interaction"][setting] = "verbose"
    assert runner.run_packet(repo, control, "WP-1.1", configured, False) == 0
    output = capsys.readouterr().out
    assert ("Implementation attempt 1 started." in output) is (setting == "progress")
    assert ("Independent review cycle 1 started." in output) is (setting == "progress")
    assert ("Reviewed checkpoint:" in output) is (setting == "detail")
    assert ("Review evidence:" in output) is (setting == "detail")


def test_implementer_passes_project_prompt_through_stdin(tmp_path: Path, monkeypatch) -> None:
    from adapters import claude_code

    seen = {}

    def fake_command(command, **kwargs):
        seen.update(command=command, **kwargs)
        return FakeRun()

    monkeypatch.setattr(claude_code, "require_binary", lambda _: "claude")
    monkeypatch.setattr(claude_code, "run_command", fake_command)
    claude_code.ClaudeCodeImplementer().implement("sensitive project context", tmp_path)
    assert seen["stdin"] == "sensitive project context"
    assert "sensitive project context" not in seen["command"]


@pytest.mark.parametrize(("payload", "detail"), [
    ({"is_error": True, "errors": ["The configured model is unavailable."], "result": "generic failure"},
     "The configured model is unavailable."),
    ({"is_error": True, "result": "The configured model is unavailable."}, "The configured model is unavailable."),
    ({"is_error": True, "error": {"message": "The configured model is unavailable."}}, "The configured model is unavailable."),
    ({"type": "result", "subtype": "success", "is_error": True, "result": "Credit balance is too low"},
     "Credit balance is too low"),
])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_claude_structured_failure_is_reported_instead_of_startup_warning(
    tmp_path: Path, monkeypatch, payload: dict, detail: str, exit_code: int
) -> None:
    from adapters import claude_code

    result = FakeRun()
    result.stdout = json.dumps(payload)
    result.stderr = "[warning] An optional integration was disabled."
    result.returncode = exit_code
    monkeypatch.setattr(claude_code, "require_binary", lambda _: "claude")
    monkeypatch.setattr(claude_code, "run_command", lambda *args, **kwargs: result)
    with pytest.raises(runner.AdapterError) as error:
        claude_code.ClaudeCodeImplementer().implement("implement", tmp_path)
    assert str(error.value) == f"Claude Code implementation failed: {detail}"


@pytest.mark.parametrize(("stdout", "stderr", "expected"), [
    ("not JSON", "CLI could not start", "CLI could not start"),
    ("CLI returned a plain-text error", "", "CLI returned a plain-text error"),
    (json.dumps({"is_error": True, "errors": ["x" * 2000]}), "warning", "x" * 500),
])
def test_claude_error_detail_is_bounded_and_has_plain_text_fallbacks(
    tmp_path: Path, monkeypatch, stdout: str, stderr: str, expected: str
) -> None:
    from adapters import claude_code

    result = FakeRun()
    result.stdout, result.stderr, result.returncode = stdout, stderr, 1
    monkeypatch.setattr(claude_code, "require_binary", lambda _: "claude")
    monkeypatch.setattr(claude_code, "run_command", lambda *args, **kwargs: result)
    with pytest.raises(runner.AdapterError) as error:
        claude_code.ClaudeCodeImplementer().implement("implement", tmp_path)
    assert str(error.value) == f"Claude Code implementation failed: {expected}"


def test_reviewer_explicitly_disables_approval_escalation(tmp_path: Path, monkeypatch) -> None:
    from adapters import codex_cli

    seen = {}

    def fake_command(command, **kwargs):
        seen.update(command=command, **kwargs)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("{}", encoding="utf-8")
        return FakeRun()

    monkeypatch.setattr(codex_cli, "require_binary", lambda _: "codex")
    monkeypatch.setattr(codex_cli, "run_command", fake_command)
    codex_cli.CodexCLIReviewer().review("review prompt", tmp_path, ROOT / "templates/review-result.schema.json")
    command = seen["command"]
    assert command[:4] == ["codex", "--ask-for-approval", "never", "exec"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert seen["stdin"] == "review prompt"


@pytest.mark.skipif(os.name != "posix", reason="runner process-group isolation requires POSIX")
def test_timed_out_agent_cannot_leave_a_child_editing(tmp_path: Path) -> None:
    from adapters.base import AdapterError, run_command

    marker = tmp_path / "child-edit.txt"
    child = f"import time; from pathlib import Path; time.sleep(2); Path({str(marker)!r}).write_text('late edit')"
    parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(20)"
    with pytest.raises(AdapterError, match="timed out"):
        run_command([sys.executable, "-c", parent], cwd=tmp_path, timeout_s=1)
    time.sleep(1.5)
    assert not marker.exists()


@pytest.mark.skipif(os.name != "posix", reason="runner process-group isolation requires POSIX")
def test_sigterm_during_agent_startup_still_stops_child(tmp_path: Path, monkeypatch) -> None:
    from adapters import base

    original_popen = base.subprocess.Popen
    original_handler = signal.getsignal(signal.SIGTERM)
    children = []

    def interrupt_startup(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        os.kill(os.getpid(), signal.SIGTERM)
        return child

    monkeypatch.setattr(base.subprocess, "Popen", interrupt_startup)
    try:
        with pytest.raises(SystemExit) as error:
            base.run_command([sys.executable, "-c", "import time; time.sleep(20)"], cwd=tmp_path)
        assert error.value.code == 128 + signal.SIGTERM
        assert children[0].poll() is not None
        assert signal.getsignal(signal.SIGTERM) == original_handler
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate()


@pytest.mark.skipif(os.name != "posix", reason="runner process-group isolation requires POSIX")
def test_sigterm_stops_agent_children_before_releasing_runner_lock(tmp_path: Path) -> None:
    repo, control = init_repo(tmp_path)
    ready = tmp_path / "agent-ready"
    child = (
        f"import os, time; from pathlib import Path; Path({str(ready)!r}).write_text(str(os.getpid())); "
        f"time.sleep(1.5); Path({str(repo / 'app.txt')!r}).write_text('late agent edit')"
    )
    agent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(20)"
    invoke = f"""
import sys
sys.path.insert(0, {str(ROOT / 'tests')!r})
import test_dual_agent_runner as contracts
from adapters.base import run_command
class SlowImplementer(contracts.Implementer):
    def implement(self, prompt, cwd):
        return run_command([sys.executable, '-c', {agent!r}], cwd=cwd, timeout_s=20)
contracts.runner.ClaudeCodeImplementer = SlowImplementer
contracts.runner.CodexCLIReviewer = contracts.Reviewer
raise SystemExit(contracts.runner.main(['run', 'WP-1.1']))
"""
    process = subprocess.Popen([sys.executable, "-c", invoke], cwd=repo, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    group = None
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "local agent did not become ready"
        group = os.getpgid(int(ready.read_text(encoding="utf-8")))
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 128 + signal.SIGTERM, stdout + stderr
        with runner.execution_lock(repo):
            time.sleep(1.6)
            assert (repo / "app.txt").read_text(encoding="utf-8") == "base\n"
        assert execution(repo, control)["phase"] == "implementing"
    finally:
        if process.poll() is None:
            process.kill()
        if group is not None:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.communicate()


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
    blocked = subprocess.run([sys.executable, str(hook)], input=event, text=True, capture_output=True, check=False)
    assert blocked.returncode == 2
    runtime.write_text(
        json.dumps({"phase": "approved", "review_status": "passed", "reviewed_commit": git(repo, "rev-parse", "HEAD"),
                    "baseline_revision": 1, "plan_revision": 1}),
        encoding="utf-8",
    )
    allowed = subprocess.run([sys.executable, str(hook)], input=event, text=True, capture_output=True, check=False)
    assert allowed.returncode == 0
