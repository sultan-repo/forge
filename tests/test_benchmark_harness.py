from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[1] / "evals" / "core"
sys.path.insert(0, str(CORE))
scorer = importlib.import_module("assert_run")
fixtures = importlib.import_module("build_fixtures")
containers = importlib.import_module("container_run")
entrypoint = importlib.import_module("score_entrypoint")


def harness(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    env["BENCH_MOCK_AGENT"] = "reference"
    return subprocess.run(
        ["bash", str(CORE / "run.sh"), *arguments], cwd=cwd, env=env,
        capture_output=True, text=True, timeout=90, check=False,
    )


def reference(repo: Path, scenario: str, stage: str = "main") -> None:
    subprocess.run(
        [sys.executable, str(CORE / "mock_agent.py"), "reference", scenario, stage],
        cwd=repo, check=True,
    )


@pytest.mark.parametrize("arguments", [
    ["--runs", "0"], ["--runs", "-1"], ["--runs", "nan"],
    ["--scenarios", "b5"], ["--scenarios", "b1,b1"],
    ["--conditions", "baseline,unknown"], ["--conditions", "forge,forge"], ["--out"],
])
def test_invalid_matrix_is_rejected_before_output(arguments: list[str], tmp_path: Path) -> None:
    completed = harness(arguments, tmp_path)
    assert completed.returncode != 0
    assert not list(tmp_path.iterdir())


def test_output_directory_preserves_existing_evidence(tmp_path: Path) -> None:
    out = tmp_path / "evidence"
    out.mkdir()
    sentinel = out / "MANIFEST.json"
    sentinel.write_text("previous result", encoding="utf-8")
    completed = harness(["--runs", "1", "--out", "evidence"], tmp_path)
    assert completed.returncode != 0
    assert "must be empty" in completed.stderr
    assert sentinel.read_text(encoding="utf-8") == "previous result"


def test_parallel_matrices_have_separate_fixtures_and_stable_order(tmp_path: Path) -> None:
    args = ["--scenarios", "b4", "--conditions", "baseline,forge", "--runs", "1"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(harness, [*args, "--out", name], tmp_path) for name in ("first", "second")]
        for future in futures:
            result = future.result()
            assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "first/RUN_ORDER.tsv").read_bytes() == (tmp_path / "second/RUN_ORDER.tsv").read_bytes()
    for name in ("first", "second"):
        out = tmp_path / name
        assert (out / "fixtures/b4/.git").is_dir()
        assert not (out / ".running").exists()
        runs = list(out.glob("b4/*/run-1/run.json"))
        assert len(runs) == 2
        assert all(json.loads(run.read_text())["pass"] for run in runs)


def test_hidden_tests_ignore_candidate_hooks_settings_and_pytest_shadow(tmp_path: Path) -> None:
    repo = fixtures.build("b4", tmp_path)
    (repo / "conftest.py").write_text("raise RuntimeError('candidate hook loaded')\n", encoding="utf-8")
    (repo / "pytest.py").write_text("raise RuntimeError('pytest shadow loaded')\n", encoding="utf-8")
    with (repo / "pyproject.toml").open("a", encoding="utf-8") as stream:
        stream.write('\naddopts = "--ignore-glob=*"\n')
    before = scorer.run_hidden(repo, "b4")
    assert before["rc"] == 1
    assert scorer.req_status(before["outcomes"])["B4"] is False
    reference(repo, "b4")
    after = scorer.run_hidden(repo, "b4")
    assert after["rc"] == 0
    assert scorer.req_status(after["outcomes"])["B4"] is True
    assert not list(repo.glob(".bench_hidden*"))


@pytest.mark.parametrize("overrides,transcript_success", [
    ({"rc": 1}, True), ({"timed_out": True}, True), ({"rc": 124}, True), ({}, False),
])
def test_successful_artifacts_cannot_hide_failed_agent(
    tmp_path: Path, overrides: dict, transcript_success: bool,
) -> None:
    repo = fixtures.build("b4", tmp_path)
    reference(repo, "b4")
    meta = {"rc": 0, "timed_out": False, **overrides}
    transcript = {**scorer.parse_transcript(None), "result_success": transcript_success}
    result = scorer.score("b4", repo, meta, transcript)
    assert result["assertions"]["required_requirements_pass"]
    assert not result["pass"]
    assert "agent_completed" in result["failed_assertions"]


