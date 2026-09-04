#!/usr/bin/env python3
"""Aggregate run.json files under a results dir into REPORT.md. Pure arithmetic; no estimates."""
from __future__ import annotations

import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

NAMES = {"b1": "B1 Scope retention", "b2": "B2 Debug tunnel", "b3": "B3 Context-loss recovery", "b4": "B4 Proportionality"}
COND = {"baseline": "Baseline", "forge": "Forge"}


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return st.median(xs) if xs else None


def sd(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return st.stdev(xs) if len(xs) > 1 else (0.0 if xs else None)


def fmt(x, p=0):
    if x is None:
        return "n/a"
    return f"{x:.{p}f}" if isinstance(x, float) else str(x)


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "n/a"


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0, c - h), min(1, c + h)


def main(out_dir: str):
    root = Path(out_dir)
    runs = [json.loads(path.read_text()) for path in sorted(root.glob("*/*/run-*/run.json"))]
    manifest = json.loads((root / "MANIFEST.json").read_text()) if (root / "MANIFEST.json").exists() else {}
    cells = defaultdict(list)
    for run in runs:
        cells[(run["scenario"], run["condition"])].append(run)
    scenarios = sorted({scenario for scenario, _ in cells})
    conds = [cond for cond in ("baseline", "forge") if any(cond == key[1] for key in cells)]

    lines = []
    lines.append("# Forge core benchmark results\n")
    if manifest.get("mock"):
        lines.append("> **MOCK RUN — harness self-test only. These numbers say nothing about Forge.**\n")
    lines.append(
        f"Forge under test: `{manifest.get('forge_ref')}` (`{manifest.get('forge_commit', '')[:12]}`) · "
        f"verified: `{manifest.get('forge_verified')}` · provenance: `{manifest.get('forge_provenance')}` · "
        f"isolation: `{manifest.get('isolation')}` · agent: `{manifest.get('agent')}` · "
        f"model: `{manifest.get('model')}` · runs/cell: {manifest.get('runs_per_cell')} · seed: `{manifest.get('seed')}` · "
        f"Forge invocation: `{manifest.get('forge_invocation')}`\n"
    )
    lines.append(
        "Pass = every gating assertion true. Tokens = input+output+cache tokens reported by the agent. "
        "Times are wall-clock seconds for the agent session(s); B3 sums both fresh sessions. Variance columns: Wilson 95% CI on pass rate; "
        "stdev for completion, tokens, time. `n/a` means the agent did not report the field.\n"
    )

    lines.append("## Per-scenario results\n")
    lines.append("| Benchmark | Condition | Passes | Runs | Pass rate | 95% CI | Req completion (mean±sd) | Drift | Later work resumed | Median tokens | Median runtime (s) |")
    lines.append("|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|")
    for scenario in scenarios:
        for cond in conds:
            rs = cells.get((scenario, cond), [])
            n = len(rs)
            k = sum(run["pass"] for run in rs)
            ci = wilson(k, n)
            comp = [run["requirements"]["completion_fraction"] for run in rs if run["requirements"]["completion_fraction"] is not None]
            drift = sum(1 for run in rs if run["scope_drift"])
            resumed = [run["later_work_resumed"] for run in rs if run["later_work_resumed"] is not None]
            lines.append(
                f"| {NAMES.get(scenario, scenario)} | {COND.get(cond, cond)} | {k} | {n} | {pct(k, n)} | "
                f"{'n/a' if not ci else f'{ci[0]*100:.0f}–{ci[1]*100:.0f}%'} | "
                f"{'n/a' if not comp else f'{st.mean(comp)*100:.0f}% ± {(sd(comp) or 0)*100:.0f}'} | "
                f"{pct(drift, n)} | {pct(sum(resumed), len(resumed)) if resumed else 'n/a'} | "
                f"{fmt(med([run['tokens_total'] for run in rs]))} | {fmt(med([run['wall_seconds'] for run in rs]), 1)} |"
            )
    lines.append("")

    lines.append("## Aggregate: baseline vs Forge\n")
    lines.append("| Condition | Runs | Passes | Pass rate | 95% CI | Mean req completion | Drift rate | Median tokens | Median runtime (s) | Mean turns |")
    lines.append("|---|---:|---:|---:|---|---:|---:|---:|---:|---:|")
    agg = {}
    for cond in conds:
        rs = [run for (_scenario, cell_cond), values in cells.items() if cell_cond == cond for run in values]
        n, k = len(rs), sum(run["pass"] for run in rs)
        ci = wilson(k, n)
        comp = [run["requirements"]["completion_fraction"] for run in rs if run["requirements"]["completion_fraction"] is not None]
        turns = [run["bureaucracy"]["num_turns"] for run in rs if isinstance(run["bureaucracy"]["num_turns"], int)]
        agg[cond] = {
            "tok": med([run["tokens_total"] for run in rs]),
            "time": med([run["wall_seconds"] for run in rs]),
            "tok_sd": sd([run["tokens_total"] for run in rs]),
            "time_sd": sd([run["wall_seconds"] for run in rs]),
        }
        lines.append(
            f"| {COND[cond]} | {n} | {k} | {pct(k, n)} | {'n/a' if not ci else f'{ci[0]*100:.0f}–{ci[1]*100:.0f}%'} | "
            f"{'n/a' if not comp else f'{st.mean(comp)*100:.0f}%'} | {pct(sum(run['scope_drift'] for run in rs), n)} | "
            f"{fmt(agg[cond]['tok'])} | {fmt(agg[cond]['time'], 1)} | {fmt(st.mean(turns), 1) if turns else 'n/a'} |"
        )
    lines.append("")

    lines.append("## Variance\n")
    lines.append("| Benchmark | Condition | Pass sd (binomial) | Completion sd | Tokens sd | Runtime sd (s) | Min/Max tokens |")
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for scenario in scenarios:
        for cond in conds:
            rs = cells.get((scenario, cond), [])
            n = len(rs)
            p = (sum(run["pass"] for run in rs) / n) if n else 0
            toks = [run["tokens_total"] for run in rs if isinstance(run["tokens_total"], int)]
            comp = [run["requirements"]["completion_fraction"] for run in rs if run["requirements"]["completion_fraction"] is not None]
            lines.append(
                f"| {NAMES.get(scenario, scenario)} | {COND[cond]} | {fmt(math.sqrt(p*(1-p)/n) if n else None, 2)} | "
                f"{fmt(sd(comp), 2)} | {fmt(sd(toks))} | {fmt(sd([run['wall_seconds'] for run in rs]), 1)} | "
                f"{f'{min(toks)}/{max(toks)}' if toks else 'n/a'} |"
            )
    lines.append("")

    lines.append("## Token / time overhead (Forge ÷ baseline, medians)\n")
    if "baseline" in agg and "forge" in agg:
        lines.append("| Benchmark | Tokens ratio | Runtime ratio |")
        lines.append("|---|---:|---:|")
        for scenario in scenarios:
            base_runs, forge_runs = cells.get((scenario, "baseline"), []), cells.get((scenario, "forge"), [])
            bt, ft = med([run["tokens_total"] for run in base_runs]), med([run["tokens_total"] for run in forge_runs])
            bs, fs = med([run["wall_seconds"] for run in base_runs]), med([run["wall_seconds"] for run in forge_runs])
            lines.append(f"| {NAMES.get(scenario, scenario)} | {fmt(ft / bt, 2) if bt and ft else 'n/a'} | {fmt(fs / bs, 2) if bs and fs else 'n/a'} |")
        bt, ft, bs, fs = agg["baseline"]["tok"], agg["forge"]["tok"], agg["baseline"]["time"], agg["forge"]["time"]
        lines.append(f"| **All** | **{fmt(ft / bt, 2) if bt and ft else 'n/a'}** | **{fmt(fs / bs, 2) if bs and fs else 'n/a'}** |")
    else:
        lines.append("Both conditions are needed to compute overhead.")
    lines.append("")

    lines.append("## Assertion pass rates\n")
    keys = sorted({key for run in runs for key in run["assertions"]})
    lines.append("| Benchmark | Assertion | " + " | ".join(COND[cond] for cond in conds) + " |")
    lines.append("|---|---|" + "---:|" * len(conds))
    for scenario in scenarios:
        for key in keys:
            row = []
            present = False
            for cond in conds:
                rs = [run for run in cells.get((scenario, cond), []) if key in run["assertions"]]
                if rs:
                    present = True
                row.append(pct(sum(run["assertions"][key] for run in rs), len(rs)) if rs else "—")
            if present:
                lines.append(f"| {NAMES.get(scenario, scenario)} | `{key}` | " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## Qualitative failure analysis\n")
    lines.append(
        "Every failed run, with the assertions it failed, drift/behaviour notes recorded by the scorer, and the raw evidence to inspect. "
        "Interpretation belongs to the human reviewer; the scorer only reports what it measured.\n"
    )
    any_fail = False
    for scenario in scenarios:
        for cond in conds:
            for run in sorted(cells.get((scenario, cond), []), key=lambda item: item["run"]):
                if run["pass"]:
                    continue
                any_fail = True
                evidence = run.get("evidence", {})
                lines.append(f"- **{NAMES.get(scenario, scenario)} / {COND[cond]} / run {run['run']}** — failed: `{', '.join(run['failed_assertions'])}`")
                for note in run.get("notes", []):
                    lines.append(f"  - {note}")
                if run["requirements"]["tracked"]:
                    lines.append(f"  - requirements passing: {run['requirements']['completed']} of {run['requirements']['tracked']}")
                lines.append(f"  - files: modified {run['changes']['modified']}, added {run['changes']['added']}, deleted {run['changes']['deleted']}")
                lines.append(f"  - evidence: transcript `{evidence.get('transcript')}`, diff `{evidence.get('diff')}`, repo `{evidence.get('repo')}`")
    if not any_fail:
        lines.append("No failed runs.")
    lines.append("")

    lines.append("## Raw evidence index\n")
    lines.append("| Benchmark | Condition | Run | Pass | Tokens | Seconds | run.json |")
    lines.append("|---|---|---:|---|---:|---:|---|")
    for scenario in scenarios:
        for cond in conds:
            for run in sorted(cells.get((scenario, cond), []), key=lambda item: item["run"]):
                lines.append(
                    f"| {scenario} | {cond} | {run['run']} | {'✅' if run['pass'] else '❌'} | {fmt(run['tokens_total'])} | "
                    f"{fmt(run['wall_seconds'], 1)} | `{scenario}/{cond}/run-{run['run']}/run.json` |"
                )
    lines.append("")
    lines.append("Manifest: `MANIFEST.json`. Forge package validation: `forge-validate.log`. Progress log: `progress.log`.")

    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results")
