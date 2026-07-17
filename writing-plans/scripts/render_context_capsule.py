#!/usr/bin/env python3
"""Render a budgeted, sensitivity-aware context capsule for one plan node."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from _plan_state import capsule_source_hash, contains_secret_like, load_json, redact_secret_like
from validate_plan_state import DEFAULT_SCHEMA, validate_file


def _summary(item: dict[str, Any]) -> str:
    object_id = item.get("id", "object")
    if item.get("sensitive") or contains_secret_like(item):
        return f"- {object_id}: [REDACTED]"
    text = item.get("statement") or item.get("claim") or item.get("question") or item.get("objective") or ""
    status = f" ({item['status']})" if item.get("status") else ""
    return f"- {object_id}{status}: {text}"


def _index(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for collection in ("global_invariants", "facts", "decisions", "evidence", "nodes", "risks", "gaps", "approvals", "snapshots"):
        for item in state.get(collection, []):
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                result[item["id"]] = item
    return result


def render(
    state: dict[str, Any],
    node_id: str,
    budget: int,
    *,
    runtime_projection: dict[str, Any] | None = None,
    card_refs: list[dict[str, str]] | None = None,
    projection_spec_id: str = "wp.slicing.context-capsules@1",
) -> tuple[str, dict[str, Any]]:
    objects = _index(state)
    node = objects.get(node_id)
    if not node or not node_id.startswith("P-"):
        raise ValueError(f"node does not exist: {node_id}")
    node_sensitive = bool(node.get("sensitive")) or contains_secret_like(node)
    state_hash = capsule_source_hash(state)
    if card_refs is None:
        manifest = load_json(Path(__file__).resolve().parents[1] / "registries" / "reference-cards.manifest.json")
        card_refs = [
            {"card_id": card["card_id"], "card_hash": card["sha256"]}
            for card in manifest.get("cards", [])
            if card.get("card_id") == "wp.slicing.context-capsules"
        ]
    if not 1 <= len(card_refs) <= 8 or any(
        set(item) != {"card_id", "card_hash"}
        or not str(item.get("card_id", "")).startswith(("wp.", "sqw."))
        or not str(item.get("card_hash", "")).startswith("sha256:")
        for item in card_refs
    ):
        raise ValueError("card_refs must contain one to eight exact card ID/hash bindings")
    if not projection_spec_id.startswith("wp.") or "@" not in projection_spec_id:
        raise ValueError("projection_spec_id must be a versioned WP policy ID")
    effective_budget = min(budget, 8192)
    runtime = runtime_projection or {}
    unknown_runtime = sorted(set(runtime) - {"incumbent_artifact_ref", "hard_failure_refs", "remaining_budget"})
    if unknown_runtime:
        raise ValueError(f"unknown runtime projection fields: {unknown_runtime}")
    incumbent = runtime.get("incumbent_artifact_ref")
    if incumbent is not None and (not isinstance(incumbent, str) or not incumbent.startswith("artifact:")):
        raise ValueError("incumbent_artifact_ref must be an artifact reference")
    hard_failures = runtime.get("hard_failure_refs", [])
    if not isinstance(hard_failures, list) or len(hard_failures) > 50 or any(not isinstance(item, str) for item in hard_failures):
        raise ValueError("hard_failure_refs must be a bounded string array")
    remaining_budget = runtime.get("remaining_budget", {})
    allowed_budget_fields = {"iterations", "candidate_evaluations", "review_rounds", "changed_lines", "total_changed_lines"}
    if not isinstance(remaining_budget, dict) or set(remaining_budget) - allowed_budget_fields or any(type(value) is not int or value < 0 for value in remaining_budget.values()):
        raise ValueError("remaining_budget must contain only non-negative bounded counters")
    blocking_gaps = [gap for gap in state.get("gaps", []) if node_id in gap.get("blocks", []) and gap.get("status") != "closed"]
    mandatory: list[str] = [
        "# Plan context capsule",
        "",
        f"Plan: {state['plan_id']} / {state['profile']} / {state['status']}",
        f"State: version={state['state_version']} hash={state_hash}",
        f"Source: revision={state['source']['base_revision']} scope={state['source']['scope_hash']}",
        f"Bundle: {state['source']['bundle_id']} policy={state['source']['policy_bundle_hash']} cards={state['source']['reference_manifest_hash']}",
        "Cards: " + ", ".join(f"{item['card_id']}@{item['card_hash']}" for item in card_refs),
        "",
        "## Goal",
        state["goal"],
        "",
        f"## Current node {node_id}",
        f"Objective: {'[REDACTED]' if node_sensitive else node['objective']}",
        f"Completion: {'[REDACTED]' if node_sensitive else node.get('completion_criterion', node['verifier']['completion_criterion'])}",
        f"Status/kind: {node['status']} / {node['kind']}",
        f"Dependencies: {', '.join(node['depends_on']) or 'none'}",
        f"Allowed reads: {', '.join(node['read_set']) or 'none'}",
        f"Allowed writes: {', '.join(node['write_set']) or 'none'}",
        f"Resources: {', '.join(node['resource_set']) or 'none'}",
        f"Effects: {', '.join(node['effect_set']) or 'none'}",
        f"Side effect: {node['side_effect_level']}",
        f"Active decisions: {', '.join(item.get('id') for item in state.get('decisions', []) if isinstance(item.get('id'), str)) or 'none'}",
        f"Blocking plan gaps: {', '.join(item.get('id') for item in blocking_gaps) or 'none'}",
        "Policies: " + (", ".join(f"{item['policy_id']}@{item['policy_hash']}" for item in state.get("policy_claims", [])) or "none"),
        "",
        "## Global invariants",
    ]
    included: list[str] = [node_id]
    for invariant in state.get("global_invariants", []):
        mandatory.append(_summary(invariant))
        included.append(invariant["id"])

    approval_edges = [edge for edge in state.get("edges", []) if edge.get("kind") == "approval" and edge.get("to") == node_id]
    mandatory.extend(["", "## Authority and verifier"])
    if approval_edges:
        approval_text = []
        for edge in approval_edges:
            approval = objects.get(edge["from"], {})
            approval_text.append(f"{edge['from']}={approval.get('status', 'missing')}")
            included.append(edge["from"])
        mandatory.append("Approvals: " + ", ".join(approval_text))
    else:
        mandatory.append("Approvals: none declared")
    verifier = node["verifier"]
    mandatory.extend(
        [
            f"Verifier kind: {verifier['kind']}",
            f"Criterion: {verifier['completion_criterion']}",
            f"Required evidence: {', '.join(verifier['required_evidence']) or 'none'}",
            f"False-green risk: {verifier['false_green_risk']}",
            f"Retry: allowed={node['retry']['allowed']} max_attempts={node['retry']['max_attempts']} idempotency={node['retry']['idempotency']}",
            "",
            "## Explicit non-goals",
        ]
    )
    mandatory.extend(f"- {item}" for item in state.get("non_goals", []))
    mandatory.extend(
        [
            "",
            "## Bounded runtime projection",
            f"Incumbent: {runtime.get('incumbent_artifact_ref', 'none')}",
            f"Hard failures: {', '.join(runtime.get('hard_failure_refs', [])) or 'none'}",
            f"Remaining budget: {json.dumps(runtime.get('remaining_budget', {}), ensure_ascii=False, sort_keys=True)}",
        ]
    )

    mandatory_text = redact_secret_like("\n".join(mandatory).rstrip() + "\n")
    mandatory_bytes = len(mandatory_text.encode("utf-8"))
    if mandatory_bytes > effective_budget:
        raise ValueError(f"mandatory capsule exceeds budget: required={mandatory_bytes} budget={effective_budget}")
    optional_blocks: list[tuple[str, str]] = []
    relevant_refs: list[str] = []
    for ref in node.get("inputs", []) + node.get("outputs", []) + verifier.get("required_evidence", []):
        if ref not in relevant_refs:
            relevant_refs.append(ref)
    for dependency in node.get("depends_on", []):
        dep = objects.get(dependency)
        if dep:
            relevant_refs.extend(ref for ref in dep.get("outputs", []) if ref not in relevant_refs)
    for gap in state.get("gaps", []):
        if node_id in gap.get("blocks", []) and gap["id"] not in relevant_refs:
            relevant_refs.append(gap["id"])

    for ref in relevant_refs:
        item = objects.get(ref)
        if not item or ref in included:
            continue
        optional_blocks.append((ref, _summary(item)))

    text = mandatory_text
    omitted: list[str] = []
    if optional_blocks:
        heading = "\n## Relevant facts, decisions, evidence, and blockers\n"
        if len((text + heading).encode("utf-8")) <= effective_budget:
            text += heading
        else:
            omitted.extend(ref for ref, _ in optional_blocks)
            optional_blocks = []
    for ref, block in optional_blocks:
        candidate = text + block + "\n"
        if len(candidate.encode("utf-8")) <= effective_budget:
            text = candidate
            included.append(ref)
        else:
            omitted.append(ref)

    all_future = [item["id"] for item in state.get("nodes", []) if item["id"] != node_id and item["id"] not in node.get("depends_on", [])]
    omitted.extend(ref for ref in all_future if ref not in omitted)
    text = redact_secret_like(text)
    projection_hash = "sha256:" + sha256(text.encode("utf-8")).hexdigest()
    metadata = {
        "plan_id": state["plan_id"],
        "node_id": node_id,
        "state_hash": state_hash,
        "state_version": state["state_version"],
        "requested_budget": budget,
        "budget_chars": effective_budget,
        "budget_bytes": effective_budget,
        "actual_chars": len(text),
        "actual_bytes": len(text.encode("utf-8")),
        "mandatory_chars": len(mandatory_text),
        "mandatory_bytes": mandatory_bytes,
        "mandatory_truncation_count": 0,
        "budget_exceeded": False,
        "card_refs": card_refs,
        "projection_spec_id": projection_spec_id,
        "projection_hash": projection_hash,
        "included_refs": sorted(set(included)),
        "omitted_refs": sorted(set(omitted)),
        "omission_reason": "budget_or_unrelated_future_state" if omitted else None,
        "requires_on_demand_read": bool(omitted),
    }
    return text, metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("node_id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--budget-chars", type=int, default=6000)
    parser.add_argument("--runtime-projection", type=Path)
    args = parser.parse_args(argv)
    if args.budget_chars < 500:
        print(json.dumps({"ok": False, "error": "budget must be at least 500 characters"}, indent=2))
        return 2
    state, violations = validate_file(args.state, args.schema)
    if violations or state is None:
        print(json.dumps({"ok": False, "violations": [item.as_dict() for item in violations]}, indent=2))
        return 2
    try:
        runtime = load_json(args.runtime_projection) if args.runtime_projection else None
        if runtime is not None and not isinstance(runtime, dict):
            raise ValueError("runtime projection must be a JSON object")
        text, metadata = render(state, args.node_id, args.budget_chars, runtime_projection=runtime)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "capsule_path": str(args.output), **metadata}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
