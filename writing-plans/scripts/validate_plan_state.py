#!/usr/bin/env python3
"""Deterministically validate writing-plans durable state."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from _closure_contract import ContractInputError, canonical_contract_hash, load_contract
from _plan_state import (
    PlanInputError,
    Violation,
    canonical_state_hash,
    contains_secret_like,
    is_local_id,
    json_output,
    load_json,
    path_allowed,
    patterns_may_overlap,
    pointer,
    verifier_ref_is_structured,
    validate_against_schema,
)
from validate_closure_contract import validate_contract

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "plan-state.schema.json"
DEFAULT_CONTRACT_SCHEMA = ROOT / "schemas" / "closure-contract.schema.json"
LIVE_NODE_STATUSES = {"ready", "in_progress", "done"}
SATISFIED_NODE_STATUSES = {"done", "skipped", "superseded"}
EXTERNAL_EFFECTS = {"external_reversible", "external_non_idempotent", "destructive"}
HIGH_RISK_KINDS = {"migration", "approval", "release"}
CONTRACT_BOUND_KINDS = {"implementation", "migration", "release", "verification"}


def _objects(state: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    result: list[tuple[str, int, dict[str, Any]]] = []
    for collection in ("global_invariants", "facts", "decisions", "evidence", "nodes", "edges", "risks", "gaps", "approvals", "snapshots"):
        for index, item in enumerate(state.get(collection, [])):
            if isinstance(item, dict):
                result.append((collection, index, item))
    return result


def _id_index(state: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[Violation]]:
    index: dict[str, dict[str, Any]] = {}
    seen_path: dict[str, str] = {}
    violations: list[Violation] = []
    for collection, position, item in _objects(state):
        object_id = item.get("id")
        if not isinstance(object_id, str):
            continue
        path = pointer((collection, position, "id"))
        if object_id in index:
            violations.append(Violation("plan.id-duplicate", path, f"ID duplicates {seen_path[object_id]}", object_id))
        else:
            index[object_id] = item
            seen_path[object_id] = path
    return index, violations


def _references(state: dict[str, Any]) -> Iterable[tuple[str, str, str | None]]:
    def emit(values: Any, parts: tuple[str | int, ...], owner: str | None = None) -> Iterable[tuple[str, str, str | None]]:
        if isinstance(values, list):
            for index, value in enumerate(values):
                if isinstance(value, str):
                    yield value, pointer(parts + (index,)), owner
        elif isinstance(values, str):
            yield values, pointer(parts), owner

    for collection in ("facts", "decisions"):
        for i, item in enumerate(state.get(collection, [])):
            yield from emit(item.get("evidence_refs", []), (collection, i, "evidence_refs"), item.get("id"))
    for i, item in enumerate(state.get("evidence", [])):
        if item.get("producer_node"):
            yield from emit(item["producer_node"], ("evidence", i, "producer_node"), item.get("id"))
    for i, node in enumerate(state.get("nodes", [])):
        owner = node.get("id")
        for field in ("depends_on", "inputs", "outputs"):
            yield from emit(node.get(field, []), ("nodes", i, field), owner)
        verifier = node.get("verifier", {})
        yield from emit(verifier.get("required_evidence", []), ("nodes", i, "verifier", "required_evidence"), owner)
        refinement = node.get("refinement", {})
        if refinement.get("parent"):
            yield from emit(refinement["parent"], ("nodes", i, "refinement", "parent"), owner)
        yield from emit(refinement.get("replaces", []), ("nodes", i, "refinement", "replaces"), owner)
    for i, edge in enumerate(state.get("edges", [])):
        yield from emit(edge.get("from"), ("edges", i, "from"), edge.get("id"))
        yield from emit(edge.get("to"), ("edges", i, "to"), edge.get("id"))
    yield from emit(state.get("current_frontier", []), ("current_frontier",))
    for collection, field in (("risks", "mitigation_refs"), ("gaps", "blocks")):
        for i, item in enumerate(state.get(collection, [])):
            yield from emit(item.get(field, []), (collection, i, field), item.get("id"))
    yield from emit(state.get("closure", {}).get("required_evidence", []), ("closure", "required_evidence"))


def _node_graph(state: dict[str, Any]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {node["id"]: set() for node in state.get("nodes", []) if isinstance(node.get("id"), str)}
    for node in state.get("nodes", []):
        target = node.get("id")
        for dependency in node.get("depends_on", []):
            if dependency in graph and target in graph:
                graph[dependency].add(target)
    for edge in state.get("edges", []):
        if edge.get("kind") == "control" and edge.get("from") in graph and edge.get("to") in graph:
            graph[edge["from"]].add(edge["to"])
    return graph


def _control_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(node: str) -> None:
        if node in visiting:
            start = stack.index(node)
            cycles.append(stack[start:] + [node])
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for child in graph.get(node, set()):
            visit(child)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    return cycles


def _has_edge(state: dict[str, Any], kind: str, source_prefix: str, target: str) -> bool:
    return any(edge.get("kind") == kind and str(edge.get("from", "")).startswith(source_prefix) and edge.get("to") == target for edge in state.get("edges", []))


def _unclassified_secret_violations(
    value: Any,
    parts: tuple[str | int, ...] = (),
    *,
    classified: bool = False,
    owner: str | None = None,
) -> Iterable[Violation]:
    if isinstance(value, dict):
        current_owner = value.get("id") if isinstance(value.get("id"), str) else owner
        child_classified = classified or value.get("sensitive") is True
        for key, child in value.items():
            yield from _unclassified_secret_violations(
                child,
                parts + (key,),
                classified=child_classified,
                owner=current_owner,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _unclassified_secret_violations(
                child,
                parts + (index,),
                classified=classified,
                owner=owner,
            )
    elif isinstance(value, str) and not classified and contains_secret_like(value):
        yield Violation(
            "plan.sensitive-unclassified",
            pointer(parts),
            "raw credential-shaped value requires sensitive classification or a controlled pointer",
            owner,
        )


def _contract_binding_violations(state: dict[str, Any], closure_contract: dict[str, Any] | None) -> list[Violation]:
    violations: list[Violation] = []
    policy = state.get("execution_policy")
    contract_ref = state.get("closure_contract_ref")
    if policy == "standard":
        if contract_ref is not None:
            violations.append(Violation("plan.contract-forbidden", "/closure_contract_ref", "standard plan must not carry a Closure Contract reference"))
        return violations
    if policy != "autonomous_closure":
        return violations
    if state.get("profile") != "program":
        violations.append(Violation("plan.contract-profile", "/profile", "autonomous closure requires Program profile"))
    if not isinstance(contract_ref, dict) or closure_contract is None:
        violations.append(Violation("plan.contract-missing", "/closure_contract_ref", "autonomous closure requires a loaded frozen Closure Contract"))
        return violations
    if closure_contract.get("status") != "frozen" or closure_contract.get("content_hash") != canonical_contract_hash(closure_contract):
        violations.append(Violation("plan.contract-stale", "/closure_contract_ref/content_hash", "loaded Closure Contract is not a self-consistent frozen artifact"))
    if contract_ref.get("content_hash") != closure_contract.get("content_hash") or contract_ref.get("epoch") != closure_contract.get("epoch"):
        violations.append(Violation("plan.contract-stale", "/closure_contract_ref", "plan contract hash or epoch differs from the loaded contract"))
    artifact_ref = contract_ref.get("artifact_ref")
    if not isinstance(artifact_ref, str) or artifact_ref.rsplit("/", 1)[-1] != closure_contract.get("contract_id"):
        violations.append(Violation("plan.contract-stale", "/closure_contract_ref/artifact_ref", "artifact ref does not bind the loaded contract ID"))

    plan_source = state.get("source") if isinstance(state.get("source"), dict) else {}
    contract_source = closure_contract.get("source") if isinstance(closure_contract.get("source"), dict) else {}
    for field in ("base_revision", "scope_hash", "policy_bundle_hash"):
        if plan_source.get(field) != contract_source.get(field):
            violations.append(Violation("plan.contract-source-mismatch", f"/source/{field}", f"plan {field} differs from frozen contract"))
    if state.get("content_hash") != canonical_state_hash(state):
        violations.append(Violation("plan.contract-plan-hash", "/content_hash", "autonomous closure plan requires a fresh canonical state hash"))

    plan_scope = state.get("scope") if isinstance(state.get("scope"), dict) else {}
    contract_scope = closure_contract.get("scope") if isinstance(closure_contract.get("scope"), dict) else {}
    for plan_field, contract_field in (("allowed_reads", "allowed_read_paths"), ("allowed_writes", "allowed_write_paths")):
        allowed = contract_scope.get(contract_field, []) if isinstance(contract_scope.get(contract_field), list) else []
        for index, path in enumerate(plan_scope.get(plan_field, [])):
            if isinstance(path, str) and not path_allowed(path, allowed):
                violations.append(Violation("plan.contract-scope-mismatch", pointer(("scope", plan_field, index)), f"plan path {path!r} exceeds frozen contract scope"))

    contract_ids = {
        "constraint_refs": {item.get("id") for item in closure_contract.get("hard_constraints", []) if isinstance(item, dict)},
        "corner_refs": {item.get("id") for item in closure_contract.get("corners", []) if isinstance(item, dict)},
        "verifier_requirement_refs": {item.get("id") for item in closure_contract.get("verifier_requirements", []) if isinstance(item, dict)},
    }
    for node_index, node in enumerate(state.get("nodes", [])):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id") if isinstance(node.get("id"), str) else None
        if node.get("kind") in CONTRACT_BOUND_KINDS and not (node.get("constraint_refs") or node.get("verifier_requirement_refs")):
            violations.append(Violation("plan.node-contract-ref", pointer(("nodes", node_index)), "closure execution node requires a constraint or verifier requirement", node_id))
        for field, allowed in contract_ids.items():
            values = node.get(field, [])
            if not isinstance(values, list):
                continue
            for ref_index, ref in enumerate(values):
                if ref not in allowed:
                    violations.append(Violation("plan.node-contract-ref", pointer(("nodes", node_index, field, ref_index)), f"{ref!r} does not resolve in the frozen contract", node_id))
    return violations


def semantic_violations(
    state: dict[str, Any],
    *,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
    closure_contract: dict[str, Any] | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(_contract_binding_violations(state, closure_contract))
    ids, duplicate_errors = _id_index(state)
    violations.extend(duplicate_errors)

    violations.extend(_unclassified_secret_violations(state))

    for ref, path, owner in _references(state):
        if ref.startswith("candidate:") or ref.startswith("CAND-"):
            violations.append(Violation("plan.candidate-id", path, "candidate identity cannot enter canonical plan state", owner))
        if is_local_id(ref) and ref not in ids:
            violations.append(Violation("plan.ref-missing", path, f"reference does not exist: {ref}", owner))

    for collection, position, item in _objects(state):
        object_id = item.get("id")
        if isinstance(object_id, str) and (object_id.startswith("CAND-") or object_id.startswith("candidate:")):
            violations.append(Violation("plan.candidate-id", pointer((collection, position, "id")), "candidate identity cannot enter canonical plan IDs", object_id))
    for decision_index, decision in enumerate(state.get("decisions", [])):
        if not isinstance(decision, dict):
            continue
        if decision.get("provenance") == "default_policy" and (
            decision.get("materiality") != "low" or decision.get("reversibility") != "local"
        ):
            violations.append(Violation("plan.default-unsafe", pointer(("decisions", decision_index)), "default policy decisions must be low-materiality and locally reversible", decision.get("id")))
        if state.get("execution_policy") == "autonomous_closure" and decision.get("contract_effect") == "requires_new_epoch":
            violations.append(Violation("plan.contract-epoch-required", pointer(("decisions", decision_index, "contract_effect")), "accepted contract-changing decision requires a new contract epoch before execution", decision.get("id")))

    graph = _node_graph(state)
    for cycle in _control_cycles(graph):
        violations.append(Violation("plan.control-cycle", "/nodes", "blocking control cycle: " + " -> ".join(cycle), cycle[0]))

    node_by_id = {node.get("id"): node for node in state.get("nodes", [])}
    evidence_by_id = {item.get("id"): item for item in state.get("evidence", [])}
    approval_by_id = {item.get("id"): item for item in state.get("approvals", [])}

    frontier = state.get("current_frontier", [])
    for index, node_id in enumerate(frontier):
        node = node_by_id.get(node_id)
        if not node or node.get("status") != "ready":
            violations.append(Violation("plan.frontier-stale", pointer(("current_frontier", index)), "frontier item must name a ready node", node_id))
            continue
        unsatisfied = [dep for dep in node.get("depends_on", []) if node_by_id.get(dep, {}).get("status") not in SATISFIED_NODE_STATUSES]
        if unsatisfied:
            violations.append(Violation("plan.frontier-stale", pointer(("current_frontier", index)), f"blocking dependencies are not complete: {unsatisfied}", node_id))

    allowed_writes = state.get("scope", {}).get("allowed_writes", [])
    for index, node in enumerate(state.get("nodes", [])):
        node_id = node.get("id")
        verifier = node.get("verifier", {})
        command_ref = verifier.get("command_ref")
        if node.get("status") in LIVE_NODE_STATUSES and (
            (verifier.get("kind") == "command" and not verifier_ref_is_structured(command_ref))
            or (command_ref is not None and not verifier_ref_is_structured(command_ref))
        ):
            violations.append(
                Violation(
                    "plan.verifier-unresolved",
                    pointer(("nodes", index, "verifier", "command_ref")),
                    "executable command verifier requires a supported namespace:target reference",
                    node_id,
                )
            )
        if node.get("status") == "done":
            required = set(node.get("outputs", [])) | set(node.get("verifier", {}).get("required_evidence", []))
            missing = [ref for ref in sorted(required) if ref.startswith("E-") and evidence_by_id.get(ref, {}).get("status") != "observed"]
            if missing:
                violations.append(Violation("plan.done-without-evidence", pointer(("nodes", index, "status")), f"done node lacks observed evidence: {missing}", node_id))
        for write_index, path in enumerate(node.get("write_set", [])):
            if not path_allowed(path, allowed_writes):
                violations.append(Violation("plan.scope-write", pointer(("nodes", index, "write_set", write_index)), f"write is outside allowed scope: {path}", node_id))

        effect = node.get("side_effect_level")
        retry = node.get("retry", {})
        if retry.get("allowed") and (
            (effect in {"external_non_idempotent", "destructive"} and retry.get("idempotency") not in {"idempotency_key", "manual_reconciliation"})
            or (retry.get("idempotency") == "idempotency_key" and not retry.get("idempotency_key"))
            or retry.get("max_attempts", 0) < 1
        ):
            violations.append(Violation("plan.retry-unsafe", pointer(("nodes", index, "retry")), "retry policy is unsafe for this side effect", node_id))
        if not retry.get("allowed") and retry.get("max_attempts", 0) > 1:
            violations.append(Violation("plan.retry-unsafe", pointer(("nodes", index, "retry", "max_attempts")), "disabled retry cannot allow multiple attempts", node_id))

        if effect in EXTERNAL_EFFECTS:
            approval_edges = [edge for edge in state.get("edges", []) if edge.get("kind") == "approval" and edge.get("to") == node_id]
            granted = any(approval_by_id.get(edge.get("from"), {}).get("status") == "granted" for edge in approval_edges)
            if not granted:
                violations.append(Violation("plan.approval-missing", pointer(("nodes", index, "side_effect_level")), "external/destructive node lacks a granted approval edge", node_id))

        high_risk = effect in EXTERNAL_EFFECTS or node.get("kind") in HIGH_RISK_KINDS
        invariant_bound = any(str(ref).startswith("I-") for ref in node.get("inputs", [])) or _has_edge(state, "invariant", "I-", node_id)
        if high_risk and not invariant_bound:
            violations.append(Violation("plan.invariant-unbound", pointer(("nodes", index, "inputs")), "high-risk node is not bound to a global invariant", node_id))

        if node.get("status") == "fog" and (node_id in frontier or node.get("write_set") or node.get("outputs")):
            violations.append(Violation("plan.fog-executed", pointer(("nodes", index, "status")), "fog node cannot be executable or produce effects", node_id))

    for index, evidence in enumerate(state.get("evidence", [])):
        if evidence.get("status") != "observed":
            continue
        policy = evidence.get("freshness_policy", {})
        kind = policy.get("kind")
        missing: list[str] = []
        if kind not in {"source_bound", "external_time_bound", "stable"}:
            missing.append("freshness_policy")
        if kind == "source_bound" and not evidence.get("source_revision"):
            missing.append("source_revision")
        if kind == "external_time_bound":
            if not policy.get("max_age_hours") and not policy.get("expected_version"):
                missing.append("max_age_hours or expected_version")
            if policy.get("max_age_hours") and not evidence.get("observed_at"):
                missing.append("observed_at")
            if policy.get("expected_version") and not evidence.get("external_version"):
                missing.append("external_version")
        if missing:
            violations.append(
                Violation(
                    "plan.evidence-unbound",
                    pointer(("evidence", index, "freshness_policy")),
                    f"observed evidence lacks freshness binding: {', '.join(missing)}",
                    evidence.get("id"),
                )
            )

    if current_revision and state.get("source", {}).get("base_revision") not in {current_revision, "explicit-unversioned"}:
        violations.append(Violation("plan.source-stale", "/source/base_revision", "base revision differs from current revision"))
    if current_scope_hash and state.get("source", {}).get("scope_hash") != current_scope_hash:
        violations.append(Violation("plan.source-stale", "/source/scope_hash", "scope hash differs from current scope"))
    if state.get("content_hash") and state["content_hash"] != canonical_state_hash(state):
        violations.append(Violation("plan.source-stale", "/content_hash", "content hash does not match canonical plan state"))

    for index, snapshot in enumerate(state.get("snapshots", [])):
        if snapshot.get("kind") in {"line", "snippet", "symbol", "capsule"} and not snapshot.get("source_revision"):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "source_revision")), "snapshot kind requires source_revision", snapshot.get("id")))
        if snapshot.get("kind") == "symbol" and not snapshot.get("symbol"):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "symbol")), "symbol snapshot requires an identity token", snapshot.get("id")))
        if snapshot.get("kind") in {"line", "snippet", "capsule"} and not snapshot.get("content_hash"):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "content_hash")), "content-bound snapshot requires content_hash", snapshot.get("id")))
        if snapshot.get("kind") == "capsule" and (
            not snapshot.get("plan_state_hash") or not snapshot.get("plan_state_version")
        ):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index)), "capsule snapshot requires plan_state_hash and plan_state_version", snapshot.get("id")))
        if snapshot.get("line_start") and snapshot.get("line_end") and snapshot["line_end"] < snapshot["line_start"]:
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "line_end")), "line_end cannot precede line_start", snapshot.get("id")))

    frontier_nodes = [node_by_id[node_id] for node_id in frontier if node_id in node_by_id and node_by_id[node_id].get("status") == "ready"]
    for left_index, left in enumerate(frontier_nodes):
        for right in frontier_nodes[left_index + 1 :]:
            write_conflict = any(patterns_may_overlap(a, b) for a in left.get("write_set", []) for b in right.get("write_set", []))
            resource_conflict = bool(set(left.get("resource_set", [])) & set(right.get("resource_set", [])))
            if write_conflict or resource_conflict:
                violations.append(Violation("plan.effect-conflict", "/current_frontier", f"frontier nodes conflict: {left['id']} and {right['id']}", left["id"]))

    for source_id, source_node in node_by_id.items():
        if source_node.get("status") != "invalidated":
            continue
        for target_id in graph.get(source_id, set()):
            if node_by_id.get(target_id, {}).get("status") in LIVE_NODE_STATUSES:
                violations.append(Violation("plan.invalidated-dependent-live", "/nodes", f"{target_id} remains live after {source_id} was invalidated", target_id))

    closure = state.get("closure", {})
    if closure.get("status") == "complete":
        missing = [ref for ref in closure.get("required_evidence", []) if evidence_by_id.get(ref, {}).get("status") != "observed"]
        blocking_gaps = [gap.get("id") for gap in state.get("gaps", []) if gap.get("status") != "closed" and gap.get("blocks")]
        unfinished = [node.get("id") for node in state.get("nodes", []) if node.get("status") not in SATISFIED_NODE_STATUSES]
        if missing or blocking_gaps or unfinished:
            violations.append(Violation("plan.closure-premature", "/closure/status", f"closure has missing evidence={missing}, blocking gaps={blocking_gaps}, unfinished nodes={unfinished}"))

    if state.get("profile") == "brief" and (state.get("nodes") or state.get("edges") or state.get("current_frontier")):
        violations.append(Violation("plan.profile-overbuilt", "/profile", "Brief profile must not carry durable graph state"))

    claims: dict[str, set[str]] = defaultdict(set)
    claim_paths: dict[str, str] = {}
    for index, claim in enumerate(state.get("policy_claims", [])):
        policy = claim.get("policy")
        owner = claim.get("normative_owner")
        if policy and owner:
            claims[policy].add(owner)
            claim_paths.setdefault(policy, pointer(("policy_claims", index)))
    for policy, owners in claims.items():
        if len(owners) > 1:
            violations.append(Violation("plan.owner-duplicate", claim_paths[policy], f"policy has multiple normative owners: {sorted(owners)}"))

    return violations


def validate_file(
    path: Path,
    schema_path: Path,
    *,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
    closure_contract_path: Path | None = None,
    closure_contract_schema_path: Path = DEFAULT_CONTRACT_SCHEMA,
) -> tuple[dict[str, Any] | None, list[Violation]]:
    try:
        state = load_json(path)
        schema = load_json(schema_path)
    except (OSError, PlanInputError) as exc:
        return None, [Violation("plan.schema", "", str(exc))]
    schema_errors = validate_against_schema(state, schema)
    if schema_errors or not isinstance(state, dict):
        return state if isinstance(state, dict) else None, schema_errors
    closure_contract: dict[str, Any] | None = None
    contract_errors: list[Violation] = []
    if closure_contract_path is not None:
        try:
            closure_contract = load_contract(closure_contract_path)
            contract_schema = load_contract(closure_contract_schema_path)
            contract_errors = [Violation("plan.contract-invalid", item.path, f"{item.code}: {item.message}", item.object_id) for item in validate_contract(closure_contract, contract_schema)]
        except (ContractInputError, OSError, TypeError, ValueError) as exc:
            contract_errors = [Violation("plan.contract-invalid", "/closure_contract_ref", str(exc))]
    return state, contract_errors + semantic_violations(
        state,
        current_revision=current_revision,
        current_scope_hash=current_scope_hash,
        closure_contract=closure_contract,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--current-revision")
    parser.add_argument("--scope-hash")
    parser.add_argument("--closure-contract", type=Path)
    parser.add_argument("--closure-contract-schema", type=Path, default=DEFAULT_CONTRACT_SCHEMA)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state, violations = validate_file(
        args.state,
        args.schema,
        current_revision=args.current_revision,
        current_scope_hash=args.scope_hash,
        closure_contract_path=args.closure_contract,
        closure_contract_schema_path=args.closure_contract_schema,
    )
    if args.as_json:
        print(json.dumps(json_output(not violations, violations, plan_id=(state or {}).get("plan_id")), ensure_ascii=False, indent=2))
    elif violations:
        for item in violations:
            label = f"{item.object_id} " if item.object_id else ""
            print(f"{label}{item.code} {item.path}: {item.message}")
    else:
        print(f"OK: plan state valid ({state.get('plan_id')})")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
