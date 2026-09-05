"""Execute release/gate shell contracts with a local fake gh; never call GitHub."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def step_source(workflow: str, name: str) -> tuple[str, dict[str, str]]:
    """Extract this repository's named YAML step without adding a YAML dependency."""
    lines = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() in {f"- name: {name}", f"name: {name}"})
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith("      - ") or (lines[index].strip() and len(lines[index]) - len(lines[index].lstrip()) <= 4)), len(lines))
    step = lines[start:end]
    run_index = next(index for index, line in enumerate(step) if line.startswith("        run:"))
    value = step[run_index].split("run:", 1)[1].strip()
    if value == "|":
        script = textwrap.dedent("\n".join(step[run_index + 1:]))
    else:
        script = value
    environment = {}
    if "        env:" in step:
        env_start = step.index("        env:") + 1
        for line in step[env_start:]:
            if not line.startswith("          "):
                break
            key, value = line.strip().split(":", 1)
            environment[key] = value.strip()
    return script, environment


@pytest.fixture
def workflow_case(tmp_path):
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    fake = binary_dir / "gh"
    fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent("""\
        import json, os, sys
        from pathlib import Path
        with Path(os.environ['FAKE_GH_LOG']).open('a') as log:
            log.write(json.dumps(sys.argv[1:]) + '\\n')
        if any(argument.endswith('/git/ref/heads/main') for argument in sys.argv):
            print(os.environ.get('FAKE_GH_MAIN_SHA', 'a' * 40))
            raise SystemExit(int(os.environ.get('FAKE_GH_MAIN_EXIT', '0')))
        print(os.environ.get('FAKE_GH_RESPONSE', ''), end='')
        raise SystemExit(int(os.environ.get('FAKE_GH_EXIT', '0')))
        """), encoding="utf-8")
    fake.chmod(0o755)
    environment = os.environ.copy()
    # No real provider CLI or authentication enters any tested release operation.
    environment.pop("PRERELEASE", None)
    environment.update(PATH=f"{binary_dir}{os.pathsep}{os.environ['PATH']}",
                       GITHUB_REPOSITORY="forge-test/fixture", GITHUB_OUTPUT=str(tmp_path / "outputs"),
                       FAKE_GH_LOG=str(tmp_path / "gh-log"), RELEASE_SHA="a" * 40)

    def run(workflow, name, *, version="1.2.3", env=None, context=None):
        (tmp_path / "VERSION").write_text(version + "\n", encoding="utf-8")
        script, declared_environment = step_source(workflow, name)
        expressions = {"github.repository": "forge-test/fixture", "github.token": "fake-token",
                       "github.event.workflow_run.head_sha": "a" * 40,
                       "steps.release.outputs.tag": "v" + version,
                       "steps.release.outputs.version": version,
                       "steps.release.outputs.asset": f"forge-skill-v{version}.zip",
                       **(context or {})}

        def expand(value):
            return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: expressions[match[1]], value)

        script = expand(script).replace("/tmp/", str(tmp_path) + "/")
        actual_env = {**environment, **{key: expand(value) for key, value in declared_environment.items()}, **(env or {})}
        (tmp_path / "outputs").write_text("", encoding="utf-8")
        result = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script],
                                cwd=tmp_path, env=actual_env, text=True, capture_output=True, timeout=10, check=False)
        outputs = dict(line.split("=", 1) for line in (tmp_path / "outputs").read_text().splitlines())
        return result, outputs

    return tmp_path, run


@pytest.mark.parametrize(("response", "exit_code", "expected", "unreleased"), [
    ("", 0, 0, "true"),
    ("v0.9.0\tfalse\n", 0, 0, "true"),
    ("v1.2.3\tfalse\n", 0, 0, "false"),
    ("v1.2.3\ttrue\n", 0, 2, None),
    ("", 7, 7, None),
])
def test_release_eligibility_fails_closed(workflow_case, response, exit_code, expected, unreleased):
    _, run = workflow_case
    result, outputs = run("release.yml", "Check whether the validated version is unpublished",
                          env={"FAKE_GH_RESPONSE": response, "FAKE_GH_EXIT": str(exit_code)})
    assert result.returncode == expected, result.stderr
    assert outputs.get("unreleased") == unreleased


def test_stale_workflow_completion_cannot_release_an_older_commit(workflow_case):
    directory, run = workflow_case
    result, outputs = run("release.yml", "Check whether the validated version is unpublished",
                          env={"FAKE_GH_MAIN_SHA": "b" * 40})
    assert result.returncode == 0, result.stderr
    assert outputs == {"unreleased": "false"}
    assert len((directory / "gh-log").read_text().splitlines()) == 1


def test_main_ref_api_failure_cannot_make_a_commit_eligible(workflow_case):
    _, run = workflow_case
    result, outputs = run("release.yml", "Check whether the validated version is unpublished",
                          env={"FAKE_GH_MAIN_EXIT": "4"})
    assert result.returncode == 4
    assert outputs == {}


@pytest.mark.parametrize(("version", "prerelease", "latest"), [
    ("1.2.3", "false", "true"), ("1.2.3-rc.1", "true", "false"), ("1.2.3.dev1", "true", "false"),
])
def test_release_identity_classifies_suffixes(workflow_case, version, prerelease, latest):
    _, run = workflow_case
    result, outputs = run("release.yml", "Resolve release identity", version=version)
    assert result.returncode == 0, result.stderr
    assert outputs == {"version": version, "tag": "v" + version,
                       "asset": f"forge-skill-v{version}.zip", "prerelease": prerelease, "latest": latest}


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "1.2.3;exit 0", "1.2.3+build"])
def test_release_identity_rejects_unsupported_versions(workflow_case, version):
    _, run = workflow_case
    result, outputs = run("release.yml", "Resolve release identity", version=version)
    assert result.returncode == 2
    assert outputs == {}


