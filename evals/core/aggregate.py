#!/usr/bin/env python3
"""Aggregate run.json files under a results dir into REPORT.md. Pure arithmetic; no estimates."""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

from assert_run import SCENARIO_CRITERIA, criteria_for

NAMES = {"b1": "B1 Scope retention", "b2": "B2 Debug tunnel", "b3": "B3 Context-loss recovery", "b4": "B4 Proportionality"}
NAMES.update({"b4n": "B4n Export formatting", "b4a": "B4a Conditional change record", "q4": "Q4 Destructive safeguard",
              "s2": "S2 Stale detour recovery", "v1": "V1 Invariant verification claims"})
COND = {"baseline": "Baseline", "forge": "Forge", "candidate": "Candidate"}


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


def main(out_dir: str, by_criteria: bool = False):
    root = Path(out_dir)
    runs = [json.loads(path.read_text()) for path in sorted(root.glob("*/*/run-*/run.json"))]
    if not runs:
        raise SystemExit("no final run.json files found; there are no results to aggregate")
    manifest = json.loads((root / "MANIFEST.json").read_text()) if (root / "MANIFEST.json").exists() else {}
    versions = {run.get("criteria_version") for run in runs}
    if not versions.issubset(set(SCENARIO_CRITERIA.values())) or (len(versions) > 1 and not by_criteria):
        raise SystemExit("criteria versions are missing, mixed, or incompatible; use the scorer/report revision that produced these results")
    scenarios = manifest.get("scenarios", "").split(",")
    criteria_map = manifest.get("criteria_by_scenario")
    if criteria_map is None:
        criteria_map = dict.fromkeys(scenarios, manifest.get("criteria_version"))
    if (not isinstance(criteria_map, dict) or any(scenario not in SCENARIO_CRITERIA or criteria_map.get(scenario) != criteria_for(scenario)
                                                for scenario in scenarios)
            or any(run.get("scenario") not in SCENARIO_CRITERIA or run.get("criteria_version") != criteria_for(run["scenario"]) for run in runs)):
        raise SystemExit("criteria versions do not match the scenario contracts and manifest")
    labels = {criteria_for(scenario) for scenario in scenarios}
    if len(labels) > 1 and not by_criteria:
        raise SystemExit("criteria versions in the manifest are mixed; use --by-criteria")
    if len(labels) > 1:
        for version in sorted(labels):
            render_report(root, [run for run in runs if run["criteria_version"] == version], manifest, version,
                          f"REPORT.{version}.md", f"ALL_RUNS.{version}.json")
        (root / "REPORT.md").write_text("# Benchmark reports by criteria\n\nCriteria are not pooled.\n\n" + "\n".join(
            f"- [{version}](REPORT.{version}.md)" for version in sorted(labels)) + "\n")
    else:
        render_report(root, runs, manifest, next(iter(versions)))


