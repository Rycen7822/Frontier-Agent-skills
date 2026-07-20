#!/usr/bin/env python3
"""Validate SQW workflow state, event streams, and canonical transitions."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from _workflow_state import (
    InputError,
    Violation,
    canonical_hash,
    contains_secret_like,
    is_local_id,
    load_json,
    load_json_lines,
    path_allowed,
    patterns_may_overlap,
    pointer,
    validate_against_schema,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_SCHEMA = ROOT / "schemas" / "workflow-state.schema.json"
DEFAULT_EVENT_SCHEMA = ROOT / "schemas" / "workflow-event.schema.json"
EFFECT_ORDER = {
    "none": 0,
    "local_ephemeral": 1,
    "local_reversible": 2,
    "external_reversible": 3,
    "external_non_idempotent": 4,
    "destructive": 5,
}
SATISFIED_NODE_STATUSES = {"done", "skipped", "superseded"}
LIVE_NODE_STATUSES = {"pending", "ready", "running", "blocked", "failed", "invalidated"}
EXTERNAL_EFFECTS = {"external_reversible", "external_non_idempotent", "destructive"}
WORKER_EVENT_TYPES = {"node_output_committed", "node_failed", "artifact_observed", "plan_change_proposed"}
REVIEWER_EVENT_TYPES = {"review_submitted", "artifact_observed"}
TOOL_EVENT_TYPES = {"artifact_observed"}
CONTROLLER_ONLY_EVENT_TYPES = {
    "source_drift_detected", "workflow_completed",
}
NODE_EVENT_TYPES = {"node_refined", "node_started", "node_output_committed", "node_completed", "node_failed"}
RUN_EVENT_TYPES = {"node_started", "node_output_committed", "node_completed", "node_failed"}


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(character in "0123456789abcdef" for character in value[7:])


WORKFLOW_TRANSITIONS = {
    "open": {"active", "aborted"},
    "active": {"blocked", "completed", "aborted"},
    "blocked": {"active", "completed", "aborted"},
    "completed": set(),
    "aborted": set(),
}
NODE_TRANSITIONS = {
    "pending": {"ready", "blocked", "skipped", "cancelled", "superseded"},
    "ready": {"running", "blocked", "skipped", "cancelled", "superseded"},
    "running": {"done", "failed", "blocked", "cancelled"},
    "blocked": {"ready", "cancelled", "superseded"},
    "done": {"invalidated"},
    "failed": {"ready", "cancelled", "superseded"},
    "invalidated": {"ready", "cancelled", "superseded"},
    "superseded": set(),
    "skipped": set(),
    "cancelled": set(),
}
def _objects(state: dict[str, Any]) -> Iterable[tuple[str, int, dict[str, Any]]]:
    for collection in ("global_invariants", "nodes", "verifiers", "edges", "artifacts", "recent_failures"):
        for index, item in enumerate(state.get(collection, [])):
            if isinstance(item, dict):
                yield collection, index, item
    for index, item in enumerate(state.get("authority", {}).get("approvals", [])):
        if isinstance(item, dict):
            yield "authority/approvals", index, item


def _id_index(state: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[Violation]]:
    result: dict[str, dict[str, Any]] = {}
    paths: dict[str, str] = {}
    violations: list[Violation] = []
    for collection, index, item in _objects(state):
        object_id = item.get("id")
        if not isinstance(object_id, str):
            continue
        path = f"/{collection}/{index}/id"
        if object_id in result:
            violations.append(Violation("workflow.id-duplicate", path, f"ID duplicates {paths[object_id]}", object_id))
        else:
            result[object_id], paths[object_id] = item, path
    return result, violations


def _node_graph(state: dict[str, Any]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {item.get("id"): set() for item in state.get("nodes", []) if isinstance(item.get("id"), str)}
    for node in state.get("nodes", []):
        for dependency in node.get("depends_on", []):
            if dependency in graph and node.get("id") in graph:
                graph[dependency].add(node["id"])
    for edge in state.get("edges", []):
        if edge.get("kind") == "control" and edge.get("from") in graph and edge.get("to") in graph:
            graph[edge["from"]].add(edge["to"])
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
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
        for target in sorted(graph.get(node, set())):
            visit(target)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)
    return cycles


def _reference_rows(state: dict[str, Any]) -> Iterable[tuple[str, str, str | None]]:
    for node_index, node in enumerate(state.get("nodes", [])):
        node_id = node.get("id")
        for field in ("depends_on", "input_refs", "verifier_refs", "required_approvals"):
            for index, ref in enumerate(node.get(field, [])):
                yield ref, pointer(("nodes", node_index, field, index)), node_id
    for index, verifier in enumerate(state.get("verifiers", [])):
        for field in ("required_evidence", "observed_evidence"):
            for ref_index, ref in enumerate(verifier.get(field, [])):
                yield ref, pointer(("verifiers", index, field, ref_index)), verifier.get("id")
    for index, edge in enumerate(state.get("edges", [])):
        yield edge.get("from"), pointer(("edges", index, "from")), edge.get("id")
        yield edge.get("to"), pointer(("edges", index, "to")), edge.get("id")
    for index, ref in enumerate(state.get("frontier", [])):
        yield ref, pointer(("frontier", index)), None
    for index, artifact in enumerate(state.get("artifacts", [])):
        yield artifact.get("producer", {}).get("node_id"), pointer(("artifacts", index, "producer", "node_id")), artifact.get("id")
    for index, failure in enumerate(state.get("recent_failures", [])):
        yield failure.get("node_id"), pointer(("recent_failures", index, "node_id")), failure.get("id")
def validate_state(
    state: Any,
    schema: dict[str, Any],
    *,
    current_revision: str | None = None,
    current_scope_binding_id: str | None = None,
    current_plan_hash: str | None = None,
) -> list[Violation]:
    violations = validate_against_schema(state, schema, code="workflow.schema")
    schema_failed = bool(violations)
    if not isinstance(state, dict):
        return violations

    if schema_failed:
        return violations

    active = state.get("active_owners", {})
    primary = active.get("primary")
    normative = active.get("normative", [])
    companions = active.get("companions", [])
    active_ids = [primary, *normative, *companions]
    active_ids = [owner_id for owner_id in active_ids if isinstance(owner_id, str)]
    if len(active_ids) != len(set(active_ids)):
        violations.append(Violation("workflow.owner-stack", "/active_owners", "active owner IDs must be unique"))

    snapshot = state["source_snapshot"]
    records = snapshot["scoped_records"]
    record_paths = [item["path"] for item in records]
    scope_patterns = sorted(set(state["scope_binding"]["allowed_reads"]) | set(state["scope_binding"]["allowed_writes"]))
    if snapshot["identity_hash"] != state["source_identity"]["identity_hash"] or snapshot["kind"] != state["source_identity"]["kind"]:
        violations.append(Violation("workflow.source-snapshot", "/source_snapshot", "source snapshot must bind current source identity"))
    if (snapshot["kind"] == "repository" and (snapshot["head_commit"] is None or snapshot["head_tree"] is None)) or (snapshot["kind"] == "unversioned" and (snapshot["head_commit"] is not None or snapshot["head_tree"] is not None)):
        violations.append(Violation("workflow.source-snapshot", "/source_snapshot/head_commit", "repository snapshots require HEAD and tree; unversioned snapshots forbid them"))
    if record_paths != sorted(set(record_paths)) or any(not path_allowed(path, scope_patterns) for path in record_paths):
        violations.append(Violation("workflow.source-snapshot", "/source_snapshot/scoped_records", "scoped source records must be sorted, unique, and inside the immutable scope binding"))

    plan_id = state.get("plan_ref", {}).get("plan_id")
    plan_prefix = f"plan:{plan_id}#" if isinstance(plan_id, str) else None
    for node_index, node in enumerate(state.get("nodes", [])):
        candidate_refs = [("plan_node_ref", node.get("plan_node_ref"))]
        candidate_refs.extend(("input_refs", ref) for ref in node.get("input_refs", []) if str(ref).startswith("plan:"))
        for field, ref in candidate_refs:
            if isinstance(ref, str) and ref.startswith("plan:") and (plan_prefix is None or not ref.startswith(plan_prefix)):
                violations.append(Violation("workflow.plan-ref-mismatch", pointer(("nodes", node_index, field)), f"plan reference {ref} does not match workflow plan_ref namespace {plan_prefix}", node.get("id")))

    completion_bindings: list[tuple[str, str, int, str | None]] = []
    completion_ids: set[str] = set()
    operation_ids: set[str] = set()
    source_cursor = state["bootstrap"]["initial_source_identity_hash"]
    for index, entry in enumerate(state.get("card_completions", [])):
        operation_id = entry["operation_id"]
        prior_version = entry["prior_state_version"]
        prior_hash = entry["prior_state_hash"]
        completion_id = entry.get("completion_id") if entry["storage"] == "materialized" else entry.get("completion", {}).get("content_hash")
        if not _is_hash(completion_id):
            violations.append(Violation("workflow.completion-binding", pointer(("card_completions", index)), "completion entry lacks a canonical completion ID"))
            continue
        if operation_id in operation_ids or completion_id in completion_ids:
            violations.append(Violation("workflow.completion-binding", pointer(("card_completions", index)), "completion and operation IDs must be exact-once", completion_id))
        operation_ids.add(operation_id)
        completion_ids.add(completion_id)
        if prior_version >= state["state_version"] or (prior_version == 0) != (prior_hash is None):
            violations.append(Violation("workflow.completion-binding", pointer(("card_completions", index)), "prior state version/hash binding is inconsistent", completion_id))
        if entry["storage"] == "materialized":
            locator = entry["content_locator"]
            if (
                locator["artifact_id"] != entry["artifact_id"]
                or locator["content_hash"] != completion_id
                or entry["scope_binding_id"] != state["scope_binding"]["binding_id"]
            ):
                violations.append(Violation("workflow.completion-binding", pointer(("card_completions", index)), "materialized completion locator, content, or scope binding differs", completion_id))
            source_cursor = entry["source_hash"]
        else:
            source_transition = entry.get("completion", {}).get("source_transition")
            if source_transition is not None:
                changed_paths = source_transition["changed_paths"]
                expected_changed_hash = "sha256:" + sha256(json.dumps(changed_paths, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
                if source_transition["changed_paths_hash"] != expected_changed_hash:
                    violations.append(Violation("workflow.source-transition", pointer(("card_completions", index, "completion", "source_transition")), "changed paths hash is invalid", completion_id))
                if source_transition["before_identity_hash"] != source_cursor:
                    violations.append(Violation("workflow.source-transition", pointer(("card_completions", index, "completion", "source_transition", "before_identity_hash")), "source transition does not continue the committed identity chain", completion_id))
                if any(not path_allowed(item["path"], state["scope_binding"]["allowed_writes"]) for item in changed_paths):
                    violations.append(Violation("workflow.source-transition", pointer(("card_completions", index, "completion", "source_transition", "changed_paths")), "source transition exceeds allowed_writes", completion_id))
                if source_transition["after_identity_hash"] != state["source_identity"]["identity_hash"] and entry["operation_id"] == state["last_transition"]["operation_id"]:
                    violations.append(Violation("workflow.source-transition", pointer(("card_completions", index, "completion", "source_transition", "after_identity_hash")), "current transition must bind current source identity", completion_id))
                source_cursor = source_transition["after_identity_hash"]
        completion_bindings.append((operation_id, completion_id, prior_version, prior_hash))

    if source_cursor != state["source_identity"]["identity_hash"]:
        violations.append(Violation("workflow.source-transition", "/source_identity/identity_hash", "completion source chain does not reach current source identity"))

    transition = state["last_transition"]
    current_binding = (
        transition["operation_id"], transition["completion_id"],
        transition["prior_state_version"], transition["prior_state_hash"],
    )
    if current_binding not in completion_bindings or transition["prior_state_version"] != state["state_version"] - 1:
        violations.append(Violation("workflow.transition-binding", "/last_transition", "last transition must bind the current exact completion and prior state"))
    if transition["transition_kind"] == "bootstrap" and state["state_version"] != 1:
        violations.append(Violation("workflow.transition-binding", "/last_transition/transition_kind", "bootstrap transition is only valid for state version 1"))

    ids, duplicate_violations = _id_index(state)
    violations.extend(duplicate_violations)
    declared_outputs = {ref for node in state.get("nodes", []) for ref in node.get("output_refs", []) if is_local_id(ref)}
    for ref, path, owner in _reference_rows(state):
        if is_local_id(ref) and not str(ref).startswith("RUN-") and ref not in ids and ref not in declared_outputs:
            violations.append(Violation("workflow.ref-missing", path, f"reference does not exist: {ref}", owner))

    graph = _node_graph(state)
    for cycle in _cycles(graph):
        violations.append(Violation("workflow.control-cycle", "/nodes", "blocking control cycle: " + " -> ".join(cycle), cycle[0]))

    nodes = {item.get("id"): item for item in state.get("nodes", [])}
    artifacts = {item.get("id"): item for item in state.get("artifacts", [])}
    verifiers = {item.get("id"): item for item in state.get("verifiers", [])}
    approvals = {item.get("id"): item for item in state.get("authority", {}).get("approvals", [])}
    declared_resources = {resource for node in state.get("nodes", []) for resource in node.get("resource_set", [])}
    for index, invariant in enumerate(state.get("global_invariants", [])):
        locality = invariant.get("locality")
        targets = set(invariant.get("targets", []))
        if locality == "global" and targets:
            violations.append(Violation("workflow.invariant-locality", pointer(("global_invariants", index, "targets")), "global invariant must not declare local targets", invariant.get("id")))
        elif locality == "node_set" and (not targets or not targets.issubset(nodes)):
            violations.append(Violation("workflow.invariant-locality", pointer(("global_invariants", index, "targets")), "node-set invariant targets must resolve to workflow nodes", invariant.get("id")))
        elif locality == "resource_set" and (not targets or not targets.issubset(declared_resources)):
            violations.append(Violation("workflow.invariant-locality", pointer(("global_invariants", index, "targets")), "resource-set invariant targets must resolve to declared resources", invariant.get("id")))
    frontier = state.get("frontier", [])
    for index, node_id in enumerate(frontier):
        node = nodes.get(node_id)
        if not node or node.get("status") != "ready":
            violations.append(Violation("workflow.frontier-stale", pointer(("frontier", index)), "frontier must contain ready nodes", node_id))
            continue
        unsatisfied = [ref for ref in node.get("depends_on", []) if nodes.get(ref, {}).get("status") not in SATISFIED_NODE_STATUSES]
        if unsatisfied:
            violations.append(Violation("workflow.frontier-stale", pointer(("frontier", index)), f"blocking dependencies are not satisfied: {unsatisfied}", node_id))

    ceiling = EFFECT_ORDER[state["authority"]["risk_ceiling"]]
    allowed_writes = state["scope"]["allowed_writes"]
    protected_paths = state["scope"]["protected_paths"]
    for index, node in enumerate(state.get("nodes", [])):
        node_id = node.get("id")
        effect = node.get("side_effect")
        input_contracts = {item.get("ref"): item.get("schema_id") for item in node.get("input_contracts", [])}
        output_contracts = {item.get("ref"): item.get("schema_id") for item in node.get("output_contracts", [])}
        for ref in node.get("input_refs", []):
            if str(ref).startswith("EV-"):
                artifact_schema = artifacts.get(ref, {}).get("schema_id")
                if ref not in input_contracts or (artifact_schema is not None and input_contracts[ref] != artifact_schema):
                    violations.append(Violation("workflow.io-schema-mismatch", pointer(("nodes", index, "input_contracts")), f"input contract does not match artifact {ref}: expected={input_contracts.get(ref)} actual={artifact_schema}", node_id))
        for ref in node.get("output_refs", []):
            if str(ref).startswith("EV-"):
                artifact_schema = artifacts.get(ref, {}).get("schema_id")
                if ref not in output_contracts or (artifact_schema is not None and output_contracts[ref] != artifact_schema):
                    violations.append(Violation("workflow.io-schema-mismatch", pointer(("nodes", index, "output_contracts")), f"output contract does not match artifact {ref}: expected={output_contracts.get(ref)} actual={artifact_schema}", node_id))
        for write_index, write in enumerate(node.get("write_set", [])):
            protected = any(patterns_may_overlap(write, item) for item in protected_paths)
            if not path_allowed(write, allowed_writes) or protected:
                violations.append(Violation("workflow.scope-write", pointer(("nodes", index, "write_set", write_index)), f"write is outside allowed scope or intersects a protected path: {write}", node_id))
        if EFFECT_ORDER.get(effect, 99) > ceiling or (effect in EXTERNAL_EFFECTS and state["authority"]["external_writes"] != "approved") or (effect == "destructive" and state["authority"]["destructive_actions"] != "approved"):
            violations.append(Violation("workflow.authority-exceeded", pointer(("nodes", index, "side_effect")), f"side effect {effect} exceeds authority ceiling", node_id))
        if effect in EXTERNAL_EFFECTS:
            required = node.get("required_approvals", [])
            if not required or any(approvals.get(ref, {}).get("status") != "granted" for ref in required):
                violations.append(Violation("workflow.approval-missing", pointer(("nodes", index, "required_approvals")), "external or destructive node lacks a granted approval", node_id))

        retry = node.get("attempt_policy", {})
        unsafe_retry = (
            retry.get("attempts_used", 0) > retry.get("max_attempts", 0)
            or (effect in {"external_non_idempotent", "destructive"} and retry.get("max_attempts", 0) > 1 and retry.get("idempotency") not in {"idempotency_key", "manual_reconciliation"})
            or (retry.get("idempotency") == "idempotency_key" and not retry.get("idempotency_key"))
            or (retry.get("idempotency") == "not_retryable" and retry.get("max_attempts", 0) > 1)
        )
        if unsafe_retry:
            violations.append(Violation("workflow.retry-unsafe", pointer(("nodes", index, "attempt_policy")), "retry policy is unsafe for attempts or side effects", node_id))

        if node.get("status") == "done":
            missing_verifiers = [ref for ref in node.get("verifier_refs", []) if verifiers.get(ref, {}).get("status") != "passed"]
            missing_evidence: list[str] = []
            for ref in node.get("verifier_refs", []):
                verifier = verifiers.get(ref, {})
                observed = set(verifier.get("observed_evidence", []))
                for evidence_ref in verifier.get("required_evidence", []):
                    artifact = artifacts.get(evidence_ref, {})
                    classification = artifact.get("observation", {}).get("classification")
                    if evidence_ref not in observed or artifact.get("freshness") != "fresh" or classification not in {"pass", "expected_red"}:
                        missing_evidence.append(evidence_ref)
            if missing_verifiers or missing_evidence:
                violations.append(Violation("workflow.done-without-evidence", pointer(("nodes", index, "status")), f"done node lacks passed verifiers={missing_verifiers} or fresh evidence={sorted(set(missing_evidence))}", node_id))

    for collection in ("global_invariants", "nodes", "artifacts", "recent_failures"):
        for index, item in enumerate(state.get(collection, [])):
            if isinstance(item, dict) and contains_secret_like(item):
                violations.append(Violation("workflow.sensitive-unclassified", pointer((collection, index, "sensitive")), "raw credential-shaped values are forbidden even when classified; store only a controlled pointer", item.get("id")))
    for index, verifier in enumerate(state.get("verifiers", [])):
        if contains_secret_like(verifier):
            violations.append(Violation("workflow.sensitive-unclassified", pointer(("verifiers", index)), "verifier cannot contain raw credential-shaped values", verifier.get("id")))

    if state.get("state_hash") and state["state_hash"] != canonical_hash(state):
        violations.append(Violation("workflow.state-hash", "/state_hash", "state_hash does not match canonical state"))
    if current_revision and state["source"]["observed_revision"] != current_revision:
        violations.append(Violation("workflow.source-stale", "/source/observed_revision", "observed source revision differs from current revision"))
    if current_scope_binding_id and state["scope_binding"]["binding_id"] != current_scope_binding_id:
        violations.append(Violation("workflow.scope-stale", "/scope_binding/binding_id", "scope binding differs from current scope"))
    if current_plan_hash and state.get("plan_ref", {}).get("content_hash") != current_plan_hash:
        violations.append(Violation("workflow.plan-stale", "/plan_ref/content_hash", "workflow references a stale plan hash"))

    if state.get("status") == "completed":
        failed_verifiers = [ref for ref, verifier in verifiers.items() if verifier.get("status") != "passed"]
        unfinished = [node.get("id") for node in state.get("nodes", []) if node.get("status") not in SATISFIED_NODE_STATUSES]
        if failed_verifiers or unfinished or state.get("pending_background"):
            violations.append(Violation("workflow.completion-premature", "/status", f"workflow incomplete: verifiers={failed_verifiers}, nodes={unfinished}, background={state.get('pending_background')}"))
    return violations


def validate_transition(previous: dict[str, Any], current: dict[str, Any], *, actor_kind: str = "controller") -> list[Violation]:
    violations: list[Violation] = []
    if previous != current and actor_kind != "controller":
        violations.append(Violation("workflow.controller-only", "", "only controller may mutate canonical workflow state"))
    if previous.get("workflow_id") != current.get("workflow_id"):
        violations.append(Violation("workflow.identity-change", "/workflow_id", "workflow_id is immutable"))
    immutable_fields = ("mode", "request_mode", "policy_bundle_hash")
    if any(previous.get(field) != current.get(field) for field in immutable_fields):
        violations.append(Violation("workflow.identity-change", "/mode", "mode, request mode, and policy bundle hash are immutable after open"))
    if current.get("state_version") != previous.get("state_version", 0) + 1:
        violations.append(Violation("workflow.state-version", "/state_version", "transition must increment state_version by exactly one"))
    before_status, after_status = previous.get("status"), current.get("status")
    if before_status != after_status and after_status not in WORKFLOW_TRANSITIONS.get(before_status, set()):
        violations.append(Violation("workflow.status-transition", "/status", f"invalid workflow transition {before_status} -> {after_status}"))

    before_nodes = {item.get("id"): item for item in previous.get("nodes", [])}
    after_nodes = {item.get("id"): item for item in current.get("nodes", [])}
    for node_id, before in before_nodes.items():
        if node_id not in after_nodes:
            violations.append(Violation("workflow.node-deleted", "/nodes", "canonical nodes cannot be deleted; supersede them", node_id))
            continue
        old, new = before.get("status"), after_nodes[node_id].get("status")
        if old != new and new not in NODE_TRANSITIONS.get(old, set()):
            violations.append(Violation("workflow.status-transition", "/nodes", f"invalid node transition {old} -> {new}", node_id))
    if EFFECT_ORDER.get(current.get("authority", {}).get("risk_ceiling"), -1) > EFFECT_ORDER.get(previous.get("authority", {}).get("risk_ceiling"), -1):
        violations.append(Violation("workflow.authority-expanded", "/authority/risk_ceiling", "state transition cannot silently expand authority"))
    before_writes = set(previous.get("scope", {}).get("allowed_writes", []))
    after_writes = set(current.get("scope", {}).get("allowed_writes", []))
    if not after_writes.issubset(before_writes):
        violations.append(Violation("workflow.authority-expanded", "/scope/allowed_writes", "state transition cannot silently expand write scope"))
    return violations


def validate_event_stream(events: list[dict[str, Any]], schema: dict[str, Any], *, require_contiguous: bool = True) -> list[Violation]:
    violations: list[Violation] = []
    seen_ids: set[str] = set()
    workflow_id: str | None = None
    previous_sequence: int | None = None
    previous_version: int | None = None
    previous_time: datetime | None = None
    for index, event in enumerate(events):
        schema_errors = validate_against_schema(event, schema, parts=(index,), code="workflow.event-schema")
        violations.extend(schema_errors)
        if isinstance(event, dict):
            event_id_value = event.get("event_id") if isinstance(event.get("event_id"), str) else None
            if "workflow_id" not in event or "state_version" not in event:
                violations.append(Violation("workflow.event-shape", pointer((index,)), "durable events require workflow_id and state_version", event_id_value))
        if schema_errors or not isinstance(event, dict):
            continue
        event_id = event["event_id"]
        if event_id in seen_ids:
            violations.append(Violation("workflow.event-duplicate", pointer((index, "event_id")), "event_id must be append-only unique", event_id))
        seen_ids.add(event_id)
        event_type = event["type"]
        if workflow_id is None:
            workflow_id = event["workflow_id"]
        elif event["workflow_id"] != workflow_id:
            violations.append(Violation("workflow.event-workflow", pointer((index, "workflow_id")), "one event stream cannot mix workflow IDs", event_id))
        if previous_version is not None and event["state_version"] < previous_version:
            violations.append(Violation("workflow.event-version", pointer((index, "state_version")), "event state_version cannot move backwards", event_id))
        previous_version = event["state_version"]
        if require_contiguous and previous_sequence is None and event["sequence"] != 1:
            violations.append(Violation("workflow.event-order", pointer((index, "sequence")), "complete event stream must start at sequence 1", event_id))
        if require_contiguous and previous_sequence is not None and event["sequence"] != previous_sequence + 1:
            violations.append(Violation("workflow.event-order", pointer((index, "sequence")), "event sequence must be contiguous and increasing", event_id))
        observed_time = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        if previous_time is not None and observed_time < previous_time:
            violations.append(Violation("workflow.event-order", pointer((index, "timestamp")), "event timestamps cannot move backwards", event_id))
        previous_sequence, previous_time = event["sequence"], observed_time

        actor_kind = event["actor"]["kind"]
        if actor_kind == "worker" and event_type not in WORKER_EVENT_TYPES:
            violations.append(Violation("workflow.actor-forbidden", pointer((index, "type")), f"worker cannot submit {event_type}", event_id))
        if actor_kind == "reviewer" and event_type not in REVIEWER_EVENT_TYPES:
            violations.append(Violation("workflow.actor-forbidden", pointer((index, "type")), f"reviewer cannot submit {event_type}", event_id))
        if actor_kind == "tool" and event_type not in TOOL_EVENT_TYPES:
            violations.append(Violation("workflow.actor-forbidden", pointer((index, "type")), f"tool cannot submit {event_type}", event_id))
        if event_type in CONTROLLER_ONLY_EVENT_TYPES and actor_kind != "controller":
            violations.append(Violation("workflow.actor-forbidden", pointer((index, "type")), f"only controller may submit {event_type}", event_id))
        if event_type in NODE_EVENT_TYPES and not event.get("node_id"):
            violations.append(Violation("workflow.event-shape", pointer((index, "node_id")), f"{event_type} requires node_id", event_id))
        if event_type in RUN_EVENT_TYPES and not event.get("run_id"):
            violations.append(Violation("workflow.event-shape", pointer((index, "run_id")), f"{event_type} requires run_id", event_id))
        payload = event.get("payload", {})
        if event_type == "plan_change_proposed" and not payload.get("plan_change_ref"):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "plan_change_ref")), "plan_change_proposed requires a controlled proposal pointer", event_id))
        if event_type in {"approval_granted", "approval_revoked"} and not payload.get("approval_ref"):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "approval_ref")), f"{event_type} requires approval_ref", event_id))
        if event_type in {"lock_acquired", "lock_released"} and not payload.get("resource"):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "resource")), f"{event_type} requires resource", event_id))
        if event_type == "lock_acquired" and not payload.get("lease_expires_at"):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "lease_expires_at")), "lock_acquired requires lease_expires_at", event_id))
        if event_type == "artifact_observed" and not payload.get("artifact_refs"):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "artifact_refs")), "artifact_observed requires at least one artifact pointer", event_id))
        if event_type == "node_failed" and not payload.get("failure_ref"):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "failure_ref")), "node_failed requires failure_ref", event_id))
        if contains_secret_like(event):
            violations.append(Violation("workflow.sensitive-unclassified", pointer((index, "payload")), "events cannot contain raw credential-shaped values; store a controlled pointer", event_id))
    return violations


def _load_or_violation(path: Path, code: str) -> tuple[Any | None, list[Violation]]:
    try:
        return load_json(path), []
    except InputError as exc:
        return None, [Violation(code, "", str(exc))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_STATE_SCHEMA)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--event-schema", type=Path, default=DEFAULT_EVENT_SCHEMA)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--current-revision")
    parser.add_argument("--current-scope-binding-id")
    parser.add_argument("--current-plan-hash")
    args = parser.parse_args(argv)

    state, violations = _load_or_violation(args.state, "workflow.schema")
    schema, schema_violations = _load_or_violation(args.schema, "workflow.schema")
    violations.extend(schema_violations)
    if state is not None and schema is not None:
        violations.extend(validate_state(state, schema, current_revision=args.current_revision, current_scope_binding_id=args.current_scope_binding_id, current_plan_hash=args.current_plan_hash))
    if args.previous is not None and state is not None:
        previous, errors = _load_or_violation(args.previous, "workflow.schema")
        violations.extend(errors)
        if previous is not None:
            violations.extend(validate_transition(previous, state))
    if args.events is not None:
        try:
            events, event_schema = load_json_lines(args.events), load_json(args.event_schema)
            violations.extend(validate_event_stream(events, event_schema))
        except InputError as exc:
            violations.append(Violation("workflow.event-schema", "", str(exc)))

    result = {"ok": not violations, "violations": [item.as_dict() for item in violations]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
