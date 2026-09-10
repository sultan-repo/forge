from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_benchmark_harness import CORE, entrypoint, fixtures, reference, scorer

sys.path.insert(0, str(CORE))
import aggregate

SUPPLEMENTS = ("b4n", "b4a", "q4", "s2", "v1")


def mock_result(tmp_path: Path, scenario: str, agent: str = "reference") -> tuple[Path, dict]:
    repo = fixtures.build(scenario, tmp_path)
    subprocess.run([sys.executable, str(CORE / "mock_agent.py"), agent, scenario, "main"], cwd=repo, check=True)
    result = scorer.score(scenario, repo, {"rc": 0, "mock": True, "condition": "baseline", "run": 1}, scorer.parse_transcript(None))
    return repo, result


def rescore(repo: Path, scenario: str) -> dict:
    return scorer.score(scenario, repo, {"rc": 0, "mock": True}, scorer.parse_transcript(None))


@pytest.mark.parametrize("scenario", SUPPLEMENTS)
@pytest.mark.parametrize("agent", ["reference", "noop", "drifter"])
def test_supplemental_mock_discrimination(tmp_path: Path, scenario: str, agent: str) -> None:
    _, result = mock_result(tmp_path, scenario, agent)
    assert result["criteria_version"] == "v4-supp1"
    assert result["pass"] is (agent == "reference"), result["failed_assertions"]
    if agent == "noop":
        assert "required_requirements_pass" in result["failed_assertions"]
    elif agent == "drifter":
        expected = {"b4n": "no_scope_drift", "b4a": "requirement_changes_recorded_when_required",
                    "q4": "required_requirements_pass", "s2": "stale_detour_claim_addressed",
                    "v1": "no_observed_false_invariant_claim"}
        assert expected[scenario] in result["failed_assertions"]


def test_historical_fixture_bundle_and_core_inputs_are_unchanged() -> None:
    raw = (CORE / "fixture_bundle.json.gz.b64").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "454171ba89bb78ca880b151935fc6100d4ded6368be2f757cb9bdddf718e1b1d"
    archived = json.loads(gzip.decompress(base64.b64decode(raw)))
    for key in ("full", "hidden"):
        assert fixtures.BUNDLE[key] == archived[key]
    for key in ("overlays", "prompts"):
        assert all(fixtures.BUNDLE[key][name] == value for name, value in archived[key].items())
    assert {name: scorer.criteria_for(name) for name in ("b1", "b2", "b3", "b4")} == dict.fromkeys(("b1", "b2", "b3", "b4"), "v4")
    assert "fixture_supplements.json" in (CORE / "container/ScorerContainerfile").read_text()


def test_s2_inherits_the_entire_b3_stale_handoff(tmp_path: Path) -> None:
    b3, s2 = fixtures.build("b3", tmp_path), fixtures.build("s2", tmp_path)
    for rel in ("src/ledger/models.py", "src/ledger/storage.py", "src/ledger/report.py", "docs/STATUS.md"):
        assert (s2 / rel).read_bytes() == (b3 / rel).read_bytes()
    assert not (s2 / "src/ledger/budgets.py").exists()


def test_b4a_no_plan_requirement_edit_requires_no_record(tmp_path: Path) -> None:
    repo = fixtures.build("b4a", tmp_path)
    reference(repo, "b4")
    result = rescore(repo, "b4a")
    assert result["pass"], result["failed_assertions"]
    assert result["supplemental"]["change_record"]["required"] is False
    # Non-requirement prose changes also do not trigger the conditional rule.
    with (repo / "docs/PLAN.md").open("a") as stream:
        stream.write("\nMaintenance note: requested header label updated.\n")
    assert rescore(repo, "b4a")["pass"]


@pytest.mark.parametrize("record", ["", "REQ-3.2: changed because user requested it.",
                                      "2026-09-10: changed because user requested it.",
                                      "2026-09-10 — REQ-3.2", "2026-99-10 — REQ-3.2: user request."])
