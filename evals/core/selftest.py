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
runs = [json.loads(path.read_text()) for path in sorted(root.glob("*/*/run-*/run.json"))]
if not runs:
    raise SystemExit("no final run.json files found")
scenarios = {run.get("scenario") for run in runs}
if scenarios != {"b1", "b2", "b3", "b4"}:
    raise SystemExit(f"expected all four scenarios, found {sorted(scenarios)}")
want = args.expect == "pass"
bad = [run for run in runs if bool(run.get("pass")) != want]
if bad:
    raise SystemExit(
        "unexpected mock outcomes: "
        + ", ".join(f"{run['scenario']}/{run['condition']}={run['pass']}" for run in bad)
    )
print(f"SELFTEST OK: {len(runs)} cells all {args.expect.upper()}")
