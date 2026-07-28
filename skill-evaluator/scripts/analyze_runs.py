#!/usr/bin/env python3
"""Summarize normalized Agent Skill evaluation runs from JSONL.

The analyzer reports dimension metrics and paired candidate/baseline outcomes. It
never treats its summary as a substitute for the frozen evaluation contract.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import compile_eval_plan as compiler
import model_grade_transport as model_transport
from evidence_io import (
    atomic_write_bytes,
    canonical_json_bytes,
    canonical_self_hash,
    canonical_sha256,
    file_sha256,
    load_json,
    load_jsonl_objects,
    normalize_relative_path,
    resolve_contained_path,
    validate_locator,
    verify_artifact_records,
    verify_self_hash,
)
from validate_eval_suite import (
    PAIRED_METRIC_DIRECTIONS,
    load_v5_schema_registry,
    validate_host_protocol_record,
    validate_v5_schema,
)

Z_95 = 1.959963984540054
BINARY_FIELDS = {
    "valid", "routing_evaluable", "should_trigger", "skill_body_loaded",
    "skill_incorporated", "skill_applied", "task_pass", "safety_pass",
}
NUMERIC_FIELDS = {
    "process_score", "quality_score", "tokens_in", "tokens_out", "latency_ms",
    "tool_calls", "retries", "critical_safety_incidents", "unauthorized_side_effects",
}
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$", re.I)
PLACEHOLDER_RE = re.compile(r"(?:\breplace(?:-|_)|sha256:replace|example-(?:agent|model|harness))", re.I)
STATIC_CONTEXT_KINDS = {"metadata", "body", "reference"}
CONTEXT_COMPONENT_KINDS = STATIC_CONTEXT_KINDS | {"protocol_output", "failed_command_output"}
CONTEXT_EFFICIENCY_FIELDS = (
    "unique_static_content_bytes",
    "repeated_static_content_bytes",
    "protocol_output_bytes",
    "failed_command_output_bytes",
)
DERIVED_CONTEXT_BYTE_FIELDS = (
    "host_integration_duplicate_bytes",
    "unexplained_repeated_static_content_bytes",
)
DYNAMIC_CONTEXT_SOURCE = re.compile(
    r"^(?:protocol|failed-command):[A-Za-z0-9][A-Za-z0-9._-]{0,63}:[1-9][0-9]*$"
)
PAIRED_METRIC_SOURCES = {
    "task_pass_rate": (None, "task_pass", "binary"),
    "safety_pass_rate": (None, "safety_pass", "binary"),
    "process_score_normalized": (None, "process_score", "score"),
    "quality_score_normalized": (None, "quality_score", "score"),
    "tokens_in": (None, "tokens_in", "native"),
    "tokens_out": (None, "tokens_out", "native"),
    "task_tool_calls": ("counts", "task_tool_calls", "native"),
    "executor_prewrite_task_tool_calls": (
        "counts", "executor_prewrite_task_tool_calls", "native",
    ),
    "executor_prewrite_tool_output_bytes": (
        "bytes", "executor_prewrite_tool_output_bytes", "native",
    ),
    "host_preflight_tool_output_bytes": (
        "bytes", "host_preflight_tool_output_bytes", "native",
    ),
    "skill_context_bytes": ("context_usage", "bytes", "native"),
    "controlled_skill_context_bytes": (
        "context_usage", "controlled_bytes", "native",
    ),
    "controlled_core_skill_context_bytes": (
        "context_usage", "controlled_core_bytes", "native",
    ),
    "host_injected_body_count": ("counts", "host_injected_body_count", "native"),
    "model_initiated_body_read_count": ("counts", "model_initiated_body_read_count", "native"),
    "reference_load_count": ("counts", "reference_load_count", "native"),
    "skill_load_tool_calls": ("counts", "skill_load_tool_calls", "native"),
    "skill_protocol_tool_calls": ("counts", "skill_protocol_tool_calls", "native"),
    "workflow_artifact_count": ("counts", "workflow_artifact_count", "native"),
}
def validate_grader_output(
    output: Any, requirements: list[dict[str, Any]], artifacts: dict[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "overall_pass", "score", "checks", "missing_evidence",
        "grader_failure", "grader_failure_reason",
    }
    if not isinstance(output, dict) or set(output) != expected_fields:
        raise ValueError("grader output fields do not match the v1 transport shape")
    if not isinstance(output.get("overall_pass"), bool):
        raise ValueError("grader overall_pass must be boolean")
    score = output.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        raise ValueError("grader score must be an integer in [0, 100]")
    checks = output.get("checks")
    missing_evidence = output.get("missing_evidence")
    if not isinstance(checks, list) or not isinstance(missing_evidence, list):
        raise ValueError("grader checks and missing_evidence must be arrays")
    failure = output.get("grader_failure")
    reason = output.get("grader_failure_reason")
    if not isinstance(failure, bool):
        raise ValueError("grader_failure must be boolean")

    if failure:
        if checks or not missing_evidence or output["overall_pass"] or score != 0:
            raise ValueError("grader failure must have empty checks, missing evidence, score 0, and overall false")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("grader failure requires a non-empty reason")
        for item in missing_evidence:
            if (
                not isinstance(item, dict) or set(item) != {"check_id", "item"}
                or item.get("check_id") is not None
                or not isinstance(item.get("item"), str) or not item["item"].strip()
            ):
                raise ValueError("grader failure missing_evidence must use {check_id:null,item}")
        return {"overall_pass": False, "score": 0, "checks": {}, "grader_failure": True}

    if reason is not None:
        raise ValueError("non-failure grader output requires grader_failure_reason=null")
    selected_ids = [requirement["check_id"] for requirement in requirements]
    check_ids: list[str] = []
    check_results: dict[str, bool] = {}
    for index, check in enumerate(checks):
        prefix = f"grader checks[{index}]"
        if not isinstance(check, dict) or set(check) != {
            "check_id", "pass", "evidence", "notes", "uncertainty",
        }:
            raise ValueError(f"{prefix} fields do not match the transport shape")
        check_id = check.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError(f"{prefix}.check_id must be a non-empty string")
        if check_id in check_results:
            raise ValueError(f"duplicate grader check ID: {check_id}")
        if not isinstance(check.get("pass"), bool):
            raise ValueError(f"{prefix}.pass must be boolean")
        if not isinstance(check.get("notes"), str) or not isinstance(
            check.get("uncertainty"), str,
        ):
            raise ValueError(f"{prefix} notes/uncertainty are invalid")
        evidence_items = check.get("evidence")
        if not isinstance(evidence_items, list):
            raise ValueError(f"{prefix}.evidence must be an array")
        for evidence in evidence_items:
            if (
                not isinstance(evidence, dict)
                or set(evidence) != {"artifact", "locator", "observation"}
                or not isinstance(evidence["locator"], dict)
                or not isinstance(evidence["observation"], str)
                or not evidence["observation"]
            ):
                raise ValueError(f"{prefix} evidence shape is invalid")
            validate_locator(
                {
                    "kind": "text_lines",
                    "artifact": evidence["artifact"],
                    **evidence["locator"],
                },
                artifacts,
            )
        check_ids.append(check_id)
        check_results[check_id] = check["pass"]
    if len(check_ids) != len(set(check_ids)):
        raise ValueError("duplicate grader check ID")
    if set(check_ids) != set(selected_ids) or len(check_ids) != len(selected_ids):
        raise ValueError("grader selected check IDs do not match case requirements")

    missing_pairs: set[tuple[str, str]] = set()
    required_by_check = {requirement["check_id"]: requirement["required"] for requirement in requirements}
    for item in missing_evidence:
        if (
            not isinstance(item, dict) or set(item) != {"check_id", "item"}
            or item.get("check_id") not in check_results
            or not isinstance(item.get("item"), str) or not item["item"].strip()
        ):
            raise ValueError("normal missing_evidence must map a selected check_id to a non-empty item")
        pair = (item["check_id"], item["item"])
        if pair in missing_pairs:
            raise ValueError("duplicate grader missing_evidence item")
        missing_pairs.add(pair)
        if check_results[item["check_id"]] is True:
            raise ValueError("missing_evidence cannot reference a passing check")
        if required_by_check[item["check_id"]] is True:
            raise ValueError("required check cannot be accepted with missing evidence")

    computed_overall = all(
        check_results[requirement["check_id"]]
        for requirement in requirements if requirement["required"] is True
    )
    weights = [requirement.get("weight") for requirement in requirements]
    if weights and all(weight is not None for weight in weights):
        denominator = sum(float(weight) for weight in weights)
        raw_score = sum(
            float(requirement["weight"]) for requirement in requirements
            if check_results[requirement["check_id"]]
        ) / denominator * 100
    else:
        raw_score = sum(1 for result in check_results.values() if result) / len(check_results) * 100
    computed_score = math.floor(raw_score + 0.5)
    if output["overall_pass"] != computed_overall:
        raise ValueError("grader overall_pass mismatch")
    if score != computed_score:
        raise ValueError(f"grader score mismatch: expected {computed_score}, got {score}")
    return {
        "overall_pass": computed_overall,
        "score": computed_score,
        "checks": check_results,
        "grader_failure": False,
    }


def wilson(successes: int, n: int, z: float = Z_95) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def proportion(values: Iterable[bool]) -> dict[str, Any]:
    data = list(values)
    successes = sum(1 for value in data if value)
    n = len(data)
    return {
        "n": n,
        "successes": successes,
        "rate": successes / n if n else None,
        "wilson95": wilson(successes, n),
    }


def nearest_rank(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def continuous(values: Iterable[float]) -> dict[str, Any]:
    data = [float(value) for value in values]
    if not data:
        return {"n": 0, "mean": None, "median": None, "p90": None, "min": None, "max": None}
    return {
        "n": len(data),
        "mean": statistics.fmean(data),
        "median": statistics.median(data),
        "p90": nearest_rank(data, 0.90),
        "min": min(data),
        "max": max(data),
    }


def routing_summary(
    records: list[dict[str, Any]],
    target_skill_id: str | None,
    eligible_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    rows = [
        record for record in records
        if record.get("valid") is True
        and (
            record["case_id"] in eligible_case_ids
            if eligible_case_ids is not None
            else record.get("routing_evaluable") is True
        )
    ]
    if not target_skill_id:
        return {
            "status": "not_evaluable", "reason": "target skill ID is unavailable",
            "n": len({row.get("case_id") for row in rows}), "run_count": len(rows),
        }
    required_fields = {
        "should_trigger", "retrieved_skill_ids", "selected_skill_id", "skill_body_loaded",
        "resources_loaded", "skill_incorporated", "skill_applied",
    }
    missing = [
        {"run_id": row.get("run_id"), "fields": sorted(required_fields - set(row))}
        for row in rows if required_fields - set(row)
    ]
    bad_types = []
    for row in rows:
        if not isinstance(row.get("should_trigger"), bool):
            bad_types.append({"run_id": row.get("run_id"), "field": "should_trigger"})
        if not isinstance(row.get("retrieved_skill_ids"), list):
            bad_types.append({"run_id": row.get("run_id"), "field": "retrieved_skill_ids"})
        if row.get("selected_skill_id") is not None and not isinstance(row.get("selected_skill_id"), str):
            bad_types.append({"run_id": row.get("run_id"), "field": "selected_skill_id"})
        for field in ("skill_body_loaded", "skill_incorporated", "skill_applied"):
            if not isinstance(row.get(field), bool):
                bad_types.append({"run_id": row.get("run_id"), "field": field})
        if not isinstance(row.get("resources_loaded"), list):
            bad_types.append({"run_id": row.get("run_id"), "field": "resources_loaded"})
    if missing or bad_types:
        return {
            "status": "not_evaluable",
            "reason": "routing-stage evidence is incomplete or malformed",
            "n": len({row.get("case_id") for row in rows}),
            "run_count": len(rows),
            "missing": missing[:100],
            "bad_types": bad_types[:100],
        }

    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    inconsistent_labels = [
        case_id for case_id, case_rows in by_case.items()
        if len({row["should_trigger"] for row in case_rows}) != 1
    ]
    if inconsistent_labels:
        return {
            "status": "not_evaluable",
            "reason": "should_trigger disagrees across repeats",
            "case_ids": sorted(inconsistent_labels),
            "n": len(by_case),
        }

    cases = [
        (case_id, sorted(case_rows, key=lambda row: row["repeat"]))
        for case_id, case_rows in sorted(by_case.items())
    ]
    positives = [(case_id, case_rows) for case_id, case_rows in cases if case_rows[0]["should_trigger"]]
    negatives = [(case_id, case_rows) for case_id, case_rows in cases if not case_rows[0]["should_trigger"]]

    def retrieved(row: dict[str, Any]) -> bool:
        return target_skill_id in row["retrieved_skill_ids"]

    def selected(row: dict[str, Any]) -> bool:
        return row["selected_skill_id"] == target_skill_id

    def all_stage(case_rows: list[dict[str, Any]], predicate: Any) -> bool:
        return all(predicate(row) for row in case_rows)

    def any_stage(case_rows: list[dict[str, Any]], predicate: Any) -> bool:
        return any(predicate(row) for row in case_rows)

    positive_loaded = [all_stage(case_rows, lambda row: row["skill_body_loaded"]) for _, case_rows in positives]
    negative_loaded = [any_stage(case_rows, lambda row: row["skill_body_loaded"]) for _, case_rows in negatives]
    tp = sum(positive_loaded)
    fn = len(positive_loaded) - tp
    fp = sum(negative_loaded)
    tn = len(negative_loaded) - fp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None

    reciprocal_ranks = []
    for _, case_rows in positives:
        repeat_ranks = []
        for row in case_rows:
            try:
                repeat_ranks.append(1.0 / (row["retrieved_skill_ids"].index(target_skill_id) + 1))
            except ValueError:
                repeat_ranks.append(0.0)
        reciprocal_ranks.append(statistics.fmean(repeat_ranks))

    failure_counts: Counter[str] = Counter()
    for _, case_rows in cases:
        should_trigger = case_rows[0]["should_trigger"]
        if should_trigger:
            if not all_stage(case_rows, retrieved):
                failure_counts["retrieval_miss"] += 1
            elif not all_stage(case_rows, selected):
                failure_counts["selection_miss"] += 1
            elif not all_stage(case_rows, lambda row: row["skill_body_loaded"]):
                failure_counts["body_load_miss"] += 1
            elif not all_stage(case_rows, lambda row: row["skill_incorporated"]):
                failure_counts["incorporation_miss"] += 1
            elif not all_stage(case_rows, lambda row: row["skill_applied"]):
                failure_counts["application_miss"] += 1
        else:
            if any_stage(case_rows, selected):
                failure_counts["false_selection"] += 1
            if any_stage(case_rows, lambda row: row["skill_body_loaded"]):
                failure_counts["false_body_load"] += 1
            if any_stage(case_rows, lambda row: row["skill_applied"]):
                failure_counts["false_application"] += 1

    retrieval_positive = proportion(all_stage(case_rows, retrieved) for _, case_rows in positives)
    retrieval_negative = proportion(any_stage(case_rows, retrieved) for _, case_rows in negatives)
    selection_positive = proportion(all_stage(case_rows, selected) for _, case_rows in positives)
    selection_negative = proportion(any_stage(case_rows, selected) for _, case_rows in negatives)
    body_positive = proportion(positive_loaded)
    body_negative = proportion(negative_loaded)
    incorporated_positive = proportion(
        all_stage(case_rows, lambda row: row["skill_incorporated"]) for _, case_rows in positives
    )
    applied_positive = proportion(
        all_stage(case_rows, lambda row: row["skill_applied"]) for _, case_rows in positives
    )
    applied_negative = proportion(
        any_stage(case_rows, lambda row: row["skill_applied"]) for _, case_rows in negatives
    )
    repeat_consistency = proportion(
        len({row["skill_body_loaded"] for row in case_rows}) == 1 for _, case_rows in cases
    )

    return {
        "status": "complete",
        "target_skill_id": target_skill_id,
        "n": len(cases),
        "run_count": len(rows),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": precision,
        "precision_wilson95": wilson(tp, tp + fp),
        "recall": recall,
        "recall_wilson95": wilson(tp, tp + fn),
        "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else None,
        "false_negative_rate": fn / (fn + tp) if fn + tp else None,
        "retrieval": {
            "positive_hit_rate": retrieval_positive,
            "negative_hit_rate": retrieval_negative,
            "mrr_on_positive": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else None,
        },
        "selection": {"positive_rate": selection_positive, "negative_rate": selection_negative},
        "body_load": {"positive_rate": body_positive, "negative_rate": body_negative},
        "incorporation": {"positive_rate": incorporated_positive},
        "application": {"positive_rate": applied_positive, "negative_rate": applied_negative},
        "repeat_consistency": repeat_consistency,
        "resources_loaded": continuous(
            statistics.fmean(len(row["resources_loaded"]) for row in case_rows)
            for _, case_rows in cases
        ),
        "stage_failure_counts": dict(sorted(failure_counts.items())),
    }


def summarize_material_failure_cases(
    records: list[dict[str, Any]],
    *,
    baseline: str,
    candidate: str,
    case_ids: set[str],
    repeats: int,
    material_failure_ids: set[str],
) -> dict[str, Any]:
    indexed: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("case_id") in case_ids:
            indexed[
                (record["variant"], record["case_id"], record["repeat"])
            ].append(record)

    complete = True
    failures: dict[str, set[str]] = {baseline: set(), candidate: set()}
    for variant in (baseline, candidate):
        for case_id in case_ids:
            for repeat in range(1, repeats + 1):
                rows = indexed.get((variant, case_id, repeat), [])
                if len(rows) != 1 or rows[0].get("valid") is not True:
                    complete = False
                    continue
                row = rows[0]
                hard_failures = set(row.get("hard_gate_failures", []))
                always_material = any(
                    "no-overclaim" in failure
                    or "authority" in failure
                    for failure in hard_failures
                )
                if (
                    row.get("task_pass") is False
                    or row.get("safety_pass") is False
                    or always_material
                    or bool(hard_failures & material_failure_ids)
                ):
                    failures[variant].add(case_id)

    baseline_failures = failures[baseline]
    candidate_failures = failures[candidate]
    resolved = baseline_failures - candidate_failures
    candidate_only = candidate_failures - baseline_failures
    if not complete:
        usefulness_status = "not_evaluable"
    elif len(baseline_failures) < 3:
        usefulness_status = "inconclusive_ceiling"
    elif (
        len(resolved) >= 2
        and not candidate_only
        and len(candidate_failures) <= len(baseline_failures) // 2
    ):
        usefulness_status = "supported"
    else:
        usefulness_status = "not_supported"
    return {
        "evidence_complete": complete,
        "baseline_material_failure_cases": len(baseline_failures),
        "candidate_material_failure_cases": len(candidate_failures),
        "resolved_baseline_failure_cases": len(resolved),
        "candidate_only_failure_cases": len(candidate_only),
        "baseline_failure_case_ids": sorted(baseline_failures),
        "candidate_failure_case_ids": sorted(candidate_failures),
        "resolved_case_ids": sorted(resolved),
        "candidate_only_case_ids": sorted(candidate_only),
        "usefulness_status": usefulness_status,
    }


def matched_planner_executor_tokens(
    planner_records: list[dict[str, Any]],
    executor_records: list[dict[str, Any]],
    arm_map: dict[str, dict[str, Any]],
    *,
    baseline_planner: str,
    candidate_planner: str,
    baseline_executor: str,
    candidate_executor: str,
    case_ids: set[str],
    repeats: int,
    confidence_level: float = 0.95,
    bootstrap_iterations: int = 10000,
    random_seed: int = 2735,
) -> dict[str, Any]:
    def valid_token_count(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    planners: dict[tuple[str, str, int], dict[str, Any]] = {}
    duplicate_planner_keys = False
    for record in planner_records:
        key = (record["variant"], record["case_id"], record["repeat"])
        if key in planners:
            duplicate_planner_keys = True
        planners[key] = record
    executors: dict[tuple[str, str, int], dict[str, Any]] = {}
    duplicate_executor_keys = False
    for record in executor_records:
        arm = arm_map.get(record["case_id"])
        if not isinstance(arm, dict):
            continue
        key = (
            record["variant"],
            arm["source_case_id"],
            arm["planner_repeat"],
        )
        if key in executors:
            duplicate_executor_keys = True
        executors[key] = record

    case_totals = []
    excluded_pairs = []
    for case_id in sorted(case_ids):
        repeat_totals: dict[str, list[int]] = {
            "baseline": [],
            "candidate": [],
        }
        for repeat in range(1, repeats + 1):
            paired_rows = {
                "baseline": (
                    planners.get((baseline_planner, case_id, repeat)),
                    executors.get((baseline_executor, case_id, repeat)),
                ),
                "candidate": (
                    planners.get((candidate_planner, case_id, repeat)),
                    executors.get((candidate_executor, case_id, repeat)),
                ),
            }
            for arm_name, rows in paired_rows.items():
                reason = None
                if any(row is None for row in rows):
                    reason = "missing"
                elif any(row.get("valid") is not True for row in rows):
                    reason = "invalid"
                elif any(
                    not valid_token_count(row.get(field))
                    for row in rows
                    for field in ("tokens_in", "tokens_out")
                ):
                    reason = "invalid_tokens"
                if reason is not None:
                    excluded_pairs.append({
                        "case_id": case_id,
                        "repeat": repeat,
                        "arm": arm_name,
                        "reason": reason,
                    })
                    continue
                repeat_totals[arm_name].append(sum(
                    row["tokens_in"] + row["tokens_out"]
                    for row in rows
                ))
        if all(len(values) == repeats for values in repeat_totals.values()):
            baseline_total = statistics.fmean(repeat_totals["baseline"])
            candidate_total = statistics.fmean(repeat_totals["candidate"])
            case_totals.append({
                "case_id": case_id,
                "baseline_total_tokens": baseline_total,
                "candidate_total_tokens": candidate_total,
                "relative_reduction": (
                    (baseline_total - candidate_total) / baseline_total
                    if baseline_total > 0 else None
                ),
            })
    reductions = [
        row["relative_reduction"]
        for row in case_totals if row["relative_reduction"] is not None
    ]
    complete = (
        not duplicate_planner_keys
        and not duplicate_executor_keys
        and len(case_totals) == len(case_ids)
        and len(reductions) == len(case_ids)
    )
    if len(reductions) >= 2:
        uncertainty = summarize_case_differences(
            reductions,
            confidence_level=confidence_level,
            bootstrap_iterations=bootstrap_iterations,
            random_seed=random_seed,
        )
    else:
        uncertainty = {"point": None, "lower": None, "upper": None}
    return {
        "status": "complete" if complete else "incomplete",
        "case_count": len(reductions),
        "expected_case_count": len(case_ids),
        "complete": complete,
        "duplicate_planner_keys": duplicate_planner_keys,
        "duplicate_executor_keys": duplicate_executor_keys,
        "excluded_pairs": excluded_pairs,
        "point": uncertainty["point"],
        "lower": uncertainty["lower"],
        "upper": uncertainty["upper"],
        "cases": case_totals,
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
    case_differences: list[float], *, confidence_level: float,
    bootstrap_iterations: int, random_seed: int,
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


def paired_metric_value(record: dict[str, Any], metric: str) -> tuple[float, float]:
    container, field, scale = PAIRED_METRIC_SOURCES[metric]
    source = record if container is None else record.get(container)
    if not isinstance(source, dict) or field not in source:
        raise ValueError(f"missing {metric}")
    value = source[field]
    if scale == "binary":
        if not isinstance(value, bool):
            raise ValueError(f"{metric} must be boolean")
        raw = float(value)
        return raw, raw
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{metric} must be finite numeric")
    raw = float(value)
    if raw < 0:
        raise ValueError(f"{metric} must be non-negative")
    if scale == "score":
        if raw > 100:
            raise ValueError(f"{metric} raw score must be in [0, 100]")
        return raw, raw / 100
    return raw, raw


def paired_metric_scale(metric: str) -> dict[str, str]:
    if metric in {"process_score_normalized", "quality_score_normalized"}:
        return {"raw": "rubric_0_100", "reported": "normalized_0_1", "normalization": "raw / 100"}
    if metric in {"task_pass_rate", "safety_pass_rate"}:
        return {"raw": "boolean", "reported": "binary_0_1", "normalization": "false=0,true=1"}
    return {"raw": "native", "reported": "native", "normalization": "identity"}


def paired_metric_result_base(
    metric: str, comparator: str, direction: str, effect: str,
) -> dict[str, Any]:
    return {
        "status": "not_evaluable",
        "comparator": comparator,
        "direction": direction,
        "effect": effect,
        "estimand": f"{direction}:{effect}:{metric}:candidate_vs_{comparator}",
        "scale": paired_metric_scale(metric),
        "case_count": 0,
        "repeat_count": 0,
        "point": None,
        "lower": None,
        "upper": None,
        "case_differences": [],
        "task_failures": [],
    }


def summarize_paired_metric(
    records: list[dict[str, Any]], *, comparator: str, candidate: str,
    metric: str, direction: str, effect: str, confidence_level: float,
    bootstrap_iterations: int, random_seed: int,
    eligible_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    base = paired_metric_result_base(metric, comparator, direction, effect)
    if metric not in PAIRED_METRIC_DIRECTIONS:
        return {**base, "reason": f"unsupported paired metric: {metric}"}
    if direction != PAIRED_METRIC_DIRECTIONS[metric]:
        return {**base, "reason": f"direction contradicts metric: {metric}"}
    if effect not in {"absolute", "relative"}:
        return {**base, "reason": f"unsupported effect: {effect}"}

    indexed: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if eligible_case_ids is not None and record.get("case_id") not in eligible_case_ids:
            continue
        if record.get("variant") in {comparator, candidate}:
            indexed[(record["variant"], record["case_id"], record["repeat"])].append(record)
    comparator_keys = {(case_id, repeat) for variant, case_id, repeat in indexed if variant == comparator}
    candidate_keys = {(case_id, repeat) for variant, case_id, repeat in indexed if variant == candidate}
    shared_keys = sorted(comparator_keys & candidate_keys)
    if not shared_keys:
        return {**base, "reason": "no shared comparator/candidate pairs"}
    duplicate_keys = [
        f"{variant}:{case_id}:{repeat}"
        for (variant, case_id, repeat), rows in sorted(indexed.items()) if len(rows) != 1
    ]
    if duplicate_keys:
        return {**base, "reason": "duplicate variant/case/repeat keys", "duplicate_keys": duplicate_keys}

    by_case: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    task_failures: list[dict[str, Any]] = []
    for case_id, repeat in shared_keys:
        comparator_row = indexed[(comparator, case_id, repeat)][0]
        candidate_row = indexed[(candidate, case_id, repeat)][0]
        if comparator_row.get("valid") is not True or candidate_row.get("valid") is not True:
            return {**base, "reason": "paired run is invalid"}
        try:
            comparator_raw, comparator_value = paired_metric_value(comparator_row, metric)
            candidate_raw, candidate_value = paired_metric_value(candidate_row, metric)
        except ValueError as exc:
            return {**base, "reason": str(exc), "task_failures": task_failures}
        by_case[case_id].append((comparator_raw, candidate_raw, comparator_value, candidate_value))

    case_differences: list[dict[str, Any]] = []
    for case_id, values in sorted(by_case.items()):
        comparator_raw = statistics.fmean(item[0] for item in values)
        candidate_raw = statistics.fmean(item[1] for item in values)
        comparator_value = statistics.fmean(item[2] for item in values)
        candidate_value = statistics.fmean(item[3] for item in values)
        signed_difference = (
            candidate_value - comparator_value
            if direction == "higher_is_better" else comparator_value - candidate_value
        )
        if effect == "absolute":
            benefit = signed_difference
        elif comparator_value > 0:
            benefit = signed_difference / comparator_value
        elif direction == "lower_is_better":
            benefit = 0.0 if candidate_value == 0 else -1.0
        else:
            return {
                **base,
                "reason": f"comparator value is zero for case {case_id}",
                "task_failures": task_failures,
            }
        case_differences.append({
            "case_id": case_id,
            "comparator_raw_value": comparator_raw,
            "candidate_raw_value": candidate_raw,
            "comparator_value": comparator_value,
            "candidate_value": candidate_value,
            "benefit": benefit,
        })
    if len(case_differences) < 2:
        return {
            **base,
            "reason": "at least two distinct complete cases are required",
            "case_count": len(case_differences),
            "repeat_count": len({repeat for _, repeat in shared_keys}),
            "case_differences": case_differences,
            "task_failures": task_failures,
        }
    uncertainty = summarize_case_differences(
        [row["benefit"] for row in case_differences],
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed,
    )
    return {
        **base,
        "status": "complete",
        "case_count": len(case_differences),
        "repeat_count": len({repeat for _, repeat in shared_keys}),
        "point": uncertainty["point"],
        "lower": uncertainty["lower"],
        "upper": uncertainty["upper"],
        "case_differences": case_differences,
        "task_failures": task_failures,
    }


def summarize_paired_cost_delta(
    records: list[dict[str, Any]], *, comparator: str, candidate: str,
    metric: str, confidence_level: float, bootstrap_iterations: int,
    random_seed: int, eligible_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    result = summarize_paired_metric(
        records,
        comparator=comparator,
        candidate=candidate,
        metric=metric,
        direction="lower_is_better",
        effect="absolute",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed,
        eligible_case_ids=eligible_case_ids,
    )
    if result["status"] != "complete":
        return result
    return {
        **result,
        "estimand": f"candidate_minus_{comparator}:{metric}",
        "point": -result["point"],
        "lower": -result["upper"],
        "upper": -result["lower"],
        "case_differences": [
            {
                **{
                    key: value
                    for key, value in row.items()
                    if key != "benefit"
                },
                "delta": -row["benefit"],
            }
            for row in result["case_differences"]
        ],
    }


def build_paired_metrics(
    records: list[dict[str, Any]], spec: dict[str, Any], *, candidate: str,
    comparator_variants: dict[str, str | None], cases_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    primary = spec["analysis"]["primary_benefit"]
    definitions = [primary] + [
        gate for gate in spec.get("hard_gates", [])
        if gate.get("metric") in PAIRED_METRIC_DIRECTIONS
    ]
    candidate_definition = next(item for item in spec["variants"] if item["id"] == candidate)
    results: dict[str, dict[str, Any]] = {}
    task_failures: dict[tuple[Any, ...], dict[str, Any]] = {}
    for definition in definitions:
        metric = definition["metric"]
        comparator_role = definition["comparator"]
        comparator = comparator_variants.get(comparator_role)
        if comparator is None:
            unavailable = {
                **paired_metric_result_base(
                    metric, comparator_role, definition["direction"], definition["effect"],
                ),
                "reason": f"{comparator_role} comparator variant is unavailable",
                "comparator_variant": None,
            }
            unavailable.pop("task_failures")
            results[metric] = unavailable
            continue
        comparator_definition = next(item for item in spec["variants"] if item["id"] == comparator)
        candidate_profile = f"{candidate_definition['role']}/{candidate_definition['mode']}"
        comparator_profile = f"{comparator_definition['role']}/{comparator_definition['mode']}"
        eligible_case_ids = {
            case_id for case_id, case in cases_by_id.items()
            if case.get("attribution_evaluable") is True
            and candidate_profile in case.get("applicable_variant_profiles", [])
            and comparator_profile in case.get("applicable_variant_profiles", [])
        }
        summary = summarize_paired_metric(
            records, comparator=comparator, candidate=candidate, metric=metric,
            direction=definition["direction"], effect=definition["effect"],
            confidence_level=float(spec["analysis"]["confidence_level"]),
            bootstrap_iterations=int(spec["analysis"]["paired_bootstrap_iterations"]),
            random_seed=int(spec["environment"]["random_seed"]),
            eligible_case_ids=eligible_case_ids,
        )
        for failure in summary.pop("task_failures", []):
            key = (
                comparator_role, failure["case_id"], failure["repeat"],
                failure["comparator_task_pass"], failure["candidate_task_pass"],
            )
            task_failures[key] = {"comparator": comparator_role, **failure}
        summary["comparator"] = comparator_role
        summary["comparator_variant"] = comparator
        results[metric] = summary
    return results, [task_failures[key] for key in sorted(task_failures, key=str)]


def evaluate_benefit(summary: dict[str, Any], minimum_benefit: float) -> dict[str, Any]:
    result = {
        "minimum_benefit": float(minimum_benefit),
        "point": summary.get("point"),
        "lower": summary.get("lower"),
        "upper": summary.get("upper"),
    }
    if summary.get("status") != "complete":
        return {**result, "status": "not_evaluable", "reason": summary.get("reason", "paired metric unavailable")}
    if summary["lower"] >= minimum_benefit:
        return {**result, "status": "pass", "reason": None}
    if summary["upper"] < minimum_benefit:
        return {**result, "status": "fail", "reason": None}
    return {
        **result,
        "status": "not_evaluable",
        "reason": "benefit interval overlaps the declared threshold",
    }


def strict_field_sum(records: list[dict[str, Any]], variant: str, field: str) -> float | None:
    rows = [record for record in records if record["variant"] == variant and record.get("valid") is True]
    if not rows:
        return None
    values = [record.get(field) for record in rows]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return None
    return float(sum(values))


def strict_field_mean(records: list[dict[str, Any]], variant: str, field: str) -> float | None:
    rows = [record for record in records if record["variant"] == variant and record.get("valid") is True]
    if not rows:
        return None
    values = [record.get(field) for record in rows]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return None
    return float(statistics.fmean(values))


def strict_boolean_rate(records: list[dict[str, Any]], variant: str, field: str, *, invert: bool = False) -> float | None:
    rows = [record for record in records if record["variant"] == variant and record.get("valid") is True]
    if not rows or not all(isinstance(record.get(field), bool) for record in rows):
        return None
    successes = sum(1 for record in rows if bool(record[field]) != invert)
    return successes / len(rows)


def strict_routing_metric(
    records: list[dict[str, Any]], variant: str, name: str, target_skill_id: str | None,
    eligible_case_ids: set[str] | None = None,
) -> float | None:
    rows = [record for record in records if record["variant"] == variant]
    summary = routing_summary(rows, target_skill_id, eligible_case_ids)
    if summary.get("status") != "complete":
        return None
    direct = summary.get(name)
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return float(direct)
    nested_mapping = {
        "retrieval_recall": summary["retrieval"]["positive_hit_rate"]["rate"],
        "retrieval_mrr": summary["retrieval"]["mrr_on_positive"],
        "body_load_recall": summary["body_load"]["positive_rate"]["rate"],
        "incorporation_recall": summary["incorporation"]["positive_rate"]["rate"],
        "application_recall": summary["application"]["positive_rate"]["rate"],
        "false_application_rate": summary["application"]["negative_rate"]["rate"],
    }
    if name in nested_mapping:
        value = nested_mapping[name]
        return float(value) if value is not None else None
    return None


def derive_protected_outcome_failures(
    records: list[dict[str, Any]],
    cases_by_id: dict[str, dict[str, Any]], *, baseline: str,
    candidate: str, repeats: int,
) -> int:
    protected_cases = {
        case_id: {
            requirement["id"]
            for requirement in case["requirements"]
            if requirement["dimension"] == "outcome" and requirement["required"] is True
        }
        for case_id, case in cases_by_id.items()
        if "protected" in case.get("tags", [])
    }
    index: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (record["variant"], record["case_id"], record["repeat"])
        index[key].append(record)
    failures = 0
    for case_id, required_outcome_ids in protected_cases.items():
        for variant in (baseline, candidate):
            for repeat in range(1, repeats + 1):
                rows = index.get((variant, case_id, repeat), [])
                if len(rows) != 1 or rows[0].get("valid") is not True:
                    failures += 1
                    continue
                hard_failures = rows[0].get("hard_gate_failures")
                if not isinstance(hard_failures, list) or required_outcome_ids & set(hard_failures):
                    failures += 1
    return failures


def summarize_skill_context(
    records: list[dict[str, Any]], cases_by_id: dict[str, dict[str, Any]],
    spec: dict[str, Any], repeats: int, *, role: str = "candidate",
    mode: str = "natural_routing",
) -> dict[str, Any]:
    selected_profiles = {
        variant["id"]: f"{variant['role']}/{variant['mode']}"
        for variant in spec["variants"]
        if variant["role"] == role and variant["mode"] == mode
    }
    planned_keys = {
        (variant_id, case_id, repeat)
        for variant_id, profile in selected_profiles.items()
        for case_id, case in cases_by_id.items()
        if case.get("should_trigger") is True
        and case.get("attribution_evaluable") is True
        and profile in case.get("applicable_variant_profiles", [])
        for repeat in range(1, repeats + 1)
    }
    indexed: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        indexed[(record["variant"], record["case_id"], record["repeat"])].append(record)

    valid_rows = [record for record in records if record.get("valid") is True]
    conservation_failures = 0
    for row in valid_rows:
        context = row.get("context_usage")
        values = [context.get(field) for field in CONTEXT_EFFICIENCY_FIELDS] if isinstance(context, dict) else []
        host_duplicate = context.get("host_integration_duplicate_bytes") if isinstance(context, dict) else None
        unexplained_repeated = context.get("unexplained_repeated_static_content_bytes") if isinstance(context, dict) else None
        controlled = context.get("controlled_bytes") if isinstance(context, dict) else None
        unique_reference = context.get("unique_reference_bytes") if isinstance(context, dict) else None
        controlled_core = context.get("controlled_core_bytes") if isinstance(context, dict) else None
        unattributed_reads = context.get("unattributed_model_body_read_count") if isinstance(context, dict) else None
        if (
            len(values) != len(CONTEXT_EFFICIENCY_FIELDS)
            or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values)
            or context.get("bytes") != sum(values)
            or not isinstance(host_duplicate, int) or isinstance(host_duplicate, bool)
            or not isinstance(unexplained_repeated, int) or isinstance(unexplained_repeated, bool)
            or not isinstance(controlled, int) or isinstance(controlled, bool)
            or not isinstance(unique_reference, int) or isinstance(unique_reference, bool)
            or not isinstance(controlled_core, int) or isinstance(controlled_core, bool)
            or not isinstance(unattributed_reads, int) or isinstance(unattributed_reads, bool)
            or min(
                host_duplicate, unexplained_repeated, controlled,
                unique_reference, controlled_core, unattributed_reads,
            ) < 0
            or controlled != context.get("bytes") - host_duplicate
            or controlled_core != controlled - unique_reference
            or unexplained_repeated != context.get("repeated_static_content_bytes") - host_duplicate
        ):
            conservation_failures += 1

    negative_case_ids = {
        case_id for case_id, case in cases_by_id.items()
        if case.get("should_trigger") is False
        and any(profile in case.get("applicable_variant_profiles", []) for profile in selected_profiles.values())
    }
    negative_cases: list[list[dict[str, Any]]] = []
    for case_id in sorted(negative_case_ids):
        case_rows = [
            indexed.get((variant_id, case_id, repeat), [])
            for variant_id in selected_profiles
            for repeat in range(1, repeats + 1)
        ]
        if all(
            len(rows) == 1 and rows[0].get("valid") is True
            and rows[0].get("context_usage", {}).get("attributed") is True
            for rows in case_rows
        ):
            negative_cases.append([rows[0] for rows in case_rows])
    false_loads = [any(row.get("skill_body_loaded") is True for row in case_rows) for case_rows in negative_cases]
    false_body_load_bytes = sum(
        component["bytes"]
        for case_rows in negative_cases for row in case_rows
        for component in row["context_usage"]["components"] if component.get("kind") == "body"
    )
    negative_summary = {
        "planned_case_count": len(negative_case_ids),
        "complete_case_count": len(negative_cases),
        "false_body_load_bytes": false_body_load_bytes,
        "false_body_load_case_count": sum(false_loads),
        "false_body_load_rate": proportion(false_loads),
        "repeat_consistency": proportion(
            len({row.get("skill_body_loaded") for row in case_rows}) == 1
            for case_rows in negative_cases
        ),
    }

    attributed_rows: list[dict[str, Any]] = []
    for key in sorted(planned_keys):
        rows = indexed.get(key, [])
        if (
            len(rows) == 1
            and rows[0].get("valid") is True
            and rows[0].get("context_usage", {}).get("attributed") is True
        ):
            attributed_rows.append(rows[0])
    planned = len(planned_keys)
    attributed = len(attributed_rows)
    coverage = attributed / planned if planned else None
    complete = planned > 0 and attributed == planned
    efficiency_fields = CONTEXT_EFFICIENCY_FIELDS + DERIVED_CONTEXT_BYTE_FIELDS
    efficiency_values = {field: [] for field in efficiency_fields}
    controlled_values: list[int] = []
    unattributed_read_values: list[int] = []
    for row in attributed_rows:
        context = row["context_usage"]
        values = [context.get(field) for field in efficiency_fields]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("context efficiency fields must be non-negative integers")
        if context.get("bytes") != sum(context[field] for field in CONTEXT_EFFICIENCY_FIELDS):
            raise ValueError("context efficiency fields do not conserve total skill context bytes")
        controlled = context.get("controlled_bytes")
        unique_reference = context.get("unique_reference_bytes")
        controlled_core = context.get("controlled_core_bytes")
        unattributed_reads = context.get("unattributed_model_body_read_count")
        if (
            not isinstance(controlled, int) or isinstance(controlled, bool) or controlled < 0
            or not isinstance(unique_reference, int)
            or isinstance(unique_reference, bool) or unique_reference < 0
            or not isinstance(controlled_core, int)
            or isinstance(controlled_core, bool) or controlled_core < 0
            or controlled_core != controlled - unique_reference
            or not isinstance(unattributed_reads, int) or isinstance(unattributed_reads, bool)
            or unattributed_reads < 0
        ):
            raise ValueError("host-aware context fields must be non-negative integers")
        for field, value in zip(efficiency_fields, values, strict=True):
            efficiency_values[field].append(value)
        controlled_values.append(controlled)
        unattributed_read_values.append(unattributed_reads)
    byte_values = [float(row["context_usage"]["bytes"]) for row in attributed_rows]
    token_values = [row["context_usage"]["tokens"] for row in attributed_rows]
    token_complete = complete and all(
        isinstance(value, int) and not isinstance(value, bool) for value in token_values
    )
    kind_bytes: Counter[str] = Counter()
    kind_tokens: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    for row in attributed_rows:
        context = row["context_usage"]
        sources[context["measurement_source"]] += 1
        for component in context["components"]:
            kind_bytes[component["kind"]] += component["bytes"]
            if component["tokens"] is not None:
                kind_tokens[component["kind"]] += component["tokens"]
    context_efficiency = {
        field: {
            "p50": nearest_rank(values, 0.50) if complete else None,
            "p95": nearest_rank(values, 0.95) if complete else None,
            "max": max(values) if complete and values else None,
        }
        for field, values in efficiency_values.items()
    }
    return {
        "all_valid_rows": len(valid_rows),
        "conservation_failures": conservation_failures,
        "negative_cohort": negative_summary,
        "planned_rows": planned,
        "attributed_rows": attributed,
        "attribution_rate": coverage,
        "bytes_p95": nearest_rank(byte_values, 0.95) if complete else None,
        "controlled_skill_context_bytes_p95": (
            nearest_rank(controlled_values, 0.95) if complete else None
        ),
        "unattributed_model_body_read_count_max": (
            max(unattributed_read_values) if complete and unattributed_read_values else None
        ),
        "tokens_p95": nearest_rank([float(value) for value in token_values], 0.95) if token_complete else None,
        "measurement_source_counts": dict(sorted(sources.items())),
        "component_bytes": dict(sorted(kind_bytes.items())),
        "component_tokens": dict(sorted(kind_tokens.items())) if token_complete else None,
        "context_efficiency": context_efficiency,
    }


def summarize_prior_skill_context(
    records: list[dict[str, Any]], cases_by_id: dict[str, dict[str, Any]],
    spec: dict[str, Any], repeats: int, candidate_summary: dict[str, Any],
    *, mode: str = "natural_routing",
) -> dict[str, Any] | None:
    """Return a prior comparison only for the candidate treatment mode."""
    prior_ids = [
        variant["id"] for variant in spec["variants"]
        if variant["role"] == "prior" and variant["mode"] == mode
    ]
    if not prior_ids:
        return None
    result: dict[str, Any] = {
        "prior_skill_context": None,
        "candidate_minus_prior_bytes_p95": None,
    }
    candidate_ids = [
        variant["id"] for variant in spec["variants"]
        if variant["role"] == "candidate" and variant["mode"] == mode
    ]
    if len(prior_ids) != 1 or len(candidate_ids) != 1:
        return result

    prior_summary = summarize_skill_context(
        records, cases_by_id, spec, repeats, role="prior", mode=mode
    )
    result["prior_skill_context"] = prior_summary
    if candidate_summary.get("attribution_rate") != 1 or prior_summary.get("attribution_rate") != 1:
        return result

    candidate_id, prior_id = candidate_ids[0], prior_ids[0]
    candidate_profile = f"candidate/{mode}"
    prior_profile = f"prior/{mode}"
    comparable_cases = {
        case_id for case_id, case in cases_by_id.items()
        if case.get("should_trigger") is True
        and case.get("attribution_evaluable") is True
        and candidate_profile in case.get("applicable_variant_profiles", [])
        and prior_profile in case.get("applicable_variant_profiles", [])
    }
    expected_pairs = {
        (case_id, repeat)
        for case_id in comparable_cases
        for repeat in range(1, repeats + 1)
    }
    if not expected_pairs or candidate_summary.get("planned_rows") != len(expected_pairs) or prior_summary.get("planned_rows") != len(expected_pairs):
        return result

    indexed: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        indexed[(record["variant"], record["case_id"], record["repeat"])].append(record)
    for case_id, repeat in expected_pairs:
        candidate_rows = indexed.get((candidate_id, case_id, repeat), [])
        prior_rows = indexed.get((prior_id, case_id, repeat), [])
        if len(candidate_rows) != 1 or len(prior_rows) != 1:
            return result
        candidate_row, prior_row = candidate_rows[0], prior_rows[0]
        if (
            candidate_row.get("valid") is not True
            or prior_row.get("valid") is not True
            or candidate_row.get("context_usage", {}).get("attributed") is not True
            or prior_row.get("context_usage", {}).get("attributed") is not True
            or candidate_row["context_usage"].get("measurement_source")
            != prior_row["context_usage"].get("measurement_source")
        ):
            return result

    candidate_p95 = candidate_summary.get("bytes_p95")
    prior_p95 = prior_summary.get("bytes_p95")
    if isinstance(candidate_p95, (int, float)) and isinstance(prior_p95, (int, float)):
        result["candidate_minus_prior_bytes_p95"] = candidate_p95 - prior_p95
    return result


def derive_usefulness_status(
    *,
    level: str,
    evidence_status: str,
    primary_benefit_status: str,
    guardrail_statuses: list[str],
    protected_outcome_failures: int,
    material_harm: bool,
    candidate_hard_failures: int,
) -> str:
    if level in {"L0", "L1"}:
        return "not_evaluable"
    if evidence_status != "complete":
        return "not_evaluable"
    if (
        candidate_hard_failures > 0
        or material_harm
        or protected_outcome_failures > 0
        or "fail" in guardrail_statuses
    ):
        return "not_supported"
    if primary_benefit_status == "fail":
        return "not_supported"
    if primary_benefit_status == "pass" and all(status == "pass" for status in guardrail_statuses):
        return "supported"
    return "not_evaluable"


def derive_evidence_status(
    *, current_status: str, incomplete_matrix: bool,
    duplicate_pairs: bool, identity_invalid: bool,
) -> str:
    if current_status == "invalid" or duplicate_pairs or identity_invalid:
        return "invalid"
    if current_status == "incomplete" or incomplete_matrix:
        return "incomplete"
    return "complete"


def resolve_gate_metric(
    metric: str,
    spec: dict[str, Any],
    variant_summaries: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    candidate: str | None,
    paired: dict[str, Any] | None,
    target_skill_id: str | None,
    prior: str | None,
    cases_by_id: dict[str, dict[str, Any]] | None,
    repeats: int | None,
    context_summary: dict[str, Any] | None = None,
    paired_metrics: dict[str, dict[str, Any]] | None = None,
) -> float | None:
    if metric == "paired_case_count":
        primary_metric = spec.get("analysis", {}).get("primary_benefit", {}).get("metric")
        summary = paired_metrics.get(primary_metric) if paired_metrics and primary_metric else None
        value = summary.get("case_count") if summary and summary.get("status") == "complete" else None
        return float(value) if value is not None else None
    context_metrics = {
        "skill_context_attribution_rate": "attribution_rate",
        "skill_context_bytes_p95": "bytes_p95",
        "controlled_skill_context_bytes_p95": "controlled_skill_context_bytes_p95",
        "skill_context_tokens_p95": "tokens_p95",
        "unattributed_model_body_read_count_max": "unattributed_model_body_read_count_max",
    }
    if metric in context_metrics:
        value = context_summary.get(context_metrics[metric]) if context_summary else None
        return float(value) if value is not None else None
    efficiency_metrics = {
        "host_integration_duplicate_bytes_max": "host_integration_duplicate_bytes",
        "unexplained_repeated_static_content_bytes_max": "unexplained_repeated_static_content_bytes",
        "protocol_output_bytes_max": "protocol_output_bytes",
        "failed_command_output_bytes_max": "failed_command_output_bytes",
    }
    if metric in efficiency_metrics:
        field = context_summary.get("context_efficiency", {}).get(efficiency_metrics[metric], {}) if context_summary else {}
        value = field.get("max")
        return float(value) if value is not None else None
    variant = candidate
    name = metric
    if "." in metric:
        prefix, suffix = metric.split(".", 1)
        if prefix in variant_summaries:
            variant, name = prefix, suffix
    if variant is None or variant not in variant_summaries:
        return None

    if name == "protected_outcome_failures":
        baseline = paired.get("baseline") if paired else None
        selected_candidate = paired.get("candidate") if paired else candidate
        if not baseline or not selected_candidate or not cases_by_id or not repeats:
            return None
        return float(derive_protected_outcome_failures(
            records, cases_by_id, baseline=baseline,
            candidate=selected_candidate, repeats=repeats,
        ))

    summary = variant_summaries[variant]
    variant_def = next((item for item in spec["variants"] if item["id"] == variant), None)
    eligible_case_ids = None
    if variant_def and cases_by_id is not None:
        profile = f"{variant_def['role']}/{variant_def['mode']}"
        eligible_case_ids = {
            case_id for case_id, case in cases_by_id.items()
            if variant_def["mode"] == "natural_routing"
            and profile in case["applicable_variant_profiles"]
        }
    def route_metric(metric_name: str) -> float | None:
        return strict_routing_metric(records, variant, metric_name, target_skill_id, eligible_case_ids)

    direct = {
        "task_pass_rate": strict_boolean_rate(records, variant, "task_pass"),
        "routing_precision": route_metric("precision"),
        "routing_recall": route_metric("recall"),
        "routing_f1": route_metric("f1"),
        "retrieval_recall": route_metric("retrieval_recall"),
        "retrieval_mrr": route_metric("retrieval_mrr"),
        "body_load_recall": route_metric("body_load_recall"),
        "incorporation_recall": route_metric("incorporation_recall"),
        "application_recall": route_metric("application_recall"),
        "false_application_rate": route_metric("false_application_rate"),
        "safety_incident_rate": strict_boolean_rate(records, variant, "safety_pass", invert=True),
        "critical_safety_incidents": summary["critical_safety_incidents"],
        "invalid_run_rate": summary["invalid_records"] / summary["records"] if summary["records"] else None,
        "worst_slice_task_pass": (
            summary["worst_slice_task_pass"]["rate"]
            if strict_boolean_rate(records, variant, "task_pass") is not None and summary.get("worst_slice_task_pass")
            else None
        ),
    }
    if name in direct:
        value = direct[name]
        return float(value) if value is not None else None
    if name == "unauthorized_side_effects":
        return strict_field_sum(records, variant, name)
    if name in summary["numeric"]:
        return strict_field_mean(records, variant, name)
    return None


def _first_v5_diagnostic(diagnostics: list[dict[str, str]]) -> str:
    diagnostic = diagnostics[0]
    path = diagnostic.get("path") or "/"
    return f"{diagnostic['code']} {path}: {diagnostic['message']}"


def _find_v5_plan(
    spec_path: Path,
    index_path: Path,
    registry: dict[str, dict[str, Any]],
) -> tuple[Path, dict[str, Any]]:
    spec = load_json(spec_path)
    spec_hash = canonical_sha256(compiler._normalize_spec(spec))
    matches: list[tuple[Path, dict[str, Any]]] = []
    for candidate in sorted(spec_path.parent.glob("*.json")):
        if (
            candidate == spec_path
            or candidate.is_symlink()
            or not candidate.is_file()
        ):
            continue
        try:
            value = load_json(candidate)
        except ValueError:
            continue
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("spec_hash") != spec_hash
            or not isinstance(value.get("entries"), list)
        ):
            continue
        diagnostics = validate_v5_schema(
            value, "execution-plan-v1.schema.json", registry,
        )
        if diagnostics or not verify_self_hash(value, "plan_hash"):
            continue
        _, artifacts_root = resolve_contained_path(
            candidate.parent,
            value["artifacts"]["root"],
            "plan artifacts root",
        )
        _, expected_index = resolve_contained_path(
            artifacts_root,
            value["artifacts"]["index_relpath"],
            "plan index",
        )
        if expected_index == index_path:
            matches.append((candidate.resolve(), value))
    if len(matches) != 1:
        raise ValueError(
            "spec parent must contain exactly one validated plan projecting "
            "the supplied index",
        )
    return matches[0]


def _load_v5_analysis_inputs(
    spec_path: Path,
    index_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    Path,
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    registry = load_v5_schema_registry()
    plan_path, plan = _find_v5_plan(spec_path, index_path, registry)
    spec_value = load_json(spec_path)
    _, scenarios_path = resolve_contained_path(
        spec_path.parent,
        spec_value["suite"]["scenarios"]["path"],
        "scenario corpus",
        kind="file",
    )
    _, host_path = resolve_contained_path(
        spec_path.parent,
        spec_value["host"]["manifest"]["path"],
        "host manifest",
        kind="file",
    )
    spec, scenarios, host, registry = compiler._load_ready_contract(
        spec_path, scenarios_path, host_path,
    )
    compiler.validate_compiled_plan(
        plan,
        spec,
        scenarios,
        host,
        spec_path=spec_path,
        source_path=Path(compiler.__file__).resolve(),
        registry=registry,
        runtime_override=plan["compiler"],
    )
    return spec, scenarios, host, plan_path, plan, registry


def _load_v5_bound_artifact(
    spec: dict[str, Any],
    spec_path: Path,
    *,
    field: str,
    schema_name: str,
    hash_field: str,
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    binding = spec["suite"].get(field)
    if binding is None:
        return None
    _, path = resolve_contained_path(
        spec_path.parent,
        binding["path"],
        f"suite {field}",
        kind="file",
    )
    if file_sha256(path) != binding["sha256"]:
        raise ValueError(f"suite {field} bytes differ from the spec binding")
    artifact = load_json(path)
    diagnostics = validate_v5_schema(artifact, schema_name, registry)
    if diagnostics:
        raise ValueError(_first_v5_diagnostic(diagnostics))
    if not verify_self_hash(artifact, hash_field):
        raise ValueError(f"suite {field} self-hash is invalid")
    return artifact


def _load_v5_bound_evidence(
    spec: dict[str, Any],
    spec_path: Path,
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    quality = _load_v5_bound_artifact(
        spec,
        spec_path,
        field="quality",
        schema_name="suite-quality-v1.schema.json",
        hash_field="suite_quality_hash",
        registry=registry,
    )
    calibration = _load_v5_bound_artifact(
        spec,
        spec_path,
        field="calibration",
        schema_name="grader-calibration-v1.schema.json",
        hash_field="calibration_hash",
        registry=registry,
    )
    quality_status = "not_applicable"
    if quality is not None:
        statuses = set(quality["gates"].values())
        quality_status = (
            "fail"
            if "fail" in statuses
            else "not_evaluable"
            if "not_evaluable" in statuses
            else "pass"
        )
    return {
        "quality": quality,
        "quality_status": quality_status,
        "calibration": calibration,
        "calibration_status": (
            "pass" if calibration is not None else "not_applicable"
        ),
    }


def _load_v5_index(
    index_path: Path,
    plan: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    records = load_jsonl_objects(index_path)
    entries = {
        entry["entry_id"]: entry for entry in plan["entries"]
    }
    rows: list[dict[str, Any]] = []
    previous_key: tuple[int, int] | None = None
    attempts: dict[str, int] = defaultdict(int)
    for line_no, row in records:
        diagnostics = validate_v5_schema(
            row, "run-index-row-v2.schema.json", registry,
        )
        if diagnostics:
            raise ValueError(
                f"index line {line_no}: {_first_v5_diagnostic(diagnostics)}",
            )
        entry = entries.get(row["entry_id"])
        if entry is None or entry["disposition"] != "execute":
            raise ValueError(
                f"index line {line_no} does not name an execute plan entry",
            )
        expected = {
            "plan_hash": plan["plan_hash"],
            "plan_id": plan["plan_id"],
            "entry_ordinal": entry["entry_ordinal"],
            "case_id": entry["case_id"],
            "treatment_id": entry["treatment_id"],
            "repeat": entry["repeat"],
        }
        if any(row[field] != value for field, value in expected.items()):
            raise ValueError(
                f"index line {line_no} differs from its plan entry",
            )
        attempts[row["entry_id"]] += 1
        if row["attempt"] != attempts[row["entry_id"]]:
            raise ValueError(
                f"index line {line_no} breaks the contiguous attempt sequence",
            )
        key = (row["entry_ordinal"], row["attempt"])
        if previous_key is not None and key <= previous_key:
            raise ValueError(
                f"index line {line_no} breaks deterministic global order",
            )
        previous_key = key
        rows.append(row)
    return rows


def _expected_v4_provenance(
    plan: dict[str, Any],
    entry: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    return {
        "spec_hash": plan["spec_hash"],
        "scenario_corpus_hash": plan["scenario_corpus_hash"],
        "scenario_hash": entry["scenario_hash"],
        "plan_hash": plan["plan_hash"],
        "host_manifest_hash": plan["host_manifest_hash"],
        "package_hash": plan["package_hashes"][spec["subject"]["skill_id"]],
        "catalog_hash": entry["catalog_hash"],
        "treatment_hash": entry["treatment_hash"],
        "fixture_hash": entry["fixture_hash"],
        "grader_set_hash": plan["grader_set_hash"],
        "calibration_hash": plan["calibration_hash"],
        "suite_quality_hash": plan["suite_quality_hash"],
    }


def _load_v4_receipt(
    row: dict[str, Any],
    *,
    artifacts_root: Path,
    plan: dict[str, Any],
    entry: dict[str, Any],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    expected_dir = f"{entry['artifact_relpath']}/attempt-{row['attempt']:04d}"
    expected_receipt = f"{expected_dir}/receipt.json"
    if (
        row["artifact_dir"] != expected_dir
        or row["receipt"]["path"] != expected_receipt
    ):
        raise ValueError("index attempt paths differ from the plan projection")
    _, attempt_dir = resolve_contained_path(
        artifacts_root, expected_dir, "attempt directory", kind="directory",
    )
    _, receipt_path = resolve_contained_path(
        artifacts_root, expected_receipt, "receipt", kind="file",
    )
    if file_sha256(receipt_path) != row["receipt"]["sha256"]:
        raise ValueError("indexed receipt bytes do not match receipt.sha256")
    receipt = load_json(receipt_path)
    diagnostics = validate_v5_schema(
        receipt, "receipt-v4.schema.json", registry,
    )
    if diagnostics:
        raise ValueError(_first_v5_diagnostic(diagnostics))
    if not verify_self_hash(receipt, "receipt_hash"):
        raise ValueError("receipt_hash does not match canonical receipt bytes")

    _, marker_path = resolve_contained_path(
        attempt_dir, "attempt-start.json", "attempt marker", kind="file",
    )
    marker = load_json(marker_path)
    if (
        not verify_self_hash(marker, "marker_hash")
        or marker != receipt["attempt_start"]
    ):
        raise ValueError("receipt attempt marker is invalid or mismatched")
    run = receipt["run"]
    expected_run = {
        "plan_hash": plan["plan_hash"],
        "plan_id": plan["plan_id"],
        "entry_ordinal": entry["entry_ordinal"],
        "entry_id": entry["entry_id"],
        "case_id": entry["case_id"],
        "treatment_id": entry["treatment_id"],
        "repeat": entry["repeat"],
        "attempt": row["attempt"],
        "run_id": row["run_id"],
    }
    if any(run[field] != value for field, value in expected_run.items()):
        raise ValueError("receipt run identity differs from plan/index identity")
    if receipt["provenance"] != _expected_v4_provenance(plan, entry, spec):
        raise ValueError("receipt provenance differs from the plan entry")
    if receipt["routing"]["catalog"] != [
        item["id"] for item in entry["execute_case_payload"]["catalog"]
    ]:
        raise ValueError("receipt routing catalog differs from the plan entry")
    if {
        principal["slot_id"] for principal in receipt["principals"]
    } not in (set(), set(entry["principal_slot_ids"])):
        raise ValueError("receipt principal slots differ from the plan entry")
    for receipt_key, entry_key, identity_key in (
        ("handoffs", "handoff_ids", "handoff_id"),
        ("actions", "action_ids", "action_id"),
        ("observations", "observation_ids", "observation_id"),
    ):
        identities = {item[identity_key] for item in receipt[receipt_key]}
        if identities not in (set(), set(entry[entry_key])):
            raise ValueError(
                f"receipt {receipt_key} differ from the plan entry",
            )
    context = receipt["context_usage"]
    if (
        context["controlled_core_bytes"]
        != context["controlled_bytes"] - context["unique_reference_bytes"]
        or context["bytes"] != sum(
            component["bytes"] for component in context["components"]
        )
    ):
        raise ValueError("receipt context byte conservation failed")
    artifacts = verify_artifact_records(
        receipt["artifacts"], attempt_dir, label="receipt",
    )
    return receipt, artifacts


def _verified_v4_artifact(
    reference: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    artifact = artifacts.get(reference["path"])
    if artifact is None:
        raise ValueError(f"{label} is absent from verified artifacts")
    if any(
        artifact[field] != reference[field]
        for field in ("path", "sha256", "encoding")
    ):
        raise ValueError(f"{label} reference differs from verified artifacts")
    return artifact


def _model_v4_output(
    entry: dict[str, Any],
    requirements: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
    attempts_by_entry: dict[str, dict[str, Any]],
    grader_id: str,
) -> tuple[dict[str, Any], str, dict[str, str], str]:
    matching_specs = [
        item for item in entry["model_grade_specs"]
        if item["grader_id"] == grader_id
    ]
    if len(matching_specs) != 1:
        raise ValueError("model grader lacks one bound plan specification")
    model_spec = matching_specs[0]
    owner = attempts_by_entry.get(model_spec["batch_owner_entry_id"])
    if owner is None:
        raise ValueError("model grader batch owner receipt is absent")
    receipt = owner["receipt"]
    artifacts = owner["artifacts"]
    references = [
        item for item in receipt["grader_outputs"]
        if item["kind"] == "model" and item["grader_id"] == grader_id
    ]
    if len(references) != 1:
        raise ValueError("model grader batch owner output is ambiguous")
    reference = references[0]
    if reference["schedule_hash"] != model_spec["schedule_hash"]:
        raise ValueError("model grader schedule hash differs from the plan")
    blinded_artifact = _verified_v4_artifact(
        reference["blinded_input"], artifacts, "model blinded input",
    )
    raw_artifact = _verified_v4_artifact(
        reference["raw_batch"], artifacts, "model raw batch",
    )
    try:
        blinded = json.loads(blinded_artifact["text"])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"model blinded input is invalid JSON: {exc.msg}",
        ) from None
    batch_items = []
    for member_id in model_spec["batch_entry_ids"]:
        member = attempts_by_entry.get(member_id)
        if member is None:
            raise ValueError("model grader batch member receipt is absent")
        member_entry = member["entry"]
        member_specs = [
            item for item in member_entry["model_grade_specs"]
            if item["grader_id"] == grader_id
        ]
        if (
            len(member_specs) != 1
            or any(
                member_specs[0][field] != model_spec[field]
                for field in (
                    "batch_id",
                    "batch_entry_ids",
                    "batch_owner_entry_id",
                    "batch_hash",
                    "schedule_hash",
                )
            )
        ):
            raise ValueError("model grader batch member differs from the plan")
        result = model_transport.execution_result(member["receipt"])
        member_blinded = model_transport.blinded_execution(
            member_entry,
            result,
        )
        if sorted(member_blinded) != sorted(model_spec["blinded_projection"]):
            raise ValueError(
                "model blinded input differs from the plan projection",
            )
        batch_items.append(model_transport.execution_item(
            member_blinded,
            grader_id=grader_id,
            entry_id=member_id,
            read_artifact=lambda item, bound=member: _verified_v4_artifact(
                item,
                bound["artifacts"],
                "model grader evidence",
            )["text"],
        ))
    batch = model_transport.execution_batch(
        batch_items,
        batch_id=model_spec["batch_id"],
    )
    if blinded != batch:
        raise ValueError("model blinded batch differs from member receipts")

    requests = [
        item for item in receipt["host_protocol"]["requests"]
        if (
            item["envelope"]["request_kind"] == "model_grade"
            and item["payload"].get("grader_id") == reference["grader_id"]
        )
    ]
    if len(requests) != 1:
        raise ValueError("model grader requires one bound host request")
    request = requests[0]
    if (
        request["payload"].get("batch_hash") != model_spec["batch_hash"]
        or request["payload"].get("schedule_hash") != model_spec["schedule_hash"]
        or request["payload"].get("blinded_input") != batch
    ):
        raise ValueError("model grader host request differs from the plan/batch")

    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw_artifact["text"].splitlines(), 1):
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"model raw batch line {line_no} is invalid JSON: {exc.msg}",
            ) from None
        if not isinstance(record, dict):
            raise ValueError(f"model raw batch line {line_no} is not an object")
        record_type = record.get("record_type")
        schema_name = (
            "host_event"
            if record_type == "skill-evaluator-host-event/1"
            else "host_result"
            if record_type == "skill-evaluator-host-result/1"
            else None
        )
        if schema_name is None:
            raise ValueError("model raw batch contains an unknown record type")
        diagnostics = validate_host_protocol_record(
            schema_name, record, registry,
        )
        if diagnostics:
            raise ValueError(_first_v5_diagnostic(diagnostics))
        records.append(record)
    results = [
        item for item in records
        if item["record_type"] == "skill-evaluator-host-result/1"
    ]
    if not records or len(results) != 1 or records[-1] is not results[0]:
        raise ValueError("model raw batch requires one final terminal result")
    result = results[0]
    if (
        result["envelope"] != request["envelope"]
        or result["request_hash"] != request["request_hash"]
        or result["terminal_status"] != "completed"
        or result["protocol_error"] is not None
    ):
        raise ValueError("model raw batch terminal result is invalid or unbound")
    if sum(
        item == result for item in receipt["host_protocol"]["results"]
    ) != 1:
        raise ValueError("model raw batch result differs from receipt protocol")
    if len(result["artifacts"]) != 1:
        raise ValueError("model grader result requires one output artifact")
    output_reference = result["artifacts"][0]
    output_artifact = _verified_v4_artifact(
        output_reference, artifacts, "model grader output",
    )
    try:
        output = json.loads(output_artifact["text"])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"model grader output is invalid JSON: {exc.msg}",
        ) from None
    normalized, pointers = model_transport.normalize_judgment(
        output,
        batch=batch,
        requirements=requirements,
        item_id=entry["entry_id"],
    )
    return (
        validate_grader_output(normalized, requirements, artifacts),
        output_reference["path"],
        pointers,
        owner["row"]["artifact_dir"],
    )


def _deterministic_v4_output(
    reference: dict[str, Any],
    declaration: dict[str, Any],
    requirements: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    credential_policy: str,
) -> tuple[dict[str, Any], str, dict[str, str]]:
    invocation_artifact = _verified_v4_artifact(
        reference["invocation"], artifacts, "grader invocation",
    )
    output_artifact = _verified_v4_artifact(
        reference["output"], artifacts, "grader output",
    )
    try:
        invocation = json.loads(invocation_artifact["text"])
        output = json.loads(output_artifact["text"])
    except json.JSONDecodeError as exc:
        raise ValueError(f"grader artifact is invalid JSON: {exc.msg}") from None
    expected_fields = {
        "grader_id", "declared_argv", "resolved_argv",
        "resolved_executable_sha256", "cwd", "env", "timeout_seconds",
        "input_allowlist", "inputs", "exit_code", "pass_exit_codes",
        "credential_policy", "shell", "start_new_session",
    }
    if not isinstance(invocation, dict) or set(invocation) != expected_fields:
        raise ValueError("deterministic grader invocation fields are invalid")
    verifier = declaration["verifier"]
    expected = {
        "grader_id": reference["grader_id"],
        "declared_argv": verifier["argv"],
        "cwd": verifier["cwd"],
        "timeout_seconds": verifier["timeout_seconds"],
        "input_allowlist": verifier["input_allowlist"],
        "pass_exit_codes": verifier["pass_exit_codes"],
        "credential_policy": credential_policy,
        "shell": False,
        "start_new_session": True,
    }
    if any(invocation[field] != value for field, value in expected.items()):
        raise ValueError("deterministic grader invocation differs from the spec")
    expected_inputs = []
    prefix = f"graders/{reference['grader_id']}"
    if verifier["cwd"] != ".":
        prefix += "/" + verifier["cwd"]
    for relative in verifier["input_allowlist"]:
        expected_inputs.append(f"{prefix}/{relative}")
    observed_inputs = [item["path"] for item in invocation["inputs"]]
    if observed_inputs != expected_inputs:
        raise ValueError("deterministic grader inputs differ from the allowlist")
    for item in invocation["inputs"]:
        _verified_v4_artifact(item, artifacts, "grader input")
    normalized = validate_grader_output(output, requirements, artifacts)
    if (
        invocation["exit_code"] in invocation["pass_exit_codes"]
    ) != normalized["overall_pass"]:
        raise ValueError("deterministic grader exit/pass semantics contradict")
    return normalized, reference["output"]["path"], {
        item["check_id"]: f"/checks/{index}/pass"
        for index, item in enumerate(output["checks"])
    }


def _read_v4_grades(
    receipt: dict[str, Any],
    entry: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    attempts_by_entry: dict[str, dict[str, Any]],
) -> tuple[dict[str, bool], dict[str, dict[str, Any]]]:
    scenario = entry["execute_case_payload"]["case"]
    requirements = scenario["requirements"]
    expected_graders = set(entry["grader_ids"])
    declarations = {
        item["grader_id"]: item for item in spec["graders"]
    }
    checks: dict[str, bool] = {}
    locators: dict[str, dict[str, Any]] = {}
    consumed_references = 0
    for grader_id in entry["grader_ids"]:
        selected = [
            requirement for requirement in requirements
            if requirement["grader_id"] == grader_id
        ]
        declaration = declarations.get(grader_id)
        if declaration is None:
            raise ValueError("plan grader is absent from the spec")
        references = [
            item for item in receipt["grader_outputs"]
            if item["grader_id"] == grader_id
        ]
        artifact_dir = None
        if declaration["type"] == "deterministic":
            if len(references) != 1 or references[0]["kind"] != "deterministic":
                raise ValueError(
                    "receipt deterministic grader output differs from the plan",
                )
            reference = references[0]
            consumed_references += 1
            normalized, output_path, pointers = _deterministic_v4_output(
                reference,
                declaration,
                selected,
                artifacts,
                spec["execution"]["credential_policy"],
            )
        else:
            model_specs = [
                item for item in entry["model_grade_specs"]
                if item["grader_id"] == grader_id
            ]
            if len(model_specs) != 1:
                raise ValueError("plan model grader batch is ambiguous")
            owns_batch = (
                model_specs[0]["batch_owner_entry_id"] == entry["entry_id"]
            )
            if (
                len(references) != int(owns_batch)
                or any(item["kind"] != "model" for item in references)
            ):
                raise ValueError(
                    "receipt model grader output differs from batch ownership",
                )
            consumed_references += len(references)
            (
                normalized,
                output_path,
                pointers,
                artifact_dir,
            ) = _model_v4_output(
                entry,
                selected,
                registry,
                attempts_by_entry,
                grader_id,
            )
        if normalized["grader_failure"]:
            raise ValueError("grader output reports apparatus failure")
        for check_id, passed in normalized["checks"].items():
            if check_id in checks:
                raise ValueError(f"duplicate normalized grader check: {check_id}")
            checks[check_id] = passed
            locators[check_id] = {
                "kind": "json_pointer",
                "artifact": output_path,
                "json_pointer": pointers[check_id],
                **(
                    {"artifact_dir": artifact_dir}
                    if artifact_dir is not None
                    else {}
                ),
            }
    if (
        len(entry["grader_ids"]) != len(expected_graders)
        or consumed_references != len(receipt["grader_outputs"])
    ):
        raise ValueError("receipt grader outputs differ from the plan entry")
    expected_checks = {item["check_id"] for item in requirements}
    if set(checks) != expected_checks:
        raise ValueError("normalized grader checks do not cover the scenario")
    return checks, locators


def _v4_context_projection(context: dict[str, Any]) -> dict[str, Any]:
    components = context["components"]
    component_bytes = sum(item["bytes"] for item in components)
    unique_static = sum(
        item["bytes"]
        for item in components
        if item["kind"] in STATIC_CONTEXT_KINDS and item["occurrence"] == 1
    )
    repeated_static = sum(
        item["bytes"]
        for item in components
        if item["kind"] in STATIC_CONTEXT_KINDS and item["occurrence"] > 1
    )
    protocol_output = sum(
        item["bytes"] for item in components
        if item["kind"] == "protocol_output"
    )
    failed_output = sum(
        item["bytes"] for item in components
        if item["kind"] == "failed_command_output"
    )
    first_host_static = {
        (item["kind"], item["source_path"], item["content_sha256"])
        for item in components
        if (
            item["kind"] in {"metadata", "body"}
            and item["occurrence"] == 1
        )
    }
    host_duplicate = sum(
        item["bytes"] for item in components
        if (
            item["kind"] in {"metadata", "body"}
            and item["occurrence"] > 1
            and (
                item["kind"],
                item["source_path"],
                item["content_sha256"],
            ) in first_host_static
        )
    )
    unique_reference = sum(
        item["bytes"] for item in components
        if item["kind"] == "reference" and item["occurrence"] == 1
    )
    if (
        context["controlled_bytes"] != context["bytes"] - host_duplicate
        or context["unique_reference_bytes"] != unique_reference
    ):
        raise ValueError("receipt context control-byte accounting failed")
    return {
        **context,
        "attributed": context["status"] == "captured",
        "measurement_source": "receipt-v4",
        "unique_static_content_bytes": unique_static,
        "repeated_static_content_bytes": repeated_static,
        "protocol_output_bytes": protocol_output,
        "failed_command_output_bytes": failed_output,
        "host_integration_duplicate_bytes": host_duplicate,
        "unexplained_repeated_static_content_bytes": (
            repeated_static - host_duplicate
        ),
        "unattributed_residue_bytes": context["bytes"] - component_bytes,
        "unattributed_model_body_read_count": 0,
    }


def _v5_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc,
    )


def _record_from_v4_receipt(
    receipt: dict[str, Any],
    entry: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    bound_evidence: dict[str, Any],
    attempts_by_entry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    run = receipt["run"]
    usage = receipt["usage"]["records"]
    valid = run["valid"] is True
    if entry["model_grade_specs"]:
        calibration = bound_evidence["calibration"]
        if calibration is None:
            raise ValueError("model grader receipt lacks bound calibration")
        created = _v5_utc(calibration["created"])
        started = _v5_utc(run["started_at"])
        ended = _v5_utc(run["ended_at"])
        expires = _v5_utc(calibration["expires"])
        if not created <= started <= ended < expires:
            raise ValueError(
                "model grader attempt is outside the calibration window",
            )
    checks, check_locators = (
        _read_v4_grades(
            receipt,
            entry,
            artifacts,
            spec,
            registry,
            attempts_by_entry,
        )
        if valid else ({}, {})
    )
    requirements = entry["execute_case_payload"]["case"]["requirements"]

    def required_pass(dimension: str) -> bool:
        selected = [
            requirement for requirement in requirements
            if requirement["dimension"] == dimension
            and requirement["required"] is True
        ]
        return bool(selected) and all(
            checks[requirement["check_id"]] for requirement in selected
        )

    terminal_completed = run["terminal"] == "completed"
    task_pass = terminal_completed and required_pass("outcome")
    safety_requirements = [
        item for item in requirements
        if item["dimension"] == "safety" and item["required"] is True
    ]
    safety_pass = all(
        checks[item["check_id"]] for item in safety_requirements
    )
    hard_failures = sorted({
        item["requirement_id"]
        for item in requirements
        if item["required"] is True
        and (
            not checks.get(item["check_id"], False)
            or (item["dimension"] == "outcome" and not terminal_completed)
        )
    })
    routing = receipt["routing"]
    context_components = receipt["context_usage"]["components"]
    return {
        "run_id": run["run_id"],
        "entry_id": run["entry_id"],
        "variant": run["treatment_id"],
        "case_id": run["case_id"],
        "repeat": run["repeat"],
        "valid": valid,
        "task_pass": task_pass,
        "safety_pass": safety_pass,
        "process_score": (
            100 if required_pass("process") else 0
            if any(item["dimension"] == "process" for item in requirements)
            else None
        ),
        "quality_score": (
            100 if required_pass("quality") else 0
            if any(item["dimension"] == "quality" for item in requirements)
            else None
        ),
        "tokens_in": sum(item["input_tokens"] for item in usage),
        "tokens_out": sum(item["output_tokens"] for item in usage),
        "latency_ms": sum(item["runtime_ms"] for item in usage),
        "tool_calls": sum(item["tool_calls"] for item in usage),
        "retries": sum(item["retries"] for item in usage),
        "pricing_identity": receipt["usage"]["pricing_identity"],
        "usage_records": usage,
        "critical_safety_incidents": (
            0 if safety_pass else sum(
                item["safety_severity"] in {"high", "critical"}
                for item in safety_requirements
            )
        ),
        "unauthorized_side_effects": 0,
        "routing_evaluable": True,
        "should_trigger": spec["subject"]["skill_id"] in routing["catalog"],
        "skill_body_loaded": spec["subject"]["skill_id"] in routing["loaded"],
        "skill_incorporated": spec["subject"]["skill_id"] in routing["invoked"],
        "skill_applied": spec["subject"]["skill_id"] in routing["applied"],
        "routing": routing,
        "hard_gate_failures": hard_failures,
        "grader_check_locators": check_locators,
        "error_type": None if terminal_completed else run["terminal"],
        "counts": {
            "task_tool_calls": sum(item["tool_calls"] for item in usage),
            "executor_prewrite_task_tool_calls": 0,
            "host_injected_body_count": sum(
                item["kind"] == "body" and item["occurrence"] == 1
                for item in context_components
            ),
            "model_initiated_body_read_count": 0,
            "reference_load_count": sum(
                item["kind"] == "reference"
                for item in context_components
            ),
            "skill_load_tool_calls": 0,
            "skill_protocol_tool_calls": 0,
            "workflow_artifact_count": len(receipt["artifacts"]),
        },
        "bytes": {
            "executor_prewrite_tool_output_bytes": 0,
            "host_preflight_tool_output_bytes": 0,
        },
        "context_usage": _v4_context_projection(
            receipt["context_usage"],
        ),
        "receipt": receipt,
    }


def _collect_v5_evidence(
    index_rows: list[dict[str, Any]],
    *,
    artifacts_root: Path,
    plan: dict[str, Any],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    bound_evidence: dict[str, Any],
) -> dict[str, Any]:
    entries = {entry["entry_id"]: entry for entry in plan["entries"]}
    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records: list[dict[str, Any]] = []
    selected_attempts: dict[str, dict[str, Any]] = {}
    receipt_issues: list[dict[str, Any]] = []
    for row in index_rows:
        entry = entries[row["entry_id"]]
        try:
            receipt, artifacts = _load_v4_receipt(
                row,
                artifacts_root=artifacts_root,
                plan=plan,
                entry=entry,
                spec=spec,
                registry=registry,
            )
            _, receipt_path = resolve_contained_path(
                artifacts_root,
                row["receipt"]["path"],
                "indexed receipt",
                kind="file",
            )
        except FileNotFoundError as exc:
            receipt_issues.append({
                "row": row,
                "entry": entry,
                "status": "incomplete",
                "issue": str(exc),
            })
            continue
        except (OSError, ValueError, KeyError, TypeError) as exc:
            receipt_issues.append({
                "row": row,
                "entry": entry,
                "status": "invalid",
                "issue": str(exc),
            })
            continue
        attempt = {
            "row": row,
            "entry": entry,
            "receipt": receipt,
            "receipt_path": receipt_path,
            "artifacts": artifacts,
            "record": None,
            "analysis_error": None,
        }
        attempts[entry["entry_id"]].append(attempt)

    attempts_by_entry = {}
    for entry_id, candidates in attempts.items():
        valid = [
            item for item in candidates
            if item["receipt"]["run"]["valid"] is True
        ]
        if len(valid) == 1:
            attempts_by_entry[entry_id] = valid[0]
    for candidates in attempts.values():
        for attempt in candidates:
            if attempt["receipt"]["run"]["valid"] is not True:
                continue
            try:
                attempt["record"] = _record_from_v4_receipt(
                    attempt["receipt"],
                    attempt["entry"],
                    attempt["artifacts"],
                    spec,
                    registry,
                    bound_evidence,
                    attempts_by_entry,
                )
            except (OSError, ValueError, KeyError, TypeError) as exc:
                attempt["analysis_error"] = str(exc)
                receipt_issues.append({
                    "row": attempt["row"],
                    "entry": attempt["entry"],
                    "status": "invalid",
                    "issue": str(exc),
                })

    missing_entries: list[str] = []
    duplicate_terminal_entries: list[str] = []
    for entry in plan["entries"]:
        if entry["disposition"] != "execute":
            continue
        terminal = [
            item for item in attempts[entry["entry_id"]]
            if (
                item["receipt"]["run"]["valid"] is True
                and item["analysis_error"] is None
            )
        ]
        if not terminal:
            missing_entries.append(entry["entry_id"])
            continue
        if len(terminal) != 1:
            duplicate_terminal_entries.append(entry["entry_id"])
            continue
        selected = terminal[0]
        selected_attempts[entry["entry_id"]] = selected
        records.append(selected["record"])

    return {
        "attempts": attempts,
        "selected_attempts": selected_attempts,
        "records": records,
        "missing_entries": missing_entries,
        "duplicate_terminal_entries": duplicate_terminal_entries,
        "receipt_issues": receipt_issues,
        "attempt_count": len(index_rows),
        "invalid_attempts": len({
            (item["row"]["entry_id"], item["row"]["attempt"])
            for values in attempts.values()
            for item in values
            if (
                item["receipt"]["run"]["valid"] is not True
                or item["analysis_error"] is not None
            )
        } | {
            (item["row"]["entry_id"], item["row"]["attempt"])
            for item in receipt_issues
            if item["status"] == "invalid"
        }),
    }


def _empty_metric_summary(
    metric_id: str,
    *,
    direction: str = "lower_is_better",
    effect: str = "absolute",
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "status": "not_evaluable",
        "direction": direction,
        "effect": effect,
        "point": None,
        "lower": None,
        "upper": None,
        "case_count": 0,
        "excluded_pairs": 0,
        "case_differences": {},
    }


def _v5_estimand_metric(
    spec: dict[str, Any],
    plan: dict[str, Any],
    records: list[dict[str, Any]],
    estimand: dict[str, Any],
) -> dict[str, Any]:
    raw = summarize_paired_metric(
        records,
        comparator=estimand["comparator_treatment_id"],
        candidate=estimand["candidate_treatment_id"],
        metric=estimand["metric"],
        direction=estimand["direction"],
        effect=estimand["effect"],
        confidence_level=float(spec["analysis"]["confidence_level"]),
        bootstrap_iterations=int(spec["analysis"]["bootstrap_iterations"]),
        random_seed=int(plan["ordering"]["seed"]),
        eligible_case_ids=None,
    )
    evaluated = evaluate_benefit(raw, estimand["minimum_benefit"])
    return {
        "metric_id": estimand["estimand_id"],
        "status": evaluated["status"],
        "direction": estimand["direction"],
        "effect": estimand["effect"],
        "point": raw.get("point"),
        "lower": raw.get("lower"),
        "upper": raw.get("upper"),
        "case_count": raw.get("case_count", 0),
        "excluded_pairs": len(raw.get("task_failures", [])),
        "case_differences": {
            item["case_id"]: item["benefit"]
            for item in raw.get("case_differences", [])
        },
    }


def _v5_gate_status(gate: dict[str, Any], observed: Any) -> str:
    if observed is None:
        return "not_evaluable"
    direction = gate["direction"]
    threshold = gate["threshold"]
    if direction == "present":
        return "pass"
    if direction == "equal":
        return "pass" if observed == threshold else "fail"
    if (
        not isinstance(observed, (int, float))
        or isinstance(observed, bool)
        or not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
    ):
        return "not_evaluable"
    if direction == "at_least":
        return "pass" if observed >= threshold else "fail"
    if direction == "at_most":
        return "pass" if observed <= threshold else "fail"
    return "not_evaluable"


def _v5_protected_outcome_failures(
    plan: dict[str, Any],
    records: list[dict[str, Any]],
) -> int:
    by_entry = {
        record["entry_id"]: record
        for record in records
        if "entry_id" in record
    }
    failures = 0
    for entry in plan.get("entries", []):
        if (
            entry["disposition"] != "execute"
            or "protected" not in entry["execute_case_payload"]["case"]["tags"]
        ):
            continue
        record = by_entry.get(entry["entry_id"])
        outcome_requirements = {
            item["requirement_id"]
            for item in entry["execute_case_payload"]["case"]["requirements"]
            if item["required"] is True and item["dimension"] == "outcome"
        }
        if (
            record is None
            or record["task_pass"] is not True
            or bool(outcome_requirements & set(record["hard_gate_failures"]))
        ):
            failures += 1
    return failures


def _v5_metric_analysis(
    spec: dict[str, Any],
    plan: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    evidence_status: str,
    feasibility_status: str,
    manual_authority: dict[str, Any] | None = None,
    suite_quality_status: str | None = None,
    calibration_status: str | None = None,
    module_summaries: list[dict[str, Any]] | None = None,
    context_cost: dict[str, Any] | None = None,
) -> dict[str, Any]:
    estimands = spec["analysis"]["estimands"]
    paired_metrics = {
        estimand["estimand_id"]: _v5_estimand_metric(
            spec, plan, records, estimand,
        )
        for estimand in estimands
    }
    primary_definition = estimands[0]
    primary = dict(paired_metrics[primary_definition["estimand_id"]])
    candidate_id = primary_definition["candidate_treatment_id"]
    comparator_id = primary_definition["comparator_treatment_id"]
    candidate_failure_cases = {
        record["case_id"]
        for record in records
        if (
            record["variant"] == candidate_id
            and record.get("valid") is True
            and (
                record.get("task_pass") is not True
                or record.get("safety_pass") is not True
                or bool(record.get("hard_gate_failures"))
            )
        )
    }
    comparator_failure_cases = {
        record["case_id"]
        for record in records
        if (
            record["variant"] == comparator_id
            and record.get("valid") is True
            and (
                record.get("task_pass") is not True
                or record.get("safety_pass") is not True
                or bool(record.get("hard_gate_failures"))
            )
        )
    }
    minimum_headroom = int(
        spec["analysis"]["materiality"].get("minimum_cases", 0),
    )
    baseline_ceiling = (
        spec["level"] not in {"L0", "L1"}
        and evidence_status == "complete"
        and feasibility_status == "feasible"
        and not candidate_failure_cases
        and len(comparator_failure_cases) < minimum_headroom
    )
    candidate_records = [
        record for record in records
        if record["variant"] == candidate_id and record.get("valid") is True
    ]
    absolute_metrics: dict[str, Any] = {
        "critical_safety_incidents": sum(
            record.get("critical_safety_incidents", 0)
            for record in candidate_records
        ),
        "unauthorized_side_effects": sum(
            record.get("unauthorized_side_effects", 0)
            for record in candidate_records
        ),
        "protected_outcome_failures": _v5_protected_outcome_failures(
            plan, records,
        ),
    }
    if context_cost is not None:
        absolute_metrics["skill_context_attribution_rate"] = context_cost[
            "attribution_coverage"
        ]
    module_metrics: dict[str, dict[str, Any]] = {}
    for summary in module_summaries or []:
        module_metrics[summary["module"]] = {
            "status": summary["status"],
            "point": summary["pass_rate"],
            "lower": summary["lower"],
            "upper": summary["upper"],
        }
        module_metrics[f"{summary['module']}_pass_rate"] = module_metrics[
            summary["module"]
        ]
    gate_results: list[dict[str, Any]] = []
    for gate in spec["hard_gates"]:
        matching = [
            paired_metrics[item["estimand_id"]]
            for item in estimands
            if item["metric"] == gate["metric"]
        ]
        metric = matching[0] if len(matching) == 1 else None
        status = "not_evaluable"
        observed: Any = None
        if (
            gate["kind"] in {
                "benefit", "noninferiority", "safety", "protected",
                "context", "module",
            }
            and (
                evidence_status != "complete"
                or feasibility_status != "feasible"
            )
        ):
            pass
        elif gate["kind"] == "manual" and manual_authority is not None:
            observed = manual_authority["decision"]
            status = (
                "pass"
                if (
                    manual_authority["status"] == "complete"
                    and observed == "approve"
                )
                else "fail"
                if (
                    manual_authority["status"] == "complete"
                    and observed in {"hold", "reject"}
                )
                else "not_evaluable"
            )
        elif gate["kind"] == "quality" and suite_quality_status is not None:
            observed = suite_quality_status
            status = (
                "pass" if observed == "pass"
                else "fail" if observed == "fail"
                else "not_evaluable"
            )
        elif gate["kind"] == "calibration" and calibration_status is not None:
            observed = calibration_status
            status = (
                "pass" if observed == "pass"
                else "fail" if observed in {"fail", "expired"}
                else "not_evaluable"
            )
        elif gate["kind"] == "host":
            observed = feasibility_status
            status = (
                "pass" if observed == "feasible"
                else "fail" if observed == "unsupported"
                else "not_evaluable"
            )
        elif gate["kind"] in {"safety", "protected"}:
            observed = absolute_metrics.get(gate["metric"])
            status = _v5_gate_status(gate, observed)
        elif gate["kind"] == "module":
            module_metric = module_metrics.get(gate["metric"])
            if module_metric is not None:
                if gate["direction"] == "at_least":
                    observed = module_metric["lower"]
                elif gate["direction"] == "at_most":
                    observed = module_metric["upper"]
                elif gate["direction"] == "present":
                    observed = module_metric["status"]
                else:
                    observed = module_metric["point"]
                status = _v5_gate_status(gate, observed)
        elif gate["kind"] == "context" and metric is None:
            observed = absolute_metrics.get(gate["metric"])
            status = _v5_gate_status(gate, observed)
        elif metric is not None and metric["point"] is not None:
            if gate["direction"] == "at_least":
                observed = metric["lower"]
                status = _v5_gate_status(gate, observed)
            elif gate["direction"] == "at_most":
                observed = metric["upper"]
                status = _v5_gate_status(gate, observed)
            elif gate["direction"] == "equal":
                observed = metric["point"]
                status = _v5_gate_status(gate, observed)
            elif gate["direction"] == "present":
                observed = metric["point"]
                status = _v5_gate_status(gate, observed)
        gate_results.append({
            "gate": gate,
            "status": status,
            "observed": observed,
        })

    required_gate_statuses = [
        item["status"] for item in gate_results
        if (
            item["gate"]["required"] is True
            and item["gate"]["kind"] != "manual"
        )
    ]
    if spec["level"] in {"L0", "L1"}:
        usefulness = "not_evaluable"
    elif evidence_status != "complete" or feasibility_status != "feasible":
        usefulness = "not_evaluable"
    elif candidate_failure_cases or "fail" in required_gate_statuses:
        usefulness = "not_supported"
    elif baseline_ceiling:
        usefulness = "inconclusive_ceiling"
        primary["status"] = "inconclusive_ceiling"
        paired_metrics[primary_definition["estimand_id"]] = primary
    elif (
        primary["status"] == "pass"
        and all(status == "pass" for status in required_gate_statuses)
    ):
        usefulness = "supported"
    elif primary["status"] == "fail":
        usefulness = "not_supported"
    else:
        usefulness = "not_evaluable"
    return {
        "primary_benefit": primary,
        "paired_metrics": paired_metrics,
        "gate_results": gate_results,
        "candidate_failure_cases": sorted(candidate_failure_cases),
        "comparator_failure_cases": sorted(comparator_failure_cases),
        "baseline_ceiling": baseline_ceiling,
        "usefulness_status": usefulness,
    }


def _module_entry_pass(
    module: str,
    entry: dict[str, Any],
    attempt: dict[str, Any],
    record: dict[str, Any],
    *,
    target_skill_id: str,
    treatment: dict[str, Any],
) -> bool:
    receipt = attempt["receipt"]
    case = entry["execute_case_payload"]["case"]
    if record["task_pass"] is not True or record["safety_pass"] is not True:
        return False
    if module in {"natural_routing", "catalog_routing"}:
        contract = case.get("routing_contract")
        if contract is None:
            return (
                target_skill_id in receipt["routing"]["applied"]
                if treatment["causal_role"] == "candidate"
                else True
            )
        expected = {
            field: [
                value
                for item in contract["expectations"]
                if item["treatment_profile"] == treatment["profile"]
                for value in item[field]
            ]
            for field in (
                "declared", "discovered", "loaded", "model_visible",
                "selected", "invoked", "applied", "order", "composition",
            )
        }
        return all(
            receipt["routing"][field] == values
            for field, values in expected.items()
        )
    if module in {
        "declared_composition", "multi_principal_coordination",
    }:
        coordination_pass = (
            {item["slot_id"] for item in receipt["principals"]}
            == set(entry["principal_slot_ids"])
            and {item["handoff_id"] for item in receipt["handoffs"]}
            == set(entry["handoff_ids"])
            and all(
                item["status"] == "result" for item in receipt["handoffs"]
            )
        )
        if module == "multi_principal_coordination":
            return coordination_pass
        contract = case.get("routing_contract")
        routing_pass = True
        if contract is not None and contract["composition_mode"] != "none":
            expected = [
                value
                for item in contract["expectations"]
                if item["treatment_profile"] == treatment["profile"]
                for value in item["composition"]
            ]
            routing_pass = receipt["routing"]["composition"] == expected
        return routing_pass and coordination_pass
    if module == "multi_turn_state":
        return (
            len(receipt["state"]["checkpoints"]) >= len(case["turns"])
            and receipt["state"]["cleanup"] == "clean"
        )
    if module == "tool_faults":
        expected = {
            item["fault_id"] for item in case["fault_script"]
        }
        return all(
            {item["fault_id"] for item in receipt["faults"][phase]}
            == expected
            for phase in ("injected", "observed", "recovered")
        )
    if module == "dynamic_security":
        return all(
            action["stages"]
            and action["resolved_decision"]
            in {"allow", "deny", "allow_with_changes"}
            for action in receipt["actions"]
        ) and all(
            observation["integrity"] == "pass"
            and observation["temporal_validity"] == "pass"
            for observation in receipt["observations"]
        )
    if module == "longitudinal":
        return (
            receipt["state"]["terminal"] != ""
            and receipt["cleanup"]["process"] == "clean"
        )
    return True


def _v5_module_summaries(
    spec: dict[str, Any],
    plan: dict[str, Any],
    evidence: dict[str, Any],
    evidence_complete: bool,
) -> list[dict[str, Any]]:
    entries = {entry["entry_id"]: entry for entry in plan["entries"]}
    treatments = {
        item["treatment_id"]: item for item in plan["treatments"]
    }
    records = {
        record["receipt"]["run"]["entry_id"]: record
        for record in evidence["records"]
    }
    summaries: list[dict[str, Any]] = []
    for decision in plan["module_decisions"]:
        required = decision["status"] == "required"
        selected: list[tuple[dict[str, Any], bool]] = []
        for entry_id, attempt in evidence["selected_attempts"].items():
            entry = entries[entry_id]
            record = records[entry_id]
            selected.append((
                entry,
                _module_entry_pass(
                    decision["module"],
                    entry,
                    attempt,
                    record,
                    target_skill_id=spec["subject"]["skill_id"],
                    treatment=treatments[entry["treatment_id"]],
                ),
            ))
        case_results: dict[str, list[bool]] = defaultdict(list)
        repeat_results: dict[tuple[str, str], list[bool]] = defaultdict(list)
        for entry, passed in selected:
            case_results[entry["case_id"]].append(passed)
            repeat_results[
                (entry["case_id"], entry["treatment_id"])
            ].append(passed)
        case_passes = [
            all(values) for values in case_results.values()
        ]
        passed_cases = sum(case_passes)
        interval = (
            wilson(passed_cases, len(case_passes))
            if case_passes else None
        )
        failure_ids = sorted({
            requirement_id
            for record in records.values()
            for requirement_id in record["hard_gate_failures"]
        })
        summaries.append({
            "module": decision["module"],
            "eligible": len({
                entry["case_id"] for entry in plan["entries"]
                if entry["disposition"] == "execute"
            }) if required else 0,
            "planned": plan["expected_counts"]["execute"] if required else 0,
            "present": len(selected) if required else 0,
            "valid": len(selected) if required else 0,
            "invalid": evidence["invalid_attempts"] if required else 0,
            "missing": (
                len(evidence["missing_entries"]) if required else 0
            ),
            "pass_rate": (
                passed_cases / len(case_passes)
                if required and case_passes else None
            ),
            "lower": interval[0] if required and interval else None,
            "upper": interval[1] if required and interval else None,
            "repeat_consistency": (
                (
                    sum(len(set(values)) == 1 for values in repeat_results.values())
                    / len(repeat_results)
                )
                if required and repeat_results else None
            ),
            "worst_slice": None,
            "failure_mechanisms": (
                ["module_evidence_failed"]
                if required and case_passes and not all(case_passes)
                else []
            ),
            "hard_requirement_ids": failure_ids if required else [],
            "status": (
                "not_applicable"
                if not required
                else "not_evaluable"
                if not evidence_complete or not case_passes
                else "pass"
                if all(case_passes)
                else "fail"
            ),
        })
    return summaries


def _v5_context_cost(
    spec: dict[str, Any],
    plan: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    captured = [
        record for record in records
        if record["context_usage"]["attributed"] is True
    ]
    coverage = len(captured) / len(records) if records else 0.0
    summaries: dict[str, Any] = {}
    primary = spec["analysis"]["estimands"][0]
    for metric_id in (
        "skill_context_bytes",
        "controlled_skill_context_bytes",
        "controlled_core_skill_context_bytes",
    ):
        raw = summarize_paired_metric(
            captured,
            comparator=primary["comparator_treatment_id"],
            candidate=primary["candidate_treatment_id"],
            metric=metric_id,
            direction="lower_is_better",
            effect="absolute",
            confidence_level=float(spec["analysis"]["confidence_level"]),
            bootstrap_iterations=int(spec["analysis"]["bootstrap_iterations"]),
            random_seed=int(plan["ordering"]["seed"]),
            eligible_case_ids=None,
        )
        summary = _empty_metric_summary(metric_id)
        summary.update({
            "status": (
                "pass"
                if raw["status"] == "complete" and coverage == 1.0
                else "not_evaluable"
            ),
            "point": raw.get("point"),
            "lower": raw.get("lower"),
            "upper": raw.get("upper"),
            "case_count": raw.get("case_count", 0),
            "excluded_pairs": 0,
            "case_differences": {
                item["case_id"]: item["benefit"]
                for item in raw.get("case_differences", [])
            },
        })
        summaries[metric_id] = summary

    usage = [
        (record["run_id"], item)
        for record in records
        for item in record.get("usage_records", [])
    ]
    usage_fields = (
        "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "queue_ms", "runtime_ms", "tool_calls",
        "retries", "rework", "network_calls", "residue_count",
        "requested_effort", "effective_effort",
    )

    def grouped_usage_metrics() -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        dimensions = (
            ("principal", lambda run_id, item: item["principal_id"]),
            (
                "turn",
                lambda run_id, item: (
                    item["turn_id"] if item["turn_id"] is not None else "null"
                ),
            ),
            ("phase", lambda run_id, item: item["phase"]),
            (
                "call",
                lambda run_id, item: "|".join((
                    run_id,
                    item["principal_id"],
                    item["turn_id"] or "null",
                    item["phase"],
                    item["call_id"],
                )),
            ),
        )
        for prefix, key_fn in dimensions:
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for run_id, item in usage:
                grouped[key_fn(run_id, item)].append(item)
            metrics[f"{prefix}_count"] = len(grouped)
            for index, identity in enumerate(sorted(grouped), 1):
                values = grouped[identity]
                metrics[f"{prefix}_{index}_id"] = identity
                for field in usage_fields:
                    metrics[f"{prefix}_{index}_{field}"] = sum(
                        item[field] for item in values
                    )
        return metrics

    def aggregate(reason: str, **values: Any) -> dict[str, Any] | None:
        if not records:
            return None
        return {"status": "pass", "metrics": values, "reason": reason}

    recovery_usage = [
        item for _, item in usage
        if (
            item["retries"] > 0
            or item["rework"] > 0
            or item["residue_count"] > 0
            or item["phase"] in {"fault", "recovery", "cleanup"}
        )
    ]
    recovery_summary = (
        None
        if not records
        else {
            "status": "pass" if recovery_usage else "not_applicable",
            "metrics": {
                field: sum(item[field] for item in recovery_usage)
                for field in usage_fields
            },
            "reason": (
                "verified failure/recovery usage records"
                if recovery_usage
                else "no failure/recovery usage was recorded"
            ),
        }
    )
    return {
        "attribution_coverage": coverage,
        **summaries,
        "tokens": aggregate(
            "verified receipt usage totals",
            input=sum(item["input_tokens"] for _, item in usage),
            output=sum(item["output_tokens"] for _, item in usage),
            cache_read=sum(item["cache_read_tokens"] for _, item in usage),
            cache_write=sum(item["cache_write_tokens"] for _, item in usage),
            pricing_identities=",".join(sorted({
                record.get("pricing_identity", "unknown")
                for record in records
            })),
        ),
        "latency_ms": aggregate(
            "verified queue and runtime totals",
            queue=sum(item["queue_ms"] for _, item in usage),
            runtime=sum(item["runtime_ms"] for _, item in usage),
        ),
        "calls": aggregate(
            "verified per-principal, turn, phase, and call usage",
            tool_calls=sum(item["tool_calls"] for _, item in usage),
            network_calls=sum(item["network_calls"] for _, item in usage),
            **grouped_usage_metrics(),
        ),
        "retries": aggregate(
            "verified retry and rework totals",
            retries=sum(item["retries"] for _, item in usage),
            rework=sum(item["rework"] for _, item in usage),
            requested_effort=sum(
                item["requested_effort"] for _, item in usage
            ),
            effective_effort=sum(
                item["effective_effort"] for _, item in usage
            ),
        ),
        "workflow_artifacts": aggregate(
            "verified artifact, checkpoint, and residue totals",
            artifacts=sum(
                record["counts"]["workflow_artifact_count"]
                for record in records
            ),
            state_checkpoints=sum(
                len(record["receipt"]["state"]["checkpoints"])
                for record in records
                if "receipt" in record
            ),
            residue=sum(item["residue_count"] for _, item in usage),
        ),
        "failure_recovery_overhead": recovery_summary,
        "cache": (
            None
            if not records
            else {
                "status": "pass",
                "metrics": {
                    "provider_cache_read_tokens": sum(
                        item["cache_read_tokens"] for _, item in usage
                    ),
                    "provider_cache_write_tokens": sum(
                        item["cache_write_tokens"] for _, item in usage
                    ),
                    "application_cache_status": "not_evaluable",
                },
                "reason": (
                    "provider token-cache classes are captured; application "
                    "cache semantics are not asserted"
                ),
            }
        ),
    }


def _stage_result(
    surface: str,
    stage: str,
    *,
    eligible: int,
    reached: int,
    passed: int,
    apparatus_gap: bool = False,
) -> dict[str, Any]:
    if eligible == 0:
        status = "not_applicable"
        reason = "stage has no eligible evidence"
    elif reached < eligible and apparatus_gap:
        status = "not_reached_due_to_apparatus"
        reason = "required terminal evidence is missing or invalid"
    elif reached < eligible:
        status = "not_reached_due_to_prior_treatment_failure"
        reason = "an earlier treatment stage did not reach this stage"
    elif passed == eligible:
        status = "pass"
        reason = "all eligible verified evidence passed"
    else:
        status = "fail"
        reason = "verified stage evidence failed"
    return {
        "surface": surface,
        "stage": stage,
        "eligible": eligible,
        "reached": reached,
        "passed": passed,
        "status": status,
        "reason_key": reason.replace(" ", "_"),
    }


def _v5_stage_summaries(
    spec: dict[str, Any],
    plan: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    selected = list(evidence["selected_attempts"].values())
    records = evidence["records"]
    apparatus_gap = bool(
        evidence["missing_entries"]
        or evidence["duplicate_terminal_entries"]
        or evidence["receipt_issues"]
    )
    stages = [
        _stage_result(
            "plan", "exists", eligible=1, reached=1, passed=1,
        ),
        _stage_result(
            "plan", "contract_quality", eligible=1, reached=1, passed=1,
        ),
        _stage_result(
            "plan", "compliance", eligible=1, reached=1, passed=1,
        ),
        _stage_result(
            "plan",
            "execution",
            eligible=plan["expected_counts"]["execute"],
            reached=len(selected),
            passed=len(records),
            apparatus_gap=apparatus_gap,
        ),
        _stage_result(
            "plan",
            "outcome",
            eligible=len(records),
            reached=len(records),
            passed=sum(
                record["task_pass"] is True
                and record["safety_pass"] is True
                for record in records
            ),
        ),
    ]
    required_modules = {
        item["module"] for item in plan["module_decisions"]
        if item["status"] == "required"
    }
    if required_modules & {"natural_routing", "catalog_routing"}:
        entries = {
            entry["entry_id"]: entry for entry in plan["entries"]
        }
        for stage, field in (
            ("declared", "declared"),
            ("discovered", "discovered"),
            ("loaded", "loaded"),
            ("model_visible", "model_visible"),
            ("selected", "selected"),
            ("invoked", "invoked"),
            ("executed", "applied"),
        ):
            eligible = 0
            reached = 0
            passed = 0
            for entry_id, attempt in evidence["selected_attempts"].items():
                entry = entries[entry_id]
                case = entry["execute_case_payload"]["case"]
                contract = case.get("routing_contract")
                if contract is None:
                    eligible += 1
                    reached += 1
                    target = spec["subject"]["skill_id"]
                    passed += target in attempt["receipt"]["routing"][field]
                    continue
                profile = entry["execute_case_payload"]["treatment"][
                    "profile"
                ]
                expected = {
                    item["turn_id"]: item[field]
                    for item in contract["expectations"]
                    if item["treatment_profile"] == profile
                }
                observed = {
                    event["turn_id"]: event["payload"]["routing"][field]
                    for event in attempt["receipt"]["host_protocol"]["events"]
                    if (
                        event["turn_id"] in expected
                        and "routing" in event["payload"]
                    )
                }
                eligible += len(expected)
                reached += len(observed)
                passed += sum(
                    observed.get(turn_id) == values
                    for turn_id, values in expected.items()
                )
            stages.append(_stage_result(
                "skill_tool_access",
                stage,
                eligible=eligible,
                reached=reached,
                passed=passed,
                apparatus_gap=apparatus_gap,
            ))

    actions = [
        action
        for attempt in selected
        for action in attempt["receipt"]["actions"]
    ]
    if actions or any(
        entry["action_ids"] for entry in plan["entries"]
    ):
        mapping = (
            ("proposed", "declared"),
            ("authorized", "authorization_resolved"),
            ("executed", "executed"),
            ("raw_result", "raw_backend_result"),
            ("model_delivery", "model_delivered_result"),
            ("display", "rendered_or_displayed"),
            ("observed", "effect_observed"),
            ("confirmed", "effect_confirmed"),
        )
        for stage, receipt_stage in mapping:
            eligible_actions = (
                actions
                if stage in {"proposed", "authorized"}
                else [
                    action for action in actions
                    if action["resolved_decision"] != "deny"
                ]
            )
            reached = sum(
                receipt_stage
                in {item["stage"] for item in action["stages"]}
                for action in eligible_actions
            )
            stages.append(_stage_result(
                "action_effect",
                stage,
                eligible=len(eligible_actions),
                reached=reached,
                passed=reached,
                apparatus_gap=apparatus_gap,
            ))
        denied = [
            action for action in actions
            if action["resolved_decision"] == "deny"
        ]
        denied_clean = sum(
            action["executed_input"] is None
            and action["backend_request"] is None
            for action in denied
        )
        stages.extend([
            _stage_result(
                "safety",
                "hazard_detected",
                eligible=len(denied),
                reached=len(denied),
                passed=len(denied),
            ),
            _stage_result(
                "safety",
                "unsafe_action_prevented",
                eligible=len(denied),
                reached=denied_clean,
                passed=denied_clean,
            ),
            _stage_result(
                "safety",
                "blast_contained",
                eligible=len(actions),
                reached=len(actions),
                passed=sum(
                    (
                        action["resolved_decision"] == "deny"
                        and action["backend_request"] is None
                    )
                    or (
                        action["resolved_decision"] != "deny"
                        and action["confirmed_effect"] is not None
                    )
                    for action in actions
                ),
            ),
            _stage_result(
                "safety",
                "evidence_auditable",
                eligible=len(actions),
                reached=sum(
                    action["rollback_cleanup_locator"] is not None
                    for action in actions
                ),
                passed=sum(
                    action["rollback_cleanup_locator"] is not None
                    for action in actions
                ),
            ),
        ])

    grounding_requirements = [
        requirement
        for entry in plan["entries"]
        if entry["disposition"] == "execute"
        for requirement in entry["execute_case_payload"]["case"]["requirements"]
        if requirement["dimension"] == "grounding"
    ]
    if grounding_requirements:
        failed = {
            requirement_id
            for record in records
            for requirement_id in record["hard_gate_failures"]
        }
        observations = [
            item for attempt in selected
            for item in attempt["receipt"]["observations"]
        ]
        passed_requirements = sum(
            item["requirement_id"] not in failed
            for item in grounding_requirements
        )
        observation_eligible = len(observations)
        stages.extend([
            _stage_result(
                "grounding", "source_retrieved",
                eligible=len(grounding_requirements),
                reached=observation_eligible,
                passed=observation_eligible,
                apparatus_gap=apparatus_gap,
            ),
            _stage_result(
                "grounding", "source_exists",
                eligible=observation_eligible,
                reached=observation_eligible,
                passed=observation_eligible,
            ),
            _stage_result(
                "grounding", "source_supports_claim",
                eligible=len(grounding_requirements),
                reached=len(grounding_requirements),
                passed=passed_requirements,
            ),
            _stage_result(
                "grounding", "attribution_locator_correct",
                eligible=observation_eligible,
                reached=observation_eligible,
                passed=sum(
                    item["integrity"] == "pass" for item in observations
                ),
            ),
            _stage_result(
                "grounding", "source_temporally_valid",
                eligible=observation_eligible,
                reached=observation_eligible,
                passed=sum(
                    item["temporal_validity"] == "pass"
                    for item in observations
                ),
            ),
        ])
    return stages


def _nullable_summary(
    status: str,
    reason: str,
    **metrics: Any,
) -> dict[str, Any]:
    return {"status": status, "metrics": metrics, "reason": reason}


def _v5_special_summaries(
    spec: dict[str, Any],
    plan: dict[str, Any],
    evidence: dict[str, Any],
    bound_evidence: dict[str, Any],
) -> dict[str, dict[str, Any] | None]:
    selected = list(evidence["selected_attempts"].values())
    receipts = [item["receipt"] for item in selected]
    required_modules = {
        item["module"] for item in plan["module_decisions"]
        if item["status"] == "required"
    }
    coordination: dict[str, Any] | None = None
    if required_modules & {
        "declared_composition", "multi_principal_coordination",
    }:
        principals = sum(len(receipt["principals"]) for receipt in receipts)
        handoffs = [
            handoff for receipt in receipts
            for handoff in receipt["handoffs"]
        ]
        complete = sum(
            handoff["status"] == "result" for handoff in handoffs
        )
        coordination = _nullable_summary(
            "pass" if complete == len(handoffs) else "fail",
            "verified principal topology and typed handoff joins",
            entries=len(receipts),
            principals=principals,
            handoffs=len(handoffs),
            complete_handoffs=complete,
        )

    actions = [
        action for receipt in receipts for action in receipt["actions"]
    ]
    action_summary: dict[str, Any] | None = None
    if actions or any(entry["action_ids"] for entry in plan["entries"]):
        allowed = [
            item for item in actions
            if item["resolved_decision"] != "deny"
        ]
        denied = [
            item for item in actions
            if item["resolved_decision"] == "deny"
        ]
        confirmed = sum(
            item["confirmed_effect"] is not None for item in allowed
        )
        denied_without_execution = sum(
            item["executed_input"] is None
            and item["backend_request"] is None
            for item in denied
        )
        action_summary = _nullable_summary(
            (
                "pass"
                if confirmed == len(allowed)
                and denied_without_execution == len(denied)
                else "fail"
            ),
            "authorization and effect layers remain separate",
            actions=len(actions),
            allowed=len(allowed),
            denied=len(denied),
            confirmed_effects=confirmed,
            denied_without_execution=denied_without_execution,
        )

    principals = [
        principal for receipt in receipts
        for principal in receipt["principals"]
    ]
    independence: dict[str, Any] | None = None
    calibration = bound_evidence["calibration"]
    if calibration is not None:
        derived_status = calibration["independence"]["status"]
        independence = _nullable_summary(
            (
                "pass"
                if derived_status == "independent"
                else "fail"
                if derived_status == "dependent"
                else "not_evaluable"
            ),
            "bound calibration supplies derived grader independence evidence",
            calibration_bound=True,
            principal_count=len(principals),
            derived_status=derived_status,
            **{
                key: value
                for key, value in calibration["independence"].items()
                if key != "status"
            },
        )
    elif len(principals) > len(receipts):
        dependent = sum(
            item["context_mode"] in {"forked", "scoped_handoff"}
            for item in principals
        )
        independence = _nullable_summary(
            "not_evaluable",
            "task topology does not establish independent judging authority",
            calibration_bound=False,
            principal_count=len(principals),
            context_dependent_principals=dependent,
        )

    critique_requirements = [
        requirement
        for entry in plan["entries"]
        if entry["disposition"] == "execute"
        for requirement in entry["execute_case_payload"]["case"]["requirements"]
        if any(
            token in requirement["requirement_id"].lower()
            for token in ("critique", "review", "finding", "repair", "uptake")
        )
    ]
    critique: dict[str, Any] | None = None
    if critique_requirements:
        failed = {
            failure
            for record in evidence["records"]
            for failure in record["hard_gate_failures"]
        }
        passed = sum(
            item["requirement_id"] not in failed
            for item in critique_requirements
        )
        critique = _nullable_summary(
            "pass" if passed == len(critique_requirements) else "fail",
            "critique detection, uptake, and repair remain separate requirements",
            requirements=len(critique_requirements),
            passed=passed,
            failed=len(critique_requirements) - passed,
        )

    grounding_requirements = [
        requirement
        for entry in plan["entries"]
        if entry["disposition"] == "execute"
        for requirement in entry["execute_case_payload"]["case"]["requirements"]
        if requirement["dimension"] == "grounding"
    ]
    observations = [
        observation for receipt in receipts
        for observation in receipt["observations"]
    ]
    grounding: dict[str, Any] | None = None
    if grounding_requirements or observations:
        valid_observations = sum(
            item["integrity"] == "pass"
            and item["temporal_validity"] == "pass"
            for item in observations
        )
        failed_requirements = {
            failure
            for record in evidence["records"]
            for failure in record["hard_gate_failures"]
        }
        passed_requirements = sum(
            item["requirement_id"] not in failed_requirements
            for item in grounding_requirements
        )
        grounding = _nullable_summary(
            (
                "pass"
                if valid_observations == len(observations)
                and passed_requirements == len(grounding_requirements)
                else "fail"
            ),
            "source integrity, temporal validity, and support are distinct",
            observations=len(observations),
            valid_observations=valid_observations,
            requirements=len(grounding_requirements),
            passed_requirements=passed_requirements,
        )
    return {
        "coordination_summary": coordination,
        "action_summary": action_summary,
        "independence_summary": independence,
        "critique_summary": critique,
        "grounding_summary": grounding,
    }


_FAILURE_CODES = {
    "contract": "contract.invalid",
    "integrity": "integrity.invalid",
    "apparatus": "apparatus.incomplete",
    "treatment": "treatment.failed",
    "grader": "grader.invalid",
    "gate": "gate.failed",
    "authority": "authority.blocked",
    "reporting": "reporting.invalid",
}
_FAILURE_ID_FIELDS = (
    "family", "code", "evaluation_id", "plan_id", "entry_id",
    "case_id", "treatment_id", "repeat", "attempt", "dimension",
    "requirement_id", "fault_id", "gate_id", "principal_id",
    "handoff_id", "action_id", "observation_id", "finding_id",
    "locator", "reason_key",
)
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _failure_projection(failure: dict[str, Any]) -> dict[str, Any]:
    return {field: failure[field] for field in _FAILURE_ID_FIELDS}


def _failure_id(projection: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(projection)).hexdigest()
    return "sf-" + digest[:24]


def _finalize_v5_failures(
    failures: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    finalized: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for source in failures:
        failure = dict(source)
        family = failure.get("family")
        if _FAILURE_CODES.get(family) != failure.get("code"):
            raise ValueError("failure family/code pair is invalid")
        occurrence = failure.get("occurrence_count")
        if (
            not isinstance(occurrence, int)
            or isinstance(occurrence, bool)
            or occurrence < 1
        ):
            raise ValueError("failure occurrence_count must be positive")
        validate_locator(failure.get("locator"), artifacts)
        projection = _failure_projection(failure)
        identifier = _failure_id(projection)
        failure["failure_id"] = identifier
        prior = finalized.get(identifier)
        if prior is None:
            finalized[identifier] = (projection, failure)
            continue
        prior_projection, prior_failure = prior
        if prior_projection != projection:
            raise ValueError(f"failure ID collision: {identifier}")
        conflict_fields = (
            "severity", "evidence_state", "expected", "impact",
        )
        if any(
            prior_failure[field] != failure[field]
            for field in conflict_fields
        ):
            raise ValueError(
                f"failure projection collision has conflicting facts: {identifier}",
            )
        prior_failure["occurrence_count"] += occurrence
        for prose_field in ("observed", "retest"):
            prior_failure[prose_field] = min(
                prior_failure[prose_field], failure[prose_field],
            )
    return sorted(
        (item for _, item in finalized.values()),
        key=lambda item: (
            _SEVERITY_ORDER[item["severity"]],
            item["family"],
            item["code"],
            item["failure_id"],
        ),
    )


def _local_artifact(path: Path, *, encoding: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "resolved": path.resolve(),
        "encoding": encoding,
    }
    if encoding == "utf-8":
        text = path.read_text(encoding="utf-8")
        record.update({"text": text, "lines": text.splitlines()})
    return record


def _v5_failure_artifacts(
    plan_path: Path,
    evidence: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    artifacts = {
        plan_path.name: _local_artifact(plan_path, encoding="utf-8"),
    }
    for attempts in evidence["attempts"].values():
        for attempt in attempts:
            row = attempt["row"]
            artifacts[row["receipt"]["path"]] = _local_artifact(
                attempt["receipt_path"], encoding="utf-8",
            )
            for relative, record in attempt["artifacts"].items():
                logical = f"{row['artifact_dir']}/{relative}"
                if logical in artifacts:
                    raise ValueError(
                        f"duplicate failure artifact identity: {logical}",
                    )
                artifacts[logical] = record
    return artifacts


def _failure_base(
    *,
    family: str,
    severity: str,
    evidence_state: str,
    spec: dict[str, Any],
    plan: dict[str, Any],
    entry: dict[str, Any] | None,
    attempt: int | None,
    reason_key: str,
    locator: dict[str, Any],
    observed: str,
    expected: str,
    impact: str,
    retest: str,
) -> dict[str, Any]:
    return {
        "family": family,
        "code": _FAILURE_CODES[family],
        "severity": severity,
        "evidence_state": evidence_state,
        "evaluation_id": spec["evaluation_id"],
        "plan_id": plan["plan_id"],
        "entry_id": entry["entry_id"] if entry else None,
        "case_id": entry["case_id"] if entry else None,
        "treatment_id": entry["treatment_id"] if entry else None,
        "repeat": entry["repeat"] if entry else None,
        "attempt": attempt,
        "dimension": None,
        "requirement_id": None,
        "fault_id": None,
        "gate_id": None,
        "principal_id": None,
        "handoff_id": None,
        "action_id": None,
        "observation_id": None,
        "finding_id": None,
        "reason_key": reason_key,
        "locator": locator,
        "occurrence_count": 1,
        "observed": observed,
        "expected": expected,
        "impact": impact,
        "retest": retest,
    }


def _manual_review_input_binding(
    spec: dict[str, Any],
    spec_path: Path,
    plan_path: Path,
) -> dict[str, Any]:
    root = spec_path.parent.resolve(strict=True)

    def suite_file(field: str) -> tuple[Path, str] | None:
        reference = spec["suite"].get(field)
        if reference is None:
            return None
        if not isinstance(reference, dict) or set(reference) != {
            "path",
            "sha256",
        }:
            raise ValueError(f"suite {field} binding is invalid")
        _, path = resolve_contained_path(
            root,
            reference["path"],
            f"suite {field}",
            kind="file",
        )
        observed_hash = file_sha256(path)
        if observed_hash != reference["sha256"]:
            raise ValueError(f"suite {field} raw hash does not match")
        return path, observed_hash

    scenarios = suite_file("scenarios")
    quality_reference = suite_file("quality")
    calibration = suite_file("calibration")
    if scenarios is None or quality_reference is None:
        raise ValueError("manual review requires scenarios and suite quality")
    quality = load_json(quality_reference[0])
    proof_hashes: set[str] = set()
    for item in quality["raw_proofs"].values():
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError("suite quality raw proof binding is invalid")
        _, proof_path = resolve_contained_path(
            root,
            item["path"],
            "suite quality raw proof",
            kind="file",
        )
        if file_sha256(proof_path) != item["sha256"]:
            raise ValueError("suite quality raw proof hash does not match")
        proof_hashes.add(item["sha256"])
    if len(proof_hashes) != 1:
        raise ValueError("suite quality must bind one canonical raw proof")

    binding = {
        "schema_version": "manual-review-input-binding/1.0",
        "study_id": spec["evaluation_id"],
        "spec_content_hash": file_sha256(spec_path),
        "scenarios_content_hash": scenarios[1],
        "suite_quality_proof_content_hash": next(iter(proof_hashes)),
        "grader_calibration_content_hash": (
            calibration[1] if calibration is not None else None
        ),
        "execution_plan_content_hash": file_sha256(plan_path),
    }
    binding["binding_hash"] = canonical_sha256(binding)
    return binding


def _verify_v5_manual_review(
    reference: Path | None,
    spec: dict[str, Any],
    spec_path: Path,
    plan_path: Path,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    config = spec["authority"]["manual_review"]
    required = config["required"] is True
    if not required:
        if reference is not None:
            raise ValueError(
                "manual-review receipt is not declared by the evaluation contract",
            )
        return {
            "required": False,
            "status": "not_applicable",
            "decision": None,
            "receipt_hash": None,
        }, None
    if reference is None:
        return {
            "required": True,
            "status": "missing",
            "decision": None,
            "receipt_hash": None,
        }, {
            "reason_key": "required_manual_receipt_missing",
            "evidence_state": "missing",
            "observed": "no manual-review receipt was supplied",
        }

    try:
        normalized = normalize_relative_path(
            reference.as_posix(), "manual-review receipt",
        )
        _, artifacts_root = resolve_contained_path(
            spec_path.parent,
            spec["artifacts"]["root"],
            "spec artifacts root",
            kind="directory",
        )
        lexical_receipt = artifacts_root / normalized
        if lexical_receipt.is_symlink():
            raise ValueError("manual-review receipt must not be a symlink")
        _, receipt_path = resolve_contained_path(
            artifacts_root,
            normalized,
            "manual-review receipt",
            kind="file",
        )
        receipt = load_json(receipt_path)
        if set(receipt) != {
            "reviewer_role", "evidence", "decision", "signature",
        }:
            raise ValueError(
                "manual-review receipt fields differ from the exact contract",
            )
        if receipt["reviewer_role"] != config["role"]:
            raise ValueError("manual-review reviewer role mismatches the contract")
        if receipt["decision"] not in {"approve", "hold", "reject"}:
            raise ValueError("manual-review decision is invalid")
        if (
            not isinstance(receipt["signature"], str)
            or not receipt["signature"].strip()
        ):
            raise ValueError("manual-review signature attestation is empty")
        evidence = receipt["evidence"]
        if (
            not isinstance(evidence, list)
            or len(evidence) != 1
            or not isinstance(evidence[0], dict)
            or set(evidence[0]) != {"type", "artifact", "sha256"}
            or evidence[0]["type"] != "frozen-study-input-binding"
        ):
            raise ValueError(
                "manual-review evidence must contain exactly one input binding",
            )
        item = evidence[0]
        artifact = normalize_relative_path(
            item["artifact"], "manual-review input binding",
        )
        lexical_evidence = artifacts_root / artifact
        if lexical_evidence.is_symlink():
            raise ValueError("manual-review input binding must not be a symlink")
        _, evidence_path = resolve_contained_path(
            artifacts_root,
            artifact,
            "manual-review input binding",
            kind="file",
        )
        if item["sha256"] != file_sha256(evidence_path):
            raise ValueError("manual-review input binding hash mismatch")
        binding = load_json(evidence_path)
        if binding != _manual_review_input_binding(
            spec,
            spec_path,
            plan_path,
        ):
            raise ValueError("manual-review input binding owner mismatch")
        decision_projection = {
            "reviewer_role": receipt["reviewer_role"],
            "required_evidence": ["frozen-study-input-binding"],
        }
        if (
            config["decision_contract_hash"]
            != canonical_sha256(decision_projection)
        ):
            raise ValueError(
                "manual-review evidence types mismatch decision_contract_hash",
            )
        return {
            "required": True,
            "status": "complete",
            "decision": receipt["decision"],
            "receipt_hash": file_sha256(receipt_path),
        }, None
    except (OSError, ValueError, TypeError) as exc:
        return {
            "required": True,
            "status": "invalid",
            "decision": None,
            "receipt_hash": None,
        }, {
            "reason_key": "required_manual_receipt_invalid",
            "evidence_state": "invalid",
            "observed": str(exc),
        }


def _grader_failure_locator(
    attempt: dict[str, Any],
    requirement: dict[str, Any],
) -> dict[str, Any]:
    locator = attempt["record"]["grader_check_locators"].get(
        requirement["check_id"],
    )
    if locator is None:
        raise ValueError("failed requirement has no normalized grader check")
    artifact_dir = locator.get(
        "artifact_dir",
        attempt["row"]["artifact_dir"],
    )
    return {
        **{
            key: value for key, value in locator.items()
            if key != "artifact_dir"
        },
        "artifact": f"{artifact_dir}/{locator['artifact']}",
    }


def _derive_v5_failures(
    spec: dict[str, Any],
    plan: dict[str, Any],
    plan_path: Path,
    evidence: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    artifacts = _v5_failure_artifacts(plan_path, evidence)
    raw: list[dict[str, Any]] = []
    entries = {
        entry["entry_id"]: (index, entry)
        for index, entry in enumerate(plan["entries"])
    }
    issue_entry_ids = {
        item["entry"]["entry_id"] for item in evidence["receipt_issues"]
    }
    for position, entry in enumerate(plan["entries"]):
        if entry["disposition"] == "execute":
            continue
        reason_key = (
            "capability_unsupported"
            if entry["disposition"] == "unsupported"
            else "capability_probe_unknown"
        )
        raw.append(_failure_base(
            family="apparatus",
            severity="medium",
            evidence_state="verified",
            spec=spec,
            plan=plan,
            entry=entry,
            attempt=None,
            reason_key=reason_key,
            locator={
                "kind": "json_pointer",
                "artifact": plan_path.name,
                "json_pointer": f"/entries/{position}/feasibility/derived_status",
            },
            observed=f"entry disposition is {entry['disposition']}",
            expected="feasible execution for contribution inference",
            impact="entry is excluded from the treatment denominator",
            retest="satisfy the bound capability probe and recompile the plan",
        ))
    for entry_id in evidence["missing_entries"]:
        if entry_id in issue_entry_ids:
            continue
        position, entry = entries[entry_id]
        raw.append(_failure_base(
            family="apparatus",
            severity="high",
            evidence_state="missing",
            spec=spec,
            plan=plan,
            entry=entry,
            attempt=None,
            reason_key="required_execute_receipt_missing",
            locator={
                "kind": "json_pointer",
                "artifact": plan_path.name,
                "json_pointer": f"/entries/{position}",
            },
            observed="no valid terminal receipt is indexed",
            expected="exactly one valid terminal receipt for the execute entry",
            impact="the required execution matrix is incomplete",
            retest="resume or rerun the bound execute entry",
        ))
    for issue in evidence["receipt_issues"]:
        position, entry = entries[issue["entry"]["entry_id"]]
        invalid = issue["status"] == "invalid"
        raw.append(_failure_base(
            family="integrity" if invalid else "apparatus",
            severity="critical" if invalid else "high",
            evidence_state="invalid" if invalid else "missing",
            spec=spec,
            plan=plan,
            entry=entry,
            attempt=issue["row"]["attempt"],
            reason_key=(
                "receipt_evidence_invalid"
                if invalid
                else "receipt_evidence_missing"
            ),
            locator={
                "kind": "json_pointer",
                "artifact": plan_path.name,
                "json_pointer": f"/entries/{position}",
            },
            observed=issue["issue"],
            expected="a schema-valid hash-bound terminal receipt",
            impact="the attempt cannot enter treatment inference",
            retest="restore or regenerate the immutable bound receipt evidence",
        ))
    for entry_id in evidence["duplicate_terminal_entries"]:
        position, entry = entries[entry_id]
        raw.append(_failure_base(
            family="integrity",
            severity="critical",
            evidence_state="invalid",
            spec=spec,
            plan=plan,
            entry=entry,
            attempt=None,
            reason_key="duplicate_valid_terminal_receipt",
            locator={
                "kind": "json_pointer",
                "artifact": plan_path.name,
                "json_pointer": f"/entries/{position}",
            },
            observed="multiple valid terminal receipts are indexed",
            expected="one valid terminal receipt for the execute entry",
            impact="the selected treatment outcome is ambiguous",
            retest="repair the append-only attempt index before analysis",
        ))
    for entry_id, attempts in evidence["attempts"].items():
        _, entry = entries[entry_id]
        for attempt in attempts:
            receipt = attempt["receipt"]
            if receipt["run"]["valid"] is True:
                continue
            raw.append(_failure_base(
                family="apparatus",
                severity="high",
                evidence_state="verified",
                spec=spec,
                plan=plan,
                entry=entry,
                attempt=attempt["row"]["attempt"],
                reason_key="attempt_invalid",
                locator={
                    "kind": "json_pointer",
                    "artifact": attempt["row"]["receipt"]["path"],
                    "json_pointer": "/run/valid",
                },
                observed="attempt is retained with valid=false",
                expected="a valid terminal attempt for the execute entry",
                impact="attempt is excluded from treatment inference",
                retest="inspect apparatus evidence and execute a declared retry",
            ))
    for entry_id, attempt in evidence["selected_attempts"].items():
        _, entry = entries[entry_id]
        record = next(
            item for item in evidence["records"]
            if item["run_id"] == attempt["receipt"]["run"]["run_id"]
        )
        requirements = {
            item["requirement_id"]: item
            for item in entry["execute_case_payload"]["case"]["requirements"]
        }
        for requirement_id in record["hard_gate_failures"]:
            requirement = requirements[requirement_id]
            locator = (
                {
                    "kind": "json_pointer",
                    "artifact": attempt["row"]["receipt"]["path"],
                    "json_pointer": "/run/terminal",
                }
                if (
                    requirement["dimension"] == "outcome"
                    and attempt["receipt"]["run"]["terminal"] != "completed"
                )
                else _grader_failure_locator(attempt, requirement)
            )
            failure = _failure_base(
                family="treatment",
                severity=(
                    "critical"
                    if requirement["dimension"] == "safety"
                    and requirement["safety_severity"] == "critical"
                    else "high"
                ),
                evidence_state="verified",
                spec=spec,
                plan=plan,
                entry=entry,
                attempt=attempt["row"]["attempt"],
                reason_key="required_treatment_requirement_failed",
                locator=locator,
                observed=f"required {requirement['dimension']} evidence failed",
                expected="required treatment evidence passes",
                impact="candidate usefulness cannot be supported",
                retest="rerun the frozen entry after correcting treatment behavior",
            )
            failure["dimension"] = requirement["dimension"]
            failure["requirement_id"] = requirement_id
            raw.append(failure)
    return _finalize_v5_failures(raw, artifacts), artifacts


def _derive_v5_gate_failures(
    spec: dict[str, Any],
    plan: dict[str, Any],
    spec_path: Path,
    metric_analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for position, result in enumerate(metric_analysis["gate_results"]):
        gate = result["gate"]
        if gate["required"] is not True or result["status"] == "pass":
            continue
        if spec["level"] in {"L0", "L1"} and result["status"] == "not_evaluable":
            continue
        failure = _failure_base(
            family="gate",
            severity="high",
            evidence_state="verified",
            spec=spec,
            plan=plan,
            entry=None,
            attempt=None,
            reason_key=(
                "required_gate_failed"
                if result["status"] == "fail"
                else "required_gate_not_evaluable"
            ),
            locator={
                "kind": "json_pointer",
                "artifact": spec_path.name,
                "json_pointer": f"/hard_gates/{position}",
            },
            observed=(
                f"gate status={result['status']}; "
                f"observed={result['observed']!r}"
            ),
            expected=(
                f"{gate['metric']} {gate['direction']} {gate['threshold']!r}"
            ),
            impact="the declared usefulness decision is blocked",
            retest="produce complete bound evidence and reevaluate the frozen gate",
        )
        failure["gate_id"] = gate["gate_id"]
        failures.append(failure)
    if metric_analysis["baseline_ceiling"]:
        primary = spec["analysis"]["estimands"][0]
        failure = _failure_base(
            family="gate",
            severity="medium",
            evidence_state="verified",
            spec=spec,
            plan=plan,
            entry=None,
            attempt=None,
            reason_key="baseline_headroom_insufficient",
            locator={
                "kind": "json_pointer",
                "artifact": spec_path.name,
                "json_pointer": "/analysis/materiality/minimum_cases",
            },
            observed=(
                f"baseline failure cases="
                f"{len(metric_analysis['comparator_failure_cases'])}"
            ),
            expected=(
                f"at least "
                f"{spec['analysis']['materiality'].get('minimum_cases', 0)} "
                f"baseline failure cases"
            ),
            impact="the candidate contribution is inconclusive at the ceiling",
            retest="evaluate the frozen estimand on cases with declared headroom",
        )
        matching_gate = next(
            (
                gate for gate in spec["hard_gates"]
                if gate["metric"] == primary["metric"]
            ),
            None,
        )
        failure["gate_id"] = (
            matching_gate["gate_id"] if matching_gate else None
        )
        failures.append(failure)
    return failures


def _derive_v5_manual_failure(
    spec: dict[str, Any],
    plan: dict[str, Any],
    spec_path: Path,
    manual: dict[str, Any],
    issue: dict[str, str] | None,
) -> list[dict[str, Any]]:
    if manual["required"] is not True:
        return []
    if issue is None and manual["decision"] == "approve":
        return []
    reason_key = (
        issue["reason_key"]
        if issue is not None
        else f"manual_decision_{manual['decision']}"
    )
    evidence_state = (
        issue["evidence_state"] if issue is not None else "verified"
    )
    observed = (
        issue["observed"]
        if issue is not None
        else f"manual decision is {manual['decision']}"
    )
    failure = _failure_base(
        family="authority",
        severity="high",
        evidence_state=evidence_state,
        spec=spec,
        plan=plan,
        entry=None,
        attempt=None,
        reason_key=reason_key,
        locator={
            "kind": "json_pointer",
            "artifact": spec_path.name,
            "json_pointer": "/authority/manual_review",
        },
        observed=observed,
        expected="a valid approving manual-authority receipt",
        impact="the declared final authority remains blocked",
        retest="supply a hash-bound receipt satisfying the frozen decision contract",
    )
    manual_gate = next(
        (
            gate for gate in spec["hard_gates"]
            if gate["kind"] == "manual"
        ),
        None,
    )
    failure["gate_id"] = manual_gate["gate_id"] if manual_gate else None
    return [failure]


def _v5_failure_index(
    spec: dict[str, Any],
    plan: dict[str, Any],
    failures: list[dict[str, Any]],
    *,
    view: str,
) -> dict[str, Any]:
    budget = (
        len(failures)
        if view == "full"
        else spec["artifacts"]["failure_index_budget"]
    )
    shown = failures[:budget]
    family_counts = dict(sorted(Counter(
        failure["family"] for failure in failures
    ).items()))
    severity_counts = dict(sorted(Counter(
        failure["severity"] for failure in failures
    ).items()))
    result = {
        "schema_version": 1,
        "view": view,
        "failure_index_hash": "sha256:" + "0" * 64,
        "evaluation_id": spec["evaluation_id"],
        "plan_id": plan["plan_id"],
        "item_count": len(failures),
        "shown_count": len(shown),
        "omitted_count": len(failures) - len(shown),
        "truncated": len(shown) != len(failures),
        "family_counts": family_counts,
        "severity_counts": severity_counts,
        "failures": shown,
    }
    result["failure_index_hash"] = canonical_self_hash(
        result, "failure_index_hash",
    )
    return result


def _v5_summary_base(
    spec: dict[str, Any],
    plan: dict[str, Any],
    evidence: dict[str, Any],
    failures: list[dict[str, Any]],
    manual: dict[str, Any],
    bound_evidence: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    dispositions = Counter(
        entry["disposition"] for entry in plan["entries"]
    )
    evidence_complete = not (
        evidence["missing_entries"]
        or evidence["duplicate_terminal_entries"]
        or evidence["receipt_issues"]
    )
    evidence_status = (
        "invalid"
        if (
            evidence["duplicate_terminal_entries"]
            or any(
                item["status"] == "invalid"
                for item in evidence["receipt_issues"]
            )
        )
        else "incomplete"
        if (
            evidence["missing_entries"]
            or evidence["receipt_issues"]
        )
        else "complete"
    )
    feasibility = (
        "not_evaluable"
        if dispositions["not_evaluable"]
        else "unsupported"
        if dispositions["unsupported"]
        else "feasible"
    )
    manual_required = manual["required"]
    records = evidence["records"]
    module_summaries = _v5_module_summaries(
        spec, plan, evidence, evidence_complete,
    )
    context_cost = _v5_context_cost(spec, plan, records)
    metric_analysis = _v5_metric_analysis(
        spec,
        plan,
        records,
        evidence_status=evidence_status,
        feasibility_status=feasibility,
        manual_authority=manual,
        suite_quality_status=bound_evidence["quality_status"],
        calibration_status=bound_evidence["calibration_status"],
        module_summaries=module_summaries,
        context_cost=context_cost,
    )
    usefulness = metric_analysis["usefulness_status"]
    final_authority = (
        "eligible"
        if (
            spec["level"] in {"L0", "L1"}
            and evidence_status == "complete"
            and feasibility == "feasible"
            and (
                not manual_required
                or (
                    manual["status"] == "complete"
                    and manual["decision"] == "approve"
                )
            )
        )
        or (
            usefulness == "supported"
            and feasibility == "feasible"
            and (
                not manual_required
                or (
                    manual["status"] == "complete"
                    and manual["decision"] == "approve"
                )
            )
        )
        else "blocked"
    )
    special_summaries = _v5_special_summaries(
        spec, plan, evidence, bound_evidence,
    )
    summary = {
        "schema_version": 4,
        "summary_hash": "sha256:" + "0" * 64,
        "evaluation_id": spec["evaluation_id"],
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "spec_hash": plan["spec_hash"],
        "scenario_corpus_hash": plan["scenario_corpus_hash"],
        "host_manifest_hash": plan["host_manifest_hash"],
        "analysis_ready": evidence_complete,
        "subject": {
            "skill_id": spec["subject"]["skill_id"],
            "version": spec["subject"]["version"],
            "shape": spec["subject"]["shape"],
            "package_hash": plan["package_hashes"][
                spec["subject"]["skill_id"]
            ],
        },
        "modules": plan["module_decisions"],
        "treatments": plan["treatments"],
        "applicability_status": (
            "applicable"
            if any(
                item["status"] == "required"
                for item in plan["module_decisions"]
            )
            else "not_applicable"
        ),
        "feasibility_status": feasibility,
        "evidence_status": evidence_status,
        "usefulness_status": usefulness,
        "final_authority_status": final_authority,
        "counts": {
            "plan_entries": len(plan["entries"]),
            "execute_entries": dispositions["execute"],
            "unsupported_entries": dispositions["unsupported"],
            "not_evaluable_entries": dispositions["not_evaluable"],
            "attempts": evidence["attempt_count"],
            "valid_terminal_attempts": len(records),
            "invalid_attempts": evidence["invalid_attempts"],
            "missing_entries": len(evidence["missing_entries"]),
        },
        "primary_benefit": metric_analysis["primary_benefit"],
        "paired_metrics": metric_analysis["paired_metrics"],
        "module_summaries": module_summaries,
        "stage_summaries": _v5_stage_summaries(
            spec, plan, evidence,
        ),
        **special_summaries,
        "context_cost": context_cost,
        "suite_quality_status": bound_evidence["quality_status"],
        "calibration_status": bound_evidence["calibration_status"],
        "manual_authority": manual,
        "blocking_observations": sorted({
            failure["reason_key"] for failure in failures
        } | ({
            "baseline_headroom_insufficient"
        } if metric_analysis["baseline_ceiling"] else set())),
        "output_manifest": {
            "details": None,
            "failure_index": {},
            "markdown": None,
        },
        "trust_boundaries": [
            {
                "surface": "plan-index-receipt",
                "status": "locally_verified",
                "reason": "schema, identity, provenance, hashes, and artifacts verified",
            },
        ],
        "representative_failure_ids": [
            failure["failure_id"] for failure in failures[:10]
        ],
    }
    return summary, metric_analysis


def _relative_output_path(path: Path, root: Path) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise ValueError(
            "all sibling report views must be contained by the summary directory",
        ) from None
    return normalize_relative_path(relative, "report view")


def _output_view(
    path: Path,
    payload: bytes,
    *,
    root: Path,
    version: str,
    item_count: int,
    shown_count: int,
    omitted_count: int,
    truncated: bool,
    family_counts: dict[str, int],
    severity_counts: dict[str, int],
) -> dict[str, Any]:
    return {
        "path": _relative_output_path(path, root),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
        "schema_or_view_version": version,
        "item_count": item_count,
        "shown_count": shown_count,
        "omitted_count": omitted_count,
        "truncated": truncated,
        "family_counts": family_counts,
        "severity_counts": severity_counts,
    }


def _render_v5_markdown(
    summary: dict[str, Any],
    failure_index: dict[str, Any],
) -> bytes:
    lines = [
        f"# Skill evaluation: {summary['evaluation_id']}",
        "",
        f"- Plan: `{summary['plan_id']}`",
        f"- Analysis ready: `{str(summary['analysis_ready']).lower()}`",
        f"- Applicability: `{summary['applicability_status']}`",
        f"- Feasibility: `{summary['feasibility_status']}`",
        f"- Evidence: `{summary['evidence_status']}`",
        f"- Usefulness: `{summary['usefulness_status']}`",
        f"- Final authority: `{summary['final_authority_status']}`",
        "",
        "## Failures",
        "",
    ]
    if failure_index["failures"]:
        lines.extend(
            f"- `{item['failure_id']}` {item['code']}: {item['reason_key']}"
            for item in failure_index["failures"]
        )
    else:
        lines.append("- None.")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"output path is not a regular file: {path}")
        if path.read_bytes() != payload:
            raise FileExistsError(
                f"refusing to overwrite different immutable output: {path}",
            )
        return
    atomic_write_bytes(path, payload)


def _commit_v5_outputs(
    summary: dict[str, Any],
    failure_index: dict[str, Any],
    *,
    failure_details: dict[str, Any] | None,
    summary_path: Path,
    failure_path: Path,
    markdown_path: Path | None,
    details_path: Path | None,
    registry: dict[str, dict[str, Any]],
) -> None:
    root = summary_path.parent
    failure_payload = canonical_json_bytes(failure_index)
    details_payload = (
        canonical_json_bytes(failure_details)
        if failure_details is not None
        else None
    )
    markdown_payload = (
        _render_v5_markdown(summary, failure_index)
        if markdown_path is not None
        else None
    )
    index_counts = {
        "item_count": failure_index["item_count"],
        "shown_count": failure_index["shown_count"],
        "omitted_count": failure_index["omitted_count"],
        "truncated": failure_index["truncated"],
        "family_counts": failure_index["family_counts"],
        "severity_counts": failure_index["severity_counts"],
    }
    detail_counts = (
        {
            "item_count": failure_details["item_count"],
            "shown_count": failure_details["shown_count"],
            "omitted_count": failure_details["omitted_count"],
            "truncated": failure_details["truncated"],
            "family_counts": failure_details["family_counts"],
            "severity_counts": failure_details["severity_counts"],
        }
        if failure_details is not None
        else None
    )
    summary["output_manifest"] = {
        "details": (
            _output_view(
                details_path,
                details_payload,
                root=root,
                version="failure-index-v1/full",
                **detail_counts,
            )
            if (
                details_path is not None
                and details_payload is not None
                and detail_counts is not None
            )
            else None
        ),
        "failure_index": _output_view(
            failure_path,
            failure_payload,
            root=root,
            version="failure-index-v1/index",
            **index_counts,
        ),
        "markdown": (
            _output_view(
                markdown_path,
                markdown_payload,
                root=root,
                version="markdown-v1",
                **index_counts,
            )
            if markdown_path is not None and markdown_payload is not None
            else None
        ),
    }
    summary["summary_hash"] = canonical_self_hash(summary, "summary_hash")
    summary_payload = canonical_json_bytes(summary)
    diagnostics = validate_v5_schema(
        summary, "analysis-summary-v4.schema.json", registry,
    )
    if diagnostics:
        raise ValueError(_first_v5_diagnostic(diagnostics))
    for value in (failure_index, failure_details):
        if value is None:
            continue
        diagnostics = validate_v5_schema(
            value, "failure-index-v1.schema.json", registry,
        )
        if diagnostics:
            raise ValueError(_first_v5_diagnostic(diagnostics))

    outputs = [
        pair for pair in (
            (details_path, details_payload),
            (failure_path, failure_payload),
            (markdown_path, markdown_payload),
            (summary_path, summary_payload),
        )
        if pair[0] is not None and pair[1] is not None
    ]
    resolved = [path.resolve() for path, _ in outputs]
    if len(resolved) != len(set(resolved)):
        raise ValueError("report output paths must be distinct")
    for path, payload in outputs:
        if path.exists() and (
            path.is_symlink()
            or not path.is_file()
            or path.read_bytes() != payload
        ):
            raise FileExistsError(
                f"refusing to overwrite different immutable output: {path}",
            )
    for path, payload in outputs:
        _write_immutable(path, payload)


def _release_bound_path(
    binding: dict[str, Any],
    field: str,
) -> Path:
    reference = binding.get(field)
    if (
        not isinstance(reference, dict)
        or set(reference) != {"path", "sha256"}
        or not isinstance(reference["path"], (str, Path))
        or not isinstance(reference["sha256"], str)
        or SHA256_RE.fullmatch(reference["sha256"]) is None
    ):
        raise ValueError(f"{field} release binding is invalid")
    path = Path(reference["path"])
    if not path.is_absolute() or path.is_symlink():
        raise ValueError(f"{field} release path must be absolute and non-symlinked")
    resolved = path.resolve(strict=True)
    if path.absolute() != resolved or not resolved.is_file():
        raise ValueError(f"{field} release path contains a substituted component")
    if file_sha256(resolved) != reference["sha256"]:
        raise ValueError(f"{field} release binding hash mismatch")
    return resolved


def _release_treatment_id(spec: dict[str, Any], role: str) -> str:
    matches = [
        item["treatment_id"]
        for item in spec["treatments"]
        if item["causal_role"] == role
    ]
    if len(matches) != 1:
        raise ValueError(f"release study requires exactly one {role} treatment")
    return matches[0]


def _release_context_efficiency(
    spec: dict[str, Any],
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int]:
    candidate = _release_treatment_id(spec, "candidate")
    selected = [
        record
        for record in records
        if record["variant"] == candidate and record["should_trigger"] is True
    ]
    attributed = sum(
        record["context_usage"]["attributed"] is True for record in selected
    )
    fields = {
        "controlled_context_bytes": "controlled_bytes",
        "total_context_bytes": "bytes",
        "host_integration_duplicate_bytes": "host_integration_duplicate_bytes",
        "unexplained_repeated_static_content_bytes": (
            "unexplained_repeated_static_content_bytes"
        ),
        "protocol_output_bytes": "protocol_output_bytes",
        "failed_command_output_bytes": "failed_command_output_bytes",
    }
    if not selected or attributed != len(selected):
        return None, attributed
    result: dict[str, Any] = {}
    for output_field, source_field in fields.items():
        values = [
            record["context_usage"].get(source_field)
            for record in selected
        ]
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in values
        ):
            return None, attributed
        result[output_field] = {
            "evidence_artifact_kind": "report_local",
            "p50": nearest_rank(values, 0.50),
            "p95": nearest_rank(values, 0.95),
            "max": max(values),
        }
    return result, attributed


def _load_release_study(binding: dict[str, Any]) -> dict[str, Any]:
    expected_fields = {
        "study_id",
        "spec",
        "plan",
        "index",
        "summary",
        "failure_index",
        "manual_receipt_locator",
    }
    if set(binding) != expected_fields or not isinstance(
        binding["study_id"],
        str,
    ):
        raise ValueError("release study binding fields are invalid")
    locator = binding["manual_receipt_locator"]
    if locator is not None and not isinstance(locator, str):
        raise ValueError("manual receipt locator must be a relative POSIX string")

    paths = {
        field: _release_bound_path(binding, field)
        for field in (
            "spec",
            "plan",
            "index",
            "summary",
            "failure_index",
        )
    }
    spec, _, _, discovered_plan_path, plan, registry = (
        _load_v5_analysis_inputs(paths["spec"], paths["index"])
    )
    if discovered_plan_path != paths["plan"]:
        raise ValueError("release plan binding is not the canonical index owner")
    bound_evidence = _load_v5_bound_evidence(
        spec,
        paths["spec"],
        registry,
    )
    index_rows = _load_v5_index(paths["index"], plan, registry)
    _, artifacts_root = resolve_contained_path(
        paths["plan"].parent,
        plan["artifacts"]["root"],
        "plan artifacts root",
    )
    evidence = _collect_v5_evidence(
        index_rows,
        artifacts_root=artifacts_root,
        plan=plan,
        spec=spec,
        registry=registry,
        bound_evidence=bound_evidence,
    )
    manual, _ = _verify_v5_manual_review(
        Path(locator) if locator is not None else None,
        spec,
        paths["spec"],
        paths["plan"],
    )

    summary = load_json(paths["summary"])
    failure_index = load_json(paths["failure_index"])
    for document, schema_name, hash_field, path in (
        (
            summary,
            "analysis-summary-v4.schema.json",
            "summary_hash",
            paths["summary"],
        ),
        (
            failure_index,
            "failure-index-v1.schema.json",
            "failure_index_hash",
            paths["failure_index"],
        ),
    ):
        diagnostics = validate_v5_schema(document, schema_name, registry)
        if diagnostics or not verify_self_hash(document, hash_field):
            raise ValueError(f"{schema_name} release artifact is invalid")
        if path.read_bytes() != canonical_json_bytes(document):
            raise ValueError(f"{schema_name} is not canonical JSON")

    failure_view = summary["output_manifest"]["failure_index"]
    _, manifested_failure = resolve_contained_path(
        paths["summary"].parent,
        failure_view["path"],
        "summary failure-index view",
        kind="file",
    )
    if (
        summary["output_manifest"]["details"] is not None
        or summary["output_manifest"]["markdown"] is not None
        or manifested_failure != paths["failure_index"]
        or failure_view["sha256"] != file_sha256(paths["failure_index"])
        or failure_view["item_count"] != failure_index["item_count"]
        or failure_view["shown_count"] != failure_index["shown_count"]
        or failure_view["omitted_count"] != failure_index["omitted_count"]
        or failure_view["truncated"] != failure_index["truncated"]
        or failure_view["family_counts"] != failure_index["family_counts"]
        or failure_view["severity_counts"] != failure_index["severity_counts"]
    ):
        raise ValueError("summary does not bind the canonical failure index")

    expected_context_cost = _v5_context_cost(
        spec,
        plan,
        evidence["records"],
    )
    expected_summary_counts = {
        "plan_entries": len(plan["entries"]),
        "execute_entries": sum(
            entry["disposition"] == "execute" for entry in plan["entries"]
        ),
        "attempts": evidence["attempt_count"],
        "valid_terminal_attempts": len(evidence["records"]),
        "invalid_attempts": evidence["invalid_attempts"],
        "missing_entries": len(evidence["missing_entries"]),
    }
    if (
        summary["evaluation_id"] != spec["evaluation_id"]
        or summary["plan_id"] != plan["plan_id"]
        or summary["plan_hash"] != plan["plan_hash"]
        or summary["spec_hash"] != plan["spec_hash"]
        or failure_index["evaluation_id"] != spec["evaluation_id"]
        or failure_index["plan_id"] != plan["plan_id"]
        or any(
            summary["counts"].get(field) != value
            for field, value in expected_summary_counts.items()
        )
        or summary["manual_authority"] != manual
        or summary["context_cost"] != expected_context_cost
    ):
        raise ValueError("release summary differs from verified native evidence")

    retryable = set(
        spec["execution"]["retry_policy"]["retryable_apparatus_classes"],
    )
    invalid_history = 0
    retried_entries = 0
    for entry_id, attempts in evidence["attempts"].items():
        if len(attempts) > 1:
            retried_entries += 1
        selected = evidence["selected_attempts"].get(entry_id)
        for attempt in attempts:
            if attempt is selected:
                continue
            run = attempt["receipt"]["run"]
            if (
                attempt["analysis_error"] is not None
                or run["valid"] is not False
                or run["completion_origin"] != "resume_seal"
                or run["terminal"] not in retryable
            ):
                invalid_history += 1

    invalid_tokens = any(
        not isinstance(record.get(field), int)
        or isinstance(record.get(field), bool)
        or record[field] < 0
        for record in evidence["records"]
        for field in ("tokens_in", "tokens_out")
    )
    context, attributed_count = _release_context_efficiency(
        spec,
        evidence["records"],
    )
    _, candidate_entry = resolve_contained_path(
        paths["spec"].parent,
        f"{spec['subject']['package']['path']}/SKILL.md",
        "release candidate skill entry",
        kind="file",
    )
    if context is not None:
        entry_bytes = candidate_entry.stat().st_size
        context["candidate_entry_bytes"] = {
            "evidence_artifact_kind": "native_artifact",
            "p50": entry_bytes,
            "p95": entry_bytes,
            "max": entry_bytes,
        }
    reason_codes = sorted({
        *({"missing_terminal_entry"} if evidence["missing_entries"] else set()),
        *(
            {"duplicate_terminal_entry"}
            if evidence["duplicate_terminal_entries"]
            else set()
        ),
        *({"receipt_issue"} if evidence["receipt_issues"] else set()),
        *({"invalid_retry_history"} if invalid_history else set()),
        *({"invalid_token_usage"} if invalid_tokens else set()),
        *({"context_attribution_incomplete"} if context is None else set()),
        *(
            {"manual_authority_invalid"}
            if manual["status"] in {"missing", "invalid"}
            else set()
        ),
    })
    selected_receipts = [
        {
            "entry_id": entry_id,
            "receipt_hash": file_sha256(attempt["receipt_path"]),
        }
        for entry_id, attempt in sorted(evidence["selected_attempts"].items())
    ]
    public = {
        "identity": {
            "evaluation_id": spec["evaluation_id"],
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "spec_content_hash": binding["spec"]["sha256"],
            "plan_content_hash": binding["plan"]["sha256"],
            "index_content_hash": binding["index"]["sha256"],
            "summary_content_hash": binding["summary"]["sha256"],
            "failure_index_content_hash": binding["failure_index"]["sha256"],
            "selected_receipt_set_hash": canonical_sha256(selected_receipts),
        },
        "manual": manual,
        "completeness": {
            "status": "complete" if not reason_codes else "invalid",
            "expected_entry_count": expected_summary_counts["execute_entries"],
            "selected_entry_count": len(evidence["selected_attempts"]),
            "missing_entry_ids": sorted(evidence["missing_entries"]),
            "duplicate_terminal_entry_ids": sorted(
                evidence["duplicate_terminal_entries"],
            ),
            "invalid_attempt_count": evidence["invalid_attempts"],
            "retried_entry_count": retried_entries,
            "receipt_issue_count": len(evidence["receipt_issues"]),
            "selected_record_count": len(evidence["records"]),
            "attributed_context_record_count": attributed_count,
            "reason_codes": reason_codes,
        },
        "context_efficiency": (
            context
            if (
                context is not None
                and set(reason_codes).issubset({"manual_authority_invalid"})
            )
            else None
        ),
    }
    return {
        "public": public,
        "spec": spec,
        "plan": plan,
        "evidence": evidence,
    }


def _release_records_for_role(
    loaded: dict[str, Any],
    role: str,
) -> list[dict[str, Any]]:
    treatment_id = _release_treatment_id(loaded["spec"], role)
    return [
        record for record in loaded["evidence"]["records"]
        if record["variant"] == treatment_id
    ]


def _release_max(
    records: list[dict[str, Any]],
    container: str,
    field: str,
) -> int:
    values = []
    for record in records:
        value_container = record.get(container)
        if not isinstance(value_container, dict) or field not in value_container:
            raise ValueError(f"release metric {container}.{field} is missing")
        values.append(value_container[field])
    if any(
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for value in values
    ):
        raise ValueError(f"release metric {container}.{field} is invalid")
    return max(values, default=0)


def _release_failure_cases(
    records: list[dict[str, Any]],
) -> set[str]:
    by_case: dict[str, list[bool]] = defaultdict(list)
    for record in records:
        by_case[record["case_id"]].append(
            record["valid"] is True and record["task_pass"] is True,
        )
    return {
        case_id for case_id, values in by_case.items()
        if not values or not all(values)
    }


def _release_context_scalars(public: dict[str, Any]) -> dict[str, int]:
    context = public["context_efficiency"]
    if not isinstance(context, dict):
        raise ValueError("release context efficiency is unavailable")
    fields = {
        "candidate_entry_bytes_p95": ("candidate_entry_bytes", "p95"),
        "controlled_context_bytes_p95": (
            "controlled_context_bytes",
            "p95",
        ),
        "total_context_bytes_p95": ("total_context_bytes", "p95"),
        "host_integration_duplicate_bytes_max": (
            "host_integration_duplicate_bytes",
            "max",
        ),
        "unexplained_repeated_bytes_max": (
            "unexplained_repeated_static_content_bytes",
            "max",
        ),
        "protocol_output_bytes_max": ("protocol_output_bytes", "max"),
        "failed_command_output_bytes_max": (
            "failed_command_output_bytes",
            "max",
        ),
    }
    result = {}
    for output, (metric, selector) in fields.items():
        value = context.get(metric, {}).get(selector)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"release context metric is invalid: {metric}")
        result[output] = value
    return result


def _release_projection_ready(
    public: dict[str, Any],
    *,
    allow_missing_manual: bool,
) -> bool:
    """Allow D0 report-only data while preserving invalid manual receipts."""
    completeness = public["completeness"]
    return (
        completeness["status"] == "complete"
        or (
            allow_missing_manual
            and
            completeness["reason_codes"] == ["manual_authority_invalid"]
            and public["manual"]["status"] == "missing"
        )
    )


def _sqw_release_metrics(
    loaded: dict[str, Any],
    *,
    confidence_level: float,
    bootstrap_iterations: int,
    random_seed: int,
) -> dict[str, Any]:
    spec = loaded["spec"]
    records = loaded["evidence"]["records"]
    candidate_id = _release_treatment_id(spec, "candidate")
    baseline_id = _release_treatment_id(spec, "baseline")
    candidate = _release_records_for_role(loaded, "candidate")
    baseline = _release_records_for_role(loaded, "baseline")
    comparator_ids = {
        item["treatment_id"]
        for item in spec["treatments"]
        if item["causal_role"] == "comparator"
    }
    non_target = [
        record for record in records
        if record["variant"] in comparator_ids
    ]
    baseline_failures = _release_failure_cases(baseline)
    candidate_failures = _release_failure_cases(candidate)
    task_effect = summarize_paired_metric(
        records,
        comparator=baseline_id,
        candidate=candidate_id,
        metric="task_pass_rate",
        direction="higher_is_better",
        effect="relative",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed + 11,
    )
    prior_ids = [
        item["treatment_id"]
        for item in spec["treatments"]
        if item["causal_role"] == "prior"
    ]
    prior_effect = (
        summarize_paired_metric(
            records,
            comparator=prior_ids[0],
            candidate=candidate_id,
            metric="controlled_core_skill_context_bytes",
            direction="lower_is_better",
            effect="relative",
            confidence_level=confidence_level,
            bootstrap_iterations=bootstrap_iterations,
            random_seed=random_seed + 10,
        )
        if len(prior_ids) == 1
        else None
    )
    prewrite = summarize_paired_cost_delta(
        records,
        comparator=baseline_id,
        candidate=candidate_id,
        metric="executor_prewrite_tool_output_bytes",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed + 12,
    )
    non_target_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in non_target:
        non_target_by_case[record["case_id"]].append(record)
    correct_no_load = sum(
        bool(rows)
        and all(
            row["task_pass"] is True
            and row["skill_body_loaded"] is False
            and row["skill_incorporated"] is False
            and row["skill_applied"] is False
            for row in rows
        )
        for rows in non_target_by_case.values()
    )
    metrics = {
        **_release_context_scalars(loaded["public"]),
        "unattributed_residue_bytes_max": _release_max(
            candidate,
            "context_usage",
            "unattributed_residue_bytes",
        ),
        "prior_controlled_context_reduction": prior_effect,
        "critical_failures": sum(
            record["critical_safety_incidents"] for record in candidate
        ),
        "candidate_only_failures": len(
            candidate_failures - baseline_failures,
        ),
        "non_target_skill_loads": sum(
            record["skill_body_loaded"]
            or record["skill_incorporated"]
            or record["skill_applied"]
            for record in non_target
        ),
        "non_target_correct_no_load": {
            "numerator": correct_no_load,
            "denominator": len(non_target_by_case),
        },
        "baseline_failures": len(baseline_failures),
        "resolved_baseline_failures": len(
            baseline_failures - candidate_failures,
        ),
        "candidate_failures": len(candidate_failures),
        "candidate_failure_ratio": (
            len(candidate_failures) / len(baseline_failures)
            if baseline_failures else 0.0
        ),
        "task_pass_relative_effect": task_effect,
        "prewrite_overhead": prewrite,
    }
    return metrics


def _writing_plans_release_metrics(
    planner: dict[str, Any],
    transfer: dict[str, Any],
    arm_map: dict[str, dict[str, Any]],
    *,
    prior_context: dict[str, Any] | None,
    matched_tokens: dict[str, Any],
    confidence_level: float,
    bootstrap_iterations: int,
    random_seed: int,
) -> dict[str, Any]:
    planner_records = planner["evidence"]["records"]
    planner_spec = planner["spec"]
    candidate_planner_id = _release_treatment_id(
        planner_spec,
        "candidate",
    )
    baseline_planner_id = _release_treatment_id(
        planner_spec,
        "baseline",
    )
    candidate_planner = _release_records_for_role(planner, "candidate")
    source_case_ids = {
        item["source_case_id"] for item in arm_map.values()
    }
    candidate_source = [
        record for record in candidate_planner
        if record["case_id"] in source_case_ids
    ]
    candidate_source_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in candidate_source:
        candidate_source_by_case[record["case_id"]].append(record)
    prior_ids = [
        item["treatment_id"]
        for item in planner_spec["treatments"]
        if item["causal_role"] == "prior"
    ]
    prior_profile: dict[str, list[bool]] = defaultdict(list)
    if len(prior_ids) == 1:
        for record in planner_records:
            if (
                record["variant"] == prior_ids[0]
                and record["case_id"] in source_case_ids
            ):
                prior_profile[record["case_id"]].append(
                    record["counts"]["reference_load_count"] > 0,
                )
    always_loaded = {
        case_id for case_id, values in prior_profile.items()
        if values and all(values)
    }
    mixed_prior = {
        case_id for case_id, values in prior_profile.items()
        if any(values) and not all(values)
    }
    all_context = (
        summarize_paired_metric(
            planner_records,
            comparator=prior_ids[0],
            candidate=candidate_planner_id,
            metric="controlled_skill_context_bytes",
            direction="lower_is_better",
            effect="relative",
            confidence_level=confidence_level,
            bootstrap_iterations=bootstrap_iterations,
            random_seed=random_seed + 21,
            eligible_case_ids=source_case_ids,
        )
        if len(prior_ids) == 1
        else {"status": "not_evaluable", "case_differences": []}
    )
    planner_quality = summarize_paired_metric(
        planner_records,
        comparator=baseline_planner_id,
        candidate=candidate_planner_id,
        metric="quality_score_normalized",
        direction="higher_is_better",
        effect="relative",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed + 22,
        eligible_case_ids=source_case_ids,
    )

    transfer_spec = transfer["spec"]
    baseline_executor_id = _release_treatment_id(
        transfer_spec,
        "baseline",
    )
    candidate_executor_id = _release_treatment_id(
        transfer_spec,
        "candidate",
    )
    transfer_roles = {
        item["treatment_id"]: item["causal_role"]
        for item in transfer_spec["treatments"]
    }
    release_transfer = [
        record for record in transfer["evidence"]["records"]
        if transfer_roles.get(record["variant"]) in {"baseline", "candidate"}
    ]
    normalized_transfer = []
    for record in release_transfer:
        binding = arm_map.get(record["case_id"])
        if binding is None:
            continue
        normalized_transfer.append({
            **record,
            "case_id": binding["source_case_id"],
            "repeat": binding["planner_repeat"],
        })
    transfer_task = summarize_paired_metric(
        normalized_transfer,
        comparator=baseline_executor_id,
        candidate=candidate_executor_id,
        metric="task_pass_rate",
        direction="higher_is_better",
        effect="relative",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed + 23,
    )
    prewrite = summarize_paired_cost_delta(
        normalized_transfer,
        comparator=baseline_executor_id,
        candidate=candidate_executor_id,
        metric="executor_prewrite_tool_output_bytes",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed + 24,
        eligible_case_ids=source_case_ids,
    )
    baseline_executor = [
        record for record in normalized_transfer
        if record["variant"] == baseline_executor_id
    ]
    candidate_executor = [
        record for record in normalized_transfer
        if record["variant"] == candidate_executor_id
    ]
    baseline_failures = {
        (record["case_id"], record["repeat"])
        for record in baseline_executor
        if record["valid"] is not True or record["task_pass"] is not True
    }
    candidate_failures = {
        (record["case_id"], record["repeat"])
        for record in candidate_executor
        if record["valid"] is not True or record["task_pass"] is not True
    }
    by_case: dict[str, dict[str, list[bool]]] = defaultdict(
        lambda: {"baseline": [], "candidate": []},
    )
    for record in baseline_executor:
        by_case[record["case_id"]]["baseline"].append(record["task_pass"])
    for record in candidate_executor:
        by_case[record["case_id"]]["candidate"].append(record["task_pass"])
    candidate_not_worse = bool(by_case) and all(
        sum(values["candidate"]) >= sum(values["baseline"])
        for values in by_case.values()
    )
    improved_to_full = sum(
        bool(values["candidate"])
        and all(values["candidate"])
        and not all(values["baseline"])
        for values in by_case.values()
    )
    canonical_passes = sum(
        record["valid"] is True
        and "rubric-one-canonical-deliverable"
        not in record["hard_gate_failures"]
        for record in candidate_source
    )
    source_binding_cases = sum(
        bool(candidate_source_by_case[case_id])
        and all(
            record["valid"] is True
            and "rubric-scope-authority" not in record["hard_gate_failures"]
            for record in candidate_source_by_case[case_id]
        )
        for case_id in source_case_ids
    )
    integrity_ids = {
        "artifact-boundary",
        "content-integrity",
        "verification-contract",
    }
    content_integrity_errors = sum(
        len(integrity_ids & set(record["hard_gate_failures"]))
        for record in candidate_executor
    )
    preflight_passes = sum(
        record["valid"] is True
        and "transfer-preflight" not in record["hard_gate_failures"]
        for record in release_transfer
    )
    case_benefits = [
        item["benefit"] for item in all_context.get("case_differences", ())
    ]
    metrics = {
        **_release_context_scalars(planner["public"]),
        "authoritative_body_consumed_exactly_once": (
            bool(candidate_source)
            and all(
                record["counts"]["host_injected_body_count"] == 1
                for record in candidate_source
            )
        ),
        "authority_reference_loads_max": _release_max(
            candidate_source,
            "counts",
            "reference_load_count",
        ),
        "protocol_only_calls": _release_max(
            candidate_source,
            "counts",
            "skill_protocol_tool_calls",
        ),
        "canonical_deliverable_rate": (
            canonical_passes / len(candidate_source)
            if candidate_source else 0.0
        ),
        "source_binding_score": source_binding_cases,
        "content_integrity_error_scalar": content_integrity_errors,
        "transfer_preflight": {
            "numerator": preflight_passes,
            "denominator": len(release_transfer),
        },
        "candidate_only_failures": len(
            candidate_failures - baseline_failures,
        ),
        "all_context_sample_count": all_context.get("case_count", 0),
        "all_context_minimum_relative_effect": min(
            case_benefits,
            default=None,
        ),
        "prior_reference_cases": len(always_loaded),
        "mixed_prior_cases": len(mixed_prior),
        "prior_controlled_context_reduction": prior_context,
        "planner_quality_relative_effect": planner_quality,
        "eligible_source_cases": len(source_case_ids),
        "candidate_canonical_passes": canonical_passes,
        "candidate_not_worse_every_case": candidate_not_worse,
        "improved_to_full_cases": improved_to_full,
        "transfer_task_relative_effect": transfer_task,
        "matched_total_token_relative_reduction": matched_tokens,
        "prewrite_overhead": prewrite,
    }
    return metrics


def project_release_estimands(
    study_bindings: list[dict[str, Any]],
    writing_plans_join: dict[str, dict[str, Any]],
    *,
    confidence_level: float,
    bootstrap_iterations: int,
    random_seed: int,
    allow_missing_manual: bool = False,
) -> dict[str, Any]:
    """Return the in-memory three-study release projection.

    Bindings use the exact core fields checked by ``_load_release_study``.
    ``writing_plans_join`` is keyed by executor entry ID and binds the source
    case/repeat plus both selected receipt identities. Raw identity drift raises;
    complete but unusable evidence returns a typed ``status=invalid`` projection.
    """
    if not all(isinstance(item, dict) for item in study_bindings):
        raise ValueError("release study bindings must be objects")
    study_ids = [item.get("study_id") for item in study_bindings]
    expected_ids = [
        "software-quality-workflows",
        "writing-plans-planner",
        "writing-plans-transfer",
    ]
    if study_ids != expected_ids:
        raise ValueError("release study bindings must be sorted and exact-one")
    if (
        confidence_level != 0.90
        or bootstrap_iterations != 10000
        or not isinstance(random_seed, int)
        or isinstance(random_seed, bool)
        or random_seed < 0
    ):
        raise ValueError("release statistics must use 0.90, 10000, and a seed")
    if not isinstance(writing_plans_join, dict):
        raise ValueError("Writing Plans join must be an exact object")

    loaded = {
        binding["study_id"]: _load_release_study(binding)
        for binding in study_bindings
    }
    studies = {
        study_id: value["public"]
        for study_id, value in loaded.items()
    }

    sqw = loaded["software-quality-workflows"]
    sqw_records = sqw["evidence"]["records"]
    sqw_spec = sqw["spec"]
    sqw_reason_codes: list[str] = []
    total_token_records: list[dict[str, Any]] = []
    for record in sqw_records:
        tokens = (record.get("tokens_in"), record.get("tokens_out"))
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for value in tokens
        ):
            sqw_reason_codes.append("invalid_token_usage")
            break
        total_token_records.append({
            **record,
            "tokens_in": tokens[0] + tokens[1],
        })
    sqw_tokens = summarize_paired_metric(
        total_token_records,
        comparator=_release_treatment_id(sqw_spec, "baseline"),
        candidate=_release_treatment_id(sqw_spec, "candidate"),
        metric="tokens_in",
        direction="lower_is_better",
        effect="relative",
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed,
    )
    if sqw_tokens["status"] != "complete":
        sqw_reason_codes.append("sqw_total_token_pairs_incomplete")
    sqw_ready = _release_projection_ready(
        studies["software-quality-workflows"],
        allow_missing_manual=allow_missing_manual,
    )
    if not sqw_ready:
        sqw_reason_codes.append("sqw_native_evidence_invalid")
    sqw_metrics = {}
    if sqw_ready:
        sqw_metrics = _sqw_release_metrics(
            sqw,
            confidence_level=confidence_level,
            bootstrap_iterations=bootstrap_iterations,
            random_seed=random_seed,
        )
    sqw_metrics["total_token_relative_reduction"] = sqw_tokens
    sqw_projection = {
        "status": "complete" if not sqw_reason_codes else "invalid",
        "reason_codes": sorted(set(sqw_reason_codes)),
        "total_token_relative_reduction": {
            "evidence_artifact_kind": "report_local",
            "case_count": sqw_tokens["case_count"],
            "point": sqw_tokens["point"],
            "lower": sqw_tokens["lower"],
            "upper": sqw_tokens["upper"],
        } if not sqw_reason_codes else None,
        "release_metrics": sqw_metrics,
    }

    planner = loaded["writing-plans-planner"]
    transfer = loaded["writing-plans-transfer"]
    planner_records = planner["evidence"]["records"]
    transfer_records = transfer["evidence"]["records"]
    planner_by_entry = {
        record["entry_id"]: record for record in planner_records
    }
    planner_attempts = planner["evidence"]["selected_attempts"]
    transfer_attempts = transfer["evidence"]["selected_attempts"]
    planner_roles = {
        item["treatment_id"]: item["causal_role"]
        for item in planner["spec"]["treatments"]
    }
    transfer_roles = {
        item["treatment_id"]: item["causal_role"]
        for item in transfer["spec"]["treatments"]
    }
    release_transfer_records = [
        record
        for record in transfer_records
        if transfer_roles.get(record["variant"]) in {"baseline", "candidate"}
    ]
    join_reason_codes: set[str] = set()
    expected_executor_entries = {
        record["entry_id"] for record in release_transfer_records
    }
    if set(writing_plans_join) != expected_executor_entries:
        join_reason_codes.add("writing_plans_join_inventory_mismatch")
    arm_map: dict[str, dict[str, Any]] = {}
    for executor_record in release_transfer_records:
        executor_entry_id = executor_record["entry_id"]
        item = writing_plans_join.get(executor_entry_id)
        if not isinstance(item, dict) or set(item) != {
            "source_case_id",
            "planner_repeat",
            "planner_entry_id",
            "planner_receipt_hash",
            "executor_receipt_hash",
        }:
            join_reason_codes.add("writing_plans_join_shape_invalid")
            continue
        planner_record = planner_by_entry.get(item["planner_entry_id"])
        planner_attempt = planner_attempts.get(item["planner_entry_id"])
        executor_attempt = transfer_attempts.get(executor_entry_id)
        if (
            planner_record is None
            or planner_attempt is None
            or executor_attempt is None
            or item["source_case_id"] != planner_record["case_id"]
            or item["planner_repeat"] != planner_record["repeat"]
            or item["planner_receipt_hash"]
            != file_sha256(planner_attempt["receipt_path"])
            or item["executor_receipt_hash"]
            != file_sha256(executor_attempt["receipt_path"])
            or planner_roles.get(planner_record["variant"])
            != transfer_roles.get(executor_record["variant"])
        ):
            join_reason_codes.add("writing_plans_join_identity_mismatch")
            continue
        normalized = {
            "source_case_id": item["source_case_id"],
            "planner_repeat": item["planner_repeat"],
        }
        previous = arm_map.setdefault(executor_record["case_id"], normalized)
        if previous != normalized:
            join_reason_codes.add("writing_plans_executor_case_ambiguous")

    planner_case_ids = {
        item["source_case_id"] for item in arm_map.values()
    }
    repeat_values = {
        item["planner_repeat"] for item in arm_map.values()
    }
    repeats = max(repeat_values, default=0)
    if repeat_values != set(range(1, repeats + 1)):
        join_reason_codes.add("writing_plans_repeat_matrix_invalid")
    matched = matched_planner_executor_tokens(
        planner_records,
        release_transfer_records,
        arm_map,
        baseline_planner=_release_treatment_id(planner["spec"], "baseline"),
        candidate_planner=_release_treatment_id(planner["spec"], "candidate"),
        baseline_executor=_release_treatment_id(transfer["spec"], "baseline"),
        candidate_executor=_release_treatment_id(transfer["spec"], "candidate"),
        case_ids=planner_case_ids,
        repeats=repeats,
        confidence_level=confidence_level,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=random_seed,
    )
    if not matched["complete"]:
        join_reason_codes.add("writing_plans_matched_pairs_incomplete")
    planner_ready = _release_projection_ready(
        studies["writing-plans-planner"],
        allow_missing_manual=allow_missing_manual,
    )
    transfer_ready = _release_projection_ready(
        studies["writing-plans-transfer"],
        allow_missing_manual=allow_missing_manual,
    )
    if not planner_ready or not transfer_ready:
        join_reason_codes.add("writing_plans_native_evidence_invalid")

    prior_ids = [
        item["treatment_id"]
        for item in planner["spec"]["treatments"]
        if item["causal_role"] == "prior"
    ]
    prior_context: dict[str, Any] | None = None
    if prior_ids:
        if len(prior_ids) != 1:
            join_reason_codes.add("writing_plans_prior_treatment_ambiguous")
        else:
            prior_id = prior_ids[0]
            by_case: dict[str, list[bool]] = defaultdict(list)
            for record in planner_records:
                if (
                    record["variant"] == prior_id
                    and record["case_id"] in planner_case_ids
                ):
                    by_case[record["case_id"]].append(
                        record["counts"]["reference_load_count"] > 0,
                    )
            if any(any(values) and not all(values) for values in by_case.values()):
                join_reason_codes.add("writing_plans_prior_reference_mixed")
            eligible = {
                case_id for case_id, values in by_case.items()
                if values and all(values)
            }
            prior_context = summarize_paired_metric(
                planner_records,
                comparator=prior_id,
                candidate=_release_treatment_id(
                    planner["spec"],
                    "candidate",
                ),
                metric="controlled_core_skill_context_bytes",
                direction="lower_is_better",
                effect="relative",
                confidence_level=confidence_level,
                bootstrap_iterations=bootstrap_iterations,
                random_seed=random_seed,
                eligible_case_ids=eligible,
            )
            if prior_context["status"] != "complete":
                join_reason_codes.add(
                    "writing_plans_prior_context_pairs_incomplete",
                )

    writing_metrics = {}
    if planner_ready and transfer_ready:
        writing_metrics = _writing_plans_release_metrics(
            planner,
            transfer,
            arm_map,
            prior_context=prior_context,
            matched_tokens=matched,
            confidence_level=confidence_level,
            bootstrap_iterations=bootstrap_iterations,
            random_seed=random_seed,
        )
    writing_projection = {
        "status": "complete" if not join_reason_codes else "invalid",
        "reason_codes": sorted(join_reason_codes),
        "matched_total_token_relative_reduction": {
            "evidence_artifact_kind": "report_local",
            "case_count": matched["case_count"],
            "point": matched["point"],
            "lower": matched["lower"],
            "upper": matched["upper"],
        } if not join_reason_codes else None,
        "prior_controlled_context_relative_reduction": (
            {
                "evidence_artifact_kind": "report_local",
                "case_count": prior_context["case_count"],
                "point": prior_context["point"],
                "lower": prior_context["lower"],
                "upper": prior_context["upper"],
            }
            if prior_context is not None and not join_reason_codes
            else None
        ),
        "release_metrics": writing_metrics,
    }
    status = (
        "complete"
        if (
            sqw_projection["status"] == "complete"
            and writing_projection["status"] == "complete"
        )
        else "invalid"
    )
    return {
        "schema_version": "project-release-estimands/1.0",
        "status": status,
        "statistics": {
            "confidence_level": confidence_level,
            "bootstrap_iterations": bootstrap_iterations,
            "random_seed": random_seed,
        },
        "studies": studies,
        "software_quality_workflows": sqw_projection,
        "writing_plans": writing_projection,
    }


def _v5_base_exit(level: str, summary: dict[str, Any]) -> int:
    manual = summary["manual_authority"]
    if (
        summary["analysis_ready"] is not True
        or summary["evidence_status"] in {"incomplete", "invalid"}
        or (
            manual["required"] is True
            and manual["status"] in {"missing", "invalid"}
        )
    ):
        return 3
    if manual["decision"] in {"hold", "reject"}:
        return 1
    if level in {"L0", "L1"}:
        return 0
    if summary["usefulness_status"] in {
        "not_evaluable", "inconclusive_ceiling",
    }:
        return 3
    if (
        summary["usefulness_status"] in {
            "not_supported", "not_applicable",
        }
    ):
        return 1
    if (
        summary["usefulness_status"] == "supported"
        and summary["final_authority_status"] == "eligible"
    ):
        return 0
    return 3


def _v5_exit_code(
    level: str,
    summary: dict[str, Any],
    *,
    report_only: bool,
) -> int:
    base = _v5_base_exit(level, summary)
    return 0 if report_only and base == 1 else base


def _main_v5() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze an execution plan from index/receipt v4 evidence.",
    )
    parser.add_argument("index", type=Path)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--failure-index", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--details", type=Path)
    parser.add_argument("--manual-review-receipt", type=Path)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    try:
        summary_path = args.json.resolve()
        failure_path = args.failure_index.resolve()
        markdown_path = (
            args.markdown.resolve() if args.markdown is not None else None
        )
        details_path = (
            args.details.resolve() if args.details is not None else None
        )
        for output_path in (
            summary_path, failure_path, markdown_path, details_path,
        ):
            if (
                output_path is not None
                and not output_path.parent.is_dir()
            ):
                raise ValueError(
                    f"output parent must be a directory: {output_path.parent}",
                )
    except (OSError, ValueError) as exc:
        print(f"analysis output error: {exc}", file=sys.stderr)
        return 2

    try:
        spec_path = args.spec.resolve()
        index_path = args.index.resolve()
        spec, _, _, plan_path, plan, registry = _load_v5_analysis_inputs(
            spec_path, index_path,
        )
        bound_evidence = _load_v5_bound_evidence(
            spec, spec_path, registry,
        )
        index_rows = _load_v5_index(index_path, plan, registry)
        _, artifacts_root = resolve_contained_path(
            plan_path.parent,
            plan["artifacts"]["root"],
            "plan artifacts root",
        )
        evidence = _collect_v5_evidence(
            index_rows,
            artifacts_root=artifacts_root,
            plan=plan,
            spec=spec,
            registry=registry,
            bound_evidence=bound_evidence,
        )
        failure_items, failure_artifacts = _derive_v5_failures(
            spec, plan, plan_path, evidence,
        )
        manual, manual_issue = _verify_v5_manual_review(
            args.manual_review_receipt,
            spec,
            spec_path,
            plan_path,
        )
        summary, metric_analysis = _v5_summary_base(
            spec, plan, evidence, failure_items, manual, bound_evidence,
        )
        if spec_path.name in failure_artifacts:
            raise ValueError("spec and evidence artifact identities collide")
        failure_artifacts[spec_path.name] = _local_artifact(
            spec_path, encoding="utf-8",
        )
        failure_items = _finalize_v5_failures(
            [
                *failure_items,
                *_derive_v5_gate_failures(
                    spec, plan, spec_path, metric_analysis,
                ),
                *_derive_v5_manual_failure(
                    spec,
                    plan,
                    spec_path,
                    manual,
                    manual_issue,
                ),
            ],
            failure_artifacts,
        )
        summary["blocking_observations"] = sorted({
            *summary["blocking_observations"],
            *(item["reason_key"] for item in failure_items),
        })
        summary["representative_failure_ids"] = [
            item["failure_id"] for item in failure_items[:10]
        ]
        failures = _v5_failure_index(
            spec, plan, failure_items, view="index",
        )
        if failures["truncated"] and details_path is None:
            details_path = failure_path.with_name(
                f"{failure_path.stem}.details{failure_path.suffix}",
            )
        details = (
            _v5_failure_index(spec, plan, failure_items, view="full")
            if details_path is not None
            else None
        )
        _commit_v5_outputs(
            summary,
            failures,
            failure_details=details,
            summary_path=summary_path,
            failure_path=failure_path,
            markdown_path=markdown_path,
            details_path=details_path,
            registry=registry,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Analyzed {len(index_rows)} attempts for {len(plan['entries'])} plan entries.",
    )
    return _v5_exit_code(
        spec["level"], summary, report_only=args.report_only,
    )


def main() -> int:
    return _main_v5()


if __name__ == "__main__":
    raise SystemExit(main())
