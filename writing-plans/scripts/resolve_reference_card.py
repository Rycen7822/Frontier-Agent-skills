#!/usr/bin/env python3
"""Resolve exactly one declared Writing Plans navigation edge."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from _writing_reference_cards import BUNDLE_ID, load_json, strict_json_bytes


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"
REQUEST_KEYS = {"active_bytes", "active_leases", "bundle_id", "context_budget_bytes", "current_card_hash", "current_card_id", "edge_id", "evidence_refs", "facts", "reason"}


def denial(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def resolve(raw: Any, manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict) or not raw or set(raw) - REQUEST_KEYS:
        return denial("ROUTE_INPUT_INCOMPLETE", "resolver request is empty, malformed, or has unknown keys")
    for field in ("bundle_id", "current_card_id", "current_card_hash", "edge_id"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            return denial("ROUTE_INPUT_INCOMPLETE", f"{field} is required")
    if raw["bundle_id"] != BUNDLE_ID or manifest.get("bundle_id") != BUNDLE_ID:
        return denial("BUNDLE_MISMATCH", "request and manifest bundle differ")
    by_id = {item["card_id"]: item for item in manifest.get("cards", [])}
    current = by_id.get(raw["current_card_id"])
    if current is None:
        return denial("EDGE_NOT_DECLARED", "current card is absent")
    if raw["current_card_hash"] != current.get("sha256"):
        return denial("CARD_HASH_STALE", "current card hash is stale")
    edge = next((item for item in current.get("neighbors", []) if item.get("edge_id") == raw["edge_id"]), None)
    if edge is None:
        return denial("EDGE_NOT_DECLARED", "edge is not declared")
    target_id = edge.get("to_card_id")
    if not isinstance(target_id, str) or not target_id.startswith("wp."):
        return denial("CROSS_SKILL_ARTIFACT_HANDOFF_REQUIRED", "cross-skill transition requires an artifact")
    target = by_id.get(target_id)
    if target is None:
        return denial("TARGET_NOT_MODEL_CARD", "target card is absent")
    leases = raw.get("active_leases", [])
    if not isinstance(leases, list) or any(not isinstance(item, dict) or not isinstance(item.get("card_id"), str) for item in leases):
        return denial("ROUTE_INPUT_INCOMPLETE", "active leases are invalid")
    active_ids = {item["card_id"] for item in leases}
    if target_id in active_ids or target_id == current["card_id"]:
        return denial("AUTO_CYCLE_FORBIDDEN", "target is already active")
    if len(active_ids - {current["card_id"]}) >= current.get("max_active_neighbors", 0):
        return denial("ACTIVE_CARD_LIMIT", "no neighbor lease remains")
    evidence = raw.get("evidence_refs", [])
    if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item for item in evidence):
        return denial("EVIDENCE_REF_MISSING", "evidence references are required")
    if edge.get("edge_mode") == "semantic" and (not isinstance(raw.get("reason"), str) or not raw["reason"].strip()):
        return denial("SEMANTIC_REASON_MISSING", "semantic reason is required")
    facts = raw.get("facts", {})
    if not isinstance(facts, dict):
        return denial("ROUTE_INPUT_INCOMPLETE", "facts must be an object")
    predicate = edge.get("hard_predicate_id")
    if edge.get("edge_mode") == "hard" and facts.get(predicate) is not True:
        return denial("HARD_PREDICATE_FALSE", f"hard predicate is not true: {predicate}")
    active_bytes, budget = raw.get("active_bytes", 0), raw.get("context_budget_bytes", 65536)
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (active_bytes, budget)):
        return denial("ROUTE_INPUT_INCOMPLETE", "byte budgets are invalid")
    if active_bytes + target["bytes"] > budget:
        return denial("CONTEXT_BUDGET_INSUFFICIENT", "target exceeds the context budget")
    seed = f"{BUNDLE_ID}\0{current['card_id']}\0{current['sha256']}\0{edge['edge_id']}\0{target_id}"
    return {
        "ok": True,
        "bundle_id": BUNDLE_ID,
        "target_card": {key: target[key] for key in ("bytes", "card_id", "path", "sha256")},
        "lease": {"card_id": target_id, "card_hash": target["sha256"], "lease_id": "ctx-" + sha256(seed.encode()).hexdigest()[:24], "loaded_for": edge["missing_decision"], "source_edge_id": edge["edge_id"], "expires_when": edge["evict_when"]},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="-")
    args = parser.parse_args(argv)
    try:
        data = sys.stdin.buffer.read(2 * 1024 * 1024 + 1) if args.request == "-" else Path(args.request).read_bytes()
        result = resolve(strict_json_bytes(data, source=args.request), load_json(MANIFEST))
    except (OSError, ValueError) as exc:
        result = denial("ROUTE_INPUT_INCOMPLETE", str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
