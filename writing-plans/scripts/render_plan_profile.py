#!/usr/bin/env python3
"""Render a plan profile from bounded structured JSON without changing canonical state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from _closure_contract import load_contract
from _plan_state import canonical_state_hash, load_json
from validate_plan_state import semantic_violations


def _items(value: Any) -> str:
    if not value:
        return "- None declared"
    if isinstance(value, list):
        return "\n".join(f"- {item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)}" for item in value)
    return f"- {value}"


def _require(data: dict[str, Any], fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if data.get(field) in (None, "", [])]
    if missing:
        raise ValueError(f"missing required fields: {missing}")


def render_brief(data: dict[str, Any]) -> str:
    _require(data, ("outcome", "scope", "invariants", "approach", "proof", "closure"))
    return f"""# Change Card: {data['outcome']}

- Outcome: {data['outcome']}
- Scope: {data['scope']}
- Invariants: {data['invariants']}
- Approach: {data['approach']}
- Proof: {data['proof']}
- Risks/open facts: {data.get('risks_open_facts', 'None declared')}
- Closure: {data['closure']}
"""


def render_handoff(data: dict[str, Any]) -> str:
    _require(data, ("plan_id", "source_revision", "scope_hash", "goal", "invariants", "owner_seams", "slices"))
    return f"""# Executable Handoff: {data['goal']}

- Plan ID: {data['plan_id']}
- Profile: handoff
- Source revision: {data['source_revision']}
- Scope hash: {data['scope_hash']}
- State ref/hash: {data.get('state_ref', 'none')} / {data.get('state_hash', 'none')}

## Non-goals

{_items(data.get('non_goals'))}

## Global invariants

{_items(data['invariants'])}

## Owner seams/contracts

{_items(data['owner_seams'])}

## Ordered outcome slices

{_items(data['slices'])}

## Current frontier

{_items(data.get('current_frontier'))}

## Gaps/fog

{_items(data.get('gaps'))}

## Required evidence

{_items(data.get('required_evidence'))}
"""


def render_program(
    state: dict[str, Any],
    *,
    closure_contract: dict[str, Any] | None = None,
    state_ref: str = "canonical-plan-state",
) -> str:
    if state.get("schema_version") != "1.1" or state.get("profile") != "program":
        raise ValueError("Program rendering requires canonical plan-state 1.1 with profile=program")
    policy = state.get("execution_policy")
    contract_ref = state.get("closure_contract_ref")
    if policy == "autonomous_closure":
        if not isinstance(contract_ref, dict) or not isinstance(closure_contract, dict):
            raise ValueError("autonomous Program rendering requires the loaded frozen Closure Contract")
        if closure_contract.get("status") != "frozen" or contract_ref.get("content_hash") != closure_contract.get("content_hash") or contract_ref.get("epoch") != closure_contract.get("epoch"):
            raise ValueError("Closure Contract projection does not match the canonical plan binding")
    elif policy != "standard" or contract_ref is not None or closure_contract is not None:
        raise ValueError("standard Program must not carry a Closure Contract projection")
    binding_errors = [
        item
        for item in semantic_violations(state, closure_contract=closure_contract)
        if item.code.startswith("plan.contract") or item.code.startswith("plan.node-contract")
    ]
    if binding_errors:
        raise ValueError(f"Program contract binding is invalid: {sorted({item.code for item in binding_errors})}")

    state_hash = state.get("content_hash") or canonical_state_hash(state)
    node_by_id = {node.get("id"): node for node in state.get("nodes", [])}
    frontier_nodes = [node_by_id[node_id] for node_id in state.get("current_frontier", []) if node_id in node_by_id]
    relevant_refs = {
        ref
        for node in frontier_nodes
        for ref in node.get("inputs", []) + node.get("outputs", []) + node.get("depends_on", []) + node.get("verifier", {}).get("required_evidence", [])
    }
    decisions = [
        f"{item.get('id')}: {item.get('statement')} [provenance={item.get('provenance')}, materiality={item.get('materiality')}, reversibility={item.get('reversibility')}]"
        for item in state.get("decisions", [])
        if item.get("id") in relevant_refs
    ]
    invariants = [
        f"{item.get('id')}: {item.get('statement')} [locality={item.get('locality')}]"
        for item in state.get("global_invariants", [])
        if item.get("locality") == "global" or item.get("id") in relevant_refs
    ]
    frontier = [
        f"{node.get('id')}: {node.get('objective')} ({node.get('status')}); completion={node.get('completion_criterion')}; reads={node.get('read_set', [])}; writes={node.get('write_set', [])}; effects={node.get('effect_set', [])}"
        for node in frontier_nodes
    ]
    coverage_rows = [
        "| {id} | {constraints} | {corners} | {verifiers} |".format(
            id=node.get("id", "?"),
            constraints=", ".join(node.get("constraint_refs", [])) or "none",
            corners=", ".join(node.get("corner_refs", [])) or "none",
            verifiers=", ".join(node.get("verifier_requirement_refs", [])) or "none",
        )
        for node in frontier_nodes
    ]
    strategy_rows = [f"| {item.get('id')} | {item.get('statement')} | selected | {item.get('provenance')} |" for item in state.get("decisions", []) if item.get("id") in relevant_refs]
    blocking_gaps = [
        f"{item.get('id')}: {item.get('question')}"
        for item in state.get("gaps", [])
        if item.get("status") != "closed" and set(item.get("blocks", [])) & set(state.get("current_frontier", []))
    ]
    risks = [
        f"{item.get('id')}: {item.get('statement')} -> {item.get('escalation')}"
        for item in state.get("risks", [])
        if set(item.get("mitigation_refs", [])) & relevant_refs
    ]
    verification = [f"{node.get('id')}: {node.get('verifier', {}).get('completion_criterion')}" for node in frontier_nodes]
    contract_block = ""
    if policy == "autonomous_closure":
        contract_block = f"\n- Closure contract: {contract_ref['artifact_ref']}\n- Contract hash / epoch: {contract_ref['content_hash']} / {contract_ref['epoch']}\n"
    text = f"""# Program/Migration Map: {state['goal']}

