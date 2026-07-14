#!/usr/bin/env python3
"""Build pending P5 ablation/reference controls from registry v2 without fake passes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_shadow import ABLATION_IDS, validate_control_evidence  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def build(corpus: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    references = []
    for owner in sorted(registry["owners"], key=lambda item: item["id"]):
        normative = owner["authority"] == "normative_owner"
        references.append({
            "owner_id": owner["id"],
            "authority": owner["authority"],
            "decision_case_status": "not_run" if normative else "not_applicable",
            "precision_case_status": "not_applicable" if normative else "not_run",
            "exclusion_case_status": "not_applicable" if normative else "not_run",
            "ablation_status": "not_run" if normative else "not_applicable",
            "evidence_refs": [],
        })
    controls = {
        "schema_version": "p5-control-evidence/1.0",
        "cohort_id": corpus["cohort_id"],
        "bundle_hash": corpus["bundle_hash"],
        "controller_hash": corpus["controller_hash"],
        "ablations": [
            {"id": item, "status": "not_run", "evidence_refs": []}
            for item in sorted(ABLATION_IDS)
        ],
        "reference_evaluations": references,
    }
    errors = validate_control_evidence(controls, corpus=corpus)
    if errors:
        raise ValueError("generated controls are invalid: " + "; ".join(errors[:12]))
    return controls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "evaluation" / "corpus" / "p5-shadow-corpus.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "p5-control-evidence.json")
    args = parser.parse_args(argv)
    try:
        corpus = load_json(args.corpus)
        registry = load_json(ROOT / "software-quality-workflows" / "references" / "owner-registry.json")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(build(corpus, registry), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
