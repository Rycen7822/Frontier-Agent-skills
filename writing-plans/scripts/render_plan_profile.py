#!/usr/bin/env python3
"""Render a plan profile from bounded structured JSON without changing canonical state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _plan_state import canonical_state_hash, load_json, validate_against_schema
from validate_plan_state import semantic_violations


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "schemas" / "plan-state.schema.json"
HANDOFF_SCHEMA = ROOT / "schemas" / "plan-execution-handoff.schema.json"


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
    _require(data, ("outcome", "scope", "invariants", "approach", "proof", "completion"))
    return f"""# Change Card: {data['outcome']}

- Outcome: {data['outcome']}
- Scope: {data['scope']}
- Invariants: {data['invariants']}
- Approach: {data['approach']}
- Proof: {data['proof']}
- Risks/open facts: {data.get('risks_open_facts', 'None declared')}
- Completion: {data['completion']}
"""


def render_handoff(data: dict[str, Any]) -> str:
    if validate_against_schema(data, load_json(HANDOFF_SCHEMA)):
        raise ValueError("handoff rendering requires a valid typed handoff 3.0")
    producer = data["producer"]
    scope = data["scope_binding"]
    requirement_rows = [
        f"- {name}: {', '.join(values) or 'none'}"
        for name, values in data["requirements"].items()
    ]
    seam_rows = [
        f"- {item['owner']}: paths={item['paths']}; resources={item['resources']}; effects={item['effects']}"
        for item in data["owner_seams"]
    ]
    slice_rows = [
        f"- {item['slice_id']} ({item['node_ref'] or 'standalone'}): {item['objective']}; depends={item['depends_on']}; reads={item['read_set']}; writes={item['write_set']}; effects={item['effect_set']}; done={item['completion_criterion']}"
        for item in data["ordered_slices"]
    ]
    return f"""# Executable Handoff: {data['goal']}

- Handoff ID: {data['handoff_id']}
- Producer: {producer['profile']} / {producer['card_id']} / {producer['completion_id']}
- Plan ID: {producer['plan_id'] or 'standalone'}
- State hash: {producer['state_hash'] or 'none'}
- Source identity: {data['source_identity']['kind']} / {data['source_identity']['identity_hash']}
- Scope binding: {scope['binding_id']}
- Effect/publication ceilings: {scope['effect_ceiling']} / {scope['publication_ceiling']}

This handoff records execution-authority requirements. It does not grant or claim actual authority.

## Non-goals

{_items(data.get('non_goals'))}

## Global invariants

{_items([f"{item['ref']}: {item['statement']}" for item in data['global_invariants']])}

## Owner seams/contracts

{chr(10).join(seam_rows)}

## Ordered outcome slices

{chr(10).join(slice_rows)}

## Required typed references

{chr(10).join(requirement_rows)}

## Rollback

- Strategy: {data['rollback']['strategy']}
{_items(data['rollback']['steps'])}

## Receiver entry

- Skill: {data['target_entry']['skill_id']}
- Route phase: {data['target_entry']['route_phase']}
- Required decisions: {', '.join(data['target_entry']['required_decision_ids'])}

## Unresolved blockers

{_items(data['unresolved_blockers'])}
"""


def render_program(state: dict[str, Any]) -> str:
    schema_errors = validate_against_schema(state, load_json(STATE_SCHEMA))
    semantic_errors = [] if schema_errors else semantic_violations(state)
    if schema_errors or semantic_errors:
        raise ValueError("Program rendering requires valid canonical plan-state 3.0")

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
    text = f"""# Program/Migration Map: {state['goal']}

- Plan ID: {state['plan_id']}
- Profile: program
- State version/hash: {state['state_version']} / {state_hash}
- Source identity: {state['source_identity']['kind']} / {state['source_identity']['identity_hash']}
- Scope binding: {state['scope_binding']['binding_id']}
- Bundle/cards: {state['bundle_id']} / {state['manifest_hash']}
- canonical_artifacts: full graph, evidence, alternatives, and history remain in the locked Program owner at {state_hash}
## Non-goals

{_items(state.get('non_goals'))}

## Applicable invariants

{_items(invariants)}

## Major current decisions

{_items(decisions)}

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

## Verification and completion

{_items(verification)}
- Plan completion status: {state.get('completion', {}).get('status')}
- Required evidence: {', '.join(state.get('completion', {}).get('required_evidence', [])) or 'none'}
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
