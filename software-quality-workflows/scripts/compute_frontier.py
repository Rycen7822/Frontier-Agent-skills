#!/usr/bin/env python3
"""Compute the deterministic ready frontier and conflict-free batches."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any

from _closure import FAILURE_PHASES, compute_terminal_status, eligible_events
from _workflow_state import InputError, load_json, patterns_may_overlap


EFFECT_ORDER = {"none": 0, "local_ephemeral": 1, "local_reversible": 2, "external_reversible": 3, "external_non_idempotent": 4, "destructive": 5}
SATISFIED = {"done", "skipped", "superseded"}
CANDIDATE = {"pending", "ready", "blocked", "failed"}
EXTERNAL = {"external_reversible", "external_non_idempotent", "destructive"}
_CLOSURE_PHASE_REQUIREMENTS = {
    "BASELINING": ("contract_ref",),
    "VERIFIER_QUALIFYING": ("contract_ref", "baseline_ref"),
    "SEARCHING": ("contract_ref", "baseline_ref", "verifier_bundle_ref"),
    "SIGNING_OFF": ("contract_ref", "baseline_ref", "verifier_bundle_ref", "incumbent_candidate_ref"),
    "TERMINAL": ("terminal_status", "terminal_certificate_ref"),
}
_CLOSURE_TASK_ROLES = {
    "BASELINING": ("test_analyst",),
    "VERIFIER_QUALIFYING": ("test_analyst",),
    "SEARCHING": ("candidate_worker", "test_analyst"),
    "SIGNING_OFF": ("reviewer",),
    "TERMINAL": (),
}
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_REF = re.compile(r"^artifact:[a-z][a-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TERMINAL_STATUSES = set(FAILURE_PHASES) | {"CLOSED"}


def _closure_binding_ready(run: dict[str, Any], field: str) -> bool:
    value = run.get(field)
    if field == "terminal_status":
        return value in _TERMINAL_STATUSES
    if field in {"terminal_certificate_ref", "incumbent_candidate_ref"}:
        return bool(_ARTIFACT_REF.fullmatch(str(value or "")))
    if not isinstance(value, dict):
        return False
    expected = {"artifact_ref", "content_hash", "epoch"} if field in {"contract_ref", "verifier_bundle_ref"} else {"artifact_ref", "content_hash"}
    if set(value) != expected or not _ARTIFACT_REF.fullmatch(str(value.get("artifact_ref", ""))) or not _HASH.fullmatch(str(value.get("content_hash", ""))):
        return False
    return field not in {"contract_ref", "verifier_bundle_ref"} or (isinstance(value.get("epoch"), int) and not isinstance(value.get("epoch"), bool) and value["epoch"] >= 1)


def _time(value: str | None) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)


def _conflicts(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if set(left.get("resource_set", [])) & set(right.get("resource_set", [])):
        return True
    if set(left.get("effect_set", [])) & set(right.get("effect_set", [])):
        return True
    path_pairs = (
        (left.get("write_set", []), right.get("write_set", [])),
        (left.get("write_set", []), right.get("read_set", [])),
        (left.get("read_set", []), right.get("write_set", [])),
    )
    return any(patterns_may_overlap(a, b) for left_set, right_set in path_pairs for a in left_set for b in right_set)


def _invariant_applies(invariant: dict[str, Any], node: dict[str, Any]) -> bool:
    locality = invariant.get("locality")
    targets = set(invariant.get("targets", []))
    if locality == "global":
        return True
    if locality == "node_set":
        return node.get("id") in targets
    if locality == "resource_set":
        return bool(targets & set(node.get("resource_set", [])))
    return True


def compute_frontier(
    state: dict[str, Any],
    *,
    now_value: str | None = None,
    actor: str | None = None,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
    current_plan_hash: str | None = None,
) -> dict[str, Any]:
    now = _time(now_value)
    nodes = {item["id"]: item for item in state.get("nodes", [])}
    artifacts = {item["id"]: item for item in state.get("artifacts", [])}
    invariants = {item["id"]: item for item in state.get("global_invariants", [])}
    approvals = {item["id"]: item for item in state.get("authority", {}).get("approvals", [])}
    ceiling = EFFECT_ORDER.get(state.get("authority", {}).get("risk_ceiling"), -1)
    blocked: dict[str, list[str]] = {}
    ready: list[str] = []
    warnings: list[str] = []

    for node_id in sorted(nodes):
        node = nodes[node_id]
        if node.get("status") not in CANDIDATE:
            continue
        reasons: list[str] = []
        for dependency in node.get("depends_on", []):
            if nodes.get(dependency, {}).get("status") not in SATISFIED:
                reasons.append(f"dependency:{dependency}")
        for ref in node.get("input_refs", []):
            if str(ref).startswith("EV-"):
                artifact = artifacts.get(ref)
                if artifact is None:
                    reasons.append(f"missing:{ref}")
                elif artifact.get("freshness") != "fresh":
                    reasons.append(f"stale:{ref}")
                else:
                    contracts = {item.get("ref"): item.get("schema_id") for item in node.get("input_contracts", [])}
                    if contracts.get(ref) != artifact.get("schema_id"):
                        reasons.append(f"schema-mismatch:{ref}")
            elif str(ref).startswith("I-") and _invariant_applies(invariants.get(ref, {}), node) and invariants.get(ref, {}).get("status") != "current":
                reasons.append(f"invariant:{ref}:{invariants.get(ref, {}).get('status', 'missing')}")
        for invariant_id, invariant in invariants.items():
            if _invariant_applies(invariant, node) and invariant.get("status") in {"changed", "unknown", "invalidated"} and f"invariant:{invariant_id}:{invariant['status']}" not in reasons:
                reasons.append(f"invariant:{invariant_id}:{invariant['status']}")

        effect = node.get("side_effect")
        if EFFECT_ORDER.get(effect, 99) > ceiling:
            reasons.append(f"authority:{effect}")
        if effect in EXTERNAL and state.get("authority", {}).get("external_writes") != "approved":
            reasons.append("authority:external-writes")
        if effect == "destructive" and state.get("authority", {}).get("destructive_actions") != "approved":
            reasons.append("authority:destructive")
        if effect in EXTERNAL:
            required = node.get("required_approvals", [])
            missing = [ref for ref in required if approvals.get(ref, {}).get("status") != "granted"]
            if not required:
                reasons.append("approval:required")
            reasons.extend(f"approval:{ref}" for ref in missing)

        retry = node.get("attempt_policy", {})
        if retry.get("attempts_used", 0) >= retry.get("max_attempts", 0):
            if node.get("status") == "failed" or retry.get("max_attempts", 0) == 0:
                reasons.append("retry:exhausted")
        if effect in {"external_non_idempotent", "destructive"} and retry.get("max_attempts", 0) > 1 and retry.get("idempotency") not in {"idempotency_key", "manual_reconciliation"}:
            reasons.append("retry:unsafe")

        resources = set(node.get("resource_set", []))
        for lock in state.get("locks", []):
            if lock.get("resource") not in resources:
                continue
            expires = _time(lock.get("lease_expires_at"))
            if expires <= now:
                reasons.append(f"expired-lock:{lock.get('id')}")
            elif actor is None or lock.get("owner") != actor:
                reasons.append(f"resource-lock:{lock.get('resource')}")

        if current_revision and state.get("source", {}).get("observed_revision") != current_revision:
            reasons.append("source:revision-drift")
        if current_scope_hash and state.get("source", {}).get("scope_hash") != current_scope_hash:
            reasons.append("source:scope-drift")
        if current_plan_hash and state.get("plan_ref", {}).get("content_hash") != current_plan_hash:
            reasons.append("plan:hash-drift")

        if reasons:
            blocked[node_id] = sorted(set(reasons))
        else:
            ready.append(node_id)

    batches: list[list[str]] = []
    for node_id in ready:
        placed = False
        for batch in batches:
            if all(not _conflicts(nodes[node_id], nodes[other]) for other in batch):
                batch.append(node_id)
                placed = True
                break
        if not placed:
            batches.append([node_id])
    for left_index, left_id in enumerate(ready):
        for right_id in ready[left_index + 1 :]:
            if _conflicts(nodes[left_id], nodes[right_id]):
                warnings.append(f"parallel-conflict:{left_id}:{right_id}")

    result = {
        "workflow_id": state.get("workflow_id"),
        "state_version": state.get("state_version"),
        "ready": ready,
        "blocked": blocked,
        "parallel_batches": batches,
        "warnings": warnings,
    }
    run = state.get("closure_run")
    if state.get("execution_policy") == "autonomous_closure" and isinstance(run, dict):
        phase = run.get("phase")
        requirements = _CLOSURE_PHASE_REQUIREMENTS.get(str(phase), ())
        missing = sorted(f"missing:{field}" for field in requirements if not _closure_binding_ready(run, field))
        if str(phase) not in _CLOSURE_PHASE_REQUIREMENTS:
            missing.append("phase:unknown")
        if run.get("policy_bundle_hash") != state.get("policy_bundle_hash"):
            missing.append("policy:bundle-hash-drift")
        if current_revision and state.get("source", {}).get("observed_revision") != current_revision:
            missing.append("source:revision-drift")
        if current_scope_hash and state.get("source", {}).get("scope_hash") != current_scope_hash:
            missing.append("source:scope-drift")
        if current_plan_hash and state.get("plan_ref", {}).get("content_hash") != current_plan_hash:
            missing.append("plan:hash-drift")
        missing = sorted(set(missing))
        controller_events = sorted(eligible_events(state))
        terminal_pending = compute_terminal_status(state) is not None
        suppressed = list(result["ready"])
        result["ready"] = []
        result["parallel_batches"] = []
        if suppressed:
            result["warnings"].append("standard-frontier-suppressed-by-autonomous-closure")
        result["closure"] = {
            "phase": phase,
            "phase_ready": not missing,
            "blocked_reasons": missing,
            "transition_authority": "controller",
            "eligible_controller_events": controller_events,
            "worker_transition_events": [],
            "eligible_task_roles": list(_CLOSURE_TASK_ROLES.get(str(phase), ())) if not missing and not terminal_pending else [],
            "suppressed_standard_ready": suppressed,
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--actor")
    parser.add_argument("--current-revision")
    parser.add_argument("--current-scope-hash")
    parser.add_argument("--current-plan-hash")
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        result = compute_frontier(state, now_value=args.now, actor=args.actor, current_revision=args.current_revision, current_scope_hash=args.current_scope_hash, current_plan_hash=args.current_plan_hash)
    except (InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
