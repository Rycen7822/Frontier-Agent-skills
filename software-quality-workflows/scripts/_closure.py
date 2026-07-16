#!/usr/bin/env python3
"""Pure deterministic state, ranking, and invalidation functions for SQW closure."""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from _workflow_state import canonical_artifact_hash, canonical_hash
from assess_closure_admission import assess_admission


class ClosureError(ValueError):
    pass


PHASE_EVENTS = {
    "BASELINING": {"baseline_qualified", "contract_superseded", "terminal_certificate_emitted", "source_drift_detected"},
    "VERIFIER_QUALIFYING": {"verifier_bundle_frozen", "verifier_qualified", "contract_superseded", "terminal_certificate_emitted", "source_drift_detected"},
    "SEARCHING": {"candidate_created", "candidate_evaluated", "candidate_pruned", "candidate_promoted", "counterexample_observed", "budget_consumed", "contract_superseded", "terminal_certificate_emitted", "source_drift_detected"},
    "SIGNING_OFF": {"signoff_started", "signoff_completed", "counterexample_observed", "budget_consumed", "contract_superseded", "terminal_certificate_emitted", "source_drift_detected"},
    "TERMINAL": {"workflow_closed"},
}
CONTROLLER_ONLY_EVENTS = set().union(*PHASE_EVENTS.values())
FAILURE_PHASES = {
    "SPEC_UNDERDETERMINED": set(),
    "SPEC_UNSAT": {"SEARCHING", "SIGNING_OFF"},
    "BASELINE_UNSTABLE": {"BASELINING"},
    "VERIFIER_UNQUALIFIED": {"VERIFIER_QUALIFYING"},
    "NON_CONVERGED": {"SEARCHING", "SIGNING_OFF"},
    "BUDGET_EXHAUSTED": {"SEARCHING", "SIGNING_OFF"},
    "AUTHORITY_BLOCKED": set(PHASE_EVENTS) - {"TERMINAL"},
    "ENVIRONMENT_UNAVAILABLE": set(PHASE_EVENTS) - {"TERMINAL"},
    "WORKFLOW_INVALID": set(PHASE_EVENTS) - {"TERMINAL"},
    "ABORTED_BY_SOURCE_DRIFT": set(PHASE_EVENTS) - {"TERMINAL"},
}


