"""Claude Code implementation adapter."""
from __future__ import annotations

import json
from pathlib import Path

from .base import AdapterError, AgentRun, require_binary, run_command


def failure_detail(payload: object, result: AgentRun) -> str:
    """Prefer the actual CLI result over incidental startup warnings on stderr."""
    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list):
            messages = [message.strip() for message in errors if isinstance(message, str) and message.strip()]
            if messages:
                return "\n".join(messages)[:500]
        for key in ("errors", "error", "result"):
            message = payload.get(key)
            if isinstance(message, dict):
                message = message.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:500]
    return (result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}")[:500]


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
        ], cwd=cwd, stdin=prompt, timeout_s=self.timeout_s)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
        reported_failure = isinstance(payload, dict) and payload.get("is_error") is True
        if result.returncode != 0 or reported_failure:
            raise AdapterError(f"Claude Code implementation failed: {failure_detail(payload, result)}")
        return result
