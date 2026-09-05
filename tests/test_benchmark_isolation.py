from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "evals" / "core"
IMAGE = os.environ.get("BENCH_SCORER_IMAGE", "forge-bench-scorer:ci")


def docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    ).returncode == 0


@pytest.mark.skipif(not docker_available(), reason="Docker is required for scorer isolation test")
def test_benchmark_scoring_cannot_write_outside_candidate(tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(CORE / "build_fixtures.py"), "b4"], check=True)
    source = CORE / "build" / "b4"
    repo = tmp_path / "repo"
    shutil.copytree(source, repo)

    sentinel = tmp_path / "outside" / "sentinel.txt"
    (repo / "conftest.py").write_text(
        "from pathlib import Path\n"
        f"SENTINEL = Path({str(sentinel)!r})\n"
        "def pytest_sessionstart(session):\n"
        "    SENTINEL.parent.mkdir(parents=True, exist_ok=True)\n"
        "    SENTINEL.write_text('escaped', encoding='utf-8')\n",
        encoding="utf-8",
    )
    tests = repo / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_sandbox_env.py").write_text(
        "import os\n"
        "def test_controller_secrets_are_not_inherited():\n"
        "    assert 'GITHUB_TOKEN' not in os.environ\n"
        "    assert 'ANTHROPIC_API_KEY' not in os.environ\n",
        encoding="utf-8",
    )

    meta = tmp_path / "meta.json"
    meta.write_text(
        json.dumps(
            {
                "scenario": "b4",
                "condition": "baseline",
                "run": 1,
                "rc": 0,
                "timed_out": False,
                "wall_seconds": 0.1,
                "forge_commit": "test",
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "128",
        "--memory",
        "768m",
        "--cpus",
        "1",
        "--tmpfs",
        "/work:rw,nosuid,nodev,size=512m,mode=1777",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=256m,mode=1777",
        "-v",
        f"{repo}:/input:ro",
        "-v",
        f"{meta}:/evidence/meta.json:ro",
        "-v",
        f"{transcript}:/evidence/transcript.jsonl:ro",
        IMAGE,
        "python3",
        "/scorer/score_entrypoint.py",
        "--phase",
        "final",
        "--scenario",
        "b4",
        "--meta",
        "/evidence/meta.json",
        "--transcript",
        "/evidence/transcript.jsonl",
    ]
    env = os.environ.copy()
    env["GITHUB_TOKEN"] = "host-secret"
    env["ANTHROPIC_API_KEY"] = "host-secret"
    completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["scenario"] == "b4"
    assert not sentinel.exists(), "candidate pytest hook escaped the scoring container"