def render_report(root: Path, runs: list[dict], manifest: dict, criteria: str,
                  report_name: str = "REPORT.md", runs_name: str = "ALL_RUNS.json") -> None:
    identities = [(run["scenario"], run["condition"], run["run"]) for run in runs]
    if len(set(identities)) != len(identities):
        raise SystemExit("duplicate scenario/condition/run identities; select one documented primary attempt per cell")
    expected = {(scenario, condition, run)
                for scenario in manifest.get("scenarios", "").split(",")
                if criteria_for(scenario) == criteria
                for condition in manifest.get("conditions", "").split(",")
                for run in range(1, int(manifest.get("runs_per_cell", 0)) + 1)}
    complete = bool(expected) and set(identities) == expected
    cells = defaultdict(list)
    for run in runs:
        cells[(run["scenario"], run["condition"])].append(run)
    scenarios = sorted({scenario for scenario, _ in cells})
    if any(condition not in COND for _scenario, condition in cells):
        raise SystemExit("unknown benchmark condition")
    conds = [cond for cond in COND if any(cond == key[1] for key in cells)]

    lines = []
    lines.append("# Forge core benchmark results\n")
    lines.append(f"Criteria: `{criteria}`. Matrix: **{'complete' if complete else 'INCOMPLETE — provisional results only'}** ({len(runs)} / {len(expected)} cells).\n")
    if manifest.get("mock"):
        lines.append("> **MOCK RUN — harness self-test only. These numbers say nothing about Forge.**\n")
    lines.append(
        f"Forge under test: `{manifest.get('forge_ref')}` (`{manifest.get('forge_commit', '')[:12]}`) · "
        f"verified: `{manifest.get('forge_verified')}` · provenance: `{manifest.get('forge_provenance')}` · "
        f"isolation: `{manifest.get('isolation')}` · agent: `{manifest.get('agent')}` · "
        f"requested model: `{manifest.get('model')}` · runs/cell: {manifest.get('runs_per_cell')} · seed: `{manifest.get('seed')}` · "
        f"Forge invocation: `{manifest.get('forge_invocation')}`\n"
    )
    models = sorted({model for run in runs for model in run.get("models", [])})
    lines.append("Reported model IDs: " + (", ".join(f"`{model}`" for model in models) or "not reported") + ". See each run.json for its models.\n")
    lines.append(
        "Pass = every automated gating assertion true; semantic scope, state accuracy, and process review remain pending. "
        "Tokens = input+output+cache tokens reported by the agent. Provider cost estimates are informational, not billing or subscription charges. "
        "Times are wall-clock seconds for the agent session(s); B3 sums both fresh sessions. Variance columns: Wilson 95% CI on pass rate; "
        "stdev for completion, tokens, time. `n/a` means the agent did not report the field.\n"
    )

    lines.append("## Per-scenario results\n")
    lines.append("| Benchmark | Condition | Passes | Runs | Pass rate | 95% CI | Req completion (mean±sd) | Detected scope loss | Later requirements passing | Median tokens | Median runtime (s) |")
    lines.append("|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|")
    for scenario in scenarios:
        for cond in conds:
            rs = cells.get((scenario, cond), [])
            n = len(rs)
            k = sum(run["pass"] for run in rs)
            ci = wilson(k, n)
            comp = [run["requirements"]["completion_fraction"] for run in rs if run["requirements"]["completion_fraction"] is not None]
            drift = sum(1 for run in rs if run["scope_drift"])
            resumed = [run["later_requirements_passing"] for run in rs if run["later_requirements_passing"] is not None]
            lines.append(
                f"| {NAMES.get(scenario, scenario)} | {COND.get(cond, cond)} | {k} | {n} | {pct(k, n)} | "
                f"{'n/a' if not ci else f'{ci[0]*100:.0f}–{ci[1]*100:.0f}%'} | "
                f"{'n/a' if not comp else f'{st.mean(comp)*100:.0f}% ± {(sd(comp) or 0)*100:.0f}'} | "
                f"{pct(drift, n)} | {pct(sum(resumed), len(resumed)) if resumed else 'n/a'} | "
                f"{fmt(med([run['tokens_total'] for run in rs]))} | {fmt(med([run['wall_seconds'] for run in rs]), 1)} |"
            )
    lines.append("")

    lines.append("## Aggregate by condition\n")
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
    lines.append("| Benchmark | Condition | Pass rate SE (binomial) | Completion sd | Tokens sd | Runtime sd (s) | Min/Max tokens |")
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

    lines.append("## Token / time overhead (ratio of medians to baseline)\n")
    if complete and "baseline" in agg and len(agg) > 1:
        lines.append("| Benchmark | Condition | Tokens ratio | Runtime ratio |")
        lines.append("|---|---|---:|---:|")
        for condition in (cond for cond in conds if cond != "baseline"):
            for scenario in scenarios:
                base_runs, treated_runs = cells.get((scenario, "baseline"), []), cells.get((scenario, condition), [])
                bt, ft = med([run["tokens_total"] for run in base_runs]), med([run["tokens_total"] for run in treated_runs])
                bs, fs = med([run["wall_seconds"] for run in base_runs]), med([run["wall_seconds"] for run in treated_runs])
                lines.append(f"| {NAMES.get(scenario, scenario)} | {COND[condition]} | {fmt(ft / bt, 2) if bt and ft else 'n/a'} | {fmt(fs / bs, 2) if bs and fs else 'n/a'} |")
            bt, ft, bs, fs = agg["baseline"]["tok"], agg[condition]["tok"], agg["baseline"]["time"], agg[condition]["time"]
            lines.append(f"| **All** | {COND[condition]} | **{fmt(ft / bt, 2) if bt and ft else 'n/a'}** | **{fmt(fs / bs, 2) if bs and fs else 'n/a'}** |")
    else:
        lines.append("A complete matrix with both conditions is required for a headline overhead comparison.")
    lines.append("Later requirements passing is final test evidence, not proof that the session resumed that work. Inspect starting state and diffs to establish progress.\n")
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

    (root / report_name).write_text("\n".join(lines) + "\n")
    (root / runs_name).write_text(json.dumps(runs, indent=2) + "\n")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", nargs="?", default="results")
    parser.add_argument("--by-criteria", action="store_true", help="write separate reports; never pool criteria labels")
    args = parser.parse_args()
    main(args.out_dir, args.by_criteria)
