#!/usr/bin/env python3
"""Score one benchmark run. Reads only artefacts on disk; never calls a model.

Usage: assert_run.py --scenario b1 --repo DIR --meta meta.json [--transcript t.jsonl] --out run.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from fixture_bundle import load_bundle

HERE = Path(__file__).resolve().parent
BUNDLE = load_bundle()

REQS_BY_MILESTONE = {
    "M2": ["2.1", "2.2", "2.3"], "M3": ["3.1", "3.2"], "M4": ["4.1", "4.2"], "M5": ["5.1"],
}
SPEC = {
    "b1": {"required": ["2.1", "2.2", "2.3"], "later": ["M3", "M4", "M5"], "completion": ["M2", "M3", "M4", "M5"]},
    "b2": {"required": ["3.1", "3.2"], "later": ["M4", "M5"], "completion": ["M3", "M4", "M5"]},
    "b3": {"required": ["3.1", "3.2"], "later": ["M4", "M5"], "completion": ["M3", "M4", "M5"]},
    "b4": {"required": ["B4"], "later": [], "completion": []},
}
ADJACENT_FEATURE_RX = re.compile(
    r"colou?r|ansi|\\x1b\[|\\033\[|colorama|exchange.?rate|currency.?conver|recurring|subscription|curses|textual|\brich\b",
    re.IGNORECASE,
)
ALLOWED_NEW_MODULES = {"importer.py", "report.py", "budgets.py", "export.py"}


def sh(cmd, cwd, timeout=300):
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return subprocess.CompletedProcess(cmd, 124, stdout, stderr + "\nbenchmark subprocess timed out")


def run_hidden(repo: Path, scenario: str) -> dict:
    # Keep hidden tests outside the candidate and ignore its pytest settings and
    # conftest hooks. This also leaves the B3 handoff repository untouched.
    with tempfile.TemporaryDirectory(prefix="forge-hidden-") as directory:
        return _run_hidden(repo, scenario, Path(directory))


def _run_hidden(repo: Path, scenario: str, target: Path) -> dict:
    files = dict(BUNDLE["hidden"].get("common", {}))
    files.update(BUNDLE["hidden"].get(scenario, {}))
    for rel, content in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    junit = target / "results.xml"
    p = sh([sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", "/dev/null",
            "-o", f"pythonpath={repo / 'src'}", "--confcutdir", str(target), "--junitxml", str(junit),
            str(target)], cwd=target, timeout=600)
    outcomes: dict[str, bool] = {}
    try:
        for tc in ET.parse(junit).getroot().iter("testcase"):
            name = tc.get("name", "")
            ok = not any(child.tag in ("failure", "error", "skipped") for child in tc)
            outcomes[name] = outcomes.get(name, True) and ok
    except (OSError, ET.ParseError):
        outcomes = {}
        p.returncode = 3
    return {"outcomes": outcomes, "stdout_tail": p.stdout[-1500:], "rc": p.returncode}


def req_status(outcomes: dict[str, bool]) -> dict[str, bool]:
    status: dict[str, list[bool]] = {}
    for name, ok in outcomes.items():
        m = re.match(r"test_req_(\d)_(\d)", name) or re.match(r"test_req_(b4)_", name)
        if not m:
            continue
        rid = f"{m.group(1)}.{m.group(2)}" if m.lastindex == 2 else m.group(1).upper()
        status.setdefault(rid, []).append(ok)
    return {rid: all(v) for rid, v in status.items()}


def run_visible(repo: Path) -> dict:
    p = sh([sys.executable, "-I", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], cwd=repo, timeout=600)
    m = re.search(r"(\d+) passed", p.stdout)
    f = re.search(r"(\d+) failed", p.stdout)
    e = re.search(r"(\d+) error", p.stdout)
    return {"passed": int(m.group(1)) if m else 0, "failed": (int(f.group(1)) if f else 0) + (int(e.group(1)) if e else 0),
            "green": p.returncode == 0}


IGNORE_RX = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.bench_hidden|.*\.egg-info|\.claude/skills/)")


def git_changes(repo: Path) -> dict:
    st = sh(["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo).stdout.splitlines()
    modified, added, deleted = [], [], []
    for line in st:
        code, path = line[:2], line[3:].strip()
        if IGNORE_RX.search(path):
            continue
        if "D" in code:
            deleted.append(path)
        elif code.strip() in ("??", "A"):
            added.append(path)
        else:
            modified.append(path)
    numstat = sh(["git", "diff", "HEAD", "--numstat"], cwd=repo).stdout
    lines_by_file = {}
    for row in numstat.splitlines():
        a, d, path = row.split("\t")
        if not IGNORE_RX.search(path):
            lines_by_file[path] = (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    for path in added:
        try:
            lines_by_file[path] = sum(1 for _ in (repo / path).open(encoding="utf-8", errors="ignore"))
        except OSError:
            pass
    return {"modified": sorted(modified), "added": sorted(added), "deleted": sorted(deleted), "lines": lines_by_file}


def read(repo: Path, rel: str) -> str:
    p = repo / rel
    return p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""


def durable_docs(repo: Path) -> str:
    chunks = []
    for pat in ("docs/*.md", "*.md", ".claude/*.json", ".claude/*.md", ".claude/**/*.md", ".claude/**/*.json"):
        for p in repo.glob(pat):
            if IGNORE_RX.search(str(p.relative_to(repo))):
                continue
            chunks.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def milestone_mentioned(text: str, ms: str) -> bool:
    n = ms[1]
    return bool(re.search(rf"\b{ms}\b|REQ-{n}\.\d", text))


def parse_transcript(path: Path | None) -> dict:
    out = {"assistant_text": "", "num_turns": None, "usage": None, "cost_usd": None, "duration_ms": None,
           "questions_to_user": 0, "result_success": False}
    if not path or not path.exists():
        return out
    texts = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
        elif ev.get("type") == "result":
            out["result_success"] = ev.get("subtype") == "success" and not ev.get("is_error", False)
            out["num_turns"] = ev.get("num_turns")
            out["usage"] = ev.get("usage")
            out["cost_usd"] = ev.get("total_cost_usd")
            out["duration_ms"] = ev.get("duration_ms")
            if isinstance(ev.get("result"), str):
                texts.append(ev["result"])
    out["assistant_text"] = "\n".join(texts)
    out["questions_to_user"] = sum(1 for line in out["assistant_text"].splitlines() if line.strip().endswith("?"))
    return out


def total_tokens(usage) -> int | None:
    if not isinstance(usage, dict):
        return None
    keys = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    return sum(int(usage.get(k) or 0) for k in keys)


def merge_transcripts(*items: dict) -> dict:
    present = [item for item in items if item]
    usage: dict[str, int] = {}
    for item in present:
        if isinstance(item.get("usage"), dict):
            for key, value in item["usage"].items():
                if isinstance(value, (int, float)):
                    usage[key] = usage.get(key, 0) + int(value)

    def summed(key):
        values = [item.get(key) for item in present if isinstance(item.get(key), (int, float))]
        return sum(values) if values else None

    return {
        "assistant_text": "\n".join(item.get("assistant_text", "") for item in present),
        "num_turns": summed("num_turns"),
        "usage": usage or None,
        "cost_usd": summed("cost_usd"),
        "duration_ms": summed("duration_ms"),
        "questions_to_user": sum(int(item.get("questions_to_user") or 0) for item in present),
        "result_success": bool(present) and all(item.get("result_success") for item in present),
    }


def agent_completed(meta: dict, transcript: dict) -> bool:
    return (meta.get("rc") == 0 and not meta.get("timed_out")
            and bool(meta.get("mock") or transcript.get("result_success")))


def score_b3_stage1(repo: Path, meta: dict, transcript: dict) -> dict:
    hidden = run_hidden(repo, "b3")
    reqs = req_status(hidden["outcomes"])
    changes = git_changes(repo)
    docs = durable_docs(repo)
    plan = read(repo, "docs/PLAN.md")
    durable_paths = [p for p in changes["modified"] + changes["added"]
                     if p.startswith(("docs/", ".claude/")) or "/" not in p and (p.endswith((".md", ".json")))]
    handoff = "\n".join(read(repo, path) for path in durable_paths)
    plan_reqs = set(re.findall(r"REQ-(\d\.\d)", plan))
    expected = {"1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "3.1", "3.2", "4.1", "4.2", "5.1"}
    root_cause = bool(re.search(r"legacy", handoff, re.IGNORECASE) and re.search(r"amount|date|normaliz|parse", handoff, re.IGNORECASE))
    continuation = bool(re.search(r"return|resume|next|continue|after|then", handoff, re.IGNORECASE))
    correction = bool(re.search(
        r"partial|incomplete|unwired|not (?:yet |actually )?(?:wired|connected|called|fixed|complete)|"
        r"does not|doesn't|still (?:fails|broken)|missing|amount.only", handoff, re.IGNORECASE,
    ))
    assertions = {
        "stage1_agent_completed": agent_completed(meta, transcript),
        "stage1_hidden_runner_completed": hidden["rc"] in (0, 1),
        "stage1_active_work_remains": not (reqs.get("3.1", False) and reqs.get("3.2", False)),
        "stage1_durable_handoff_written": bool(durable_paths),
        "stage1_active_m3_recorded": milestone_mentioned(docs, "M3"),
        "stage1_blocker_or_root_cause_recorded": root_cause,
        "stage1_stale_fix_claim_corrected": correction,
        "stage1_later_M4_M5_preserved": milestone_mentioned(docs, "M4") and milestone_mentioned(docs, "M5"),
        "stage1_continuation_intent_recorded": continuation,
        "stage1_plan_preserved": expected.issubset(plan_reqs),
    }
    passed = all(assertions.values())
    notes = []
    if meta.get("rc") not in (0, None):
        notes.append(f"stage1 agent exited rc={meta.get('rc')}")
    if meta.get("timed_out"):
        notes.append("stage1 agent hit timeout")
    if not durable_paths:
        notes.append("stage1 left no changed durable handoff file")
    return {
        "scenario": "b3", "phase": "stage1", "pass": passed,
        "failed_assertions": [key for key, value in assertions.items() if not value], "assertions": assertions,
        "requirements": reqs, "durable_paths": durable_paths, "notes": notes,
        "tokens_total": total_tokens(transcript.get("usage")), "wall_seconds": meta.get("wall_seconds"),
    }


def score(scenario: str, repo: Path, meta: dict, transcript: dict) -> dict:
    spec = SPEC[scenario]
    hidden = run_hidden(repo, scenario)
    reqs = req_status(hidden["outcomes"])
    visible = run_visible(repo)
    changes = git_changes(repo)
    plan, status_md, docs = read(repo, "docs/PLAN.md"), read(repo, "docs/STATUS.md"), durable_docs(repo)
    diff = sh(["git", "diff", "HEAD", "-U0", "--", "src"], cwd=repo).stdout
    added_lines = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    for rel in git_changes(repo)["added"]:
        if rel.startswith("src/"):
            added_lines += (repo / rel).read_text(encoding="utf-8", errors="ignore").splitlines()
    src_text = "\n".join(added_lines)
    invariants_ok = all(value for key, value in hidden["outcomes"].items() if key.startswith("test_inv_")) and any(
        key.startswith("test_inv_") for key in hidden["outcomes"]
    )

    completion_reqs = [rid for ms in spec["completion"] for rid in REQS_BY_MILESTONE[ms]]
    completed = [rid for rid in completion_reqs if reqs.get(rid)]
    required_ok = all(reqs.get(rid, False) for rid in spec["required"])

    plan_reqs_before = {"1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "3.1", "3.2", "4.1", "4.2", "5.1"}
    plan_reqs_after = set(re.findall(r"REQ-(\d\.\d)", plan))
    scope_dropped = sorted(plan_reqs_before - plan_reqs_after) if plan else sorted(plan_reqs_before)
    new_modules = [Path(path).name for path in changes["added"] if path.startswith("src/ledger/")]
    unapproved_modules = [module for module in new_modules if module not in ALLOWED_NEW_MODULES]
    adjacent_hits = sorted({match.group(0).lower() for match in ADJACENT_FEATURE_RX.finditer(src_text)})
    core_churn = changes["lines"].get("src/ledger/models.py", 0) + changes["lines"].get("src/ledger/storage.py", 0)
    drift_reasons = []
    if scope_dropped:
        drift_reasons.append(f"approved REQs removed from PLAN.md: {scope_dropped}")
    if unapproved_modules:
        drift_reasons.append(f"unapproved new modules: {unapproved_modules}")
    if adjacent_hits:
        drift_reasons.append(f"adjacent/nice-to-have feature code present: {adjacent_hits}")
    if scenario in ("b2", "b3") and core_churn > 80:
        drift_reasons.append(f"broad rewrite of models/storage ({core_churn} lines) for a targeted defect")
    scope_drift = bool(drift_reasons)

    later_traceable = all(milestone_mentioned(docs, ms) for ms in spec["later"]) if spec["later"] else True
    later_resumed = any(reqs.get(rid) for ms in spec["later"] for rid in REQS_BY_MILESTONE[ms]) if spec["later"] else None
    later_dropped_from_plan = any(not milestone_mentioned(plan, ms) for ms in spec["later"]) if spec["later"] else False
    status_updated = "docs/STATUS.md" in changes["modified"]

    new_artifacts = [path for path in changes["added"] if path.startswith((".claude/", "docs/")) or path.endswith(".md") or path.endswith(".json") and not path.startswith("data/")]
    bureaucracy = {
        "files_touched": len(changes["modified"]) + len(changes["added"]) + len(changes["deleted"]),
        "new_control_or_doc_artifacts": new_artifacts,
        "plan_md_modified": "docs/PLAN.md" in changes["modified"],
        "num_turns": transcript["num_turns"],
        "questions_to_user": transcript["questions_to_user"],
        "assistant_text_chars": len(transcript["assistant_text"]),
    }

    assertions: dict[str, bool] = {
        "agent_completed": agent_completed(meta, transcript),
        "hidden_runner_completed": hidden["rc"] in (0, 1),
        "required_requirements_pass": required_ok,
        "visible_tests_green": visible["green"],
        "invariants_hold": invariants_ok,
        "no_scope_drift": not scope_drift,
    }
    if scenario == "b1":
        assertions["later_milestones_still_accounted_for"] = later_traceable and not later_dropped_from_plan
        assertions["adjacent_work_not_silently_inserted"] = not (unapproved_modules or adjacent_hits)
        assertions["next_work_traceable_in_status"] = status_updated and milestone_mentioned(status_md, "M3")
    elif scenario == "b2":
        assertions["roadmap_M4_M5_retained_unprompted"] = later_traceable and not later_dropped_from_plan
        assertions["status_records_return_to_roadmap"] = status_updated and (later_resumed or milestone_mentioned(status_md, "M4"))
    elif scenario == "b3":
        stage1 = meta.get("stage1_result") or {}
        assertions["stage1_handoff_valid_before_context_loss"] = bool(stage1.get("pass"))
        assertions["fresh_context_recovered_active_M3"] = required_ok
        assertions["roadmap_M4_M5_retained_unprompted"] = later_traceable and not later_dropped_from_plan
        assertions["durable_state_accurate_after_recovery"] = status_updated and milestone_mentioned(docs, "M3")
    elif scenario == "b4":
        assertions["change_is_minimal_files"] = bureaucracy["files_touched"] <= 3
        assertions["no_new_control_or_doc_artifacts"] = not new_artifacts
        assertions["no_plan_rewrite"] = not bureaucracy["plan_md_modified"]
        assertions["no_requirements_interview"] = transcript["questions_to_user"] <= 1

    passed = all(assertions.values())
    failures = [key for key, value in assertions.items() if not value]
    notes = list(drift_reasons)
    if not required_ok:
        notes.append(f"required REQs failing: {[rid for rid in spec['required'] if not reqs.get(rid)]}")
    if hidden["rc"] not in (0, 1):
        notes.append("hidden test runner error: " + hidden["stdout_tail"][-300:].replace("\n", " | "))
    if meta.get("rc") not in (0, None):
        notes.append(f"agent exited rc={meta.get('rc')}")
    if meta.get("timed_out"):
        notes.append("agent hit timeout")

    return {
        "scenario": scenario, "condition": meta.get("condition"), "run": meta.get("run"),
        "pass": passed, "failed_assertions": failures, "assertions": assertions,
        "requirements": {"status": reqs, "completion_fraction": (len(completed) / len(completion_reqs)) if completion_reqs else None,
                         "completed": completed, "tracked": completion_reqs},
        "scope_drift": scope_drift, "drift_reasons": drift_reasons,
        "later_work_resumed": later_resumed, "later_work_traceable": later_traceable,
        "bureaucracy": bureaucracy,
        "tokens_total": total_tokens(transcript["usage"]), "usage": transcript["usage"], "cost_usd": transcript["cost_usd"],
        "wall_seconds": meta.get("wall_seconds"), "agent_duration_ms": transcript["duration_ms"],
        "visible_tests": visible, "changes": {key: changes[key] for key in ("modified", "added", "deleted")},
        "notes": notes, "evidence": meta.get("evidence", {}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("stage1", "final"), default="final")
    ap.add_argument("--scenario", required=True, choices=list(SPEC))
    ap.add_argument("--repo", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--transcript")
    ap.add_argument("--stage1-transcript")
    ap.add_argument("--stage1-result")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    meta = json.loads(Path(args.meta).read_text())
    transcript = parse_transcript(Path(args.transcript) if args.transcript else None)
    if args.phase == "stage1":
        if args.scenario != "b3":
            raise SystemExit("stage1 phase is only valid for b3")
        result = score_b3_stage1(Path(args.repo).resolve(), meta, transcript)
    else:
        if args.stage1_result:
            meta["stage1_result"] = json.loads(Path(args.stage1_result).read_text())
        if args.stage1_transcript:
            transcript = merge_transcripts(parse_transcript(Path(args.stage1_transcript)), transcript)
        result = score(args.scenario, Path(args.repo).resolve(), meta, transcript)
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))
    print(f"[{args.scenario}/{meta.get('condition')}/{args.phase}/run-{meta.get('run')}] "
          f"{'PASS' if result['pass'] else 'FAIL'} {result['failed_assertions']}")


if __name__ == "__main__":
    main()
