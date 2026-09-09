from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT_PATH = ROOT / "scripts" / "forge-preflight.py"
spec = importlib.util.spec_from_file_location("forge_preflight", PREFLIGHT_PATH)
assert spec and spec.loader
preflight = importlib.util.module_from_spec(spec)
sys.modules["forge_preflight"] = preflight
spec.loader.exec_module(preflight)


def write_preferences(
    root: Path,
    *,
    execution: str = "adaptive",
    codex: str = "high_risk",
    auth: str = "subscription",
    live_required: bool = True,
) -> None:
    project = {
        "version": 1,
        "execution_mode": execution,
        "claude_model_policy": "current_cli",
        "codex_review_policy": codex,
        "live_preflight_required": live_required,
    }
    local = {"version": 1, "claude_authentication": auth}
    (root / preflight.PROJECT_PREFS).parent.mkdir(parents=True, exist_ok=True)
    (root / preflight.RUNTIME_DIR).mkdir(parents=True, exist_ok=True)
    (root / preflight.PROJECT_PREFS).write_text(json.dumps(project), encoding="utf-8")
    (root / preflight.LOCAL_PREFS).write_text(json.dumps(local), encoding="utf-8")


def ok(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "ok", "")


def test_preflight_schema_accepts_example() -> None:
    schema = json.loads((ROOT / "templates" / "project-preferences.schema.json").read_text(encoding="utf-8"))
    example = json.loads((ROOT / "templates" / "project-preferences.example.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(example)
    preflight.validate_project_preferences(example)


def test_claude_only_does_not_require_codex(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path, execution="claude_only", codex="never", live_required=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "Claude 1" if binary == "claude" else None)
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    status, report, blockers, warnings = preflight.evaluate(tmp_path, live=False)

    assert status == "READY"
    assert blockers == []
    assert warnings == []
    assert report["environment"]["codex_review_required"] is False


def test_subscription_preference_blocks_api_override_without_leaking_value(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: f"{binary} ready")
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "super-secret-key")

    status, report, blockers, _ = preflight.evaluate(tmp_path, live=False)
    rendered = json.dumps(report) + "\n".join(blockers)

    assert status == "BLOCKED"
    assert any("ANTHROPIC_API_KEY is present" in message for message in blockers)
    assert "super-secret-key" not in rendered


def test_configured_codex_is_checked_before_work(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path)

    def fake_version(binary: str, cwd: Path) -> str | None:
        return "Claude 1" if binary == "claude" else None

    monkeypatch.setattr(preflight, "version_of", fake_version)
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    status, _, blockers, _ = preflight.evaluate(tmp_path, live=False, task="high_risk")

    assert status == "BLOCKED"
    assert any("Codex review is configured" in message for message in blockers)


def test_live_preflight_requests_high_reasoning_and_records_reported_model(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path, live_required=True)
    seen: list[list[str]] = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: f"{binary} 1")

    def fake_command(command: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        if command[:3] == ["claude", "auth", "status"]:
            return ok(command)
        if command[:3] == ["codex", "login", "status"]:
            return ok(command)
        if command[:3] == ["codex", "exec", "--help"]:
            return subprocess.CompletedProcess(
                command,
                0,
                "--config --ignore-user-config --ignore-rules",
                "",
            )
        if command[0] == "claude" and "-p" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({"is_error": False, "model": "claude-test", "result": "FORGE_CLAUDE_READY"}), "")
        if command[0] == "codex" and "--ask-for-approval" in command:
            return subprocess.CompletedProcess(command, 0, '\n'.join([
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "FORGE_CODEX_READY"}}),
                json.dumps({"type": "turn.completed"}),
            ]), "")
        raise AssertionError(command)

    monkeypatch.setattr(preflight, "command_result", fake_command)

    status, report, blockers, warnings = preflight.evaluate(tmp_path, live=True, task="high_risk")

    assert status == "READY"
    assert blockers == []
    assert warnings == []
    assert report["live_verified"] is True
    assert report["environment"]["claude_models_reported"] == ["claude-test"]
    codex = next(command for command in seen if command[0] == "codex" and "--ask-for-approval" in command)
    assert codex[codex.index("--config") + 1] == 'model_reasoning_effort="high"'
    assert codex[codex.index("--sandbox") + 1] == "read-only"


def test_live_evidence_is_reused_only_when_environment_matches(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path, execution="claude_only", codex="never", live_required=True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "claude 1" if binary == "claude" else None)
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))

    project = preflight.read_json(tmp_path / preflight.PROJECT_PREFS)
    local = preflight.read_json(tmp_path / preflight.LOCAL_PREFS)
    prior = {
        "version": 2,
        "status": "READY",
        "live_verified": True,
        "preferences_sha256": preflight.preferences_digest({**project, "requested_task": "planned", "requested_review": False}, local),
        "environment": {
            "claude_version": "claude 1",
            "codex_version": None,
            "anthropic_api_key_present": False,
        },
    }
    preflight.atomic_json(tmp_path / preflight.REPORT, prior)

    status, report, blockers, warnings = preflight.evaluate(tmp_path, live=False)

    assert status == "READY"
    assert report["live_verified"] is True
    assert blockers == []
    assert warnings == []


def test_missing_preferences_use_offline_defaults_without_creating_setup(tmp_path: Path, monkeypatch) -> None:
    seen = []
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "Claude 1" if binary == "claude" else None)
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: seen.append(command) or ok(command))
    status, report, blockers, _ = preflight.evaluate(tmp_path, live=False)
    assert status == "READY"
    assert blockers == []
    assert report["preferences_source"] == {"project": "default", "local": "default"}
    assert report["live_verified"] is False
    assert seen == [["claude", "auth", "status"]]
    assert not (tmp_path / preflight.PROJECT_PREFS).exists()
    assert not (tmp_path / preflight.LOCAL_PREFS).exists()