def test_hidden_runner_error_cannot_pass_partial_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = fixtures.build("b4", tmp_path)
    reference(repo, "b4")
    hidden = scorer.run_hidden(repo, "b4")
    hidden["rc"] = 2
    monkeypatch.setattr(scorer, "run_hidden", lambda *_args: hidden)
    result = scorer.score("b4", repo, {"rc": 0, "mock": True}, scorer.parse_transcript(None))
    assert result["assertions"]["required_requirements_pass"]
    assert not result["pass"]
    assert "hidden_runner_completed" in result["failed_assertions"]


def test_b3_handoff_must_correct_inherited_false_fix_claim(tmp_path: Path) -> None:
    repo = fixtures.build("b3", tmp_path)
    with (repo / "docs/STATUS.md").open("a", encoding="utf-8") as stream:
        stream.write("\nInvestigation started.\n")
    meta = {"rc": 0, "mock": True}
    transcript = scorer.parse_transcript(None)
    before = scorer.score_b3_stage1(repo, meta, transcript)
    assert not before["pass"]
    assert "stage1_stale_fix_claim_corrected" in before["failed_assertions"]
    reference(repo, "b3", "stage1")
    after = scorer.score_b3_stage1(repo, meta, transcript)
    assert after["pass"], after["failed_assertions"]


def test_result_error_is_not_success_even_with_zero_cli_exit(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    path.write_text(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True}), encoding="utf-8")
    parsed = scorer.parse_transcript(path)
    assert not scorer.agent_completed({"rc": 0}, parsed)


