"""Claude Code implementation adapter."""
from __future__ import annotations

from pathlib import Path

from .base import AdapterError, AgentRun, require_binary, run_command


class ClaudeCodeImplementer:
    name = "claude-code-cli"

    def __init__(self, binary: str = "claude", timeout_s: int = 7200) -> None:
        self.binary = binary
        self.timeout_s = timeout_s

    def doctor(self, cwd: Path) -> tuple[bool, str]:
        try:
            require_binary(self.binary)
        except AdapterError as exc:
            return False, str(exc)
        result = run_command([self.binary, "--version"], cwd=cwd, timeout_s=30)
        if result.returncode != 0:
            return False, "Claude Code is installed but could not start."
        return True, "Claude Code ready"

    def implement(self, prompt: str, cwd: Path) -> AgentRun:
        require_binary(self.binary)
        result = run_command([
            self.binary,
            "-p",
            "--permission-mode",
            "acceptEdits",
            "--output-format",
            "json",
            prompt,
        ], cwd=cwd, timeout_s=self.timeout_s)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise AdapterError(f"Claude Code implementation failed: {detail[:500]}")
        return result
