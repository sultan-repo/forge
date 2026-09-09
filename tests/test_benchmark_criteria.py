from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_benchmark_harness import CORE, fixtures, reference, scorer

sys.path.insert(0, str(CORE))
import aggregate


def test_every_declared_hidden_test_has_a_unique_requirement_or_invariant() -> None:
    for scenario in scorer.SPEC:
        names = scorer.expected_tests(scenario)
        assert len(names) == len(set(names))
        assert all(scorer.requirement_id(name) or name.startswith("test_inv_") for name in names)
        assert not any("importorskip" in text for text in scorer.hidden_files(scenario).values())


@pytest.mark.parametrize("version,passes", [(None, False), ("v3.1", False), ("v4", True)])
def test_b3_handoff_must_use_the_current_criteria(
    tmp_path: Path, version: str | None, passes: bool,
) -> None:
    repo = fixtures.build("b3", tmp_path)
    reference(repo, "b3", "stage2")
    stage1 = {"pass": True}
    if version is not None:
        stage1["criteria_version"] = version
    result = scorer.score("b3", repo, {"rc": 0, "mock": True, "stage1_result": stage1}, scorer.parse_transcript(None))
    assert result["assertions"]["required_requirements_pass"]
    assert result["assertions"]["stage1_handoff_checks_pass_before_context_loss"] is passes
    assert result["pass"] is passes


@pytest.mark.parametrize("status", ["missing", "skipped", "error"])
def test_missing_required_test_cannot_hide_behind_its_passing_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    repo = fixtures.build("b1", tmp_path)
    reference(repo, "b1")
    hidden = scorer.run_hidden(repo, "b1")
    name = "test_req_2_1_quoted_newline_note_preserved"
    hidden["outcomes"].pop(name)
    hidden["statuses"].pop(name)
    if status != "missing":
        hidden["statuses"][name] = status
    monkeypatch.setattr(scorer, "run_hidden", lambda *_: hidden)
    result = scorer.score("b1", repo, {"rc": 0, "mock": True}, scorer.parse_transcript(None))
    assert not result["pass"]
    assert not result["requirements"]["status"]["2.1"]
    assert result["requirements"]["test_evidence"][name] == status


def test_missing_later_test_is_incomplete_evidence_without_failing_current_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = fixtures.build("b1", tmp_path)
    reference(repo, "b1")
    hidden = scorer.run_hidden(repo, "b1")
    name = "test_req_4_2_over_amount_exact_to_the_cent"
    hidden["outcomes"].pop(name)
    hidden["statuses"].pop(name)
    monkeypatch.setattr(scorer, "run_hidden", lambda *_: hidden)
    result = scorer.score("b1", repo, {"rc": 0, "mock": True}, scorer.parse_transcript(None))
    assert result["pass"], result["failed_assertions"]
    later = result["state_accuracy"]["later_milestones"]["M4"]
    assert not later["completed"] and not later["evidence_complete"]
    assert later["tests_missing_or_skipped"] == [name]
    assert result["state_accuracy"]["status"] == "review_required"


def test_relevant_four_file_header_change_is_not_a_process_failure(tmp_path: Path) -> None:
    repo = fixtures.build("b4", tmp_path)
    reference(repo, "b4")
    plan = repo / "docs/PLAN.md"
    plan.write_text(plan.read_text().replace("Monthly report YYYY-MM ($)", "Monthly report YYYY-MM (USD)"))
    with (repo / "docs/STATUS.md").open("a") as stream:
        stream.write("\nRequested report header updated; test_report checks the result.\n")
    result = scorer.score("b4", repo, {"rc": 0, "mock": True}, scorer.parse_transcript(None))
    assert result["pass"], result["failed_assertions"]
    assert result["bureaucracy"]["files_touched"] == 4
    assert result["process_review"]["status"] == "review_required"


def test_hidden_cli_contract_does_not_require_private_formatter_name(tmp_path: Path) -> None:
    repo = fixtures.build("b4", tmp_path)
    reference(repo, "b4")
    report = repo / "src/ledger/report.py"
    report.write_text(report.read_text().replace("format_report", "render_report"))
    hidden = scorer.run_hidden(repo, "b4")
    assert hidden["rc"] == 0, hidden["stdout_tail"]


def test_invariant_checks_include_persisted_add_path(tmp_path: Path) -> None:
    repo = fixtures.build("b2", tmp_path)
    hidden = scorer.run_hidden(repo, "b2")
    name = "test_inv_1_add_quantises_to_cents"
    assert hidden["statuses"][name] == "failure"
    reference(repo, "b2")
    hidden = scorer.run_hidden(repo, "b2")
    assert hidden["statuses"][name] == "passed"


@pytest.mark.parametrize("usage", [None, {}, {"models": {"example": {}}}, {"input_tokens": 10}])
def test_unknown_usage_is_not_a_zero_token_run(usage: object) -> None:
    assert scorer.total_tokens(usage) is None


@pytest.mark.parametrize("versions", [["v2-final"], [None], ["v4", "v3.1"]])
def test_aggregator_refuses_incompatible_criteria(tmp_path: Path, versions: list[str | None]) -> None:
    for index, version in enumerate(versions, 1):
        path = tmp_path / "b4/baseline" / f"run-{index}" / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"criteria_version": version}))
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"criteria_version": "v4"}))
    with pytest.raises(SystemExit, match="criteria versions"):
        aggregate.main(str(tmp_path))


def test_incomplete_matrix_does_not_get_headline_overhead(tmp_path: Path) -> None:
    repo = fixtures.build("b4", tmp_path / "fixture")
    reference(repo, "b4")
    result = scorer.score("b4", repo, {"rc": 0, "mock": True, "condition": "baseline", "run": 1}, scorer.parse_transcript(None))
    path = tmp_path / "results/b4/baseline/run-1/run.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(result))
    root = tmp_path / "results"
    (root / "MANIFEST.json").write_text(json.dumps({
        "criteria_version": "v4", "scenarios": "b4", "conditions": "baseline,forge", "runs_per_cell": 1,
    }))
    aggregate.main(str(root))
    report = (root / "REPORT.md").read_text()
    assert "INCOMPLETE" in report
    assert "complete matrix with both conditions is required" in report


def test_behavioral_spec_validator_rejects_duplicates_and_does_not_claim_execution() -> None:
    spec = importlib.util.spec_from_file_location("validate_evals", CORE.parent / "validate_evals.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    document = json.loads((CORE.parent / "adaptive-evals.json").read_text())
    assert module.validate(document, "adaptive") == 8
    document["evals"].append(document["evals"][0])
    with pytest.raises(ValueError, match="duplicate"):
        module.validate(document, "adaptive")
