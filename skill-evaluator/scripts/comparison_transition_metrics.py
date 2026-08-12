"""Metric, stage, and gate evidence for model-transition comparisons."""

from __future__ import annotations

from typing import Any

from comparison_contract import CycleCapsule, make_diagnostic
from comparison_revision_contract import (
    artifact_source,
    capsule_diagnostic,
    estimand,
    failure_index_complete,
    same,
)


def _observation_metric(
    capsule: CycleCapsule,
    metric_id: str,
) -> dict[str, Any] | None:
    if capsule.observations is None:
        return None
    matches = [
        item
        for item in capsule.observations["metrics"]
        if item["metric_id"] == metric_id
    ]
    return matches[0] if len(matches) == 1 else None


def _token_scaled(observation: dict[str, Any] | None) -> bool:
    if observation is None:
        return False
    scale = observation["scale"]
    return any(
        "token" in scale[field].lower()
        for field in ("raw", "reported", "normalization")
    )


def metric_result(
    plan: dict[str, Any],
    reference: CycleCapsule,
    later: CycleCapsule,
    rule: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metric_id = rule["metric_id"]
    purpose = rule["purpose"]
    if purpose == "native_capability":
        return _native_metric_result(plan, reference, later, rule)
    reference_metric = reference.summary["paired_metrics"].get(metric_id)
    later_metric = later.summary["paired_metrics"].get(metric_id)
    reference_estimand = estimand(reference.spec, metric_id)
    later_estimand = estimand(later.spec, metric_id)
    problems: list[str] = []
    if reference_metric is None or later_metric is None:
        problems.append("metric is absent from one or both summaries")
    if reference_estimand is None or later_estimand is None:
        problems.append("estimand is absent or duplicated")
    elif not same(reference_estimand, later_estimand):
        problems.append("estimand definitions differ")
    elif reference_estimand["direction"] != rule["direction"]:
        problems.append("policy direction differs from the estimand")

    reference_cases: set[str] = set()
    later_cases: set[str] = set()
    if reference_metric is not None and later_metric is not None:
        if (
            reference_metric["direction"] != rule["direction"]
            or later_metric["direction"] != rule["direction"]
            or reference_metric["effect"] != later_metric["effect"]
        ):
            problems.append("metric direction or effect differs")
        for label, metric in (
            (reference.role, reference_metric),
            (later.role, later_metric),
        ):
            if metric["status"] in {"not_evaluable", "inconclusive_ceiling"}:
                problems.append(f"{label} metric is not evaluable")
            if not all(
                isinstance(metric[field], (int, float))
                and not isinstance(metric[field], bool)
                for field in ("point", "lower", "upper")
            ):
                problems.append(f"{label} metric lacks numeric bounds")
            elif not metric["lower"] <= metric["point"] <= metric["upper"]:
                problems.append(f"{label} metric bounds are inconsistent")
            if metric["case_count"] != len(metric["case_differences"]):
                problems.append(f"{label} metric case count is inconsistent")
        reference_cases = set(reference_metric["case_differences"])
        later_cases = set(later_metric["case_differences"])
        if reference_cases != later_cases:
            problems.append("distinct case sets differ")
        minimum = plan["decision_policy"]["minimum_distinct_cases"]
        if len(reference_cases) < minimum:
            problems.append("distinct case support is below the frozen minimum")
        reference_plan_cases = {
            entry["case_id"]
            for entry in reference.execution_plan["entries"]
            if entry["disposition"] == "execute"
        }
        later_plan_cases = {
            entry["case_id"]
            for entry in later.execution_plan["entries"]
            if entry["disposition"] == "execute"
        }
        if (
            not reference_cases <= reference_plan_cases
            or not later_cases <= later_plan_cases
        ):
            problems.append("metric evidence names a case outside the execution plan")

    reference_observation = _observation_metric(reference, metric_id)
    later_observation = _observation_metric(later, metric_id)
    if reference_observation is None or later_observation is None:
        problems.append("comparison observations are missing the metric scale")
    elif any(
        reference_observation[field] != later_observation[field]
        for field in (
            "direction",
            "effect",
            "scale",
            "comparator_treatment_id",
            "candidate_treatment_id",
        )
    ):
        problems.append("comparison observation contracts differ")
    tokenizer_changed = (
        any(
            reference.execution_plan["execution_profile"][field]
            != later.execution_plan["execution_profile"][field]
            for field in ("tokenizer_id", "pricing_id")
        )
    )
    if (
        tokenizer_changed
        and plan["decision_policy"]["token_policy"] == "bytes_only_if_changed"
        and (
            _token_scaled(reference_observation)
            or _token_scaled(later_observation)
        )
    ):
        problems.append("token-scaled metric is not comparable across tokenizers")

    diagnostics: list[dict[str, Any]] = []
    if problems:
        underpowered = problems == [
            "distinct case support is below the frozen minimum",
        ]
        diagnostics.append(capsule_diagnostic(
            plan,
            later,
            "summary",
            fact_type="evidence_gap",
            reason_key=(
                "transition_metric_underpowered"
                if underpowered
                else "transition_metric_not_evaluable"
            ),
            roles=[reference.role, later.role],
            expected="comparable metric evidence with sufficient distinct cases",
            observed=problems,
            json_pointer=f"/paired_metrics/{metric_id}",
            case_ids=sorted(reference_cases | later_cases),
            metric_ids=[metric_id],
        ))
        status = "not_evaluable"
        point = lower = upper = retention = None
    else:
        assert reference_metric is not None and later_metric is not None
        point = later_metric["point"] - reference_metric["point"]
        lower = later_metric["lower"] - reference_metric["upper"]
        upper = later_metric["upper"] - reference_metric["lower"]
        retention = None
        if purpose == "gain_retention":
            if reference_metric["point"] <= 0:
                status = "not_evaluable"
                diagnostics.append(capsule_diagnostic(
                    plan,
                    reference,
                    "summary",
                    fact_type="evidence_gap",
                    reason_key="transition_retention_reference_nonpositive",
                    roles=[reference.role, later.role],
                    expected="a positive reference gain before computing retention",
                    observed=reference_metric["point"],
                    json_pointer=f"/paired_metrics/{metric_id}/point",
                    metric_ids=[metric_id],
                ))
            else:
                retention = later_metric["lower"] / reference_metric["point"]
                status = "pass" if retention >= rule["threshold"] else "fail"
        elif purpose in {"protected_noninferiority", "interference"}:
            status = "pass" if lower >= -rule["threshold"] else "fail"
        else:
            status = (
                "pass"
                if later_metric["lower"] >= rule["threshold"]
                else "fail"
            )
        if status == "fail":
            diagnostics.append(capsule_diagnostic(
                plan,
                later,
                "summary",
                fact_type="metric",
                reason_key="transition_metric_threshold_not_met",
                roles=[reference.role, later.role],
                expected={"purpose": purpose, "threshold": rule["threshold"]},
                observed={"lower_delta": lower, "retention": retention},
                json_pointer=f"/paired_metrics/{metric_id}",
                case_ids=sorted(reference_cases),
                metric_ids=[metric_id],
            ))
    return {
        "metric_id": metric_id,
        "purpose": purpose,
        "reference_role": reference.role,
        "later_role": later.role,
        "status": status,
        "direction": rule["direction"],
        "point": point,
        "lower": lower,
        "upper": upper,
        "gain_retention": retention,
        "distinct_case_count": len(reference_cases & later_cases),
        "diagnostic_ids": [item["diagnostic_id"] for item in diagnostics],
    }, diagnostics


def _native_metric_result(
    plan: dict[str, Any],
    reference: CycleCapsule,
    later: CycleCapsule,
    rule: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metric_id = rule["metric_id"]
    reference_metric = _observation_metric(reference, metric_id)
    later_metric = _observation_metric(later, metric_id)
    problems: list[str] = []
    if reference_metric is None or later_metric is None:
        problems.append("comparison observations are missing the metric")
        reference_values = later_values = {}
    else:
        if (
            reference_metric["status"] != "complete"
            or later_metric["status"] != "complete"
            or reference_metric["direction"] != rule["direction"]
            or later_metric["direction"] != rule["direction"]
        ):
            problems.append("observation status or direction is incompatible")
        if any(
            reference_metric[field] != later_metric[field]
            for field in (
                "effect",
                "scale",
                "comparator_treatment_id",
                "candidate_treatment_id",
            )
        ):
            problems.append("observation contracts differ")
        reference_values = {
            item["case_id"]: item for item in reference_metric["values"]
        }
        later_values = {
            item["case_id"]: item for item in later_metric["values"]
        }
        if (
            len(reference_values) != len(reference_metric["values"])
            or len(later_values) != len(later_metric["values"])
        ):
            problems.append("observation case IDs are duplicated")
        if set(reference_values) != set(later_values):
            problems.append("observation case sets differ")
        reference_plan_cases = {
            entry["case_id"]
            for entry in reference.execution_plan["entries"]
            if entry["disposition"] == "execute"
        }
        later_plan_cases = {
            entry["case_id"]
            for entry in later.execution_plan["entries"]
            if entry["disposition"] == "execute"
        }
        if (
            not set(reference_values) <= reference_plan_cases
            or not set(later_values) <= later_plan_cases
        ):
            problems.append(
                "observation evidence names a case outside the execution plan"
            )
        if len(reference_values) < plan["decision_policy"]["minimum_distinct_cases"]:
            problems.append("native-capability support is below the frozen minimum")
        tokenizer_changed = (
            any(
                reference.execution_plan["execution_profile"][field]
                != later.execution_plan["execution_profile"][field]
                for field in ("tokenizer_id", "pricing_id")
            )
        )
        if (
            tokenizer_changed
            and plan["decision_policy"]["token_policy"]
            == "bytes_only_if_changed"
            and (_token_scaled(reference_metric) or _token_scaled(later_metric))
        ):
            problems.append(
                "token-scaled metric is not comparable across tokenizers"
            )

    diagnostics: list[dict[str, Any]] = []
    if problems:
        point = None
        status = "not_evaluable"
        underpowered = problems == [
            "native-capability support is below the frozen minimum",
        ]
        diagnostics.append(capsule_diagnostic(
            plan,
            later,
            "observations",
            fact_type="evidence_gap",
            reason_key=(
                "transition_native_capability_underpowered"
                if underpowered
                else "transition_native_capability_not_evaluable"
            ),
            roles=[reference.role, later.role],
            expected="complete absolute treatment observations on identical cases",
            observed=problems,
            json_pointer=f"/metrics/{metric_id}",
            case_ids=sorted(set(reference_values) | set(later_values)),
            metric_ids=[metric_id],
        ))
    else:
        case_ids = sorted(reference_values)
        deltas = []
        for case_id in case_ids:
            target_native = later_values[case_id]["comparator_value"]
            reference_skill = reference_values[case_id]["candidate_value"]
            deltas.append(
                target_native - reference_skill
                if rule["direction"] == "higher_is_better"
                else reference_skill - target_native
            )
        point = sum(deltas) / len(deltas)
        status = "pass" if point >= -rule["threshold"] else "fail"
        if status == "fail":
            diagnostics.append(capsule_diagnostic(
                plan,
                later,
                "observations",
                fact_type="metric",
                reason_key="transition_native_capability_threshold_not_met",
                roles=[reference.role, later.role],
                expected=(
                    "direction-normalized target native capability minus "
                    f"reference skill capability >= {-rule['threshold']}"
                ),
                observed=point,
                json_pointer=f"/metrics/{metric_id}/values",
                case_ids=case_ids,
                metric_ids=[metric_id],
            ))
    case_count = len(set(reference_values) & set(later_values))
    return {
        "metric_id": metric_id,
        "purpose": "native_capability",
        "reference_role": reference.role,
        "later_role": later.role,
        "status": status,
        "direction": rule["direction"],
        "point": point,
        "lower": point,
        "upper": point,
        "gain_retention": None,
        "distinct_case_count": case_count,
        "diagnostic_ids": [item["diagnostic_id"] for item in diagnostics],
    }, diagnostics


def stage_result(
    plan: dict[str, Any],
    reference: CycleCapsule,
    later: CycleCapsule,
    rule: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    def selected(capsule: CycleCapsule) -> list[dict[str, Any]]:
        return [
            item
            for item in capsule.summary["stage_summaries"]
            if item["surface"] == rule["surface"]
            and item["stage"] == rule["stage"]
        ]

    reference_items = selected(reference)
    later_items = selected(later)
    problems = []
    if len(reference_items) != 1 or len(later_items) != 1:
        problems.append("the stage summary is absent or duplicated")
        reference_item = later_item = None
    else:
        reference_item = reference_items[0]
        later_item = later_items[0]
        for label, item in (
            (reference.role, reference_item),
            (later.role, later_item),
        ):
            if not 0 <= item["passed"] <= item["reached"] <= item["eligible"]:
                problems.append(f"{label} stage counts are inconsistent")
            if item["status"] in {
                "not_reached_due_to_apparatus",
                "unsupported",
                "not_evaluable",
                "not_applicable",
            }:
                problems.append(f"{label} stage evidence is not comparable")
        if reference_item["passed"] <= 0:
            problems.append("reference passed count is not positive")
        if min(reference_item["eligible"], later_item["eligible"]) < plan[
            "decision_policy"
        ]["minimum_distinct_cases"]:
            problems.append("stage support is below the frozen minimum")

    diagnostics: list[dict[str, Any]] = []
    if problems:
        point = retention = None
        status = "not_evaluable"
        underpowered = problems == [
            "stage support is below the frozen minimum",
        ]
        diagnostics.append(capsule_diagnostic(
            plan,
            later,
            "summary",
            fact_type="evidence_gap",
            reason_key=(
                "transition_stage_underpowered"
                if underpowered
                else "transition_stage_not_evaluable"
            ),
            roles=[reference.role, later.role],
            expected="one supported stage summary per role",
            observed=problems,
            json_pointer="/stage_summaries",
            metric_ids=[f"stage-{rule['purpose']}"],
        ))
        case_count = 0
    else:
        assert reference_item is not None and later_item is not None
        reference_rate = (
            reference_item["passed"] / reference_item["eligible"]
        )
        later_rate = later_item["passed"] / later_item["eligible"]
        point = later_rate - reference_rate
        retention = later_rate / reference_rate
        status = (
            "pass"
            if retention >= rule["minimum_retention"]
            else "fail"
        )
        case_count = min(
            reference_item["eligible"],
            later_item["eligible"],
        )
        if status == "fail":
            diagnostics.append(capsule_diagnostic(
                plan,
                later,
                "summary",
                fact_type="metric",
                reason_key=f"transition_{rule['purpose']}_retention_failed",
                roles=[reference.role, later.role],
                expected=f"stage retention >= {rule['minimum_retention']}",
                observed=retention,
                json_pointer="/stage_summaries",
                metric_ids=[f"stage-{rule['purpose']}"],
            ))
    return {
        "metric_id": f"stage-{rule['purpose']}",
        "purpose": rule["purpose"],
        "reference_role": reference.role,
        "later_role": later.role,
        "status": status,
        "direction": "higher_is_better",
        "point": point,
        "lower": point,
        "upper": point,
        "gain_retention": retention,
        "distinct_case_count": case_count,
        "diagnostic_ids": [item["diagnostic_id"] for item in diagnostics],
    }, diagnostics


def gate_diagnostics(
    plan: dict[str, Any],
    candidate: CycleCapsule,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    required_axes = plan["decision_policy"]["required_axes"]
    gate_ids = {
        gate["gate_id"]
        for gate in candidate.spec["hard_gates"]
        if gate["required"] is True and gate["decision_axis"] in required_axes
    }
    declared_axes = {
        gate["decision_axis"]
        for gate in candidate.spec["hard_gates"]
        if gate["required"] is True and gate["decision_axis"] in required_axes
    }
    blocking: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if declared_axes != set(required_axes) or not failure_index_complete(
        candidate,
    ):
        blocking.append(capsule_diagnostic(
            plan,
            candidate,
            "summary",
            fact_type="evidence_gap",
            reason_key="transition_gate_evidence_incomplete",
            roles=[candidate.role],
            expected={
                "required_axes": required_axes,
                "complete_failure_index": True,
            },
            observed={
                "declared_axes": sorted(declared_axes),
                "complete_failure_index": failure_index_complete(candidate),
            },
            json_pointer="/representative_failure_ids",
        ))
        return blocking, failures
    assert candidate.failure_index is not None
    failed_items = [
        item
        for item in candidate.failure_index["failures"]
        if item["gate_id"] in gate_ids
    ]
    if failed_items:
        path = artifact_source(plan, candidate, "failure_index")
        failures.append(make_diagnostic(
            severity="critical",
            fact_type="gate",
            reason_key="transition_required_gate_failed",
            roles=[candidate.role],
            expected="every frozen required gate passes",
            observed=[item["failure_id"] for item in failed_items],
            locator_artifact=path,
            json_pointer="/failures",
            source_ref=path,
        ))
    return blocking, failures