@pytest.mark.parametrize(("policy", "task", "review", "required"), [
    ("never", "high_risk", False, False),
    ("explicit", "high_risk", False, False),
    ("explicit", "quick", True, True),
    ("high_risk", "planned", False, False),
    ("high_risk", "high_risk", False, True),
    ("substantial", "quick", False, False),
    ("substantial", "planned", False, True),
])
def test_codex_requirements_follow_requested_operation(policy, task, review, required) -> None:
    assert preflight.codex_is_required({"codex_review_policy": policy}, task, review) is required


def test_required_probe_blocks_external_readiness_without_making_provider_call(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path, execution="claude_only", codex="never", live_required=True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "Claude 1")
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))
    status, report, blockers, _ = preflight.evaluate(tmp_path, live=False)
    assert status == "BLOCKED"
    assert report["live_verified"] is False
    assert any("Project policy requires" in message for message in blockers)


@pytest.mark.parametrize("payload", [
    "not JSON", [], {}, {"is_error": False, "result": []},
    {"is_error": False, "result": "anything else"},
    {"is_error": True, "result": "FORGE_CLAUDE_READY"},
    {"is_error": False, "result": "FORGE_CLAUDE_READY", "subtype": "error_max_turns"},
])
def test_zero_exit_malformed_or_failed_claude_probe_is_not_ready(tmp_path: Path, monkeypatch, payload) -> None:
    write_preferences(tmp_path, execution="claude_only", codex="never", live_required=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "Claude 1")
    def fake(command, cwd, **kwargs):
        if "-p" in command:
            assert command[command.index("--tools") + 1] == ""
            assert "--disable-slash-commands" in command
            assert "--strict-mcp-config" in command
            assert command[command.index("--settings") + 1] == '{"disableAllHooks":true}'
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return ok(command)
    monkeypatch.setattr(preflight, "command_result", fake)
    status, report, _, _ = preflight.evaluate(tmp_path, live=True)
    assert status == "BLOCKED"
    assert report["live_verified"] is False


@pytest.mark.parametrize("events", [
    [], ["not JSON"], [{"type": "turn.completed"}],
    [{"type": "item.completed", "item": {"type": "agent_message", "text": "FORGE_CODEX_READY"}}],
    [{"type": "item.completed", "item": {"type": "agent_message", "text": []}}, {"type": "turn.completed"}],
    [{"type": "item.completed", "item": {"type": "agent_message", "text": "FORGE_CODEX_READY"}}, {"type": "turn.failed"}],
])
def test_codex_probe_requires_answer_and_successful_completion(events) -> None:
    assert not preflight.codex_probe_succeeded("\n".join(json.dumps(event) for event in events))


def test_empty_version_output_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda binary: binary)
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd: subprocess.CompletedProcess(command, 0, "", ""))
    assert preflight.version_of("claude", tmp_path) is None


def test_preflight_atomic_write_does_not_follow_predictable_temporary_symlink(tmp_path: Path) -> None:
    target = tmp_path / "preflight.json"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("preserve")
    trap = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    trap.symlink_to(unrelated)
    preflight.atomic_json(target, {"status": "READY"})
    assert unrelated.read_text() == "preserve"
    assert json.loads(target.read_text()) == {"status": "READY"}
    assert trap.is_symlink()


def test_failed_authentication_invalidates_prior_live_evidence(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path, execution="claude_only", codex="never", live_required=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "Claude 1")
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))
    _, prior, _, _ = preflight.evaluate(tmp_path, live=False)
    prior.update(live_verified=True, live_checked_at="2026-09-01T00:00:00+00:00")
    preflight.atomic_json(tmp_path / preflight.REPORT, prior)
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: subprocess.CompletedProcess(command, 1, "", "not logged in"))
    status, report, _, _ = preflight.evaluate(tmp_path, live=False)
    assert status == "BLOCKED"
    assert report["live_verified"] is False
    assert report["live_checked_at"] is None


def test_preflight_rejects_runtime_symlink_outside_project(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / preflight.RUNTIME_DIR).parent.mkdir(parents=True)
    (root / preflight.RUNTIME_DIR).symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="symbolic links"):
        preflight.evaluate(root, live=False)
    assert list(outside.iterdir()) == []


def test_cached_probe_preserves_original_time_and_model(tmp_path: Path, monkeypatch) -> None:
    write_preferences(tmp_path, execution="claude_only", codex="never", live_required=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "version_of", lambda binary, cwd: "Claude 1")
    monkeypatch.setattr(preflight, "command_result", lambda command, cwd, **kwargs: ok(command))
    _, prior, _, _ = preflight.evaluate(tmp_path, live=False)
    prior.update(live_verified=True, live_checked_at="2026-09-01T00:00:00+00:00")
    prior["environment"]["claude_models_reported"] = ["reported-model"]
    preflight.atomic_json(tmp_path / preflight.REPORT, prior)
    _, report, _, _ = preflight.evaluate(tmp_path, live=False)
    assert report["live_verified"] is True
    assert report["live_checked_at"] == "2026-09-01T00:00:00+00:00"
    assert report["environment"]["claude_models_reported"] == ["reported-model"]
    _, different_operation, _, _ = preflight.evaluate(tmp_path, live=False, task="quick")
    assert different_operation["live_verified"] is False