def test_container_deadline_removes_container(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    log = tmp_path / "calls.jsonl"
    runtime.write_text(
        f"#!{sys.executable}\nimport json,sys,time\n"
        f"with open({str(log)!r}, 'a') as stream: stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1] == 'run': time.sleep(60)\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    assert containers.run_container(str(runtime), 2, ["image", "command"]) == 124
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0][:2] == ["run", "--name"]
    assert calls[1] == ["rm", "-f", calls[0][2]]


@pytest.mark.parametrize("payload", [
    {"scenario": "b4", "pass": True},
    {"scenario": "b4", "pass": True, "assertions": {}, "failed_assertions": []},
    {"scenario": "b4", "pass": True, "assertions": {"test": False}, "failed_assertions": ["test"]},
    {"scenario": "b4", "pass": "true", "assertions": {"test": True}, "failed_assertions": []},
])
def test_scorer_result_must_agree_with_assertions(payload: dict) -> None:
    with pytest.raises(ValueError):
        entrypoint.validate_result(payload, "b4", "final")


@pytest.mark.parametrize("result,is_error", [
    ("Did not activate; expected FORGE_ACTIVE:99.88.77", False),
    ("FORGE_ACTIVE:99.88.77", True),
])
def test_activation_requires_exact_success_without_disclosing_version(
    tmp_path: Path, result: str, is_error: bool,
) -> None:
    package = tmp_path / "candidate"
    (package / "scripts").mkdir(parents=True)
    (package / "scripts/validate-skill-package.py").write_text("", encoding="utf-8")
    (package / "VERSION").write_text("99.88.77\n", encoding="utf-8")
    (package / "SKILL.md").write_text("Test candidate", encoding="utf-8")
    (package / "evals/core").mkdir(parents=True)
    (package / "evals/core/fixture_bundle.json.gz.b64").write_text("hidden reference solution", encoding="utf-8")
    (package / "tests").mkdir()
    (package / "tests/test_secret.py").write_text("hidden scorer regression", encoding="utf-8")
    runtime = tmp_path / "fake-runtime"
    prompt_log = tmp_path / "preflight-prompt.txt"
    event = {"type": "result", "subtype": "error" if is_error else "success", "is_error": is_error, "result": result}
    runtime.write_text(
        f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\na=sys.argv[1:]\n"
        "if a[0] == 'image' and '--format' in a: print('sha256:fixture')\n"
        "elif a[0] == 'run':\n"
        "    if '--version' in a: print('test-claude')\n"
        "    elif '-p' in a:\n"
        f"        Path({str(prompt_log)!r}).write_text(a[a.index('-p')+1])\n"
        f"        print({json.dumps(event)!r})\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": str(Path(sys.executable).parent) + os.pathsep + env["PATH"],
        "BENCH_MOCK_AGENT": "", "BENCH_CONTAINER_RUNTIME": str(runtime),
        "FORGE_DIR": "candidate", "ALLOW_UNVERIFIED_FORGE": "1",
        "ANTHROPIC_API_KEY": "test-only-no-network", "COPY_CREDENTIALS": "0",
    })
    completed = subprocess.run(
        ["bash", str(CORE / "run.sh"), "--scenarios", "b4", "--conditions", "forge", "--runs", "1", "--out", "results"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode != 0
    assert "preflight failed" in completed.stderr
    assert "99.88.77" not in prompt_log.read_text()
    assert not (tmp_path / "results/forge-activation.log").exists()
    installed = tmp_path / "results/forge-activation-preflight/config/skills/forge"
    assert (installed / "SKILL.md").read_text() == "Test candidate"
    assert not (installed / "evals").exists()
    assert not (installed / "tests").exists()


def extract_release(source: Path, destination: Path) -> subprocess.CompletedProcess[str]:
    # Exercise the exact extraction program used by the verified release branch.
    marker = '  python3 - "$rel_dir/$asset" "$unpack" <<\'PY\'\n'
    program = (CORE / "run.sh").read_text(encoding="utf-8").split(marker, 1)[1].split("\nPY\n", 1)[0]
    return subprocess.run(
        [sys.executable, "-", str(source), str(destination)], input=program,
        text=True, capture_output=True, check=False,
    )


def test_release_extraction_preserves_launchers_and_passes_package_validation(tmp_path: Path) -> None:
    root = CORE.parents[1]
    archive_path = tmp_path / "forge-release.zip"
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root,
    ).decode().split("\0")
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in names:
            source = root / name
            if not name or not source.is_file():
                continue
            info = zipfile.ZipInfo("forge/" + name)
            info.create_system = 3
            # git archive stores Unix regular-file mode in external_attr.
            permissions = stat.S_IMODE(source.stat().st_mode)
            if name == "scripts/forge":
                permissions |= stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX
            info.external_attr = (stat.S_IFREG | permissions) << 16
            archive.writestr(info, source.read_bytes())
    destination = tmp_path / "unpacked"
    extracted = extract_release(archive_path, destination)
    assert extracted.returncode == 0, extracted.stderr
    package = destination / "forge"
    for name in ("forge", "bootstrap.sh", "install.sh"):
        mode = (package / "scripts" / name).stat().st_mode
        assert mode & stat.S_IXUSR, f"{name} lost its executable mode"
        assert not mode & 0o7000, "archive special permissions must not be restored"
    assert not (package / "VERSION").stat().st_mode & 0o111
    validated = subprocess.run(
        [sys.executable, str(package / "scripts/validate-skill-package.py")], cwd=package,
        text=True, capture_output=True, check=False,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr


@pytest.mark.parametrize("member", ["../outside", "/absolute", "forge/../../outside"])
def test_release_extraction_rejects_unsafe_paths_before_writing(tmp_path: Path, member: str) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("forge/VERSION", "1.0.0")
        archive.writestr(member, "unsafe")
    destination = tmp_path / "unpacked"
    extracted = extract_release(archive_path, destination)
    assert extracted.returncode != 0
    assert "unsafe archive member" in extracted.stderr
    assert not destination.exists(), "all members must pass validation before extraction"
