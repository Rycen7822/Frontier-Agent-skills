#!/usr/bin/env python3
"""Evaluate a preregistered paired case-level Bundle comparison v4."""

from __future__ import annotations

import argparse
from hashlib import sha256
import math
from pathlib import Path
import random
import sys
from typing import Any

sys.dont_write_bytecode = True

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "skill-evaluator/scripts"))

from comparison_contract import CycleCapsule, ROLE_ORDER, load_cycle_capsules  # noqa: E402
from comparison_revision import (  # noqa: E402
    _check,
    _gate_diagnostics,
    _policy_diagnostics,
    _unique_diagnostics,
)
from comparison_revision_contract import (  # noqa: E402
    capsule_diagnostic,
    estimand,
    evidence_diagnostics,
    identity_diagnostics,
    plan_diagnostic,
    same,
)
from evidence_io import (  # noqa: E402
    canonical_json_bytes,
    normalize_relative_path,
    resolve_contained_path,
)
from _model_evolution_comparison_v4_contract import (  # noqa: E402
    ContractError,
    commit_outputs,
    load_plan,
)


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _seed(policy_bytes: bytes, case_ids: list[str]) -> int:
    domain = b"frontier-confirmatory-bootstrap-v1"
    parts = [policy_bytes, canonical_json_bytes(case_ids)]
    payload = domain + b"".join(
        len(part).to_bytes(8, "big") + part for part in parts
    )
    return int.from_bytes(sha256(payload).digest()[:8], "big")


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * probability)]


def _absolute_decision(metric: dict[str, Any], threshold: float) -> str:
    if not all(_finite(metric.get(field)) for field in ("point", "lower", "upper")):
        return "not_evaluable"
    if metric["direction"] == "higher_is_better":
        if metric["lower"] >= threshold:
            return "pass"
        if metric["upper"] < threshold:
            return "fail"
    else:
        if metric["upper"] <= threshold:
            return "pass"
        if metric["lower"] > threshold:
            return "fail"
    return "inconclusive"


