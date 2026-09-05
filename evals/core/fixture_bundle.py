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
    return value
