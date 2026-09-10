#!/usr/bin/env python3
"""Crash-safe append-only session accounting for the pilot launcher.

Use ``start`` immediately before every session and ``record`` immediately after it. A reserved
invocation counts even when the CLI or launcher crashes before producing a transcript. ``check``
is a read-only diagnostic, not a substitute for the atomic reservation. All started sessions count,
including authentication/network failures. Subscription runs enforce an invocation ceiling only;
provider dollar estimates are informational unless an explicit estimate ceiling is configured.

Provider limits/authentication/network failures return exit 5 from ``record``; the runner preserves
the attempt and pauses. No automatic account, model, credentials, or billing changes are made.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STOP_EXIT = 3
PROVIDER_LIMIT_EXIT = 5
# Provider-limit wording of the pinned Claude Code (usage cap on a subscription, API rate limit, overload).
PROVIDER_LIMIT_RX = re.compile(r"usage limit reached|hit your limit|limit resets|exceeded your usage|rate.?limit(?:ed|_error)?|\b429\b|overloaded|\b529\b",
                               re.IGNORECASE)
SUBSCRIPTION_RX = re.compile(r"usage limit|hit your limit|limit resets|exceeded your usage", re.IGNORECASE)
# The session never reached the provider (network, proxy/TLS interception, DNS, connection refused): the pinned
# Claude Code reports it as "API Error: Unable to connect to API: ..." with terminal_reason api_error and zero usage.
# Credentials the container was given are no longer usable (expired session, revoked or rotated token): the request
# never produced agent work; the run must pause until the operator re-materialises the credentials file.
AUTH_RX = re.compile(r"failed to authenticate|oauth session expired|could not be refreshed|token has been revoked|\b401\b|invalid api key|please run /login|authentication_error",
                     re.IGNORECASE)
UNREACHABLE_RX = re.compile(r"unable to connect to api|self-signed certificate|certificate (?:verify|has expired|chain)|ECONNREFUSED|ECONNRESET|ENOTFOUND|ETIMEDOUT|EAI_AGAIN|fetch failed|network error|socket hang up",
                            re.IGNORECASE)


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    sessions = [e for e in entries if e.get("event") == "session"]
    completed = {e.get("session_id") for e in sessions if e.get("session_id")}
    pending = [e for e in entries if e.get("event") == "session_start" and e["session_id"] not in completed]
    # An interrupted launcher must never forget a started session just because no transcript survived.
    sessions += [dict(e, cost_usd=None, pending=True) for e in pending]
    known = [e for e in sessions if isinstance(e.get("cost_usd"), (int, float))]
    unknown = [e for e in sessions if not isinstance(e.get("cost_usd"), (int, float))]
    return {
        "sessions": len(sessions),
        "pending_sessions": len(pending),
        "by_kind": {kind: sum(1 for e in sessions if e.get("kind") == kind) for kind in ("preflight", "stage1", "stage2", "main")},
        "known_spend_usd": round(sum(float(e["cost_usd"]) for e in known), 4),
        "unknown_usage_sessions": len(unknown),
        "model_mismatches": sum(1 for e in sessions if e.get("model_mismatch")),
        "infrastructure_failures": sum(1 for e in sessions if e.get("infrastructure_failure")),
        "provider_limit_sessions": sum(1 for e in sessions if e.get("provider_limit")),
        "unreachable_sessions": sum(1 for e in sessions if (e.get("provider_limit_detail") or {}).get("kind") in ("unreachable", "auth")),
        "auth_failure_sessions": sum(1 for e in sessions if (e.get("provider_limit_detail") or {}).get("kind") == "auth"),
        "mock_sessions": sum(1 for e in sessions if e.get("mock")),
        "stops": [e for e in entries if e.get("event") == "stop"],
    }


def check(ledger: Path, ceiling: int, usd_ceiling: float | None = None, reserve: float | None = None,
          exclude_unreachable: bool = False) -> tuple[bool, dict[str, Any]]:
    if ceiling < 1 or (usd_ceiling is None) != (reserve is None):
        raise ValueError("positive invocation ceiling and both or neither USD policy values required")
    if usd_ceiling is not None and (not math.isfinite(usd_ceiling) or usd_ceiling <= 0 or not math.isfinite(reserve) or reserve <= 0):
        raise ValueError("USD policy values must be positive finite numbers")
    if exclude_unreachable:
        raise ValueError("every started session counts; excluding failed connection attempts is not supported")
    t = totals(read_ledger(ledger))
    spending_rule = usd_ceiling is not None and reserve is not None
    committed = t["known_spend_usd"] + t["unknown_usage_sessions"] * (reserve or 0.0)
    counted = t["sessions"] - (t["unreachable_sessions"] if exclude_unreachable else 0)
    verdict = {"sessions_recorded": t["sessions"], "sessions_counted": counted,
               "ceiling_counts": "sessions that reached the provider" if exclude_unreachable else "every session",
               "invocation_ceiling": ceiling, "known_spend_usd": t["known_spend_usd"],
               "unknown_usage_sessions": t["unknown_usage_sessions"], "reserve_usd": reserve,
               "committed_usd_if_started": round(committed + (reserve or 0.0), 4) if spending_rule else None,
               "usd_ceiling": usd_ceiling, "spending_rule": "enforced" if spending_rule else "none (provider estimates informational)"}
    if t["stops"]:
        verdict["reason"] = "a stop was already recorded; the run must not continue"
        return False, verdict
    if counted + 1 > ceiling:
        verdict["reason"] = f"starting counted session {counted + 1} would exceed the invocation ceiling {ceiling}"
        return False, verdict
    if spending_rule and committed + reserve > usd_ceiling:
        verdict["reason"] = (f"known spend {t['known_spend_usd']:.2f} + {t['unknown_usage_sessions']} unknown-usage sessions x {reserve:.2f}"
                             f" + reserve {reserve:.2f} exceeds the spending ceiling {usd_ceiling:.2f}")
        return False, verdict
    return True, verdict


def provider_limit(text: str) -> dict[str, Any] | None:
    """Classify provider-limit or provider-unreachable wording; parse a reset time when the message carries one.

    ``kind`` is ``subscription`` (usage cap), ``rate``, ``overloaded``, or ``unreachable`` (the request never reached
    the provider: network, proxy or TLS interception, DNS). All four pause the run; none is an outcome or a Forge failure.
    """
    unreachable = UNREACHABLE_RX.search(text)
    auth = AUTH_RX.search(text)
    if not PROVIDER_LIMIT_RX.search(text) and not unreachable and not auth:
        return None
    if auth and not SUBSCRIPTION_RX.search(text):
        kind = "auth"
        unreachable = auth
    elif unreachable and not SUBSCRIPTION_RX.search(text):
        kind = "unreachable"
    else:
        kind = "subscription" if SUBSCRIPTION_RX.search(text) else ("overloaded" if re.search(r"overloaded|\b529\b", text, re.IGNORECASE) else "rate")
    reset = None
    m = re.search(r"\|\s*(1[5-9]\d{8}|2\d{9})\b", text) or re.search(r"resetsAtSeconds\W+(1[5-9]\d{8}|2\d{9})", text)
    if m:
        reset = int(m.group(1))
    snippet = PROVIDER_LIMIT_RX.search(text) or unreachable
    start = max(0, (snippet.start() if snippet else 0) - 60)
    return {"kind": kind, "reset_at_epoch": reset, "message": text[start:start + 200].strip()}


def parse_session(transcript: Path | None, stderr: Path | None = None) -> dict[str, Any]:
    """Usage, cost, main model, result presence and provider-limit signals from a stream-json transcript."""
    out: dict[str, Any] = {"main_model": None, "models": [], "cost_usd": None, "usage": None, "num_turns": None,
                           "has_init": False, "has_result": False, "result_success": None, "provider_limit": None, "init_model": None, "main_models": [], "has_agent_work": False}
    error_texts: list[str] = []
    if stderr and stderr.exists():
        error_texts.append(stderr.read_text(encoding="utf-8", errors="ignore")[-4000:])
    if not transcript or not transcript.exists():
        limit = provider_limit("\n".join(error_texts))
        out["provider_limit"] = limit
        return out
    models: set[str] = set()
    principal_models: set[str] = set()
    for line in transcript.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            out["has_init"] = True
            if isinstance(ev.get("model"), str):
                out["init_model"] = ev["model"]
                out["main_model"] = ev["model"]
        elif ev.get("type") == "assistant" and isinstance(ev.get("message"), dict):
            model = ev["message"].get("model")
            if isinstance(model, str) and model.strip():
                models.add(model)
                if not ev.get("parent_tool_use_id"):
                    principal_models.add(model)
                    if ev["message"].get("content"):
                        out["has_agent_work"] = True
                    out["main_model"] = model
        elif ev.get("type") == "result":
            out["has_result"] = True
            out["result_success"] = ev.get("subtype") == "success" and not ev.get("is_error", False)
            if ev.get("is_error") or ev.get("subtype") != "success":
                error_texts.append(json.dumps(ev)[:4000])
            cost = ev.get("total_cost_usd")
            out["cost_usd"] = cost if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0 else None
            out["usage"] = ev.get("usage") if isinstance(ev.get("usage"), dict) else None
            if isinstance((out["usage"] or {}).get("output_tokens"), (int, float)) and out["usage"]["output_tokens"] > 0:
                out["has_agent_work"] = True
            out["num_turns"] = ev.get("num_turns")
            model_usage = ev.get("modelUsage")
            if isinstance(model_usage, dict):
                models.update(m for m in model_usage if isinstance(m, str))
    out["models"] = sorted(models)
    out["main_models"] = sorted(principal_models) or ([out["init_model"]] if out["init_model"] else [])
    out["provider_limit"] = provider_limit("\n".join(error_texts)) if error_texts else None
    return out


def session_id(kind: str, cell: str, out_dir: Path | None, transcript: Path | None = None) -> str:
    identity = str(out_dir.resolve()) if out_dir else str(transcript.resolve()) if transcript else cell
    return hashlib.sha256(f"{kind}\0{cell}\0{identity}".encode()).hexdigest()


@contextlib.contextmanager
def ledger_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def append(path: Path, entry: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def start(ledger: Path, ceiling: int, kind: str, cell: str, out_dir: Path,
          usd_ceiling: float | None = None, reserve: float | None = None) -> tuple[bool, dict[str, Any]]:
    """Atomically reserve and count an invocation before dispatch, including a later process crash."""
    identity = session_id(kind, cell, out_dir)
    with ledger_lock(ledger):
        entries = read_ledger(ledger)
        if any(e.get("session_id") == identity for e in entries):
            return False, {"reason": "session already started; preserve it and recover or use a new authorized attempt"}
        ok, verdict = check(ledger, ceiling, usd_ceiling, reserve)
        if not ok:
            append(ledger, {"event": "stop", "recorded_utc": datetime.now(timezone.utc).isoformat(), **verdict})
            return False, verdict
        append(ledger, {"event": "session_start", "session_id": identity, "kind": kind, "cell": cell,
                        "out_dir": str(out_dir.resolve()), "recorded_utc": datetime.now(timezone.utc).isoformat()})
        return True, dict(verdict, session_id=identity)


def record(ledger: Path, kind: str, cell: str, transcript: Path | None, rc: int | None, pinned_model: str | None,
           mock_usd: float | None, out_dir: Path | None, stderr: Path | None = None, repaired: bool = False) -> dict[str, Any]:
    session = parse_session(transcript, stderr)
    mock = mock_usd is not None
    entry: dict[str, Any] = {
        "event": "session", "session_id": session_id(kind, cell, out_dir, transcript),
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "kind": kind, "cell": cell,
        "rc": rc, "mock": mock, "transcript": str(transcript.resolve()) if transcript else None,
        "out_dir": str(out_dir.resolve()) if out_dir else None, "pinned_model": pinned_model, **session,
        "repaired": repaired,
    }
    if mock:
        if not math.isfinite(mock_usd) or mock_usd < 0:
            raise ValueError("mock cost must be a nonnegative finite number")
        entry["cost_usd"] = float(mock_usd)
    entry["usage_source"] = "mock (synthetic)" if mock else "transcript result event" if session["cost_usd"] is not None else "missing"
    entry["model_mismatch"] = bool(pinned_model) and not mock and any(model != pinned_model for model in session["main_models"])
    entry["model_unknown"] = bool(pinned_model) and not mock and session["main_model"] is None
    no_session = not session["has_init"] and not session["has_result"]
    entry["provider_limit"] = bool(session.get("provider_limit"))
    entry["provider_limit_detail"] = session.get("provider_limit")
    # Timeouts remain outcomes. Missing model identity after a claimed result is invalid evidence.
    entry["infrastructure_failure"] = entry["model_mismatch"] or (not entry["provider_limit"] and bool(
        rc in (125, 126, 127) or (not mock and rc != 124 and (no_session or entry["model_unknown"]))))
    with ledger_lock(ledger):
        existing = next((e for e in read_ledger(ledger) if e.get("event") == "session" and e.get("session_id") == entry["session_id"]), None)
        if existing:
            if existing.get("transcript") != entry["transcript"] or (rc is not None and existing.get("rc") != rc):
                raise ValueError("conflicting duplicate session record")
            return existing
        append(ledger, entry)
    return entry


def session_kind_and_cell(transcript: Path, pilot_dir: Path) -> tuple[str, str, Path]:
    parts = transcript.relative_to(pilot_dir).parts
    if len(parts) == 3 and parts[1].endswith("-activation-preflight"):
        return "preflight", parts[1].removesuffix("-preflight"), transcript.parent
    if "preflight" in parts:
        pos = parts.index("preflight")
        return "preflight", f"{parts[pos + 1]}-activation", transcript.parent
    # attempt-N / scenario / arm / run-N / session|stage1|stage2 / transcript.jsonl
    if len(parts) != 6 or parts[-2] not in ("session", "stage1", "stage2"):
        raise ValueError(f"unrecognised session transcript layout: {transcript}")
    return "main" if parts[-2] == "session" else parts[-2], "/".join(parts[1:4]), transcript.parent


def reconcile(ledger: Path, pilot_dir: Path, pinned_model: str | None = None) -> dict[str, Any]:
    """Append missing result records; preserve unknown exit codes and all pre-dispatch reservations."""
    known = {e.get("transcript") for e in read_ledger(ledger) if e.get("event") == "session"}
    repaired = []
    transcripts = sorted(pilot_dir.glob("attempt-*/**/transcript.jsonl"))
    for transcript in transcripts:
        if str(transcript.resolve()) in known:
            continue
        kind, cell, out_dir = session_kind_and_cell(transcript, pilot_dir)
        mapping = pilot_dir / transcript.relative_to(pilot_dir).parts[0] / "STAGE1_RECOVERY.json"
        if kind == "stage1" and mapping.exists():
            source = json.loads(mapping.read_text()).get(cell)
            if source:
                original = Path(source) / "transcript.jsonl"
                if not original.is_file() or original.read_bytes() != transcript.read_bytes():
                    raise ValueError("restored stage-1 transcript differs from original; refusing duplicate accounting")
                continue  # copied evidence is the original invocation, not a new one
        e = record(ledger, kind, cell, transcript, None, pinned_model, None, out_dir, out_dir / "stderr.txt", repaired=True)
        repaired.append({"cell": cell, "kind": kind, "result_success": e["result_success"], "provider_limit": e["provider_limit"]})
    return {"transcripts_seen": len(transcripts), "already_recorded": len(known), "repaired": repaired, "backup": None}


def record_stop(ledger: Path, verdict: dict[str, Any]) -> None:
    with ledger_lock(ledger):
        append(ledger, {"event": "stop", "recorded_utc": datetime.now(timezone.utc).isoformat(), **verdict})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check")
    c.add_argument("--ledger", required=True)
    c.add_argument("--ceiling", type=int, required=True)
    c.add_argument("--usd-ceiling", type=float)
    c.add_argument("--reserve-usd", type=float)
    c.add_argument("--exclude-unreachable", action="store_true", help="count the ceiling over sessions that reached the provider")
    reserve_parser = sub.add_parser("start")
    reserve_parser.add_argument("--ledger", required=True)
    reserve_parser.add_argument("--ceiling", type=int, required=True)
    reserve_parser.add_argument("--usd-ceiling", type=float)
    reserve_parser.add_argument("--reserve-usd", type=float)
    reserve_parser.add_argument("--kind", choices=("preflight", "stage1", "stage2", "main"), required=True)
    reserve_parser.add_argument("--cell", required=True)
    reserve_parser.add_argument("--out-dir", required=True)
    r = sub.add_parser("record")
    r.add_argument("--ledger", required=True)
    r.add_argument("--kind", choices=("preflight", "stage1", "stage2", "main"), required=True)
    r.add_argument("--cell", required=True)
    r.add_argument("--transcript")
    r.add_argument("--stderr")
    r.add_argument("--rc", type=int, required=True)
    r.add_argument("--pinned-model")
    r.add_argument("--mock-usd", type=float)
    r.add_argument("--out-dir")
    s = sub.add_parser("status")
    s.add_argument("--ledger", required=True)
    rec = sub.add_parser("reconcile")
    rec.add_argument("--ledger", required=True)
    rec.add_argument("--pilot-dir", required=True)
    rec.add_argument("--pinned-model")
    args = parser.parse_args()
    ledger = Path(args.ledger)
    if args.command == "reconcile":
        print(json.dumps(reconcile(ledger, Path(args.pilot_dir), args.pinned_model), indent=2))
        return 0
    if args.command == "start":
        ok, verdict = start(ledger, args.ceiling, args.kind, args.cell, Path(args.out_dir), args.usd_ceiling, args.reserve_usd)
        print(json.dumps(verdict), file=sys.stdout if ok else sys.stderr)
        return 0 if ok else STOP_EXIT
    if args.command == "check":
        ok, verdict = check(ledger, args.ceiling, args.usd_ceiling, args.reserve_usd, args.exclude_unreachable)
        if not ok:
            record_stop(ledger, verdict)
            print(json.dumps(verdict), file=sys.stderr)
            return STOP_EXIT
        return 0
    if args.command == "record":
        entry = record(ledger, args.kind, args.cell, Path(args.transcript) if args.transcript else None, args.rc,
                       args.pinned_model, args.mock_usd, Path(args.out_dir) if args.out_dir else None,
                       Path(args.stderr) if args.stderr else None)
        if entry["model_mismatch"]:
            print(f"model mismatch in {args.cell} ({args.kind}): {entry['main_model']} != {args.pinned_model}", file=sys.stderr)
        if entry["model_mismatch"]:
            return 6
        if entry["provider_limit"]:
            print(json.dumps({"cell": args.cell, "kind": args.kind, **entry["provider_limit_detail"]}))
            return PROVIDER_LIMIT_EXIT
        if entry["model_mismatch"] or (entry["model_unknown"] and args.rc != 124):
            print(f"pinned model identity not established in {args.cell}; refusing further sessions", file=sys.stderr)
            return 6
        if entry["infrastructure_failure"]:
            print(f"infrastructure failure in {args.cell}; only an explicit eligible retry may continue", file=sys.stderr)
            return 7
        return 0
    print(json.dumps(totals(read_ledger(ledger)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
