#!/usr/bin/env python3
"""Validate Writing Plans cards and generated navigation manifest."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from _writing_reference_cards import ContractIssue, build_manifest, canonical_json_bytes, issue_payload, load_json


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"


def main() -> int:
    try:
        expected, issues = build_manifest(ROOT)
        actual = load_json(MANIFEST)
        if canonical_json_bytes(actual) != canonical_json_bytes(expected):
            issues.append(ContractIssue("manifest.stale", str(MANIFEST), "manifest does not match card bytes"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    if issues:
        print(json.dumps({"ok": False, "issues": issue_payload(issues)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, "cards": len(expected["cards"])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
