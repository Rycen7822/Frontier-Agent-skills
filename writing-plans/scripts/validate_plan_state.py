#!/usr/bin/env python3
"""Deterministically validate writing-plans durable state."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any, Iterable

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

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "plan-state.schema.json"
LIVE_NODE_STATUSES = {"ready", "in_progress", "done"}
SATISFIED_NODE_STATUSES = {"done", "skipped", "superseded"}
EXTERNAL_EFFECTS = {"external_reversible", "external_non_idempotent", "destructive"}
HIGH_RISK_KINDS = {"migration", "approval", "release"}


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
    yield from emit(state.get("completion", {}).get("required_evidence", []), ("completion", "required_evidence"))
    yield from emit(state.get("rollback", {}).get("verifier_refs", []), ("rollback", "verifier_refs"))


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


def semantic_violations(
    state: dict[str, Any],
    *,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
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

    invariant_by_id = {item.get("id"): item for item in state.get("global_invariants", []) if isinstance(item, dict)}
    for index, invariant in enumerate(state.get("global_invariants", [])):
        locality = invariant.get("locality")
        applicability = invariant.get("applicability")
        targets = invariant.get("targets", [])
        valid_shape = (
            (locality == "global" and applicability == "always" and not targets)
            or (locality == "node_set" and applicability == "when_target_active" and bool(targets) and all(str(item).startswith("P-") for item in targets))
            or (locality == "resource_set" and applicability == "when_resource_touched" and bool(targets))
        )
        if not valid_shape:
            violations.append(Violation("plan.invariant-applicability", pointer(("global_invariants", index)), "invariant locality, applicability, and targets are inconsistent", invariant.get("id")))

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

    allowed_writes = state.get("scope_binding", {}).get("allowed_plan_outputs", [])
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
        bound_invariant_ids = {str(ref) for ref in node.get("inputs", []) if str(ref).startswith("I-")}
        bound_invariant_ids.update(
            str(edge.get("from"))
            for edge in state.get("edges", [])
            if edge.get("kind") == "invariant" and edge.get("to") == node_id and str(edge.get("from", "")).startswith("I-")
        )
        invariant_bound = any(
            invariant_id in invariant_by_id and _invariant_applies(invariant_by_id[invariant_id], node)
            for invariant_id in bound_invariant_ids
        )
        if high_risk and not invariant_bound:
            violations.append(Violation("plan.invariant-unbound", pointer(("nodes", index, "inputs")), "high-risk node lacks an applicable targeted invariant", node_id))

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

    source_identity = state.get("source_identity", {})
    if current_revision and source_identity.get("kind") == "repository" and source_identity.get("head_commit") != current_revision:
        violations.append(Violation("plan.source-stale", "/source_identity/head_commit", "repository HEAD differs from current revision"))
    if current_scope_hash and state.get("scope_binding", {}).get("binding_id") != current_scope_hash:
        violations.append(Violation("plan.source-stale", "/scope_binding/binding_id", "planning scope binding differs from current scope"))
    if state.get("content_hash") and state["content_hash"] != canonical_state_hash(state):
        violations.append(Violation("plan.source-stale", "/content_hash", "content hash does not match canonical plan state"))

    for index, snapshot in enumerate(state.get("snapshots", [])):
        if snapshot.get("kind") in {"line", "snippet", "symbol"} and not snapshot.get("source_revision"):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "source_revision")), "snapshot kind requires source_revision", snapshot.get("id")))
        if snapshot.get("kind") == "symbol" and not snapshot.get("symbol"):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "symbol")), "symbol snapshot requires an identity token", snapshot.get("id")))
        if snapshot.get("kind") in {"line", "snippet"} and not snapshot.get("content_hash"):
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "content_hash")), "content-bound snapshot requires content_hash", snapshot.get("id")))
        if snapshot.get("line_start") and snapshot.get("line_end") and snapshot["line_end"] < snapshot["line_start"]:
            violations.append(Violation("plan.snapshot-unbound", pointer(("snapshots", index, "line_end")), "line_end cannot precede line_start", snapshot.get("id")))

    frontier_nodes = [node_by_id[node_id] for node_id in frontier if node_id in node_by_id and node_by_id[node_id].get("status") == "ready"]
    for left_index, left in enumerate(frontier_nodes):
        for right in frontier_nodes[left_index + 1 :]:
            write_write = any(patterns_may_overlap(a, b) for a in left.get("write_set", []) for b in right.get("write_set", []))
            write_read = any(patterns_may_overlap(a, b) for a in left.get("write_set", []) for b in right.get("read_set", []))
            read_write = any(patterns_may_overlap(a, b) for a in left.get("read_set", []) for b in right.get("write_set", []))
            resource_conflict = bool(set(left.get("resource_set", [])) & set(right.get("resource_set", [])))
            effect_conflict = any(patterns_may_overlap(a, b) for a in left.get("effect_set", []) for b in right.get("effect_set", []))
            conflicts = [
                name
                for name, present in (
                    ("write-write", write_write),
                    ("write-read", write_read),
                    ("read-write", read_write),
                    ("resource", resource_conflict),
                    ("effect", effect_conflict),
                )
                if present
            ]
            if conflicts:
                violations.append(Violation("plan.effect-conflict", "/current_frontier", f"frontier nodes conflict ({', '.join(conflicts)}): {left['id']} and {right['id']}", left["id"]))

    for source_id, source_node in node_by_id.items():
        if source_node.get("status") != "invalidated":
            continue
        for target_id in graph.get(source_id, set()):
            if node_by_id.get(target_id, {}).get("status") in LIVE_NODE_STATUSES:
                violations.append(Violation("plan.invalidated-dependent-live", "/nodes", f"{target_id} remains live after {source_id} was invalidated", target_id))

    completion = state.get("completion", {})
    if completion.get("status") == "complete":
        missing = [ref for ref in completion.get("required_evidence", []) if evidence_by_id.get(ref, {}).get("status") != "observed"]
        blocking_gaps = [gap.get("id") for gap in state.get("gaps", []) if gap.get("status") != "closed" and gap.get("blocks")]
        unfinished = [node.get("id") for node in state.get("nodes", []) if node.get("status") not in SATISFIED_NODE_STATUSES]
        if missing or blocking_gaps or unfinished:
            violations.append(Violation("plan.completion-premature", "/completion/status", f"completion has missing evidence={missing}, blocking gaps={blocking_gaps}, unfinished nodes={unfinished}"))

    queue = state.get("pending_card_instances", [])
    queue_ids = [item.get("card_instance_id") for item in queue if isinstance(item, dict)]
    if len(queue_ids) != len(set(queue_ids)):
        violations.append(Violation("plan.queue-duplicate", "/pending_card_instances", "pending card instance IDs must be unique"))
    if state.get("status") in {"blocked", "completed", "superseded"} and queue:
        violations.append(Violation("plan.queue-terminal", "/pending_card_instances", "terminal Program state must have an empty queue"))
    if queue and state.get("status") not in {"drafting", "ready", "active"}:
        violations.append(Violation("plan.queue-status", "/pending_card_instances", "only live Program state may have pending cards"))
    for index, item in enumerate(queue):
        subject = item.get("subject_ref") if isinstance(item, dict) else None
        if subject is not None and (not str(subject).startswith("P-") or subject not in node_by_id):
            violations.append(Violation("plan.queue-subject", pointer(("pending_card_instances", index, "subject_ref")), "queue subject must name a local plan node"))

    scope_binding = state.get("scope_binding", {})
    if scope_binding.get("initial_source_identity_hash") != source_identity.get("identity_hash") and state.get("state_version") == 1:
        violations.append(Violation("plan.source-binding", "/source_identity/identity_hash", "initial source identity does not match planning scope"))
    transition = state.get("last_transition", {})
    if transition.get("scope_binding_id") != scope_binding.get("binding_id"):
        violations.append(Violation("plan.transition-scope", "/last_transition/scope_binding_id", "transition does not bind the planning scope"))
    if transition.get("transition_kind") == "init":
        if (
            state.get("state_version") != 1
            or transition.get("prior_state_version") != 0
            or transition.get("prior_content_hash") is not None
            or transition.get("completed_card_instance_id") is not None
            or transition.get("completion_id") != state.get("initial_completion_id")
            or transition.get("enqueued_card_instance_ids") != queue_ids
            or transition.get("inline_render_completion") is not None
        ):
            violations.append(Violation("plan.transition-init", "/last_transition", "initial transition does not bind version 0 and the exact initial queue"))
    elif transition.get("transition_kind") == "card" and transition.get("completed_card_instance_id") is None:
        violations.append(Violation("plan.transition-card", "/last_transition/completed_card_instance_id", "card transition must bind the completed queue instance"))

    artifact_completion_ids = [item.get("completion_id") for item in state.get("artifacts", []) if isinstance(item, dict)]
    if len(artifact_completion_ids) != len(set(artifact_completion_ids)):
        violations.append(Violation("plan.artifact-duplicate", "/artifacts", "durable artifacts must be unique by completion ID"))
    if any(item.get("scope_binding_id") != scope_binding.get("binding_id") for item in state.get("artifacts", []) if isinstance(item, dict)):
        violations.append(Violation("plan.artifact-scope", "/artifacts", "durable artifact does not bind the planning scope"))
    inline = transition.get("inline_render_completion")
    if inline is not None and len(json.dumps(inline, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")) > 8192:
        violations.append(Violation("plan.inline-render-budget", "/last_transition/inline_render_completion", "inline render completion exceeds 8192 bytes"))

    claims: dict[str, set[tuple[str, str]]] = defaultdict(set)
    claim_paths: dict[str, str] = {}
    for index, claim in enumerate(state.get("policy_claims", [])):
        policy_id = claim.get("policy_id")
        bundle_version = claim.get("bundle_version")
        policy_hash = claim.get("policy_hash")
        if policy_id and bundle_version and policy_hash:
            claims[policy_id].add((bundle_version, policy_hash))
            claim_paths.setdefault(policy_id, pointer(("policy_claims", index)))
            if bundle_version != state.get("bundle_id"):
                violations.append(Violation("plan.policy-binding", pointer(("policy_claims", index, "bundle_version")), "policy claim bundle differs from plan bundle identity", policy_id))
    for policy_id, bindings in claims.items():
        if len(bindings) > 1:
            violations.append(Violation("plan.owner-duplicate", claim_paths[policy_id], f"policy has multiple bundle/hash bindings: {sorted(bindings)}"))

    return violations


def validate_file(
    path: Path,
    schema_path: Path,
    *,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
) -> tuple[dict[str, Any] | None, list[Violation]]:
    try:
        state = load_json(path)
        schema = load_json(schema_path)
    except (OSError, PlanInputError) as exc:
        return None, [Violation("plan.schema", "", str(exc))]
    schema_errors = validate_against_schema(state, schema)
    if schema_errors or not isinstance(state, dict):
        return state if isinstance(state, dict) else None, schema_errors
    return state, semantic_violations(
        state,
        current_revision=current_revision,
        current_scope_hash=current_scope_hash,
    )


def _invariant_applies(invariant: dict[str, Any], node: dict[str, Any]) -> bool:
    locality = invariant.get("locality")
    targets = invariant.get("targets", [])
    if locality == "global":
        return invariant.get("applicability") == "always" and not targets
    if locality == "node_set":
        return invariant.get("applicability") == "when_target_active" and node.get("id") in targets
    if locality == "resource_set":
        resources = list(node.get("resource_set", [])) + list(node.get("effect_set", []))
        return invariant.get("applicability") == "when_resource_touched" and any(
            patterns_may_overlap(target, resource) for target in targets for resource in resources
        )
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--current-revision")
    parser.add_argument("--scope-hash")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state, violations = validate_file(
        args.state,
        args.schema,
        current_revision=args.current_revision,
        current_scope_hash=args.scope_hash,
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
