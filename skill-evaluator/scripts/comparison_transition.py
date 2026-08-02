"""Deterministic policy for model-transition comparisons."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from comparison_contract import CycleCapsule
from comparison_revision_contract import (
    capsule_diagnostic,
    cycle_plan_projection,
    cycle_spec_projection,
    plan_diagnostic,
    same,
)
from comparison_transition_metrics import (
    gate_diagnostics,
    metric_result,
    stage_result,
)


_DIRECT_IDENTITY_FIELDS = {"model_hash", "host_hash"}
_MODEL_HOST_FIELDS = {"provider", "model", "model_revision"}


def _host_projection(
    host: dict[str, Any],
    *,
    model_change: bool,
    tokenizer_change: bool,
) -> dict[str, Any]:
    projected = deepcopy(host)
    projected.pop("manifest_hash", None)
    identity = projected["identity"]
    identity["repository"].pop("worktree", None)
    identity["session"].pop("session_id", None)
    execution = identity["execution"]
    if model_change:
        for field in _MODEL_HOST_FIELDS:
            execution.pop(field, None)
    if tokenizer_change:
        execution.pop("tokenizer_id", None)
        execution.pop("pricing_id", None)
    return projected


def _contract_projection(
    capsule: CycleCapsule,
    *,
    omit_judge: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    subject_id = capsule.spec["subject"]["skill_id"]
    spec = cycle_spec_projection(capsule.spec)
    plan = cycle_plan_projection(capsule.execution_plan, subject_id)
    if omit_judge:
        spec.pop("graders", None)
        spec["suite"].pop("grader_set_hash", None)
        spec["suite"].pop("grader_schedule_hash", None)
        plan.pop("grader_set_hash", None)
    return spec, plan


def _host_subject_projection(
    host: dict[str, Any],
    subject_id: str,
) -> dict[str, Any]:
    """Keep the evaluated package fixed across apparatus changes."""
    return {
        "skill_hash": host["identity"]["execution"]["skill_hash"],
        "subject_entries": [
            entry for entry in host["catalog"]["entries"]
            if entry["id"] == subject_id
        ],
    }


def _pair_contract_diagnostics(
    plan: dict[str, Any],
    left: CycleCapsule,
    right: CycleCapsule,
    *,
    allowed_identity_fields: set[str],
    require_model_change: bool,
    allow_judge_change: bool,
    broad_host_change: bool,
    model_host_change: bool,
    tokenizer_host_change: bool,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    left_identity = left.execution_plan["execution_identity"]
    right_identity = right.execution_plan["execution_identity"]
    changed_identity_fields = {
        field
        for field in left_identity
        if field != "as_of" and left_identity[field] != right_identity[field]
    }
    unexpected = sorted(changed_identity_fields - allowed_identity_fields)
    model_changed = left_identity["model_hash"] != right_identity["model_hash"]
    if unexpected or model_changed != require_model_change:
        diagnostics.append(capsule_diagnostic(
            plan,
            right,
            "execution_plan",
            fact_type="identity_mismatch",
            reason_key="transition_execution_identity_invalid",
            roles=[left.role, right.role],
            expected={
                "allowed_changes": sorted(allowed_identity_fields),
                "model_change_required": require_model_change,
            },
            observed={
                "changed_fields": sorted(changed_identity_fields),
                "unexpected_fields": unexpected,
                "model_changed": model_changed,
            },
            json_pointer="/execution_identity",
        ))

    left_spec, left_plan = _contract_projection(
        left,
        omit_judge=allow_judge_change,
    )
    right_spec, right_plan = _contract_projection(
        right,
        omit_judge=allow_judge_change,
    )
    left_host_subject = _host_subject_projection(
        left.host_manifest,
        left.spec["subject"]["skill_id"],
    )
    right_host_subject = _host_subject_projection(
        right.host_manifest,
        right.spec["subject"]["skill_id"],
    )
    host_subject_valid = (
        same(left_host_subject, right_host_subject)
        and len(left_host_subject["subject_entries"]) == 1
        and len(right_host_subject["subject_entries"]) == 1
        and left_host_subject["subject_entries"][0]["root_hash"]
        == left.spec["subject"]["package"]["package_hash"]
        and right_host_subject["subject_entries"][0]["root_hash"]
        == right.spec["subject"]["package"]["package_hash"]
    )
    contract_parts = {
        "subject": same(left.spec["subject"], right.spec["subject"]),
        "host_subject": host_subject_valid,
        "package_hashes": same(
            left.execution_plan["package_hashes"],
            right.execution_plan["package_hashes"],
        ),
        "spec": same(left_spec, right_spec),
        "execution_plan": same(left_plan, right_plan),
    }
    if not all(contract_parts.values()):
        diagnostics.append(capsule_diagnostic(
            plan,
            right,
            "execution_plan",
            fact_type="identity_mismatch",
            reason_key="transition_cycle_contract_drift",
            roles=[left.role, right.role],
            expected=(
                "subject, package, case, treatment, fixture, ordering, "
                "and count semantics match"
            ),
            observed=contract_parts,
            json_pointer="",
        ))

    judge_changed = (
        left.execution_plan["grader_set_hash"]
        != right.execution_plan["grader_set_hash"]
    )
    if judge_changed and not allow_judge_change:
        diagnostics.append(capsule_diagnostic(
            plan,
            right,
            "execution_plan",
            fact_type="identity_mismatch",
            reason_key="transition_judge_identity_drift",
            roles=[left.role, right.role],
            expected="the grader set remains fixed",
            observed="grader_set_hash changed without a permitted bridge",
            json_pointer="/grader_set_hash",
        ))

    if not broad_host_change and not same(
        _host_projection(
            left.host_manifest,
            model_change=model_host_change,
            tokenizer_change=tokenizer_host_change,
        ),
        _host_projection(
            right.host_manifest,
            model_change=model_host_change,
            tokenizer_change=tokenizer_host_change,
        ),
    ):
        diagnostics.append(capsule_diagnostic(
            plan,
            right,
            "host_manifest",
            fact_type="identity_mismatch",
            reason_key="transition_host_change_not_allowed",
            roles=[left.role, right.role],
            expected="host changes are limited to the registered model/tokenizer fields",
            observed="the stable host projection differs",
            json_pointer="",
        ))
    return diagnostics


def _identity_diagnostics(
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
) -> list[dict[str, Any]]:
    policy = plan["decision_policy"]
    mode = policy["mode"]
    tokenizer_change = policy["token_policy"] == "bytes_only_if_changed"
    direct_fields = set(_DIRECT_IDENTITY_FIELDS)
    if tokenizer_change:
        direct_fields.add("tokenizer_pricing_hash")
    allow_bridge_judge = policy["judge_policy"] == "bridge_required_if_changed"
    if mode == "bridge":
        apparatus_fields = set(policy["apparatus_change_fields"])
        return (
            _pair_contract_diagnostics(
                plan,
                capsules["A"],
                capsules["B"],
                allowed_identity_fields=apparatus_fields,
                require_model_change=False,
                allow_judge_change=allow_bridge_judge,
                broad_host_change="host_hash" in apparatus_fields,
                model_host_change=False,
                tokenizer_host_change=(
                    "tokenizer_pricing_hash" in apparatus_fields
                ),
            )
            + _pair_contract_diagnostics(
                plan,
                capsules["B"],
                capsules["C"],
                allowed_identity_fields=direct_fields,
                require_model_change=True,
                allow_judge_change=False,
                broad_host_change=False,
                model_host_change=True,
                tokenizer_host_change=tokenizer_change,
            )
        )
    allowed = direct_fields | (
        set(policy["apparatus_change_fields"])
        if mode == "combined"
        else set()
    )
    return _pair_contract_diagnostics(
        plan,
        capsules["A"],
        capsules["C"],
        allowed_identity_fields=allowed,
        require_model_change=True,
        allow_judge_change=False,
        broad_host_change=(
            mode == "combined" and "host_hash" in allowed
        ),
        model_host_change=True,
        tokenizer_host_change=tokenizer_change,
    )


def _policy_diagnostics(
    plan_path: Path,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    policy = plan["decision_policy"]
    metric_keys = [
        (rule["purpose"], rule["metric_id"])
        for rule in policy["metric_rules"]
    ]
    stage_purposes = [rule["purpose"] for rule in policy["stage_rules"]]
    gain_count = sum(
        rule["purpose"] == "gain_retention"
        for rule in policy["metric_rules"]
    )
    apparatus_fields = policy["apparatus_change_fields"]
    apparatus_shape_valid = (
        not apparatus_fields
        if policy["mode"] == "direct"
        else bool(apparatus_fields)
    )
    if (
        len(metric_keys) == len(set(metric_keys))
        and gain_count == 1
        and sorted(stage_purposes) == ["application", "loading", "routing"]
        and apparatus_shape_valid
    ):
        return []
    return [plan_diagnostic(
        plan_path,
        fact_type="registration",
        reason_key="transition_policy_invalid",
        expected=(
            "one gain rule, unique metric rules, three unique stages, "
            "and mode-appropriate apparatus fields"
        ),
        observed={
            "metric_keys": metric_keys,
            "gain_count": gain_count,
            "stage_purposes": stage_purposes,
            "apparatus_change_fields": apparatus_fields,
        },
        json_pointer="/decision_policy",
        roles=(
            ["A", "B", "C"]
            if policy["mode"] == "bridge"
            else ["A", "C"]
        ),
    )]


def _check(
    check_id: str,
    diagnostics: list[dict[str, Any]],
    *,
    roles: list[str],
    failed: bool = False,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": (
            "not_evaluable" if diagnostics and not failed
            else "fail" if diagnostics
            else "pass"
        ),
        "roles": sorted({
            role for item in diagnostics for role in item["roles"]
        }) or roles,
        "diagnostic_ids": list(dict.fromkeys(
            item["diagnostic_id"] for item in diagnostics
        )),
    }


def _unique_diagnostics(
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for diagnostic in diagnostics:
        diagnostic_id = diagnostic["diagnostic_id"]
        existing = unique.get(diagnostic_id)
        if existing is not None and existing != diagnostic:
            raise ValueError(f"diagnostic ID collision: {diagnostic_id}")
        unique[diagnostic_id] = diagnostic
    return list(unique.values())


def _evidence_diagnostics(
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
) -> list[dict[str, Any]]:
    diagnostics = []
    for capsule in capsules.values():
        summary = capsule.summary
        observed = {
            "analysis_ready": summary["analysis_ready"],
            "evidence_status": summary["evidence_status"],
            "feasibility_status": summary["feasibility_status"],
            "observations_bound": capsule.observations is not None,
        }
        if observed != {
            "analysis_ready": True,
            "evidence_status": "complete",
            "feasibility_status": "feasible",
            "observations_bound": True,
        }:
            diagnostics.append(capsule_diagnostic(
                plan,
                capsule,
                "summary",
                fact_type="evidence_gap",
                reason_key="transition_cycle_evidence_incomplete",
                roles=[capsule.role],
                expected="analysis-ready, complete, feasible evidence with observations",
                observed=observed,
                json_pointer="/analysis_ready",
            ))
    return diagnostics


def _classification(
    mode: str,
    *,
    apparatus_issues: list[dict[str, Any]],
    underpowered_issues: list[dict[str, Any]],
    gate_failures: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    stages: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    by_purpose: dict[str, list[dict[str, Any]]] = {}
    for metric in metrics:
        by_purpose.setdefault(metric["purpose"], []).append(metric)
    stage_by_purpose = {item["purpose"]: item for item in stages}

    if apparatus_issues:
        return "apparatus_inconclusive", []
    protected_failures = [
        item
        for item in by_purpose.get("protected_noninferiority", [])
        if item["status"] == "fail"
    ]
    if gate_failures or protected_failures:
        return (
            "safety_or_protected_interference",
            [item["metric_id"] for item in protected_failures],
        )
    if mode == "combined":
        return "combined_model_harness_drift", []
    if underpowered_issues:
        return (
            "mixed_or_underpowered",
            sorted({
                metric_id
                for item in underpowered_issues
                for metric_id in item["metric_ids"]
            }),
        )
    for purpose, classification in (
        ("routing", "routing_loss"),
        ("loading", "loading_loss"),
        ("application", "application_loss"),
    ):
        stage = stage_by_purpose[purpose]
        if stage["status"] == "fail":
            return classification, [stage["metric_id"]]

    interference = [
        item
        for item in by_purpose.get("interference", [])
        if item["status"] == "fail"
    ]
    if interference:
        return "skill_interference", [
            item["metric_id"] for item in interference
        ]
    gain = by_purpose["gain_retention"][0]
    if gain["status"] == "pass":
        return "retained_specialized_value", [gain["metric_id"]]
    native = [
        item
        for item in by_purpose.get("native_capability", [])
        if item["status"] == "pass"
    ]
    if native:
        return "native_capability_absorption_candidate", sorted({
            gain["metric_id"],
            *(item["metric_id"] for item in native),
        })
    specialization = by_purpose.get("specialization", [])
    if specialization and any(
        item["status"] == "fail" for item in specialization
    ):
        return "insufficient_specialization", [
            item["metric_id"]
            for item in specialization
            if item["status"] == "fail"
        ]
    if gain["status"] == "fail":
        return "stable_no_incremental_value", [gain["metric_id"]]
    return "mixed_or_underpowered", [gain["metric_id"]]


def evaluate_transition(
    plan_path: Path,
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    policy = plan["decision_policy"]
    mode = policy["mode"]
    reference = capsules["B"] if mode == "bridge" else capsules["A"]
    later = capsules["C"]
    roles = sorted(capsules)

    policy_issues = _policy_diagnostics(plan_path, plan)
    identity_issues = _identity_diagnostics(plan, capsules)
    evidence_issues = _evidence_diagnostics(plan, capsules)
    metrics: list[dict[str, Any]] = []
    metric_issues: list[dict[str, Any]] = []
    metric_failures: list[dict[str, Any]] = []
    for rule in policy["metric_rules"]:
        metric, diagnostics = metric_result(
            plan,
            reference,
            later,
            rule,
        )
        metrics.append(metric)
        (
            metric_issues
            if metric["status"] == "not_evaluable"
            else metric_failures
        ).extend(diagnostics)

    stages: list[dict[str, Any]] = []
    stage_issues: list[dict[str, Any]] = []
    stage_failures: list[dict[str, Any]] = []
    for rule in policy["stage_rules"]:
        stage, diagnostics = stage_result(plan, reference, later, rule)
        stages.append(stage)
        (
            stage_issues
            if stage["status"] == "not_evaluable"
            else stage_failures
        ).extend(diagnostics)
    gate_blocking, gate_failures = gate_diagnostics(plan, later)

    underpowered_issues = [
        item
        for item in metric_issues + stage_issues
        if item["reason_key"].endswith("_underpowered")
    ]
    apparatus_issues = (
        policy_issues
        + identity_issues
        + evidence_issues
        + gate_blocking
        + [
            item
            for item in metric_issues + stage_issues
            if item not in underpowered_issues
        ]
    )
    classification, classification_metric_ids = _classification(
        mode,
        apparatus_issues=apparatus_issues,
        underpowered_issues=underpowered_issues,
        gate_failures=gate_failures,
        metrics=metrics,
        stages=stages,
    )
    blocked_classifications = {
        "apparatus_inconclusive",
        "safety_or_protected_interference",
        "mixed_or_underpowered",
        "combined_model_harness_drift",
    }
    pre_registered = plan["registration"]["mode"] == "pre_registered"
    eligible = bool(
        classification not in blocked_classifications
        and pre_registered
        and plan["claim_scope"] == "transition_retention"
    )
    authority_issues: list[dict[str, Any]] = []
    if classification not in blocked_classifications and not eligible:
        authority_issues.append(plan_diagnostic(
            plan_path,
            fact_type="authority",
            reason_key="transition_authority_blocked",
            expected="a pre-registered transition_retention claim",
            observed={
                "registration": plan["registration"]["mode"],
                "claim_scope": plan["claim_scope"],
            },
            json_pointer="/registration",
            roles=roles,
        ))

    checks = [
        _check("transition-policy", policy_issues, roles=roles),
        _check("transition-identity", identity_issues, roles=roles),
        _check("transition-evidence", evidence_issues, roles=roles),
        _check(
            "transition-metrics",
            metric_issues or metric_failures,
            roles=roles,
            failed=bool(metric_failures and not metric_issues),
        ),
        _check(
            "transition-stages",
            stage_issues or stage_failures,
            roles=roles,
            failed=bool(stage_failures and not stage_issues),
        ),
        _check(
            "transition-required-gates",
            gate_blocking or gate_failures,
            roles=roles,
            failed=bool(gate_failures and not gate_blocking),
        ),
    ]
    diagnostics = _unique_diagnostics(
        apparatus_issues
        + underpowered_issues
        + metric_failures
        + stage_failures
        + gate_failures
        + authority_issues,
    )
    return {
        "registration_status": (
            "not_evaluable"
            if classification == "apparatus_inconclusive"
            else "declared_pre_registered" if pre_registered else "exploratory"
        ),
        "comparability_checks": checks,
        "metrics": metrics + stages,
        "result": {
            "kind": "model_transition",
            "mode": mode,
            "classification": classification,
            "classification_metric_ids": classification_metric_ids,
        },
        "authority_eligibility": "eligible" if eligible else "blocked",
        "claim_ceiling": (
            "transition_retention" if eligible else "diagnostic_only"
        ),
    }, diagnostics
