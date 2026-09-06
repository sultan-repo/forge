"""Real staged installation and distribution validation; no user installation touched."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def package(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(
        ".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "results", "fixture_bundle.json",
    ))
    return source


def install(source, destination, *, extra_env=None, entrypoint="install.sh"):
    env = dict(os.environ, CLAUDE_SKILLS_DIR=str(destination), PYTHONPYCACHEPREFIX=str(destination.parent / "cache"))
    # Default to the test interpreter; explicit command proxies take precedence.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["bash", str(source / "scripts" / entrypoint)], env=env, text=True, capture_output=True, check=False)


@pytest.mark.parametrize("name", ["project-control", "execution-profile", "implementation-handoff", "review-result"])
def test_distributed_schemas_and_examples_remain_valid(name):
    schema = json.loads((ROOT / "templates" / f"{name}.schema.json").read_text())
    schema_validator = jsonschema.validators.validator_for(schema)
    schema_validator.check_schema(schema)
    example = ROOT / "templates" / f"{name}.example.json"
    if example.exists():
        schema_validator(schema).validate(json.loads(example.read_text()))


def test_installed_package_validates_and_preserves_previous_install(package, tmp_path):
    skills = tmp_path / "skills"
    previous = skills / "forge"
    previous.mkdir(parents=True)
    (previous / "previous.txt").write_text("previous installation")
    generated = package / "evals/core/results"
    generated.mkdir()
    (generated / "private-result.json").write_text("not distributable")
    completed = install(package, skills)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (previous / "tests/test_dual_agent_runner.py").exists()
    assert (previous / "CONTRIBUTING.md").exists()
    assert (previous / ".github/workflows/validate.yml").exists()
    assert not (previous / "evals/core/results").exists()
    assert os.access(previous / "scripts/forge", os.X_OK)
    backup = list(skills.glob("forge.backup.*"))
    assert len(backup) == 1
    assert (backup[0] / "previous.txt").read_text() == "previous installation"
    check = subprocess.run([sys.executable, str(previous / "scripts/validate-skill-package.py")], text=True, capture_output=True, check=False)
    assert check.returncode == 0, check.stdout + check.stderr
    again = install(previous, skills)
    assert again.returncode == 0, again.stdout + again.stderr
    assert len(list(skills.glob("forge.backup.*"))) == 1


def test_invalid_candidate_keeps_active_install_intact(package, tmp_path):
    skills = tmp_path / "skills"
    previous = skills / "forge"
    previous.mkdir(parents=True)
    (previous / "previous.txt").write_text("keep this")
    (package / "templates/review-result.schema.json").write_text("not JSON")
    result = install(package, skills)
    assert result.returncode != 0
    assert (previous / "previous.txt").read_text() == "keep this"
    assert not list(skills.glob("forge.backup.*"))
    assert not list(skills.glob(".forge-install.*"))


@pytest.mark.parametrize("failure", ["wrong_name", "unclosed", "disabled_body_decoy", "duplicate_name", "empty_description"])
def test_invalid_skill_frontmatter_keeps_active_install_intact(package, tmp_path, failure):
    skill = package / "SKILL.md"
    contents = skill.read_text()
    if failure == "wrong_name":
        contents = contents.replace("name: forge\n", "name: another-skill\n", 1)
    elif failure == "unclosed":
        contents = contents.replace("\n---\n", "\n", 1)
    elif failure == "disabled_body_decoy":
        contents = contents.replace("disable-model-invocation: false", "disable-model-invocation: true", 1)
        contents += "\n<!-- disable-model-invocation: false -->\n"
    elif failure == "duplicate_name":
        contents = contents.replace("name: forge\n", "name: forge\nname: another-skill\n", 1)
    else:
        contents = "\n".join("description:" if line.startswith("description:") else line for line in contents.split("\n"))
    skill.write_text(contents)
    skills = tmp_path / "skills"
    previous = skills / "forge"
    previous.mkdir(parents=True)
    (previous / "previous.txt").write_text("keep the valid installation")

    result = install(package, skills)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "SKILL INVALID" in result.stderr
    assert "SKILL.md" in result.stderr
    assert "Traceback" not in result.stderr
    assert (previous / "previous.txt").read_text() == "keep the valid installation"
    assert not list(skills.glob("forge.backup.*"))
    assert not list(skills.glob(".forge-install.*"))


@pytest.mark.parametrize("disabled", ["false", "NO", "off", "0"])
def test_supported_frontmatter_scalars_and_folded_description(package, disabled):
    skill = package / "SKILL.md"
    body = skill.read_text().split("\n---\n", 1)[1]
    skill.write_text(
        "---\nname: 'forge' # skill identity\n"
        "description: >-\n"
        "  Invoke only when the user explicitly mentions Forge\n"
        "  to request its use.\n"
        f"disable-model-invocation: {disabled} # supports natural-language requests\n"
        "---\n" + body
    )
    result = subprocess.run([sys.executable, str(package / "scripts/validate-skill-package.py")], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("description", [
    '"Forge # invoke only when explicitly requested" # comment',
    "|-\n  Forge # invoke only when explicitly requested",
])
def test_frontmatter_description_preserves_literal_hashes(package, description):
    skill = package / "SKILL.md"
    body = skill.read_text().split("\n---\n", 1)[1]
    skill.write_text(
        f'---\nname: "forge"\ndescription: {description}\n'
        "disable-model-invocation: false\n---\n" + body
    )
    result = subprocess.run([sys.executable, str(package / "scripts/validate-skill-package.py")], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_install_lock_does_not_remove_another_installer_lock(package, tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    lock = skills / ".forge-install.lock"
    lock.mkdir()
    result = install(package, skills)
    assert result.returncode == 2
    assert lock.is_dir()
    assert not (skills / "forge").exists()


@pytest.mark.parametrize("contents", ["[]", '{"evals": [null]}', '{"evals": [{"id": {}, "expectations": []}]}'])
def test_malformed_evaluation_has_actionable_failure(package, contents):
    (package / "evals/evals.json").write_text(contents)
    result = subprocess.run([sys.executable, str(package / "scripts/validate-skill-package.py")], text=True, capture_output=True, check=False)
    assert result.returncode == 2
    assert "SKILL INVALID" in result.stderr
    assert "Traceback" not in result.stderr


def test_validator_ignores_local_benchmark_results(package):
    results = package / "evals/core/results"
    results.mkdir()
    (results / "interrupted.json").write_text("not completed")
    result = subprocess.run([sys.executable, str(package / "scripts/validate-skill-package.py")], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("shared_interpreter_bin", [False, True])
def test_failed_final_move_restores_previous_install_under_lock(package, tmp_path, monkeypatch, shared_interpreter_bin):
    if shared_interpreter_bin:
        # System interpreters can share a bin directory with mv; venvs usually do not.
        interpreter_bin = tmp_path / "system-bin"
        interpreter_bin.mkdir()
        (interpreter_bin / "python3").symlink_to(sys.executable)
        (interpreter_bin / "mv").symlink_to(shutil.which("mv"))
        monkeypatch.setattr(sys.modules[__name__], "sys", SimpleNamespace(executable=str(interpreter_bin / "python3")))
    skills = tmp_path / "skills"
    previous = skills / "forge"
    previous.mkdir(parents=True)
    (previous / "previous.txt").write_text("keep this installation")
    commands = tmp_path / "commands"
    commands.mkdir()
    rollback_marker = tmp_path / "rollback-under-lock"
    proxy = commands / "mv"
    proxy.write_text("#!/usr/bin/env python3\n" + """
