#!/usr/bin/env python3
"""Render a budgeted, sensitivity-aware context capsule for one plan node."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from _closure_contract import load_contract
from _plan_state import capsule_source_hash, contains_secret_like, load_json, redact_secret_like
from validate_plan_state import DEFAULT_SCHEMA, semantic_violations, validate_file


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
    closure_contract: dict[str, Any] | None = None,
    runtime_projection: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    objects = _index(state)
    node = objects.get(node_id)
    if not node or not node_id.startswith("P-"):
        raise ValueError(f"node does not exist: {node_id}")
    node_sensitive = bool(node.get("sensitive")) or contains_secret_like(node)
    state_hash = capsule_source_hash(state)
    execution_policy = state.get("execution_policy", "standard")
    contract_ref = state.get("closure_contract_ref")
    if execution_policy == "autonomous_closure":
        if not isinstance(contract_ref, dict) or not isinstance(closure_contract, dict):
            raise ValueError("autonomous closure capsule requires the loaded frozen Closure Contract")
        if closure_contract.get("status") != "frozen" or contract_ref.get("content_hash") != closure_contract.get("content_hash") or contract_ref.get("epoch") != closure_contract.get("epoch"):
            raise ValueError("capsule Closure Contract does not match canonical plan binding")
    elif closure_contract is not None or contract_ref is not None:
        raise ValueError("standard plan capsule must not carry a Closure Contract")
    binding_errors = [
        item
        for item in semantic_violations(state, closure_contract=closure_contract)
        if item.code.startswith("plan.contract") or item.code.startswith("plan.node-contract")
    ]
    if binding_errors:
        raise ValueError(f"capsule contract binding is invalid: {sorted({item.code for item in binding_errors})}")
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
        f"Execution policy: {execution_policy}",
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
        f"Side effect: {node['side_effect_level']}",
        f"Constraints: {', '.join(node.get('constraint_refs', [])) or 'none'}",
        f"Corners: {', '.join(node.get('corner_refs', [])) or 'none'}",
        f"Verifier requirements: {', '.join(node.get('verifier_requirement_refs', [])) or 'none'}",
        f"Active decisions: {', '.join(item.get('id') for item in state.get('decisions', []) if isinstance(item.get('id'), str)) or 'none'}",
        f"Blocking plan gaps: {', '.join(item.get('id') for item in blocking_gaps) or 'none'}",
        "",
        "## Global invariants",
    ]
    if execution_policy == "autonomous_closure":
        mandatory[6:6] = [
            f"Contract: {contract_ref['artifact_ref']} hash={contract_ref['content_hash']} epoch={contract_ref['epoch']}",
            "Contract detail: load the immutable artifact by ID; full constraint text is intentionally not copied",
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
        if len(text) + len(heading) <= budget:
            text += heading
        else:
            omitted.extend(ref for ref, _ in optional_blocks)
            optional_blocks = []
    for ref, block in optional_blocks:
        candidate = text + block + "\n"
        if len(candidate) <= budget:
            text = candidate
            included.append(ref)
        else:
            omitted.append(ref)

    all_future = [item["id"] for item in state.get("nodes", []) if item["id"] != node_id and item["id"] not in node.get("depends_on", [])]
    omitted.extend(ref for ref in all_future if ref not in omitted)
    text = redact_secret_like(text)
    metadata = {
        "plan_id": state["plan_id"],
        "node_id": node_id,
        "state_hash": state_hash,
        "state_version": state["state_version"],
        "execution_policy": execution_policy,
        "contract_hash": contract_ref.get("content_hash") if isinstance(contract_ref, dict) else None,
        "contract_epoch": contract_ref.get("epoch") if isinstance(contract_ref, dict) else None,
        "budget_chars": budget,
        "actual_chars": len(text),
        "budget_exceeded": len(mandatory_text) > budget,
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
    parser.add_argument("--closure-contract", type=Path)
    parser.add_argument("--runtime-projection", type=Path)
    args = parser.parse_args(argv)
    if args.budget_chars < 500:
        print(json.dumps({"ok": False, "error": "budget must be at least 500 characters"}, indent=2))
        return 2
    state, violations = validate_file(args.state, args.schema, closure_contract_path=args.closure_contract)
    if violations or state is None:
        print(json.dumps({"ok": False, "violations": [item.as_dict() for item in violations]}, indent=2))
        return 2
    try:
        contract = load_contract(args.closure_contract) if args.closure_contract else None
        runtime = load_json(args.runtime_projection) if args.runtime_projection else None
        if runtime is not None and not isinstance(runtime, dict):
            raise ValueError("runtime projection must be a JSON object")
        text, metadata = render(state, args.node_id, args.budget_chars, closure_contract=contract, runtime_projection=runtime)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "capsule_path": str(args.output), **metadata}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
