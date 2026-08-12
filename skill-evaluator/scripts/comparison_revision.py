"""Deterministic policy for one controlled Skill revision."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from comparison_contract import CycleCapsule, make_diagnostic
from comparison_revision_contract import (
    artifact_source,
    capsule_diagnostic,
    estimand,
    evidence_diagnostics,
    failure_index_complete,
    identity_diagnostics,
    plan_diagnostic,
    same,
)


def _target_diagnostics(
    plan: dict[str, Any],
    prior: CycleCapsule,
    candidate: CycleCapsule,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    list[str],
]:
    target = plan["decision_policy"]["target"]
    blocking: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    if prior.failure_index is None:
        blocking.append(capsule_diagnostic(
            plan,
            prior,
            "summary",
            fact_type="evidence_gap",
            reason_key="revision_prior_failure_index_missing",
            expected="the prior failure index contains every target diagnostic",
            observed="the prior failure index is absent",
            json_pointer="/representative_failure_ids",
        ))
        return blocking, residual, [], target["diagnostic_ids"]

    prior_by_id = {
        item["failure_id"]: item
        for item in prior.failure_index["failures"]
    }
    missing = [
        failure_id
        for failure_id in target["diagnostic_ids"]
        if failure_id not in prior_by_id
    ]
    selected = [
        prior_by_id[failure_id]
        for failure_id in target["diagnostic_ids"]
        if failure_id in prior_by_id
    ]
    actual_cases = sorted({
        item["case_id"] for item in selected if item["case_id"] is not None
    })
    actual_requirements = sorted({
        item["requirement_id"]
        for item in selected
        if item["requirement_id"] is not None
    })
    if (
        missing
        or actual_cases != sorted(target["case_ids"])
        or actual_requirements != sorted(target["requirement_ids"])
    ):
        path = artifact_source(plan, prior, "failure_index")
        blocking.append(make_diagnostic(
            severity="high",
            fact_type="evidence_gap",
            reason_key="revision_target_binding_invalid",
            roles=["prior"],
            expected={
                "diagnostic_ids": target["diagnostic_ids"],
                "case_ids": target["case_ids"],
                "requirement_ids": target["requirement_ids"],
            },
            observed={
                "missing_diagnostic_ids": missing,
                "case_ids": actual_cases,
                "requirement_ids": actual_requirements,
            },
            locator_artifact=path,
            json_pointer="/failures",
            source_ref=path,
            case_ids=target["case_ids"],
            requirement_ids=target["requirement_ids"],
        ))
        return blocking, residual, [], target["diagnostic_ids"]

    if not failure_index_complete(candidate):
        required = plan["decision_policy"]["require_candidate_failure_index"]
        blocking.append(capsule_diagnostic(
            plan,
            candidate,
            "summary",
            fact_type="evidence_gap",
            reason_key=(
                "revision_candidate_failure_index_incomplete"
                if required
                else "revision_target_closure_unverifiable"
            ),
            expected=(
                "the required candidate failure index is complete"
                if required
                else "complete candidate failure evidence is bound before claiming closure"
            ),
            observed=(
                "missing"
                if candidate.failure_index is None
                else {
                    "truncated": candidate.failure_index["truncated"],
                    "omitted_count": candidate.failure_index["omitted_count"],
                }
            ),
            json_pointer="/representative_failure_ids",
        ))
        return blocking, residual, [], target["diagnostic_ids"]

    assert candidate.failure_index is not None

    def signature(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            item["family"],
            item["code"],
            item["reason_key"],
            item["case_id"],
            item["requirement_id"],
            item["gate_id"],
            item["dimension"],
        )
    target_signatures = {signature(item) for item in selected}
    candidate_signatures = {
        signature(item) for item in candidate.failure_index["failures"]
    }
    remaining_ids = [
        item["failure_id"]
        for item in selected
        if signature(item) in candidate_signatures
    ]
    closed_ids = [
        item["failure_id"]
        for item in selected
        if signature(item) not in candidate_signatures
    ]
    residual_items = [
        item
        for item in candidate.failure_index["failures"]
        if signature(item) in target_signatures
    ]
    if residual_items:
        path = artifact_source(plan, candidate, "failure_index")
        residual.append(make_diagnostic(
            severity="high",
            fact_type="revision_closure",
            reason_key="revision_target_failure_remains",
            roles=["prior", "candidate"],
            expected="the declared prior failure signatures are absent",
            observed=[item["failure_id"] for item in residual_items],
            locator_artifact=path,
            json_pointer="/failures",
            source_ref=path,
            case_ids=target["case_ids"],
            requirement_ids=target["requirement_ids"],
        ))
    return blocking, residual, closed_ids, remaining_ids


def _metric_result(
    plan: dict[str, Any],
    prior: CycleCapsule,
    candidate: CycleCapsule,
    rule: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metric_id = rule["metric_id"]
    prior_metric = prior.summary["paired_metrics"].get(metric_id)
    candidate_metric = candidate.summary["paired_metrics"].get(metric_id)
    priorestimand = estimand(prior.spec, metric_id)
    candidateestimand = estimand(candidate.spec, metric_id)
    problems: list[str] = []
    if prior_metric is None or candidate_metric is None:
        problems.append("metric is absent from one or both summaries")
    if priorestimand is None or candidateestimand is None:
        problems.append("estimand is absent or duplicated")
    elif not same(priorestimand, candidateestimand):
        problems.append("estimand definitions differ")
    elif rule["direction"] != priorestimand["direction"]:
        problems.append("policy direction differs from the estimand")
    if not same(
        {
            field: prior.spec["analysis"][field]
            for field in (
                "confidence_level",
                "bootstrap_iterations",
                "resampling_unit",
            )
        },
        {
            field: candidate.spec["analysis"][field]
            for field in (
                "confidence_level",
                "bootstrap_iterations",
                "resampling_unit",
            )
        },
    ):
        problems.append("confidence or bootstrap policy differs")

    prior_cases: set[str] = set()
    candidate_cases: set[str] = set()
    if prior_metric is not None and candidate_metric is not None:
        if (
            prior_metric["direction"] != rule["direction"]
            or candidate_metric["direction"] != rule["direction"]
            or prior_metric["effect"] != candidate_metric["effect"]
        ):
            problems.append("metric direction or effect differs")
        for label, metric in (
            ("prior", prior_metric),
            ("candidate", candidate_metric),
        ):
            if metric["status"] in {"not_evaluable", "inconclusive_ceiling"}:
                problems.append(f"{label} metric is not evaluable")
            if not all(
                isinstance(metric[field], (int, float))
                and not isinstance(metric[field], bool)
                for field in ("point", "lower", "upper")
            ):
                problems.append(f"{label} metric lacks numeric bounds")
            if metric["case_count"] != len(metric["case_differences"]):
                problems.append(f"{label} metric case count is inconsistent")
        prior_cases = set(prior_metric["case_differences"])
        candidate_cases = set(candidate_metric["case_differences"])
        prior_plan_cases = {
            entry["case_id"]
            for entry in prior.execution_plan["entries"]
            if entry["disposition"] == "execute"
        }
        candidate_plan_cases = {
            entry["case_id"]
            for entry in candidate.execution_plan["entries"]
            if entry["disposition"] == "execute"
        }
        if prior_cases != candidate_cases:
            problems.append("distinct case sets differ")
        if (
            not prior_cases <= prior_plan_cases
            or not candidate_cases <= candidate_plan_cases
        ):
            problems.append("metric evidence names a case outside the execution plan")
        if not set(plan["decision_policy"]["target"]["case_ids"]) <= prior_cases:
            problems.append("a target case is absent from metric evidence")
        if len(prior_cases) < plan["decision_policy"]["minimum_distinct_cases"]:
            problems.append("distinct case support is below the frozen minimum")

    diagnostics: list[dict[str, Any]] = []
    if problems:
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "summary",
            fact_type="evidence_gap",
            reason_key="revision_metric_not_evaluable",
            expected="comparable bounded metric evidence with sufficient distinct cases",
            observed=problems,
            json_pointer=f"/paired_metrics/{metric_id}",
            case_ids=sorted(prior_cases | candidate_cases),
            metric_ids=[metric_id],
        ))
        status = "not_evaluable"
        point = lower = upper = None
    else:
        assert prior_metric is not None and candidate_metric is not None
        point = candidate_metric["point"] - prior_metric["point"]
        lower = candidate_metric["lower"] - prior_metric["upper"]
        upper = candidate_metric["upper"] - prior_metric["lower"]
        threshold = (
            rule["margin"]
            if rule["purpose"] == "target_improvement"
            else -rule["margin"]
        )
        status = "pass" if lower >= threshold else "fail"
        if status == "fail":
            diagnostics.append(capsule_diagnostic(
                plan,
                candidate,
                "summary",
                fact_type="metric",
                reason_key="revision_metric_margin_not_met",
                expected=f"conservative lower delta >= {threshold}",
                observed=lower,
                json_pointer=f"/paired_metrics/{metric_id}",
                case_ids=sorted(prior_cases),
                metric_ids=[metric_id],
            ))
    return {
        "metric_id": metric_id,
        "purpose": rule["purpose"],
        "reference_role": "prior",
        "later_role": "candidate",
        "status": status,
        "direction": rule["direction"],
        "point": point,
        "lower": lower,
        "upper": upper,
        "gain_retention": None,
        "distinct_case_count": len(prior_cases & candidate_cases),
        "diagnostic_ids": [item["diagnostic_id"] for item in diagnostics],
    }, diagnostics


def _gate_diagnostics(
    plan: dict[str, Any],
    candidate: CycleCapsule,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    policy = plan["decision_policy"]
    blocking: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    declared = {
        axis: [
            gate["gate_id"]
            for gate in candidate.spec["hard_gates"]
            if gate["required"] is True and gate["decision_axis"] == axis
        ]
        for axis in policy["required_axes"]
    }
    missing_axes = [axis for axis, gate_ids in declared.items() if not gate_ids]
    if missing_axes:
        blocking.append(capsule_diagnostic(
            plan,
            candidate,
            "spec",
            fact_type="evidence_gap",
            reason_key="revision_required_gate_undeclared",
            expected=policy["required_axes"],
            observed=missing_axes,
            json_pointer="/hard_gates",
        ))
        return blocking, failures
    if not failure_index_complete(candidate):
        blocking.append(capsule_diagnostic(
            plan,
            candidate,
            "summary",
            fact_type="evidence_gap",
            reason_key="revision_gate_evidence_incomplete",
            expected="a complete candidate failure index for required gates",
            observed="the failure index is missing or truncated",
            json_pointer="/representative_failure_ids",
        ))
        return blocking, failures

    assert candidate.failure_index is not None
    required_gate_ids = {
        gate_id for gate_ids in declared.values() for gate_id in gate_ids
    }
    failed_items = [
        item
        for item in candidate.failure_index["failures"]
        if item["gate_id"] in required_gate_ids
    ]
    if failed_items:
        path = artifact_source(plan, candidate, "failure_index")
        failures.append(make_diagnostic(
            severity="critical",
            fact_type="gate",
            reason_key="revision_required_gate_failed",
            roles=["candidate"],
            expected="every frozen gate on each required decision axis passes",
            observed=[item["failure_id"] for item in failed_items],
            locator_artifact=path,
            json_pointer="/failures",
            source_ref=path,
        ))
    return blocking, failures


def _policy_diagnostics(
    plan_path: Path,
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    rules = plan["decision_policy"]["metric_rules"]
    target_count = sum(
        rule["purpose"] == "target_improvement" for rule in rules
    )
    protected_count = sum(
        rule["purpose"] == "protected_noninferiority" for rule in rules
    )
    metric_ids = [rule["metric_id"] for rule in rules]
    if (
        target_count == 1
        and protected_count >= 1
        and len(metric_ids) == len(set(metric_ids))
    ):
        return []
    return [plan_diagnostic(
        plan_path,
        fact_type="registration",
        reason_key="revision_metric_policy_invalid",
        expected="one target metric, at least one protected metric, and unique metric IDs",
        observed={
            "target_count": target_count,
            "protected_count": protected_count,
            "metric_ids": metric_ids,
        },
        json_pointer="/decision_policy/metric_rules",
    )]


def _check(
    check_id: str,
    diagnostics: list[dict[str, Any]],
    *,
    failed: bool = False,
) -> dict[str, Any]:
    diagnostic_ids = list(dict.fromkeys(
        item["diagnostic_id"] for item in diagnostics
    ))
    return {
        "check_id": check_id,
        "status": (
            "not_evaluable" if diagnostics and not failed
            else "fail" if diagnostics
            else "pass"
        ),
        "roles": ["prior", "candidate"],
        "diagnostic_ids": diagnostic_ids,
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


def evaluate_revision(
    plan_path: Path,
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prior = capsules["prior"]
    candidate = capsules["candidate"]
    policy_diagnostics = _policy_diagnostics(plan_path, plan)
    identity_issues = identity_diagnostics(plan, prior, candidate)
    evidence_issues = evidence_diagnostics(plan, (prior, candidate))
    (
        target_blocking,
        target_residual,
        closed_target_ids,
        remaining_target_ids,
    ) = _target_diagnostics(plan, prior, candidate)

    metrics: list[dict[str, Any]] = []
    metric_blocking: list[dict[str, Any]] = []
    metric_failures: list[dict[str, Any]] = []
    for rule in plan["decision_policy"]["metric_rules"]:
        metric, diagnostics = _metric_result(plan, prior, candidate, rule)
        metrics.append(metric)
        (
            metric_blocking
            if metric["status"] == "not_evaluable"
            else metric_failures
        ).extend(diagnostics)
    gate_blocking, gate_failures = _gate_diagnostics(plan, candidate)

    blocking = (
        policy_diagnostics
        + identity_issues
        + evidence_issues
        + target_blocking
        + metric_blocking
        + gate_blocking
    )
    decision_failures = (
        target_residual
        + metric_failures
        + gate_failures
    )
    if blocking:
        status = "not_evaluable"
        closed_target_ids = []
        remaining_target_ids = plan["decision_policy"]["target"][
            "diagnostic_ids"
        ]
    elif decision_failures:
        status = "open"
    else:
        status = "closed"

    pre_registered = plan["registration"]["mode"] == "pre_registered"
    eligible = bool(
        status == "closed"
        and pre_registered
        and plan["claim_scope"] == "revision_closure"
    )
    authority_diagnostics: list[dict[str, Any]] = []
    if status == "closed" and not eligible:
        authority_diagnostics.append(plan_diagnostic(
            plan_path,
            fact_type="authority",
            reason_key="revision_authority_blocked",
            expected="a pre-registered revision_closure claim after closed gates",
            observed={
                "registration": plan["registration"]["mode"],
                "claim_scope": plan["claim_scope"],
            },
            json_pointer="/registration",
        ))

    checks = [
        _check("revision-policy", policy_diagnostics),
        _check("revision-identity", identity_issues),
        _check("revision-evidence", evidence_issues),
        _check(
            "revision-target-closure",
            target_blocking or target_residual,
            failed=bool(target_residual and not target_blocking),
        ),
        _check(
            "revision-metrics",
            metric_blocking or metric_failures,
            failed=bool(metric_failures and not metric_blocking),
        ),
        _check(
            "revision-required-gates",
            gate_blocking or gate_failures,
            failed=bool(gate_failures and not gate_blocking),
        ),
    ]
    diagnostics = _unique_diagnostics(
        blocking + decision_failures + authority_diagnostics,
    )
    return {
        "registration_status": (
            "not_evaluable"
            if status == "not_evaluable"
            else "declared_pre_registered" if pre_registered else "exploratory"
        ),
        "comparability_checks": checks,
        "metrics": metrics,
        "result": {
            "kind": "revision",
            "status": status,
            "target_failure_class": plan["decision_policy"]["target"][
                "failure_class"
            ],
            "closed_diagnostic_ids": sorted(closed_target_ids),
            "remaining_diagnostic_ids": sorted(remaining_target_ids),
        },
        "authority_eligibility": "eligible" if eligible else "blocked",
        "claim_ceiling": "revision_closure" if eligible else "diagnostic_only",
    }, diagnostics