import os
from pathlib import Path
import subprocess
import sys

source, destination = map(Path, sys.argv[1:3])
if source.name.startswith(".forge-install."):
    print("Simulated final replacement failure", file=sys.stderr)
    raise SystemExit(73)
if source.name.startswith("forge.backup."):
    locked = (destination.parent / ".forge-install.lock").is_dir()
    Path(os.environ["FORGE_TEST_ROLLBACK_MARKER"]).write_text(str(locked))
raise SystemExit(subprocess.run([os.environ["FORGE_TEST_REAL_MV"], *sys.argv[1:]], check=False).returncode)
""")
    proxy.chmod(0o755)
    result = install(package, skills, extra_env={
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "FORGE_TEST_REAL_MV": shutil.which("mv"),
        "FORGE_TEST_ROLLBACK_MARKER": str(rollback_marker),
    })
    assert result.returncode == 73, result.stdout + result.stderr
    assert (previous / "previous.txt").read_text() == "keep this installation"
    assert rollback_marker.read_text() == "True", "Rollback must finish before another installer can acquire the lock"
    assert not list(skills.glob("forge.backup.*"))
    assert not list(skills.glob(".forge-install.*"))


def test_bootstrap_without_verification_does_not_install(package, tmp_path):
    skills = tmp_path / "skills"
    result = install(package, skills, extra_env={"FORGE_SOURCE_VERIFIED": ""}, entrypoint="bootstrap.sh")
    assert result.returncode == 2
    assert "FORGE_BOOTSTRAP_READY" not in result.stdout
    assert not skills.exists()


def test_bootstrap_does_not_claim_ready_after_installation_failure(package, tmp_path):
    skills = tmp_path / "skills"
    previous = skills / "forge"
    previous.mkdir(parents=True)
    (previous / "previous.txt").write_text("preserved")
    (package / "templates/review-result.schema.json").write_text("not JSON")
    result = install(package, skills, extra_env={"FORGE_SOURCE_VERIFIED": "1"}, entrypoint="bootstrap.sh")
    assert result.returncode != 0
    assert "FORGE_BOOTSTRAP_READY" not in result.stdout
    assert (previous / "previous.txt").read_text() == "preserved"
    assert not list(skills.glob(".forge-install.*"))


@pytest.mark.parametrize("script", ["install.sh", "bootstrap.sh", "forge"])
@pytest.mark.parametrize("failure", ["missing", "not_executable"])
def test_distribution_requires_usable_entrypoints(package, script, failure):
    path = package / "scripts" / script
    if failure == "missing":
        path.unlink()
    else:
        path.chmod(0o644)
    result = subprocess.run([sys.executable, str(package / "scripts/validate-skill-package.py")], text=True, capture_output=True, check=False)
    assert result.returncode == 2
    assert script in result.stderr
    assert "SKILL INVALID" in result.stderr


def test_verified_bootstrap_reports_custom_install_path(package, tmp_path):
    skills = tmp_path / "custom skills"
    result = install(package, skills, extra_env={"FORGE_SOURCE_VERIFIED": "1"}, entrypoint="bootstrap.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (skills / "forge/SKILL.md").exists()
    assert "FORGE_BOOTSTRAP_READY" in result.stdout
    assert f"Load {skills}/forge/SKILL.md directly" in result.stdout
