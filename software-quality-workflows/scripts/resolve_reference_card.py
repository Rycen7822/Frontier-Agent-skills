#!/usr/bin/env python3
"""Resolve exactly one declared SQW navigation edge without search."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_reference_cards import BUNDLE_ID, load_json, strict_json_bytes


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"
REQUEST_KEYS = {
    "active_bytes", "active_leases", "bundle_id", "context_budget_bytes",
    "current_card_hash", "current_card_id", "edge_id", "evidence_refs", "facts", "reason",
}


def denial(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def resolve(raw: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw:
        return denial("ROUTE_INPUT_INCOMPLETE", "resolver request must be a non-empty object")
    if set(raw) - REQUEST_KEYS:
        return denial("ROUTE_INPUT_INCOMPLETE", f"unknown request keys: {sorted(set(raw) - REQUEST_KEYS)}")
    for field in ("bundle_id", "current_card_id", "current_card_hash", "edge_id"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            return denial("ROUTE_INPUT_INCOMPLETE", f"{field} is required")
    if raw["bundle_id"] != BUNDLE_ID or manifest.get("bundle_id") != BUNDLE_ID:
        return denial("BUNDLE_MISMATCH", "request and manifest must use the active bundle")
    by_id = {item["card_id"]: item for item in manifest.get("cards", [])}
    current = by_id.get(raw["current_card_id"])
    if current is None:
        return denial("EDGE_NOT_DECLARED", "current card is not in the local manifest")
    if raw["current_card_hash"] != current.get("sha256"):
        return denial("CARD_HASH_STALE", "current card hash does not match the active bundle")
    edge = next((item for item in current.get("neighbors", []) if item.get("edge_id") == raw["edge_id"]), None)
    if edge is None:
        return denial("EDGE_NOT_DECLARED", "edge is not declared by the current card")
    target_id = edge.get("to_card_id")
    if not isinstance(target_id, str) or not target_id.startswith("sqw."):
        return denial("CROSS_SKILL_ARTIFACT_HANDOFF_REQUIRED", "cross-skill navigation requires a typed artifact handoff")
    target = by_id.get(target_id)
    if target is None:
        return denial("TARGET_NOT_MODEL_CARD", "edge target is not a local model card")
    leases = raw.get("active_leases", [])
    if not isinstance(leases, list) or any(not isinstance(item, dict) or not isinstance(item.get("card_id"), str) for item in leases):
        return denial("ROUTE_INPUT_INCOMPLETE", "active_leases must contain card identities")
    active_ids = {item["card_id"] for item in leases}
    if target_id in active_ids or target_id == current["card_id"]:
        return denial("AUTO_CYCLE_FORBIDDEN", "target is already active")
    active_neighbors = len(active_ids - {current["card_id"]})
    if active_neighbors >= current.get("max_active_neighbors", 0):
        return denial("ACTIVE_CARD_LIMIT", "current card has no remaining neighbor lease")
    evidence = raw.get("evidence_refs", [])
    if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item for item in evidence):
        return denial("EVIDENCE_REF_MISSING", "edge resolution requires non-empty evidence references")
    if edge.get("edge_mode") == "semantic" and (not isinstance(raw.get("reason"), str) or not raw["reason"].strip()):
        return denial("SEMANTIC_REASON_MISSING", "semantic edge requires a bounded reason")
    facts = raw.get("facts", {})
    if not isinstance(facts, dict):
        return denial("ROUTE_INPUT_INCOMPLETE", "facts must be an object")
    predicate = edge.get("hard_predicate_id")
    if edge.get("edge_mode") == "hard" and facts.get(predicate) is not True:
        return denial("HARD_PREDICATE_FALSE", f"hard predicate is not true: {predicate}")
    active_bytes = raw.get("active_bytes", 0)
    budget = raw.get("context_budget_bytes", 65536)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (active_bytes, budget)):
        return denial("ROUTE_INPUT_INCOMPLETE", "byte budgets must be non-negative integers")
    if active_bytes + target["bytes"] > budget:
        return denial("CONTEXT_BUDGET_INSUFFICIENT", "target card would exceed the explicit context budget")
    lease_seed = f"{BUNDLE_ID}\0{current['card_id']}\0{current['sha256']}\0{edge['edge_id']}\0{target_id}"
    return {
        "ok": True,
        "bundle_id": BUNDLE_ID,
        "target_card": {key: target[key] for key in ("bytes", "card_id", "path", "sha256")},
        "lease": {
            "card_id": target_id,
            "card_hash": target["sha256"],
            "lease_id": "ctx-" + sha256(lease_seed.encode("utf-8")).hexdigest()[:24],
            "loaded_for": edge["missing_decision"],
            "source_edge_id": edge["edge_id"],
            "expires_when": edge["evict_when"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="-", help="request JSON path or - for stdin")
    args = parser.parse_args(argv)
    try:
        raw_bytes = sys.stdin.buffer.read(2 * 1024 * 1024 + 1) if args.request == "-" else Path(args.request).read_bytes()
        request = strict_json_bytes(raw_bytes, source=args.request)
        result = resolve(request, load_json(MANIFEST))
    except (OSError, ValueError) as exc:
        result = denial("ROUTE_INPUT_INCOMPLETE", str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
