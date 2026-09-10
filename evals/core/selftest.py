#!/usr/bin/env python3
"""Validate mock harness outcomes. This is not a benchmark result."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("results")
parser.add_argument("--expect", choices=("pass", "fail"), required=True)
args = parser.parse_args()
root = Path(args.results)
manifest = json.loads((root / "MANIFEST.json").read_text())
if manifest.get("mock") is not True:
    raise SystemExit("selftest requires a mock manifest")
expected = {
    (scenario, condition, run)
    for scenario in manifest["scenarios"].split(",")
    for condition in manifest["conditions"].split(",")
    for run in range(1, manifest["runs_per_cell"] + 1)
}
runs = [json.loads(path.read_text()) for path in sorted(root.glob("*/*/run-*/run.json"))]
actual = {(run.get("scenario"), run.get("condition"), run.get("run")) for run in runs}
if not expected or actual != expected or len(runs) != len(expected):
    raise SystemExit("mock outcomes do not match the complete declared matrix")
want = args.expect == "pass"
bad = [run for run in runs if bool(run.get("pass")) != want]
if bad:
    raise SystemExit(
        "unexpected mock outcomes: "
        + ", ".join(f"{run['scenario']}/{run['condition']}={run['pass']}" for run in bad)
    )
print(f"SELFTEST OK: {len(runs)} cells all {args.expect.upper()}")
