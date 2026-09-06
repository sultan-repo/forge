"""Forge project readiness preflight.

The preflight separates durable project execution preferences from local
credential choices, verifies the local Claude/Codex environment, and can make
small live no-edit probes before substantial work begins.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_PREFS = Path(".claude/forge/project-preferences.json")
RUNTIME_DIR = Path(".claude/forge/runtime")
LOCAL_PREFS = RUNTIME_DIR / "local-preferences.json"
REPORT = RUNTIME_DIR / "preflight.json"
EXECUTION_MODES = {"adaptive", "claude_only", "dual_agent"}
CODEX_POLICIES = {"never", "explicit", "high_risk", "substantial"}
AUTH_MODES = {"subscription", "api", "inherit"}
REQUIRED_CODEX_FLAGS = ("--config", "--ignore-user-config", "--ignore-rules")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root(start: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("Run Forge preflight from inside the project Git repository.")
    return Path(completed.stdout.strip()).resolve()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing required file: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def ensure_runtime_excluded(root: Path) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "--git-path", "info/exclude"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return
    raw = completed.stdout.strip()
    path = Path(raw) if Path(raw).is_absolute() else (root / raw).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = ".claude/forge/runtime/"
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker not in current.splitlines():
        with path.open("a", encoding="utf-8") as handle:
            if current and not current.endswith("\n"):
                handle.write("\n")
            handle.write(marker + "\n")


def validate_project_preferences(value: dict[str, Any]) -> None:
    expected = {
        "version",
        "execution_mode",
        "claude_model_policy",
        "codex_review_policy",
        "live_preflight_required",
    }
    if set(value) != expected:
        raise RuntimeError("Project preflight preferences have missing or unsupported fields.")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise RuntimeError("Unsupported project preflight preference version.")
    if value.get("execution_mode") not in EXECUTION_MODES:
        raise RuntimeError("Unsupported execution_mode in project preferences.")
    if value.get("claude_model_policy") != "current_cli":
        raise RuntimeError("claude_model_policy must currently be current_cli.")
    if value.get("codex_review_policy") not in CODEX_POLICIES:
        raise RuntimeError("Unsupported codex_review_policy in project preferences.")
    if not isinstance(value.get("live_preflight_required"), bool):
        raise TypeError("live_preflight_required must be boolean.")
    if value["execution_mode"] == "claude_only" and value["codex_review_policy"] != "never":
        raise RuntimeError("claude_only execution requires codex_review_policy=never.")
    if value["execution_mode"] == "dual_agent" and value["codex_review_policy"] != "substantial":
        raise RuntimeError("dual_agent execution requires codex_review_policy=substantial.")


def validate_local_preferences(value: dict[str, Any]) -> None:
    if set(value) != {"version", "claude_authentication"}:
        raise RuntimeError("Local preflight preferences have missing or unsupported fields.")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise RuntimeError("Unsupported local preflight preference version.")
    if value.get("claude_authentication") not in AUTH_MODES:
        raise RuntimeError("Unsupported Claude authentication preference.")


def choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> str:
    print(prompt)
    for index, (_, label) in enumerate(options, 1):
        suffix = " [recommended]" if index == default else ""
        print(f"  {index}. {label}{suffix}")
    while True:
        answer = input(f"Choose [{default}]: ").strip()
        if not answer:
            answer = str(default)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        print("Enter one of the listed numbers.")


def yes_no(prompt: str, default: bool = True) -> bool:
    marker = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{marker}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Enter yes or no.")


def configure(root: Path) -> int:
    if not sys.stdin.isatty():
        print("Interactive configuration requires a terminal. Ask Forge in Claude Code to configure preflight preferences instead.")
        return 2
    print("Forge Project Preflight Setup")
    execution = choose(
        "How should Forge execute substantial work?",
        [
            ("adaptive", "Adaptive: Claude normally, Codex review when policy requires it"),
            ("claude_only", "Claude only"),
            ("dual_agent", "Claude implementation + Codex review for substantial work"),
        ],
    )
    if not yes_no("Keep the current Claude Code model selection for this project?", True):
        print("Set the desired model in Claude Code first, then run preflight configuration again.")
        return 2
    if execution == "claude_only":
        codex_policy = "never"
    elif execution == "dual_agent":
        codex_policy = "substantial"
    else:
        codex_policy = choose(
            "When should Forge require independent Codex review?",
            [
                ("high_risk", "High-risk work only"),
                ("substantial", "Every substantial planned/high-risk implementation"),
                ("explicit", "Only when I explicitly request Codex review"),
                ("never", "Never"),
            ],
        )
    authentication = choose(
        "How should Claude Code authenticate for this project on this machine?",
        [
            ("subscription", "Existing Claude subscription login; API-key override must be absent"),
            ("api", "Anthropic API key billing"),
            ("inherit", "Inherit whatever the current shell/CLI uses"),
        ],
    )
    live_required = yes_no("Require a successful live Claude/Codex readiness probe before substantial work?", True)
    project = {
        "version": 1,
        "execution_mode": execution,
        "claude_model_policy": "current_cli",
        "codex_review_policy": codex_policy,
        "live_preflight_required": live_required,
    }
    local = {"version": 1, "claude_authentication": authentication}
    validate_project_preferences(project)
    validate_local_preferences(local)
    ensure_runtime_excluded(root)
    atomic_json(root / PROJECT_PREFS, project)
    atomic_json(root / LOCAL_PREFS, local)
    print(f"Saved project preferences: {PROJECT_PREFS}")
    print("Saved local authentication preference under .claude/forge/runtime (not for commit).")
    print("Run `scripts/forge preflight --live` before substantial implementation.")
    return 0


def command_result(
    command: list[str],
    cwd: Path,
    *,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 125, "", str(exc))


def version_of(binary: str, cwd: Path) -> str | None:
    path = shutil.which(binary)
    if not path:
        return None
    result = command_result([binary, "--version"], cwd)
    if result.returncode != 0:
        return None
    return (result.stdout.strip() or result.stderr.strip()).splitlines()[0][:200]


def collect_models(value: object) -> list[str]:
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                normalized = key.lower().replace("-", "_")
                if normalized in {"model", "model_id", "model_name"} and isinstance(child, str) and child.strip():
                    found.add(child.strip())
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(found)


def preferences_digest(project: dict[str, Any], local: dict[str, Any]) -> str:
    canonical = json.dumps({"project": project, "local": local}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prior_live_is_reusable(
    prior: dict[str, Any] | None,
    digest: str,
    claude_version: str | None,
    codex_version: str | None,
    api_override: bool,
) -> bool:
    if not prior or prior.get("status") != "READY" or prior.get("live_verified") is not True:
        return False
    if prior.get("preferences_sha256") != digest:
        return False
    environment = prior.get("environment")
    if not isinstance(environment, dict):
        return False
    return (
        environment.get("claude_version") == claude_version
        and environment.get("codex_version") == codex_version
        and environment.get("anthropic_api_key_present") is api_override
    )


def evaluate(root: Path, *, live: bool) -> tuple[str, dict[str, Any], list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []
    project_path = root / PROJECT_PREFS
    local_path = root / LOCAL_PREFS
    if not project_path.exists():
        blockers.append("Project preferences are missing. Run `scripts/forge preflight --configure` or `/forge preflight`.")
        return "BLOCKED", {}, blockers, warnings
    if not local_path.exists():
        blockers.append("Local authentication preference is missing. Run preflight configuration on this machine.")
        return "BLOCKED", {}, blockers, warnings
    try:
        project = read_json(project_path)
        local = read_json(local_path)
        validate_project_preferences(project)
        validate_local_preferences(local)
    except (RuntimeError, TypeError) as exc:
        blockers.append(str(exc))
        return "BLOCKED", {}, blockers, warnings

    claude_version = version_of("claude", root)
    codex_needed = project["codex_review_policy"] != "never"
    codex_version = version_of("codex", root) if codex_needed else None
    api_override = bool(os.environ.get("ANTHROPIC_API_KEY"))
    auth_mode = local["claude_authentication"]
    if claude_version is None:
        blockers.append("Claude Code is not installed or could not start.")
    elif auth_mode == "subscription":
        if api_override:
            blockers.append("ANTHROPIC_API_KEY is present but this project is configured for Claude subscription authentication.")
        auth = command_result(["claude", "auth", "status"], root)
        if auth.returncode != 0:
            blockers.append("Claude subscription login could not be verified. Run `claude` and use `/login`.")
    elif auth_mode == "api":
        if not api_override:
            blockers.append("This machine is configured for Anthropic API-key billing, but ANTHROPIC_API_KEY is not present.")
    elif api_override:
        warnings.append("ANTHROPIC_API_KEY is active under inherited authentication and may override a subscription login.")
    else:
        auth = command_result(["claude", "auth", "status"], root)
        if auth.returncode != 0:
            blockers.append("Inherited Claude authentication is not currently usable.")

    if codex_needed:
        if codex_version is None:
            blockers.append("Codex review is configured but Codex CLI is not installed or could not start.")
        else:
            login = command_result(["codex", "login", "status"], root)
            if login.returncode != 0:
                blockers.append("Codex review is configured but Codex is not signed in. Run `codex login`.")
            help_result = command_result(["codex", "exec", "--help"], root)
            help_text = f"{help_result.stdout}\n{help_result.stderr}"
            if help_result.returncode != 0 or any(flag not in help_text for flag in REQUIRED_CODEX_FLAGS):
                blockers.append("Codex CLI is too old for Forge's isolated high-reasoning reviewer mode.")

    digest = preferences_digest(project, local)
    prior: dict[str, Any] | None = None
    try:
        if (root / REPORT).exists():
            prior = read_json(root / REPORT)
    except (RuntimeError, TypeError):
        prior = None
    live_verified = prior_live_is_reusable(prior, digest, claude_version, codex_version, api_override)
    models: list[str] = []

    if not blockers and live:
        env = os.environ.copy()
        if auth_mode == "subscription":
            env.pop("ANTHROPIC_API_KEY", None)
        claude = command_result(
            [
                "claude",
                "-p",
                "Reply with exactly FORGE_CLAUDE_READY and nothing else.",
                "--output-format",
                "json",
                "--max-turns",
                "1",
            ],
            root,
            env=env,
            timeout=120,
        )
        if claude.returncode != 0:
            blockers.append("Live Claude readiness probe failed: " + (claude.stderr.strip() or claude.stdout.strip())[-300:])
        else:
            try:
                payload = json.loads(claude.stdout)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("is_error") is True:
                blockers.append("Live Claude readiness probe returned a provider error.")
            if payload is not None:
                models = collect_models(payload)
        if codex_needed and not blockers:
            codex = command_result(
                [
                    "codex",
                    "--ask-for-approval",
                    "never",
                    "exec",
                    "--json",
                    "--config",
                    'model_reasoning_effort="high"',
                    "--sandbox",
                    "read-only",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--color",
                    "never",
                    "-",
                ],
                root,
                stdin="Reply with exactly FORGE_CODEX_READY and do not modify or inspect project files.",
                timeout=120,
            )
            if codex.returncode != 0:
                blockers.append("Live Codex high-reasoning readiness probe failed: " + (codex.stderr.strip() or codex.stdout.strip())[-300:])
        live_verified = not blockers

    if not blockers and project["live_preflight_required"] and not live_verified:
        warnings.append("A live readiness probe is required before substantial work. Run `scripts/forge preflight --live`.")

    status = "BLOCKED" if blockers else ("READY_WITH_WARNINGS" if warnings else "READY")
    report = {
        "version": 1,
        "checked_at": utc_now(),
        "status": status,
        "live_verified": live_verified,
        "preferences_sha256": digest,
        "project_preferences": project,
        "environment": {
            "claude_version": claude_version,
            "claude_authentication": auth_mode,
            "claude_models_reported": models,
            "codex_version": codex_version,
            "codex_reasoning_effort": "high" if codex_needed else None,
            "codex_review_required": codex_needed,
            "anthropic_api_key_present": api_override,
        },
        "warnings": warnings,
        "blockers": blockers,
    }
    return status, report, blockers, warnings


def print_report(status: str, report: dict[str, Any], blockers: list[str], warnings: list[str]) -> None:
    environment = report.get("environment", {}) if report else {}
    project = report.get("project_preferences", {}) if report else {}
    print("Forge Project Preflight")
    if project:
        print(f"- Execution: {project.get('execution_mode')}")
        print(f"- Codex policy: {project.get('codex_review_policy')}")
    if environment:
        print(f"- Claude: {environment.get('claude_version') or 'unavailable'}")
        print(f"- Claude auth: {environment.get('claude_authentication')}")
        models = environment.get("claude_models_reported") or []
        print(f"- Claude model: {', '.join(models) if models else 'current CLI selection'}")
        if environment.get("codex_review_required"):
            print(f"- Codex: {environment.get('codex_version') or 'unavailable'}")
            print("- Codex review: read-only, reasoning=high")
    for message in warnings:
        print(f"WARNING: {message}")
    for message in blockers:
        print(f"BLOCKED: {message}")
    print(status)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge preflight", description="Verify Forge project execution readiness")
    parser.add_argument("--configure", action="store_true", help="ask the project setup questions and save preferences")
    parser.add_argument("--live", action="store_true", help="make minimal live Claude/Codex no-edit readiness probes")
    parser.add_argument("--json", action="store_true", help="print the readiness report as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = repo_root(Path.cwd())
        if args.configure:
            return configure(root)
        ensure_runtime_excluded(root)
        status, report, blockers, warnings = evaluate(root, live=args.live)
        if report:
            atomic_json(root / REPORT, report)
        if args.json:
            print(json.dumps(report or {"status": status, "blockers": blockers, "warnings": warnings}, indent=2))
        else:
            print_report(status, report, blockers, warnings)
        return {"READY": 0, "READY_WITH_WARNINGS": 1, "BLOCKED": 2}[status]
    except (RuntimeError, TypeError, OSError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