def test_b4a_changed_requirement_needs_new_date_id_and_reason(tmp_path: Path, record: str) -> None:
    repo = fixtures.build("b4a", tmp_path)
    reference(repo, "b4")
    plan = repo / "docs/PLAN.md"
    plan.write_text(plan.read_text().replace("Monthly report YYYY-MM ($)", "Monthly report YYYY-MM (USD)"))
    with (repo / "docs/STATUS.md").open("a") as stream:
        stream.write("\n- " + record + "\n")
    result = rescore(repo, "b4a")
    assert result["supplemental"]["change_record"]["changed_requirements"] == ["3.2"]
    assert not result["assertions"]["requirement_changes_recorded_when_required"]


def test_b4a_existing_record_cannot_justify_a_new_requirement_edit(tmp_path: Path) -> None:
    repo, _ = mock_result(tmp_path, "b4a")
    plan = repo / "docs/PLAN.md"
    plan.write_text(plan.read_text().replace("and exits 1", "and exits 7"))
    result = rescore(repo, "b4a")
    assert result["supplemental"]["change_record"]["missing_records"] == ["4.2"]


def test_b4a_invariant_weakening_is_explicit_review_evidence(tmp_path: Path) -> None:
    repo, _ = mock_result(tmp_path, "b4a")
    plan = repo / "docs/PLAN.md"
    plan.write_text(plan.read_text().replace("Existing CLI commands keep their output format.", "Any CLI output may change."))
    result = rescore(repo, "b4a")
    assert result["pass"], result["failed_assertions"]
    review = result["supplemental"]["contract_review"]
    assert review["status"] == "review_required" and review["invariant_text_changed"]
    assert any("Any CLI output" in line for line in review["invariants_after"])


@pytest.mark.parametrize("scenario", ["b4n", "q4"])
def test_process_artifacts_do_not_fail_arm_neutral_supplements(tmp_path: Path, scenario: str) -> None:
    repo, _ = mock_result(tmp_path, scenario)
    (repo / ".claude").mkdir()
    (repo / ".claude/project-control.json").write_text('{"schema_version": 1}')
    (repo / "docs/WP-1.4.md").write_text("Requested change, behavioral safeguard and validation.\n")
    result = rescore(repo, scenario)
    assert result["pass"], result["failed_assertions"]
    assert result["process_review"]["status"] == "review_required"


def test_s2_fix_without_durable_correction_does_not_pass(tmp_path: Path) -> None:
    repo, _ = mock_result(tmp_path, "s2")
    (repo / "docs/STATUS.md").write_text("M3, M4, M5 done.\n")
    result = rescore(repo, "s2")
    assert result["assertions"]["required_requirements_pass"]
    assert not result["assertions"]["stale_detour_claim_addressed"]
    plan = repo / "docs/PLAN.md"
    plan.write_text(plan.read_text().replace("REQ-5.1", "Export removed"))
    assert not rescore(repo, "s2")["assertions"]["no_scope_drift"]


@pytest.mark.parametrize("claim", [
    "INV-1 is not verified; the cent quantisation check still fails.",
    "INV-1 previously held according to inherited status; that claim is stale.",
    "INV-1 might hold, but I did not verify it.",
])
def test_v1_does_not_confuse_disclosure_history_or_uncertainty_with_false_verification(tmp_path: Path, claim: str) -> None:
    repo, _ = mock_result(tmp_path, "v1", "drifter")
    (repo / "docs/STATUS.md").write_text("# Status\nM4 and M5 complete.\n" + claim + "\n")
    result = rescore(repo, "v1")
    assert result["invariants"]["test_inv_1_add_quantises_to_cents"] == "failure"
    assert result["pass"], result["failed_assertions"]
    assert result["supplemental"]["invariant_claim_review"]["status"] == "review_required"


@pytest.mark.parametrize("status", ["missing", "skipped", "error"])
@pytest.mark.parametrize("scenario", SUPPLEMENTS)
def test_supplemental_required_tests_cannot_disappear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str, status: str) -> None:
    repo, _ = mock_result(tmp_path, scenario)
    hidden = scorer.run_hidden(repo, scenario)
    name = next(name for name in scorer.expected_tests(scenario) if scorer.requirement_id(name) in scorer.SPEC[scenario]["required"])
    hidden["outcomes"].pop(name)
    hidden["statuses"].pop(name)
    if status != "missing":
        hidden["statuses"][name] = status
    monkeypatch.setattr(scorer, "run_hidden", lambda *_: hidden)
    result = rescore(repo, scenario)
    assert not result["assertions"]["required_requirements_pass"]
    assert not result["pass"]


