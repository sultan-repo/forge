from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adapters import codex_cli  # noqa: E402


class FakeRun:
    duration_s = 0.01
    stdout = ""
    stderr = ""
    returncode = 0


def test_codex_reviewer_requests_high_reasoning_per_run(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_command(command, **kwargs):
        seen.update(command=command, **kwargs)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("{}", encoding="utf-8")
        return FakeRun()

    monkeypatch.setattr(codex_cli, "require_binary", lambda _: "codex")
    monkeypatch.setattr(codex_cli, "run_command", fake_command)

    reviewer = codex_cli.CodexCLIReviewer()
    reviewer.review("review prompt", tmp_path, ROOT / "templates/review-result.schema.json")

    command = seen["command"]
    config_index = command.index("--config")
    assert command[config_index + 1] == 'model_reasoning_effort="high"'
    assert "--ignore-user-config" in command
    assert "--sandbox" in command
    assert command[command.index("--sandbox") + 1] == "read-only"


def test_codex_reviewer_keeps_model_unpinned(tmp_path: Path, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_command(command, **kwargs):
        seen.update(command=command, **kwargs)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text("{}", encoding="utf-8")
        return FakeRun()

    monkeypatch.setattr(codex_cli, "require_binary", lambda _: "codex")
    monkeypatch.setattr(codex_cli, "run_command", fake_command)

    codex_cli.CodexCLIReviewer().review("review prompt", tmp_path, ROOT / "templates/review-result.schema.json")

    command = seen["command"]
    assert "--model" not in command
    assert "-m" not in command
