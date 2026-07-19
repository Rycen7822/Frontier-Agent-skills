#!/usr/bin/env python3
"""Compute field-sensitive workflow invalidation and repair scope."""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, load_json


SEMANTIC_EDGE_KINDS = {"data", "control", "evidence", "invariant", "read", "write", "resource", "approval"}


def propagate_invalidation(
    state: dict[str, Any],
    changed_refs: set[str],
    *,
    changed_fields: dict[str, set[str]] | None = None,
    escalation_flags: set[str] | None = None,
) -> dict[str, Any]:
    changed_fields = changed_fields or {}
    escalation_flags = escalation_flags or set()
    adjacency: dict[str, set[str]] = {}
    explicit_pairs: set[tuple[str, str]] = set()

    def connect(source: str, target: str) -> None:
        if source and target:
            adjacency.setdefault(source, set()).add(target)

    for edge in state.get("edges", []):
        if edge.get("kind") not in SEMANTIC_EDGE_KINDS:
            continue
        source, target = edge.get("from"), edge.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        explicit_pairs.add((source, target))
        sensitivity = set(edge.get("sensitivity", {}).get("fields", []))
        if source in changed_fields and sensitivity and changed_fields[source].isdisjoint(sensitivity):
            continue
        connect(source, target)

    for verifier in state.get("verifiers", []):
        bindings = {item.get("ref"): set(item.get("fields", [])) for item in verifier.get("evidence_sensitivity", [])}
        for evidence_ref in verifier.get("required_evidence", []):
            sensitivity = bindings.get(evidence_ref, set())
            if evidence_ref in changed_fields and sensitivity and changed_fields[evidence_ref].isdisjoint(sensitivity):
                continue
            connect(evidence_ref, verifier["id"])
    for node in state.get("nodes", []):
        for dependency in node.get("depends_on", []):
            connect(dependency, node["id"])
        for input_ref in node.get("input_refs", []):
            if (input_ref, node["id"]) not in explicit_pairs:
                connect(input_ref, node["id"])
        for verifier_ref in node.get("verifier_refs", []):
            connect(verifier_ref, node["id"])
        for output_ref in node.get("output_refs", []):
            connect(node["id"], output_ref)

    invariants = {item.get("id"): item for item in state.get("global_invariants", []) if isinstance(item, dict)}
    for invariant_id in sorted(changed_refs & set(invariants)):
        invariant = invariants[invariant_id]
        if invariant.get("locality") == "node_set":
            for target in invariant.get("targets", []):
                if isinstance(target, str):
                    connect(invariant_id, target)
        elif invariant.get("locality") == "resource_set":
            targets = set(invariant.get("targets", []))
            for node in state.get("nodes", []):
                if targets & set(node.get("resource_set", [])):
                    connect(invariant_id, node.get("id"))

    affected = set(changed_refs)
    queue = deque(sorted(changed_refs))
    while queue:
        current = queue.popleft()
        for target in sorted(adjacency.get(current, set())):
            if target not in affected:
                affected.add(target)
                queue.append(target)

    all_refs = {"source", "scope", "authority", "goal", "plan"}
    for collection in ("global_invariants", "nodes", "verifiers", "edges", "artifacts", "recent_failures"):
        all_refs.update(item.get("id") for item in state.get(collection, []) if item.get("id"))
    all_refs.update(item.get("id") for item in state.get("authority", {}).get("approvals", []) if item.get("id"))
    for node in state.get("nodes", []):
        all_refs.update(node.get("input_refs", []))
        all_refs.update(node.get("output_refs", []))

    reasons: list[str] = []
    if affected & {"source", "scope", "goal", "plan"}:
        reasons.append("source_scope_goal_or_plan_changed")
    if "authority" in affected or any(str(ref).startswith("AP-") for ref in affected):
        reasons.append("authority_or_approval_changed")
    if any(str(ref).startswith("I-") and invariants.get(ref, {}).get("locality") == "global" for ref in affected):
        reasons.append("global_invariant_changed")
    if any(str(ref).startswith("plan:") and "#D-" in str(ref) for ref in affected):
        reasons.append("plan_decision_changed")
    reasons.extend(sorted(escalation_flags))

    nodes = {item["id"]: item for item in state.get("nodes", [])}
    repair_frontier = sorted(ref for ref in affected if ref in nodes and nodes[ref].get("status") not in {"superseded", "skipped", "cancelled"})
    rechecks = sorted(({item["id"] for item in state.get("global_invariants", [])} | {"scope_binding.binding_id"}) if affected else set())
    if any(nodes.get(ref, {}).get("side_effect") in {"external_reversible", "external_non_idempotent", "destructive"} for ref in affected):
        rechecks.append("authority.approvals")
    global_replan = bool(reasons)

    affected_sorted = sorted(affected)
    result = {
        "repair_type": "global_or_parent_replan" if global_replan else "local",
        "affected": affected_sorted,
        "invalidated": affected_sorted,
        "preserved": sorted(all_refs - affected),
        "frontier": repair_frontier,
        "required_rechecks": sorted(set(rechecks)),
        "escalation_reasons": sorted(set(reasons)),
        "repair_slice": repair_frontier,
        "preserved_slice": sorted(all_refs - affected),
        "invalidated_artifacts": sorted(ref for ref in affected if str(ref).startswith(("EV-", "artifact:"))),
        "required_revalidation_gates": sorted(set(rechecks)),
        "escalation_reason": sorted(set(reasons)),
        "new_primary_card_id": "sqw.control.evidence-and-verifier-integrity",
    }
    return result


def _changed_field(value: str) -> tuple[str, str]:
    ref, separator, field = value.partition("=")
    if not separator or not ref or not field:
        raise argparse.ArgumentTypeError("changed field must use REF=FIELD")
    return ref, field


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--changed-ref", action="append", default=[])
    parser.add_argument("--changed-field", action="append", default=[], type=_changed_field, metavar="REF=FIELD")
    parser.add_argument("--escalation-flag", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        fields: dict[str, set[str]] = {}
        for ref, field in args.changed_field:
            fields.setdefault(ref, set()).add(field)
        changed = set(args.changed_ref) | set(fields)
        if not changed:
            raise ValueError("at least one changed ref or field is required")
        result = propagate_invalidation(
            state,
            changed,
            changed_fields=fields,
            escalation_flags=set(args.escalation_flag),
        )
    except (InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