def metric_result(
    plan: dict[str, Any],
    prior: CycleCapsule,
    candidate: CycleCapsule,
    rule: dict[str, Any],
    *,
    policy_bytes: bytes | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metric_id = rule["metric_id"]
    prior_metric = prior.summary["paired_metrics"].get(metric_id)
    candidate_metric = candidate.summary["paired_metrics"].get(metric_id)
    prior_estimand = estimand(prior.spec, metric_id)
    candidate_estimand = estimand(candidate.spec, metric_id)
    problems: list[str] = []
    case_ids: list[str] = []
    if prior_metric is None or candidate_metric is None:
        problems.append("metric is absent from one or both summaries")
    if prior_estimand is None or candidate_estimand is None:
        problems.append("estimand is absent or duplicated")
    elif not same(prior_estimand, candidate_estimand):
        problems.append("estimand definitions differ")
    elif rule["direction"] != prior_estimand["direction"]:
        problems.append("policy direction differs from the estimand")

    fields = ("confidence_level", "bootstrap_iterations", "resampling_unit")
    if not same(
        {field: prior.spec["analysis"][field] for field in fields},
        {field: candidate.spec["analysis"][field] for field in fields},
    ):
        problems.append("analysis strategies differ")
    estimator = plan["decision_policy"]["estimator"]
    if (
        prior.spec["analysis"]["resampling_unit"] != estimator["resampling_unit"]
        or prior.spec["analysis"]["confidence_level"] != estimator["confidence_level"]
        or prior.spec["analysis"]["bootstrap_iterations"] != estimator["bootstrap_iterations"]
    ):
        problems.append("analysis strategy differs from the registered estimator")

    if prior_metric is not None and candidate_metric is not None:
        for label, metric in (("prior", prior_metric), ("candidate", candidate_metric)):
            if not all(_finite(metric.get(field)) for field in ("point", "lower", "upper")):
                problems.append(f"{label} metric lacks finite numeric bounds")
            if metric.get("case_count") != len(metric.get("case_differences", {})):
                problems.append(f"{label} metric case map is incomplete")
            if metric.get("direction") != rule["direction"]:
                problems.append(f"{label} metric direction differs")
        prior_cases = set(prior_metric.get("case_differences", {}))
        candidate_cases = set(candidate_metric.get("case_differences", {}))
        if prior_cases != candidate_cases:
            problems.append("confirmatory case sets differ")
        case_ids = sorted(prior_cases & candidate_cases)
        if len(case_ids) < plan["decision_policy"]["minimum_distinct_cases"]:
            problems.append("distinct case support is below the frozen minimum")
        for capsule, cases, label in (
            (prior, prior_cases, "prior"),
            (candidate, candidate_cases, "candidate"),
        ):
            planned = {
                row["case_id"]
                for row in capsule.execution_plan["entries"]
                if row["disposition"] == "execute"
            }
            if cases != planned:
                problems.append(f"{label} case map differs from its execution plan")

    diagnostics: list[dict[str, Any]] = []
    seed_source = policy_bytes or canonical_json_bytes(plan["decision_policy"])
    estimator_record = {**estimator, "seed": _seed(seed_source, case_ids)}
    if problems:
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "summary",
            fact_type="evidence_gap",
            reason_key="revision_v4_metric_incomplete",
            expected="complete paired case evidence under the registered estimator",
            observed=problems,
            json_pointer=f"/paired_metrics/{metric_id}",
            case_ids=case_ids,
            metric_ids=[metric_id],
        ))
        point = decision_lower = diagnostic_upper = None
        revision_decision = "not_evaluable"
    else:
        assert prior_metric is not None and candidate_metric is not None
        sign = 1.0 if rule["direction"] == "higher_is_better" else -1.0
        deltas = [
            sign * (
                candidate_metric["case_differences"][case_id]
                - prior_metric["case_differences"][case_id]
            )
            for case_id in case_ids
        ]
        point = sum(deltas) / len(deltas)
        generator = random.Random(estimator_record["seed"])
        draws = [
            sum(generator.choice(deltas) for _ in deltas) / len(deltas)
            for _ in range(estimator["bootstrap_iterations"])
        ]
        decision_lower = _percentile(draws, estimator["decision_lower_percentile"])
        diagnostic_upper = _percentile(draws, estimator["diagnostic_upper_percentile"])
        revision_decision = "pass" if decision_lower >= -rule["margin"] else "fail"
        if revision_decision == "fail":
            diagnostics.append(capsule_diagnostic(
                plan,
                candidate,
                "summary",
                fact_type="metric",
                reason_key="revision_v4_margin_not_met",
                expected=f"paired decision lower >= {-rule['margin']}",
                observed=decision_lower,
                json_pointer=f"/paired_metrics/{metric_id}",
                case_ids=case_ids,
                metric_ids=[metric_id],
            ))

    threshold = (
        float(candidate_estimand.get("minimum_benefit", 0))
        if isinstance(candidate_estimand, dict) else 0.0
    )
    return {
        "metric_id": metric_id,
        "purpose": rule["purpose"],
        "reference_role": "prior",
        "later_role": "candidate",
        "evidence_completeness": "missing" if problems else "complete",
        "absolute_threshold_decision": (
            "not_evaluable" if candidate_metric is None
            else _absolute_decision(candidate_metric, threshold)
        ),
        "revision_decision": revision_decision,
        "direction": rule["direction"],
        "point": point,
        "decision_lower": decision_lower,
        "diagnostic_upper": diagnostic_upper,
        "margin": rule["margin"],
        "estimator": estimator_record,
        "case_ids": case_ids,
        "excluded_case_ids": [],
        "distinct_case_count": len(case_ids),
        "diagnostic_ids": [item["diagnostic_id"] for item in diagnostics],
    }, diagnostics