- Plan ID: {state['plan_id']}
- Profile: program
- Execution policy: {policy}
- State ref/hash: {state_ref} / {state_hash}
- Source revision: {state['source']['base_revision']}
- Scope hash: {state['source']['scope_hash']}
- Bundle/cards: {state['source']['bundle_id']} / {state['source']['reference_manifest_hash']}
- canonical_artifacts: full graph, evidence, alternatives, and history remain in {state_ref} at {state_hash}
{contract_block}
## Non-goals

{_items(state.get('non_goals'))}

## Applicable invariants

{_items(invariants)}

## Major current decisions

{_items(decisions)}

## Constraint coverage

| Plan slice | Hard constraints | Corners | Verifier requirements |
|---|---|---|---|
{chr(10).join(coverage_rows) or '| none | none | none | none |'}

## Strategy families

| ID | Core mechanism | Status | Evidence / disproof |
|---|---|---|---|
{chr(10).join(strategy_rows) or '| none | none | none | none |'}

## Current frontier

{_items(frontier)}

## Blocking gaps

{_items(blocking_gaps)}

## Risk and rollback

{_items(risks)}

## Verification and plan closure

{_items(verification)}
- Plan closure status: {state.get('closure', {}).get('status')}
- Required evidence: {', '.join(state.get('closure', {}).get('required_evidence', [])) or 'none'}
"""
    if len(text.encode("utf-8")) > 8192:
        raise ValueError("current-frontier Program projection exceeds 8192 bytes")
    return text


def add_novice_projection(text: str, data: dict[str, Any]) -> str:
    _require(data, ("source_revision", "scope_hash", "state_hash", "novice_steps"))
    return text + f"""

---

# Novice-executable projection (generated; non-canonical)

Bound to source `{data['source_revision']}`, scope `{data['scope_hash']}`, and state `{data['state_hash']}`. Regenerate after any drift.

{_items(data['novice_steps'])}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("brief", "handoff", "program"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--novice", action="store_true")
    parser.add_argument("--closure-contract", type=Path)
    args = parser.parse_args(argv)
    try:
        data = load_json(args.input)
        if not isinstance(data, dict):
            raise ValueError("input must be a JSON object")
        if args.profile == "program":
            contract = load_contract(args.closure_contract) if args.closure_contract else None
            text = render_program(data, closure_contract=contract, state_ref=str(args.input))
        else:
            if args.closure_contract:
                raise ValueError("Closure Contract projection is only valid for Program")
            text = {"brief": render_brief, "handoff": render_handoff}[args.profile](data)
        if args.novice:
            if args.profile == "brief":
                raise ValueError("novice projection requires handoff or program")
            text = add_novice_projection(text, data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"ok": True, "profile": args.profile, "output": str(args.output), "novice": args.novice}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
