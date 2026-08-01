#!/usr/bin/env python3
"""Validate a skill-evaluation spec and JSONL task suite using only stdlib."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from evidence_io import (
    atomic_write_bytes,
    canonical_json_bytes,
    canonical_self_hash,
    canonical_sha256,
    file_sha256,
    load_json,
    load_jsonl_objects,
    resolve_contained_path as resolve_evidence_path,
    validate_locator,
    verify_self_hash,
)
from reviewer_pair_contract import (
    ReviewerPairError,
    read_nofollow_regular,
    validate_reviewer_pair,
)

LEVELS = {"L0", "L1", "L2", "L3", "L4"}
SPLITS = {"dev", "regression", "heldout"}
RISKS = {"low", "standard", "high"}
MODES = {"skill_disabled", "force_loaded", "natural_routing"}
ROLES = {"baseline", "candidate", "prior"}
REQUIREMENT_OWNERS = {"deterministic", "model"}
COMPARATORS = {"baseline", "prior"}
BENEFIT_DIRECTIONS = {"higher_is_better", "lower_is_better"}
BENEFIT_EFFECTS = {"absolute", "relative"}
PAIRED_METRIC_DIRECTIONS = {
    "task_pass_rate": "higher_is_better",
    "safety_pass_rate": "higher_is_better",
    "process_score_normalized": "higher_is_better",
    "quality_score_normalized": "higher_is_better",
    "tokens_in": "lower_is_better",
    "tokens_out": "lower_is_better",
    "task_tool_calls": "lower_is_better",
    "executor_prewrite_task_tool_calls": "lower_is_better",
    "executor_prewrite_tool_output_bytes": "lower_is_better",
    "host_preflight_tool_output_bytes": "lower_is_better",
    "skill_context_bytes": "lower_is_better",
    "controlled_skill_context_bytes": "lower_is_better",
    "controlled_core_skill_context_bytes": "lower_is_better",
    "host_injected_body_count": "lower_is_better",
    "model_initiated_body_read_count": "lower_is_better",
    "reference_load_count": "lower_is_better",
    "skill_load_tool_calls": "lower_is_better",
    "skill_protocol_tool_calls": "lower_is_better",
    "workflow_artifact_count": "lower_is_better",
}
PAIRED_METRICS = set(PAIRED_METRIC_DIRECTIONS)
COST_METRICS = {
    metric for metric, direction in PAIRED_METRIC_DIRECTIONS.items()
    if direction == "lower_is_better"
}
RELATIVE_EFFECT_METRICS = {
    "tokens_in", "tokens_out", "skill_context_bytes",
    "controlled_skill_context_bytes", "controlled_core_skill_context_bytes",
}
CANONICAL_VARIANT_PROFILES = {
    "baseline/skill_disabled",
    "candidate/force_loaded",
    "candidate/natural_routing",
    "prior/force_loaded",
    "prior/natural_routing",
}
GLOBAL_GATE_METRICS = {
    "critical_safety_incidents", "unauthorized_side_effects", "protected_outcome_failures",
    "paired_case_count",
    "skill_context_attribution_rate", "skill_context_bytes_p95", "skill_context_tokens_p95",
    "controlled_skill_context_bytes_p95", "host_integration_duplicate_bytes_max",
    "unexplained_repeated_static_content_bytes_max",
    "unattributed_model_body_read_count_max", "protocol_output_bytes_max",
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
SUPPORTED_DECLARED_METRICS = GLOBAL_GATE_METRICS | VARIANT_GATE_METRICS | PAIRED_METRICS
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
V5_SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
V5_SCHEMA_NAMES = {
    "analysis-summary-v4.schema.json",
    "eval-spec-v5.schema.json",
    "execution-plan-v1.schema.json",
    "failure-index-v1.schema.json",
    "grader-calibration-v1.schema.json",
    "host-manifest-v1.schema.json",
    "receipt-v4.schema.json",
    "run-index-row-v2.schema.json",
    "scenario-v1.schema.json",
    "suite-quality-v1.schema.json",
}


def _json_pointer(path: tuple[object, ...]) -> str:
    if not path:
        return ""
    return "/" + "/".join(
        str(part).replace("~", "~0").replace("/", "~1")
        for part in path
    )


def _schema_error(
    errors: list[dict[str, str]],
    keyword: str,
    path: tuple[object, ...],
    message: str,
) -> None:
    errors.append({
        "family": "schema",
        "code": f"schema.{keyword}",
        "path": _json_pointer(path),
        "message": message,
    })


def _json_equal(left: Any, right: Any) -> bool:
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise ValueError(f"unsupported schema type: {expected}")


def load_v5_schema_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for name in sorted(V5_SCHEMA_NAMES):
        schema = load_json(V5_SCHEMA_DIR / name)
        if not isinstance(schema, dict):
            raise ValueError(f"schema is not an object: {name}")
        expected_id = f"https://example.invalid/skill-evaluator/schemas/{name}"
        if schema.get("$id") != expected_id:
            raise ValueError(f"schema $id mismatch: {name}")
        registry[name] = schema
    return registry


def _resolve_schema_ref(
    reference: str,
    current_name: str,
    registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    relative, separator, fragment = reference.partition("#")
    target_name = current_name
    if relative:
        target_name = Path(relative).name
        if relative != target_name or target_name not in registry:
            raise ValueError(f"unsupported schema reference: {reference}")
    target: Any = registry[target_name]
    if separator and fragment:
        if not fragment.startswith("/"):
            raise ValueError(f"unsupported schema fragment: {reference}")
        for raw_token in fragment[1:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or token not in target:
                raise ValueError(f"unresolved schema reference: {reference}")
            target = target[token]
    if not isinstance(target, dict):
        raise ValueError(f"schema reference is not an object: {reference}")
    return target, target_name


def _validate_schema_node(
    value: Any,
    schema: dict[str, Any],
    current_name: str,
    registry: dict[str, dict[str, Any]],
    path: tuple[object, ...],
    errors: list[dict[str, str]],
) -> None:
    if "$ref" in schema:
        target, target_name = _resolve_schema_ref(
            schema["$ref"], current_name, registry,
        )
        _validate_schema_node(value, target, target_name, registry, path, errors)
        return

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = (
            expected_type if isinstance(expected_type, list) else [expected_type]
        )
        if not any(_schema_type_matches(value, item) for item in expected_types):
            _schema_error(
                errors, "type", path,
                f"expected {'|'.join(expected_types)}, got {type(value).__name__}",
            )
            return

    if "const" in schema and not _json_equal(value, schema["const"]):
        _schema_error(errors, "const", path, f"must equal {schema['const']!r}")
    if "enum" in schema and not any(
        _json_equal(value, item) for item in schema["enum"]
    ):
        _schema_error(errors, "enum", path, "value is outside the allowed enum")

    for keyword in ("allOf",):
        for branch in schema.get(keyword, []):
            _validate_schema_node(
                value, branch, current_name, registry, path, errors,
            )

    for keyword in ("oneOf", "anyOf"):
        if keyword not in schema:
            continue
        matches = 0
        for branch in schema[keyword]:
            branch_errors: list[dict[str, str]] = []
            _validate_schema_node(
                value, branch, current_name, registry, path, branch_errors,
            )
            matches += not branch_errors
        valid = matches == 1 if keyword == "oneOf" else matches >= 1
        if not valid:
            _schema_error(
                errors, keyword, path,
                f"matched {matches} of {len(schema[keyword])} branches",
            )

    if "not" in schema:
        branch_errors: list[dict[str, str]] = []
        _validate_schema_node(
            value, schema["not"], current_name, registry, path, branch_errors,
        )
        if not branch_errors:
            _schema_error(errors, "not", path, "forbidden schema matched")

    if "if" in schema:
        condition_errors: list[dict[str, str]] = []
        _validate_schema_node(
            value, schema["if"], current_name, registry, path, condition_errors,
        )
        selected = "then" if not condition_errors else "else"
        if selected in schema:
            _validate_schema_node(
                value, schema[selected], current_name, registry, path, errors,
            )

    if isinstance(value, dict):
        required = schema.get("required", [])
        for field in required:
            if field not in value:
                _schema_error(
                    errors, "required", path,
                    f"missing required property {field!r}",
                )
        properties = schema.get("properties", {})
        for field, child in properties.items():
            if field in value:
                _validate_schema_node(
                    value[field], child, current_name, registry,
                    path + (field,), errors,
                )
        additional = schema.get("additionalProperties")
        extras = sorted(set(value) - set(properties))
        if additional is False:
            for field in extras:
                _schema_error(
                    errors, "additionalProperties", path + (field,),
                    f"unexpected property {field!r}",
                )
        elif isinstance(additional, dict):
            for field in extras:
                _validate_schema_node(
                    value[field], additional, current_name, registry,
                    path + (field,), errors,
                )
        if len(value) < schema.get("minProperties", 0):
            _schema_error(errors, "minProperties", path, "object is too small")
        property_names = schema.get("propertyNames")
        if isinstance(property_names, dict):
            for field in value:
                _validate_schema_node(
                    field, property_names, current_name, registry,
                    path + (field,), errors,
                )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            _schema_error(errors, "minItems", path, "array is too short")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            _schema_error(errors, "maxItems", path, "array is too long")
        if schema.get("uniqueItems"):
            seen: set[bytes] = set()
            for index, item in enumerate(value):
                marker = canonical_json_bytes(item)
                if marker in seen:
                    _schema_error(
                        errors, "uniqueItems", path + (index,),
                        "array item is duplicated",
                    )
                seen.add(marker)
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                _validate_schema_node(
                    item, schema["items"], current_name, registry,
                    path + (index,), errors,
                )

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            _schema_error(errors, "minLength", path, "string is too short")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            _schema_error(errors, "pattern", path, "string does not match pattern")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        checks = (
            ("minimum", lambda limit: value < limit),
            ("maximum", lambda limit: value > limit),
            ("exclusiveMinimum", lambda limit: value <= limit),
            ("exclusiveMaximum", lambda limit: value >= limit),
        )
        for keyword, violates in checks:
            if keyword in schema and violates(schema[keyword]):
                _schema_error(errors, keyword, path, f"number violates {keyword}")


def validate_v5_schema(
    value: Any,
    schema_name: str,
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    if schema_name not in registry:
        raise ValueError(f"schema is not loaded: {schema_name}")
    errors: list[dict[str, str]] = []
    _validate_schema_node(
        value, registry[schema_name], schema_name, registry, (), errors,
    )
    return errors


HOST_PROTOCOL_OWNERS = {
    "host_request",
    "host_event",
    "host_result",
    "checkpoint",
    "protocol_error",
    "principal",
    "handoff",
    "authorization_decision",
    "action_trace",
}
ACTION_STAGE_ORDER = (
    "declared",
    "discovered",
    "loaded",
    "model_visible",
    "selected",
    "invoked",
    "authorization_requested",
    "authorization_resolved",
    "executed",
    "raw_backend_result",
    "model_delivered_result",
    "rendered_or_displayed",
    "effect_observed",
    "effect_confirmed",
)


def validate_host_protocol_record(
    owner: str,
    record: Any,
    registry: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    if owner not in HOST_PROTOCOL_OWNERS:
        raise ValueError(f"unknown host protocol owner: {owner}")
    active_registry = registry or load_v5_schema_registry()
    errors: list[dict[str, str]] = []
    schema = active_registry["host-manifest-v1.schema.json"]["$defs"][owner]
    _validate_schema_node(
        record,
        schema,
        "host-manifest-v1.schema.json",
        active_registry,
        (),
        errors,
    )
    if errors or not isinstance(record, dict):
        return errors

    def semantic(code: str, path: str, message: str) -> None:
        errors.append(_contract_diagnostic("host_protocol", code, path, message))

    if owner == "host_request":
        expected = canonical_self_hash(record, "request_hash")
        if record.get("request_hash") != expected:
            semantic(
                "host_protocol.request_hash",
                "/request_hash",
                f"request_hash must be {expected}",
            )
    elif owner == "host_event":
        parent = record.get("parent_seq")
        if parent is not None and parent >= record["seq"]:
            semantic(
                "host_protocol.event_parent",
                "/parent_seq",
                "parent_seq must precede seq",
            )
    elif owner == "principal":
        if record.get("parent_principal_id") == record.get("principal_id"):
            semantic(
                "host_protocol.principal_parent",
                "/parent_principal_id",
                "principal cannot be its own parent",
            )
        started = _parse_rfc3339_seconds(record["started_at"], "/started_at")
        ended = _parse_rfc3339_seconds(record["ended_at"], "/ended_at")
        if started > ended:
            semantic(
                "host_protocol.principal_time",
                "/ended_at",
                "principal ended_at precedes started_at",
            )
        requested = record.get("requested_budget", {})
        effective = record.get("effective_budget", {})
        for field in ("turns", "tokens", "seconds", "tool_calls"):
            if effective.get(field, 0) > requested.get(field, 0):
                semantic(
                    "host_protocol.principal_budget",
                    f"/effective_budget/{field}",
                    "effective budget exceeds requested budget",
                )
    elif owner == "handoff":
        if record.get("sender_principal_id") == record.get(
            "receiver_principal_id",
        ):
            semantic(
                "host_protocol.handoff_principal",
                "/receiver_principal_id",
                "handoff sender and receiver must differ",
            )
        has_result = record.get("raw_result") is not None
        if (record.get("status") == "result") != has_result:
            semantic(
                "host_protocol.handoff_result",
                "/raw_result",
                "raw_result is present exactly when handoff status is result",
            )
    elif owner == "action_trace":
        stages = record.get("stages", [])
        names = [stage.get("stage") for stage in stages]
        ordinals = [ACTION_STAGE_ORDER.index(name) for name in names]
        seqs = [stage.get("seq") for stage in stages]
        if (
            len(names) != len(set(names))
            or ordinals != sorted(ordinals)
            or seqs != sorted(seqs)
            or len(seqs) != len(set(seqs))
        ):
            semantic(
                "host_protocol.action_order",
                "/stages",
                "action stages and sequence numbers must be unique and ordered",
            )
        source_decisions = [
            item.get("decision")
            for item in record.get("authorization_decisions", [])
        ]
        derived = (
            "deny"
            if "deny" in source_decisions
            else "allow_with_changes"
            if "allow_with_changes" in source_decisions
            else "allow"
        )
        if record.get("resolved_decision") != derived:
            semantic(
                "host_protocol.authorization_resolution",
                "/resolved_decision",
                f"resolved decision must be {derived}",
            )
        if record.get("resolved_decision") == "deny" and any(
            record.get(field) is not None
            for field in (
                "executed_input", "backend_request", "backend_result",
                "model_delivered_result", "visible_result", "confirmed_effect",
            )
        ):
            semantic(
                "host_protocol.denied_execution",
                "/resolved_decision",
                "denied action cannot contain execution or effect artifacts",
            )
        if (
            "effect_confirmed" in names
            and record.get("confirmed_effect") is None
        ):
            semantic(
                "host_protocol.effect_confirmation",
                "/confirmed_effect",
                "effect_confirmed stage requires confirmed-effect evidence",
            )
    elif owner == "host_result":
        principals = record.get("principals", [])
        principal_ids = [item.get("principal_id") for item in principals]
        if len(principal_ids) != len(set(principal_ids)):
            semantic(
                "host_protocol.principal_duplicate",
                "/principals",
                "principal IDs must be unique",
            )
        principal_set = set(principal_ids)
        for index, handoff in enumerate(record.get("handoffs", [])):
            if not {
                handoff.get("sender_principal_id"),
                handoff.get("receiver_principal_id"),
            } <= principal_set:
                semantic(
                    "host_protocol.handoff_join",
                    f"/handoffs/{index}",
                    "handoff principals must exist in the result principal set",
                )
        for index, action in enumerate(record.get("actions", [])):
            if action.get("principal_id") not in principal_set:
                semantic(
                    "host_protocol.action_principal_join",
                    f"/actions/{index}/principal_id",
                    "action principal must exist in the result principal set",
                )
            for diagnostic in validate_host_protocol_record(
                "action_trace", action, active_registry,
            ):
                errors.append({
                    **diagnostic,
                    "path": f"/actions/{index}{diagnostic['path']}",
                })
    return errors


V5_MODULES = {
    "core_outcome",
    "natural_routing",
    "catalog_routing",
    "declared_composition",
    "multi_principal_coordination",
    "multi_turn_state",
    "tool_faults",
    "host_conformance",
    "dynamic_security",
    "longitudinal",
}
V5_MODULE_CAPABILITIES = {
    "natural_routing": {"discovery", "natural_routing"},
    "catalog_routing": {"catalog_snapshot"},
    "declared_composition": {"composition"},
    "multi_principal_coordination": {
        "principal_tracing", "handoff_capture",
    },
    "multi_turn_state": {"multi_turn", "state_snapshot_reset"},
    "tool_faults": {"fault_injection"},
    "dynamic_security": {
        "action_authorization_trace", "render_effect_capture",
    },
    "longitudinal": {"clock_capture"},
}
V5_READINESS_WARNING_CODES = {
    "non_ready.execution",
    "non_ready.calibration",
    "non_ready.quality",
    "non_ready.verifier",
    "non_ready.fixture",
}


def _add_contract_error(
    errors: list[dict[str, str]],
    code: str,
    path: str,
    message: str,
) -> None:
    errors.append(_contract_diagnostic("contract", code, path, message))


def _add_readiness_warning(
    warnings: list[dict[str, str]],
    code: str,
    path: str,
    message: str,
) -> None:
    if code not in V5_READINESS_WARNING_CODES:
        raise ValueError(f"unknown readiness warning code: {code}")
    warnings.append(_contract_diagnostic("readiness", code, path, message))


def treatment_contract_projection(treatments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for treatment in treatments:
        item = dict(treatment)
        item["intervention_axes"] = sorted(
            treatment.get("intervention_axes", []),
        )
        normalized.append(item)
    return sorted(
        normalized,
        key=lambda item: (
            item.get("treatment_id", ""),
            canonical_json_bytes(item),
        ),
    )


def v5_treatment_contract_hash(treatments: list[dict[str, Any]]) -> str:
    return canonical_sha256(treatment_contract_projection(treatments))


def v5_fixture_set_hash(scenarios: list[dict[str, Any]]) -> str:
    return canonical_sha256([
        {
            "case_id": scenario.get("case_id"),
            "fixture": scenario.get("fixture"),
        }
        for scenario in sorted(
            scenarios, key=lambda item: item.get("case_id", ""),
        )
    ])


def v5_grader_set_hash(graders: list[dict[str, Any]]) -> str:
    return canonical_sha256(sorted(
        graders,
        key=lambda item: (
            item.get("grader_id", ""),
            canonical_json_bytes(item),
        ),
    ))


def v5_grader_schedule_hash(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> str:
    graders = spec.get("graders", [])
    return canonical_sha256({
        "grader_ids": sorted(
            grader.get("grader_id") for grader in graders
            if isinstance(grader, dict)
        ),
        "order_seed": spec.get("suite", {}).get("order_seed"),
        "scenario_checks": [
            {
                "case_id": scenario.get("case_id"),
                "checks": sorted(
                    (
                        requirement.get("grader_id"),
                        requirement.get("check_id"),
                    )
                    for requirement in scenario.get("requirements", [])
                    if isinstance(requirement, dict)
                ),
            }
            for scenario in sorted(
                scenarios, key=lambda item: item.get("case_id", ""),
            )
        ],
    })


def quality_contract_projection(spec: dict[str, Any]) -> dict[str, Any]:
    suite = spec.get("suite", {})
    calibration = suite.get("calibration")
    quality_gates = [
        gate
        for gate in spec.get("hard_gates", [])
        if isinstance(gate, dict)
        and gate.get("kind") in {"quality", "calibration"}
    ]
    return {
        "evaluation_id": spec.get("evaluation_id"),
        "subject": {
            "shape": spec.get("subject", {}).get("shape"),
            "mechanisms": sorted(
                spec.get("subject", {}).get("mechanisms", []),
            ),
        },
        "applicability": sorted(
            spec.get("applicability", []),
            key=lambda item: item.get("module", ""),
        ),
        "bindings": {
            "scenarios": suite.get("scenarios"),
            "public_scenarios": suite.get("public_scenarios"),
            "holdout": suite.get("holdout"),
            "fixture_set_hash": suite.get("fixture_set_hash"),
            "grader_set_hash": suite.get("grader_set_hash"),
            "grader_schedule_hash": suite.get("grader_schedule_hash"),
            "treatment_contract_hash": suite.get("treatment_contract_hash"),
            "calibration": calibration if calibration is not None else None,
        },
        "thresholds": quality_gates,
        "required_coverage": sorted(
            item.get("module")
            for item in spec.get("applicability", [])
            if isinstance(item, dict) and item.get("status") == "required"
        ),
    }


def quality_contract_hash(spec: dict[str, Any]) -> str:
    return canonical_sha256(quality_contract_projection(spec))


def _check_bound_file(
    binding: dict[str, Any],
    *,
    root: Path,
    label: str,
    path: str,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    ready: bool,
    nonready_code: str | None = None,
    expected_path: Path | None = None,
) -> Path | None:
    try:
        _, resolved = resolve_evidence_path(
            root, binding.get("path"), label,
        )
    except (OSError, ValueError) as exc:
        _add_contract_error(errors, "path.invalid", path + "/path", str(exc))
        return None
    if expected_path is not None and resolved != expected_path.resolve():
        _add_contract_error(
            errors,
            "binding.path_mismatch",
            path + "/path",
            f"{label} resolves to {resolved}, expected {expected_path.resolve()}",
        )
        return None
    if not resolved.is_file():
        if not ready and nonready_code is not None:
            _add_readiness_warning(
                warnings, nonready_code, path,
                f"{label} is not materialized for this non-ready template",
            )
        else:
            _add_contract_error(
                errors, "binding.file_missing", path,
                f"{label} is not a regular file: {resolved}",
            )
        return None
    actual_hash = file_sha256(resolved)
    if binding.get("sha256") != actual_hash:
        _add_contract_error(
            errors, "binding.hash_mismatch", path + "/sha256",
            f"{label} hash is {actual_hash}",
        )
        return None
    return resolved


def _validate_self_hashed_artifact(
    value: Any,
    *,
    schema_name: str,
    hash_field: str,
    path: str,
    registry: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    for diagnostic in validate_v5_schema(value, schema_name, registry):
        errors.append({
            **diagnostic,
            "path": path + diagnostic["path"],
        })
    if isinstance(value, dict) and not verify_self_hash(value, hash_field):
        _add_contract_error(
            errors, "self_hash.mismatch", path + "/" + hash_field,
            f"{hash_field} does not match canonical artifact bytes",
        )


def required_v5_modules(spec: dict[str, Any]) -> set[str]:
    required: set[str] = set()
    level = spec.get("level")
    subject = spec.get("subject", {})
    shape = subject.get("shape")
    mechanisms = set(subject.get("mechanisms", []))
    treatments = spec.get("treatments", [])
    if level != "L0":
        required.add("core_outcome")
    if any(
        treatment.get("profile") == "candidate/natural_routing"
        for treatment in treatments
        if isinstance(treatment, dict)
    ):
        required.add("natural_routing")
    if shape == "skill_catalog" or "catalog_routed" in mechanisms:
        required.add("catalog_routing")
    if shape in {"ordered_pipeline", "handoff_graph"}:
        required.update({"declared_composition", "multi_turn_state"})
    if shape == "handoff_graph" or subject.get("principal_mode") == "multiple":
        required.add("multi_principal_coordination")
    if "stateful" in mechanisms:
        required.add("multi_turn_state")
    if "tool_api_mcp" in mechanisms:
        required.add("tool_faults")
    if "host_adapter" in mechanisms:
        required.add("host_conformance")
    if "security_sensitive" in mechanisms:
        required.add("dynamic_security")
    if level == "L4":
        required.add("longitudinal")
    return required


def _validate_applicability(
    spec: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    decisions = spec.get("applicability", [])
    names = [
        item.get("module") for item in decisions if isinstance(item, dict)
    ]
    if len(names) != len(set(names)):
        _add_contract_error(
            errors, "applicability.duplicate", "/applicability",
            "each module must be declared exactly once",
        )
    if set(names) != V5_MODULES:
        _add_contract_error(
            errors, "applicability.registry", "/applicability",
            "applicability must cover the exact module registry",
        )
        return
    required = required_v5_modules(spec)
    for index, decision in enumerate(decisions):
        module = decision["module"]
        expected = "required" if module in required else "not_applicable"
        if decision.get("status") != expected:
            _add_contract_error(
                errors,
                "applicability.shape_mismatch",
                f"/applicability/{index}/status",
                f"{module} must be {expected} for the declared level/subject",
            )


def derive_entry_disposition(
    required_capabilities: set[str],
    host: dict[str, Any],
) -> tuple[str, str]:
    probes = {
        item.get("capability"): item.get("probe", {}).get("status")
        for item in host.get("capabilities", [])
        if isinstance(item, dict)
    }
    statuses = [probes.get(capability) for capability in required_capabilities]
    if any(status is None for status in statuses):
        raise ValueError("required capability probe is missing")
    if any(status == "unknown" for status in statuses):
        return "not_evaluable", "not_evaluable"
    if any(status == "unsupported" for status in statuses):
        return "unsupported", "unsupported"
    if all(status == "pass" for status in statuses):
        return "execute", "feasible"
    raise ValueError("required capability probe has an invalid status")


def _validate_coordination(
    coordination: dict[str, Any],
    expected_slots: list[str],
    *,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    slots = coordination.get("principal_slots", [])
    slot_ids = [
        slot.get("slot_id") for slot in slots if isinstance(slot, dict)
    ]
    slot_set = set(slot_ids)
    if len(slot_ids) != len(slot_set):
        _add_contract_error(
            errors, "coordination.duplicate_slot",
            path + "/principal_slots",
            "principal slot IDs must be unique",
        )
    if set(expected_slots) != slot_set:
        _add_contract_error(
            errors, "coordination.slot_join",
            path + "/principal_slots",
            "coordination slots must equal execution_context.expected_principal_slots",
        )
    if coordination.get("task_graph_owner") not in slot_set:
        _add_contract_error(
            errors, "coordination.task_graph_owner",
            path + "/task_graph_owner",
            "task_graph_owner must name a declared principal slot",
        )
    parents: dict[str, str | None] = {}
    for index, slot in enumerate(slots):
        slot_id = slot.get("slot_id")
        parent = slot.get("parent_slot_id")
        parents[slot_id] = parent
        if parent is not None and parent not in slot_set:
            _add_contract_error(
                errors, "coordination.parent_join",
                f"{path}/principal_slots/{index}/parent_slot_id",
                "parent_slot_id must name a declared slot",
            )
    for slot_id in slot_ids:
        seen: set[str] = set()
        current: str | None = slot_id
        while current is not None and current in parents:
            if current in seen:
                _add_contract_error(
                    errors, "coordination.parent_cycle",
                    path + "/principal_slots",
                    "principal parent graph contains a cycle",
                )
                break
            seen.add(current)
            current = parents[current]

    edges = coordination.get("dependency_edges", [])
    edge_pairs: list[tuple[Any, Any]] = []
    adjacency: dict[str, set[str]] = {slot_id: set() for slot_id in slot_set}
    for index, edge in enumerate(edges):
        pair = (edge.get("from"), edge.get("to"))
        edge_pairs.append(pair)
        if (
            pair[0] not in slot_set
            or pair[1] not in slot_set
            or pair[0] == pair[1]
        ):
            _add_contract_error(
                errors, "coordination.dependency_join",
                f"{path}/dependency_edges/{index}",
                "dependency edge endpoints must be distinct declared slots",
            )
        elif pair[0] in adjacency:
            adjacency[pair[0]].add(pair[1])
    if len(edge_pairs) != len(set(edge_pairs)):
        _add_contract_error(
            errors, "coordination.duplicate_dependency",
            path + "/dependency_edges",
            "dependency edges must be unique",
        )
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return False
        if node in visited:
            return True
        visiting.add(node)
        if not all(visit(child) for child in adjacency[node]):
            return False
        visiting.remove(node)
        visited.add(node)
        return True

    if not all(visit(slot_id) for slot_id in slot_set if slot_id not in visited):
        _add_contract_error(
            errors, "coordination.dependency_cycle",
            path + "/dependency_edges",
            "dependency graph must be acyclic",
        )
    if (
        coordination.get("topology") == "single"
        or len(slot_set) < 2
        or coordination.get("max_in_flight", 0)
        > coordination.get("max_width", 0)
    ):
        _add_contract_error(
            errors, "coordination.bounds", path,
            "multi-principal coordination needs at least two slots, non-single topology, and max_in_flight <= max_width",
        )


def _validate_routing_contract(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    *,
    path: str,
    errors: list[dict[str, str]],
) -> None:
    modules = required_v5_modules(spec)
    required = bool(
        modules & {"natural_routing", "catalog_routing"}
        or spec.get("subject", {}).get("shape") == "ordered_pipeline"
    )
    contract = scenario.get("routing_contract")
    if contract is None:
        if required:
            _add_contract_error(
                errors, "routing.required", path + "/routing_contract",
                "routing/catalog or ordered composition requires exact expectations",
            )
        return
    if not required:
        _add_contract_error(
            errors, "routing.forbidden", path + "/routing_contract",
            "inactive routing/composition modules cannot declare runtime expectations",
        )
        return
    if contract.get("target_skill_id") != spec.get("subject", {}).get(
        "skill_id",
    ):
        _add_contract_error(
            errors, "routing.target_join",
            path + "/routing_contract/target_skill_id",
            "routing target must equal the evaluated subject skill",
        )
    mode = contract.get("composition_mode")
    participants = contract.get("participants", [])
    if (
        (mode == "none" and participants)
        or (mode == "unordered_pair" and len(participants) != 2)
        or (mode == "ordered_sequence" and len(participants) < 2)
    ):
        _add_contract_error(
            errors, "composition.participants",
            path + "/routing_contract/participants",
            "composition participants do not match the declared minimal shape",
        )
    expected_keys = {
        (profile, turn["turn_id"])
        for profile in scenario.get("applicable_treatment_profiles", [])
        for turn in scenario.get("turns", [])
    }
    expectations = contract.get("expectations", [])
    actual_keys = [
        (item.get("treatment_profile"), item.get("turn_id"))
        for item in expectations
        if isinstance(item, dict)
    ]
    if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != expected_keys:
        _add_contract_error(
            errors, "routing.expectation_matrix",
            path + "/routing_contract/expectations",
            "routing expectations must cover each treatment profile and turn once",
        )
    for index, expectation in enumerate(expectations):
        composition = expectation.get("composition", [])
        candidate = str(expectation.get("treatment_profile", "")).startswith(
            "candidate/",
        )
        declared = (
            set(composition) == set(participants)
            if mode == "unordered_pair"
            else composition == participants
        )
        valid = (
            not composition
            if mode == "none"
            else declared
            if candidate
            else not composition or declared
        )
        if not valid:
            _add_contract_error(
                errors, "composition.expectation",
                f"{path}/routing_contract/expectations/{index}/composition",
                "composition evidence differs from the declared participants/order",
            )
    required_evidence = set(contract.get("required_evidence", []))
    minimum = {
        "discovery", "selection", "load", "application", "order", "outcome",
    }
    if mode != "none":
        minimum.add("composition")
    if not minimum <= required_evidence:
        _add_contract_error(
            errors, "routing.evidence_contract",
            path + "/routing_contract/required_evidence",
            f"routing evidence is missing required stages: {sorted(minimum - required_evidence)}",
        )


def _validate_scenarios(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    case_ids = [
        scenario.get("case_id")
        for scenario in scenarios
        if isinstance(scenario, dict)
    ]
    if len(case_ids) != len(set(case_ids)):
        _add_contract_error(
            errors, "scenario.duplicate_id", "/scenarios",
            "case_id values must be unique",
        )
    holdout = spec.get("suite", {}).get("holdout")
    revealed_holdout = (
        spec.get("level") in {"L3", "L4"}
        and isinstance(holdout, dict)
        and holdout.get("exposure_status") == "exposed"
        and spec.get("suite", {}).get("scenarios")
        != spec.get("suite", {}).get("public_scenarios")
    )
    public_heldout = [
        case_id
        for case_id, scenario in zip(case_ids, scenarios)
        if scenario.get("split") == "heldout"
    ]
    if public_heldout and not revealed_holdout:
        _add_contract_error(
            errors, "holdout.public_exposure", "/scenarios",
            f"public scenario corpus contains heldout IDs: {public_heldout}",
        )

    graders = {
        grader.get("grader_id"): grader
        for grader in spec.get("graders", [])
        if isinstance(grader, dict)
    }
    treatment_profiles = {
        treatment.get("profile")
        for treatment in spec.get("treatments", [])
        if isinstance(treatment, dict)
    }
    coordination_required = (
        "multi_principal_coordination" in required_v5_modules(spec)
    )
    multi_turn_required = "multi_turn_state" in required_v5_modules(spec)
    for index, scenario in enumerate(scenarios):
        prefix = f"/scenarios/{index}"
        if multi_turn_required and len(scenario.get("turns", [])) < 2:
            _add_contract_error(
                errors,
                "state.multi_turn_required",
                prefix + "/turns",
                "multi_turn_state requires at least two ordered turns",
            )
        profiles = set(scenario.get("applicable_treatment_profiles", []))
        if not profiles or not profiles <= treatment_profiles:
            _add_contract_error(
                errors, "scenario.treatment_profile", prefix + "/applicable_treatment_profiles",
                "scenario profiles must be a non-empty subset of declared treatment profiles",
            )
        if coordination_required and "coordination" not in scenario:
            _add_contract_error(
                errors, "coordination.required", prefix + "/coordination",
                "multi-principal scenarios require a coordination contract",
            )
        if not coordination_required and "coordination" in scenario:
            _add_contract_error(
                errors, "coordination.forbidden", prefix + "/coordination",
                "single-principal scenarios must not declare coordination",
            )
        if coordination_required and isinstance(
            scenario.get("coordination"), dict,
        ):
            _validate_coordination(
                scenario["coordination"],
                scenario.get("execution_context", {}).get(
                    "expected_principal_slots", [],
                ),
                path=prefix + "/coordination",
                errors=errors,
            )

        turns = scenario.get("turns", [])
        turn_ids = [
            turn.get("turn_id") for turn in turns if isinstance(turn, dict)
        ]
        if len(turn_ids) != len(set(turn_ids)):
            _add_contract_error(
                errors, "turn.duplicate_id", prefix + "/turns",
                "turn_id values must be unique within a scenario",
            )
        if not any(
            turn.get("input", {}).get("kind") == "user_message"
            for turn in turns
            if isinstance(turn, dict)
        ):
            _add_contract_error(
                errors, "turn.user_required", prefix + "/turns",
                "at least one user_message turn is required",
            )
        _validate_routing_contract(
            spec, scenario, path=prefix, errors=errors,
        )

        faults = scenario.get("fault_script", [])
        fault_ids = {
            fault.get("fault_id") for fault in faults if isinstance(fault, dict)
        }
        if len(fault_ids) != len(faults):
            _add_contract_error(
                errors, "fault.duplicate_id", prefix + "/fault_script",
                "fault_id values must be unique",
            )
        for turn_index, turn in enumerate(turns):
            unknown = set(turn.get("activate_faults", [])) - fault_ids
            if unknown:
                _add_contract_error(
                    errors, "fault.unknown_activation",
                    f"{prefix}/turns/{turn_index}/activate_faults",
                    f"unknown fault IDs: {sorted(unknown)}",
                )

        requirements = scenario.get("requirements", [])
        requirement_ids = [
            item.get("requirement_id")
            for item in requirements
            if isinstance(item, dict)
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            _add_contract_error(
                errors, "requirement.duplicate_id", prefix + "/requirements",
                "requirement_id values must be unique",
            )
        required_dimensions = {
            item.get("dimension")
            for item in requirements
            if isinstance(item, dict) and item.get("required") is True
        }
        if not {"outcome", "safety"} <= required_dimensions:
            _add_contract_error(
                errors, "requirement.mandatory_dimensions",
                prefix + "/requirements",
                "required outcome and safety requirements are mandatory",
            )
        for req_index, requirement in enumerate(requirements):
            grader = graders.get(requirement.get("grader_id"))
            checks = {
                check.get("check_id")
                for check in grader.get("checks", [])
            } if isinstance(grader, dict) else set()
            if grader is None or requirement.get("check_id") not in checks:
                _add_contract_error(
                    errors, "requirement.grader_join",
                    f"{prefix}/requirements/{req_index}",
                    "requirement must join one declared grader/check",
                )
            elif requirement.get("owner") != grader.get("type"):
                _add_contract_error(
                    errors, "requirement.owner_mismatch",
                    f"{prefix}/requirements/{req_index}/owner",
                    "requirement owner must equal the joined grader type",
                )

        observation_ids = {
            item.get("observation_id")
            for item in scenario.get("observation_contracts", [])
            if isinstance(item, dict)
        }
        if len(observation_ids) != len(scenario.get("observation_contracts", [])):
            _add_contract_error(
                errors, "observation.duplicate_id",
                prefix + "/observation_contracts",
                "observation_id values must be unique",
            )
        for obs_index, observation in enumerate(
            scenario.get("observation_contracts", []),
        ):
            obs_prefix = f"{prefix}/observation_contracts/{obs_index}"
            unknown = (
                set(observation.get("consumer_requirement_ids", []))
                - set(requirement_ids)
            )
            if unknown:
                _add_contract_error(
                    errors, "observation.requirement_join",
                    obs_prefix,
                    f"unknown consumer requirement IDs: {sorted(unknown)}",
                )
            if observation.get("locator", {}).get("artifact") != observation.get(
                "artifact",
            ):
                _add_contract_error(
                    errors, "observation.locator_binding",
                    obs_prefix + "/locator/artifact",
                    "observation locator must name the declared artifact",
                )
            has_hash = observation.get("expected_hash") is not None
            has_predicate = observation.get("predicate") is not None
            if has_hash == has_predicate:
                _add_contract_error(
                    errors, "observation.bytes_contract", obs_prefix,
                    "observation requires exactly one expected_hash or predicate",
                )
            seq_values = (
                observation.get("valid_from_seq"),
                observation.get("valid_until_seq"),
            )
            utc_values = (
                observation.get("valid_from_utc"),
                observation.get("valid_until_utc"),
            )
            has_seq = all(value is not None for value in seq_values)
            has_utc = all(value is not None for value in utc_values)
            partial_window = (
                any(value is not None for value in seq_values) != has_seq
                or any(value is not None for value in utc_values) != has_utc
            )
            if partial_window or has_seq == has_utc:
                _add_contract_error(
                    errors, "observation.temporal_contract", obs_prefix,
                    "observation requires exactly one complete seq or UTC window",
                )
            elif has_seq and seq_values[0] > seq_values[1]:
                _add_contract_error(
                    errors, "observation.temporal_contract", obs_prefix,
                    "observation seq window is reversed",
                )
            elif has_utc:
                try:
                    starts = _parse_rfc3339_seconds(
                        utc_values[0], obs_prefix + "/valid_from_utc",
                    )
                    ends = _parse_rfc3339_seconds(
                        utc_values[1], obs_prefix + "/valid_until_utc",
                    )
                except ValueError as exc:
                    _add_contract_error(
                        errors, "observation.temporal_contract",
                        obs_prefix, str(exc),
                    )
                else:
                    if starts > ends:
                        _add_contract_error(
                            errors, "observation.temporal_contract",
                            obs_prefix, "observation UTC window is reversed",
                        )
        grounded_ids = {
            requirement["requirement_id"]
            for requirement in requirements
            if requirement.get("dimension") == "grounding"
        }
        observed_ids = {
            requirement_id
            for observation in scenario.get("observation_contracts", [])
            for requirement_id in observation.get(
                "consumer_requirement_ids", []
            )
        }
        if not grounded_ids <= observed_ids:
            _add_contract_error(
                errors, "grounding.observation_required",
                prefix + "/observation_contracts",
                "every grounding requirement needs an observation contract",
            )

        state_model = scenario.get("state_model", {})
        if state_model.get("scope") == "none":
            if any(
                requirement.get("transition_id") is not None
                for requirement in requirements
            ):
                _add_contract_error(
                    errors, "state.transition_forbidden", prefix + "/requirements",
                    "scope=none forbids transition-bound requirements",
                )
        else:
            allowed = set(state_model.get("allowed_transition_ids", []))
            for req_index, requirement in enumerate(requirements):
                transition = requirement.get("transition_id")
                if transition is not None and transition not in allowed:
                    _add_contract_error(
                        errors, "state.transition_join",
                        f"{prefix}/requirements/{req_index}/transition_id",
                        "transition_id is outside state_model.allowed_transition_ids",
                    )


def _validate_treatments(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    treatments = spec.get("treatments", [])
    treatment_ids = [
        item.get("treatment_id") for item in treatments
        if isinstance(item, dict)
    ]
    if len(treatment_ids) != len(set(treatment_ids)):
        _add_contract_error(
            errors, "treatment.duplicate_id", "/treatments",
            "treatment_id values must be unique",
        )
    profiles = [
        item.get("profile") for item in treatments if isinstance(item, dict)
    ]
    if len(profiles) != len(set(profiles)):
        _add_contract_error(
            errors, "treatment.duplicate_profile", "/treatments",
            "treatment profiles must be unique",
        )
    level = spec.get("level")
    if level in {"L2", "L3", "L4"}:
        if profiles.count("baseline/skill_disabled") != 1:
            _add_contract_error(
                errors, "treatment.baseline_required", "/treatments",
                "L2+ requires exactly one baseline/skill_disabled treatment",
            )
        current = [
            item for item in treatments
            if isinstance(item, dict)
            and item.get("profile") in {
                "candidate/natural_routing", "candidate/force_loaded",
            }
            and item.get("causal_role") == "candidate"
        ]
        if len(current) != 1:
            _add_contract_error(
                errors, "treatment.primary_candidate", "/treatments",
                "L2+ requires exactly one current primary candidate",
            )
    if level == "L4":
        prior_treatments = [
            item for item in treatments
            if item.get("causal_role") == "prior"
            and item.get("profile") in {
                "prior/natural_routing", "prior/force_loaded",
            }
        ]
        if len(prior_treatments) != 1:
            _add_contract_error(
                errors, "treatment.prior_required", "/treatments",
                "L4 requires exactly one immutable prior treatment",
            )

    scenario_ids = {item.get("case_id") for item in scenarios}
    scenario_tags = {
        tag for scenario in scenarios for tag in scenario.get("tags", [])
    }
    for index, treatment in enumerate(treatments):
        prefix = f"/treatments/{index}"
        if not (
            set(treatment.get("scenario_ids", [])) & scenario_ids
            or set(treatment.get("scenario_tags", [])) & scenario_tags
        ):
            _add_contract_error(
                errors, "treatment.coverage", prefix,
                "treatment must cover at least one supplied scenario",
            )
        profile = treatment.get("profile")
        role = treatment.get("causal_role")
        expected_role = profile.split("/", 1)[0] if isinstance(profile, str) else None
        if expected_role in {"baseline", "candidate", "prior", "comparator"}:
            if role != expected_role:
                _add_contract_error(
                    errors, "treatment.role_mismatch", prefix + "/causal_role",
                    f"{profile} requires causal_role={expected_role}",
                )
        if profile == "candidate/natural_routing":
            if "natural_routing" not in required_v5_modules(spec):
                _add_contract_error(
                    errors, "treatment.routing_module", prefix + "/profile",
                    "natural-routing treatment requires natural_routing module",
                )

    baseline = next(
        (
            item for item in treatments
            if item.get("profile") == "baseline/skill_disabled"
        ),
        None,
    )
    candidate = next(
        (
            item for item in treatments
            if item.get("causal_role") == "candidate"
            and item.get("profile") in {
                "candidate/natural_routing", "candidate/force_loaded",
            }
        ),
        None,
    )
    if baseline and candidate:
        for field in (
            "prompt_variant_group_id",
            "model_identity",
            "harness_identity",
            "host_identity",
            "base_catalog_hash",
            "tool_policy_hash",
            "permission_policy_hash",
            "network_policy_hash",
            "context_policy_hash",
        ):
            if baseline.get(field) != candidate.get(field):
                _add_contract_error(
                    errors, "treatment.execution_identity",
                    f"/treatments/{field}",
                    f"causal baseline/candidate must share {field}",
                )
        baseline_axes = set(baseline.get("intervention_axes", []))
        candidate_axes = set(candidate.get("intervention_axes", []))
        if baseline_axes != candidate_axes or len(candidate_axes) != 1:
            _add_contract_error(
                errors, "treatment.intervention_axis", "/treatments",
                "causal baseline/candidate must bind the same single intervention axis",
            )

    if level == "L4" and candidate:
        priors = [
            item for item in treatments
            if item.get("causal_role") == "prior"
            and item.get("profile") in {
                "prior/natural_routing", "prior/force_loaded",
            }
        ]
        if len(priors) == 1:
            prior = priors[0]
            candidate_mode = candidate["profile"].split("/", 1)[1]
            prior_mode = prior["profile"].split("/", 1)[1]
            if prior_mode != candidate_mode:
                _add_contract_error(
                    errors,
                    "treatment.prior_mode",
                    "/treatments",
                    "L4 prior and current candidate must use the same mode",
                )
            comparable_fields = (
                "prompt_variant_group_id",
                "model_identity",
                "harness_identity",
                "host_identity",
                "base_catalog_hash",
                "tool_policy_hash",
                "permission_policy_hash",
                "network_policy_hash",
                "context_policy_hash",
            )
            changed = [
                field for field in comparable_fields
                if prior.get(field) != candidate.get(field)
            ]
            if changed:
                _add_contract_error(
                    errors,
                    "treatment.prior_identity",
                    "/treatments",
                    f"L4 prior/current execution identity differs: {changed}",
                )
            if (
                set(prior.get("intervention_axes", []))
                != set(candidate.get("intervention_axes", []))
                or len(set(candidate.get("intervention_axes", []))) != 1
            ):
                _add_contract_error(
                    errors,
                    "treatment.prior_axis",
                    "/treatments",
                    "L4 prior/current must bind the same single intervention axis",
                )
            if prior.get("implementation_hash") == candidate.get(
                "implementation_hash",
            ):
                _add_contract_error(
                    errors,
                    "treatment.prior_immutable",
                    "/treatments",
                    "L4 prior/current implementation hashes must identify different cycles",
                )
            estimands = spec.get("analysis", {}).get("estimands", [])
            if not any(
                item.get("candidate_treatment_id")
                == candidate.get("treatment_id")
                and item.get("comparator_treatment_id")
                == prior.get("treatment_id")
                for item in estimands
            ):
                _add_contract_error(
                    errors,
                    "treatment.prior_estimand",
                    "/analysis/estimands",
                    "L4 requires a current-versus-prior estimand",
                )

    expected_hash = v5_treatment_contract_hash(treatments)
    actual_hash = spec.get("suite", {}).get("treatment_contract_hash")
    if actual_hash != expected_hash:
        _add_contract_error(
            errors, "treatment.contract_hash",
            "/suite/treatment_contract_hash",
            f"treatment contract hash must be {expected_hash}",
        )


def _validate_probe_artifact(
    probe: dict[str, Any],
    *,
    root: Path,
    path: str,
    ready: bool,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    artifact = probe.get("artifact", {})
    resolved = _check_bound_file(
        artifact,
        root=root,
        label="capability probe artifact",
        path=path + "/artifact",
        errors=errors,
        warnings=warnings,
        ready=ready,
        nonready_code="non_ready.fixture",
    )
    if resolved is None:
        return
    locator = probe.get("locator", {})
    if locator.get("artifact") != artifact.get("path"):
        _add_contract_error(
            errors, "probe.locator_binding", path + "/locator/artifact",
            "probe locator must name the bound probe artifact",
        )
        return
    if locator.get("kind") == "text_lines":
        try:
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            _add_contract_error(
                errors, "probe.locator_encoding", path + "/locator",
                "text locator requires a UTF-8 probe artifact",
            )
            return
        start = locator.get("start_line")
        end = locator.get("end_line")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
            or end > len(lines)
            or not any(lines[start - 1 : end])
        ):
            _add_contract_error(
                errors, "probe.locator_bounds", path + "/locator",
                "text locator is empty or out of bounds",
            )


def _validate_host_manifest(
    spec: dict[str, Any],
    host: dict[str, Any],
    *,
    host_path: Path,
    ready: bool,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, str]:
    if not verify_self_hash(host, "manifest_hash"):
        _add_contract_error(
            errors, "self_hash.mismatch", "/host/manifest_hash",
            "manifest_hash does not match canonical host-manifest bytes",
        )
    capabilities = host.get("capabilities", [])
    names = [
        item.get("capability") for item in capabilities
        if isinstance(item, dict)
    ]
    if len(names) != len(set(names)):
        _add_contract_error(
            errors, "host.capability_duplicate", "/host/capabilities",
            "host capabilities must be unique",
        )
    records = {
        item.get("capability"): item
        for item in capabilities
        if isinstance(item, dict)
    }
    required = set(spec.get("host", {}).get("required_capabilities", []))
    module_capabilities = {
        capability
        for module in required_v5_modules(spec)
        for capability in V5_MODULE_CAPABILITIES.get(module, set())
    }
    missing_declarations = module_capabilities - required
    if missing_declarations:
        _add_contract_error(
            errors, "module.capability_missing",
            "/host/required_capabilities",
            f"required modules need capabilities: {sorted(missing_declarations)}",
        )
    required.update(module_capabilities)
    for treatment in spec.get("treatments", []):
        required.update(treatment.get("expected_capabilities", []))
    missing = required - set(records)
    if missing:
        _add_contract_error(
            errors, "host.probe_missing", "/host/capabilities",
            f"required capability probes are missing: {sorted(missing)}",
        )
    for index, record in enumerate(capabilities):
        probe = record.get("probe", {})
        if record.get("declared") is False and probe.get("status") == "pass":
            _add_contract_error(
                errors, "host.declaration_probe_conflict",
                f"/host/capabilities/{index}",
                "declared=false cannot have a passing capability probe",
            )
        _validate_probe_artifact(
            probe,
            root=host_path.parent,
            path=f"/host/capabilities/{index}/probe",
            ready=ready,
            errors=errors,
            warnings=warnings,
        )
    reset_probe = host.get("reset", {}).get("probe")
    if isinstance(reset_probe, dict):
        _validate_probe_artifact(
            reset_probe,
            root=host_path.parent,
            path="/host/reset/probe",
            ready=ready,
            errors=errors,
            warnings=warnings,
        )
    return {
        name: record.get("probe", {}).get("status")
        for name, record in records.items()
    }


def _parse_rfc3339_seconds(value: Any, path: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a UTC RFC 3339 seconds string")
    try:
        parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError(
            f"{path} must match YYYY-MM-DDTHH:MM:SSZ",
        ) from None
    return parsed.replace(tzinfo=dt.timezone.utc)


def _validate_calibration_binding(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    host: dict[str, Any],
    *,
    spec_path: Path,
    ready: bool,
    registry: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any] | None:
    suite = spec.get("suite", {})
    binding = suite.get("calibration")
    model_graders = [
        grader for grader in spec.get("graders", [])
        if grader.get("type") == "model"
    ]
    if not model_graders:
        if binding is not None:
            _add_contract_error(
                errors, "calibration.forbidden", "/suite/calibration",
                "deterministic-grader-only specs must not bind calibration",
            )
        return None
    if binding is None:
        if ready:
            _add_contract_error(
                errors, "calibration.required", "/suite/calibration",
                "selected model graders require calibration",
            )
        else:
            _add_readiness_warning(
                warnings, "non_ready.calibration", "/suite/calibration",
                "model-grader calibration is not materialized",
            )
        return None
    path = _check_bound_file(
        binding,
        root=spec_path.parent,
        label="grader calibration",
        path="/suite/calibration",
        errors=errors,
        warnings=warnings,
        ready=ready,
        nonready_code="non_ready.calibration",
    )
    if path is None:
        return None
    calibration = load_json(path)
    _validate_self_hashed_artifact(
        calibration,
        schema_name="grader-calibration-v1.schema.json",
        hash_field="calibration_hash",
        path="/calibration",
        registry=registry,
        errors=errors,
    )
    if not isinstance(calibration, dict):
        return None
    _validate_calibration_raw_normalization(
        spec,
        calibration,
        artifact_path=path,
        errors=errors,
        warnings=warnings,
    )
    if calibration.get("evaluation_id") != spec.get("evaluation_id"):
        _add_contract_error(
            errors, "calibration.evaluation_identity",
            "/calibration/evaluation_id",
            "calibration evaluation_id does not match the spec",
        )
    grader_ids = {grader.get("grader_id") for grader in model_graders}
    if calibration.get("grader", {}).get("grader_id") not in grader_ids:
        _add_contract_error(
            errors, "calibration.grader_scope", "/calibration/grader/grader_id",
            "calibration does not cover a selected model grader",
        )
    as_of = _parse_rfc3339_seconds(
        spec.get("execution", {}).get("as_of"), "/execution/as_of",
    )
    created = _parse_rfc3339_seconds(
        calibration.get("created"), "/calibration/created",
    )
    expires = _parse_rfc3339_seconds(
        calibration.get("expires"), "/calibration/expires",
    )
    if not created <= as_of < expires:
        _add_contract_error(
            errors, "calibration.expired", "/suite/calibration",
            "calibration must satisfy created <= execution.as_of < expires",
        )
    for index, trigger in enumerate(calibration.get("drift_triggers", [])):
        if (
            trigger.get("status") != "unchanged"
            or trigger.get("expected") != trigger.get("observed")
        ):
            _add_contract_error(
                errors, "calibration.drift",
                f"/calibration/drift_triggers/{index}",
                "calibration drift trigger changed",
            )

    scope = calibration.get("scope", {})
    expected_scope = {
        "tasks": {
            item.get("execution_context", {}).get("domain")
            for item in scenarios
        },
        "languages": {
            item.get("execution_context", {}).get("language")
            for item in scenarios
        },
        "risks": {
            item.get("risk")
            for item in scenarios
            if any(
                requirement.get("owner") == "model"
                for requirement in item.get("requirements", [])
            )
        } or {spec.get("risk_tier")},
        "hosts": {host.get("identity", {}).get("host_id")},
        "models": {grader.get("model") for grader in model_graders},
    }
    for field, expected in expected_scope.items():
        if not expected <= set(scope.get(field, [])):
            _add_contract_error(
                errors, "calibration.scope",
                f"/calibration/scope/{field}",
                f"calibration scope does not cover {sorted(expected)}",
            )
    requires_independent = any(
        gate.get("required") is True
        and gate.get("kind") == "calibration"
        and gate.get("metric") == "independent_judge"
        for gate in spec.get("hard_gates", [])
    )
    if (
        requires_independent
        and calibration.get("independence", {}).get("status") != "independent"
    ):
        _add_contract_error(
            errors, "calibration.independence",
            "/calibration/independence/status",
            "the independent-judge gate requires derived status independent",
        )
    return calibration


def _validate_quality_binding(
    spec: dict[str, Any],
    *,
    spec_path: Path,
    ready: bool,
    registry: dict[str, dict[str, Any]],
    calibration: dict[str, Any] | None,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any] | None:
    suite = spec.get("suite", {})
    binding = suite.get("quality")
    if binding is None:
        return None
    path = _check_bound_file(
        binding,
        root=spec_path.parent,
        label="suite-quality artifact",
        path="/suite/quality",
        errors=errors,
        warnings=warnings,
        ready=ready,
        nonready_code="non_ready.quality",
    )
    if path is None:
        return None
    quality = load_json(path)
    _validate_self_hashed_artifact(
        quality,
        schema_name="suite-quality-v1.schema.json",
        hash_field="suite_quality_hash",
        path="/suite_quality",
        registry=registry,
        errors=errors,
    )
    if not isinstance(quality, dict):
        return None
    _validate_suite_quality_raw_normalization(
        spec,
        quality,
        spec_path=spec_path,
        artifact_path=path,
        errors=errors,
        warnings=warnings,
    )
    expected_contract_hash = quality_contract_hash(spec)
    identities = {
        "evaluation_id": spec.get("evaluation_id"),
        "quality_contract_hash": expected_contract_hash,
        "scenario_hash": suite.get("scenarios", {}).get("sha256"),
        "holdout_hash": (
            suite.get("holdout", {}).get("payload", {}).get("sha256")
            if isinstance(suite.get("holdout"), dict) else None
        ),
        "fixture_set_hash": suite.get("fixture_set_hash"),
        "grader_set_hash": suite.get("grader_set_hash"),
        "treatment_contract_hash": suite.get("treatment_contract_hash"),
        "calibration_hash": (
            suite.get("calibration", {}).get("sha256")
            if calibration is not None else None
        ),
    }
    for field, expected in identities.items():
        if quality.get(field) != expected:
            _add_contract_error(
                errors, "quality.binding", f"/suite_quality/{field}",
                f"suite-quality {field} does not match the spec projection",
            )
    failed_gates = [
        gate for gate, status in quality.get("gates", {}).items()
        if status != "pass"
    ]
    module_coverage = quality.get("coverage", {}).get("modules", {})
    uncovered_modules = [
        module
        for module in sorted(required_v5_modules(spec))
        if module not in module_coverage
        or module_coverage[module].get("positive", 0) < 1
        or module_coverage[module].get("boundary_or_failure", 0) < 1
    ]
    if uncovered_modules:
        _add_contract_error(
            errors, "quality.module_coverage",
            "/suite_quality/coverage/modules",
            f"required modules lack positive/boundary coverage: {uncovered_modules}",
        )
    if ready and failed_gates:
        _add_contract_error(
            errors, "quality.gate_failed", "/suite_quality/gates",
            f"scored-ready quality gates are not pass: {sorted(failed_gates)}",
        )
    return quality


def _validate_authority_closure(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    host: dict[str, Any],
    errors: list[dict[str, str]],
) -> None:
    required_capabilities = set(
        spec.get("host", {}).get("required_capabilities", []),
    )
    for treatment in spec.get("treatments", []):
        required_capabilities.update(
            treatment.get("expected_capabilities", []),
        )
    try:
        disposition, _ = derive_entry_disposition(required_capabilities, host)
    except ValueError as exc:
        _add_contract_error(
            errors, "host.probe_invalid", "/host/capabilities", str(exc),
        )
        return
    if disposition != "execute":
        return
    authority = spec.get("authority", {})
    capabilities = set(authority.get("runner_capabilities", []))
    if "local_execution" not in capabilities:
        _add_contract_error(
            errors, "authority.missing_execute",
            "/authority/runner_capabilities",
            "execute entries require local_execution authority",
        )
    surfaces = {
        surface
        for scenario in scenarios
        for surface in scenario.get("execution_context", {}).get(
            "expected_policy_surfaces", []
        )
    }
    for surface in ("install", "publish", "deploy", "external_writes"):
        if surface in surfaces and authority.get(surface) is not True:
            _add_contract_error(
                errors, "authority.missing_execute",
                f"/authority/{surface}",
                f"execute entries requiring {surface} need explicit authority",
            )


def _validate_level_requirements(
    spec: dict[str, Any],
    *,
    spec_path: Path,
    ready: bool,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    level = spec.get("level")
    risk = spec.get("risk_tier")
    authority = spec.get("authority", {})
    manual = authority.get("manual_review", {})
    if level in {"L3", "L4"} or risk == "high":
        if (
            manual.get("required") is not True
            or not nonempty_string(manual.get("role"))
            or not isinstance(manual.get("decision_contract_hash"), str)
        ):
            _add_contract_error(
                errors,
                "authority.manual_required",
                "/authority/manual_review",
                "L3/L4 and high-risk contracts require hash-bound manual authority",
            )
    if level not in {"L3", "L4"}:
        return

    required_gate_kinds = {
        gate.get("kind")
        for gate in spec.get("hard_gates", [])
        if gate.get("required") is True
    }
    missing_gates = {"safety", "host", "manual"} - required_gate_kinds
    if missing_gates:
        _add_contract_error(
            errors,
            "level.gates",
            "/hard_gates",
            f"{level} lacks required gate kinds: {sorted(missing_gates)}",
        )

    holdout = spec.get("suite", {}).get("holdout")
    if not isinstance(holdout, dict):
        _add_contract_error(
            errors,
            "holdout.required",
            "/suite/holdout",
            f"{level} requires a sequestered holdout binding",
        )
        return
    if holdout.get("exposure_status") not in {"sealed", "exposed"}:
        _add_contract_error(
            errors,
            "holdout.exposure",
            "/suite/holdout/exposure_status",
            "L3/L4 holdout exposure_status must be sealed or exposed",
        )
    if ready and holdout.get("exposure_status") != "exposed":
        _add_contract_error(
            errors,
            "holdout.not_revealed",
            "/suite/holdout/exposure_status",
            "compiler-ready L3/L4 requires an exposed execution partition",
        )
    manifest_path = _check_bound_file(
        holdout.get("manifest", {}),
        root=spec_path.parent,
        label="holdout manifest",
        path="/suite/holdout/manifest",
        errors=errors,
        warnings=warnings,
        ready=ready,
        nonready_code="non_ready.holdout",
    )
    payload_path = _check_bound_file(
        holdout.get("payload", {}),
        root=spec_path.parent,
        label="holdout payload",
        path="/suite/holdout/payload",
        errors=errors,
        warnings=warnings,
        ready=ready,
        nonready_code="non_ready.holdout",
    )
    if manifest_path is None or payload_path is None:
        return
    public_path = spec.get("suite", {}).get("public_scenarios", {}).get("path")
    try:
        _, resolved_public = resolve_evidence_path(
            spec_path.parent,
            public_path,
            "public scenario corpus",
            kind="file",
        )
    except (OSError, ValueError):
        resolved_public = None
    if payload_path == manifest_path or payload_path == resolved_public:
        _add_contract_error(
            errors,
            "holdout.separation",
            "/suite/holdout",
            "holdout manifest, payload, and public corpus must be distinct",
        )
    try:
        manifest = load_json(manifest_path)
    except (OSError, ValueError) as exc:
        _add_contract_error(
            errors,
            "holdout.manifest",
            "/suite/holdout/manifest",
            f"cannot read holdout manifest: {exc}",
        )
        return
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        _add_contract_error(
            errors,
            "holdout.manifest",
            "/suite/holdout/manifest",
            "holdout manifest must be a version-1 object",
        )
        return
    manifest_payload = manifest.get("payload_file")
    try:
        _, declared_payload = resolve_evidence_path(
            manifest_path.parent,
            manifest_payload,
            "holdout manifest payload",
            kind="file",
        )
    except (OSError, ValueError) as exc:
        _add_contract_error(
            errors,
            "holdout.manifest",
            "/suite/holdout/manifest",
            f"holdout manifest payload is invalid: {exc}",
        )
        return
    if (
        declared_payload != payload_path
        or manifest.get("payload_sha256") != file_sha256(payload_path)
        or manifest.get("custodian") != holdout.get("custodian")
        or manifest.get("exposure_status")
        != holdout.get("exposure_status")
    ):
        _add_contract_error(
            errors,
            "holdout.manifest_binding",
            "/suite/holdout",
            "holdout manifest identity, custody, exposure, or payload hash differs",
        )


def _validate_execution_scenario_partition(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    *,
    spec_path: Path,
    public_path: Path | None,
    errors: list[dict[str, str]],
) -> None:
    suite = spec["suite"]
    same_binding = suite["scenarios"] == suite["public_scenarios"]
    if spec["level"] not in {"L3", "L4"}:
        if not same_binding:
            _add_contract_error(
                errors,
                "binding.public_scenario_mismatch",
                "/suite/public_scenarios",
                "L1/L2 scenarios must equal the public scenario binding",
            )
        return
    holdout = suite.get("holdout")
    if not isinstance(holdout, dict):
        return
    if holdout.get("exposure_status") == "sealed":
        if not same_binding:
            _add_contract_error(
                errors,
                "holdout.sealed_execution",
                "/suite/scenarios",
                "sealed holdout cannot appear in the execution corpus",
            )
        return
    if holdout.get("exposure_status") != "exposed" or public_path is None:
        return
    if same_binding:
        _add_contract_error(
            errors,
            "holdout.exposed_execution",
            "/suite/scenarios",
            "exposed holdout requires a distinct execution corpus",
        )
        return
    try:
        _, payload_path = resolve_evidence_path(
            spec_path.parent,
            holdout["payload"]["path"],
            "holdout payload",
            kind="file",
        )
        public = load_jsonl(public_path)
        heldout = load_jsonl(payload_path)
    except (KeyError, OSError, ValueError) as exc:
        _add_contract_error(
            errors,
            "holdout.execution_partition",
            "/suite/scenarios",
            f"cannot read revealed scenario partition: {exc}",
        )
        return
    public_ids = {item.get("case_id") for item in public}
    heldout_ids = {item.get("case_id") for item in heldout}
    execution_rows = [
        {key: value for key, value in item.items() if key != "_line"}
        for item in scenarios
    ]
    partition_rows = [
        {key: value for key, value in item.items() if key != "_line"}
        for item in (*public, *heldout)
    ]
    if (
        any(item.get("split") == "heldout" for item in public)
        or any(item.get("split") != "heldout" for item in heldout)
        or public_ids & heldout_ids
        or execution_rows != partition_rows
    ):
        _add_contract_error(
            errors,
            "holdout.execution_partition",
            "/suite/scenarios",
            "execution corpus must be the disjoint ordered public+heldout union",
        )


def validate_v5_contract_semantics(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    host: dict[str, Any] | None,
    *,
    spec_path: Path,
    scenarios_path: Path | None,
    host_path: Path | None,
    registry: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    level = spec["level"]
    ready = spec["execution"]["ready"] is True
    _validate_applicability(spec, errors)
    if level == "L0":
        return errors, warnings
    if scenarios_path is None or host_path is None or host is None:
        raise ValueError("L1+ semantic validation requires scenarios and host")

    suite = spec["suite"]
    _check_bound_file(
        suite["scenarios"],
        root=spec_path.parent,
        label="scenarios",
        path="/suite/scenarios",
        errors=errors,
        warnings=warnings,
        ready=ready,
        expected_path=scenarios_path,
    )
    public_path = _check_bound_file(
        suite["public_scenarios"],
        root=spec_path.parent,
        label="public scenarios",
        path="/suite/public_scenarios",
        errors=errors,
        warnings=warnings,
        ready=ready,
    )
    _validate_execution_scenario_partition(
        spec,
        scenarios,
        spec_path=spec_path,
        public_path=public_path,
        errors=errors,
    )
    _check_bound_file(
        spec["host"]["manifest"],
        root=spec_path.parent,
        label="host manifest",
        path="/host/manifest",
        errors=errors,
        warnings=warnings,
        ready=ready,
        expected_path=host_path,
    )

    expected_hashes = {
        "fixture_set_hash": v5_fixture_set_hash(scenarios),
        "grader_set_hash": v5_grader_set_hash(spec["graders"]),
        "grader_schedule_hash": v5_grader_schedule_hash(spec, scenarios),
    }
    for field, expected in expected_hashes.items():
        if suite.get(field) != expected:
            _add_contract_error(
                errors, f"binding.{field}", f"/suite/{field}",
                f"{field} must be {expected}",
            )
    if "quality_contract_hash" in suite:
        expected_quality_hash = quality_contract_hash(spec)
        if suite["quality_contract_hash"] != expected_quality_hash:
            _add_contract_error(
                errors, "quality.contract_hash",
                "/suite/quality_contract_hash",
                f"quality_contract_hash must be {expected_quality_hash}",
            )

    _validate_scenarios(spec, scenarios, errors)
    _validate_treatments(spec, scenarios, errors)
    _validate_host_manifest(
        spec, host, host_path=host_path, ready=ready,
        errors=errors, warnings=warnings,
    )
    if "host_adapter" in set(spec["subject"].get("mechanisms", [])):
        claimed_hosts = set(spec["subject"].get("claimed_hosts", []))
        bound_host = host.get("identity", {}).get("host_id")
        if claimed_hosts != {bound_host}:
            _add_contract_error(
                errors, "host.claim_binding", "/subject/claimed_hosts",
                "each host-conformance plan must claim exactly its bound host",
            )

    for scenario_index, scenario in enumerate(scenarios):
        fixture = scenario.get("fixture", {})
        _check_bound_file(
            {"path": fixture.get("manifest"), "sha256": fixture.get("sha256")},
            root=scenarios_path.parent,
            label=f"scenario {scenario.get('case_id')} fixture manifest",
            path=f"/scenarios/{scenario_index}/fixture",
            errors=errors,
            warnings=warnings,
            ready=ready,
            nonready_code="non_ready.fixture",
        )
    for grader_index, grader in enumerate(spec["graders"]):
        if grader.get("type") != "deterministic":
            continue
        verifier = grader["verifier"]
        placeholder = any(
            "replace" in argument.lower()
            for argument in verifier.get("argv", [])
            if isinstance(argument, str)
        )
        if placeholder:
            if ready:
                _add_contract_error(
                    errors, "readiness.verifier_placeholder",
                    f"/graders/{grader_index}/verifier/argv",
                    "execution-ready verifier argv contains a placeholder",
                )
            else:
                _add_readiness_warning(
                    warnings, "non_ready.verifier",
                    f"/graders/{grader_index}/verifier",
                    "deterministic verifier invocation is still a template",
                )
        _check_bound_file(
            {"path": verifier["path"], "sha256": verifier["sha256"]},
            root=spec_path.parent,
            label=f"grader {grader.get('grader_id')} verifier",
            path=f"/graders/{grader_index}/verifier",
            errors=errors,
            warnings=warnings,
            ready=ready,
            nonready_code="non_ready.verifier",
        )

    calibration = _validate_calibration_binding(
        spec, scenarios, host, spec_path=spec_path, ready=ready,
        registry=registry, errors=errors, warnings=warnings,
    )
    _validate_quality_binding(
        spec, spec_path=spec_path, ready=ready, registry=registry,
        calibration=calibration, errors=errors, warnings=warnings,
    )
    _validate_authority_closure(spec, scenarios, host, errors)
    _validate_level_requirements(
        spec,
        spec_path=spec_path,
        ready=ready,
        errors=errors,
        warnings=warnings,
    )
    if not ready:
        _add_readiness_warning(
            warnings, "non_ready.execution", "/execution/ready",
            "execution.ready is false; contract is not compiler-eligible",
        )
    return errors, warnings


def treatment_contract_hash(variants: list[dict[str, Any]]) -> str:
    return canonical_sha256([
        {
            field: variant[field]
            for field in (
                "id", "role", "mode", "package_hash", "catalog_hash",
                "treatment_hash",
            )
        }
        for variant in sorted(variants, key=lambda item: item["id"])
    ])


def validate_transfer_contract(contract: Any) -> list[str]:
    if not isinstance(contract, dict):
        return ["transfer contract must be an object"]
    allowed = contract.get("allowed_paths")
    required = contract.get("required_paths")
    protected = contract.get("protected_paths")
    owners = contract.get("path_owners")
    slices = contract.get("source_changing_slices")
    errors = []
    for label, value in (
        ("allowed_paths", allowed),
        ("required_paths", required),
        ("protected_paths", protected),
    ):
        if (
            not isinstance(value, list)
            or any(not nonempty_string(path) for path in value)
            or len(value) != len(set(value))
        ):
            errors.append(f"transfer {label} must be a unique non-empty string array")
    if errors:
        return errors
    if not required or not set(required).issubset(allowed):
        errors.append("transfer required_paths must be a non-empty subset of allowed_paths")
    if set(protected) & set(allowed):
        errors.append("transfer protected_paths must not overlap allowed_paths")
    if (
        not isinstance(slices, list)
        or len(slices) != 1
        or not isinstance(slices[0], dict)
        or set(slices[0]) != {"id", "required_paths"}
        or not nonempty_string(slices[0].get("id"))
        or slices[0].get("required_paths") != required
    ):
        errors.append("transfer must declare exactly one source-changing slice")
    if (
        not isinstance(owners, dict)
        or any(
            not nonempty_string(owners.get(path))
            for path in set(protected) | {
                effect.get("path")
                for effect in contract.get("allowed_effects", [])
                if isinstance(effect, dict) and effect.get("operation") == "created"
            }
        )
        or any(not nonempty_string(owner) for owner in owners.values())
    ):
        errors.append("transfer generated/protected paths must have one owner")
    return errors


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, value in load_jsonl_objects(path):
        value = dict(value)
        value["_line"] = line_no
        records.append(value)
    return records


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check_benefit_definition(
    value: Any, errors: list[str], *, prefix: str, allow_negative_threshold: bool,
) -> None:
    required = {"metric", "comparator", "direction", "effect", "minimum_benefit"}
    if not isinstance(value, dict):
        errors.append(f"{prefix} must be an object")
        return
    if set(value) != required:
        errors.append(f"{prefix} fields must equal {sorted(required)}")
    metric = value.get("metric")
    if metric not in PAIRED_METRICS:
        errors.append(f"{prefix}.metric must be one of {sorted(PAIRED_METRICS)}")
    comparator = value.get("comparator")
    if comparator not in COMPARATORS:
        errors.append(f"{prefix}.comparator must be one of {sorted(COMPARATORS)}")
    direction = value.get("direction")
    if direction not in BENEFIT_DIRECTIONS:
        errors.append(f"{prefix}.direction must be one of {sorted(BENEFIT_DIRECTIONS)}")
    elif metric in PAIRED_METRIC_DIRECTIONS and direction != PAIRED_METRIC_DIRECTIONS[metric]:
        errors.append(f"{prefix}.direction contradicts metric {metric}")
    if value.get("effect") not in BENEFIT_EFFECTS:
        errors.append(f"{prefix}.effect must be one of {sorted(BENEFIT_EFFECTS)}")
    elif value.get("effect") == "relative" and metric not in RELATIVE_EFFECT_METRICS:
        errors.append(f"{prefix}.effect must be absolute for metric {metric}")
    threshold = value.get("minimum_benefit")
    if (
        not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
        or not math.isfinite(float(threshold))
        or (not allow_negative_threshold and threshold < 0)
    ):
        qualifier = "finite numeric" if allow_negative_threshold else "finite non-negative numeric"
        errors.append(f"{prefix}.minimum_benefit must be {qualifier}")


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

    if spec.get("schema_version") != 4:
        errors.append("spec.schema_version must equal 4")
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
            "treatment_contract_hash",
        ):
            value = suite.get(field)
            if not nonempty_string(value):
                errors.append(f"spec.suite.{field} must be a non-empty SHA-256 value")
            elif not PLACEHOLDER_RE.search(value) and not SHA256_RE.fullmatch(value):
                errors.append(f"spec.suite.{field} must be sha256:<64 hex>")
        if (
            isinstance(variants, list)
            and variants
            and all(
                isinstance(variant, dict)
                and {
                    "id", "role", "mode", "package_hash", "catalog_hash",
                    "treatment_hash",
                }.issubset(variant)
                for variant in variants
            )
            and not PLACEHOLDER_RE.search(str(suite.get("treatment_contract_hash", "")))
            and suite.get("treatment_contract_hash") != treatment_contract_hash(variants)
        ):
            errors.append("spec.suite.treatment_contract_hash does not bind spec.variants")
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
            prefix = f"spec.hard_gates[{index}]"
            if nonempty_string(gate.get("id")):
                gate_ids.append(gate["id"])
            else:
                errors.append(f"{prefix}.id must be a non-empty string")
            if not nonempty_string(gate.get("metric")):
                errors.append(f"{prefix}.metric must be a non-empty string")
            else:
                metric = gate["metric"]
                supported = (
                    metric in PAIRED_METRICS or metric in GLOBAL_GATE_METRICS
                    or ("." in metric and metric.split(".", 1)[1] in VARIANT_GATE_METRICS)
                )
                if not supported:
                    errors.append(f"{prefix}.metric is not supported by the bundled analyzer: {metric}")
                elif "." in metric and metric.split(".", 1)[0] not in variant_ids:
                    errors.append(f"{prefix}.metric references an unknown variant: {metric}")
            if gate.get("metric") in PAIRED_METRICS:
                if set(gate) != {"id", "metric", "comparator", "direction", "effect", "minimum_benefit"}:
                    errors.append(f"{prefix} comparative fields are invalid")
                check_benefit_definition(
                    {key: gate.get(key) for key in (
                        "metric", "comparator", "direction", "effect", "minimum_benefit",
                    )},
                    errors, prefix=prefix, allow_negative_threshold=True,
                )
            else:
                if set(gate) != {"id", "metric", "operator", "value"}:
                    errors.append(f"{prefix} absolute fields are invalid")
                if gate.get("operator") not in {"==", "!=", ">=", "<=", ">", "<"}:
                    errors.append(f"{prefix}.operator is invalid")
                value = gate.get("value")
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                    errors.append(f"{prefix}.value must be numeric for the bundled analyzer")
        duplicates = sorted(name for name, count in Counter(gate_ids).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate hard-gate IDs: {duplicates}")
        paired_gate_metrics = [
            gate.get("metric") for gate in gates
            if isinstance(gate, dict) and gate.get("metric") in PAIRED_METRICS
        ]
        duplicates = sorted(name for name, count in Counter(paired_gate_metrics).items() if count > 1)
        if duplicates:
            errors.append(f"comparative hard-gate metrics must be unique: {duplicates}")

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
        allowed_analysis_fields = {
            "confidence_level", "paired_bootstrap_iterations", "primary_benefit",
            "context_budget_gate_id", "context_budget_authority",
        }
        unsupported_analysis_fields = sorted(set(analysis) - allowed_analysis_fields)
        if unsupported_analysis_fields:
            errors.append(f"spec.analysis has unsupported fields {unsupported_analysis_fields}")
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
            for legacy_field in ("usefulness_benefit_gate_id", "task_noninferiority_gate_id"):
                if legacy_field in analysis:
                    errors.append(f"spec.analysis.{legacy_field} is not supported by spec v4")
            primary_benefit = analysis.get("primary_benefit")
            check_benefit_definition(
                primary_benefit, errors, prefix="spec.analysis.primary_benefit",
                allow_negative_threshold=False,
            )
            if isinstance(primary_benefit, dict):
                comparator = primary_benefit.get("comparator")
                if comparator in COMPARATORS and not any(
                    variant.get("role") == comparator
                    for variant in spec.get("variants", []) if isinstance(variant, dict)
                ):
                    errors.append(f"spec.analysis.primary_benefit.comparator has no {comparator} variant")
                if isinstance(metrics, list) and primary_benefit.get("metric") not in metrics:
                    errors.append("spec.metrics must declare the primary benefit metric")
                if primary_benefit.get("metric") in {
                    gate.get("metric") for gate in (gates if isinstance(gates, list) else [])
                    if isinstance(gate, dict)
                }:
                    errors.append("primary benefit metric must not be duplicated as a hard gate")

                comparative_guardrails = {
                    gate.get("metric") for gate in (gates if isinstance(gates, list) else [])
                    if isinstance(gate, dict)
                    and gate.get("metric") in PAIRED_METRICS
                    and isinstance(gate.get("minimum_benefit"), (int, float))
                    and not isinstance(gate.get("minimum_benefit"), bool)
                    and gate.get("minimum_benefit") <= 0
                    and gate.get("comparator") == primary_benefit.get("comparator")
                }
                for gate in (gates if isinstance(gates, list) else []):
                    if not isinstance(gate, dict) or gate.get("metric") not in PAIRED_METRICS:
                        continue
                    if isinstance(metrics, list) and gate.get("metric") not in metrics:
                        errors.append(f"spec.metrics must declare comparative gate metric {gate.get('metric')}")
                    comparator_role = gate.get("comparator")
                    if comparator_role in COMPARATORS and not any(
                        variant.get("role") == comparator_role
                        for variant in spec.get("variants", []) if isinstance(variant, dict)
                    ):
                        errors.append(f"comparative gate {gate.get('id')} has no {comparator_role} variant")
                if (
                    primary_benefit.get("metric") != "task_pass_rate"
                    and "task_pass_rate" not in comparative_guardrails
                ):
                    errors.append("non-task primary benefit requires a task_pass_rate noninferiority gate")
                if primary_benefit.get("metric") in COST_METRICS:
                    missing_guardrails = sorted({
                        "task_pass_rate", "quality_score_normalized", "safety_pass_rate",
                    } - comparative_guardrails)
                    if missing_guardrails:
                        errors.append(
                            "cost primary benefit requires task/quality/safety noninferiority gates: "
                            f"{missing_guardrails}"
                        )
                    authority_protection = any(
                        isinstance(gate, dict)
                        and gate.get("metric") == "unauthorized_side_effects"
                        and gate.get("operator") == "==" and gate.get("value") == 0
                        for gate in (gates if isinstance(gates, list) else [])
                    )
                    if not authority_protection:
                        errors.append("cost primary benefit requires unauthorized_side_effects == 0 authority protection")

            protected_gates = [
                gate for gate in (gates if isinstance(gates, list) else []) if isinstance(gate, dict)
                and gate.get("metric") == "protected_outcome_failures"
            ]
            if (
                len(protected_gates) != 1
                or protected_gates[0].get("operator") != "=="
                or protected_gates[0].get("value") != 0
            ):
                errors.append("L2+ spec requires one protected_outcome_failures == 0 gate")

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
                    "controlled_skill_context_bytes_p95",
                    "host_integration_duplicate_bytes_max",
                ):
                    matches = [
                        gate for gate in (gates if isinstance(gates, list) else [])
                        if isinstance(gate, dict) and gate.get("metric") == metric
                    ]
                    value = matches[0].get("value") if len(matches) == 1 else None
                    if (
                        len(matches) != 1
                        or matches[0].get("operator") != "<="
                        or not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or value <= 0
                    ):
                        errors.append(f"scored-ready L2+ spec requires one positive {metric} <= gate")
                for metric in (
                    "unexplained_repeated_static_content_bytes_max",
                    "unattributed_model_body_read_count_max",
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
    _, resolved = resolve_evidence_path(root, reference, "path")
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
                actual_hash = file_sha256(path)
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
            actual_hash = file_sha256(verifier_path)
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
                actual_hash = file_sha256(manifest_path)
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


def _contract_diagnostic(
    family: str,
    code: str,
    path: str,
    message: str,
) -> dict[str, str]:
    return {
        "family": family,
        "code": code,
        "path": path,
        "message": message,
    }


def _write_contract_report(
    report: dict[str, Any],
    output: str | None,
) -> None:
    payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if output == "-":
        sys.stdout.write(payload)
    elif output:
        atomic_write_bytes(Path(output), payload.encode("utf-8"), replace=True)


def _print_contract_status(
    report: dict[str, Any],
    *,
    json_output: str | None,
) -> None:
    errors = report["errors"]
    warnings = report["warnings"]
    if errors:
        status = "INVALID"
    elif report["strict"] and warnings:
        status = "INVALID IN STRICT MODE"
    elif warnings:
        status = "VALID WITH WARNINGS"
    else:
        status = "VALID"
    stream = sys.stderr if json_output == "-" else sys.stdout
    print(
        f"{status}: {report['scenario_count']} scenarios, "
        f"{len(errors)} errors, {len(warnings)} warnings",
        file=stream,
    )
    for diagnostic in errors:
        print(
            f"ERROR {diagnostic['code']} {diagnostic['path']}: "
            f"{diagnostic['message']}",
            file=stream,
        )
    for diagnostic in warnings:
        print(
            f"WARN {diagnostic['code']} {diagnostic['path']}: "
            f"{diagnostic['message']}",
            file=stream,
        )


def _contract_command(args: argparse.Namespace) -> int:
    try:
        spec_path = Path(args.paths[0])
        spec = load_json(spec_path)
        level = spec.get("level") if isinstance(spec, dict) else None
        expected_arity = 1 if level == "L0" else 3 if level in LEVELS else None
        if expected_arity is not None and len(args.paths) != expected_arity:
            print(
                f"contract arity error: {level} requires {expected_arity} "
                f"path argument{'s' if expected_arity != 1 else ''}",
                file=sys.stderr,
            )
            return 2
        if len(args.paths) not in {1, 3}:
            print(
                "contract arity error: expected SPEC or SPEC SCENARIOS HOST",
                file=sys.stderr,
            )
            return 2

        scenario_rows: list[dict[str, Any]] = []
        scenarios_path: Path | None = None
        host_path: Path | None = None
        host: Any = None
        if len(args.paths) == 3:
            scenarios_path = Path(args.paths[1])
            host_path = Path(args.paths[2])
            scenario_rows = [
                row for _, row in load_jsonl_objects(scenarios_path)
            ]
            host = load_json(host_path)
        registry = load_v5_schema_registry()
    except (OSError, ValueError) as exc:
        print(f"contract input error: {exc}", file=sys.stderr)
        return 2

    errors = validate_v5_schema(
        spec, "eval-spec-v5.schema.json", registry,
    )
    for index, row in enumerate(scenario_rows):
        for diagnostic in validate_v5_schema(
            row, "scenario-v1.schema.json", registry,
        ):
            errors.append({
                **diagnostic,
                "path": f"/scenarios/{index}{diagnostic['path']}",
            })
    if host is not None:
        for diagnostic in validate_v5_schema(
            host, "host-manifest-v1.schema.json", registry,
        ):
            errors.append({
                **diagnostic,
                "path": f"/host{diagnostic['path']}",
            })

    warnings: list[dict[str, str]] = []
    if not errors:
        try:
            semantic_errors, warnings = validate_v5_contract_semantics(
                spec,
                scenario_rows,
                host,
                spec_path=spec_path,
                scenarios_path=scenarios_path,
                host_path=host_path,
                registry=registry,
            )
        except (OSError, ValueError) as exc:
            print(f"contract input error: {exc}", file=sys.stderr)
            return 2
        errors.extend(semantic_errors)

    schema_valid = not any(
        diagnostic["family"] == "schema" for diagnostic in errors
    )
    execution = spec.get("execution") if isinstance(spec, dict) else None
    ready = isinstance(execution, dict) and execution.get("ready") is True
    execution_ready = (
        level != "L0" and ready and not errors
    )
    report = {
        "schema_version": 2,
        "command": "contract",
        "valid": not errors and (not args.strict or not warnings),
        "schema_valid": schema_valid,
        "execution_ready": execution_ready,
        "strict": args.strict,
        "errors": errors,
        "warnings": warnings,
        "scenario_count": len(scenario_rows),
    }
    try:
        _write_contract_report(report, args.json)
    except (OSError, ValueError) as exc:
        print(f"contract output error: {exc}", file=sys.stderr)
        return 2
    _print_contract_status(report, json_output=args.json)
    return 1 if errors or (args.strict and warnings) else 0


def _commit_preparation_artifact(
    output_path: Path,
    artifact: dict[str, Any],
    *,
    label: str,
    id_field: str,
    hash_field: str,
) -> int:
    payload = canonical_json_bytes(artifact)
    try:
        if output_path.exists():
            if output_path.read_bytes() == payload:
                print(
                    f"{label} VALID: {artifact[id_field]} "
                    f"{artifact[hash_field]}",
                )
                return 0
            print(
                f"{label.lower()} output error: refusing to overwrite "
                f"different output bytes: {output_path}",
                file=sys.stderr,
            )
            return 2
        atomic_write_bytes(output_path, payload)
        written = load_json(output_path)
    except (OSError, ValueError) as exc:
        print(f"{label.lower()} output error: {exc}", file=sys.stderr)
        return 2
    if written != artifact or not verify_self_hash(written, hash_field):
        print(
            f"{label.lower()} output error: post-write verification failed",
            file=sys.stderr,
        )
        return 2
    print(f"{label} VALID: {artifact[id_field]} {artifact[hash_field]}")
    return 0


CALIBRATION_LABEL_FIELDS = {
    "schema_version", "example_id", "class", "dimension", "check_id",
    "payload_hash", "source_support", "gold_label", "gold_severity",
    "task", "language", "risk", "host", "model",
}
CALIBRATION_RATING_FIELDS = {
    "schema_version", "rating_id", "example_id", "grader_id", "dimension",
    "check_id", "label", "severity", "position",
    "blinded_treatment_labels", "reviewer", "grader_identity",
    "execution_identity", "independence_facts", "ordering", "created",
    "expires", "drift_triggers", "adjudication_policy", "thresholds",
}


def _calibration_failure(code: str, message: str) -> int:
    print(f"ERROR {code}: {message}", file=sys.stderr)
    return 1


def _uniform_value(
    rows: list[dict[str, Any]],
    field: str,
    *,
    code: str,
) -> Any:
    values = {
        canonical_json_bytes(row.get(field))
        for row in rows
    }
    if len(values) != 1:
        raise ValueError(f"{code}: {field} must be identical across ratings")
    return rows[0].get(field)


def _relative_artifact_binding(path: Path, root: Path) -> dict[str, str]:
    binding, _, _ = read_nofollow_regular(
        path, root, label="calibration input artifact",
    )
    return binding


def _jsonl_objects_from_bytes(raw: bytes, label: str) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not valid UTF-8: {exc}") from None
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{label} line {line_no} is invalid JSON: {exc.msg}",
            ) from None
        if not isinstance(value, dict):
            raise ValueError(f"{label} line {line_no} must be an object")
        records.append(value)
    return records


def _derive_independence(
    facts: dict[str, Any],
    *,
    blinded: bool,
) -> dict[str, str]:
    candidate_principal = facts.get("candidate_principal_id")
    grader_principal = facts.get("grader_principal_id")
    principal_separation = (
        "unknown"
        if not nonempty_string(candidate_principal)
        or not nonempty_string(grader_principal)
        else "pass"
        if candidate_principal != grader_principal
        else "fail"
    )
    context_mode = facts.get("context_mode")
    context_separation = (
        "pass"
        if context_mode in {"fresh", "scoped_handoff"}
        else "fail"
        if context_mode in {"forked", "same"}
        else "unknown"
    )
    rationale = facts.get("rationale_exposed")
    rationale_exposure = (
        "present" if rationale is True
        else "absent" if rationale is False
        else "unknown"
    )

    def separation(left_field: str, right_field: str) -> str:
        left = facts.get(left_field)
        right = facts.get(right_field)
        if (
            not isinstance(left, list)
            or not left
            or not isinstance(right, list)
            or not right
            or not all(nonempty_string(item) for item in left + right)
        ):
            return "unknown"
        return "pass" if set(left).isdisjoint(right) else "fail"

    genealogy_separation = separation(
        "candidate_model_genealogy", "grader_model_genealogy",
    )
    evidence_source_separation = separation(
        "candidate_evidence_source_hashes",
        "grader_evidence_source_hashes",
    )
    normalized = {
        "principal_separation": principal_separation,
        "context_separation": context_separation,
        "rationale_exposure": rationale_exposure,
        "genealogy_separation": genealogy_separation,
        "evidence_source_separation": evidence_source_separation,
        "blinding_verified": "pass" if blinded else "fail",
    }
    unknown = any(value == "unknown" for value in normalized.values())
    dependent = any(value in {"fail", "present"} for value in normalized.values())
    normalized["status"] = (
        "unknown" if unknown else "dependent" if dependent else "independent"
    )
    return normalized


def _calibration_metric_cells(
    labels: dict[str, dict[str, Any]],
    ratings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    dimensions = sorted({row["dimension"] for row in ratings})
    for dimension in dimensions:
        selected = [
            row for row in ratings if row["dimension"] == dimension
        ]
        confusion = {
            "true_positive": 0,
            "true_negative": 0,
            "false_positive": 0,
            "false_negative": 0,
        }
        agreements: list[int] = []
        severity_errors: list[float] = []
        for row in selected:
            gold = labels[row["example_id"]]
            predicted = row["label"]
            expected = gold["gold_label"]
            agreements.append(int(predicted == expected))
            severity_errors.append(
                abs(float(row["severity"]) - float(gold["gold_severity"])),
            )
            if expected == "pass" and predicted == "pass":
                confusion["true_positive"] += 1
            elif expected == "fail" and predicted == "fail":
                confusion["true_negative"] += 1
            elif expected == "fail" and predicted == "pass":
                confusion["false_positive"] += 1
            elif expected == "pass" and predicted == "fail":
                confusion["false_negative"] += 1
        ordered = sorted(
            zip(selected, agreements), key=lambda item: item[0]["position"],
        )
        midpoint = max(1, len(ordered) // 2)
        early = [agreement for _, agreement in ordered[:midpoint]]
        late = [agreement for _, agreement in ordered[midpoint:]]
        early_rate = sum(early) / len(early)
        late_rate = sum(late) / len(late) if late else early_rate
        cells.append({
            "dimension": dimension,
            "confusion": confusion,
            "agreement": sum(agreements) / len(agreements),
            "abstention_rate": (
                sum(row["label"] == "abstain" for row in selected)
                / len(selected)
            ),
            "severity_error": sum(severity_errors) / len(severity_errors),
            "position_delta": early_rate - late_rate,
            "sample_count": len(selected),
        })
    return cells


def _calibration_raw_shape_error(
    ratings: list[Any],
    label_rows: list[Any],
) -> tuple[str, str] | None:
    for index, row in enumerate(label_rows):
        if not isinstance(row, dict) or set(row) != CALIBRATION_LABEL_FIELDS:
            return (
                "calibration.labels_shape",
                f"labels row {index + 1} has unexpected or missing fields",
            )
        strings = (
            "example_id", "dimension", "check_id", "payload_hash",
            "source_support", "task", "language", "risk", "host", "model",
        )
        if (
            row.get("schema_version") != 1
            or not all(nonempty_string(row.get(field)) for field in strings)
            or row.get("class")
            not in {"known_good", "known_bad", "boundary", "abstain"}
            or row.get("gold_label") not in {"pass", "fail", "abstain"}
            or row.get("source_support")
            not in {
                "supported", "unsupported", "unattributed", "stale",
                "not_applicable",
            }
            or not isinstance(row.get("gold_severity"), (int, float))
            or isinstance(row.get("gold_severity"), bool)
            or not math.isfinite(float(row["gold_severity"]))
        ):
            return (
                "calibration.labels_shape",
                f"labels row {index + 1} has invalid field types or values",
            )
    for index, row in enumerate(ratings):
        if not isinstance(row, dict) or set(row) != CALIBRATION_RATING_FIELDS:
            return (
                "calibration.ratings_shape",
                f"ratings row {index + 1} has unexpected or missing fields",
            )
        strings = (
            "rating_id", "example_id", "grader_id", "dimension",
            "check_id", "created", "expires", "adjudication_policy",
        )
        if (
            row.get("schema_version") != 1
            or not all(nonempty_string(row.get(field)) for field in strings)
            or row.get("label") not in {"pass", "fail", "abstain"}
            or not isinstance(row.get("severity"), (int, float))
            or isinstance(row.get("severity"), bool)
            or not math.isfinite(float(row["severity"]))
            or not isinstance(row.get("position"), int)
            or isinstance(row.get("position"), bool)
            or row["position"] < 1
            or not isinstance(row.get("blinded_treatment_labels"), bool)
            or not all(
                isinstance(row.get(field), dict)
                for field in ("reviewer", "ordering", "thresholds")
            )
            or not isinstance(row.get("drift_triggers"), list)
            or row["reviewer"].get("role")
            not in {"judge", "context_clean_subagent_reviewer"}
            or not all(
                nonempty_string(row["reviewer"].get(field))
                for field in (
                    "reviewer_id", "authority", "principal_id",
                )
            )
            or not isinstance(row["reviewer"].get("blinded"), bool)
        ):
            return (
                "calibration.ratings_shape",
                f"ratings row {index + 1} has invalid field types or values",
            )
        judge_specific = (
            "grader_identity", "execution_identity", "independence_facts",
        )
        role = row["reviewer"]["role"]
        if (
            role == "judge"
            and not all(isinstance(row.get(field), dict) for field in judge_specific)
        ) or (
            role == "context_clean_subagent_reviewer"
            and any(row.get(field) is not None for field in judge_specific)
        ):
            return (
                "calibration.ratings_shape",
                f"ratings row {index + 1} has role-incompatible judge identity fields",
            )
    return None


def _calibration_normalized_fields(
    ratings: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    reviewer_pair_binding: dict[str, str] | None,
) -> dict[str, Any]:
    labels = {row["example_id"]: row for row in label_rows}
    judge_rows = [
        row for row in ratings if row["reviewer"]["role"] == "judge"
    ]
    reviewer_rows = [
        row for row in ratings
        if row["reviewer"]["role"] == "context_clean_subagent_reviewer"
    ]
    reviewer_ids = sorted({
        row["reviewer"]["reviewer_id"] for row in reviewer_rows
    })
    reviewer_to_reviewer: list[dict[str, Any]] | None = None
    judge_to_reviewer: list[dict[str, Any]] = []
    if len(reviewer_ids) == 2:
        anchor_id = reviewer_ids[0]
        anchor = {
            row["example_id"]: {
                **labels[row["example_id"]],
                "gold_label": row["label"],
                "gold_severity": row["severity"],
            }
            for row in reviewer_rows
            if row["reviewer"]["reviewer_id"] == anchor_id
        }
        comparisons = [
            row for row in reviewer_rows
            if row["reviewer"]["reviewer_id"] != anchor_id
        ]
        reviewer_to_reviewer = _calibration_metric_cells(anchor, comparisons)

        consensus: dict[str, dict[str, Any]] = {}
        for example_id, label in labels.items():
            rows = [
                row for row in reviewer_rows
                if row["example_id"] == example_id
            ]
            counts = Counter(row["label"] for row in rows)
            ordered = sorted(
                counts.items(), key=lambda item: (-item[1], item[0]),
            )
            consensus_label = (
                ordered[0][0]
                if len(ordered) == 1 or ordered[0][1] > ordered[1][1]
                else "abstain"
            )
            consensus[example_id] = {
                **label,
                "gold_label": consensus_label,
                "gold_severity": (
                    sum(float(row["severity"]) for row in rows) / len(rows)
                ),
            }
        judge_to_reviewer = _calibration_metric_cells(consensus, judge_rows)
    blinded = all(
        row["blinded_treatment_labels"] is True
        and row["reviewer"].get("blinded") is True
        for row in ratings
    )
    return {
        "grader": _uniform_value(
            judge_rows, "grader_identity", code="calibration.grader_identity",
        ),
        "execution_identity": _uniform_value(
            judge_rows, "execution_identity",
            code="calibration.execution_identity",
        ),
        "independence": _derive_independence(
            _uniform_value(
                judge_rows, "independence_facts",
                code="calibration.independence",
            ),
            blinded=blinded,
        ),
        "dimensions": sorted({row["dimension"] for row in label_rows}),
        "check_ids": sorted({row["check_id"] for row in label_rows}),
        "examples": [
            {
                key: row[key]
                for key in (
                    "example_id", "class", "payload_hash",
                    "source_support", "gold_label",
                )
            }
            for row in sorted(label_rows, key=lambda item: item["example_id"])
        ],
        "blinded_treatment_labels": blinded,
        "ordering": _uniform_value(
            ratings, "ordering", code="calibration.ordering",
        ),
        "adjudication_policy": _uniform_value(
            ratings, "adjudication_policy",
            code="calibration.adjudication",
        ),
        "metrics": {
            "judge_to_gold": _calibration_metric_cells(labels, judge_rows),
            "reviewer_to_reviewer": reviewer_to_reviewer,
            "judge_to_reviewer": judge_to_reviewer,
        },
        "reviewer_pair": reviewer_pair_binding,
        "scope": {
            "tasks": sorted({row["task"] for row in label_rows}),
            "languages": sorted({row["language"] for row in label_rows}),
            "risks": sorted({row["risk"] for row in label_rows}),
            "hosts": sorted({row["host"] for row in label_rows}),
            "models": sorted({row["model"] for row in label_rows}),
        },
        "thresholds": _uniform_value(
            ratings, "thresholds", code="calibration.thresholds",
        ),
        "created": _uniform_value(
            ratings, "created", code="calibration.time",
        ),
        "expires": _uniform_value(
            ratings, "expires", code="calibration.time",
        ),
        "drift_triggers": _uniform_value(
            ratings, "drift_triggers", code="calibration.drift",
        ),
        "reviewers": sorted(
            {
                canonical_json_bytes(row["reviewer"]): row["reviewer"]
                for row in ratings
            }.values(),
            key=lambda item: item["reviewer_id"],
        ),
    }


def _normalize_calibration_raw(
    spec: dict[str, Any],
    ratings: list[Any],
    label_rows: list[Any],
    *,
    reviewer_pair_path: Path | None = None,
    output_root: Path | None = None,
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    if not ratings or not label_rows:
        return None, (
            "calibration.empty",
            "ratings and labels must be non-empty",
        )
    shape_error = _calibration_raw_shape_error(ratings, label_rows)
    if shape_error is not None:
        return None, shape_error
    label_ids = [row["example_id"] for row in label_rows]
    rating_ids = [row["rating_id"] for row in ratings]
    if (
        len(label_ids) != len(set(label_ids))
        or len(rating_ids) != len(set(rating_ids))
    ):
        return None, (
            "calibration.duplicate_id",
            "example_id and rating_id values must be unique",
        )
    label_coverage = {
        check_id: {
            row["gold_label"]
            for row in label_rows
            if row["check_id"] == check_id
        }
        for check_id in {row["check_id"] for row in label_rows}
    }
    incomplete_checks = sorted(
        check_id
        for check_id, labels_for_check in label_coverage.items()
        if not {"pass", "fail"} <= labels_for_check
    )
    if incomplete_checks:
        return None, (
            "calibration.check_label_coverage",
            "every calibrated check requires pass and fail gold labels: "
            f"{incomplete_checks}",
        )
    labels = {row["example_id"]: row for row in label_rows}
    judge_rows = [
        row for row in ratings if row["reviewer"]["role"] == "judge"
    ]
    if any(
        row["example_id"] not in labels
        or row["dimension"] != labels[row["example_id"]]["dimension"]
        or row["check_id"] != labels[row["example_id"]]["check_id"]
        for row in judge_rows
    ):
        return None, (
            "calibration.example_join",
            "judge ratings must join a labeled example with the same check and dimension",
        )
    reviewer_identities: dict[str, tuple[Any, ...]] = {}
    for row in ratings:
        reviewer = row["reviewer"]
        identity = (
            reviewer["role"],
            reviewer["authority"],
            reviewer["principal_id"],
            reviewer["blinded"],
        )
        reviewer_id = reviewer["reviewer_id"]
        if (
            reviewer_id in reviewer_identities
            and reviewer_identities[reviewer_id] != identity
        ):
            return None, (
                "calibration.reviewer_identity",
                "each reviewer_id must bind one role, authority, principal, and blinding state",
            )
        reviewer_identities[reviewer_id] = identity
    reviewer_examples = [
        (row["reviewer"]["reviewer_id"], row["example_id"])
        for row in ratings
    ]
    if len(reviewer_examples) != len(set(reviewer_examples)):
        return None, (
            "calibration.duplicate_rating",
            "each reviewer may rate each labeled example only once",
        )
    judge_reviewers = {
        row["reviewer"]["reviewer_id"] for row in judge_rows
    }
    if (
        len(judge_reviewers) != 1
        or len(judge_rows) != len(label_rows)
        or {row["example_id"] for row in judge_rows} != set(label_ids)
    ):
        return None, (
            "calibration.judge_coverage",
            "one blinded judge must rate every labeled example exactly once",
        )
    reviewer_rows = [
        row for row in ratings
        if row["reviewer"]["role"] == "context_clean_subagent_reviewer"
    ]
    judge_principals = {
        row["reviewer"]["principal_id"] for row in judge_rows
    }
    judge_grader_ids = {row["grader_id"] for row in judge_rows}
    if len(judge_principals) != 1 or len(judge_grader_ids) != 1:
        return None, (
            "calibration.judge_identity",
            "judge rows must bind one principal and target grader",
        )
    reviewer_pair_binding: dict[str, str] | None = None
    effective_ratings: list[dict[str, Any]] = list(ratings)
    if reviewer_pair_path is None:
        if reviewer_rows:
            return None, (
                "calibration.reviewer_pair_missing",
                "subagent reviewer rows require a reviewer pair binding",
            )
    else:
        if output_root is None:
            return None, (
                "calibration.reviewer_pair",
                "reviewer pair validation requires an output root",
            )
        judge_grader_id = next(iter(judge_grader_ids))
        target_graders = [
            grader for grader in spec.get("graders", [])
            if grader.get("type") == "model"
            and grader.get("grader_id") == judge_grader_id
        ]
        if len(target_graders) != 1:
            return None, (
                "calibration.grader_scope",
                "reviewer packet must target one selected model grader",
            )
        expected_checks = {
            check["check_id"]: check["pass_condition"]
            for check in target_graders[0].get("checks", [])
        }
        try:
            pair_result = validate_reviewer_pair(
                reviewer_pair_path,
                output_root=output_root,
                reviewer_rows=reviewer_rows,
                label_rows=label_rows,
                judge_reviewer_ids=judge_reviewers,
                judge_principal_ids=judge_principals,
                judge_grader_id=judge_grader_id,
                expected_checks=expected_checks,
            )
        except ReviewerPairError as exc:
            return None, (exc.code, exc.message)
        reviewer_pair_binding = pair_result["binding"]
        mapped_by_rating = {
            row["rating_id"]: row for row in pair_result["mapped_rows"]
        }
        effective_ratings = [
            mapped_by_rating.get(row["rating_id"], row)
            for row in ratings
        ]
    if any(
        row["blinded_treatment_labels"] is not True
        or row["reviewer"].get("blinded") is not True
        for row in ratings
    ):
        return None, (
            "calibration.blinding",
            "all calibration ratings and reviewers must be blinded",
        )
    try:
        normalized = _calibration_normalized_fields(
            effective_ratings, label_rows, reviewer_pair_binding,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return None, ("calibration.ratings_shape", str(exc))
    positions = [row["position"] for row in ratings]
    schedule_hash = canonical_sha256([
        {"example_id": row["example_id"], "position": row["position"]}
        for row in sorted(ratings, key=lambda item: item["position"])
    ])
    if (
        sorted(positions) != list(range(1, len(ratings) + 1))
        or normalized["ordering"].get("schedule_hash") != schedule_hash
    ):
        return None, (
            "calibration.ordering",
            "positions or schedule_hash do not match the blinded batch",
        )
    selected = [
        grader for grader in spec.get("graders", [])
        if grader.get("type") == "model"
        and grader.get("grader_id") == normalized["grader"].get("grader_id")
    ]
    if len(selected) != 1:
        return None, (
            "calibration.grader_scope",
            "ratings must identify exactly one selected model grader",
        )
    grader = selected[0]
    if (
        normalized["grader"].get("model") != grader.get("model")
        or normalized["grader"].get("prompt_hash")
        != grader.get("prompt", {}).get("sha256")
        or normalized["grader"].get("schema_hash")
        != grader.get("output_schema", {}).get("sha256")
    ):
        return None, (
            "calibration.grader_identity",
            "raw grader identity does not match the selected spec grader",
        )
    checks = {
        check.get("check_id"): check.get("dimension")
        for check in grader.get("checks", [])
    }
    if (
        set(normalized["check_ids"]) != set(checks)
        or any(
            checks.get(row["check_id"]) != row["dimension"]
            for row in label_rows
        )
    ):
        return None, (
            "calibration.check_coverage",
            "calibration labels must cover every selected grader check",
        )
    required_classes = {"known_good", "known_bad", "boundary", "abstain"}
    for check_id in checks:
        classes = {
            row["class"] for row in label_rows
            if row["check_id"] == check_id
        }
        if not required_classes <= classes:
            return None, (
                "calibration.class_coverage",
                f"grader check {check_id} lacks a required example class",
            )
        if (
            checks[check_id] == "grounding"
            and not {"supported", "unsupported", "unattributed"} <= {
                row["source_support"] for row in label_rows
                if row["check_id"] == check_id
            }
        ):
            return None, (
                "calibration.grounding_coverage",
                f"grounding check {check_id} lacks support/attribution boundaries",
            )
    thresholds = normalized["thresholds"]
    if (
        set(thresholds) != {"minimum_agreement", "minimum_examples"}
        or not isinstance(thresholds.get("minimum_agreement"), (int, float))
        or isinstance(thresholds.get("minimum_agreement"), bool)
        or not 0 <= thresholds["minimum_agreement"] <= 1
        or not isinstance(thresholds.get("minimum_examples"), int)
        or isinstance(thresholds.get("minimum_examples"), bool)
        or thresholds["minimum_examples"] < 1
    ):
        return None, (
            "calibration.thresholds",
            "thresholds must declare minimum_agreement and minimum_examples",
        )
    threshold_gates = {
        gate.get("metric"): gate
        for gate in spec.get("hard_gates", [])
        if gate.get("kind") == "calibration"
        and gate.get("required") is True
    }
    if any(
        key not in threshold_gates
        or threshold_gates[key].get("direction") != "at_least"
        or threshold_gates[key].get("threshold") != value
        for key, value in thresholds.items()
    ):
        return None, (
            "calibration.threshold_contract",
            "raw thresholds must equal required calibration gates in the spec",
        )
    check_agreements = {
        check_id: (
            sum(
                row["label"] == labels[row["example_id"]]["gold_label"]
                for row in judge_rows
                if row["check_id"] == check_id
            )
            / sum(row["check_id"] == check_id for row in judge_rows)
        )
        for check_id in checks
    }
    failed_checks = sorted(
        check_id
        for check_id, agreement in check_agreements.items()
        if agreement < thresholds["minimum_agreement"]
    )
    if (
        len(label_rows) < thresholds["minimum_examples"]
        or failed_checks
        or any(
            cell["agreement"] < thresholds["minimum_agreement"]
            for cell in normalized["metrics"]["judge_to_gold"]
        )
    ):
        return None, (
            "calibration.threshold_failed",
            "calibration sample count or per-check judge agreement is below "
            f"threshold; failed checks: {failed_checks}",
        )
    return normalized, None


def _validate_calibration_raw_normalization(
    spec: dict[str, Any],
    calibration: dict[str, Any],
    *,
    artifact_path: Path,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    raw_inputs: dict[str, bytes] = {}
    for field in ("labeled_examples", "raw_ratings"):
        binding = calibration.get(field)
        if (
            not isinstance(binding, dict)
            or not isinstance(binding.get("path"), str)
        ):
            _add_contract_error(
                errors,
                "calibration.raw_binding",
                f"/calibration/{field}",
                f"calibration {field} binding is invalid",
            )
            continue
        try:
            observed, raw, _ = read_nofollow_regular(
                artifact_path.parent / binding["path"],
                artifact_path.parent,
                label=f"calibration {field}",
            )
        except (OSError, ReviewerPairError) as exc:
            _add_contract_error(
                errors,
                "calibration.raw_binding",
                f"/calibration/{field}",
                str(exc),
            )
            continue
        if observed != binding:
            _add_contract_error(
                errors,
                "calibration.raw_binding",
                f"/calibration/{field}",
                f"calibration {field} binding does not match reopened bytes",
            )
            continue
        raw_inputs[field] = raw
    if len(raw_inputs) != 2:
        return
    try:
        label_rows = _jsonl_objects_from_bytes(
            raw_inputs["labeled_examples"], "calibration labels",
        )
        ratings = _jsonl_objects_from_bytes(
            raw_inputs["raw_ratings"], "calibration ratings",
        )
    except (OSError, ValueError) as exc:
        _add_contract_error(
            errors,
            "calibration.raw_read",
            "/calibration",
            f"cannot read bound calibration rows: {exc}",
        )
        return
    reviewer_pair = calibration.get("reviewer_pair")
    reviewer_pair_path = (
        artifact_path.parent / reviewer_pair["path"]
        if isinstance(reviewer_pair, dict)
        and isinstance(reviewer_pair.get("path"), str)
        else None
    )
    expected, normalization_error = _normalize_calibration_raw(
        spec,
        ratings,
        label_rows,
        reviewer_pair_path=reviewer_pair_path,
        output_root=artifact_path.parent,
    )
    if normalization_error is not None or expected is None:
        code, message = normalization_error or (
            "calibration.raw_shape", "cannot normalize bound calibration rows",
        )
        _add_contract_error(errors, code, "/calibration", message)
        return
    identity = {
        "evaluation_id": spec.get("evaluation_id"),
        "grader": expected["grader"],
        "ratings": calibration["raw_ratings"]["sha256"],
        "labels": calibration["labeled_examples"]["sha256"],
    }
    if expected["reviewer_pair"] is not None:
        identity["reviewer_pair"] = expected["reviewer_pair"]["sha256"]
    expected_id = "cal-" + canonical_sha256(identity).removeprefix("sha256:")[:24]
    expected = {
        **expected,
        "calibration_id": expected_id,
    }
    mismatched = [
        field
        for field, value in expected.items()
        if calibration.get(field) != value
    ]
    if mismatched:
        _add_contract_error(
            errors,
            "calibration.normalization",
            "/calibration",
            f"normalized fields differ from bound raw rows: {mismatched}",
        )


def _calibration_command(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    ratings_path = Path(args.ratings)
    labels_path = Path(args.labels)
    output_path = Path(args.output)
    reviewer_pair_path = (
        Path(args.reviewer_pair) if args.reviewer_pair is not None else None
    )
    try:
        spec = load_json(spec_path)
        _, ratings_raw, _ = read_nofollow_regular(
            ratings_path, output_path.parent, label="calibration ratings",
        )
        _, labels_raw, _ = read_nofollow_regular(
            labels_path, output_path.parent, label="calibration labels",
        )
        ratings = _jsonl_objects_from_bytes(
            ratings_raw, "calibration ratings",
        )
        label_rows = _jsonl_objects_from_bytes(
            labels_raw, "calibration labels",
        )
        registry = load_v5_schema_registry()
    except (OSError, ReviewerPairError, ValueError) as exc:
        print(f"calibration input error: {exc}", file=sys.stderr)
        return 2

    schema_errors = validate_v5_schema(
        spec, "eval-spec-v5.schema.json", registry,
    )
    if schema_errors:
        diagnostic = schema_errors[0]
        return _calibration_failure(
            diagnostic["code"],
            f"{diagnostic['path']}: {diagnostic['message']}",
        )
    normalized, normalization_error = _normalize_calibration_raw(
        spec,
        ratings,
        label_rows,
        reviewer_pair_path=reviewer_pair_path,
        output_root=output_path.parent,
    )
    if normalization_error is not None or normalized is None:
        return _calibration_failure(*(normalization_error or (
            "calibration.ratings_shape",
            "cannot normalize calibration rows",
        )))
    grader_identity = normalized["grader"]
    created = normalized["created"]
    expires = normalized["expires"]
    drift_triggers = normalized["drift_triggers"]
    selected = [
        grader for grader in spec.get("graders", [])
        if grader.get("type") == "model"
        and grader.get("grader_id") == grader_identity.get("grader_id")
    ]
    grader = selected[0]
    try:
        _, scenario_path = resolve_evidence_path(
            spec_path.parent,
            spec["suite"]["scenarios"]["path"],
            "calibration scenario corpus",
            kind="file",
        )
        if file_sha256(scenario_path) != spec["suite"]["scenarios"]["sha256"]:
            return _calibration_failure(
                "calibration.scope",
                "scenario corpus hash does not match the spec binding",
            )
        scenarios = [
            row for _, row in load_jsonl_objects(scenario_path)
        ]
    except (OSError, ValueError) as exc:
        print(f"calibration input error: {exc}", file=sys.stderr)
        return 2
    supplied_scope = {
        "tasks": {row["task"] for row in label_rows},
        "languages": {row["language"] for row in label_rows},
        "risks": {row["risk"] for row in label_rows},
        "hosts": {row["host"] for row in label_rows},
        "models": {row["model"] for row in label_rows},
    }
    required_scope = {
        "tasks": {
            row.get("execution_context", {}).get("domain")
            for row in scenarios
        },
        "languages": {
            row.get("execution_context", {}).get("language")
            for row in scenarios
        },
        "risks": {spec["risk_tier"]},
        "hosts": set(spec["subject"]["claimed_hosts"]),
        "models": {grader["model"]},
    }
    for field, expected in required_scope.items():
        if not expected <= supplied_scope[field]:
            return _calibration_failure(
                "calibration.scope",
                f"labeled examples do not cover {field}: {sorted(expected)}",
            )
    try:
        as_of = _parse_rfc3339_seconds(
            spec["execution"]["as_of"], "/execution/as_of",
        )
        created_at = _parse_rfc3339_seconds(created, "/ratings/created")
        expires_at = _parse_rfc3339_seconds(expires, "/ratings/expires")
    except ValueError as exc:
        return _calibration_failure("calibration.time", str(exc))
    if not created_at <= as_of < expires_at:
        return _calibration_failure(
            "calibration.expiry",
            "raw calibration must satisfy created <= execution.as_of < expires",
        )
    if any(
        trigger.get("status") != "unchanged"
        or trigger.get("expected") != trigger.get("observed")
        for trigger in drift_triggers
    ):
        return _calibration_failure(
            "calibration.drift", "raw drift trigger is changed or inconsistent",
        )

    try:
        labeled_binding = _relative_artifact_binding(
            labels_path, output_path.parent,
        )
        ratings_binding = _relative_artifact_binding(
            ratings_path, output_path.parent,
        )
    except (OSError, ReviewerPairError, ValueError) as exc:
        print(f"calibration output error: {exc}", file=sys.stderr)
        return 2
    calibration_identity = {
        "evaluation_id": spec["evaluation_id"],
        "grader": grader_identity,
        "ratings": ratings_binding["sha256"],
        "labels": labeled_binding["sha256"],
    }
    if normalized["reviewer_pair"] is not None:
        calibration_identity["reviewer_pair"] = normalized["reviewer_pair"]["sha256"]
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "calibration_id": "cal-" + canonical_sha256(
            calibration_identity,
        ).removeprefix("sha256:")[:24],
        "calibration_hash": "sha256:" + "0" * 64,
        "evaluation_id": spec["evaluation_id"],
        **normalized,
        "labeled_examples": labeled_binding,
        "raw_ratings": ratings_binding,
    }
    artifact["calibration_hash"] = canonical_self_hash(
        artifact, "calibration_hash",
    )
    output_errors = validate_v5_schema(
        artifact, "grader-calibration-v1.schema.json", registry,
    )
    if output_errors:
        diagnostic = output_errors[0]
        return _calibration_failure(
            "calibration.output_schema",
            f"{diagnostic['path']}: {diagnostic['message']}",
        )
    return _commit_preparation_artifact(
        output_path,
        artifact,
        label="CALIBRATION",
        id_field="calibration_id",
        hash_field="calibration_hash",
    )


SUITE_QUALITY_PROOF_FIELDS = {
    "schema_version", "evaluation_id", "authority", "thresholds", "golden",
    "known_bad", "mutations", "case_classes", "duplicate_groups",
    "provenance_clusters", "leakage_probes", "custody",
    "boundary_coverage", "review_status",
}


def _quality_failure(code: str, message: str) -> int:
    print(f"ERROR {code}: {message}", file=sys.stderr)
    return 1


def _coverage_map(
    keys_to_cases: dict[str, set[str]],
    classes: dict[str, set[str]],
) -> dict[str, dict[str, int]]:
    return {
        key: {
            "positive": sum(
                "positive" in classes.get(case_id, set())
                for case_id in case_ids
            ),
            "boundary_or_failure": sum(
                "boundary_or_failure" in classes.get(case_id, set())
                for case_id in case_ids
            ),
        }
        for key, case_ids in sorted(keys_to_cases.items())
    }


def _derive_quality_coverage(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    case_classes: list[dict[str, str]],
) -> dict[str, dict[str, dict[str, int]]]:
    classes: dict[str, set[str]] = {}
    for item in case_classes:
        classes.setdefault(item["case_id"], set()).add(item["class"])
    all_cases = {scenario["case_id"] for scenario in scenarios}
    slices: dict[str, set[str]] = {}
    for scenario in scenarios:
        for tag in scenario["tags"]:
            slices.setdefault(tag, set()).add(scenario["case_id"])
    claims = {
        claim: set(all_cases) for claim in spec["subject"]["claims"]
    }
    modules = {
        item["module"]: set(all_cases)
        for item in spec["applicability"]
        if item["status"] == "required"
    }
    treatments: dict[str, set[str]] = {}
    for treatment in spec["treatments"]:
        covered = set(treatment["scenario_ids"])
        covered.update(
            scenario["case_id"]
            for scenario in scenarios
            if set(scenario["tags"]) & set(treatment["scenario_tags"])
        )
        treatments[treatment["treatment_id"]] = covered & all_cases
    checks: dict[str, set[str]] = {}
    for scenario in scenarios:
        for requirement in scenario["requirements"]:
            checks.setdefault(requirement["check_id"], set()).add(
                scenario["case_id"],
            )
    return {
        "slices": _coverage_map(slices, classes),
        "claims": _coverage_map(claims, classes),
        "modules": _coverage_map(modules, classes),
        "treatments": _coverage_map(treatments, classes),
        "checks": _coverage_map(checks, classes),
    }


def _derive_duplicate_groups(
    scenarios: list[dict[str, Any]],
    kind: str,
) -> list[set[str]]:
    groups: dict[bytes, set[str]] = {}
    for scenario in scenarios:
        if kind == "exact":
            projection: Any = {
                key: value
                for key, value in scenario.items()
                if key not in {"case_id", "split"}
            }
        elif kind == "prompt_overlap":
            projection = [
                turn.get("input") for turn in scenario.get("turns", [])
            ]
        elif kind == "fixture_overlap":
            projection = scenario.get("fixture")
        else:
            raise ValueError(f"unknown duplicate kind: {kind}")
        groups.setdefault(canonical_json_bytes(projection), set()).add(
            scenario["case_id"],
        )
    return sorted(
        (case_ids for case_ids in groups.values() if len(case_ids) > 1),
        key=lambda case_ids: sorted(case_ids),
    )


def _quality_split_hashes(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> dict[str, str | None]:
    hashes: dict[str, str | None] = {}
    for split in ("dev", "regression", "heldout"):
        selected = sorted(
            (
                scenario for scenario in scenarios
                if scenario.get("split") == split
            ),
            key=lambda item: item.get("case_id", ""),
        )
        hashes[split] = canonical_sha256(selected) if selected else None
    holdout = spec.get("suite", {}).get("holdout")
    if isinstance(holdout, dict):
        hashes["heldout"] = holdout.get("payload", {}).get("sha256")
    return hashes


def _required_quality_boundaries(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> dict[str, set[str]]:
    required: dict[str, set[str]] = {}
    if any(
        {"boundary", "failure"} & set(scenario.get("tags", []))
        for scenario in scenarios
    ):
        required["scenario-oracle"] = {"boundary_or_failure"}
    modules = required_v5_modules(spec)
    if "multi_principal_coordination" in modules:
        required["coordination"] = {
            "single-principal-equal-budget",
            "decomposability",
            "complete-join",
            "partial-join",
        }
    if "dynamic_security" in modules:
        required["security"] = {
            "allow",
            "deny",
            "allow-with-changes",
            "backend-model-divergence",
            "effect-confirmation",
        }
    claims = {
        str(claim).lower() for claim in spec.get("subject", {}).get("claims", [])
    }
    if any(
        token in claim
        for claim in claims
        for token in ("review", "judge", "voter", "feedback", "critique")
    ):
        required["review"] = {
            "correct-critique-applied",
            "correct-critique-ignored",
            "harmful-uptake",
        }
    if (
        "review" in required
        or any(
            gate.get("kind") == "calibration"
            and gate.get("metric") == "independent_judge"
            and gate.get("required") is True
            for gate in spec.get("hard_gates", [])
        )
    ):
        required["independence"] = {"dependent", "unknown"}
    if any(
        scenario.get("observation_contracts")
        for scenario in scenarios
    ):
        required["observation"] = {
            "correct-fresh",
            "correct-stale",
            "wrong-bytes",
        }
    if any(
        requirement.get("dimension") == "grounding"
        for scenario in scenarios
        for requirement in scenario.get("requirements", [])
    ):
        required["grounding"] = {
            "correct-fresh",
            "correct-stale",
            "wrong-bytes",
            "source-exists-unsupported",
        }
    return required


def _normalize_suite_quality_raw(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    proof: Any,
    *,
    proof_path: Path,
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    if not isinstance(proof, dict) or set(proof) != SUITE_QUALITY_PROOF_FIELDS:
        return None, (
            "quality.proof_shape",
            "proof must be an object with the exact suite-quality input fields",
        )
    if proof.get("schema_version") != 1:
        return None, (
            "quality.proof_version",
            "proof schema_version must equal 1",
        )
    if proof.get("evaluation_id") != spec.get("evaluation_id"):
        return None, (
            "quality.evaluation_identity",
            "proof evaluation_id does not match the spec",
        )
    case_ids = {scenario["case_id"] for scenario in scenarios}
    case_classes = proof.get("case_classes")
    if (
        not isinstance(case_classes, list)
        or any(
            not isinstance(item, dict)
            or set(item) != {"case_id", "class"}
            or item.get("case_id") not in case_ids
            or item.get("class") not in {
                "positive", "boundary_or_failure",
            }
            for item in case_classes
        )
    ):
        return None, (
            "quality.case_classes",
            "case_classes must bind supplied cases to positive/boundary classes",
        )
    coverage = _derive_quality_coverage(spec, scenarios, case_classes)

    golden = proof.get("golden")
    known_bad = proof.get("known_bad")
    mutations = proof.get("mutations")
    if not (
        isinstance(golden, dict)
        and set(golden) == {"case_ids", "passed_ids"}
        and isinstance(golden.get("case_ids"), list)
        and isinstance(golden.get("passed_ids"), list)
        and set(golden["case_ids"]) <= case_ids
        and golden["case_ids"]
    ):
        return None, (
            "quality.golden",
            "golden proof must identify supplied scenarios",
        )
    boundary_ids = {
        scenario["case_id"]
        for scenario in scenarios
        if {"boundary", "failure"} & set(scenario.get("tags", []))
    }
    if not boundary_ids <= set(golden["passed_ids"]):
        return None, (
            "quality.boundary_oracle",
            "every boundary/failure scenario requires a passed golden oracle",
        )
    if not (
        isinstance(known_bad, dict)
        and set(known_bad) == {"case_ids", "detected_ids"}
        and isinstance(known_bad.get("case_ids"), list)
        and isinstance(known_bad.get("detected_ids"), list)
        and known_bad["case_ids"]
    ):
        return None, (
            "quality.known_bad",
            "known-bad proof must be non-empty",
        )
    if not (
        isinstance(mutations, dict)
        and set(mutations) == {"mutation_ids", "detected_ids"}
        and isinstance(mutations.get("mutation_ids"), list)
        and isinstance(mutations.get("detected_ids"), list)
        and mutations["mutation_ids"]
    ):
        return None, (
            "quality.mutations",
            "mutation proof must be non-empty",
        )
    if set(mutations["detected_ids"]) != set(mutations["mutation_ids"]):
        return None, (
            "quality.mutation_detection",
            "every required mutation must be detected",
        )

    declared_duplicates = proof.get("duplicate_groups")
    if not isinstance(declared_duplicates, list):
        return None, (
            "quality.duplicate_shape",
            "duplicate_groups must be an array",
        )
    for kind in ("exact", "prompt_overlap", "fixture_overlap"):
        derived_duplicates = {
            frozenset(group)
            for group in _derive_duplicate_groups(scenarios, kind)
        }
        declared_groups = {
            frozenset(group.get("case_ids", []))
            for group in declared_duplicates
            if isinstance(group, dict) and group.get("kind") == kind
        }
        if derived_duplicates != declared_groups:
            return None, (
                "quality.duplicate_recompute",
                f"declared {kind} groups do not match the scenario corpus",
            )

    provenance_clusters = proof.get("provenance_clusters")
    covered_cases = set().union(*(
        set(cluster.get("case_ids", []))
        for cluster in provenance_clusters
        if isinstance(cluster, dict)
    )) if isinstance(provenance_clusters, list) else set()
    if (
        not isinstance(provenance_clusters, list)
        or not provenance_clusters
        or covered_cases != case_ids
    ):
        return None, (
            "quality.provenance_closure",
            "provenance clusters must cover every supplied scenario",
        )
    leakage_probes = proof.get("leakage_probes")
    if not isinstance(leakage_probes, list) or not leakage_probes:
        return None, (
            "quality.leakage",
            "at least one leakage probe is required",
        )
    review_status = proof.get("review_status")
    if not isinstance(review_status, dict) or set(review_status) != {
        "duplicate_and_provenance_review", "leakage_review",
    }:
        return None, (
            "quality.review_status",
            "review_status is incomplete",
        )
    custody = proof.get("custody")
    if (
        not isinstance(custody, dict)
        or set(custody) != {
            "split_hashes",
            "custodian",
            "exposure_status",
            "author_visible_paths",
            "executor_visible_paths",
        }
        or custody.get("split_hashes") != _quality_split_hashes(spec, scenarios)
        or not isinstance(custody.get("author_visible_paths"), list)
        or not isinstance(custody.get("executor_visible_paths"), list)
    ):
        return None, (
            "quality.custody",
            "custody fields or split hashes do not match the bound suite",
        )
    holdout = spec.get("suite", {}).get("holdout")
    if isinstance(holdout, dict):
        payload_name = holdout["payload"]["path"]
        if (
            custody.get("custodian") != holdout.get("custodian")
            or custody.get("exposure_status")
            != holdout.get("exposure_status")
            or payload_name in custody["author_visible_paths"]
            or payload_name in custody["executor_visible_paths"]
        ):
            return None, (
                "quality.holdout_custody",
                "holdout custody, exposure, or visibility differs from the spec",
            )
    elif custody.get("exposure_status") != "not_applicable":
        return None, (
            "quality.holdout_custody",
            "a suite without holdout must declare exposure not_applicable",
        )
    if proof_path.name in custody["executor_visible_paths"]:
        return None, (
            "quality.executor_leakage",
            "suite-quality proof must not be executor-visible",
        )
    forbidden_executor_paths = {
        binding.get("path")
        for binding in (
            spec.get("suite", {}).get("calibration"),
            spec.get("suite", {}).get("quality"),
        )
        if isinstance(binding, dict)
    }
    leaked_paths = forbidden_executor_paths & set(
        custody["executor_visible_paths"],
    )
    if leaked_paths:
        return None, (
            "quality.executor_leakage",
            f"preparation artifacts are executor-visible: {sorted(leaked_paths)}",
        )
    causal_profiles = {
        treatment.get("profile")
        for treatment in spec.get("treatments", [])
        if treatment.get("causal_role") in {"baseline", "candidate"}
    }
    incomplete_attribution = [
        scenario.get("case_id")
        for scenario in scenarios
        if scenario.get("attribution_evaluable") is True
        and not causal_profiles <= set(
            scenario.get("applicable_treatment_profiles", []),
        )
    ]
    if incomplete_attribution:
        return None, (
            "quality.attribution_profiles",
            f"attribution-evaluable scenarios lack causal profiles: {incomplete_attribution}",
        )
    boundary_coverage = proof.get("boundary_coverage")
    if not isinstance(boundary_coverage, list):
        return None, (
            "quality.boundary_coverage",
            "boundary_coverage must be an array",
        )
    by_surface: dict[str, dict[str, Any]] = {}
    for item in boundary_coverage:
        if (
            not isinstance(item, dict)
            or set(item) != {"surface", "case_classes", "status"}
            or item.get("surface") in by_surface
            or not isinstance(item.get("case_classes"), list)
        ):
            return None, (
                "quality.boundary_coverage",
                "boundary surfaces must be unique exact records",
            )
        by_surface[item["surface"]] = item
    missing_boundaries: dict[str, list[str]] = {}
    for surface, required_classes in _required_quality_boundaries(
        spec, scenarios,
    ).items():
        supplied = by_surface.get(surface, {})
        missing = required_classes - set(supplied.get("case_classes", []))
        if supplied.get("status") != "pass" or missing:
            missing_boundaries[surface] = sorted(missing)
    if missing_boundaries:
        return None, (
            "quality.boundary_coverage",
            f"required boundary mechanisms are not closed: {missing_boundaries}",
        )

    artifact_errors: list[dict[str, str]] = []
    verified_artifacts: dict[str, dict[str, Any]] = {}
    for index, probe in enumerate(leakage_probes):
        if not isinstance(probe, dict):
            return None, (
                "quality.leakage",
                "leakage probe must be an object",
            )
        resolved = _check_bound_file(
            probe.get("artifact", {}),
            root=proof_path.parent,
            label=f"leakage probe {index}",
            path=f"/proof/leakage_probes/{index}/artifact",
            errors=artifact_errors,
            warnings=[],
            ready=True,
        )
        if resolved is not None:
            try:
                text_value = resolved.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                verified_artifacts[probe["artifact"]["path"]] = {
                    "resolved": resolved,
                    "encoding": "binary",
                }
            else:
                verified_artifacts[probe["artifact"]["path"]] = {
                    "resolved": resolved,
                    "encoding": "utf-8",
                    "text": text_value,
                    "lines": text_value.splitlines(),
                }
        if probe.get("locator", {}).get("artifact") != probe.get(
            "artifact", {},
        ).get("path"):
            _add_contract_error(
                artifact_errors,
                "quality.leakage_locator",
                f"/proof/leakage_probes/{index}/locator",
                "leakage locator must name its bound artifact",
            )
    if artifact_errors:
        first = artifact_errors[0]
        return None, (first["code"], first["message"])
    locators: list[dict[str, Any]] = [
        probe["locator"] for probe in leakage_probes
    ]
    locators.extend(
        cluster["review_locator"] for cluster in provenance_clusters
    )
    for group in declared_duplicates:
        if not isinstance(group, dict):
            return None, (
                "quality.duplicate_shape",
                "duplicate group must be an object",
            )
        locator = group.get("review_locator")
        if (
            group.get("kind") == "semantic"
            or group.get("status") == "reviewed_distinct"
        ) and locator is None:
            return None, (
                "quality.review_locator",
                "semantic or reviewed-distinct duplicates require a reviewer locator",
            )
        if locator is not None:
            locators.append(locator)
        group_case_ids = group.get("case_ids", [])
        if (
            len(group_case_ids) != len(set(group_case_ids))
            or not set(group_case_ids) <= case_ids
        ):
            return None, (
                "quality.duplicate_shape",
                "duplicate groups must contain distinct supplied case IDs",
            )
    for locator in locators:
        try:
            validate_locator(locator, verified_artifacts)
        except ValueError as exc:
            return None, (
                "quality.review_locator",
                f"review locator is not verified: {exc}",
            )

    golden_rate = (
        len(set(golden["passed_ids"]) & set(golden["case_ids"]))
        / len(set(golden["case_ids"]))
    )
    known_bad_rate = (
        len(set(known_bad["detected_ids"]) & set(known_bad["case_ids"]))
        / len(set(known_bad["case_ids"]))
    )
    mutation_rate = (
        len(set(mutations["detected_ids"]) & set(mutations["mutation_ids"]))
        / len(set(mutations["mutation_ids"]))
    )
    threshold = proof.get("thresholds", {}).get("minimum_detection")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(float(threshold))
        or not 0 <= threshold <= 1
    ):
        return None, (
            "quality.threshold",
            "minimum_detection must be within [0, 1]",
        )
    required_coverage = all(
        cell["positive"] + cell["boundary_or_failure"] > 0
        for group in coverage.values()
        for cell in group.values()
    ) and all(
        cell["positive"] > 0 and cell["boundary_or_failure"] > 0
        for cell in coverage["modules"].values()
    )
    gates = {
        "golden_solvability": (
            "pass" if golden_rate >= threshold else "fail"
        ),
        "required_mutation_detection": (
            "pass" if mutation_rate >= threshold else "fail"
        ),
        "duplicate_and_provenance_review": (
            "pass"
            if review_status["duplicate_and_provenance_review"] == "pass"
            and all(
                cluster.get("status") == "closed"
                for cluster in provenance_clusters
            )
            else "fail"
        ),
        "leakage_review": (
            "pass"
            if review_status["leakage_review"] == "pass"
            and all(probe.get("status") == "pass" for probe in leakage_probes)
            else "fail"
        ),
        "required_slice_coverage": "pass" if required_coverage else "fail",
        "grader_sensitivity": (
            "pass"
            if known_bad_rate >= threshold and mutation_rate >= threshold
            else "fail"
        ),
    }
    return {
        "duplicate_groups": declared_duplicates,
        "provenance_clusters": provenance_clusters,
        "leakage_probes": leakage_probes,
        "custody": custody,
        "coverage": coverage,
        "grader_sensitivity": {
            "known_good_pass": golden_rate,
            "known_bad_detection": known_bad_rate,
            "mutation_detection": mutation_rate,
            "sample_count": (
                len(golden["case_ids"])
                + len(known_bad["case_ids"])
                + len(mutations["mutation_ids"])
            ),
        },
        "boundary_coverage": boundary_coverage,
        "thresholds": proof["thresholds"],
        "authority": proof["authority"],
        "gates": gates,
    }, None


def _validate_suite_quality_raw_normalization(
    spec: dict[str, Any],
    quality: dict[str, Any],
    *,
    spec_path: Path,
    artifact_path: Path,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    raw_proofs = quality.get("raw_proofs", {})
    bindings = [
        raw_proofs.get(field)
        for field in ("golden", "known_bad", "mutations", "reviews")
    ]
    if not bindings or any(binding != bindings[0] for binding in bindings):
        _add_contract_error(
            errors,
            "quality.raw_binding",
            "/suite_quality/raw_proofs",
            "v1 normalized quality proof bindings must identify one exact proof",
        )
        return
    proof_path = _check_bound_file(
        bindings[0] or {},
        root=artifact_path.parent,
        label="suite-quality raw proof",
        path="/suite_quality/raw_proofs",
        errors=errors,
        warnings=warnings,
        ready=True,
    )
    scenario_path = _check_bound_file(
        spec.get("suite", {}).get("scenarios", {}),
        root=spec_path.parent,
        label="suite-quality scenario corpus",
        path="/suite/scenarios",
        errors=errors,
        warnings=warnings,
        ready=True,
    )
    if proof_path is None or scenario_path is None:
        return
    try:
        proof = load_json(proof_path)
        scenarios = [
            row for _, row in load_jsonl_objects(scenario_path)
        ]
    except (OSError, ValueError) as exc:
        _add_contract_error(
            errors,
            "quality.raw_read",
            "/suite_quality/raw_proofs",
            f"cannot read bound suite-quality proof: {exc}",
        )
        return
    normalized, normalization_error = _normalize_suite_quality_raw(
        spec, scenarios, proof, proof_path=proof_path,
    )
    if normalization_error is not None or normalized is None:
        code, message = normalization_error or (
            "quality.proof_shape", "cannot normalize bound suite-quality proof",
        )
        _add_contract_error(
            errors, code, "/suite_quality/raw_proofs", message,
        )
        return
    expected_id = "sq-" + canonical_sha256({
        "evaluation_id": spec.get("evaluation_id"),
        "quality_contract_hash": quality_contract_hash(spec),
        "proof_hash": bindings[0]["sha256"],
    }).removeprefix("sha256:")[:24]
    expected = {
        **normalized,
        "suite_quality_id": expected_id,
    }
    mismatched = [
        field
        for field, value in expected.items()
        if quality.get(field) != value
    ]
    if mismatched:
        _add_contract_error(
            errors,
            "quality.normalization",
            "/suite_quality",
            f"normalized fields differ from bound raw proof: {mismatched}",
        )


def _suite_quality_command(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    proof_path = Path(args.proof)
    output_path = Path(args.output)
    try:
        spec = load_json(spec_path)
        proof = load_json(proof_path)
        registry = load_v5_schema_registry()
    except (OSError, ValueError) as exc:
        print(f"suite-quality input error: {exc}", file=sys.stderr)
        return 2
    schema_errors = validate_v5_schema(
        spec, "eval-spec-v5.schema.json", registry,
    )
    if schema_errors:
        diagnostic = schema_errors[0]
        return _quality_failure(
            diagnostic["code"],
            f"{diagnostic['path']}: {diagnostic['message']}",
        )
    if spec.get("execution", {}).get("ready") is not False:
        return _quality_failure(
            "quality.draft_required",
            "suite-quality input spec must keep execution.ready=false",
        )
    expected_contract_hash = quality_contract_hash(spec)
    if spec.get("suite", {}).get("quality_contract_hash") != expected_contract_hash:
        return _quality_failure(
            "quality.contract_hash",
            f"quality_contract_hash must be {expected_contract_hash}",
        )
    try:
        _, scenarios_path = resolve_evidence_path(
            spec_path.parent,
            spec["suite"]["scenarios"]["path"],
            "suite scenarios",
            kind="file",
        )
        if file_sha256(scenarios_path) != spec["suite"]["scenarios"]["sha256"]:
            return _quality_failure(
                "quality.scenario_hash",
                "scenario corpus hash does not match the spec binding",
            )
        scenarios = [
            row for _, row in load_jsonl_objects(scenarios_path)
        ]
    except (OSError, ValueError) as exc:
        print(f"suite-quality input error: {exc}", file=sys.stderr)
        return 2
    for index, scenario in enumerate(scenarios):
        scenario_errors = validate_v5_schema(
            scenario, "scenario-v1.schema.json", registry,
        )
        if scenario_errors:
            diagnostic = scenario_errors[0]
            return _quality_failure(
                diagnostic["code"],
                f"/scenarios/{index}{diagnostic['path']}: "
                f"{diagnostic['message']}",
            )

    normalized, normalization_error = _normalize_suite_quality_raw(
        spec, scenarios, proof, proof_path=proof_path,
    )
    if normalization_error is not None or normalized is None:
        return _quality_failure(*(normalization_error or (
            "quality.proof_shape",
            "cannot normalize suite-quality proof",
        )))
    try:
        proof_binding = _relative_artifact_binding(
            proof_path, output_path.parent,
        )
    except (OSError, ValueError) as exc:
        print(f"suite-quality output error: {exc}", file=sys.stderr)
        return 2
    suite = spec["suite"]
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "suite_quality_id": "sq-" + canonical_sha256({
            "evaluation_id": spec["evaluation_id"],
            "quality_contract_hash": expected_contract_hash,
            "proof_hash": proof_binding["sha256"],
        }).removeprefix("sha256:")[:24],
        "suite_quality_hash": "sha256:" + "0" * 64,
        "evaluation_id": spec["evaluation_id"],
        "quality_contract_hash": expected_contract_hash,
        "scenario_hash": suite["scenarios"]["sha256"],
        "holdout_hash": (
            suite["holdout"]["payload"]["sha256"]
            if isinstance(suite.get("holdout"), dict) else None
        ),
        "fixture_set_hash": suite["fixture_set_hash"],
        "grader_set_hash": suite["grader_set_hash"],
        "treatment_contract_hash": suite["treatment_contract_hash"],
        "calibration_hash": (
            suite["calibration"]["sha256"]
            if isinstance(suite.get("calibration"), dict) else None
        ),
        "raw_proofs": {
            key: dict(proof_binding)
            for key in ("golden", "known_bad", "mutations", "reviews")
        },
        **normalized,
    }
    artifact["suite_quality_hash"] = canonical_self_hash(
        artifact, "suite_quality_hash",
    )
    output_errors = validate_v5_schema(
        artifact, "suite-quality-v1.schema.json", registry,
    )
    if output_errors:
        diagnostic = output_errors[0]
        return _quality_failure(
            "quality.output_schema",
            f"{diagnostic['path']}: {diagnostic['message']}",
        )
    return _commit_preparation_artifact(
        output_path,
        artifact,
        label="SUITE QUALITY",
        id_field="suite_quality_id",
        hash_field="suite_quality_hash",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    contract = subparsers.add_parser(
        "contract", help="Validate a v5 spec and its bound preparation inputs",
    )
    contract.add_argument(
        "paths", nargs="+", metavar="PATH",
        help="L0: SPEC; L1+: SPEC SCENARIOS HOST",
    )
    contract.add_argument(
        "--json", metavar="PATH",
        help="Write validation report JSON; use - for stdout",
    )
    contract.add_argument(
        "--strict", action="store_true", help="Treat warnings as failures",
    )
    contract.set_defaults(handler=_contract_command)

    calibration = subparsers.add_parser(
        "calibration", help="Normalize blinded grader calibration evidence",
    )
    calibration.add_argument("--spec", required=True)
    calibration.add_argument("--ratings", required=True)
    calibration.add_argument("--labels", required=True)
    calibration.add_argument("--reviewer-pair")
    calibration.add_argument("--output", required=True)
    calibration.set_defaults(handler=_calibration_command)

    suite_quality = subparsers.add_parser(
        "suite-quality", help="Normalize acyclic suite-quality evidence",
    )
    suite_quality.add_argument("--spec", required=True)
    suite_quality.add_argument("--proof", required=True)
    suite_quality.add_argument("--output", required=True)
    suite_quality.set_defaults(handler=_suite_quality_command)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
