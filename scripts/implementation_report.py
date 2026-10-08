"""Lossless normalization of implementer claims, independent of agent execution.

The producer contract is templates/implementation-report.schema.json. Runtime
normalization deliberately accepts older reports without upgrading their claims
into observed test evidence. The exact input is retained for local recovery.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

REPORT_FIELDS = {
    "summary", "acceptance_results", "validation", "discoveries", "known_uncertainties",
}
EVIDENCE_FIELDS = (
    "reported_origin", "tested_commit", "command", "cwd", "environment_identity",
    "dependency_identity", "result", "artifact",
)
REPORT_EXAMPLE: dict[str, Any] = {
    "schema_version": 1,
    "summary": "Describe the actual outcome, including incomplete work.",
    "acceptance_results": {"REQ-example": "Describe the check and actual result."},
    "validation": [{
        "claim": "Describe a check you actually ran and what it established.",
        "command": "The exact command, when known; omit otherwise.",
        "result": "The observed result, including failures or limitations.",
    }],
    "discoveries": [{
        "summary": "Describe an actual discovery; use an empty array when there are none.",
        "scope_relevance": "adjacent",
    }],
    "known_uncertainties": ["Describe a real limitation; use an empty array when there are none."],
}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _decode(text: str, issues: list[str]) -> Any:
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0] in {"```", "```json"} and lines[-1] == "```":
        issues.append("Removed a surrounding JSON code fence.")
        stripped = "\n".join(lines[1:-1])
    return json.loads(stripped)


def parse_implementation_report(stdout: str) -> dict[str, Any]:
    """Normalize entries individually and retain every input, including bad ones.

    `structured` describes the original producer contract, not success of the
    implementation. `raw_report` is for local preservation, not prompt injection
    into subsequent agent calls. No provenance or test outcome is inferred.
    """
    issues: list[str] = []
    result: dict[str, Any] = {
        "summary": "", "acceptance_results": {}, "validation": [],
        "discoveries": [], "known_uncertainties": [], "structured": False,
        "report_format": "unstructured", "normalization_issues": issues,
        "raw_report": stdout,
    }
    text = stdout
    try:
        payload = _decode(text, issues)
        # Claude's JSON transport wraps the final report in a `result` string.
        # A direct report takes precedence over transport-like extra fields.
        if isinstance(payload, dict) and not (REPORT_FIELDS & payload.keys()):
            inner = payload.get("result")
            if isinstance(inner, str):
                text = inner
                payload = _decode(text, issues)
    except (json.JSONDecodeError, RecursionError):
        result["summary"] = text
        issues.append("Report is not a JSON object; original text is preserved.")
        return result
    if not isinstance(payload, dict) or not (REPORT_FIELDS & payload.keys()):
        result["summary"] = text
        issues.append("No implementation-report object was found; original text is preserved.")
        return result

    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        issues.append("Missing or unsupported producer schema_version; normalized as a legacy report.")
    summary = payload.get("summary", "")
    result["summary"] = _text(summary)
    if "summary" not in payload or not isinstance(summary, str):
        issues.append("summary must be a string; the supplied value is preserved.")

    acceptance = payload.get("acceptance_results")
    if isinstance(acceptance, dict):
        result["acceptance_results"] = {key: _text(value) for key, value in acceptance.items()}
        for key, value in acceptance.items():
            if not isinstance(value, str):
                issues.append(f"acceptance_results.{key}: retained a non-string value as JSON text.")
    else:
        issues.append("acceptance_results is missing or is not an object; see the original report.")

    for field, label in (("validation", "claim"), ("discoveries", "summary")):
        items = payload.get(field)
        if not isinstance(items, list):
            issues.append(f"{field} is missing or is not an array; supplied value retained.")
            result[field] = [{"unparsed_value": copy.deepcopy(items)}] if field in payload else []
            continue
        entries: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            location = f"{field}[{index}]"
            if isinstance(item, str):
                entries.append({label: item})
                issues.append(f"{location}: normalized a legacy string without inferring evidence.")
            elif isinstance(item, dict):
                entries.append(copy.deepcopy(item))
                if not isinstance(item.get(label), str) or not item[label].strip():
                    issues.append(f"{location}: missing non-empty {label}; original object retained.")
                optional_strings = ("command", "result") if field == "validation" else ("scope_relevance",)
                for key in optional_strings:
                    if key in item and not isinstance(item[key], str):
                        issues.append(f"{location}.{key}: expected a string; original value retained.")
                if field == "validation" and "evidence" in item:
                    evidence = item["evidence"]
                    if not isinstance(evidence, dict):
                        issues.append(f"{location}.evidence: expected an object; original value retained.")
                    else:
                        for key in EVIDENCE_FIELDS:
                            if key in evidence and not isinstance(evidence[key], str):
                                issues.append(f"{location}.evidence.{key}: expected a string; original value retained.")
            else:
                entries.append({"unparsed_value": copy.deepcopy(item)})
                issues.append(f"{location}: retained an unsupported entry as unparsed_value.")
        result[field] = entries

    uncertainties = payload.get("known_uncertainties")
    if isinstance(uncertainties, list):
        result["known_uncertainties"] = [_text(item) for item in uncertainties]
        if any(not isinstance(item, str) for item in uncertainties):
            issues.append("known_uncertainties: retained non-string entries as JSON text.")
    else:
        issues.append("known_uncertainties is missing or is not an array; supplied value retained.")
        if "known_uncertainties" in payload:
            result["known_uncertainties"] = [_text(uncertainties)]
    result["structured"] = not issues
    result["report_format"] = "structured" if result["structured"] else "normalized"
    return result


def evidence_references(validation: Any, reviewed_commit: str) -> list[dict[str, Any]]:
    """Describe reference applicability, never attest to implementer-supplied data.

    Even complete matching metadata requires primary-artifact and environment
    verification by the reviewer/executor. Commands and artifact references are
    data only: this helper does not run, fetch, or automatically reuse anything.
    """
    references: list[dict[str, Any]] = []
    if not isinstance(validation, list):
        return references
    for index, entry in enumerate(validation):
        if not isinstance(entry, dict) or not isinstance(entry.get("evidence"), dict):
            continue
        evidence = entry["evidence"]
        missing = [key for key in EVIDENCE_FIELDS if not isinstance(evidence.get(key), str) or not evidence[key].strip()]
        tested = evidence.get("tested_commit")
        if isinstance(tested, str) and tested and tested != reviewed_commit:
            applicability = "stale_checkpoint"
        elif missing:
            applicability = "incomplete_metadata"
        else:
            applicability = "requires_verification"
        references.append({
            "validation_index": index,
            "reference": copy.deepcopy(evidence),
            "applicability": applicability,
            "missing_fields": missing,
            "trust": "unverified_implementer_supplied_reference",
        })
    return references


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a saved implementation report without running an agent.")
    parser.add_argument("report", type=Path, help="Original agent stdout or a saved report JSON file")
    args = parser.parse_args()
    try:
        raw = args.report.read_bytes().decode("utf-8", "surrogateescape")
        report = parse_implementation_report(raw)
    except OSError as exc:
        parser.exit(2, f"Could not read report: {exc}\n")
    # JSON escaping also preserves surrogateescaped bytes and terminal controls.
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
