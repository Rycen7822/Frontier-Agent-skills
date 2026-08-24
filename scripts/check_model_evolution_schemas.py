#!/usr/bin/env python3
"""Validate the versioned model-evolution schema registry."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "evaluation/model-evolution/schemas"
SCHEMAS = {
    "comparison-plan-v4.schema.json": "https://frontier.local/model-evolution/comparison-plan-v4.schema.json",
    "comparison-report-v4.schema.json": "https://frontier.local/model-evolution/comparison-report-v4.schema.json",
    "manual-authority-packet-v1.schema.json": "https://frontier.local/model-evolution/manual-authority-packet-v1.schema.json",
    "sentinel-index-v3.schema.json": "https://frontier.local/model-evolution/sentinel-index-v3.schema.json",
}


def main() -> int:
    for name, expected_id in SCHEMAS.items():
        value = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
        if value.get("$id") != expected_id:
            raise ValueError(f"schema ID differs: {name}")
        Draft202012Validator.check_schema(value)
    print(f"model-evolution schema registry passed: {len(SCHEMAS)} schemas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
