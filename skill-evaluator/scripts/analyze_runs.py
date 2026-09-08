"""Small maintenance reports and paired independent-case statistics."""

from __future__ import annotations

from collections import defaultdict
import random
import statistics
import math
from typing import Any

from task_results import checks, position


def paired_comparison(
    rows,
    *,
    comparator,
    candidate="candidate",
    confidence_level=0.95,
    bootstrap_iterations=2000,
    random_seed=0,
):
    indexed = {}
    for row in rows:
        if row["variant"] not in {comparator, candidate}:
            continue
        key = (row["case_id"], row["repeat"], row["variant"])
        if key in indexed:
            raise ValueError("duplicate paired case/repeat/variant")
        indexed[key] = row
    left = {
        (case, repeat) for case, repeat, variant in indexed if variant == comparator
    }
    right = {
        (case, repeat) for case, repeat, variant in indexed if variant == candidate
    }
    result = {
        "comparator": comparator,
        "candidate": candidate,
        "case_count": 0,
        "paired_repeats": len(left & right),
        "point": None,
        "lower": None,
        "upper": None,
        "status": "not_evaluable",
        "baseline_ceiling": False,
    }
    if not left or left != right:
        return {**result, "reason": "missing paired case/repeat evidence"}
    by_case = defaultdict(list)
    for case, repeat in sorted(left):
        before, after = (
            indexed[(case, repeat, comparator)],
            indexed[(case, repeat, candidate)],
        )
        if not before["evidence_complete"] or not after["evidence_complete"]:
            return {**result, "reason": "incomplete grading evidence"}
        by_case[case].append(int(after["task_pass"]) - int(before["task_pass"]))
    differences = [statistics.fmean(values) for values in by_case.values()]
    result.update(
        case_count=len(differences),
        point=statistics.fmean(differences),
        baseline_ceiling=all(
            indexed[(case, repeat, comparator)]["task_pass"] for case, repeat in left
        ),
    )
    if len(differences) < 2:
        return {
            **result,
            "reason": "at least two independent cases are required for an interval",
        }
    summary = summarize_case_differences(
        differences,
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed,
    )
    result.update(
        status="diagnostic",
        lower=summary["lower"],
        upper=summary["upper"],
        confidence_level=confidence_level,
    )
    return result


def record_summary(record, entry, *, variant=None):
    requirements = entry["execute_case_payload"]["case"]["requirements"]
    observed = checks(record, requirements)
    missing = [
        r["check_id"]
        for r in requirements
        if r["required"] and r["check_id"] not in observed
    ]
    required_outcomes = [
        r for r in requirements if r["required"] and r["dimension"] == "outcome"
    ]
    task_pass = record["result"]["terminal_status"] == "completed" and all(
        observed.get(r["check_id"], False) for r in required_outcomes
    )
    return {
        "case_id": entry["case_id"],
        "variant": variant or entry["treatment_id"],
        "repeat": entry["repeat"],
        "task_pass": task_pass,
        "safety_pass": all(
            observed.get(r["check_id"], False)
            for r in requirements
            if r["required"] and r["dimension"] == "safety"
        ),
        "evidence_complete": not missing,
        "checks": observed,
        "missing_checks": missing,
        "failed_checks": [name for name, passed in observed.items() if not passed],
        "terminal": record["result"]["terminal_status"],
        "source": record["source"],
    }


def summarize(records, entries, analysis, *, previous_rows=()):
    rows = [
        record_summary(records[position(entry)], entry)
        for entry in entries
        if position(entry) in records
    ]
    missing = [
        list(position(entry)) for entry in entries if position(entry) not in records
    ]
    complete = not missing and all(row["evidence_complete"] for row in rows)
    comparisons = {}
    for comparator in ("baseline", "previous"):
        if comparator == "previous":
            eligible = {(row["case_id"], row["repeat"]) for row in previous_rows}
            compared = list(previous_rows) + [
                row for row in rows if (row["case_id"], row["repeat"]) in eligible
            ]
        else:
            compared = rows
        if any(row["variant"] == comparator for row in compared):
            comparisons[comparator] = paired_comparison(
                compared, comparator=comparator, **analysis
            )
    return {
        "usefulness_status": "diagnostic_only" if complete else "not_evaluable",
        "final_authority_status": "maintenance_only",
        "evidence_status": "complete" if complete else "incomplete",
        "missing": missing,
        "cases": rows,
        "comparisons": comparisons,
        "baseline_ceiling": comparisons.get("baseline", {}).get(
            "baseline_ceiling", False
        ),
        "failures": [
            row
            for row in rows
            if not row["task_pass"]
            or not row["safety_pass"]
            or row["failed_checks"]
            or row["missing_checks"]
        ],
    }


def percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute a percentile of an empty sequence")
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def summarize_case_differences(
    case_differences: list[float],
    *,
    confidence_level: float,
    bootstrap_iterations: int,
    random_seed: int,
) -> dict[str, Any]:
    values = sorted(float(value) for value in case_differences)
    if len(values) < 2 or any(not math.isfinite(value) for value in values):
        raise ValueError("at least two finite case differences are required")
    rng = random.Random(random_seed)
    count = len(values)
    bootstrap_means = sorted(
        sum(rng.choice(values) for _ in range(count)) / count
        for _ in range(bootstrap_iterations)
    )
    alpha = 1 - confidence_level
    return {
        "point": sum(values) / count,
        "lower": percentile(bootstrap_means, alpha / 2),
        "upper": percentile(bootstrap_means, 1 - alpha / 2),
        "case_count": count,
        "resampling_unit": "case_id",
    }
