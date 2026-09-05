#!/usr/bin/env python3
"""Structural validation for the Forge skill package."""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import runpy
import subprocess
import sys
import zlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
errors: list[str] = []
warnings: list[str] = []


def err(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


skill = root / "SKILL.md"
if not skill.exists():
    err("SKILL.md missing")
else:
    text = skill.read_text(encoding="utf-8")
    lines = text.count("\n") + 1
    size = len(text.encode("utf-8"))
    if lines >= 500:
        err(f"SKILL.md is {lines} lines; must stay under 500")
    if size > 10_000:
        err(f"SKILL.md is {size} bytes; compact core must stay <= 10000")
    if not text.startswith("---\n"):
        err("SKILL.md missing YAML frontmatter")
    if "disable-model-invocation: false" not in text:
        err("Forge must allow explicit-name model invocation")
    if "explicitly mentions Forge" not in text:
        err("Forge description must constrain automatic invocation")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if "://" in target or target.startswith("#"):
            continue
        path = (root / target).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            err(f"skill link escapes package: {target}")
            continue
        if not path.exists():
            err(f"SKILL.md references missing file: {target}")

version_path = root / "VERSION"
version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else None
if not version:
    err("VERSION missing or empty")
elif not re.fullmatch(r"\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?", version):
    err(f"VERSION is not a supported semantic version: {version!r}")

changelog_path = root / "CHANGELOG.md"
if not changelog_path.exists():
    err("CHANGELOG.md missing")
elif version:
    changelog = changelog_path.read_text(encoding="utf-8")
    match = re.search(r"^##\s+(\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?)\s*$", changelog, re.MULTILINE)
    if not match:
        err("CHANGELOG.md has no version heading")
    elif match.group(1) != version:
        err(f"VERSION {version!r} does not match top CHANGELOG version {match.group(1)!r}")

if os.environ.get("GITHUB_REF_TYPE") == "tag" and version:
    ref_name = os.environ.get("GITHUB_REF_NAME", "")
    if ref_name != f"v{version}":
        err(f"git tag {ref_name!r} does not match VERSION-derived tag 'v{version}'")

# Validate distributable JSON, not ignored benchmark results or a contributor's fixtures.
for path in [*(root / "templates").rglob("*.json"), *(root / "evals").glob("*.json")]:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        err(f"invalid JSON {path.relative_to(root)}: {exc}")

for filename, fields in (
    ("evals.json", ("id", "prompt", "expected_output", "expectations")),
    ("bootstrap-evals.json", ("id", "prompt", "expectations")),
    ("dual-agent-evals.json", ("id", "scenario", "expectations")),
):
    path = root / "evals" / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        err(f"cannot read {path.relative_to(root)}: {exc}")
        continue
    if not isinstance(data, dict) or not isinstance(data.get("evals"), list):
        err(f"{filename} must contain an object with an evals array")
        continue
    if filename == "evals.json" and data.get("skill_name") != "forge":
        err("evals skill_name mismatch")
    ids: set[str | int] = set()
    for index, item in enumerate(data["evals"]):
        label = f"{filename} eval {index + 1}"
        if not isinstance(item, dict):
            err(f"{label} must be an object")
            continue
        for key in fields:
            if key not in item:
                err(f"{label} missing {key}")
        identifier = item.get("id")
        if type(identifier) not in (str, int) or identifier == "":
            err(f"{label} id must be a nonempty string or integer")
        elif identifier in ids:
            err(f"{label} duplicate id {identifier}")
        else:
            ids.add(identifier)
        expectations = item.get("expectations")
        if not isinstance(expectations, list) or not expectations or any(
            not isinstance(value, str) or not value.strip() for value in expectations
        ):
            err(f"{label} must have nonempty text expectations")

validator = root / "templates" / "validate-project-control.py"
example = root / "templates" / "project-control.example.json"
if validator.exists() and example.exists():
    completed = subprocess.run(
        [sys.executable, str(validator), str(example)],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        err("control example failed validator: " + (completed.stderr.strip() or completed.stdout.strip()))
else:
    err("control validator/example missing")

required = [
    "BOOTSTRAP.md",
    "LICENSE",
    "scripts/bootstrap.sh",
    "scripts/install.sh",
    "scripts/forge",
    "scripts/forge-run.py",
    "scripts/adapters/__init__.py",
    "scripts/adapters/base.py",
    "scripts/adapters/claude_code.py",
    "scripts/adapters/codex_cli.py",
    "evals/bootstrap-evals.json",
    "evals/CORE-BENCHMARKS.md",
    "evals/core/README.md",
    "evals/core/run.sh",
    "evals/core/build_fixtures.py",
    "evals/core/fixture_bundle.py",
    "evals/core/container_run.py",
    "evals/core/fixture_bundle.json.gz.b64",
    "evals/core/assert_run.py",
    "evals/core/score_entrypoint.py",
    "evals/core/aggregate.py",
    "evals/core/selftest.py",
    "evals/core/mock_agent.py",
    "evals/core/container/Containerfile",
    "evals/core/container/ScorerContainerfile",
    "tests/test_dual_agent_runner.py",
    "tests/test_benchmark_isolation.py",
    "references/requirements.md",
    "references/architecture-and-structure.md",
    "references/scope-and-plan-control.md",
    "references/consistency-and-convergence.md",
    "references/orchestration.md",
    "references/execution-and-quality.md",
    "references/trust-and-security.md",
    "references/context-and-governance.md",
    "references/full-spectrum-validation.md",
    "references/example-walkthrough.md",
    "references/claude-code-integration.md",
    "references/optional-task-hooks.md",
    "references/user-interaction.md",
    "templates/execution-control-kernel.md",
    "templates/project-control.schema.json",
    "templates/execution-profile.example.json",
    "templates/execution-profile.schema.json",
    "templates/implementation-handoff.schema.json",
    "templates/review-result.schema.json",
    "templates/session-start-control.py",
    "templates/task-completed-control.py",
    "docs/RELEASING.md",
    "docs/runner.md",
    "requirements-dev.txt",
]
for relative in required:
    if not (root / relative).exists():
        err(f"required package file missing: {relative}")

profile_path = root / "templates" / "execution-profile.example.json"
if profile_path.exists():
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(profile, dict):
            raise TypeError("execution profile must be an object")
        runner = runpy.run_path(str(root / "scripts" / "forge-run.py"))
        runner["validate_profile"](profile)
    except (OSError, ValueError, TypeError, RuntimeError, ImportError) as exc:
        err(f"execution profile example is invalid: {exc}")

bundle_path = root / "evals" / "core" / "fixture_bundle.json.gz.b64"
if bundle_path.exists():
    try:
        bundle_bytes = gzip.decompress(base64.b64decode(bundle_path.read_text(encoding="ascii")))
        bundle = json.loads(bundle_bytes.decode("utf-8"))
    except (OSError, EOFError, ValueError, zlib.error) as exc:
        err(f"benchmark fixture bundle is invalid: {exc}")
    else:
        if not isinstance(bundle, dict):
            err("benchmark fixture bundle must be an object")
        else:
            for key in ("full", "overlays", "hidden", "prompts"):
                if not isinstance(bundle.get(key), dict):
                    err(f"benchmark fixture bundle missing object: {key}")
            prompt_keys = set(bundle.get("prompts", {})) if isinstance(bundle.get("prompts"), dict) else set()
            expected_prompts = {"b1", "b2", "b3-stage1", "b3-stage2", "b4"}
            if not expected_prompts.issubset(prompt_keys):
                err(f"benchmark fixture bundle missing prompts: {sorted(expected_prompts - prompt_keys)}")

python_files = [
    *(root / "templates").glob("*.py"),
    *(root / "scripts").glob("*.py"),
    *(root / "scripts" / "adapters").glob("*.py"),
    *(root / "evals" / "core").glob("*.py"),
    *(root / "tests").glob("*.py"),
]
for path in python_files:
    try:
        compile(path.read_bytes(), str(path), "exec")
    except (OSError, SyntaxError) as exc:
        err(f"Python syntax validation failed for {path.relative_to(root)}: {exc}")

shell_files = [root / "evals" / "core" / "run.sh", root / "scripts" / "forge", *(root / "scripts").glob("*.sh")]
for shell_path in shell_files:
    if shell_path.exists():
        completed = subprocess.run(["bash", "-n", str(shell_path)], capture_output=True, check=False, text=True)
        if completed.returncode != 0:
            err(f"shell syntax invalid for {shell_path.relative_to(root)}: {completed.stderr.strip()}")

for launcher in ("forge", "bootstrap.sh", "install.sh"):
    if not os.access(root / "scripts" / launcher, os.X_OK):
        err(f"scripts/{launcher} must be executable")

for warning in warnings:
    print("SKILL WARNING:", warning, file=sys.stderr)
if errors:
    for error in errors:
        print("SKILL ERROR:", error, file=sys.stderr)
    print(f"SKILL INVALID: {len(errors)} error(s), {len(warnings)} warning(s)", file=sys.stderr)
    sys.exit(2)
print(f"SKILL VALID: forge {version} ({len(warnings)} warning(s))")
