#!/usr/bin/env python3
"""Validate SQW card bodies, generated manifest, and navigation graph."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from _workflow_reference_cards import ContractIssue, build_manifest, canonical_json_bytes, issue_payload, load_json
from build_reference_manifest import MANIFEST_RELATIVE, SUPPORT_MAP, build_support_map


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"


def main() -> int:
    try:
        expected, issues = build_manifest(ROOT)
        expected_bytes = canonical_json_bytes(expected)
        actual = load_json(MANIFEST)
        if canonical_json_bytes(actual) != expected_bytes:
            issues.append(ContractIssue("manifest.stale", str(MANIFEST), "manifest does not match card bytes"))
        expected_support = build_support_map(ROOT, {MANIFEST_RELATIVE: expected_bytes})
        if not SUPPORT_MAP.is_file() or SUPPORT_MAP.is_symlink() or SUPPORT_MAP.read_bytes() != expected_support:
            issues.append(ContractIssue("support-map.stale", str(SUPPORT_MAP), "support map does not match formal inventory bytes"))
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
