"""Read the immutable fixture bundle without creating shared working files."""
from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path


def load_bundle() -> dict:
    encoded = Path(__file__).with_name("fixture_bundle.json.gz.b64").read_bytes()
    value = json.loads(gzip.decompress(base64.b64decode(encoded)))
    if not isinstance(value, dict):
        raise TypeError("fixture bundle must contain a JSON object")
    # The original compressed bundle remains byte-for-byte historical evidence.
    # Supplements add names; they must never silently replace a core fixture.
    supplements = json.loads(Path(__file__).with_name("fixture_supplements.json").read_text())
    for group in ("overlays", "prompts"):
        additions = supplements[group]
        if value[group].keys() & additions.keys():
            raise ValueError(f"supplemental {group} overwrite historical fixtures")
        value[group].update(additions)
    value["supplemental_criteria_version"] = supplements["criteria_version"]
    return value
