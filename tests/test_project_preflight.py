from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import jsonschema

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

    status, _, blockers, _ = preflight.evaluate(tmp_path, live=False)

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
            return subprocess.CompletedProcess(command, 0, json.dumps({"is_error": False, "model": "claude-test"}), "")
        if command[0] == "codex" and "--ask-for-approval" in command:
            return ok(command)
        raise AssertionError(command)

    monkeypatch.setattr(preflight, "command_result", fake_command)

    status, report, blockers, warnings = preflight.evaluate(tmp_path, live=True)

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
        "status": "READY",
        "live_verified": True,
        "preferences_sha256": preflight.preferences_digest(project, local),
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
