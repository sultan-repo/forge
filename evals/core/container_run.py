"""Run one named container with a portable deadline and guaranteed cleanup."""
from __future__ import annotations

import signal
import subprocess
import sys
import uuid


def run_container(runtime: str, timeout: float, arguments: list[str]) -> int:
    name = "forge-bench-" + uuid.uuid4().hex
    process = None
    try:
        process = subprocess.Popen([runtime, "run", "--name", name, "--rm", *arguments])
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124
    finally:
        # Killing the CLI alone does not stop its container. Explicit removal
        # also handles interrupted sessions and their background processes.
        try:
            subprocess.run([runtime, "rm", "-f", name], capture_output=True, timeout=30, check=False)
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()


def interrupted(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if len(sys.argv) < 4:
        raise SystemExit("usage: container_run.py RUNTIME TIMEOUT RUN_ARGUMENTS...")
    raise SystemExit(run_container(sys.argv[1], float(sys.argv[2]), sys.argv[3:]))
