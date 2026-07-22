#!/usr/bin/env python3
"""Validate a skill-evaluation spec and JSONL task suite using only stdlib."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

LEVELS = {"L0", "L1", "L2", "L3", "L4"}
SPLITS = {"dev", "regression", "heldout"}
RISKS = {"low", "standard", "high"}
MODES = {"skill_disabled", "force_loaded", "natural_routing"}
ROLES = {"baseline", "candidate", "prior"}
REQUIREMENT_OWNERS = {"deterministic", "model"}
CANONICAL_VARIANT_PROFILES = {
    "baseline/skill_disabled",
    "candidate/force_loaded",
    "candidate/natural_routing",
    "prior/force_loaded",
    "prior/natural_routing",
}
GLOBAL_GATE_METRICS = {
    "critical_safety_incidents", "unauthorized_side_effects", "protected_outcome_failures",
    "paired_task_pass_lift", "paired_case_count",
    "paired_task_pass_lift_lower_bound", "paired_process_score_lift_lower_bound",
    "paired_quality_score_lift_lower_bound", "paired_safety_pass_lift_lower_bound",
    "skill_context_attribution_rate", "skill_context_bytes_p95", "skill_context_tokens_p95",
    "repeated_static_content_bytes_max", "protocol_output_bytes_max",
    "failed_command_output_bytes_max",
}
VARIANT_GATE_METRICS = {
    "task_pass_rate", "routing_precision", "routing_recall", "routing_f1",
    "retrieval_recall", "retrieval_mrr", "body_load_recall", "incorporation_recall",
    "application_recall", "false_application_rate",
    "safety_incident_rate", "critical_safety_incidents", "invalid_run_rate",
    "process_score", "quality_score", "tokens_in", "tokens_out", "latency_ms",
    "tool_calls", "retries", "unauthorized_side_effects",
    "worst_slice_task_pass",
}
SUPPORTED_DECLARED_METRICS = GLOBAL_GATE_METRICS | VARIANT_GATE_METRICS | {
    "paired_wins_losses",
}
GRADER_TYPES = {"deterministic", "model_rubric"}
REQUIREMENT_DIMENSIONS = {"outcome", "process", "quality", "safety"}
SAFETY_SEVERITIES = {"critical", "high", "standard"}
SAFETY_KINDS = {"unauthorized_action", "other"}
LEGACY_CASE_FIELDS = {"required_outcomes", "required_process", "forbidden_actions", "oracle"}
CASE_LIST_FIELDS = {
    "tags", "allowed_skills", "applicable_variant_profiles",
    "authoritative_inputs", "distractor_inputs", "adversarial_inputs", "expected_citations",
}
CASE_REQUIRED_FIELDS = {
    "case_id", "split", "tags", "prompt", "should_trigger", "allowed_skills",
    "fixture", "requirements",
    "timeout_seconds", "risk", "applicable_variant_profiles",
}
PLACEHOLDER_RE = re.compile(r"(?:\breplace(?:-|_)|sha256:replace|example-(?:agent|model|harness))", re.I)
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$", re.I)
LOWER_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NONREADY_SHA256_SENTINEL = "sha256:replace-before-scored-run"
NONREADY_CONTEXT_GATE_ID = "replace-before-scored-run"
NONREADY_CONTEXT_AUTHORITY = {
    "reference": "replace-before-scored-run",
    "unit": "replace-before-scored-run",
    "threshold": "replace-before-scored-run",
}
NONREADY_FIXTURE_SENTINEL = {
    "manifest": "fixtures/replace-before-scored-run.manifest.json",
    "sha256": NONREADY_SHA256_SENTINEL,
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}") from None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}") from None
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL in {path} line {line_no}: {exc.msg}") from None
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record in {path} line {line_no} must be an object")
        value["_line"] = line_no
        records.append(value)
    return records


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_spec(spec: Any, errors: list[str], warnings: list[str]) -> None:
    if not isinstance(spec, dict):
        errors.append("evaluation spec must be a JSON object")
        return

    level = spec.get("level")
    risk = spec.get("risk_tier")
    required_fields = {
        "schema_version", "evaluation_id", "decision", "claim_scope", "level",
        "risk_tier", "target", "authority", "artifacts",
    }
    if level in {"L1", "L2", "L3", "L4"}:
        required_fields.update({"environment", "suite", "variants", "graders", "ready_for_scored_run"})
    if level in {"L2", "L3", "L4"}:
        required_fields.update({"analysis", "metrics", "hard_gates"})
    for field in sorted(required_fields):
        if field not in spec:
            errors.append(f"spec missing required field: {field}")

    if spec.get("schema_version") != 3:
        errors.append("spec.schema_version must equal 3")
    if not nonempty_string(spec.get("evaluation_id")):
        errors.append("spec.evaluation_id must be a non-empty string")
    if not nonempty_string(spec.get("decision")):
        errors.append("spec.decision must be a non-empty string")
    if not nonempty_string(spec.get("claim_scope")):
        errors.append("spec.claim_scope must be a non-empty string")
    if level not in LEVELS:
        errors.append(f"spec.level must be one of {sorted(LEVELS)}")
    if risk not in RISKS:
        errors.append(f"spec.risk_tier must be one of {sorted(RISKS)}")

    forbidden_by_level = {
        "L0": {"environment", "suite", "variants", "variant_profile_requirements", "graders", "analysis", "metrics", "hard_gates", "ready_for_scored_run"},
        "L1": {"analysis", "metrics", "hard_gates"},
    }
    for field in sorted(forbidden_by_level.get(level, set()) & set(spec)):
        errors.append(f"{level} spec forbids {field}")

    manual_review = spec.get("manual_review")
    if manual_review is not None and not isinstance(manual_review, dict):
        errors.append("spec.manual_review must be an object when supplied")
    elif isinstance(manual_review, dict):
        if not isinstance(manual_review.get("required"), bool):
            errors.append("spec.manual_review.required must be boolean")
        if manual_review.get("required") is True:
            if not nonempty_string(manual_review.get("reviewer_role")):
                errors.append("spec.manual_review.reviewer_role must be a non-empty string when review is required")
            required_evidence = manual_review.get("required_evidence")
            if not isinstance(required_evidence, list) or not required_evidence or not all(nonempty_string(item) for item in required_evidence):
                errors.append("spec.manual_review.required_evidence must be a non-empty string array when review is required")
            elif len(set(required_evidence)) != len(required_evidence):
                errors.append("spec.manual_review.required_evidence entries must be unique")
    if level in {"L3", "L4"} and not (isinstance(manual_review, dict) and manual_review.get("required") is True):
        errors.append("L3/L4 spec requires manual_review.required=true")
    elif risk == "high" and not (isinstance(manual_review, dict) and manual_review.get("required") is True):
        errors.append("high-risk spec requires manual_review.required=true")

    target = spec.get("target")
    if not isinstance(target, dict):
        errors.append("spec.target must be an object")
    else:
        target_fields = ("name", "candidate_path") if level == "L0" else ("name", "candidate_path", "candidate_hash")
        for field in target_fields:
            if not nonempty_string(target.get(field)):
                errors.append(f"spec.target.{field} must be a non-empty string")
        for field in ("candidate_hash", "prior_hash"):
            value = target.get(field)
            if nonempty_string(value) and not PLACEHOLDER_RE.search(value) and not SHA256_RE.fullmatch(value):
                errors.append(f"spec.target.{field} must be sha256:<64 hex>")
        if level != "L0":
            if not nonempty_string(target.get("candidate_revision")):
                errors.append("spec.target.candidate_revision must be a non-empty string")
            for field in ("candidate_source_tree_hash", "candidate_plugin_tree_hash"):
                value = target.get(field)
                if not nonempty_string(value):
                    errors.append(f"spec.target.{field} must be a non-empty SHA-256 value")
                elif not PLACEHOLDER_RE.search(value) and not SHA256_RE.fullmatch(value):
                    errors.append(f"spec.target.{field} must be sha256:<64 hex>")

    variants = [] if level == "L0" else spec.get("variants")
    variant_ids: list[str] = []
    if level != "L0" and (not isinstance(variants, list) or not variants):
        errors.append("spec.variants must be a non-empty array")
    elif isinstance(variants, list):
        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                errors.append(f"spec.variants[{index}] must be an object")
                continue
            variant_id = variant.get("id")
            mode = variant.get("mode")
            role = variant.get("role")
            if not nonempty_string(variant_id):
                errors.append(f"spec.variants[{index}].id must be a non-empty string")
            else:
                variant_ids.append(variant_id)
            if mode not in MODES:
                errors.append(f"spec.variants[{index}].mode must be one of {sorted(MODES)}")
            if role not in ROLES:
                errors.append(f"spec.variants[{index}].role must be one of {sorted(ROLES)}")
            for field in ("package_hash", "catalog_hash", "treatment_hash"):
                value = variant.get(field)
                if not nonempty_string(value):
                    errors.append(f"spec.variants[{index}].{field} must be a non-empty SHA-256 value")
                elif not PLACEHOLDER_RE.search(value) and not SHA256_RE.fullmatch(value):
                    errors.append(f"spec.variants[{index}].{field} must be sha256:<64 hex>")
        duplicates = sorted(name for name, count in Counter(variant_ids).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate variant IDs: {duplicates}")

        target = spec.get("target") if isinstance(spec.get("target"), dict) else {}
        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                continue
            if variant.get("role") == "candidate" and variant.get("package_hash") != target.get("candidate_hash"):
                errors.append(f"spec.variants[{index}].package_hash must equal spec.target.candidate_hash")
            if variant.get("role") == "prior":
                if not nonempty_string(target.get("prior_hash")):
                    errors.append("spec.target.prior_hash is required when a prior variant is declared")
                elif variant.get("package_hash") != target.get("prior_hash"):
                    errors.append(f"spec.variants[{index}].package_hash must equal spec.target.prior_hash")

    requirements = spec.get("variant_profile_requirements")
    required_profiles: set[str] = set()
    requirement_profiles: list[str] = []
    if requirements is not None and (not isinstance(requirements, list) or not requirements):
        errors.append("spec.variant_profile_requirements must be a non-empty array when supplied")
    elif isinstance(requirements, list):
        for index, requirement in enumerate(requirements):
            if not isinstance(requirement, dict):
                errors.append(f"spec.variant_profile_requirements[{index}] must be an object")
                continue
            profile = requirement.get("profile")
            status = requirement.get("status")
            if profile not in CANONICAL_VARIANT_PROFILES:
                errors.append(
                    f"spec.variant_profile_requirements[{index}].profile must be one of "
                    f"{sorted(CANONICAL_VARIANT_PROFILES)}"
                )
                continue
            requirement_profiles.append(profile)
            if status not in {"required", "not_applicable"}:
                errors.append(f"spec.variant_profile_requirements[{index}].status must be required or not_applicable")
            elif status == "required":
                required_profiles.add(profile)
            else:
                if not nonempty_string(requirement.get("reason")):
                    errors.append(f"spec.variant_profile_requirements[{index}] not_applicable requires a reason")
                if not nonempty_string(requirement.get("approved_by")):
                    errors.append(f"spec.variant_profile_requirements[{index}] not_applicable requires approved_by")
        duplicate_profiles = sorted(name for name, count in Counter(requirement_profiles).items() if count > 1)
        if duplicate_profiles:
            errors.append(f"duplicate variant profile requirements: {duplicate_profiles}")
        declared_profiles = {
            f"{variant.get('role')}/{variant.get('mode')}"
            for variant in variants if isinstance(variant, dict)
        } if isinstance(variants, list) else set()
        undeclared_required = sorted(required_profiles - declared_profiles)
        if undeclared_required:
            errors.append(f"required variant profiles are undeclared: {undeclared_required}")
        declared_not_required = sorted(declared_profiles - required_profiles)
        if declared_not_required:
            errors.append(f"declared variants must have required profile status: {declared_not_required}")

    suite = spec.get("suite")
    if level != "L0" and not isinstance(suite, dict):
        errors.append("spec.suite must be an object")
    elif isinstance(suite, dict):
        repeats = suite.get("repeats")
        if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
            errors.append("spec.suite.repeats must be an integer >= 1")
        if not nonempty_string(suite.get("cases_file")):
            errors.append("spec.suite.cases_file must be a non-empty path")
        for field in ("reset_strategy", "retry_policy", "run_order"):
            if not nonempty_string(suite.get(field)):
                errors.append(f"spec.suite.{field} must be a non-empty string")
        for field in (
            "cases_content_hash", "case_contracts_content_hash",
            "fixture_manifest_set_hash", "grader_batch_schedule_hash",
        ):
            value = suite.get(field)
            if not nonempty_string(value):
                errors.append(f"spec.suite.{field} must be a non-empty SHA-256 value")
            elif not PLACEHOLDER_RE.search(value) and not SHA256_RE.fullmatch(value):
                errors.append(f"spec.suite.{field} must be sha256:<64 hex>")
        if level in {"L2", "L3", "L4"} and repeats == 1:
            warnings.append("L2+ spec uses one repeat; label deterministic evidence or increase repetitions")
        for field in ("development_split", "regression_split", "holdout_split"):
            value = suite.get(field)
            if value is not None and value not in SPLITS:
                errors.append(f"spec.suite.{field} must be one of {sorted(SPLITS)}")

        holdout = suite.get("holdout_control")
        if level == "L1" and holdout is not None:
            errors.append("L1 spec forbids suite.holdout_control")
        if level in {"L3", "L4"} and not isinstance(holdout, dict):
            errors.append("L3/L4 spec requires suite.holdout_control")
        if holdout is not None and not isinstance(holdout, dict):
            errors.append("spec.suite.holdout_control must be an object when supplied")
        elif isinstance(holdout, dict):
            if not isinstance(holdout.get("payload_separated"), bool):
                errors.append("spec.suite.holdout_control.payload_separated must be boolean")
            if not isinstance(holdout.get("refresh_required"), bool):
                errors.append("spec.suite.holdout_control.refresh_required must be boolean")
            if holdout.get("exposure_status") not in {"sealed", "exposed", "refreshed", "template_exposed"}:
                errors.append("spec.suite.holdout_control.exposure_status must be sealed, exposed, refreshed, or template_exposed")
            for field in ("manifest_file", "payload_file"):
                if not nonempty_string(holdout.get(field)):
                    errors.append(f"spec.suite.holdout_control.{field} must be a non-empty path")
            for field in ("manifest_hash", "payload_hash"):
                if not isinstance(holdout.get(field), str) or not SHA256_RE.fullmatch(holdout[field]):
                    errors.append(f"spec.suite.holdout_control.{field} must be sha256:<64 hex>")
            last_exposure = holdout.get("last_exposure_at")
            if last_exposure is not None and not nonempty_string(last_exposure):
                errors.append("spec.suite.holdout_control.last_exposure_at must be null or a non-empty timestamp")
            scored_ready = spec.get("ready_for_scored_run") is True
            if scored_ready:
                if not nonempty_string(holdout.get("custodian")) or PLACEHOLDER_RE.search(str(holdout.get("custodian", ""))):
                    errors.append("scored-ready holdout_control.custodian must identify the independent custodian")
                if holdout.get("payload_separated") is not True:
                    errors.append("scored-ready suite must keep holdout payload separate from the author-visible case file")
                if holdout.get("exposure_status") not in {"sealed", "refreshed"}:
                    errors.append("scored-ready holdout exposure_status must be sealed or refreshed")
                if holdout.get("refresh_required") is not False:
                    errors.append("scored-ready holdout_control.refresh_required must be false")
            elif holdout.get("payload_separated") is not True or holdout.get("refresh_required") is True:
                warnings.append("holdout payload is exposed/unseparated or requires refresh; scored promotion must remain blocked")

    graders = spec.get("graders")
    if level != "L0" and (not isinstance(graders, list) or not graders):
        errors.append("spec.graders must be a non-empty array")
    elif isinstance(graders, list):
        ids: list[str] = []
        for index, grader in enumerate(graders):
            prefix = f"spec.graders[{index}]"
            if not isinstance(grader, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if not nonempty_string(grader.get("id")):
                errors.append(f"{prefix}.id must be a non-empty string")
            else:
                ids.append(grader["id"])
            grader_type = grader.get("type")
            if grader_type not in GRADER_TYPES:
                errors.append(f"{prefix} grader type must be one of {sorted(GRADER_TYPES)}")
            if not isinstance(grader.get("hard_gate"), bool):
                errors.append(f"{prefix}.hard_gate must be boolean")
            if not nonempty_string(grader.get("version")):
                errors.append(f"{prefix}.version must be a non-empty string")

            checks = grader.get("checks")
            check_ids: list[str] = []
            if not isinstance(checks, list) or not checks:
                errors.append(f"{prefix}.checks must be a non-empty array")
            else:
                for check_index, check in enumerate(checks):
                    check_prefix = f"{prefix}.checks[{check_index}]"
                    if not isinstance(check, dict) or set(check) != {"id", "pass_condition"}:
                        errors.append(f"{check_prefix} must contain exactly id and pass_condition")
                        continue
                    if not nonempty_string(check.get("id")):
                        errors.append(f"{check_prefix}.id must be a non-empty string")
                    else:
                        check_ids.append(check["id"])
                    if not nonempty_string(check.get("pass_condition")):
                        errors.append(f"{check_prefix}.pass_condition must be a non-empty string")
                duplicate_checks = sorted(name for name, count in Counter(check_ids).items() if count > 1)
                if duplicate_checks:
                    errors.append(f"{prefix}.checks contains duplicate IDs {duplicate_checks}")

            verifier = grader.get("verifier")
            base_fields = {"id", "type", "hard_gate", "version", "checks"}
            if grader_type == "deterministic":
                extra = sorted(set(grader) - (base_fields | {"verifier"}))
                if extra:
                    errors.append(f"{prefix} deterministic grader has unsupported fields {extra}")
                if verifier is not None:
                    if not isinstance(verifier, dict) or set(verifier) != {"path", "sha256", "argv", "pass_exit_codes"}:
                        errors.append(f"{prefix}.verifier must contain exactly path, sha256, argv, and pass_exit_codes")
                    else:
                        path = verifier.get("path")
                        sha256 = verifier.get("sha256")
                        if not nonempty_string(path):
                            errors.append(f"{prefix}.verifier.path must be a non-empty relative path")
                        if sha256 != NONREADY_SHA256_SENTINEL and not (isinstance(sha256, str) and SHA256_RE.fullmatch(sha256)):
                            errors.append(f"{prefix}.verifier.sha256 must be sha256:<64 hex> or the non-ready sentinel")
                        if verifier.get("argv") != ["python3", path]:
                            errors.append(f"{prefix}.verifier.argv must equal ['python3', verifier.path]")
                        exit_codes = verifier.get("pass_exit_codes")
                        if (
                            not isinstance(exit_codes, list)
                            or not exit_codes
                            or any(not isinstance(code, int) or isinstance(code, bool) for code in exit_codes)
                            or len(set(exit_codes)) != len(exit_codes)
                        ):
                            errors.append(f"{prefix}.verifier.pass_exit_codes must be a non-empty unique integer array")
                        if sha256 == NONREADY_SHA256_SENTINEL:
                            if spec.get("ready_for_scored_run") is True:
                                errors.append("scored-ready deterministic verifier placeholder is forbidden")
                            elif "non-ready deterministic verifier placeholder" not in warnings:
                                warnings.append("non-ready deterministic verifier placeholder")
            elif grader_type == "model_rubric":
                extra = sorted(set(grader) - (base_fields | {"prompt_path", "schema_path"}))
                if extra:
                    errors.append(f"{prefix} model_rubric grader has unsupported fields {extra}")
                for field in ("prompt_path", "schema_path"):
                    if not nonempty_string(grader.get(field)):
                        errors.append(f"{prefix} model_rubric must declare {field}")
                if verifier is not None:
                    errors.append(f"{prefix} model_rubric must not declare verifier")
        duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate grader IDs: {duplicates}")

    gates = spec.get("hard_gates")
    if level in {"L2", "L3", "L4"} and (not isinstance(gates, list) or not gates):
        errors.append("spec.hard_gates must be a non-empty array")
    elif isinstance(gates, list):
        gate_ids: list[str] = []
        for index, gate in enumerate(gates):
            if not isinstance(gate, dict):
                errors.append(f"spec.hard_gates[{index}] must be an object")
                continue
            for field in ("id", "metric", "operator", "value"):
                if field not in gate:
                    errors.append(f"spec.hard_gates[{index}] missing {field}")
            if nonempty_string(gate.get("id")):
                gate_ids.append(gate["id"])
            else:
                errors.append(f"spec.hard_gates[{index}].id must be a non-empty string")
            if not nonempty_string(gate.get("metric")):
                errors.append(f"spec.hard_gates[{index}].metric must be a non-empty string")
            else:
                metric = gate["metric"]
                supported = metric in GLOBAL_GATE_METRICS or ("." in metric and metric.split(".", 1)[1] in VARIANT_GATE_METRICS)
                if not supported:
                    errors.append(f"spec.hard_gates[{index}].metric is not supported by the bundled analyzer: {metric}")
                elif "." in metric and metric.split(".", 1)[0] not in variant_ids:
                    errors.append(f"spec.hard_gates[{index}].metric references an unknown variant: {metric}")
            if gate.get("operator") not in {"==", "!=", ">=", "<=", ">", "<"}:
                errors.append(f"spec.hard_gates[{index}].operator is invalid")
            value = gate.get("value")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                errors.append(f"spec.hard_gates[{index}].value must be numeric for the bundled analyzer")
        duplicates = sorted(name for name, count in Counter(gate_ids).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate hard-gate IDs: {duplicates}")

    metrics = spec.get("metrics")
    if level in {"L2", "L3", "L4"} and (
        not isinstance(metrics, list) or not metrics or not all(nonempty_string(item) for item in metrics)
    ):
        errors.append("spec.metrics must be a non-empty array of strings")
    elif isinstance(metrics, list):
        duplicates = sorted(name for name, count in Counter(metrics).items() if count > 1)
        if duplicates:
            errors.append("spec.metrics must not contain duplicates")
        unknown = sorted(set(metrics) - SUPPORTED_DECLARED_METRICS)
        if unknown:
            errors.append(f"unsupported declared metric(s): {unknown}")

    environment = spec.get("environment")
    if level != "L0" and not isinstance(environment, dict):
        errors.append("spec.environment must be an object")
    elif isinstance(environment, dict):
        environment_fields = {"agent", "model", "harness", "network_policy", "credentials_policy"}
        if level in {"L2", "L3", "L4"}:
            environment_fields.update({"system_config_hash", "tool_catalog_hash", "skill_catalog_hash", "os_or_image"})
        for field in sorted(environment_fields):
            if not nonempty_string(environment.get(field)):
                errors.append(f"spec.environment.{field} must be a non-empty string")
        timeout = environment.get("timeout_seconds")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(float(timeout)) or timeout <= 0:
            errors.append("spec.environment.timeout_seconds must be positive")
        seed = environment.get("random_seed")
        if level in {"L2", "L3", "L4"} and (not isinstance(seed, int) or isinstance(seed, bool)):
            errors.append("spec.environment.random_seed must be an integer for L2+")
        elif seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            errors.append("spec.environment.random_seed must be an integer or null")

    analysis = spec.get("analysis")
    if level in {"L2", "L3", "L4"} and not isinstance(analysis, dict):
        errors.append("spec.analysis must be an object")
    elif isinstance(analysis, dict):
        confidence = analysis.get("confidence_level")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not math.isfinite(float(confidence)) or not 0 < confidence < 1:
            errors.append("spec.analysis.confidence_level must be numeric in (0, 1)")
        iterations = analysis.get("paired_bootstrap_iterations")
        if not isinstance(iterations, int) or isinstance(iterations, bool) or not 100 <= iterations <= 1_000_000:
            errors.append("spec.analysis.paired_bootstrap_iterations must be an integer in [100, 1000000]")
        if level in {"L2", "L3", "L4"}:
            gates_by_id = {
                gate.get("id"): gate
                for gate in (gates if isinstance(gates, list) else []) if isinstance(gate, dict)
                and nonempty_string(gate.get("id"))
            }
            benefit_id = analysis.get("usefulness_benefit_gate_id")
            benefit_gate = gates_by_id.get(benefit_id)
            benefit_metrics = {
                "paired_task_pass_lift_lower_bound",
                "paired_process_score_lift_lower_bound",
                "paired_quality_score_lift_lower_bound",
                "paired_safety_pass_lift_lower_bound",
            }
            if not nonempty_string(benefit_id) or benefit_gate is None:
                errors.append("spec.analysis.usefulness_benefit_gate_id must reference a hard gate")
            elif (
                benefit_gate.get("metric") not in benefit_metrics
                or benefit_gate.get("operator") != ">="
                or not isinstance(benefit_gate.get("value"), (int, float))
                or isinstance(benefit_gate.get("value"), bool)
                or benefit_gate["value"] <= 0
            ):
                errors.append("usefulness benefit gate must be a positive comparative lower-bound >= gate")
            noninferiority_id = analysis.get("task_noninferiority_gate_id")
            if benefit_gate and benefit_gate.get("metric") != "paired_task_pass_lift_lower_bound":
                noninferiority_gate = gates_by_id.get(noninferiority_id)
                if not nonempty_string(noninferiority_id) or noninferiority_id == benefit_id or noninferiority_gate is None:
                    errors.append("non-task benefit requires a different exact task_noninferiority_gate_id")
                elif (
                    noninferiority_gate.get("metric") != "paired_task_pass_lift_lower_bound"
                    or noninferiority_gate.get("operator") != ">="
                    or not isinstance(noninferiority_gate.get("value"), (int, float))
                    or isinstance(noninferiority_gate.get("value"), bool)
                    or noninferiority_gate["value"] > 0
                ):
                    errors.append("task_noninferiority_gate_id must reference task lift lower-bound >= a non-positive margin")
            elif noninferiority_id is not None:
                errors.append("task benefit forbids spec.analysis.task_noninferiority_gate_id")

            protected_gates = [
                gate for gate in (gates if isinstance(gates, list) else []) if isinstance(gate, dict)
                and gate.get("metric") == "protected_outcome_failures"
            ]
            if spec.get("ready_for_scored_run") is True and (
                len(protected_gates) != 1
                or protected_gates[0].get("operator") != "=="
                or protected_gates[0].get("value") != 0
            ):
                errors.append("scored-ready L2+ spec requires one protected_outcome_failures == 0 gate")

            context_gate_id = analysis.get("context_budget_gate_id")
            context_authority = analysis.get("context_budget_authority")
            id_is_sentinel = context_gate_id == NONREADY_CONTEXT_GATE_ID
            authority_is_sentinel = context_authority == NONREADY_CONTEXT_AUTHORITY
            if id_is_sentinel or authority_is_sentinel:
                if id_is_sentinel and authority_is_sentinel and spec.get("ready_for_scored_run") is not True:
                    warnings.append("non-ready context budget placeholder")
                else:
                    errors.append("context budget placeholder is valid only as the exact non-ready sentinel")
            else:
                if not isinstance(context_authority, dict) or set(context_authority) != {
                    "kind", "reference", "unit", "threshold",
                }:
                    errors.append("spec.analysis.context_budget_authority must have the exact real-authority shape")
                else:
                    kind = context_authority.get("kind")
                    reference = context_authority.get("reference")
                    unit = context_authority.get("unit")
                    threshold = context_authority.get("threshold")
                    if kind not in {"deployment_contract", "user_constraint"}:
                        errors.append("context budget authority kind is invalid")
                    if not isinstance(reference, str) or not LOWER_SHA256_RE.fullmatch(reference):
                        errors.append("context budget authority reference must be lowercase sha256:<64 hex>")
                    if unit not in {"tokens", "bytes"}:
                        errors.append("context budget authority unit must be tokens or bytes")
                    if (
                        not isinstance(threshold, (int, float))
                        or isinstance(threshold, bool)
                        or not math.isfinite(float(threshold))
                        or threshold < 0
                    ):
                        errors.append("context budget authority threshold must be finite and non-negative")

                context_gate = gates_by_id.get(context_gate_id)
                expected_metric = (
                    f"skill_context_{context_authority.get('unit')}_p95"
                    if isinstance(context_authority, dict) else None
                )
                if (
                    not nonempty_string(context_gate_id)
                    or context_gate is None
                    or context_gate.get("metric") != expected_metric
                    or context_gate.get("operator") != "<="
                    or not isinstance(context_authority, dict)
                    or context_gate.get("value") != context_authority.get("threshold")
                ):
                    errors.append("context_budget_gate_id must reference the authority-matched p95 <= gate")

            if spec.get("ready_for_scored_run") is True:
                attribution_gates = [
                    gate for gate in (gates if isinstance(gates, list) else [])
                    if isinstance(gate, dict) and gate.get("metric") == "skill_context_attribution_rate"
                ]
                budget_gates = [
                    gate for gate in (gates if isinstance(gates, list) else [])
                    if isinstance(gate, dict) and gate.get("metric") in {
                        "skill_context_bytes_p95", "skill_context_tokens_p95",
                    }
                ]
                if (
                    len(attribution_gates) != 1
                    or attribution_gates[0].get("operator") != "=="
                    or attribution_gates[0].get("value") != 1
                ):
                    errors.append("scored-ready L2+ spec requires one skill_context_attribution_rate == 1 gate")
                if len(budget_gates) != 1:
                    errors.append("scored-ready L2+ spec requires exactly one Skill context p95 budget gate")
                for metric in (
                    "repeated_static_content_bytes_max",
                    "protocol_output_bytes_max",
                    "failed_command_output_bytes_max",
                ):
                    matches = [
                        gate for gate in (gates if isinstance(gates, list) else [])
                        if isinstance(gate, dict) and gate.get("metric") == metric
                    ]
                    if (
                        len(matches) != 1
                        or matches[0].get("operator") != "=="
                        or matches[0].get("value") != 0
                    ):
                        errors.append(f"scored-ready L2+ spec requires one {metric} == 0 gate")

    authority = spec.get("authority")
    if not isinstance(authority, dict):
        errors.append("spec.authority must be an object")
    else:
        for field, value in authority.items():
            if not isinstance(value, bool):
                errors.append(f"spec.authority.{field} must be boolean")

    artifacts = spec.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("spec.artifacts must be an object")
    else:
        if not nonempty_string(artifacts.get("root")):
            errors.append("spec.artifacts.root must be a non-empty path")
        for field in ("retain_raw_traces", "redact_secrets", "manifest_required"):
            if not isinstance(artifacts.get(field), bool):
                errors.append(f"spec.artifacts.{field} must be boolean")

    if level in {"L2", "L3", "L4"}:
        variant_profiles = {
            (variant.get("role"), variant.get("mode"))
            for variant in variants if isinstance(variant, dict)
        } if isinstance(variants, list) else set()
        if ("baseline", "skill_disabled") not in variant_profiles:
            errors.append("L2+ spec must include a baseline/skill_disabled variant")
        candidate_profiles = {
            profile for profile in variant_profiles
            if profile[0] == "candidate" and profile[1] in {"force_loaded", "natural_routing"}
        }
        if not candidate_profiles:
            errors.append(
                "L2+ spec must include a candidate/force_loaded or "
                "candidate/natural_routing variant"
            )

    serialized = json.dumps(spec, ensure_ascii=False)
    if PLACEHOLDER_RE.search(serialized):
        message = "spec still contains template placeholders; replace and hash them before scored runs"
        if spec.get("ready_for_scored_run") is True:
            errors.append(message)
        else:
            warnings.append(message)
    if "ready_for_scored_run" in spec and not isinstance(spec["ready_for_scored_run"], bool):
        errors.append("spec.ready_for_scored_run must be boolean")
    if level in {"L2", "L3", "L4"} and spec.get("ready_for_scored_run") is not True:
        warnings.append("spec.ready_for_scored_run is not true; this is acceptable for a template/diagnostic but not a scored decision")


def check_cases(spec: dict[str, Any], cases: list[dict[str, Any]], errors: list[str], warnings: list[str]) -> dict[str, Any]:
    if not cases:
        errors.append("case suite is empty")
        return {}

    ids: list[str] = []
    splits: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    trigger_counts: Counter[str] = Counter()
    risks: Counter[str] = Counter()
    placeholder_fixtures = 0
    level = spec.get("level")
    graders_value = spec.get("graders")
    graders_by_id = {
        grader.get("id"): grader
        for grader in graders_value if isinstance(grader, dict) and nonempty_string(grader.get("id"))
    } if isinstance(graders_value, list) else {}
    checks_by_grader = {
        grader_id: {
            check.get("id")
            for check in grader.get("checks", [])
            if isinstance(check, dict) and nonempty_string(check.get("id"))
        }
        for grader_id, grader in graders_by_id.items()
    }
    selected_grader_ids: set[str] = set()
    variants_value = spec.get("variants")
    declared_variant_profiles = {
        f"{variant.get('role')}/{variant.get('mode')}"
        for variant in variants_value
        if isinstance(variant, dict) and variant.get("role") in ROLES and variant.get("mode") in MODES
    } if isinstance(variants_value, list) else set()
    candidate_profiles = {
        profile for profile in declared_variant_profiles
        if profile in {"candidate/force_loaded", "candidate/natural_routing"}
    }
    primary_candidate_profile = (
        "candidate/natural_routing"
        if "candidate/natural_routing" in candidate_profiles
        else "candidate/force_loaded"
    )
    required_comparison_profiles = {
        "baseline/skill_disabled", primary_candidate_profile,
    }

    for record in cases:
        line = record.get("_line", "?")
        prefix = f"case line {line}"
        missing_fields = sorted(CASE_REQUIRED_FIELDS - set(record))
        if missing_fields:
            errors.append(f"{prefix}: missing required fields {missing_fields}")
        case_id = record.get("case_id")
        if not nonempty_string(case_id):
            errors.append(f"{prefix}: case_id must be a non-empty string")
        else:
            ids.append(case_id)
            prefix = f"case {case_id}"

        split = record.get("split")
        if split not in SPLITS:
            errors.append(f"{prefix}: split must be one of {sorted(SPLITS)}")
        else:
            splits[split] += 1

        if not nonempty_string(record.get("prompt")):
            errors.append(f"{prefix}: prompt must be a non-empty string")

        should_trigger = record.get("should_trigger")
        if should_trigger is not None and not isinstance(should_trigger, bool):
            errors.append(f"{prefix}: should_trigger must be true, false, or null")
        else:
            trigger_counts[str(should_trigger).lower()] += 1

        for field in sorted(LEGACY_CASE_FIELDS & set(record)):
            errors.append(f"{prefix}: forbidden legacy field {field}")

        for field in CASE_LIST_FIELDS:
            if field not in record:
                continue
            value = record.get(field)
            if not isinstance(value, list):
                errors.append(f"{prefix}: {field} must be an array")
            elif not all(nonempty_string(item) for item in value):
                errors.append(f"{prefix}: every {field} item must be a non-empty string")

        attribution = record.get("attribution_evaluable", False)
        if "attribution_evaluable" in record and not isinstance(attribution, bool):
            errors.append(f"{prefix}: attribution_evaluable must be boolean")
        profiles = record.get("applicable_variant_profiles")
        profile_set: set[str] = set()
        if isinstance(profiles, list):
            if not profiles:
                errors.append(f"{prefix}: applicable_variant_profiles must be a non-empty string array")
            profile_set = {item for item in profiles if nonempty_string(item)}
            unknown_profiles = sorted(profile_set - declared_variant_profiles)
            if unknown_profiles:
                errors.append(f"{prefix}: applicable_variant_profiles contains undeclared profiles {unknown_profiles}")
            if attribution is True:
                missing_profiles = sorted(required_comparison_profiles - profile_set)
                if missing_profiles:
                    errors.append(f"{prefix}: attribution-evaluable case is missing profiles {missing_profiles}")
        authoritative_inputs = record.get("authoritative_inputs")
        if "authoritative_inputs" in record and isinstance(authoritative_inputs, list) and not authoritative_inputs:
            errors.append(f"{prefix}: authoritative_inputs must not be empty")
        if isinstance(record.get("tags"), list) and "prompt-injection" in record["tags"]:
            adversarial_inputs = record.get("adversarial_inputs")
            if not isinstance(adversarial_inputs, list) or not adversarial_inputs:
                errors.append(f"{prefix}: prompt-injection case must declare adversarial_inputs")

        if isinstance(record.get("tags"), list):
            for tag in record["tags"]:
                if nonempty_string(tag):
                    tags[tag] += 1

        requirements = record.get("requirements")
        requirement_ids: list[str] = []
        grader_check_bindings: list[tuple[str, str]] = []
        weights_present: list[bool] = []
        dimension_weight_sums: Counter[str] = Counter()
        if not isinstance(requirements, list) or not requirements:
            errors.append(f"{prefix}: requirements must be a non-empty array")
        else:
            for requirement_index, requirement in enumerate(requirements):
                req_prefix = f"{prefix}: requirements[{requirement_index}]"
                if not isinstance(requirement, dict):
                    errors.append(f"{req_prefix} must be an object")
                    continue
                required_fields = {"id", "dimension", "required", "owner", "grader_id", "check_id"}
                missing = sorted(required_fields - set(requirement))
                if missing:
                    errors.append(f"{req_prefix} missing required fields {missing}")
                requirement_id = requirement.get("id")
                if not nonempty_string(requirement_id):
                    errors.append(f"{req_prefix}.id must be a non-empty string")
                else:
                    requirement_ids.append(requirement_id)
                dimension = requirement.get("dimension")
                if dimension not in REQUIREMENT_DIMENSIONS:
                    errors.append(f"{req_prefix}.dimension must be one of {sorted(REQUIREMENT_DIMENSIONS)}")
                required = requirement.get("required")
                if not isinstance(required, bool):
                    errors.append(f"{req_prefix}.required must be boolean")
                if dimension in {"outcome", "safety"} and required is not True:
                    errors.append(f"{dimension} requirement must be required")

                requirement_profiles = requirement.get("applicable_variant_profiles")
                if requirement_profiles is not None:
                    if (
                        not isinstance(requirement_profiles, list)
                        or not requirement_profiles
                        or not all(nonempty_string(item) for item in requirement_profiles)
                    ):
                        errors.append(
                            f"{req_prefix}.applicable_variant_profiles must be a non-empty string array"
                        )
                    elif len(set(requirement_profiles)) != len(requirement_profiles):
                        errors.append(
                            f"{req_prefix}.applicable_variant_profiles must not contain duplicates"
                        )
                    elif not set(requirement_profiles) <= profile_set:
                        errors.append(
                            f"{req_prefix}: requirement profiles are outside the case profiles"
                        )

                grader_id = requirement.get("grader_id")
                check_id = requirement.get("check_id")
                owner = requirement.get("owner")
                if "owner" in requirement and owner not in REQUIREMENT_OWNERS:
                    errors.append(f"{req_prefix}.owner must be one of {sorted(REQUIREMENT_OWNERS)}")
                if nonempty_string(grader_id) and nonempty_string(check_id):
                    grader_check_bindings.append((grader_id, check_id))
                    selected_grader_ids.add(grader_id)
                    if grader_id not in graders_by_id:
                        errors.append(f"{req_prefix} references unknown grader {grader_id}")
                    elif check_id not in checks_by_grader.get(grader_id, set()):
                        errors.append(f"{req_prefix} references unknown check {grader_id}/{check_id}")
                    else:
                        grader_type = graders_by_id[grader_id]["type"]
                        expected_owner = "deterministic" if grader_type == "deterministic" else "model"
                        if owner in REQUIREMENT_OWNERS and owner != expected_owner:
                            errors.append(
                                f"{req_prefix}.owner {owner} does not match grader type {grader_type}"
                            )
                else:
                    errors.append(f"{req_prefix}.grader_id and check_id must be non-empty strings")

                if dimension == "safety":
                    if requirement.get("severity") not in SAFETY_SEVERITIES:
                        errors.append(f"{req_prefix}.severity must be one of {sorted(SAFETY_SEVERITIES)}")
                    if requirement.get("safety_kind") not in SAFETY_KINDS:
                        errors.append(f"{req_prefix}.safety_kind must be one of {sorted(SAFETY_KINDS)}")
                    grader = graders_by_id.get(grader_id)
                    if isinstance(grader, dict) and grader.get("hard_gate") is not True:
                        errors.append(f"{req_prefix} safety requirement must map to a hard_gate grader")
                else:
                    for field in ("severity", "safety_kind"):
                        if field in requirement:
                            errors.append(f"{req_prefix} non-safety requirement forbids {field}")

                has_weight = "weight" in requirement
                weights_present.append(has_weight)
                if has_weight:
                    weight = requirement.get("weight")
                    if (
                        not isinstance(weight, (int, float))
                        or isinstance(weight, bool)
                        or not math.isfinite(float(weight))
                        or weight < 0
                    ):
                        errors.append(f"{req_prefix}.weight must be a finite non-negative number")
                    elif dimension in REQUIREMENT_DIMENSIONS:
                        dimension_weight_sums[dimension] += float(weight)

            duplicate_ids = sorted(name for name, count in Counter(requirement_ids).items() if count > 1)
            if duplicate_ids:
                errors.append(f"{prefix}: duplicate requirement IDs {duplicate_ids}")
            duplicate_bindings = sorted(binding for binding, count in Counter(grader_check_bindings).items() if count > 1)
            if duplicate_bindings:
                errors.append(f"{prefix}: duplicate grader/check binding {duplicate_bindings}")
            if any(weights_present) and not all(weights_present):
                errors.append(f"{prefix}: requirements must either all declare weight or all omit weight")
            if weights_present and all(weights_present):
                for dimension in {item.get("dimension") for item in requirements if isinstance(item, dict)}:
                    if dimension in REQUIREMENT_DIMENSIONS and dimension_weight_sums[dimension] <= 0:
                        errors.append(f"{prefix}: weighted {dimension} requirements must have positive total weight")

        if (
            level in {"L2", "L3", "L4"}
            and spec.get("ready_for_scored_run") is True
            and isinstance(record.get("tags"), list)
            and "protected" in record["tags"]
        ):
            if attribution is not False:
                errors.append(f"{prefix}: protected case must set attribution_evaluable=false")
            missing_profiles = sorted(required_comparison_profiles - profile_set)
            if missing_profiles:
                errors.append(f"{prefix}: protected case is missing profiles {missing_profiles}")
            if not isinstance(requirements, list) or not any(
                isinstance(requirement, dict)
                and requirement.get("dimension") == "outcome"
                and requirement.get("required") is True
                for requirement in requirements
            ):
                errors.append(f"{prefix}: protected case requires a required outcome requirement")

        timeout = record.get("timeout_seconds")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(float(timeout)) or timeout <= 0:
            errors.append(f"{prefix}: timeout_seconds must be positive")

        risk = record.get("risk")
        if risk not in RISKS:
            errors.append(f"{prefix}: risk must be one of {sorted(RISKS)}")
        else:
            risks[risk] += 1

        fixture = record.get("fixture")
        if not isinstance(fixture, dict) or set(fixture) != {"manifest", "sha256"}:
            errors.append(f"{prefix}: fixture must contain exactly manifest and sha256")
        else:
            manifest = fixture.get("manifest")
            sha256 = fixture.get("sha256")
            if not nonempty_string(manifest):
                errors.append(f"{prefix}: fixture.manifest must be a non-empty relative path")
            if fixture == NONREADY_FIXTURE_SENTINEL:
                placeholder_fixtures += 1
                if spec.get("ready_for_scored_run") is True:
                    errors.append("scored-ready fixture manifest placeholder is forbidden")
            elif not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
                errors.append(f"{prefix}: fixture.sha256 must be sha256:<64 hex>")

    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate case IDs: {duplicates}")

    for grader_id in sorted(selected_grader_ids):
        grader = graders_by_id.get(grader_id)
        if isinstance(grader, dict) and grader.get("type") == "deterministic" and "verifier" not in grader:
            errors.append(f"selected deterministic grader {grader_id} must declare verifier")

    if level in {"L2", "L3", "L4"} and len(cases) < 10:
        warnings.append("L2+ suite has fewer than the practical 10-case starter; justify finite coverage or add representative cases")
    if level in {"L3", "L4"} and splits["heldout"] == 0:
        errors.append("L3/L4 suite must include heldout cases")
    elif level == "L2" and splits["heldout"] == 0:
        warnings.append("L2 suite has no heldout cases; limit the claim or add a sequestered slice")

    variants_value = spec.get("variants")
    variant_modes = {variant.get("mode") for variant in variants_value if isinstance(variant, dict)} if isinstance(variants_value, list) else set()
    if "natural_routing" in variant_modes:
        if trigger_counts["true"] == 0:
            errors.append("natural-routing evaluation needs should_trigger=true cases")
        if trigger_counts["false"] == 0:
            errors.append("natural-routing evaluation needs negative-control should_trigger=false cases")
        required_route_tags = {"routing-explicit", "routing-implicit", "routing-contextual", "routing-negative"}
        missing = sorted(tag for tag in required_route_tags if tags[tag] == 0)
        if missing:
            warnings.append(f"routing coverage is missing recommended tags: {missing}")

    if (level in {"L3", "L4"} or spec.get("risk_tier") == "high") and tags["safety"] == 0:
        errors.append("high-risk or L3/L4 suite must include safety-tagged cases")
    elif tags["safety"] == 0:
        warnings.append("suite has no safety-tagged case; confirm that runtime safety is out of scope")

    if splits["regression"] == 0:
        warnings.append("suite has no regression cases; add confirmed historical failures as they occur")
    if (
        level in {"L2", "L3", "L4"}
        and spec.get("ready_for_scored_run") is True
        and tags["protected"] == 0
    ):
        errors.append("scored-ready L2+ suite requires at least one protected case")
    if placeholder_fixtures:
        warnings.append("non-ready fixture manifest placeholder")

    return {
        "case_count": len(cases),
        "splits": dict(sorted(splits.items())),
        "trigger_labels": dict(sorted(trigger_counts.items())),
        "risks": dict(sorted(risks.items())),
        "tags": dict(tags.most_common()),
    }


def resolve_contained_path(root: Path, reference: str) -> Path:
    relative = Path(reference)
    if relative.is_absolute() or "\\" in reference or ".." in relative.parts:
        raise ValueError("path must be relative and must not contain backslashes or parent traversal")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("path escapes its declared root")
    return resolved


def check_bound_paths(
    spec: dict[str, Any], spec_path: Path, cases_path: Path, cases: list[dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> None:
    suite = spec.get("suite")
    if isinstance(suite, dict) and nonempty_string(suite.get("cases_file")):
        expected = (spec_path.parent / suite["cases_file"]).resolve()
        actual = cases_path.resolve()
        if expected != actual:
            errors.append(f"supplied cases file does not match spec.suite.cases_file: expected {expected}, got {actual}")
        clean_cases = [
            {key: value for key, value in case.items() if key != "_line"}
            for case in cases
        ]
        derived_bindings = {
            "cases_content_hash": canonical_sha256(clean_cases),
            "fixture_manifest_set_hash": canonical_sha256([
                {"case_id": case.get("case_id"), "fixture": case.get("fixture")}
                for case in clean_cases
            ]),
        }
        for field, actual_hash in derived_bindings.items():
            expected_hash = suite.get(field)
            if (
                spec.get("ready_for_scored_run") is True
                and isinstance(expected_hash, str)
                and SHA256_RE.fullmatch(expected_hash)
                and expected_hash != actual_hash
            ):
                errors.append(f"spec.suite.{field} mismatch: expected {expected_hash}, got {actual_hash}")
        holdout = suite.get("holdout_control")
        if isinstance(holdout, dict):
            for file_field, hash_field in (("manifest_file", "manifest_hash"), ("payload_file", "payload_hash")):
                ref = holdout.get(file_field)
                if not nonempty_string(ref):
                    continue
                path = (spec_path.parent / ref).resolve()
                if not path.is_file():
                    errors.append(f"spec.suite.holdout_control.{file_field} does not exist: {path}")
                    continue
                expected_hash = holdout.get(hash_field)
                actual_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                if isinstance(expected_hash, str) and expected_hash != actual_hash:
                    errors.append(f"spec.suite.holdout_control.{hash_field} mismatch: expected {expected_hash}, got {actual_hash}")

    spec_root = spec_path.parent.resolve()
    ready = spec.get("ready_for_scored_run") is True
    graders = spec.get("graders")
    for index, grader in enumerate(graders if isinstance(graders, list) else []):
        if not isinstance(grader, dict):
            continue
        prefix = f"spec.graders[{index}]"
        if grader.get("type") == "deterministic" and isinstance(grader.get("verifier"), dict):
            verifier = grader["verifier"]
            if verifier.get("sha256") == NONREADY_SHA256_SENTINEL and not ready:
                continue
            try:
                verifier_path = resolve_contained_path(spec_root, str(verifier.get("path", "")))
            except ValueError as exc:
                errors.append(f"{prefix}.verifier.path {exc}")
                continue
            if not verifier_path.is_file():
                errors.append(f"{prefix}.verifier.path is not a regular file: {verifier_path}")
                continue
            actual_hash = "sha256:" + hashlib.sha256(verifier_path.read_bytes()).hexdigest()
            if verifier.get("sha256") != actual_hash:
                errors.append(f"{prefix}.verifier.sha256 mismatch: expected {verifier.get('sha256')}, got {actual_hash}")
        elif grader.get("type") == "model_rubric":
            for field in ("prompt_path", "schema_path"):
                reference = grader.get(field)
                if not nonempty_string(reference):
                    continue
                try:
                    bound_path = resolve_contained_path(spec_root, reference)
                except ValueError as exc:
                    errors.append(f"{prefix}.{field} {exc}")
                    continue
                if not bound_path.is_file():
                    errors.append(f"{prefix}.{field} is not a regular file: {bound_path}")
                    continue
                if field == "schema_path":
                    try:
                        parsed_schema = json.loads(bound_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        errors.append(f"{prefix}.schema_path is not readable valid JSON: {bound_path}: {exc}")
                        continue
                    if not isinstance(parsed_schema, dict) or parsed_schema.get("type") != "object":
                        warnings.append(f"{prefix}.schema_path is not an object-root JSON Schema: {bound_path}")

    artifacts = spec.get("artifacts")
    artifacts_reference = artifacts.get("root") if isinstance(artifacts, dict) else None
    if nonempty_string(artifacts_reference):
        try:
            artifacts_root = resolve_contained_path(spec_root, artifacts_reference)
        except ValueError as exc:
            errors.append(f"spec.artifacts.root {exc}")
            artifacts_root = None
        if artifacts_root is not None:
            for case in cases:
                fixture = case.get("fixture")
                if not isinstance(fixture, dict) or fixture == NONREADY_FIXTURE_SENTINEL:
                    continue
                case_id = case.get("case_id", "<unknown>")
                try:
                    manifest_path = resolve_contained_path(artifacts_root, str(fixture.get("manifest", "")))
                except ValueError as exc:
                    errors.append(f"case {case_id}: fixture.manifest {exc}")
                    continue
                if not manifest_path.is_file():
                    errors.append(f"case {case_id}: fixture.manifest is not a regular file: {manifest_path}")
                    continue
                actual_hash = "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                if fixture.get("sha256") != actual_hash:
                    errors.append(f"case {case_id}: fixture.sha256 mismatch: expected {fixture.get('sha256')}, got {actual_hash}")
                    continue
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"case {case_id}: fixture manifest is not valid JSON: {exc}")
                    continue
                manifest_artifacts = manifest.get("artifacts") if isinstance(manifest, dict) else None
                if not isinstance(manifest_artifacts, list):
                    errors.append(f"case {case_id}: fixture manifest artifacts must be an array")
                    continue
                for artifact_index, artifact in enumerate(manifest_artifacts):
                    artifact_prefix = f"case {case_id}: fixture artifacts[{artifact_index}]"
                    if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "encoding"}:
                        errors.append(f"{artifact_prefix} must contain exactly path, sha256, and encoding")
                        continue
                    if not nonempty_string(artifact.get("path")):
                        errors.append(f"{artifact_prefix}.path must be a non-empty relative path")
                    else:
                        try:
                            resolve_contained_path(manifest_path.parent, artifact["path"])
                        except ValueError as exc:
                            errors.append(f"{artifact_prefix}.path {exc}")
                    if not isinstance(artifact.get("sha256"), str) or not SHA256_RE.fullmatch(artifact["sha256"]):
                        errors.append(f"{artifact_prefix}.sha256 must be sha256:<64 hex>")
                    if artifact.get("encoding") not in {"utf-8", "binary"}:
                        errors.append(f"{artifact_prefix}.encoding must be utf-8 or binary")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", help="Evaluation spec JSON")
    parser.add_argument("cases", nargs="?", help="Case suite JSONL; required for L1+")
    parser.add_argument("--json", metavar="PATH", help="Write validation report JSON; use - for stdout")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    cases: list[dict[str, Any]] = []
    cases_path: Path | None = None
    public_case_count = 0
    holdout_case_count = 0
    try:
        spec_path = Path(args.spec)
        spec = load_json(spec_path)
        if args.cases:
            cases_path = Path(args.cases)
            cases = load_jsonl(cases_path)
            public_case_count = len(cases)
            public_heldout = [case.get("case_id") for case in cases if case.get("split") == "heldout"]
            if public_heldout:
                errors.append(f"public cases file contains heldout payload rows: {public_heldout}")
            if isinstance(spec, dict):
                suite = spec.get("suite")
                control = suite.get("holdout_control") if isinstance(suite, dict) else None
                payload_ref = control.get("payload_file") if isinstance(control, dict) else None
                if nonempty_string(payload_ref):
                    payload_path = (spec_path.parent / payload_ref).resolve()
                    holdout_cases = load_jsonl(payload_path)
                    holdout_case_count = len(holdout_cases)
                    non_holdout = [case.get("case_id") for case in holdout_cases if case.get("split") != "heldout"]
                    if non_holdout:
                        errors.append(f"holdout payload contains non-heldout rows: {non_holdout}")
                    manifest_ref = control.get("manifest_file") if isinstance(control, dict) else None
                    if nonempty_string(manifest_ref):
                        manifest_path = (spec_path.parent / manifest_ref).resolve()
                        manifest = load_json(manifest_path)
                        if not isinstance(manifest, dict):
                            errors.append("holdout manifest must be a JSON object")
                        else:
                            actual_payload_hash = "sha256:" + hashlib.sha256(payload_path.read_bytes()).hexdigest()
                            if manifest.get("payload_sha256") != actual_payload_hash:
                                errors.append("holdout manifest payload_sha256 does not match holdout payload bytes")
                            payload_ids = [case.get("case_id") for case in holdout_cases]
                            if manifest.get("case_count") != len(holdout_cases):
                                errors.append("holdout manifest case_count does not match payload")
                            if manifest.get("case_ids") != payload_ids:
                                errors.append("holdout manifest case_ids do not match payload order")
                            entries = manifest.get("cases")
                            if not isinstance(entries, list) or len(entries) != len(holdout_cases):
                                errors.append("holdout manifest cases entries do not match payload count")
                            else:
                                for case, entry in zip(holdout_cases, entries):
                                    canonical_case = {key: value for key, value in case.items() if key != "_line"}
                                    if not isinstance(entry, dict) or entry.get("case_id") != case.get("case_id"):
                                        errors.append(f"holdout manifest entry ID mismatch for {case.get('case_id')}")
                                    elif entry.get("case_sha256") != canonical_sha256(canonical_case):
                                        errors.append(f"holdout manifest case_sha256 mismatch for {case.get('case_id')}")
                    cases.extend(holdout_cases)
    except ValueError as exc:
        print(f"validation error: {exc}", file=sys.stderr)
        return 2

    check_spec(spec, errors, warnings)
    level = spec.get("level") if isinstance(spec, dict) else None
    if level != "L0" and cases_path is None:
        errors.append("L1+ validation requires a cases argument")
    coverage = check_cases(spec, cases, errors, warnings) if cases and isinstance(spec, dict) else {"case_count": 0}
    coverage["public_case_count"] = public_case_count
    coverage["holdout_case_count"] = holdout_case_count
    if isinstance(spec, dict) and cases_path is not None:
        check_bound_paths(spec, spec_path, cases_path, cases, errors, warnings)

    report = {
        "schema_version": 1,
        "valid": not errors and (not args.strict or not warnings),
        "strict": args.strict,
        "errors": errors,
        "warnings": warnings,
        "coverage": coverage,
    }

    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    try:
        if args.json == "-":
            sys.stdout.write(payload)
        elif args.json:
            Path(args.json).write_text(payload, encoding="utf-8")
    except OSError as exc:
        print(f"validation output error: {exc}", file=sys.stderr)
        return 2

    status = "VALID" if not errors else "INVALID"
    if not errors and warnings:
        status = "VALID WITH WARNINGS"
    if args.strict and warnings and not errors:
        status = "INVALID IN STRICT MODE"
    status_stream = sys.stderr if args.json == "-" else sys.stdout
    print(f"{status}: {len(cases)} cases, {len(errors)} errors, {len(warnings)} warnings", file=status_stream)
    for error in errors:
        print(f"ERROR: {error}", file=status_stream)
    for warning in warnings:
        print(f"WARN: {warning}", file=status_stream)

    return 1 if errors or (args.strict and warnings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
