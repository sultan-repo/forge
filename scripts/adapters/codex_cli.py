"""Codex CLI independent-review adapter."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, cast

from .base import AdapterError, AgentRun, require_binary, run_command


class CodexCLIReviewer:
    name = "codex-cli"

    def __init__(self, binary: str = "codex", timeout_s: int = 3600) -> None:
        self.binary = binary
        self.timeout_s = timeout_s

    def doctor(self, cwd: Path) -> tuple[bool, str]:
        try:
            require_binary(self.binary)
        except AdapterError as exc:
            return False, str(exc)
        result = run_command([self.binary, "login", "status"], cwd=cwd, timeout_s=30)
        if result.returncode != 0:
            return False, "Codex is not signed in. Run `codex login`."
        help_result = run_command([self.binary, "exec", "--help"], cwd=cwd, timeout_s=30)
        help_text = f"{help_result.stdout}\n{help_result.stderr}"
        required_flags = ("--ignore-user-config", "--ignore-rules", "--output-schema")
        if help_result.returncode != 0 or any(flag not in help_text for flag in required_flags):
            return False, "Codex CLI is too old for Forge's isolated reviewer mode. Update Codex CLI."
        return True, "Codex ready"

    def review(self, prompt: str, cwd: Path, schema_path: Path) -> tuple[AgentRun, dict[str, Any]]:
        require_binary(self.binary)
        with tempfile.TemporaryDirectory(prefix="forge-codex-") as tmp:
            output_path = Path(tmp) / "review.json"
            result = run_command(
                [
                    self.binary,
                    "--ask-for-approval",
                    "never",
                    "exec",
                    "--cd",
                    str(cwd),
                    "--sandbox",
                    "read-only",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--color",
                    "never",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                    "-",
                ],
                cwd=cwd,
                stdin=prompt,
                timeout_s=self.timeout_s,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise AdapterError(f"Codex review failed: {detail[:500]}")
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise AdapterError("Codex did not return a valid structured review") from exc
            if not isinstance(payload, dict):
                raise AdapterError("Codex structured review must be a JSON object")
        return result, cast(dict[str, Any], payload)
