#!/usr/bin/env python3
"""Run benchmark scoring inside an isolated container.

The candidate repository is mounted read-only at /input and copied into a
throwaway /work tree before any tests execute. Only the final structured JSON
result is emitted on stdout; scorer diagnostics go to stderr.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCORER_ROOT = Path("/scorer")
INPUT_REPO = Path("/input")
WORK_ROOT = Path("/work")
WORK_REPO = WORK_ROOT / "repo"
RESULT_PATH = WORK_ROOT / "run.json"


def sanitized_env() -> dict[str, str]:
    """Return the minimal environment inherited by scorer subprocesses."""
    env = {
        "HOME": "/tmp/scorer-home",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def copy_candidate() -> None:
    """Copy the untrusted candidate into disposable writable storage."""
    shutil.rmtree(WORK_REPO, ignore_errors=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(INPUT_REPO, WORK_REPO, symlinks=True)


def build_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(SCORER_ROOT / "assert_run.py"),
        "--phase",
        args.phase,
        "--scenario",
        args.scenario,
        "--repo",
        str(WORK_REPO),
        "--meta",
        args.meta,
        "--out",
        str(RESULT_PATH),
    ]
    if args.transcript:
        command += ["--transcript", args.transcript]
    if args.stage1_transcript:
        command += ["--stage1-transcript", args.stage1_transcript]
    if args.stage1_result:
        command += ["--stage1-result", args.stage1_result]
    return command


def validate_result(payload: object, scenario: str, phase: str) -> None:
    if not isinstance(payload, dict) or payload.get("scenario") != scenario:
        raise ValueError("isolated scorer result has the wrong scenario")
    if phase == "stage1" and payload.get("phase") != "stage1":
        raise ValueError("isolated scorer result has the wrong phase")
    assertions = payload.get("assertions")
    if not isinstance(assertions, dict) or not assertions or any(type(value) is not bool for value in assertions.values()):
        raise ValueError("isolated scorer assertions must be nonempty booleans")
    failures = [key for key, value in assertions.items() if not value]
    if type(payload.get("pass")) is not bool or payload["pass"] != (not failures) or payload.get("failed_assertions") != failures:
        raise ValueError("isolated scorer result contradicts its assertions")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("stage1", "final"), default="final")
    parser.add_argument("--scenario", required=True, choices=("b1", "b2", "b3", "b4"))
    parser.add_argument("--meta", required=True)
    parser.add_argument("--transcript")
    parser.add_argument("--stage1-transcript")
    parser.add_argument("--stage1-result")
    args = parser.parse_args()

    if not INPUT_REPO.is_dir():
        raise SystemExit("scorer input repository is missing")

    copy_candidate()
    completed = subprocess.run(
        build_command(args),
        cwd=SCORER_ROOT,
        env=sanitized_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.rstrip(), file=sys.stderr)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"isolated scorer failed with rc={completed.returncode}")

    try:
        payload = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"isolated scorer did not produce valid JSON: {exc}") from exc
    validate_result(payload, args.scenario, args.phase)

    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
