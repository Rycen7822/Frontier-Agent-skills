#!/usr/bin/env python3
"""Compute field-sensitive workflow invalidation and repair scope."""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
import sys
from typing import Any

from _closure import compute_invalidation as compute_closure_invalidation
from _workflow_state import InputError, load_json


SEMANTIC_EDGE_KINDS = {"control", "data", "evidence", "invariant", "effect", "resource", "approval"}


def propagate_invalidation(
    state: dict[str, Any],
    changed_refs: set[str],
    *,
    changed_fields: dict[str, set[str]] | None = None,
    escalation_flags: set[str] | None = None,
    closure_graph: dict[str, list[str]] | None = None,
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

    affected = set(changed_refs)
    queue = deque(sorted(changed_refs))
    while queue:
        current = queue.popleft()
        for target in sorted(adjacency.get(current, set())):
            if target not in affected:
                affected.add(target)
                queue.append(target)

    all_refs = {"source", "scope", "authority", "goal", "plan"}
    for collection in ("global_invariants", "nodes", "verifiers", "edges", "locks", "artifacts", "recent_failures"):
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
    if any(str(ref).startswith("I-") for ref in affected):
        reasons.append("global_invariant_changed")
    if any(str(ref).startswith("plan:") and "#D-" in str(ref) for ref in affected):
        reasons.append("plan_decision_changed")
    reasons.extend(sorted(escalation_flags))

    nodes = {item["id"]: item for item in state.get("nodes", [])}
    repair_frontier = sorted(ref for ref in affected if ref in nodes and nodes[ref].get("status") not in {"superseded", "skipped", "cancelled"})
    rechecks = sorted(({item["id"] for item in state.get("global_invariants", [])} | {"source.scope_hash"}) if affected else set())
    if any(nodes.get(ref, {}).get("side_effect") in {"external_reversible", "external_non_idempotent", "destructive"} for ref in affected):
        rechecks.append("authority.approvals")
    global_replan = bool(reasons)
    closure_result: dict[str, Any] | None = None
    if state.get("execution_policy") == "autonomous_closure" and isinstance(state.get("closure_run"), dict):
        run = state["closure_run"]
        graph: dict[str, list[str]] = {}

        def add_edges(source: str | None, targets: list[str]) -> None:
            if source:
                graph.setdefault(source, [])
                graph[source] = sorted(set(graph[source]) | {target for target in targets if target and target != source})

        contract = run.get("contract_ref", {}).get("artifact_ref") if isinstance(run.get("contract_ref"), dict) else None
        baseline = run.get("baseline_ref", {}).get("artifact_ref") if isinstance(run.get("baseline_ref"), dict) else None
        verifier = run.get("verifier_bundle_ref", {}).get("artifact_ref") if isinstance(run.get("verifier_bundle_ref"), dict) else None
        candidates = [item for item in run.get("active_candidate_refs", []) if isinstance(item, str)]
        counterexamples = [item for item in run.get("active_counterexample_refs", []) if isinstance(item, str)]
        incumbent = run.get("incumbent_candidate_ref") if isinstance(run.get("incumbent_candidate_ref"), str) else None
        terminal = run.get("terminal_certificate_ref") if isinstance(run.get("terminal_certificate_ref"), str) else None
        workflow_derived = [
            item.get("id")
            for collection in ("nodes", "verifiers", "artifacts", "global_invariants")
            for item in state.get(collection, [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        downstream = [item for item in [baseline, verifier, *candidates, *counterexamples, incumbent, terminal, *workflow_derived] if item]
        add_edges(contract, downstream)
        add_edges(baseline, [item for item in [verifier, *candidates, *counterexamples, incumbent, terminal] if item])
        add_edges(verifier, [item for item in [*candidates, *counterexamples, incumbent, terminal] if item])
        for counterexample in counterexamples:
            add_edges(counterexample, [item for item in [*candidates, incumbent, terminal] if item])
        for candidate in candidates:
            add_edges(candidate, [item for item in [incumbent, terminal] if item])
        if closure_graph is not None:
            if not isinstance(closure_graph, dict) or len(closure_graph) > 5000:
                raise ValueError("closure_graph must be a bounded object")
            for source, targets in closure_graph.items():
                if not isinstance(source, str) or not isinstance(targets, list) or len(targets) > 5000 or any(not isinstance(item, str) for item in targets):
                    raise ValueError("closure_graph must map string refs to bounded string arrays")
                add_edges(source, targets)
        if sum(len(values) for values in graph.values()) > 20000:
            raise ValueError("closure_graph exceeds the bounded edge limit")

        global_kinds = {
            contract: "contract_hash",
            verifier: "verifier_bundle_hash",
            baseline: "baseline_environment",
            "source": "source_revision",
            "scope": "protected_surface",
            "policy_bundle_hash": "policy_bundle_hash",
            "controller_hash": "controller_hash",
            "protected_surface": "protected_surface",
            "baseline_environment": "baseline_environment",
            "plan": "contract_hash",
            "goal": "contract_hash",
            "authority": "contract_hash",
        }
        closure_parts: list[dict[str, Any]] = []
        for changed in sorted(changed_refs):
            kind = global_kinds.get(changed)
            if kind is None:
                kind = "counterexample" if changed in counterexamples else ("candidate" if changed in candidates or changed == incumbent else "artifact")
            closure_parts.append(compute_closure_invalidation({"kind": kind, "ref": changed}, graph))
        if closure_parts:
            phase_order = {"SPEC_COMPILING": 0, "BASELINING": 1, "VERIFIER_QUALIFYING": 2, "SEARCHING": 3}
            restart_phase = min((item["restart_phase"] for item in closure_parts), key=lambda item: phase_order.get(item, 99))
            closure_affected = {ref for item in closure_parts for ref in item["affected"]}
            closure_reasons = {reason for item in closure_parts for reason in item["reason_codes"]}
            new_epoch = any(item["new_epoch_required"] for item in closure_parts)
            affected.update(closure_affected)
            if new_epoch:
                reasons.extend(sorted(closure_reasons))
                global_replan = True
            rechecks.extend(["closure.contract", "closure.verifier", "closure.baseline", "source.scope_hash"])
            closure_result = {
                "affected": sorted(closure_affected),
                "new_epoch_required": new_epoch,
                "restart_phase": restart_phase,
                "reason_codes": sorted(closure_reasons),
            }
            all_refs.update(graph)
            for values in graph.values():
                all_refs.update(values)

    nodes = {item["id"]: item for item in state.get("nodes", [])}
    repair_frontier = sorted(ref for ref in affected if ref in nodes and nodes[ref].get("status") not in {"superseded", "skipped", "cancelled"})
    affected_sorted = sorted(affected)
    result = {
        "repair_type": "global_or_parent_replan" if global_replan else "local",
        "affected": affected_sorted,
        "invalidated": affected_sorted,
        "preserved": sorted(all_refs - affected),
        "frontier": repair_frontier,
        "required_rechecks": sorted(set(rechecks)),
        "escalation_reasons": sorted(set(reasons)),
    }
    if closure_result is not None:
        result["closure"] = closure_result
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
    parser.add_argument("--closure-graph", type=Path, help="optional controller-exported closure artifact dependency graph")
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        fields: dict[str, set[str]] = {}
        for ref, field in args.changed_field:
            fields.setdefault(ref, set()).add(field)
        changed = set(args.changed_ref) | set(fields)
        if not changed:
            raise ValueError("at least one changed ref or field is required")
        closure_graph = load_json(args.closure_graph) if args.closure_graph else None
        result = propagate_invalidation(
            state,
            changed,
            changed_fields=fields,
            escalation_flags=set(args.escalation_flag),
            closure_graph=closure_graph,
        )
    except (InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
