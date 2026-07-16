#!/usr/bin/env python3
"""Validate SQW workflow state, event streams, and canonical transitions."""

from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
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
WORKER_EVENT_TYPES = {"reference_loaded", "node_output_committed", "node_failed", "artifact_observed", "plan_change_proposed", "candidate_created", "counterexample_observed"}
REVIEWER_EVENT_TYPES = {"review_submitted", "artifact_observed", "verifier_qualified", "verifier_rejected", "counterexample_observed", "signoff_completed"}
TOOL_EVENT_TYPES = {"artifact_observed", "baseline_qualified", "baseline_rejected", "verifier_qualified", "verifier_rejected", "candidate_created", "candidate_evaluated", "counterexample_observed", "signoff_completed"}
ADMISSION_EVENT_TYPES = {"closure_admission_started", "closure_admission_completed"}
CONTROLLER_ONLY_EVENT_TYPES = {
    "baseline_qualified", "verifier_bundle_frozen", "verifier_qualified", "candidate_created",
    "candidate_evaluated", "candidate_pruned", "candidate_promoted", "counterexample_observed",
    "budget_consumed", "signoff_started", "signoff_completed", "contract_superseded",
    "terminal_certificate_emitted", "source_drift_detected", "workflow_closed",
}
NODE_EVENT_TYPES = {"node_refined", "node_started", "node_output_committed", "node_completed", "node_failed"}
RUN_EVENT_TYPES = {"node_started", "node_output_committed", "node_completed", "node_failed"}
WORKFLOW_TRANSITIONS = {
    "open": {"active", "aborted"},
    "active": {"blocked", "closing", "aborted"},
    "blocked": {"active", "aborted"},
    "closing": {"active", "blocked", "closed", "aborted"},
    "closed": set(),
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
CLOSURE_PHASE_TRANSITIONS = {
    "BASELINING": {"VERIFIER_QUALIFYING", "TERMINAL"},
    "VERIFIER_QUALIFYING": {"SEARCHING", "BASELINING", "TERMINAL"},
    "SEARCHING": {"SIGNING_OFF", "BASELINING", "TERMINAL"},
    "SIGNING_OFF": {"SEARCHING", "BASELINING", "TERMINAL"},
    "TERMINAL": set(),
}


def _objects(state: dict[str, Any]) -> Iterable[tuple[str, int, dict[str, Any]]]:
    for collection in ("global_invariants", "nodes", "verifiers", "edges", "locks", "artifacts", "recent_failures"):
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
    closure = state.get("closure", {})
    for field in ("required_verifiers", "evidence_refs"):
        for index, ref in enumerate(closure.get(field, [])):
            yield ref, pointer(("closure", field, index)), None


def _validate_closure_run(state: dict[str, Any], run: dict[str, Any]) -> list[Violation]:
    violations: list[Violation] = []
    phase = run.get("phase")
    if run.get("policy_bundle_hash") != state.get("policy_bundle_hash"):
        violations.append(Violation("workflow.closure-policy", "/closure_run/policy_bundle_hash", "closure run policy hash differs from immutable workflow policy"))
    budget = run.get("budget", {})
    if not isinstance(budget, dict):
        budget = {}
    for used, limit in (
        ("iterations_used", "iterations_limit"),
        ("candidate_evaluations_used", "candidate_evaluations_limit"),
        ("review_rounds_used", "review_rounds_limit"),
    ):
        if isinstance(budget.get(used), int) and isinstance(budget.get(limit), int) and budget[used] > budget[limit]:
            violations.append(Violation("workflow.closure-budget", f"/closure_run/budget/{used}", f"{used} exceeds {limit}"))

    required_by_phase = {
        "BASELINING": {"contract_ref"},
        "VERIFIER_QUALIFYING": {"contract_ref", "baseline_ref"},
        "SEARCHING": {"contract_ref", "baseline_ref", "verifier_bundle_ref"},
        "SIGNING_OFF": {"contract_ref", "baseline_ref", "verifier_bundle_ref", "incumbent_candidate_ref"},
        "TERMINAL": {"terminal_certificate_ref"},
    }
    future_forbidden = {
        "BASELINING": {"baseline_ref", "verifier_bundle_ref", "incumbent_candidate_ref", "signoff_result_ref"},
        "VERIFIER_QUALIFYING": {"incumbent_candidate_ref", "signoff_result_ref"},
        "SEARCHING": set(),
        "SIGNING_OFF": set(),
        "TERMINAL": set(),
    }
    for field in required_by_phase.get(phase, set()):
        value = run.get(field)
        if value is None or value == "":
            violations.append(Violation("workflow.closure-phase", f"/closure_run/{field}", f"{phase} requires {field}"))
    for field in future_forbidden.get(phase, set()):
        if field in run:
            violations.append(Violation("workflow.closure-phase", f"/closure_run/{field}", f"{phase} cannot bind future {field}"))
    if phase not in {"SEARCHING", "SIGNING_OFF", "TERMINAL"} and (run.get("active_candidate_refs") or run.get("active_counterexample_refs")):
        violations.append(Violation("workflow.closure-phase", "/closure_run/active_candidate_refs", f"{phase} cannot carry active candidate/counterexample refs"))
    terminal_status = run.get("terminal_status")
    terminal_ref = run.get("terminal_certificate_ref")
    if phase == "TERMINAL":
        if terminal_status is None or terminal_ref is None:
            violations.append(Violation("workflow.closure-phase", "/closure_run/terminal_status", "TERMINAL requires status and certificate"))
        if terminal_status == "CLOSED":
            for field in ("contract_ref", "baseline_ref", "verifier_bundle_ref", "incumbent_candidate_ref", "signoff_result_ref"):
                if run.get(field) is None:
                    violations.append(Violation("workflow.closure-phase", f"/closure_run/{field}", f"CLOSED requires {field}"))
    elif terminal_status is not None or terminal_ref is not None:
        violations.append(Violation("workflow.closure-phase", "/closure_run/terminal_status", "non-terminal phase cannot carry terminal state"))
    contract = run.get("contract_ref")
    verifier = run.get("verifier_bundle_ref")
    if isinstance(contract, dict) and isinstance(verifier, dict) and contract.get("epoch") != verifier.get("epoch"):
        violations.append(Violation("workflow.closure-epoch", "/closure_run/verifier_bundle_ref/epoch", "verifier and contract epochs differ"))
    return violations


def validate_state(
    state: Any,
    schema: dict[str, Any],
    *,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
    current_plan_hash: str | None = None,
) -> list[Violation]:
    violations = validate_against_schema(state, schema, code="workflow.schema")
    schema_failed = bool(violations)
    if not isinstance(state, dict):
        return violations

    execution_policy = state.get("execution_policy")
    closure_run = state.get("closure_run")
    if execution_policy == "standard" and closure_run is not None:
        violations.append(Violation("workflow.closure-policy", "/closure_run", "standard workflow must not carry closure_run"))
    if execution_policy == "autonomous_closure":
        if state.get("mode") not in {"M2_SPARSE", "M3_FULL"}:
            violations.append(Violation("workflow.closure-mode", "/mode", "autonomous closure requires M2 or M3"))
        if state.get("request_mode") not in {"change", "recovery"}:
            violations.append(Violation("workflow.closure-mode", "/request_mode", "autonomous closure requires change or recovery request mode"))
        if not isinstance(closure_run, dict):
            violations.append(Violation("workflow.closure-policy", "/closure_run", "autonomous closure requires closure_run"))
        else:
            violations.extend(_validate_closure_run(state, closure_run))
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

    plan_id = state.get("plan_ref", {}).get("plan_id")
    plan_prefix = f"plan:{plan_id}#" if isinstance(plan_id, str) else None
    for node_index, node in enumerate(state.get("nodes", [])):
        candidate_refs = [("plan_node_ref", node.get("plan_node_ref"))]
        candidate_refs.extend(("input_refs", ref) for ref in node.get("input_refs", []) if str(ref).startswith("plan:"))
        for field, ref in candidate_refs:
            if isinstance(ref, str) and ref.startswith("plan:") and (plan_prefix is None or not ref.startswith(plan_prefix)):
                violations.append(Violation("workflow.plan-ref-mismatch", pointer(("nodes", node_index, field)), f"plan reference {ref} does not match workflow plan_ref namespace {plan_prefix}", node.get("id")))

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

    locks_by_resource: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for lock in state.get("locks", []):
        locks_by_resource[lock.get("resource")].append(lock)
        if lock.get("state_version", 0) > state["state_version"]:
            violations.append(Violation("workflow.lock-conflict", "/locks", "lock references a future state version", lock.get("id")))
    for resource, locks in locks_by_resource.items():
        owners = {item.get("owner") for item in locks}
        if len(locks) > 1 and len(owners) > 1:
            violations.append(Violation("workflow.lock-conflict", "/locks", f"resource has concurrent owners: {resource} -> {sorted(owners)}"))

    for collection in ("global_invariants", "nodes", "artifacts", "recent_failures"):
        for index, item in enumerate(state.get(collection, [])):
            if isinstance(item, dict) and contains_secret_like(item):
                violations.append(Violation("workflow.sensitive-unclassified", pointer((collection, index, "sensitive")), "raw credential-shaped values are forbidden even when classified; store only a controlled pointer", item.get("id")))
    for index, verifier in enumerate(state.get("verifiers", [])):
        if contains_secret_like(verifier):
            violations.append(Violation("workflow.sensitive-unclassified", pointer(("verifiers", index)), "verifier cannot contain raw credential-shaped values", verifier.get("id")))

    if state.get("mode") == "M1_TRACE" and any(state.get(field) for field in ("nodes", "edges", "frontier", "locks")):
        violations.append(Violation("workflow.m1-graph", "/mode", "M1 trace cannot carry a predeclared durable execution graph"))
    if state.get("state_hash") and state["state_hash"] != canonical_hash(state):
        violations.append(Violation("workflow.state-hash", "/state_hash", "state_hash does not match canonical state"))
    if current_revision and state["source"]["observed_revision"] != current_revision:
        violations.append(Violation("workflow.source-stale", "/source/observed_revision", "observed source revision differs from current revision"))
    if current_scope_hash and state["source"]["scope_hash"] != current_scope_hash:
        violations.append(Violation("workflow.source-stale", "/source/scope_hash", "scope hash differs from current scope"))
    if current_plan_hash and state.get("plan_ref", {}).get("content_hash") != current_plan_hash:
        violations.append(Violation("workflow.plan-stale", "/plan_ref/content_hash", "workflow references a stale plan hash"))

    closure = state.get("closure", {})
    if closure.get("status") == "closed" or state.get("status") == "closed":
        missing_verifiers = [ref for ref in closure.get("required_verifiers", []) if verifiers.get(ref, {}).get("status") != "passed"]
        stale_evidence = [ref for ref in closure.get("evidence_refs", []) if artifacts.get(ref, {}).get("freshness") != "fresh"]
        unfinished = [node.get("id") for node in state.get("nodes", []) if node.get("status") not in SATISFIED_NODE_STATUSES]
        if missing_verifiers or stale_evidence or unfinished or state.get("pending_background") or state.get("locks") or closure.get("known_gaps"):
            violations.append(Violation("workflow.closure-premature", "/closure/status", f"closure incomplete: verifiers={missing_verifiers}, evidence={stale_evidence}, nodes={unfinished}, background={state.get('pending_background')}, locks={len(state.get('locks', []))}"))
    return violations


def validate_transition(previous: dict[str, Any], current: dict[str, Any], *, actor_kind: str = "controller") -> list[Violation]:
    violations: list[Violation] = []
    if previous != current and actor_kind != "controller":
        violations.append(Violation("workflow.controller-only", "", "only controller may mutate canonical workflow state"))
    if previous.get("workflow_id") != current.get("workflow_id"):
        violations.append(Violation("workflow.identity-change", "/workflow_id", "workflow_id is immutable"))
    immutable_fields = ("mode", "request_mode", "execution_policy", "policy_bundle_hash")
    if any(previous.get(field) != current.get(field) for field in immutable_fields):
        violations.append(Violation("workflow.identity-change", "/mode", "mode, request mode, execution policy, and policy bundle hash are immutable after open"))
    if current.get("state_version") != previous.get("state_version", 0) + 1:
        violations.append(Violation("workflow.state-version", "/state_version", "transition must increment state_version by exactly one"))
    before_status, after_status = previous.get("status"), current.get("status")
    if before_status != after_status and after_status not in WORKFLOW_TRANSITIONS.get(before_status, set()):
        violations.append(Violation("workflow.status-transition", "/status", f"invalid workflow transition {before_status} -> {after_status}"))

    before_nodes = {item.get("id"): item for item in previous.get("nodes", [])}
    after_nodes = {item.get("id"): item for item in current.get("nodes", [])}
    previous_run = previous.get("closure_run") if isinstance(previous.get("closure_run"), dict) else {}
    current_run = current.get("closure_run") if isinstance(current.get("closure_run"), dict) else {}
    previous_contract = previous_run.get("contract_ref") if isinstance(previous_run.get("contract_ref"), dict) else {}
    current_contract = current_run.get("contract_ref") if isinstance(current_run.get("contract_ref"), dict) else {}
    contract_superseded = (
        isinstance(previous_contract.get("epoch"), int)
        and isinstance(current_contract.get("epoch"), int)
        and current_contract["epoch"] > previous_contract["epoch"]
        and current_contract != previous_contract
        and current_run.get("handoff_ref") != previous_run.get("handoff_ref")
        and current.get("plan_ref") != previous.get("plan_ref")
        and current_run.get("phase") == "BASELINING"
    )
    for node_id, before in before_nodes.items():
        if node_id not in after_nodes:
            if not contract_superseded:
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
    before_run, after_run = previous.get("closure_run"), current.get("closure_run")
    if isinstance(before_run, dict) and isinstance(after_run, dict):
        before_phase, after_phase = before_run.get("phase"), after_run.get("phase")
        if before_phase != after_phase and after_phase not in CLOSURE_PHASE_TRANSITIONS.get(before_phase, set()):
            violations.append(Violation("workflow.closure-transition", "/closure_run/phase", f"invalid closure transition {before_phase} -> {after_phase}"))
        before_budget, after_budget = before_run.get("budget", {}), after_run.get("budget", {})
        if isinstance(before_budget, dict) and isinstance(after_budget, dict):
            for field in ("iterations_used", "candidate_evaluations_used", "review_rounds_used"):
                if isinstance(before_budget.get(field), int) and isinstance(after_budget.get(field), int) and after_budget[field] < before_budget[field]:
                    violations.append(Violation("workflow.closure-budget-transition", f"/closure_run/budget/{field}", f"{field} cannot decrease"))
            for field in ("iterations_limit", "candidate_evaluations_limit", "review_rounds_limit"):
                if before_budget.get(field) != after_budget.get(field):
                    violations.append(Violation("workflow.closure-budget-transition", f"/closure_run/budget/{field}", f"{field} is immutable"))
        for field in ("contract_ref", "verifier_bundle_ref"):
            before_ref, after_ref = before_run.get(field), after_run.get(field)
            if isinstance(before_ref, dict) and isinstance(after_ref, dict):
                if isinstance(before_ref.get("epoch"), int) and isinstance(after_ref.get("epoch"), int) and after_ref["epoch"] < before_ref["epoch"]:
                    violations.append(Violation("workflow.closure-epoch-transition", f"/closure_run/{field}/epoch", f"{field} epoch cannot decrease"))
    return violations


def validate_event_stream(events: list[dict[str, Any]], schema: dict[str, Any], *, require_contiguous: bool = True) -> list[Violation]:
    violations: list[Violation] = []
    seen_ids: set[str] = set()
    workflow_id: str | None = None
    previous_sequence: int | None = None
    previous_version: int | None = None
    previous_time: datetime | None = None
    durable_seen = False
    for index, event in enumerate(events):
        schema_errors = validate_against_schema(event, schema, parts=(index,), code="workflow.event-schema")
        violations.extend(schema_errors)
        if isinstance(event, dict):
            event_type_value = event.get("type")
            event_id_value = event.get("event_id") if isinstance(event.get("event_id"), str) else None
            if event_type_value in ADMISSION_EVENT_TYPES and ("workflow_id" in event or "state_version" in event):
                violations.append(Violation("workflow.admission-event-shape", pointer((index,)), "pre-workflow admission events must omit workflow_id and state_version", event_id_value))
            elif isinstance(event_type_value, str) and event_type_value not in ADMISSION_EVENT_TYPES and ("workflow_id" not in event or "state_version" not in event):
                violations.append(Violation("workflow.event-shape", pointer((index,)), "durable events require workflow_id and state_version", event_id_value))
        if schema_errors or not isinstance(event, dict):
            continue
        event_id = event["event_id"]
        if event_id in seen_ids:
            violations.append(Violation("workflow.event-duplicate", pointer((index, "event_id")), "event_id must be append-only unique", event_id))
        seen_ids.add(event_id)
        event_type = event["type"]
        is_admission = event_type in ADMISSION_EVENT_TYPES
        if is_admission:
            if "workflow_id" in event or "state_version" in event:
                violations.append(Violation("workflow.admission-event-shape", pointer((index,)), "pre-workflow admission events must omit workflow_id and state_version", event_id))
            if durable_seen:
                violations.append(Violation("workflow.event-order", pointer((index, "type")), "admission events must precede durable workflow events", event_id))
        else:
            durable_seen = True
            if "workflow_id" not in event or "state_version" not in event:
                violations.append(Violation("workflow.event-shape", pointer((index,)), "durable events require workflow_id and state_version", event_id))
            else:
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
        if event_type == "budget_consumed" and not isinstance(payload.get("budget_delta"), dict):
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "budget_delta")), "budget_consumed requires budget_delta", event_id))
        if "next_phase" in payload and event_type != "signoff_completed":
            violations.append(Violation("workflow.event-shape", pointer((index, "payload", "next_phase")), "next_phase is only valid on signoff_completed", event_id))
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
    parser.add_argument("--current-scope-hash")
    parser.add_argument("--current-plan-hash")
    args = parser.parse_args(argv)

    state, violations = _load_or_violation(args.state, "workflow.schema")
    schema, schema_violations = _load_or_violation(args.schema, "workflow.schema")
    violations.extend(schema_violations)
    if state is not None and schema is not None:
        violations.extend(validate_state(state, schema, current_revision=args.current_revision, current_scope_hash=args.current_scope_hash, current_plan_hash=args.current_plan_hash))
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
