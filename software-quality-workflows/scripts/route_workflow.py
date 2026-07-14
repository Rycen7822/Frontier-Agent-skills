#!/usr/bin/env python3
"""Select SQW mode, execution policy, and a validated owner/reference stack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, Violation, load_json, pointer
from assess_closure_admission import assess_admission
from validate_owner_registry import validate_registry


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "references" / "owner-registry.json"
REGISTRY_SCHEMA_PATH = ROOT / "schemas" / "owner-registry.schema.json"

FACT_DEFAULTS: dict[str, Any] = {
    "request_mode": "change",
    "task_kind": "routine_change",
    "root_cause_status": "not_applicable",
    "intent_status": "defined",
    "same_session": None,
    "durable_handoff": None,
    "resume_required": None,
    "independent_read_slices": 0,
    "independent_write_slices": 0,
    "strategy_family_count": 1,
    "writes_are_disjoint": None,
    "resources_are_disjoint": None,
    "machine_observable_outcome": None,
    "requirements_stable_enough": None,
    "verifier_separable": None,
    "reproducible_environment": None,
    "bounded_side_effects": None,
    "search_value": "none",
    "dirty_or_concurrent_work": None,
    "public_contract": None,
    "security_boundary": None,
    "migration_or_release": None,
    "installed_surface": None,
    "external_side_effect": None,
    "destructive_or_irreversible": None,
    "privileged": None,
    "shared_mutable_state": None,
    "source_version_uncertain": None,
    "verification_cost": "low",
    "failure_locality": "likely_local",
    "explicit_plan_request": False,
    "autonomous_closure_requested": False,
    "trace_only": False,
    "plugin_source": False,
    "browser_runtime": False,
    "performance_sensitive": False,
    "slow_external_job": False,
    "publication_ceiling": "none",
    "user_constraints": {},
}

NULLABLE_BOOLEAN_FACTS = {
    "same_session",
    "durable_handoff",
    "resume_required",
    "writes_are_disjoint",
    "resources_are_disjoint",
    "machine_observable_outcome",
    "requirements_stable_enough",
    "verifier_separable",
    "reproducible_environment",
    "bounded_side_effects",
    "dirty_or_concurrent_work",
    "public_contract",
    "security_boundary",
    "migration_or_release",
    "installed_surface",
    "external_side_effect",
    "destructive_or_irreversible",
    "privileged",
    "shared_mutable_state",
    "source_version_uncertain",
}
BOOLEAN_FACTS = {
    "explicit_plan_request",
    "autonomous_closure_requested",
    "trace_only",
    "plugin_source",
    "browser_runtime",
    "performance_sensitive",
    "slow_external_job",
}
RISK_FACTS = {
    "same_session",
    "durable_handoff",
    "resume_required",
    "dirty_or_concurrent_work",
    "public_contract",
    "security_boundary",
    "migration_or_release",
    "installed_surface",
    "external_side_effect",
    "destructive_or_irreversible",
    "privileged",
    "shared_mutable_state",
    "source_version_uncertain",
    "machine_observable_outcome",
    "requirements_stable_enough",
    "verifier_separable",
    "reproducible_environment",
    "bounded_side_effects",
}
ROUTE_RESULT_KEYS = {
    "workflow_mode", "execution_policy", "request_mode", "primary_owner",
    "active_normative_owners", "active_companions", "required_references",
    "must_not_load", "forbidden_actions", "reason_codes", "required_gates",
    "closure_admission", "plan_profile", "durable_state_required",
    "approval_required", "warnings",
}


def _registry(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, dict[str, Any]], set[str]]:
    registry = load_json(root / "references" / "owner-registry.json")
    schema = load_json(root / "schemas" / "owner-registry.schema.json")
    violations = validate_registry(registry, schema, root)
    if violations:
        raise ValueError("owner registry is invalid: " + ", ".join(sorted({item.code for item in violations})))
    by_id = {item["id"]: item for item in registry["owners"]}
    external = {item["id"] for item in registry.get("external_owners", [])}
    return registry, by_id, external


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _dependency_closure(seed_ids: list[str], by_id: dict[str, dict[str, Any]]) -> set[str]:
    pending = list(seed_ids)
    result: set[str] = set()
    while pending:
        owner_id = pending.pop()
        owner = by_id.get(owner_id)
        if owner is None:
            continue
        for target in owner.get("requires", []):
            if target not in result:
                result.add(target)
                pending.append(target)
    return result


def _path_for(owner_id: str, by_id: dict[str, dict[str, Any]]) -> str:
    return by_id[owner_id]["path"]


def _validated_facts(raw_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_facts, dict):
        raise ValueError("route facts must be an object")
    unknown = sorted(set(raw_facts) - set(FACT_DEFAULTS))
    if unknown:
        raise ValueError(f"unknown route facts: {unknown}")
    facts = {**FACT_DEFAULTS, **raw_facts}
    for key in NULLABLE_BOOLEAN_FACTS:
        if facts[key] is not None and not isinstance(facts[key], bool):
            raise ValueError(f"{key} must be boolean or null")
    for key in BOOLEAN_FACTS:
        if not isinstance(facts[key], bool):
            raise ValueError(f"{key} must be boolean")
    for key in ("independent_read_slices", "independent_write_slices"):
        value = facts[key]
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1000:
            raise ValueError(f"{key} must be an integer from 0 through 1000")
    families = facts["strategy_family_count"]
    if not isinstance(families, int) or isinstance(families, bool) or not 1 <= families <= 64:
        raise ValueError("strategy_family_count must be an integer from 1 through 64")
    enums = {
        "request_mode": {"report", "review", "diagnose", "change", "recovery"},
        "task_kind": {"routine_change", "bugfix", "failure", "migration", "runtime_stability", "merge_conflict", "recovery", "audit"},
        "root_cause_status": {"known", "unknown", "not_applicable"},
        "intent_status": {"defined", "low_risk_defaults_available", "materially_underdefined"},
        "search_value": {"none", "low", "medium", "high"},
        "verification_cost": {"low", "medium", "high"},
        "failure_locality": {"likely_local", "mixed", "not_localizable"},
        "publication_ceiling": {"none", "local_patch", "draft_pr"},
    }
    for key, values in enums.items():
        if facts[key] not in values:
            raise ValueError(f"invalid {key}: {facts[key]!r}")
    constraints = facts["user_constraints"]
    allowed_constraints = {"no_subagents", "no_external_writes", "max_review_rounds", "max_candidate_evaluations"}
    if not isinstance(constraints, dict) or set(constraints) - allowed_constraints:
        raise ValueError("user_constraints contains unknown fields or is not an object")
    constraints = {
        "no_subagents": constraints.get("no_subagents", False),
        "no_external_writes": constraints.get("no_external_writes", False),
        "max_review_rounds": constraints.get("max_review_rounds", 2),
        "max_candidate_evaluations": constraints.get("max_candidate_evaluations", 10),
    }
    for key in ("no_subagents", "no_external_writes"):
        if not isinstance(constraints[key], bool):
            raise ValueError(f"user_constraints.{key} must be boolean")
    for key in ("max_review_rounds", "max_candidate_evaluations"):
        value = constraints[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"user_constraints.{key} must be a non-negative integer")
    facts["user_constraints"] = constraints
    return facts


def _build_result(
    facts: dict[str, Any],
    *,
    mode: str,
    execution_policy: str,
    primary: str,
    reasons: list[str],
    gates: list[str],
    normative: list[str] | None = None,
    companions: list[str] | None = None,
    must_not: list[str] | None = None,
    forbidden: list[str] | None = None,
    closure_admission: str = "not_applicable",
    plan_profile: str | None = None,
    preworkflow: bool = False,
) -> dict[str, Any]:
    _, by_id, external = _registry()
    normative_ids = list(normative or [])
    companion_ids = list(companions or [])
    local_seed = ([primary] if primary in by_id else []) + normative_ids + companion_ids
    dependency_ids = _dependency_closure(local_seed, by_id)
    normative_ids.extend(owner_id for owner_id in sorted(dependency_ids) if by_id[owner_id]["authority"] == "normative_owner" and owner_id != primary)
    normative_ids = _unique(normative_ids)
    companion_ids = _unique(companion_ids)

    active_local = ([primary] if primary in by_id else []) + normative_ids + companion_ids
    reference_paths = [_path_for(owner_id, by_id) for owner_id in _unique(active_local)]
    must_not_paths: list[str] = []
    for item in must_not or []:
        must_not_paths.append(_path_for(item, by_id) if item in by_id else item)
    forbidden_actions = list(forbidden or [])
    reason_codes = list(reasons)
    constraints = facts["user_constraints"]
    if constraints["no_subagents"]:
        reason_codes.append("user_forbids_subagents")
        must_not_paths.extend([
            _path_for("delegated-development", by_id),
            _path_for("evidence-delegation", by_id),
        ])
        forbidden_actions.append("delegation")
    if constraints["no_external_writes"]:
        reason_codes.append("user_forbids_external_writes")
        forbidden_actions.append("external_write")
    if facts["slow_external_job"]:
        forbidden_actions.append("multi_candidate_fanout")

    warnings: list[str] = []
    unique_active = _unique(active_local)
    if len(unique_active) > 8:
        warnings.append("reference_soft_budget_exceeded")
        reason_codes.extend("reference_budget_extra_" + owner_id.replace("-", "_") for owner_id in unique_active[8:])

    result: dict[str, Any] = {
        "workflow_mode": mode,
        "execution_policy": execution_policy,
        "request_mode": facts["request_mode"],
        "primary_owner": primary,
        "active_normative_owners": normative_ids,
        "active_companions": companion_ids,
        "required_references": reference_paths,
        "must_not_load": _unique(must_not_paths),
        "forbidden_actions": _unique(forbidden_actions),
        "reason_codes": _unique(reason_codes),
        "required_gates": _unique(gates),
        "closure_admission": closure_admission,
        "plan_profile": plan_profile,
        "durable_state_required": False if preworkflow else mode in {"M2_SPARSE", "M3_FULL"},
        "approval_required": any(facts[key] is True for key in ("external_side_effect", "destructive_or_irreversible", "privileged")),
        "warnings": warnings,
    }
    violations = validate_route_result(result, ROOT)
    if violations:
        raise ValueError("invalid route result: " + ", ".join(sorted({item.code for item in violations})))
    return result


def validate_route_result(result: Any, root: Path = ROOT) -> list[Violation]:
    violations: list[Violation] = []
    if not isinstance(result, dict):
        return [Violation("route.shape", "", "route result must be an object")]
    missing_keys = sorted(ROUTE_RESULT_KEYS - set(result))
    unknown_keys = sorted(set(result) - ROUTE_RESULT_KEYS)
    if missing_keys or unknown_keys:
        violations.append(Violation("route.shape", "", f"route result keys differ: missing={missing_keys}, unknown={unknown_keys}"))
    try:
        _, by_id, external = _registry(root)
    except (OSError, InputError, ValueError) as exc:
        return [Violation("route.registry-invalid", "", str(exc))]

    primary = result.get("primary_owner")
    if primary not in by_id and primary not in external:
        violations.append(Violation("route.owner-unknown", "/primary_owner", f"unknown primary owner: {primary}"))
    elif primary in by_id and by_id[primary]["authority"] != "normative_owner":
        violations.append(Violation("route.companion-primary", "/primary_owner", "companion cannot be primary", primary))

    normative = result.get("active_normative_owners", [])
    companions = result.get("active_companions", [])
    normative_valid = isinstance(normative, list) and all(isinstance(item, str) for item in normative)
    companions_valid = isinstance(companions, list) and all(isinstance(item, str) for item in companions)
    if not normative_valid or len(normative) > 8 or len(set(normative)) != len(normative):
        violations.append(Violation("route.owner-budget", "/active_normative_owners", "normative owners must be unique and no more than 8"))
        normative = normative if normative_valid else []
    if not companions_valid or len(companions) > 6 or len(set(companions)) != len(companions):
        violations.append(Violation("route.owner-budget", "/active_companions", "companions must be unique and no more than 6"))
        companions = companions if companions_valid else []
    for index, owner_id in enumerate(normative):
        owner = by_id.get(owner_id)
        if owner is None:
            violations.append(Violation("route.owner-unknown", pointer(("active_normative_owners", index)), f"unknown normative owner: {owner_id}"))
        elif owner["authority"] != "normative_owner" or owner_id == primary:
            violations.append(Violation("route.owner-authority", pointer(("active_normative_owners", index)), "entry is not a non-primary normative owner", owner_id))
    for index, owner_id in enumerate(companions):
        owner = by_id.get(owner_id)
        if owner is None:
            violations.append(Violation("route.owner-unknown", pointer(("active_companions", index)), f"unknown companion: {owner_id}"))
        elif owner["authority"] != "companion":
            violations.append(Violation("route.owner-authority", pointer(("active_companions", index)), "entry is not a companion", owner_id))

    active_ids = _unique(([primary] if primary in by_id else []) + list(normative) + list(companions))
    if len(active_ids) > 12:
        violations.append(Violation("route.reference-hard-cap", "/required_references", "active reference hard cap is 12"))
    if len(active_ids) > 8:
        reasons = result.get("reason_codes", [])
        for owner_id in active_ids[8:]:
            expected_reason = "reference_budget_extra_" + owner_id.replace("-", "_")
            if not isinstance(reasons, list) or expected_reason not in reasons:
                violations.append(Violation("route.reference-soft-budget", "/reason_codes", f"missing unique overflow reason for {owner_id}"))
    expected_paths = {_path_for(owner_id, by_id) for owner_id in active_ids if owner_id in by_id}
    references = result.get("required_references", [])
    if not isinstance(references, list) or any(not isinstance(path, str) or not path.startswith("references/") for path in references):
        violations.append(Violation("route.reference-path", "/required_references", "references must use full registry-relative paths"))
    elif set(references) != expected_paths or len(references) != len(set(references)):
        violations.append(Violation("route.reference-closure", "/required_references", "loaded paths must exactly match active local owners"))
    must_not = result.get("must_not_load", [])
    registered_paths = {item["path"] for item in by_id.values()}
    if not isinstance(must_not, list) or any(not isinstance(path, str) or not path.startswith("references/") for path in must_not):
        violations.append(Violation("route.reference-path", "/must_not_load", "must-not-load entries must use full registry-relative paths"))
    else:
        for index, path in enumerate(must_not):
            if path not in registered_paths:
                violations.append(Violation("route.reference-unknown", pointer(("must_not_load", index)), f"unregistered must-not-load path: {path}"))
            if path in expected_paths:
                violations.append(Violation("route.reference-conflict", pointer(("must_not_load", index)), "reference is both required and forbidden"))

    required = _dependency_closure(active_ids, by_id)
    if not required.issubset(set(active_ids)):
        violations.append(Violation("route.requires-missing", "/active_normative_owners", f"missing required owners: {sorted(required - set(active_ids))}"))
    for owner_id in active_ids:
        owner = by_id.get(owner_id, {})
        for conflict in owner.get("conflicts_with", []):
            if conflict in active_ids:
                violations.append(Violation("route.owner-conflict", "/active_normative_owners", f"active owners conflict: {owner_id}, {conflict}"))

    mode = result.get("workflow_mode")
    policy = result.get("execution_policy")
    admission = result.get("closure_admission")
    if mode not in {"M0_DIRECT", "M1_TRACE", "M2_SPARSE", "M3_FULL"}:
        violations.append(Violation("route.mode", "/workflow_mode", "unknown workflow mode"))
    if policy not in {"standard", "autonomous_closure"}:
        violations.append(Violation("route.execution-policy", "/execution_policy", "unknown execution policy"))
    if admission not in {"not_applicable", "candidate", "eligible", "ineligible", "terminal"}:
        violations.append(Violation("route.closure-admission", "/closure_admission", "unknown closure admission result"))
    if policy == "autonomous_closure" and mode in {"M0_DIRECT", "M1_TRACE"} and admission not in {"terminal", "candidate"}:
        violations.append(Violation("route.closure-mode", "/workflow_mode", "autonomous closure workflow cannot use M0/M1"))
    if admission == "eligible" and (primary != "autonomous-closure" or result.get("plan_profile") != "program"):
        violations.append(Violation("route.closure-shape", "/closure_admission", "eligible closure requires autonomous owner and Program plan"))
    profile = result.get("plan_profile")
    if profile not in {None, "brief", "handoff", "program"}:
        violations.append(Violation("route.plan-profile", "/plan_profile", "unknown plan profile"))
    if admission in {"eligible", "candidate"} and policy != "autonomous_closure":
        violations.append(Violation("route.closure-policy", "/execution_policy", "eligible/candidate admission requires autonomous policy"))
    if admission == "ineligible" and policy != "standard":
        violations.append(Violation("route.closure-policy", "/execution_policy", "ineligible admission must fall back to standard policy"))
    if result.get("request_mode") not in {"report", "review", "diagnose", "change", "recovery"}:
        violations.append(Violation("route.request-mode", "/request_mode", "unknown request mode"))
    for field in ("forbidden_actions", "reason_codes", "required_gates", "warnings"):
        value = result.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value) or len(value) != len(set(value)):
            violations.append(Violation("route.shape", f"/{field}", f"{field} must be a unique string array"))
    if not isinstance(result.get("approval_required"), bool):
        violations.append(Violation("route.shape", "/approval_required", "approval_required must be boolean"))
    durable = result.get("durable_state_required")
    if not isinstance(durable, bool):
        violations.append(Violation("route.durable-state", "/durable_state_required", "durable-state flag must be boolean"))
    elif mode in {"M0_DIRECT", "M1_TRACE"} and durable:
        violations.append(Violation("route.durable-state", "/durable_state_required", "M0/M1 cannot require durable workflow state"))
    elif mode in {"M2_SPARSE", "M3_FULL"} and not durable and admission not in {"candidate", "terminal"} and primary not in external:
        violations.append(Violation("route.durable-state", "/durable_state_required", "M2/M3 route requires durable state unless it is pre-workflow"))
    return violations


def _closure_candidate(facts: dict[str, Any]) -> bool:
    return (
        facts["autonomous_closure_requested"]
        or facts["strategy_family_count"] >= 2
        or facts["search_value"] in {"medium", "high"}
    )


def _admission_facts(facts: dict[str, Any]) -> dict[str, Any]:
    unknown_authority = any(facts[key] is None for key in RISK_FACTS)
    no_external = facts["user_constraints"]["no_external_writes"]
    authority_conflict = (
        facts["privileged"] is True
        or (facts["external_side_effect"] is True and no_external)
        or (facts["publication_ceiling"] != "none" and no_external)
    )
    framework_tax = "high" if facts["slow_external_job"] else ("medium" if facts["verification_cost"] == "high" else "low")
    return {
        "autonomous_closure_requested": facts["autonomous_closure_requested"],
        "intent_status": facts["intent_status"],
        "machine_observable_outcome": facts["machine_observable_outcome"],
        "requirements_stable_enough": facts["requirements_stable_enough"],
        "known_requirement_conflict": False,
        "scope_freezable": None if unknown_authority else True,
        "authority_freezable": None if unknown_authority else not authority_conflict,
        "reproducible_environment": facts["reproducible_environment"],
        "verifier_separable": facts["verifier_separable"],
        "bounded_side_effects": facts["bounded_side_effects"],
        "resume_required": facts["resume_required"] is True,
        "expensive_proof_reusable": facts["verification_cost"] == "high",
        "local_repair_likely": facts["task_kind"] == "bugfix" and facts["failure_locality"] == "likely_local",
        "strategy_family_count": facts["strategy_family_count"],
        "search_value": facts["search_value"],
        "framework_tax": framework_tax,
    }


def assess(raw_facts: dict[str, Any]) -> dict[str, Any]:
    facts = _validated_facts(raw_facts)

    if facts["trace_only"]:
        traced = dict(facts)
        traced["trace_only"] = False
        traced["autonomous_closure_requested"] = False
        traced["strategy_family_count"] = 1
        traced["search_value"] = "none"
        result = assess(traced)
        if result["workflow_mode"] == "M0_DIRECT":
            result["workflow_mode"] = "M1_TRACE"
            result["durable_state_required"] = False
        result["reason_codes"] = _unique(result["reason_codes"] + ["trace_only"])
        violations = validate_route_result(result, ROOT)
        if violations:
            raise ValueError("invalid traced route result: " + ", ".join(sorted({item.code for item in violations})))
        return result

    if facts["request_mode"] in {"report", "review"}:
        companions = ["evidence-delegation"] if facts["independent_read_slices"] >= 2 and facts["durable_handoff"] is True and not facts["user_constraints"]["no_subagents"] else []
        mode = "M2_SPARSE" if companions else "M0_DIRECT"
        return _build_result(facts, mode=mode, execution_policy="standard", primary="read-only-architecture-audits", reasons=["report_only"] + (["independent_read_slices"] if companions else []), gates=["static_contract"], companions=companions, forbidden=["source_write"])

    if facts["request_mode"] == "recovery" or facts["task_kind"] in {"recovery", "merge_conflict"}:
        owner = "merge-conflict-resolution" if facts["task_kind"] == "merge_conflict" else "repository-recovery"
        forbidden = ["auto_commit", "auto_continue"] if owner == "merge-conflict-resolution" else []
        return _build_result(facts, mode="M3_FULL", execution_policy="standard", primary=owner, reasons=["recovery_required"], gates=["focused", "affected", "approval"], forbidden=forbidden)

    if facts["request_mode"] == "diagnose" or (facts["task_kind"] in {"bugfix", "failure"} and facts["root_cause_status"] != "known"):
        normative: list[str] = []
        if facts["installed_surface"] is True:
            normative.append("plugin-installed-surface")
        if facts["browser_runtime"]:
            normative.append("browser-runtime-verification")
        mode = "M2_SPARSE" if normative else "M0_DIRECT"
        return _build_result(facts, mode=mode, execution_policy="standard", primary="systematic-debugging", reasons=["root_cause_unknown"], gates=["focused"], normative=normative, must_not=["delegated-development"] if mode == "M0_DIRECT" else [])

    if facts["intent_status"] == "materially_underdefined":
        return _build_result(facts, mode="M0_DIRECT", execution_policy="standard", primary="intent-and-design-discovery", reasons=["material_intent_ambiguity"], gates=[], closure_admission="terminal" if facts["autonomous_closure_requested"] else "not_applicable", preworkflow=True)

    if _closure_candidate(facts):
        admission = assess_admission(_admission_facts(facts))
        status = admission["status"]
        if status == "closure_eligible":
            mode = "M3_FULL" if facts["task_kind"] in {"migration", "runtime_stability"} or facts["migration_or_release"] is True or facts["shared_mutable_state"] is True else "M2_SPARSE"
            return _build_result(facts, mode=mode, execution_policy="autonomous_closure", primary="autonomous-closure", reasons=admission["reason_codes"], gates=["baseline", "verifier_qualification", "candidate_cascade", "four_axis_signoff"], closure_admission="eligible", plan_profile="program")
        if status == "verifier_unqualified_candidate":
            return _build_result(facts, mode="M2_SPARSE", execution_policy="autonomous_closure", primary="autonomous-closure", reasons=admission["reason_codes"], gates=["verifier_qualification"], closure_admission="candidate", preworkflow=True)
        if status not in {"direct_preferred"}:
            return _build_result(facts, mode="M2_SPARSE", execution_policy="autonomous_closure", primary="autonomous-closure", reasons=admission["reason_codes"], gates=["terminal_certificate"], closure_admission="terminal", preworkflow=True)
        closure_admission = "ineligible"
        closure_reasons = admission["reason_codes"]
    else:
        closure_admission = "not_applicable"
        closure_reasons = []

    if facts["explicit_plan_request"]:
        profile = "brief" if facts["same_session"] is True and facts["durable_handoff"] is False else "handoff"
        return _build_result(facts, mode="M2_SPARSE" if profile == "handoff" else "M0_DIRECT", execution_policy="standard", primary="writing-plans", reasons=closure_reasons + ["user_requires_plan"], gates=["plan_contract"], closure_admission=closure_admission, plan_profile=profile, preworkflow=True)

    unknown_risk = any(facts[key] is None for key in RISK_FACTS)
    if unknown_risk:
        return _build_result(facts, mode="M2_SPARSE", execution_policy="standard", primary="change-execution", reasons=closure_reasons + ["risk_fact_unknown"], gates=["focused", "affected"], normative=["authority-and-scope"], closure_admission=closure_admission)

    normative: list[str] = []
    companions: list[str] = []
    reasons = list(closure_reasons)
    gates = ["focused", "affected"]
    mode = "M0_DIRECT"
    plan_profile: str | None = None

    if facts["migration_or_release"] is True or facts["task_kind"] == "migration":
        mode = "M3_FULL"
        normative.append("api-interface-design")
        reasons.extend(["migration_or_release", "durable_handoff"])
        gates.extend(["public_surface", "canonical"])
        plan_profile = "program"
    elif facts["public_contract"] is True:
        mode = "M2_SPARSE"
        normative.append("api-interface-design")
        reasons.append("public_contract")
        gates.append("public_surface")
        plan_profile = "program"
    if facts["security_boundary"] is True:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        normative.append("security-hardening")
        reasons.append("security_boundary")
        gates.append("security_negative")
    if facts["plugin_source"]:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        normative.append("plugin-quality")
        reasons.append("plugin_source")
    if facts["installed_surface"] is True:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        normative.append("plugin-installed-surface")
        reasons.append("installed_surface")
        gates.append("public_surface")
    if facts["browser_runtime"]:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        normative.append("browser-runtime-verification")
        reasons.append("browser_runtime")
        gates.append("public_surface")
    if facts["performance_sensitive"]:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        normative.append("performance-optimization")
        reasons.append("performance_sensitive")
        gates.append("benchmark")
    if facts["task_kind"] == "runtime_stability":
        mode = "M3_FULL"
        companions.append("real-runtime-stability-loop")
        reasons.extend(["runtime_stability", "resume_required"])
        gates.append("canonical")
    if any(facts[key] is True for key in ("external_side_effect", "destructive_or_irreversible", "privileged", "source_version_uncertain")):
        mode = "M3_FULL" if facts["destructive_or_irreversible"] is True else "M2_SPARSE"
        normative.append("authority-and-scope")
        reasons.append("authority_guard_required")
        gates.append("approval")
    if facts["shared_mutable_state"] is True:
        mode = "M2_SPARSE"
        reasons.append("shared_mutable_state")
        if facts["writes_are_disjoint"] is True and facts["resources_are_disjoint"] is True:
            normative.append("delegated-development")
        else:
            reasons.append("delegation_not_isolated")
    if facts["independent_write_slices"] >= 2 and facts["durable_handoff"] is True:
        mode = "M2_SPARSE"
        if facts["writes_are_disjoint"] is True and facts["resources_are_disjoint"] is True and not facts["user_constraints"]["no_subagents"]:
            normative.append("delegated-development")
            reasons.append("delegation_net_positive")
        else:
            reasons.append("delegation_not_isolated")
    if facts["durable_handoff"] is True or facts["resume_required"] is True:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        reasons.append("durable_state_required")
    if facts["dirty_or_concurrent_work"] is True:
        mode = "M2_SPARSE" if mode == "M0_DIRECT" else mode
        normative.append("authority-and-scope")
        reasons.append("dirty_or_concurrent_work")
    if facts["slow_external_job"]:
        mode = "M1_TRACE" if mode == "M0_DIRECT" else mode
        normative.append("observability-instrumentation")
        reasons.append("slow_external_job")
        gates.append("canonical")

    if facts["task_kind"] == "bugfix":
        reasons.append("root_cause_known")
        gates.insert(0, "red")
    if mode == "M0_DIRECT":
        reasons.extend(["routine_direct_path", "local_reversible"])

    return _build_result(facts, mode=mode, execution_policy="standard", primary="change-execution", reasons=reasons, gates=gates, normative=normative, companions=companions, closure_admission=closure_admission, plan_profile=plan_profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess(load_json(args.facts))
    except (OSError, InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
