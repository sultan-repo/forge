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


def stop_agent_processes(process: subprocess.Popen[str]) -> None:
    """Stop the owned agent group, including children with redirected stdio."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass


def run_command(command: Sequence[str], *, cwd: Path, stdin: str | None = None, timeout_s: int = 3600) -> AgentRun:
    started = time.monotonic()
    process: subprocess.Popen[str] | None = None
    pending_termination: int | None = None

    def raise_interruption(signum: int) -> None:
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    def terminate(signum: int, _frame: FrameType | None) -> None:
        # Unwind the runner's normal cleanup/lock contexts instead of exiting
        # while a detached agent group still owns the working tree.
        nonlocal pending_termination
        pending_termination = signum
        if process is not None:
            raise_interruption(signum)

    previous_handlers = {}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.signal(signum, terminate)
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
            raise_interruption(pending_termination)
        stdout, stderr = process.communicate(input=stdin, timeout=timeout_s)
        # A successful CLI can leave background commands whose redirected stdio
        # does not keep communicate() open. They must stop before checkpointing.
        stop_agent_processes(process)
        return AgentRun(list(command), stdout, stderr, process.returncode, time.monotonic() - started)
    except BaseException as exc:
        if process is not None:
            # Agent shells share this process group. Stop them as well as the CLI
            # before any interruption can release the repository lock.
            stop_agent_processes(process)
            process.communicate()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise AdapterError(f"agent command timed out after {timeout_s}s") from exc
        if isinstance(exc, OSError) and process is None:
            raise AdapterError(f"agent command could not start: {exc}") from exc
        raise
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
