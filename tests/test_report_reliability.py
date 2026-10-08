"""Report and correction-loop regressions; no live provider or credential use.

Runner integration below uses real Git checkpoints and fake adapters. Canonical
control validation is stubbed here; its independent existing suite is unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reliability_runner", ROOT / "scripts" / "forge-run.py")
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from implementation_report import REPORT_EXAMPLE, evidence_references  # noqa: E402


def report(**changes):
    return {"schema_version": 1, "summary": "implemented", "acceptance_results": {},
            "validation": [], "discoveries": [], "known_uncertainties": [], **changes}


def wrapped(value):
    return json.dumps({"result": json.dumps(value)})


def test_legacy_string_arrays_retain_all_claims():
    source = report(validation=[f"check {i}" for i in range(7)], discoveries=[f"discovery {i}" for i in range(6)])
    source.pop("schema_version")
    parsed = runner.parse_implementation_report(wrapped(source))
    assert parsed["validation"] == [{"claim": value} for value in source["validation"]]
    assert parsed["discoveries"] == [{"summary": value} for value in source["discoveries"]]
    assert not parsed["structured"]
    assert parsed["normalization_issues"]


def test_mixed_entries_do_not_discard_valid_siblings_or_invent_results():
    validation = [{"claim": "observed failure", "result": "failed"}, "tests passed", 9, None, {}]
    parsed = runner.parse_implementation_report(wrapped(report(validation=validation)))
    assert parsed["validation"] == [validation[0], {"claim": "tests passed"},
                                    {"unparsed_value": 9}, {"unparsed_value": None}, {}]
    assert parsed["raw_report"] == wrapped(report(validation=validation))
    assert parsed["normalization_issues"]


@pytest.mark.parametrize("source", ["start\n" + "x" * 7000, wrapped("not an object"), "{malformed", "null"])
def test_unstructured_output_is_preserved_without_truncation(source):
    parsed = runner.parse_implementation_report(source)
    assert parsed["raw_report"] == source
    assert parsed["report_format"] == "unstructured"
    assert not parsed["structured"]
    if source.startswith("start"):
        assert parsed["summary"] == source


@pytest.mark.parametrize("transport", [lambda value: json.dumps(value), wrapped,
                                       lambda value: wrapped_text("```json\n" + json.dumps(value) + "\n```")])
def test_direct_wrapped_and_fenced_reports(transport):
    source = copy.deepcopy(REPORT_EXAMPLE)
    parsed = runner.parse_implementation_report(transport(source))
    for field in ("summary", "acceptance_results", "validation", "discoveries", "known_uncertainties"):
        assert parsed[field] == source[field]
    assert parsed["report_format"] in {"structured", "normalized"}


def wrapped_text(text):
    return json.dumps({"result": text})


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"schema_version": 99}, {"summary": None},
    {"validation": [{}]}, {"discoveries": [{}]}, {"validation": {"check": "kept"}},
    {"known_uncertainties": [None, {"reason": "blocked"}]},
    {"validation": [{"claim": "check", "command": 12}]},
    {"validation": [{"claim": "check", "evidence": "wrong type"}]},
    {"validation": [{"claim": "check", "evidence": {"tested_commit": 123}}]},
])
def test_bad_contract_fields_are_explicit_not_structured(changes):
    source = wrapped(report(**changes))
    parsed = runner.parse_implementation_report(source)
    assert not parsed["structured"]
    assert parsed["normalization_issues"]
    assert parsed["raw_report"] == source


def test_acceptance_values_and_unknown_extension_survive():
    source = report(acceptance_results={"good": "passed", "odd": {"blocked": True}}, extension={"keep": [1, 2]})
    parsed = runner.parse_implementation_report(wrapped(source))
    assert parsed["acceptance_results"]["good"] == "passed"
    assert json.loads(parsed["acceptance_results"]["odd"]) == {"blocked": True}
    assert json.loads(json.loads(parsed["raw_report"])["result"])["extension"] == source["extension"]


def test_producer_example_and_parser_agree_with_schema():
    schema = json.loads((ROOT / "templates/implementation-report.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(REPORT_EXAMPLE, schema)
    assert runner.parse_implementation_report(json.dumps(REPORT_EXAMPLE))["structured"]
    assert runner.parse_implementation_report(wrapped(REPORT_EXAMPLE))["structured"]


def test_offline_recovery_never_dispatches_an_agent(tmp_path):
    original = tmp_path / "original.stdout.txt"
    original.write_text(wrapped(report(validation=["retained"])))
    before = original.read_bytes()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/implementation_report.py"), str(original)],
                            capture_output=True, text=True, env={**os.environ, "PATH": ""}, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["validation"] == [{"claim": "retained"}]
    assert original.read_bytes() == before
    assert list(tmp_path.iterdir()) == [original]


def evidence(commit):
    return {"reported_origin": "ci", "tested_commit": commit, "command": "pytest tests",
            "cwd": ".", "environment_identity": "linux-python3.12", "dependency_identity": "lock-sha",
            "result": "passed", "artifact": "ci-run:123/artifact:456"}


def test_evidence_matching_metadata_is_not_independent_verification():
    commit = "a" * 40
    entries = [{"claim": "passed", "evidence": evidence(commit)}]
    matching = evidence_references(entries, commit)[0]
    assert matching["applicability"] == "requires_verification"
    assert matching["trust"] == "unverified_implementer_supplied_reference"
    assert not matching["missing_fields"]
    assert evidence_references(entries, "b" * 40)[0]["applicability"] == "stale_checkpoint"
    del entries[0]["evidence"]["environment_identity"]
    missing = evidence_references(entries, commit)[0]
    assert missing["applicability"] == "incomplete_metadata"
    assert missing["missing_fields"] == ["environment_identity"]
    assert evidence_references([{"claim": "passed"}], commit) == []


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Forge Regression Test")
    git(root, "config", "user.email", "test@example.invalid")
    state = {"baseline_revision": 1, "plan_revision": 1, "active_work_packets": ["WP-1"],
             "work_packets": {"WP-1": {"status": "in_progress", "baseline_revision": 1, "plan_revision": 1,
                                       "dependencies": [], "reconciled": False}},
             "gates": {"plan_consistency": {"status": "passed", "baseline_revision": 1, "plan_revision": 1}}}
    control = root / ".claude/project-control.json"
    control.parent.mkdir()
    control.write_text(json.dumps(state))
    (root / "app.txt").write_text("base\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    runner.ensure_runtime_excluded(root)
    monkeypatch.setattr(runner, "validate_control", lambda root, path: runner.read_json(path))
    profile = {"version": 1, "profile": "dual-agent-local", "roles": {
        "implementer": {"adapter": "claude-code-cli", "authentication": "inherited"},
        "reviewer": {"adapter": "codex-cli", "authentication": "inherited", "write_access": False}},
        "review": {"max_cycles": 3, "checkpoint_required": True, "independent": True, "on_reviewer_unavailable": "stop"},
        "interaction": {"progress": "concise", "detail": "simple"}, "history": {"enabled": True}}
    return root, control, state, profile


def finding(scope="current_required", severity="Low"):
    return {"id": "REV-1", "severity": severity, "confidence": "High", "scope_relevance": scope,
            "title": "Required behavior is absent", "requirements": ["REQ-1"],
            "evidence": [{"kind": "code", "source": "app.txt", "location": None, "detail": "Missing behavior"}],
            "impact": "Acceptance fails", "root_cause": "Missing branch", "correction": "Implement branch",
            "validation": "Exercise missing branch"}


def review_payload(prompt, verdict="PASS", findings=None):
    def value(key):
        match = re.search(rf"^- {key}: ([^\n]+)", prompt, re.MULTILINE)
        assert match
        return match.group(1)
    return {"schema_version": 1, "packet_id": value("packet_id"), "base_commit": value("base_commit"),
            "reviewed_commit": value("reviewed_commit"), "baseline_revision": int(value("baseline_revision")),
            "plan_revision": int(value("plan_revision")), "cycle": int(value("cycle")),
            "verdict": verdict, "summary": "Evidence inspected", "findings": findings or []}


def validate(review):
    runner.validate_review_contract(review, packet_id=review["packet_id"],
                                    baseline_revision=review["baseline_revision"], plan_revision=review["plan_revision"],
                                    packet_base=review["base_commit"], reviewed_commit=review["reviewed_commit"], cycle=review["cycle"])


@pytest.mark.parametrize("scope", ["current_required", "current_blocking"])
@pytest.mark.parametrize("severity", ["Critical", "High", "Medium", "Low"])
def test_pass_cannot_hide_required_findings_at_any_severity(scope, severity):
    state = {"work_packets": {"WP-1": {}}, "baseline_revision": 1, "plan_revision": 1}
    prompt = runner.reviewer_prompt("WP-1", state, "a" * 40, "b" * 40, 1)
    with pytest.raises(runner.ForgeRunnerError, match="unresolved blocking findings"):
        validate(review_payload(prompt, findings=[finding(scope, severity)]))


@pytest.mark.parametrize("scope", ["adjacent", "future", "unrelated"])
@pytest.mark.parametrize("severity", ["Critical", "High", "Medium", "Low"])
def test_noncurrent_findings_do_not_become_mandatory(scope, severity):
    state = {"work_packets": {"WP-1": {}}, "baseline_revision": 1, "plan_revision": 1}
    prompt = runner.reviewer_prompt("WP-1", state, "a" * 40, "b" * 40, 1)
    validate(review_payload(prompt, findings=[finding(scope, severity)]))


class Implementer:
    name = "fake-implementer"

    def __init__(self, action=None):
        self.action, self.calls = action, 0
        self.output = wrapped(report(validation=["assertion retained"]))

    def doctor(self, root):
        return True, "ready"

    def implement(self, prompt, root):
        self.calls += 1
        if self.action:
            self.action(root)
        else:
            with (root / "app.txt").open("a") as handle:
                handle.write(f"implementation {self.calls}\n")
        return SimpleNamespace(stdout=self.output, duration_s=0.01, returncode=0)


class Reviewer:
    name = "fake-reviewer"

    def __init__(self, correction=False, interrupt_second=False):
        self.prompts = []
        self.correction = correction
        self.interrupt_second = interrupt_second

    def doctor(self, root):
        return True, "ready"

    def review(self, prompt, root, schema):
        self.prompts.append(prompt)
        assert runner.repository_is_clean(root)
        if self.interrupt_second and len(self.prompts) == 2:
            raise runner.AdapterError("transient review failure")
        change = self.correction and len(self.prompts) == 1
        payload = review_payload(prompt, "CHANGES_REQUIRED" if change else "PASS", [finding()] if change else [])
        return SimpleNamespace(duration_s=0.01), payload


def install(monkeypatch, implementer, reviewer):
    monkeypatch.setattr(runner, "ClaudeCodeImplementer", lambda: implementer)
    monkeypatch.setattr(runner, "CodexCLIReviewer", lambda: reviewer)


def originals(root):
    return sorted((root / runner.RUNTIME_DIR / "reports").glob("*.stdout.txt"))


def test_saved_output_is_private_untracked_and_unique_on_retry(project):
    root = project[0]
    raw = "Arabic العربية\r\n" + "unstructured " * 600 + "\udcff"
    records = [runner.persist_implementation_report(root, "WP-1", 1, raw) for _ in range(2)]
    assert len(originals(root)) == 2
    assert records[0]["raw_report_path"] != records[1]["raw_report_path"]
    for record in records:
        path = root / record["raw_report_path"]
        assert path.read_bytes() == raw.encode("utf-8", "surrogateescape")
        assert record["raw_report_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert "raw_report" not in json.loads(path.with_suffix(".json").read_text())
        if os.name == "posix":
            assert path.stat().st_mode & 0o077 == 0
    assert runner.repository_is_clean(root)


def test_raw_output_survives_parser_exception(project, monkeypatch):
    root = project[0]
    def fail(_):
        raise ValueError("parser defect")
    monkeypatch.setattr(runner, "parse_implementation_report", fail)
    with pytest.raises(ValueError, match="parser defect"):
        runner.persist_implementation_report(root, "WP-1", 1, "full original")
    assert originals(root)[0].read_text() == "full original"


def test_runtime_report_directory_cannot_escape(project, tmp_path):
    root = project[0]
    runtime = root / runner.RUNTIME_DIR
    runtime.mkdir(parents=True)
    (runtime / "reports").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(runner.ForgeRunnerError, match="runtime paths"):
        runner.persist_implementation_report(root, "WP-1", 1, "must stay local")


@pytest.mark.parametrize("failure", ["invalid_control", "revision_changed", "premature_reconciliation"])
def test_report_precedes_post_implementation_failure_paths(project, monkeypatch, failure):
    root, control, state, profile = project
    before = control.read_bytes()
    def action(_):
        if failure == "invalid_control":
            control.write_text("{broken")
        elif failure == "revision_changed":
            state["plan_revision"] = 2
            control.write_text(json.dumps(state))
        else:
            state["work_packets"]["WP-1"]["reconciled"] = True
            control.write_text(json.dumps(state))
    implementer, reviewer = Implementer(action), Reviewer()
    install(monkeypatch, implementer, reviewer)
    if failure == "invalid_control":
        with pytest.raises(runner.ForgeRunnerError, match="last valid state was restored"):
            runner.run_packet(root, control, "WP-1", profile, False)
        assert control.read_bytes() == before
    else:
        assert runner.run_packet(root, control, "WP-1", profile, False) == 2
    assert originals(root)[0].read_text() == implementer.output
    assert reviewer.prompts == []


def test_adapter_failure_retains_output_before_control_restoration(project, monkeypatch):
    from adapters.base import AgentRun
    root, control, _, profile = project
    before = control.read_bytes()
    raw = wrapped_text("partial work; provider stopped")
    run = AgentRun([], raw, "", 1, 0.1)
    def action(_):
        control.write_text("{bad")
        raise runner.AdapterError("provider failed", run=run)
    install(monkeypatch, Implementer(action), Reviewer())
    with pytest.raises(runner.ForgeRunnerError):
        runner.run_packet(root, control, "WP-1", profile, False)
    assert control.read_bytes() == before
    saved = originals(root)[0]
    assert saved.read_text() == raw
    assert json.loads(saved.with_suffix(".json").read_text())["implementation_outcome"] == "adapter_failed"


def test_claude_reported_failure_carries_original_run(tmp_path, monkeypatch):
    from adapters import claude_code
    from adapters.base import AgentRun
    run = AgentRun([], json.dumps({"is_error": True, "result": "partial output"}), "", 0, 0.1)
    monkeypatch.setattr(claude_code, "require_binary", lambda _: "claude")
    monkeypatch.setattr(claude_code, "run_command", lambda *args, **kwargs: run)
    with pytest.raises(runner.AdapterError) as caught:
        claude_code.ClaudeCodeImplementer().implement("task", tmp_path)
    assert caught.value.run is run


def test_correction_review_receives_prior_checkpoint_and_findings(project, monkeypatch):
    root, control, _, profile = project
    implementer, reviewer = Implementer(), Reviewer(correction=True, interrupt_second=True)
    install(monkeypatch, implementer, reviewer)
    with pytest.raises(runner.AdapterError, match="transient"):
        runner.run_packet(root, control, "WP-1", profile, False)
    assert implementer.calls == 2
    assert runner.run_packet(root, control, "WP-1", profile, False) == 0
    assert implementer.calls == 2  # Retrying review must not rerun implementation.
    first, second = [review_payload(prompt) for prompt in reviewer.prompts[:2]]
    assert first["reviewed_commit"] != second["reviewed_commit"]
    assert f"{first['reviewed_commit']}..{second['reviewed_commit']}" in reviewer.prompts[1]
    assert "Required behavior is absent" in reviewer.prompts[1]
    assert f"{first['base_commit']}..{second['reviewed_commit']}" in reviewer.prompts[1]
    assert len(originals(root)) == 2
    handoff = runner.read_json(runner.handoff_path(root, "WP-1", 2))
    assert handoff["report_origin"] == "implementer_claim"
    assert handoff["validation"] == [{"claim": "assertion retained"}]
    assert "raw_report" not in handoff
    jsonschema.validate(handoff, json.loads((ROOT / "templates/implementation-handoff.schema.json").read_text()))
    assert runner.repository_is_clean(root)


def test_handoff_does_not_infer_test_checkpoint(project, monkeypatch):
    root, control, _, profile = project
    initial = git(root, "rev-parse", "HEAD")
    implementer, reviewer = Implementer(), Reviewer()
    implementer.output = wrapped(report(validation=[{"claim": "passed", "evidence": evidence(initial)}]))
    install(monkeypatch, implementer, reviewer)
    assert runner.run_packet(root, control, "WP-1", profile, False) == 0
    handoff = runner.read_json(runner.handoff_path(root, "WP-1", 1))
    assert handoff["implementation_commit"] != initial
    assert handoff["validation_evidence"][0]["applicability"] == "stale_checkpoint"
    assert handoff["validation"][0]["evidence"]["tested_commit"] == initial


def test_no_change_correction_still_preserves_the_second_report(project, monkeypatch):
    root, control, _, profile = project
    install(monkeypatch, Implementer(lambda _: None), Reviewer(correction=True))
    assert runner.run_packet(root, control, "WP-1", profile, False) == 2
    assert len(originals(root)) == 2
    saved = runner.read_json(runner.runtime_state_path(root, "WP-1"))
    assert saved["phase"] == "escalated"
    assert saved["completed_reviews"] == 1


def test_missing_prior_review_falls_back_to_full_review(project):
    root, _, state, _ = project
    saved = runner.new_execution_state(root, state, "WP-1")
    saved.update(review_cycle=3, completed_reviews=2, last_completed_review=2,
                 implementation_commit=git(root, "rev-parse", "HEAD"))
    assert runner.correction_review_context(root, "WP-1", saved) is None


@pytest.mark.parametrize("field,value", [("packet_id", "WP-other"), ("cycle", 9), ("plan_revision", 2)])
def test_present_prior_review_with_wrong_identity_is_rejected(project, field, value):
    root, _, state, _ = project
    head = git(root, "rev-parse", "HEAD")
    prompt = runner.reviewer_prompt("WP-1", state, head, head, 1)
    previous = review_payload(prompt, "CHANGES_REQUIRED", [finding()])
    previous[field] = value
    runner.atomic_json(runner.review_result_path(root, "WP-1", 1), previous)
    saved = runner.new_execution_state(root, state, "WP-1")
    saved.update(review_cycle=2, completed_reviews=1, last_completed_review=1, implementation_commit=head)
    with pytest.raises(runner.ForgeRunnerError, match="stale or mismatched"):
        runner.correction_review_context(root, "WP-1", saved)


def test_old_handoff_still_validates_without_new_optional_fields():
    legacy = {"schema_version": 1, "packet_id": "WP-1", "baseline_revision": 1, "plan_revision": 1,
              "base_commit": "a" * 40, "implementation_commit": "b" * 40, "cycle": 1,
              "files_changed": [], "status": "READY_FOR_REVIEW"}
    jsonschema.validate(legacy, json.loads((ROOT / "templates/implementation-handoff.schema.json").read_text()))