@pytest.mark.parametrize("prerelease", ["true", "false"])
def test_draft_creation_passes_classification_and_exact_commit(workflow_case, prerelease):
    directory, run = workflow_case
    result, _ = run("release.yml", "Create draft release with asset",
                    context={"steps.release.outputs.prerelease": prerelease})
    assert result.returncode == 0, result.stderr
    command = json.loads((directory / "gh-log").read_text().splitlines()[-1])
    assert command[:3] == ["release", "create", "v1.2.3"]
    assert "--draft" in command
    assert f"--prerelease={prerelease}" in command
    assert command[command.index("--target") + 1] == "a" * 40
    assert "forge-skill-v1.2.3.zip#Forge skill package v1.2.3" in command


@pytest.mark.parametrize(("env", "exit_code"), [
    ({"FAKE_GH_MAIN_SHA": "b" * 40}, 2), ({"FAKE_GH_MAIN_EXIT": "7"}, 7),
])
def test_main_change_or_api_failure_during_packaging_prevents_draft(workflow_case, env, exit_code):
    directory, run = workflow_case
    result, _ = run("release.yml", "Create draft release with asset", env=env,
                    context={"steps.release.outputs.prerelease": "false"})
    assert result.returncode == exit_code
    calls = [json.loads(line) for line in (directory / "gh-log").read_text().splitlines()]
    assert not any(call[:2] == ["release", "create"] for call in calls)


def test_publication_does_not_replace_an_existing_release(workflow_case):
    _, run = workflow_case
    result, _ = run("release.yml", "Ensure release does not already exist")
    assert result.returncode == 2
    assert "Refusing to replace" in result.stderr


def test_publication_does_not_reuse_an_unpublished_tag(workflow_case):
    directory, run = workflow_case
    for arguments in (["init", "-q"], ["-c", "user.name=Forge Test", "-c", "user.email=forge@example.invalid",
                                      "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture"],
                      ["tag", "v1.2.3"]):
        subprocess.run(["git", *arguments], cwd=directory, check=True, capture_output=True)
    result, _ = run("release.yml", "Ensure release does not already exist", env={"FAKE_GH_EXIT": "1"})
    assert result.returncode == 2
    assert "unverified target" in result.stderr


@pytest.mark.parametrize(("key", "value"), [
    ("CHANGES", "failure"), ("CHANGES", "skipped"), ("STATIC", "skipped"),
    ("DUAL_AGENT", "failure"), ("BENCHMARK_SELFTESTS", "cancelled"), ("BENCHMARK_ISOLATION", "failure"),
])
def test_validation_gate_blocks_failed_or_missing_required_checks(workflow_case, key, value):
    _, run = workflow_case
    checks = {name: "success" for name in ("CHANGES", "STATIC", "DUAL_AGENT", "BENCHMARK_SELFTESTS", "BENCHMARK_ISOLATION")}
    checks[key] = value
    context = {"needs.changes.result": checks["CHANGES"], "needs.static-checks.result": checks["STATIC"],
               "needs.dual-agent-tests.result": checks["DUAL_AGENT"], "needs.benchmark-selftests.result": checks["BENCHMARK_SELFTESTS"],
               "needs.benchmark-isolation.result": checks["BENCHMARK_ISOLATION"],
               "needs.changes.outputs.dual_agent": "true", "needs.changes.outputs.benchmark": "true"}
    result, _ = run("validate.yml", "Require all applicable validation jobs", context=context)
    assert result.returncode == 1


def test_validation_gate_allows_inapplicable_expensive_checks(workflow_case):
    _, run = workflow_case
    context = {"needs.changes.result": "success", "needs.static-checks.result": "success",
               "needs.dual-agent-tests.result": "skipped", "needs.benchmark-selftests.result": "skipped",
               "needs.benchmark-isolation.result": "skipped",
               "needs.changes.outputs.dual_agent": "false", "needs.changes.outputs.benchmark": "false"}
    result, _ = run("validate.yml", "Require all applicable validation jobs", context=context)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("expect_dual", "expect_benchmark", "skipped", "expected"), [
    ("true", "false", ("dual-agent-tests",), 1),
    ("false", "true", ("benchmark-selftests",), 1),
    ("false", "true", ("benchmark-isolation",), 1),
    ("true", "true", ("dual-agent-tests", "benchmark-selftests", "benchmark-isolation"), 1),
    ("true", "false", ("benchmark-selftests", "benchmark-isolation"), 0),
    ("false", "true", ("dual-agent-tests",), 0),
    ("true", "true", (), 0),
])
def test_validation_gate_requires_success_for_each_applicable_job(
    workflow_case, expect_dual, expect_benchmark, skipped, expected,
):
    _, run = workflow_case
    context = {f"needs.{job}.result": "success" for job in (
        "changes", "static-checks", "dual-agent-tests", "benchmark-selftests", "benchmark-isolation",
    )}
    context.update({f"needs.{job}.result": "skipped" for job in skipped})
    context.update({"needs.changes.outputs.dual_agent": expect_dual,
                    "needs.changes.outputs.benchmark": expect_benchmark})
    result, _ = run("validate.yml", "Require all applicable validation jobs", context=context)
    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert "An applicable test job did not succeed" in result.stderr
