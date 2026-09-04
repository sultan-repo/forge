#!/usr/bin/env python3
"""Materialize benchmark fixture repositories from the compact fixture bundle."""
from __future__ import annotations

import base64
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUNDLE_JSON = ROOT / "fixture_bundle.json"
BUNDLE_B64 = ROOT / "fixture_bundle.json.gz.b64"
OUT = ROOT / "build"

REMOVE = {
    "b1": [
        "src/ledger/importer.py",
        "src/ledger/report.py",
        "src/ledger/budgets.py",
        "src/ledger/export.py",
        "tests/test_importer.py",
        "tests/test_report.py",
        "tests/test_budgets.py",
        "tests/test_export.py",
        "data/budgets.json",
    ],
    "b2": [
        "src/ledger/budgets.py",
        "src/ledger/export.py",
        "tests/test_budgets.py",
        "tests/test_export.py",
        "data/budgets.json",
    ],
    "b3": [
        "src/ledger/budgets.py",
        "src/ledger/export.py",
        "tests/test_budgets.py",
        "tests/test_export.py",
        "data/budgets.json",
    ],
    "b4": [],
}
INHERIT = {"b3": "b2"}
GIT = ["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid"]


def load_bundle() -> dict:
    """Decode the checked-in compact bundle and return its JSON object."""
    encoded = BUNDLE_B64.read_text(encoding="ascii")
    raw = gzip.decompress(base64.b64decode(encoded))
    BUNDLE_JSON.write_bytes(raw)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("fixture bundle must contain a JSON object")
    return value


BUNDLE = load_bundle()


def write_mapping(root: Path, mapping: dict[str, str]) -> None:
    for rel, content in mapping.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def build(name: str) -> Path:
    if name not in REMOVE:
        raise SystemExit(f"unknown fixture: {name}")
    dest = OUT / name
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    write_mapping(dest, BUNDLE["full"])
    for rel in REMOVE[name]:
        (dest / rel).unlink(missing_ok=True)
    for layer in (INHERIT.get(name), name):
        if layer:
            write_mapping(dest, BUNDLE["overlays"].get(layer, {}))
    (dest / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n*.egg-info/\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=dest, check=True)
    subprocess.run(GIT + ["add", "-A"], cwd=dest, check=True)
    subprocess.run(GIT + ["commit", "-q", "-m", f"fixture {name}"], cwd=dest, check=True)
    return dest


if __name__ == "__main__":
    for scenario in (sys.argv[1:] or list(REMOVE)):
        print("built", build(scenario))