def evaluate(
    plan_path: Path,
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prior, candidate = capsules["prior"], capsules["candidate"]
    policy_binding = plan["decision_policy"]["registered_policy"]
    policy_relative = normalize_relative_path(
        policy_binding["path"], "registered comparison policy"
    )
    _, policy_path = resolve_contained_path(
        plan_path.parent,
        policy_relative,
        "registered comparison policy",
        kind="file",
    )
    if policy_path.is_symlink():
        raise ContractError("policy.file", "registered comparison policy is missing")
    policy_bytes = policy_path.read_bytes()
    if "sha256:" + sha256(policy_bytes).hexdigest() != policy_binding["digest"]:
        raise ContractError("policy.digest", "registered comparison policy changed")
    policy_issues = _policy_diagnostics(plan_path, plan)
    identity_issues = identity_diagnostics(plan_path, plan, prior, candidate)
    evidence_issues = evidence_diagnostics(plan, (prior, candidate))
    metrics, metric_blocking, metric_failures = [], [], []
    for rule in plan["decision_policy"]["metric_rules"]:
        metric, diagnostics = metric_result(
            plan, prior, candidate, rule, policy_bytes=policy_bytes
        )
        metrics.append(metric)
        target = metric_blocking if metric["revision_decision"] == "not_evaluable" else metric_failures
        target.extend(diagnostics)
    gate_blocking, gate_failures = _gate_diagnostics(plan, candidate)
    blocking = policy_issues + identity_issues + evidence_issues + metric_blocking + gate_blocking
    failures = metric_failures + gate_failures
    status = "not_evaluable" if blocking else "open" if failures else "closed"
    eligible = (
        status == "closed"
        and plan["registration"]["mode"] == "pre_registered"
        and plan["claim_scope"] == "revision_noninferiority"
    )
    authority: list[dict[str, Any]] = []
    if status == "closed" and not eligible:
        authority.append(plan_diagnostic(
            plan_path,
            fact_type="authority",
            reason_key="revision_v4_authority_blocked",
            expected="a pre-registered revision_noninferiority claim",
            observed={"registration": plan["registration"]["mode"], "claim_scope": plan["claim_scope"]},
            json_pointer="/registration",
        ))
    diagnostics = _unique_diagnostics(blocking + failures + authority)
    return {
        "registration_status": "not_evaluable" if status == "not_evaluable" else "declared_pre_registered",
        "comparability_checks": [
            _check("revision-policy", policy_issues),
            _check("revision-identity", identity_issues),
            _check("revision-evidence", evidence_issues),
            _check("revision-metrics", metric_blocking or metric_failures, failed=bool(metric_failures and not metric_blocking)),
            _check("revision-required-gates", gate_blocking or gate_failures, failed=bool(gate_failures and not gate_blocking)),
        ],
        "metrics": metrics,
        "result": {
            "kind": "revision",
            "status": status,
            "target_failure_class": "bundle_noninferiority",
            "closed_diagnostic_ids": [],
            "remaining_diagnostic_ids": [],
        },
        "authority_eligibility": "eligible" if eligible else "blocked",
        "claim_ceiling": "revision_noninferiority" if eligible else "diagnostic_only",
    }, diagnostics


def _report(plan: dict[str, Any], capsules: dict[str, CycleCapsule], decision: dict[str, Any]) -> dict[str, Any]:
    roles = sorted(capsules, key=ROLE_ORDER.__getitem__)
    products = plan["decision_policy"]["bundle_products"]
    inputs = []
    for role in roles:
        row = capsules[role].report_record()
        row["product_identity"] = products[role]
        inputs.append(row)
    return {
        "schema_version": 4,
        "comparison_id": plan["comparison_id"],
        "kind": "revision",
        "claim_scope": plan["claim_scope"],
        "generator": {
            "name": "compare_cycles.py",
            "version": "6.0.0",
            "source_revision": capsules["candidate"].execution_plan["source_revision"],
        },
        "registration_status": decision["registration_status"],
        "registration_policy_digest": plan["decision_policy"]["policy_digest"],
        "inputs": inputs,
        "comparability_checks": decision["comparability_checks"],
        "metrics": decision["metrics"],
        "result": decision["result"],
        "authority_eligibility": decision["authority_eligibility"],
        "claim_ceiling": decision["claim_ceiling"],
        "diagnostic_index_path": plan["output"]["diagnostic_index"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args(argv)
    try:
        plan_path, plan, registry = load_plan(args.plan)
        capsules = load_cycle_capsules(plan_path, plan, registry)
        decision, diagnostics = evaluate(plan_path, plan, capsules)
        report_path, index_path = commit_outputs(
            plan_path, plan, _report(plan, capsules, decision), diagnostics, registry
        )
    except ContractError as exc:
        print(f"comparison error [{exc.code}]: {exc}", file=sys.stderr)
        return 2
    except (FileExistsError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"comparison error [comparison.failure]: {exc}", file=sys.stderr)
        return 2
    print(
        f"comparison={decision['result']['status']} "
        f"report={report_path.relative_to(plan_path.parent).as_posix()} "
        f"diagnostic_index={index_path.relative_to(plan_path.parent).as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
