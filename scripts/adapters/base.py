"""Shared adapter helpers for Forge external-agent execution."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time
from typing import Sequence


class AdapterError(RuntimeError):
    """Raised when an external coding-agent adapter cannot complete its role."""


@dataclass(frozen=True)
class AgentRun:
    command: list[str]
    stdout: str
    stderr: str
    returncode: int
    duration_s: float


def require_binary(binary: str) -> str:
    resolved = shutil.which(binary)
    if not resolved:
        raise AdapterError(f"{binary} is not installed or is not on PATH")
    return resolved


def run_command(command: Sequence[str], *, cwd: Path, stdin: str | None = None, timeout_s: int = 3600) -> AgentRun:
    started = time.monotonic()
    try:
        completed = subprocess.run(list(command), cwd=cwd, input=stdin, text=True, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AdapterError(f"agent command timed out after {timeout_s}s") from exc
    return AgentRun(list(command), completed.stdout, completed.stderr, completed.returncode, time.monotonic() - started)
