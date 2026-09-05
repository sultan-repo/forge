"""Shared adapter helpers for Forge external-agent execution."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType


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
    process: subprocess.Popen[str] | None = None
    pending_termination: int | None = None

    def terminate(signum: int, _frame: FrameType | None) -> None:
        # Unwind the runner's normal cleanup/lock contexts instead of exiting
        # while a detached agent group still owns the working tree.
        nonlocal pending_termination
        pending_termination = signum
        if process is not None:
            raise SystemExit(128 + signum)

    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.signal(signal.SIGTERM, terminate)
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.PIPE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
        if pending_termination is not None:
            raise SystemExit(128 + pending_termination)
        stdout, stderr = process.communicate(input=stdin, timeout=timeout_s)
        return AgentRun(list(command), stdout, stderr, process.returncode, time.monotonic() - started)
    except BaseException as exc:
        if process is not None:
            # Agent shells share this process group. Stop them as well as the CLI
            # before any interruption can release the repository lock.
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            process.communicate()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise AdapterError(f"agent command timed out after {timeout_s}s") from exc
        if isinstance(exc, OSError) and process is None:
            raise AdapterError(f"agent command could not start: {exc}") from exc
        raise
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