def admit(facts: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(facts)
    if policy:
        for key in ("framework_tax",):
            if key in policy:
                merged[key] = policy[key]
    return assess_admission(merged)


def _at_hard_limit(budget: dict[str, Any], used: str, limit: str) -> bool:
    observed, ceiling = budget.get(used), budget.get(limit)
    return all(isinstance(value, int) and not isinstance(value, bool) for value in (observed, ceiling)) and observed >= ceiling


def compute_terminal_status(state: dict[str, Any]) -> str | None:
    run = state.get("closure_run")
    if not isinstance(run, dict):
        return None
    if run.get("phase") == "TERMINAL":
        return run.get("terminal_status") if isinstance(run.get("terminal_status"), str) else None
    budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
    if _at_hard_limit(budget, "iterations_used", "iterations_limit"):
        return "BUDGET_EXHAUSTED"
    phase = run.get("phase")
    if _at_hard_limit(budget, "candidate_evaluations_used", "candidate_evaluations_limit"):
        can_finish_evaluated_candidate = phase == "SEARCHING" and bool(run.get("active_candidate_refs"))
        if not can_finish_evaluated_candidate and phase != "SIGNING_OFF":
            return "BUDGET_EXHAUSTED"
    if _at_hard_limit(budget, "review_rounds_used", "review_rounds_limit") and phase != "SIGNING_OFF":
        return "BUDGET_EXHAUSTED"
    return None


def eligible_events(state: dict[str, Any]) -> set[str]:
    run = state.get("closure_run")
    if state.get("execution_policy") != "autonomous_closure" or not isinstance(run, dict):
        return set()
    phase = run.get("phase")
    if phase != "TERMINAL" and compute_terminal_status(state) == "BUDGET_EXHAUSTED":
        return {"terminal_certificate_emitted", "source_drift_detected"}
    events = set(PHASE_EVENTS.get(phase, set()))
    budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
    if _at_hard_limit(budget, "candidate_evaluations_used", "candidate_evaluations_limit"):
        events -= {"strategy_family_registered", "candidate_created", "candidate_evaluation_started", "candidate_evaluated"}
    if _at_hard_limit(budget, "review_rounds_used", "review_rounds_limit"):
        events.discard("signoff_started")
    return events


def _artifact(event: dict[str, Any], artifacts: dict[str, dict[str, Any]], schema_id: str | None = None) -> tuple[str, dict[str, Any]]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    refs = payload.get("artifact_refs") if isinstance(payload.get("artifact_refs"), list) else []
    resolved = [(ref, artifacts[ref]) for ref in refs if isinstance(ref, str) and ref in artifacts]
    if schema_id is not None:
        resolved = [(ref, artifact) for ref, artifact in resolved if artifact.get("schema_id") == schema_id]
    if len(resolved) != 1:
        qualifier = f" {schema_id}" if schema_id else ""
        raise ClosureError(f"{event.get('type')} requires exactly one resolved{qualifier} artifact_ref")
    return resolved[0]


def _contract_artifact(event: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    refs = payload.get("artifact_refs") if isinstance(payload.get("artifact_refs"), list) else []
    resolved = [
        (ref, artifacts[ref])
        for ref in refs
        if isinstance(ref, str) and ref in artifacts and isinstance(artifacts[ref].get("contract_id"), str)
    ]
    if len(resolved) != 1:
        raise ClosureError(f"{event.get('type')} requires exactly one frozen Closure Contract artifact")
    return resolved[0]


def _supersession_boundary(
    event: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], str, dict[str, Any], str, dict[str, Any], str, dict[str, Any], str, dict[str, Any]]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    refs = payload.get("artifact_refs") if isinstance(payload.get("artifact_refs"), list) else []

    def unique(prefix: str) -> tuple[str, dict[str, Any]]:
        matches = [(ref, artifacts.get(ref)) for ref in refs if isinstance(ref, str) and ref.startswith(prefix)]
        if len(matches) != 1 or not isinstance(matches[0][1], dict):
            raise ClosureError(f"contract_superseded requires exactly one resolved {prefix} artifact")
        return matches[0][0], matches[0][1]

    handoff_ref, handoff = unique("artifact:handoff/")
    admission_ref, admission = unique("artifact:admission/")
    plan_ref, plan = unique("artifact:plan/")
    contract_ref, contract = unique("artifact:contract/")
    authority_ref = contract.get("authority_manifest_ref")
    authority = artifacts.get(authority_ref) if isinstance(authority_ref, str) else None
    if not isinstance(authority_ref, str) or not isinstance(authority, dict):
        raise ClosureError("contract_superseded requires the contract-bound Authority Manifest")
    expected = {
        "closure_admission_ref": admission_ref,
        "closure_admission_hash": canonical_artifact_hash(admission),
        "plan_ref": plan_ref,
        "plan_hash": canonical_artifact_hash(plan),
        "closure_contract_ref": contract_ref,
        "closure_contract_hash": canonical_artifact_hash(contract),
        "authority_manifest_ref": authority_ref,
    }
    if any(handoff.get(field) != value for field, value in expected.items()):
        raise ClosureError("contract_superseded handoff artifact identities do not match")
    if contract.get("closure_admission_ref") != admission_ref or contract.get("closure_admission_hash") != expected["closure_admission_hash"]:
        raise ClosureError("contract_superseded contract does not bind Admission")
    if contract.get("authority_manifest_hash") != canonical_artifact_hash(authority):
        raise ClosureError("contract_superseded contract does not bind Authority Manifest")
    return handoff_ref, handoff, admission_ref, admission, plan_ref, plan, contract_ref, contract, authority_ref, authority


def _semantic_transition_hash(state: dict[str, Any]) -> str:
    value = deepcopy(state)
    value.pop("state_hash", None)
    value.pop("state_version", None)
    value.pop("context_trace_ref", None)
    return canonical_hash(value)


def _set_phase(state: dict[str, Any], phase: str) -> None:
    state["closure_run"]["phase"] = phase


def _terminal(state: dict[str, Any], ref: str, artifact: dict[str, Any], *, source_drift: bool = False) -> None:
    run = state["closure_run"]
    phase = run["phase"]
    payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
    status = payload.get("terminal_status")
    if not isinstance(status, str):
        raise ClosureError("terminal certificate has no typed terminal_status")
    if source_drift and status != "ABORTED_BY_SOURCE_DRIFT":
        raise ClosureError("source_drift_detected requires ABORTED_BY_SOURCE_DRIFT certificate")
    if status == "CLOSED":
        if phase != "SIGNING_OFF" or run.get("incumbent_candidate_ref") is None:
            raise ClosureError("CLOSED requires SIGNING_OFF with an incumbent")
        signoff_ref = payload.get("signoff_result_ref")
        if not isinstance(signoff_ref, str):
            raise ClosureError("CLOSED certificate requires signoff_result_ref")
    else:
        allowed = FAILURE_PHASES.get(status)
        if allowed is None or phase not in allowed:
            raise ClosureError(f"{status} is not terminal from {phase}")
    inferred = compute_terminal_status(state)
    if inferred == "BUDGET_EXHAUSTED" and status != inferred:
        raise ClosureError("budget exhaustion cannot be replaced by another terminal status")
    if status == "BUDGET_EXHAUSTED" and inferred != status:
        raise ClosureError("BUDGET_EXHAUSTED requires an exhausted hard budget")
    _set_phase(state, "TERMINAL")
    run["terminal_status"] = status
    run["terminal_certificate_ref"] = ref
    run["active_candidate_refs"] = []
    run["active_counterexample_refs"] = []


def apply_event(state: dict[str, Any], event: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if event.get("type") not in eligible_events(state):
        raise ClosureError(f"event {event.get('type')} is not eligible in {state.get('closure_run', {}).get('phase')}")
    if event.get("workflow_id") != state.get("workflow_id"):
        raise ClosureError("event workflow_id differs from state")
    if event.get("state_version") != state.get("state_version", 0) + 1:
        raise ClosureError("event state_version must equal current state_version + 1")
    actor_kind = event.get("actor", {}).get("kind") if isinstance(event.get("actor"), dict) else None
    if event.get("type") in CONTROLLER_ONLY_EVENTS and actor_kind != "controller":
        raise ClosureError(f"{event.get('type')} is controller-only")

    result = deepcopy(state)
    run = result["closure_run"]
    event_type = event["type"]
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}

    if event_type == "baseline_qualified":
        ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/baseline-result/1.0")
        if artifact.get("schema_id") != "sqw://closure-artifacts/baseline-result/1.0" or artifact.get("payload", {}).get("status") != "qualified":
            raise ClosureError("baseline_qualified requires a qualified baseline artifact")
        run["baseline_ref"] = {"artifact_ref": ref, "content_hash": artifact["content_hash"]}
        _set_phase(result, "VERIFIER_QUALIFYING")
    elif event_type == "verifier_bundle_frozen":
        ref, artifact = _artifact(event, artifacts)
        if artifact.get("status") not in {"frozen", "qualified"} or artifact.get("closure_epoch") != run.get("contract_ref", {}).get("epoch"):
            raise ClosureError("verifier bundle must be frozen and match contract epoch")
        run["verifier_bundle_ref"] = {"artifact_ref": ref, "content_hash": artifact["content_hash"], "epoch": artifact["closure_epoch"]}
    elif event_type == "verifier_qualified":
        ref, artifact = _artifact(event, artifacts)
        if artifact.get("status") != "qualified" or run.get("verifier_bundle_ref", {}).get("artifact_ref") != ref:
            raise ClosureError("verifier_qualified requires the bound qualified verifier bundle")
        _set_phase(result, "SEARCHING")
    elif event_type == "candidate_created":
        ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/candidate-manifest/1.0")
        if artifact.get("schema_id") != "sqw://closure-artifacts/candidate-manifest/1.0":
            raise ClosureError("candidate_created requires candidate manifest")
        if ref not in run["active_candidate_refs"]:
            run["active_candidate_refs"].append(ref)
    elif event_type == "candidate_evaluated":
        ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/candidate-evaluation/1.0")
        if artifact.get("schema_id") != "sqw://closure-artifacts/candidate-evaluation/1.0":
            raise ClosureError("candidate_evaluated requires candidate evaluation")
        run["budget"]["candidate_evaluations_used"] += 1
    elif event_type == "candidate_pruned":
        ref, _ = _artifact(event, artifacts, "sqw://closure-artifacts/candidate-manifest/1.0")
        run["active_candidate_refs"] = [item for item in run["active_candidate_refs"] if item != ref]
    elif event_type == "candidate_promoted":
        ref = select_promotion(state, event, artifacts)
        run["incumbent_candidate_ref"] = ref
        run["active_candidate_refs"] = []
        run["active_counterexample_refs"] = []
        _set_phase(result, "SIGNING_OFF")
    elif event_type == "counterexample_observed":
        ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/counterexample/1.0")
        if artifact.get("schema_id") != "sqw://closure-artifacts/counterexample/1.0":
            raise ClosureError("counterexample_observed requires counterexample artifact")
        if ref not in run["active_counterexample_refs"]:
            run["active_counterexample_refs"].append(ref)
        if run["phase"] == "SIGNING_OFF":
            _set_phase(result, "SEARCHING")
    elif event_type == "budget_consumed":
        delta = payload.get("budget_delta") if isinstance(payload.get("budget_delta"), dict) else None
        if delta is None:
            raise ClosureError("budget_consumed requires budget_delta")
        if delta.get("candidate_evaluations") != 0 or delta.get("review_rounds") != 0:
            raise ClosureError("evaluation and review budgets are accounted only by their controller events")
        value = delta.get("iterations")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ClosureError("budget_consumed requires a positive iteration delta")
        run["budget"]["iterations_used"] += value
    elif event_type == "signoff_started":
        run["budget"]["review_rounds_used"] += 1
    elif event_type == "signoff_completed":
        _, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/signoff-result/1.0")
        if artifact.get("schema_id") != "sqw://closure-artifacts/signoff-result/1.0" or artifact.get("payload", {}).get("candidate_ref") != run.get("incumbent_candidate_ref"):
            raise ClosureError("signoff_completed requires a result bound to the incumbent")
        verdict = artifact.get("payload", {}).get("verdict")
        if verdict != "pass":
            next_phase = payload.get("next_phase", "SEARCHING")
            if next_phase != "SEARCHING":
                raise ClosureError("failed sign-off returns only to SEARCHING")
            _set_phase(result, next_phase)
        else:
            ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/signoff-result/1.0")
            run["signoff_result_ref"] = {"artifact_ref": ref, "content_hash": artifact["content_hash"]}
    elif event_type == "contract_superseded":
        handoff_ref, handoff, admission_ref, admission, plan_ref, plan, ref, artifact, authority_ref, authority = _supersession_boundary(event, artifacts)
        epoch = artifact.get("epoch")
        previous_epoch = run.get("contract_ref", {}).get("epoch") if isinstance(run.get("contract_ref"), dict) else None
        if artifact.get("status") != "frozen" or not isinstance(epoch, int) or isinstance(epoch, bool) or not isinstance(previous_epoch, int) or epoch <= previous_epoch or not isinstance(artifact.get("content_hash"), str):
            raise ClosureError("contract_superseded requires a frozen hashed contract from a validated handoff")
        for field in ("contract_ref", "baseline_ref", "verifier_bundle_ref", "incumbent_candidate_ref", "signoff_result_ref"):
            run.pop(field, None)
        run["contract_ref"] = {"artifact_ref": ref, "content_hash": artifact["content_hash"], "epoch": epoch}
        run["handoff_ref"] = {"artifact_ref": handoff_ref, "content_hash": canonical_artifact_hash(handoff)}
        run["admission_ref"] = {"artifact_ref": admission_ref, "content_hash": canonical_artifact_hash(admission)}
        run["authority_manifest_ref"] = {"artifact_ref": authority_ref, "content_hash": canonical_artifact_hash(authority)}
        run["active_candidate_refs"] = []
        run["active_counterexample_refs"] = []
        search_policy = artifact.get("search_policy") if isinstance(artifact.get("search_policy"), dict) else {}
        run["budget"] = {
            "iterations_used": 0,
            "iterations_limit": search_policy.get("max_iterations"),
            "candidate_evaluations_used": 0,
            "candidate_evaluations_limit": search_policy.get("max_candidate_evaluations"),
            "review_rounds_used": 0,
            "review_rounds_limit": search_policy.get("max_review_rounds"),
        }
        result["plan_ref"] = {
            "plan_id": plan.get("plan_id"),
            "artifact_ref": plan_ref,
            "state_ref": plan_ref,
            "content_hash": canonical_artifact_hash(plan),
        }
        result["nodes"] = []
        result["verifiers"] = []
        result["edges"] = []
        result["frontier"] = []
        result["locks"] = []
        result["artifacts"] = []
        result["recent_failures"] = []
        result["pending_background"] = []
        result["closure"] = {
            "status": "open",
            "required_verifiers": [],
            "evidence_refs": [],
            "known_gaps": [],
            "residual_risk": [],
            "epistemic_status": "needs_repair",
        }
        _set_phase(result, "BASELINING")
    elif event_type == "terminal_certificate_emitted":
        ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/terminal-certificate/1.0")
        if artifact.get("schema_id") != "sqw://closure-artifacts/terminal-certificate/1.0":
            raise ClosureError("terminal_certificate_emitted requires terminal certificate artifact")
        if artifact.get("payload", {}).get("terminal_status") == "CLOSED":
            signoff_ref = artifact.get("payload", {}).get("signoff_result_ref")
            signoff = artifacts.get(signoff_ref)
            if not isinstance(signoff, dict) or signoff.get("payload", {}).get("verdict") != "pass" or signoff.get("payload", {}).get("candidate_ref") != run.get("incumbent_candidate_ref"):
                raise ClosureError("CLOSED requires a fresh passing sign-off bound to the incumbent")
        _terminal(result, ref, artifact)
    elif event_type == "source_drift_detected":
        ref, artifact = _artifact(event, artifacts, "sqw://closure-artifacts/terminal-certificate/1.0")
        _terminal(result, ref, artifact, source_drift=True)
    elif event_type == "workflow_closed":
        result["status"] = "closed"
        result["closure"]["status"] = "closed"

    for used, limit in (("iterations_used", "iterations_limit"), ("candidate_evaluations_used", "candidate_evaluations_limit"), ("review_rounds_used", "review_rounds_limit")):
        if run["budget"][used] > run["budget"][limit]:
            raise ClosureError(f"hard budget exceeded: {used}")
    if _semantic_transition_hash(result) == _semantic_transition_hash(state):
        raise ClosureError(f"event {event_type} has no controller state effect")
    result["state_version"] = event["state_version"]
    result.pop("state_hash", None)
    result["state_hash"] = canonical_hash(result)
    return result


def _evaluation_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    payload = candidate.get("payload")
    return payload if isinstance(payload, dict) else candidate


def _computed_promotion_eligibility(payload: dict[str, Any], contract: dict[str, Any]) -> bool:
    required_hard = {item.get("id") for item in contract.get("hard_constraints", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    hard_results = {item.get("id"): item.get("status") for item in payload.get("hard_constraint_results", []) if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if any(hard_results.get(identifier) != "pass" for identifier in required_hard):
        return False
    if any(isinstance(item, dict) and item.get("status") == "fail" for item in payload.get("regression_results", [])):
        return False
    if any(isinstance(item, dict) and (item.get("blocking") is True or item.get("severity") in {"critical", "high"}) for item in payload.get("risk_findings", [])):
        return False
    return True


def rank_candidates(candidates: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    objectives = sorted(
        [item for item in contract.get("soft_objectives", []) if isinstance(item, dict) and isinstance(item.get("id"), str)],
        key=lambda item: (item.get("priority", 10**9), item["id"]),
    )
    ranked: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    for candidate in candidates:
        payload = _evaluation_payload(candidate)
        candidate_id = payload.get("candidate_id")
        if not isinstance(candidate_id, str):
            raise ClosureError("every candidate evaluation needs candidate_id")
        if candidate_id in candidate_ids:
            raise ClosureError(f"duplicate candidate evaluation: {candidate_id}")
        candidate_ids.add(candidate_id)
        hard_failures = sum(isinstance(item, dict) and item.get("status") == "fail" for item in payload.get("hard_constraint_results", []))
        regression_failures = sum(isinstance(item, dict) and item.get("status") == "fail" for item in payload.get("regression_results", []))
        metrics: dict[str, dict[str, Any]] = {}
        for item in payload.get("soft_objective_metrics", []):
            if not isinstance(item, dict) or not isinstance(item.get("objective_ref"), str):
                raise ClosureError(f"{candidate_id} has a malformed soft objective metric")
            if item["objective_ref"] in metrics:
                raise ClosureError(f"{candidate_id} repeats soft objective {item['objective_ref']}")
            metrics[item["objective_ref"]] = item
        soft_vector: list[float] = []
        for objective in objectives:
            metric = metrics.get(objective["id"])
            if metric is None:
                soft_vector.append(1e30)
                continue
            value = metric.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ClosureError(f"{candidate_id} has a non-finite metric for {objective['id']}")
            if metric.get("direction") not in {None, objective.get("direction")}:
                raise ClosureError(f"{candidate_id} metric direction differs from contract for {objective['id']}")
            direction = objective.get("direction")
            if direction == "minimize":
                soft_vector.append(float(value))
            elif direction == "maximize":
                soft_vector.append(-float(value))
            elif direction == "target":
                target = objective.get("target_value")
                if not isinstance(target, (int, float)) or isinstance(target, bool) or not math.isfinite(float(target)):
                    raise ClosureError(f"{objective['id']} has a malformed target value")
                soft_vector.append(abs(float(value) - float(target)))
            else:
                raise ClosureError(f"{objective['id']} has an unsupported direction")
        risks = [item for item in payload.get("risk_findings", []) if isinstance(item, dict)]
        high_risk = sum(item.get("severity") in {"critical", "high"} for item in risks)
        duplication = sum(item.get("category") == "architecture_duplication" or "duplication" in str(item.get("id", "")).lower() for item in risks)
        diff = payload.get("diff_stats") if isinstance(payload.get("diff_stats"), dict) else {}
        counts = [diff.get("files_changed"), diff.get("lines_added"), diff.get("lines_deleted")]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts):
            raise ClosureError(f"{candidate_id} has malformed diff statistics")
        files, added, deleted = counts
        lines = added + deleted
        complexity = files + lines
        cost = payload.get("evaluation_cost") if isinstance(payload.get("evaluation_cost"), dict) else {}
        wall_seconds = cost.get("wall_seconds")
        if not isinstance(wall_seconds, (int, float)) or isinstance(wall_seconds, bool) or not math.isfinite(float(wall_seconds)) or wall_seconds < 0:
            raise ClosureError(f"{candidate_id} has malformed evaluation cost")
        wall_seconds = float(wall_seconds)
        score = (hard_failures, regression_failures, tuple(soft_vector), high_risk, duplication, files, complexity, lines, wall_seconds, candidate_id)
        computed_eligible = _computed_promotion_eligibility(payload, contract)
        comparison = {
            "hard_constraint_failure_count": hard_failures,
            "blocking_regression_count": regression_failures,
            "soft_objective_vector_by_priority": soft_vector,
            "unresolved_high_risk_count": high_risk,
            "architecture_duplication_count": duplication,
            "changed_surface_risk": files,
            "diff_complexity": complexity,
            "changed_lines": lines,
            "evaluation_cost": wall_seconds,
            "controller_eligible": computed_eligible,
        }
        ranked.append({"candidate_id": candidate_id, "score": score, "comparison": comparison, "evaluation": candidate, "controller_eligible": computed_eligible})
    ranked.sort(key=lambda item: item["score"])
    for item in ranked:
        item["score"] = list(item["score"][:-1])
    winner = next((item["candidate_id"] for item in ranked if item["controller_eligible"]), None)
    return {"ranked": ranked, "winner_candidate_id": winner}


def select_promotion(state: dict[str, Any], event: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> str:
    run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
    contract_ref = run.get("contract_ref", {}).get("artifact_ref") if isinstance(run.get("contract_ref"), dict) else None
    contract = artifacts.get(contract_ref)
    if not isinstance(contract, dict):
        raise ClosureError("promotion requires the frozen contract")
    active_refs = [ref for ref in run.get("active_candidate_refs", []) if isinstance(ref, str)]
    manifests = [artifacts.get(ref) for ref in active_refs]
    if not active_refs or any(not isinstance(item, dict) for item in manifests):
        raise ClosureError("promotion requires all active candidate manifests")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    event_refs = set(payload.get("artifact_refs", [])) if isinstance(payload.get("artifact_refs"), list) else set()
    evaluations = [
        artifact
        for ref, artifact in artifacts.items()
        if ref in event_refs and artifact.get("schema_id") == "sqw://closure-artifacts/candidate-evaluation/1.0"
    ]
    by_candidate: dict[str, dict[str, Any]] = {}
    for evaluation in evaluations:
        candidate_id = evaluation.get("payload", {}).get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id in by_candidate:
            raise ClosureError("promotion requires one evaluation per active candidate")
        by_candidate[candidate_id] = evaluation
    active_ids = [item.get("payload", {}).get("candidate_id") for item in manifests if isinstance(item, dict)]
    if any(not isinstance(candidate_id, str) or candidate_id not in by_candidate for candidate_id in active_ids):
        raise ClosureError("promotion requires fresh evaluations for every active candidate")
    ranked = rank_candidates([by_candidate[candidate_id] for candidate_id in active_ids], contract)
    winner_id = ranked.get("winner_candidate_id")
    if not isinstance(winner_id, str):
        raise ClosureError("controller found no promotion-eligible candidate")
    return active_refs[active_ids.index(winner_id)]


def compute_invalidation(root_change: dict[str, Any], graph: dict[str, list[str]]) -> dict[str, Any]:
    kind = root_change.get("kind")
    root = root_change.get("ref")
    global_restart = {
        "contract_hash": "BASELINING",
        "policy_bundle_hash": "BASELINING",
        "controller_hash": "BASELINING",
        "protected_surface": "BASELINING",
        "verifier_bundle_hash": "VERIFIER_QUALIFYING",
        "baseline_environment": "BASELINING",
        "source_revision": "BASELINING",
    }
    universe = {str(item) for item in graph}
    for values in graph.values():
        universe.update(str(item) for item in values)
    if kind in global_restart:
        return {
            "affected": sorted(universe),
            "preserved": [],
            "new_epoch_required": True,
            "restart_phase": global_restart[kind],
            "reason_codes": [f"global_{kind}_changed"],
        }
    pending = list(graph.get(str(root), []))
    affected: set[str] = set()
    while pending:
        item = str(pending.pop(0))
        if item in affected:
            continue
        affected.add(item)
        pending.extend(graph.get(item, []))
    return {
        "affected": sorted(affected),
        "preserved": sorted(universe - affected - {str(root)}),
        "new_epoch_required": False,
        "restart_phase": "SEARCHING",
        "reason_codes": [f"local_{kind}_changed"],
    }
