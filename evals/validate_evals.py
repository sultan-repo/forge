"""Validate evaluation specifications, without executing agents or claiming outcomes."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate(document: object, name: str) -> int:
    if not isinstance(document, dict):
        raise TypeError(f"{name}: document must be an object")
    scenario_suite = document.get("suite") == "forge-dual-agent"
    if document.get("skill_name") != "forge" and not scenario_suite:
        raise ValueError(f"{name}: skill_name must be forge")
    cases = document.get("evals")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{name}: evals must be a nonempty list")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise TypeError(f"{name}: cases must be objects")
        identity = case.get("id")
        if type(identity) not in (str, int) or not str(identity).strip() or str(identity) in seen:
            raise ValueError(f"{name}: missing or duplicate case id {identity!r}")
        seen.add(str(identity))
        for field in (("scenario",) if scenario_suite else ("prompt", "expected_output")):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f"{name}/{identity}: {field} must be nonempty text")
        expectations = case.get("expectations")
        if not isinstance(expectations, list) or not expectations or any(
            not isinstance(item, str) or not item.strip() for item in expectations
        ):
            raise ValueError(f"{name}/{identity}: expectations must contain nonempty text")
        files = case.get("files", [] if scenario_suite else None)
        if not isinstance(files, list) or any(not isinstance(item, str) for item in files):
            raise ValueError(f"{name}/{identity}: files must be a list of paths")
        if "expected_route" in case and case["expected_route"] not in ("quick", "planned", "high-risk", "read-only"):
            raise ValueError(f"{name}/{identity}: invalid expected_route")
        if "sessions" in case and (type(case["sessions"]) is not int or case["sessions"] < 1):
            raise ValueError(f"{name}/{identity}: sessions must be positive")
    return len(cases)


def main() -> None:
    count = sum(validate(json.loads(path.read_text(encoding="utf-8")), path.name)
                for path in sorted(ROOT.glob("*.json")))
    print(f"EVAL SPECIFICATIONS VALID: {count} cases; no model sessions executed, no behavioral results measured.")


if __name__ == "__main__":
    main()