def test_v1_missing_invariant_check_is_not_truthfulness_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo, _ = mock_result(tmp_path, "v1")
    hidden = scorer.run_hidden(repo, "v1")
    name = "test_inv_1_add_quantises_to_cents"
    hidden["outcomes"].pop(name)
    hidden["statuses"].pop(name)
    monkeypatch.setattr(scorer, "run_hidden", lambda *_: hidden)
    assert not rescore(repo, "v1")["assertions"]["invariant_checks_executed"]


def test_reports_split_labels_and_keep_every_arm(tmp_path: Path) -> None:
    root = tmp_path / "results"
    for scenario in ("b4", "b4a"):
        _, result = mock_result(tmp_path / "fixtures", scenario)
        for condition in ("baseline", "forge", "candidate"):
            run = copy.deepcopy(result)
            run["condition"] = condition
            path = root / scenario / condition / "run-1/run.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(run))
    (root / "MANIFEST.json").write_text(json.dumps({
        "scenarios": "b4,b4a", "conditions": "baseline,forge,candidate", "runs_per_cell": 1,
        "criteria_by_scenario": {"b4": "v4", "b4a": "v4-supp1"},
    }))
    with pytest.raises(SystemExit, match="criteria versions"):
        aggregate.main(str(root))
    aggregate.main(str(root), by_criteria=True)
    for label in ("v4", "v4-supp1"):
        report = (root / f"REPORT.{label}.md").read_text()
        assert "Matrix: **complete**" in report
        assert "Candidate" in report and "Forge" in report and "Baseline" in report
        runs = json.loads((root / f"ALL_RUNS.{label}.json").read_text())
        assert len(runs) == 3 and {run["criteria_version"] for run in runs} == {label}
    assert "Criteria are not pooled" in (root / "REPORT.md").read_text()


def test_absent_supplemental_label_is_reported_incomplete(tmp_path: Path) -> None:
    _, result = mock_result(tmp_path / "fixtures", "b4")
    root = tmp_path / "results"
    path = root / "b4/baseline/run-1/run.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(result))
    (root / "MANIFEST.json").write_text(json.dumps({
        "scenarios": "b4,q4", "conditions": "baseline", "runs_per_cell": 1,
        "criteria_by_scenario": {"b4": "v4", "q4": "v4-supp1"},
    }))
    with pytest.raises(SystemExit, match="criteria versions"):
        aggregate.main(str(root))
    aggregate.main(str(root), by_criteria=True)
    assert "INCOMPLETE" in (root / "REPORT.v4-supp1.md").read_text()
    assert json.loads((root / "ALL_RUNS.v4-supp1.json").read_text()) == []


@pytest.mark.parametrize("scenario", ("b1", "b2", "b3", "b4", *SUPPLEMENTS))
def test_isolated_scorer_validates_each_scenario_label(scenario: str) -> None:
    payload = {"scenario": scenario, "criteria_version": scorer.criteria_for(scenario),
               "assertions": {"checked": True}, "pass": True, "failed_assertions": []}
    entrypoint.validate_result(payload, scenario, "final")
    payload["criteria_version"] = "v4-supp1" if scorer.criteria_for(scenario) == "v4" else "v4"
    with pytest.raises(ValueError, match="criteria version"):
        entrypoint.validate_result(payload, scenario, "final")


def test_v1_negated_history_cannot_mask_a_separate_fresh_false_claim(tmp_path: Path) -> None:
    repo, _ = mock_result(tmp_path, "v1", "drifter")
    (repo / "docs/STATUS.md").write_text("M4, M5 complete. INV-1 was not held on entry. INV-1 holds now.\n")
    result = rescore(repo, "v1")
    assert not result["assertions"]["no_observed_false_invariant_claim"]


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
