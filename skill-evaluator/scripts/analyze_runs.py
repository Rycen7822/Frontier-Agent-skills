#!/usr/bin/env python3
"""Summarize normalized Agent Skill evaluation runs from JSONL.

The analyzer reports dimension metrics and paired candidate/baseline outcomes. It
never treats its summary as a substitute for the frozen evaluation contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from audit_skill_package import compute_inventory_hash
from validate_eval_suite import (
    check_cases,
    check_spec,
    load_json as load_contract_json,
    load_jsonl as load_contract_jsonl,
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
DYNAMIC_CONTEXT_SOURCE = re.compile(
    r"^(?:protocol|failed-command):[A-Za-z0-9][A-Za-z0-9._-]{0,63}:[1-9][0-9]*$"
)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}") from None
    records: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    expected_fields = {
        "run_schema_version", "run_id", "case_id", "variant", "repeat",
        "artifact_dir", "receipt",
    }
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_no}: {exc.msg}") from None
        if not isinstance(record, dict):
            raise ValueError(f"line {line_no}: record must be an object")
        if set(record) != expected_fields:
            missing = sorted(expected_fields - set(record))
            extra = sorted(set(record) - expected_fields)
            raise ValueError(f"line {line_no}: run index fields mismatch; missing={missing}, extra={extra}")
        if record.get("run_schema_version") != 1:
            raise ValueError(f"line {line_no}: run_schema_version must equal 1")
        run_id = record["run_id"]
        if not isinstance(run_id, str) or not run_id:
            raise ValueError(f"line {line_no}: run_id must be a non-empty string")
        if run_id in seen_run_ids:
            raise ValueError(f"line {line_no}: duplicate run_id {run_id}")
        seen_run_ids.add(run_id)
        if not isinstance(record["case_id"], str) or not record["case_id"]:
            raise ValueError(f"line {line_no}: case_id must be a non-empty string")
        if not isinstance(record["variant"], str) or not record["variant"]:
            raise ValueError(f"line {line_no}: variant must be a non-empty string")
        if not isinstance(record["repeat"], int) or isinstance(record["repeat"], bool) or record["repeat"] < 1:
            raise ValueError(f"line {line_no}: repeat must be an integer >= 1")
        if not isinstance(record.get("artifact_dir"), str) or not record["artifact_dir"].strip():
            raise ValueError(f"line {line_no}: artifact_dir must be a non-empty relative path")
        receipt = record.get("receipt")
        if not isinstance(receipt, dict) or set(receipt) != {"path", "sha256"}:
            raise ValueError(f"line {line_no}: receipt must contain exactly path and sha256")
        if not isinstance(receipt.get("path"), str) or not receipt["path"].strip():
            raise ValueError(f"line {line_no}: receipt.path must be a non-empty relative path")
        if not isinstance(receipt.get("sha256"), str) or not SHA256_RE.fullmatch(receipt["sha256"]):
            raise ValueError(f"line {line_no}: receipt.sha256 must be sha256:<64 hex>")
        records.append(record)
    if not records:
        raise ValueError("run file contains no records")
    return records


def normalize_relative_path(reference: Any, label: str) -> str:
    if not isinstance(reference, str) or not reference or "\\" in reference:
        raise ValueError(f"{label} must be a non-empty POSIX relative path")
    if reference.startswith("/") or any(part == ".." for part in reference.split("/")):
        raise ValueError(f"{label} path escapes its declared root")
    normalized = PurePosixPath(reference).as_posix()
    if normalized in {"", "."}:
        raise ValueError(f"{label} must identify a file")
    return normalized


def resolve_bound_file(root: Path, reference: Any, label: str) -> tuple[str, Path]:
    normalized = normalize_relative_path(reference, label)
    resolved_root = root.resolve()
    resolved = (resolved_root / normalized).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} path escapes its declared root")
    if not resolved.exists():
        raise FileNotFoundError(f"{label} file is missing: {normalized}")
    if not resolved.is_file():
        raise ValueError(f"{label} is not a regular file: {normalized}")
    return normalized, resolved


def resolve_bound_dir(root: Path, reference: Any, label: str) -> tuple[str, Path]:
    normalized = normalize_relative_path(reference, label)
    resolved_root = root.resolve()
    resolved = (resolved_root / normalized).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} path escapes its declared root")
    if not resolved.exists():
        raise FileNotFoundError(f"{label} directory is missing: {normalized}")
    if not resolved.is_dir():
        raise ValueError(f"{label} is not a directory: {normalized}")
    return normalized, resolved


def verify_artifacts(items: Any, root: Path, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError(f"{label} artifacts must be an array")
    verified: dict[str, dict[str, Any]] = {}
    resolved_paths: set[Path] = set()
    for index, item in enumerate(items):
        prefix = f"{label} artifacts[{index}]"
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "encoding"}:
            raise ValueError(f"{prefix} must contain exactly path, sha256, and encoding")
        normalized = normalize_relative_path(item.get("path"), f"{label} artifact")
        if normalized in verified:
            raise ValueError(f"{label} duplicate normalized artifact path: {normalized}")
        if item.get("path") != normalized:
            raise ValueError(f"{label} artifact path is not canonical: {item.get('path')}")
        if item.get("encoding") not in {"utf-8", "binary"}:
            raise ValueError(f"{prefix}.encoding must be utf-8 or binary")
        sha256 = item.get("sha256")
        if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
            raise ValueError(f"{prefix}.sha256 must be sha256:<64 hex>")
        try:
            _, resolved = resolve_bound_file(root, normalized, f"{label} artifact")
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        if resolved in resolved_paths:
            raise ValueError(f"{label} duplicate resolved artifact path: {normalized}")
        resolved_paths.add(resolved)
        actual = file_sha256(resolved)
        if actual != sha256:
            raise ValueError(f"{label} artifact sha256 mismatch for {normalized}: expected {sha256}, got {actual}")
        entry = dict(item)
        entry["resolved"] = resolved
        if item["encoding"] == "utf-8":
            try:
                entry["lines"] = resolved.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise ValueError(f"{label} UTF-8 artifact is not decodable: {normalized}: {exc}") from None
        verified[normalized] = entry
    return verified


def verify_locator_reference(
    evidence: Any, artifacts: dict[str, dict[str, Any]], *, label: str,
) -> None:
    if not isinstance(evidence, dict) or set(evidence) != {"artifact", "locator", "observation"}:
        raise ValueError(f"{label} evidence must contain exactly artifact, locator, and observation")
    artifact = evidence.get("artifact")
    if artifact not in artifacts:
        raise ValueError(f"{label} evidence references an artifact outside the allowlist: {artifact}")
    entry = artifacts[artifact]
    if isinstance(entry, list):
        entry = {"encoding": "utf-8", "lines": entry}
    if entry.get("encoding") != "utf-8":
        raise ValueError(f"{label} evidence locator requires a UTF-8 artifact: {artifact}")
    locator = evidence.get("locator")
    if not isinstance(locator, dict) or set(locator) != {"start_line", "end_line"}:
        raise ValueError(f"{label} locator must contain exactly start_line and end_line")
    start = locator.get("start_line")
    end = locator.get("end_line")
    lines = entry.get("lines", [])
    if (
        not isinstance(start, int) or isinstance(start, bool)
        or not isinstance(end, int) or isinstance(end, bool)
        or start < 1 or end < start or end > len(lines)
    ):
        raise ValueError(f"{label} line locator is outside artifact bounds")
    if not any(line.strip() for line in lines[start - 1:end]):
        raise ValueError(f"{label} line locator resolves only to empty lines")
    if not isinstance(evidence.get("observation"), str) or not evidence["observation"].strip():
        raise ValueError(f"{label} observation must be a non-empty string")


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
        if not isinstance(check, dict) or set(check) != {"id", "pass", "evidence", "notes", "uncertainty"}:
            raise ValueError(f"{prefix} fields do not match the transport shape")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError(f"{prefix}.id must be a non-empty string")
        if check_id in check_results:
            raise ValueError(f"duplicate grader check ID: {check_id}")
        if not isinstance(check.get("pass"), bool):
            raise ValueError(f"{prefix}.pass must be boolean")
        if not isinstance(check.get("notes"), str) or check.get("uncertainty") not in {"none", "low", "medium", "high"}:
            raise ValueError(f"{prefix} notes/uncertainty are invalid")
        evidence_items = check.get("evidence")
        if not isinstance(evidence_items, list):
            raise ValueError(f"{prefix}.evidence must be an array")
        for evidence in evidence_items:
            verify_locator_reference(evidence, artifacts, label=prefix)
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


def derive_run_fields(
    case: dict[str, Any], graders: dict[str, dict[str, Any]], grader_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    requirements = case["requirements"]

    def passed(requirement: dict[str, Any]) -> bool:
        return bool(grader_results[requirement["grader_id"]]["checks"][requirement["check_id"]])

    def dimension_score(dimension: str) -> int | None:
        selected = [requirement for requirement in requirements if requirement["dimension"] == dimension]
        if not selected:
            return None
        if all("weight" in requirement for requirement in selected):
            denominator = sum(float(requirement["weight"]) for requirement in selected)
            raw = sum(float(requirement["weight"]) for requirement in selected if passed(requirement)) / denominator * 100
        else:
            raw = sum(1 for requirement in selected if passed(requirement)) / len(selected) * 100
        return math.floor(raw + 0.5)

    outcome = [requirement for requirement in requirements if requirement["dimension"] == "outcome" and requirement["required"]]
    safety = [requirement for requirement in requirements if requirement["dimension"] == "safety"]
    failed_safety = [requirement for requirement in safety if not passed(requirement)]
    hard_failures = sorted(
        requirement["id"] for requirement in requirements
        if requirement["required"] and not passed(requirement)
        and graders[requirement["grader_id"]]["hard_gate"] is True
    )
    return {
        "task_pass": all(passed(requirement) for requirement in outcome),
        "process_score": dimension_score("process"),
        "quality_score": dimension_score("quality"),
        "safety_pass": not failed_safety,
        "critical_safety_incidents": sum(requirement.get("severity") == "critical" for requirement in failed_safety),
        "unauthorized_side_effects": sum(
            requirement.get("safety_kind") == "unauthorized_action" for requirement in failed_safety
        ),
        "hard_gate_failures": hard_failures,
    }


def compute_grader_digest(grader: dict[str, Any], spec_root: Path) -> str:
    binding: dict[str, Any] = {"declaration": grader}
    if grader["type"] == "deterministic":
        verifier = grader["verifier"]
        try:
            _, verifier_path = resolve_bound_file(spec_root, verifier["path"], "deterministic verifier")
        except FileNotFoundError:
            raise
        actual = file_sha256(verifier_path)
        if actual != verifier["sha256"]:
            raise ValueError(
                f"deterministic verifier sha256 mismatch: expected {verifier['sha256']}, got {actual}"
            )
    else:
        bound_files = {}
        for field in ("prompt_path", "schema_path"):
            _, path = resolve_bound_file(spec_root, grader[field], f"model rubric {field}")
            bound_files[field] = file_sha256(path)
        binding["bound_files"] = bound_files
    return canonical_sha256(binding)


def verify_fixture(case: dict[str, Any], artifacts_root: Path) -> str:
    fixture = case["fixture"]
    _, manifest_path = resolve_bound_file(artifacts_root, fixture["manifest"], "fixture manifest")
    actual_manifest_hash = file_sha256(manifest_path)
    if actual_manifest_hash != fixture["sha256"]:
        raise ValueError(
            f"fixture manifest sha256 mismatch: expected {fixture['sha256']}, got {actual_manifest_hash}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"fixture manifest is not valid UTF-8 JSON: {exc}") from None
    if not isinstance(manifest, dict) or set(manifest) != {"artifacts"}:
        raise ValueError("fixture manifest must contain exactly artifacts")
    verify_artifacts(manifest["artifacts"], manifest_path.parent, "fixture")
    return actual_manifest_hash


def resolve_candidate_package_hash(spec: dict[str, Any], spec_path: Path) -> str:
    """Compute the candidate provenance binding once per analyzer invocation."""
    candidate_path = Path(spec["target"]["candidate_path"])
    if not candidate_path.is_absolute():
        candidate_path = spec_path.parent.resolve() / candidate_path
    try:
        package_hash = "sha256:" + compute_inventory_hash(candidate_path)
    except (OSError, ValueError) as exc:
        raise ValueError(f"candidate package inventory failed: {exc}") from None
    return package_hash


def derive_verified_run(
    row: dict[str, Any], spec: dict[str, Any], spec_path: Path,
    case: dict[str, Any], variant: dict[str, Any], candidate_package_hash: str,
) -> dict[str, Any]:
    spec_root = spec_path.parent.resolve()
    artifacts_reference, artifacts_root = resolve_bound_dir(
        spec_root, spec["artifacts"]["root"], "spec artifacts root"
    )
    artifact_dir_reference = normalize_relative_path(row["artifact_dir"], "run artifact_dir")
    if artifact_dir_reference != row["artifact_dir"]:
        raise ValueError("run artifact_dir is not canonical")
    _, artifact_dir = resolve_bound_dir(artifacts_root, artifact_dir_reference, "run artifact_dir")
    receipt_reference = normalize_relative_path(row["receipt"]["path"], "receipt path")
    if receipt_reference != row["receipt"]["path"]:
        raise ValueError("receipt path is not canonical")
    _, receipt_path = resolve_bound_file(artifact_dir, receipt_reference, "receipt")
    actual_receipt_hash = file_sha256(receipt_path)
    if actual_receipt_hash != row["receipt"]["sha256"]:
        raise ValueError(
            f"receipt sha256 mismatch: expected {row['receipt']['sha256']}, got {actual_receipt_hash}"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"receipt is not valid UTF-8 JSON: {exc}") from None
    receipt_fields = {
        "schema_version", "run", "artifacts", "routing", "usage",
        "context_usage", "grader_outputs",
    }
    if not isinstance(receipt, dict) or set(receipt) != receipt_fields:
        raise ValueError("receipt fields do not match receipt v1")
    if receipt.get("schema_version") != 1:
        raise ValueError("receipt schema_version must equal 1")

    run = receipt.get("run")
    run_fields = {
        "run_id", "case_id", "variant", "repeat", "valid", "error_type",
        "invalid_reason", "provenance",
    }
    if not isinstance(run, dict) or set(run) != run_fields:
        raise ValueError("receipt run fields do not match receipt v1")
    for field in ("run_id", "case_id", "variant", "repeat"):
        if run.get(field) != row[field]:
            raise ValueError(f"receipt/index identity mismatch for {field}")
    if not isinstance(run.get("valid"), bool):
        raise ValueError("receipt run.valid must be boolean")
    error_type = run.get("error_type")
    invalid_reason = run.get("invalid_reason")
    if error_type is not None and (not isinstance(error_type, str) or not error_type.strip()):
        raise ValueError("receipt run.error_type must be null or a non-empty string")
    if invalid_reason is not None and (not isinstance(invalid_reason, str) or not invalid_reason.strip()):
        raise ValueError("receipt run.invalid_reason must be null or a non-empty string")
    if run["valid"] is False and (error_type != "evaluation_apparatus" or not invalid_reason):
        raise ValueError("invalid run requires error_type=evaluation_apparatus and invalid_reason")
    if run["valid"] is True and error_type == "evaluation_apparatus":
        raise ValueError("valid run cannot claim an evaluation_apparatus failure")

    artifacts = verify_artifacts(receipt["artifacts"], artifact_dir, "receipt")
    fixture_hash = verify_fixture(case, artifacts_root)
    selected_requirements = case["requirements"]
    selected_grader_ids = sorted({requirement["grader_id"] for requirement in selected_requirements})
    graders = {grader["id"]: grader for grader in spec["graders"]}
    grader_digests = {
        grader_id: compute_grader_digest(graders[grader_id], spec_root)
        for grader_id in selected_grader_ids
    }
    grader_set_hash = canonical_sha256([
        {"id": grader_id, "sha256": grader_digests[grader_id]}
        for grader_id in selected_grader_ids
    ])

    package_hash = variant["package_hash"]
    if variant["role"] == "candidate":
        package_hash = candidate_package_hash
        if package_hash != spec["target"]["candidate_hash"] or package_hash != variant["package_hash"]:
            raise ValueError("candidate package inventory hash mismatch")

    provenance = run.get("provenance")
    provenance_fields = {
        "spec_sha256", "case_sha256", "grader_set_sha256", "environment_sha256",
        "package_hash", "fixture_hash", "catalog_hash", "treatment_hash",
    }
    if not isinstance(provenance, dict) or set(provenance) != provenance_fields:
        raise ValueError("receipt provenance fields do not match receipt v1")
    expected_provenance = {
        "spec_sha256": file_sha256(spec_path),
        "case_sha256": canonical_sha256(case),
        "grader_set_sha256": grader_set_hash,
        "environment_sha256": canonical_sha256(spec["environment"]),
        "package_hash": package_hash,
        "fixture_hash": fixture_hash,
        "catalog_hash": variant["catalog_hash"],
        "treatment_hash": variant["treatment_hash"],
    }
    for field, expected in expected_provenance.items():
        if provenance.get(field) != expected:
            raise ValueError(f"receipt provenance {field} mismatch")

    routing = receipt.get("routing")
    routing_fields = {
        "retrieved_skill_ids", "selected_skill_id", "skill_body_loaded",
        "resources_loaded", "skill_incorporated", "skill_applied", "evidence",
    }
    if not isinstance(routing, dict) or set(routing) != routing_fields:
        raise ValueError("receipt routing fields do not match receipt v1")
    for field in ("retrieved_skill_ids", "resources_loaded"):
        values = routing.get(field)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) or not value.strip() for value in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"receipt routing.{field} must be a unique string array")
    if routing.get("selected_skill_id") is not None and (
        not isinstance(routing["selected_skill_id"], str) or not routing["selected_skill_id"].strip()
    ):
        raise ValueError("receipt routing.selected_skill_id must be null or a non-empty string")
    for field in ("skill_body_loaded", "skill_incorporated", "skill_applied"):
        if not isinstance(routing.get(field), bool):
            raise ValueError(f"receipt routing.{field} must be boolean")
    routing_evidence = routing.get("evidence")
    if not isinstance(routing_evidence, list):
        raise ValueError("receipt routing.evidence must be an array")
    for evidence in routing_evidence:
        verify_locator_reference(evidence, artifacts, label="routing")

    usage = receipt.get("usage")
    usage_fields = {"tokens_in", "tokens_out", "latency_ms", "tool_calls", "retries", "evidence"}
    if not isinstance(usage, dict) or set(usage) != usage_fields:
        raise ValueError("receipt usage fields do not match receipt v1")
    for field in usage_fields - {"evidence"}:
        value = usage.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"receipt usage.{field} must be a finite non-negative number")
    usage_evidence = usage.get("evidence")
    if not isinstance(usage_evidence, list):
        raise ValueError("receipt usage.evidence must be an array")
    for evidence in usage_evidence:
        verify_locator_reference(evidence, artifacts, label="usage")

    context_usage = receipt.get("context_usage")
    if (
        not isinstance(context_usage, dict)
        or set(context_usage) != {"measurement_source", "components"}
        or context_usage.get("measurement_source") not in {"host_receipt", "replay_manifest", "paired_total_only"}
        or not isinstance(context_usage.get("components"), list)
    ):
        raise ValueError("receipt context_usage fields are invalid")
    measurement_source = context_usage["measurement_source"]
    components = context_usage["components"]
    if measurement_source == "paired_total_only" and components:
        raise ValueError("paired_total_only context_usage requires empty components")
    verified_components: list[dict[str, Any]] = []
    component_artifacts: set[str] = set()
    dynamic_sources: set[str] = set()
    static_content_seen: set[tuple[str, str]] = set()
    context_efficiency = {field: 0 for field in CONTEXT_EFFICIENCY_FIELDS}
    for index, component in enumerate(components):
        if not isinstance(component, dict) or set(component) != {
            "kind", "source_path", "artifact", "tokens",
        }:
            raise ValueError(f"context component {index} fields do not match receipt v1")
        kind = component.get("kind")
        source_path = component.get("source_path")
        artifact = component.get("artifact")
        tokens = component.get("tokens")
        if kind not in CONTEXT_COMPONENT_KINDS:
            raise ValueError(f"context component {index} kind is invalid")
        if not isinstance(source_path, str) or not source_path.strip():
            raise ValueError(f"context component {index} source_path must be non-empty")
        if kind in STATIC_CONTEXT_KINDS:
            if normalize_relative_path(source_path, f"context component {index} source_path") != source_path:
                raise ValueError(f"context component {index} source_path is not canonical")
        else:
            expected_prefix = "protocol:" if kind == "protocol_output" else "failed-command:"
            if not DYNAMIC_CONTEXT_SOURCE.fullmatch(source_path) or not source_path.startswith(expected_prefix):
                raise ValueError(f"context component {index} dynamic source_path is invalid")
            if source_path in dynamic_sources:
                raise ValueError("dynamic context source paths must be unique")
            dynamic_sources.add(source_path)
        if not isinstance(artifact, str) or artifact not in artifacts:
            raise ValueError(f"context component {index} artifact is not allowlisted")
        if artifact in component_artifacts:
            raise ValueError("context component artifacts must be unique")
        component_artifacts.add(artifact)
        artifact_item = artifacts[artifact]
        if artifact_item["encoding"] != "utf-8":
            raise ValueError("context components must reference UTF-8 artifacts")
        if measurement_source == "host_receipt":
            if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
                raise ValueError("host_receipt context components require non-negative integer tokens")
        elif tokens is not None:
            raise ValueError("replay_manifest context component tokens must be null")
        byte_count = artifact_item["resolved"].stat().st_size
        content_sha256 = file_sha256(artifact_item["resolved"])
        if kind in STATIC_CONTEXT_KINDS:
            identity = (source_path, content_sha256)
            field = "repeated_static_content_bytes" if identity in static_content_seen else "unique_static_content_bytes"
            static_content_seen.add(identity)
        elif kind == "protocol_output":
            field = "protocol_output_bytes"
        else:
            field = "failed_command_output_bytes"
        context_efficiency[field] += byte_count
        verified_components.append({
            "kind": kind,
            "source_path": source_path,
            "artifact": artifact,
            "bytes": byte_count,
            "tokens": tokens if measurement_source == "host_receipt" else None,
        })
    if measurement_source != "paired_total_only":
        body_present = any(item["kind"] == "body" for item in verified_components)
        if body_present != routing["skill_body_loaded"]:
            raise ValueError("context body components contradict routing.skill_body_loaded")
        reference_sources = {
            item["source_path"] for item in verified_components if item["kind"] == "reference"
        }
        if reference_sources != set(routing["resources_loaded"]):
            raise ValueError("context reference sources do not match routing.resources_loaded")
    derived_context_usage = {
        "measurement_source": measurement_source,
        "attributed": measurement_source in {"host_receipt", "replay_manifest"} and bool(verified_components),
        "bytes": sum(item["bytes"] for item in verified_components),
        "tokens": (
            sum(item["tokens"] for item in verified_components)
            if measurement_source == "host_receipt" else None
        ),
        "components": verified_components,
        **context_efficiency,
    }
    if derived_context_usage["bytes"] != sum(context_efficiency.values()):
        raise ValueError("context byte attribution does not conserve total skill context bytes")

    grader_outputs = receipt.get("grader_outputs")
    if not isinstance(grader_outputs, list):
        raise ValueError("receipt grader_outputs must be an array")
    output_ids = [item.get("grader_id") for item in grader_outputs if isinstance(item, dict)]
    if len(output_ids) != len(grader_outputs) or len(set(output_ids)) != len(output_ids):
        raise ValueError("receipt grader_outputs contains a duplicate or malformed grader")
    if set(output_ids) != set(selected_grader_ids):
        raise ValueError("receipt grader_outputs do not match the case-derived grader set")

    deterministic_output_paths: set[str] = set()
    for item in grader_outputs:
        grader = graders[item["grader_id"]]
        if grader["type"] != "deterministic":
            continue
        if set(item) != {"grader_id", "invocation"} or not isinstance(item.get("invocation"), dict):
            raise ValueError(f"selected deterministic grader {item['grader_id']} requires invocation")
        invocation = item["invocation"]
        for field in ("stdout_artifact", "stderr_artifact"):
            reference = invocation.get(field)
            if not isinstance(reference, str):
                raise ValueError(f"deterministic invocation {field} must be a canonical artifact path")
            deterministic_output_paths.add(reference)

    expected_input_paths = sorted(set(artifacts) - deterministic_output_paths)
    expected_artifact_root = PurePosixPath(artifacts_reference, artifact_dir_reference).as_posix()
    grader_results: dict[str, dict[str, Any]] = {}
    any_grader_failure = False
    for item in grader_outputs:
        grader_id = item["grader_id"]
        grader = graders[grader_id]
        requirements = [
            requirement for requirement in selected_requirements
            if requirement["grader_id"] == grader_id
        ]
        if grader["type"] == "deterministic":
            invocation = item["invocation"]
            invocation_fields = {
                "grader_sha256", "selected_check_ids", "artifact_root", "input_artifacts",
                "stdout_artifact", "stderr_artifact", "exit_code",
            }
            if set(invocation) != invocation_fields:
                raise ValueError("deterministic invocation fields do not match receipt v1")
            if invocation["grader_sha256"] != grader_digests[grader_id]:
                raise ValueError("deterministic invocation grader_sha256 mismatch")
            expected_checks = sorted(requirement["check_id"] for requirement in requirements)
            if invocation.get("selected_check_ids") != expected_checks:
                raise ValueError("deterministic invocation selected_check_ids mismatch")
            if invocation.get("artifact_root") != expected_artifact_root:
                raise ValueError("invocation artifact_root mismatch")
            input_items = invocation.get("input_artifacts")
            if not isinstance(input_items, list):
                raise ValueError("deterministic invocation input_artifacts must be an array")
            input_paths: list[str] = []
            for input_item in input_items:
                if not isinstance(input_item, dict) or set(input_item) != {"path", "sha256"}:
                    raise ValueError("deterministic input artifact must contain exactly path and sha256")
                path = input_item.get("path")
                if path == receipt_reference or path in deterministic_output_paths:
                    raise ValueError("input_artifacts must not reference receipt or grader outputs")
                if path not in artifacts or input_item.get("sha256") != artifacts[path]["sha256"]:
                    raise ValueError("deterministic input artifact is not bound by the receipt allowlist")
                input_paths.append(path)
            if input_paths != sorted(input_paths) or input_paths != expected_input_paths:
                raise ValueError("invocation input_artifacts do not equal the frozen input set")
            stdout_reference = invocation["stdout_artifact"]
            stderr_reference = invocation["stderr_artifact"]
            if stdout_reference == stderr_reference:
                raise ValueError("deterministic stdout_artifact and stderr_artifact must differ")
            if stdout_reference not in artifacts or artifacts[stdout_reference]["encoding"] != "utf-8":
                raise ValueError("deterministic stdout_artifact must be an allowlisted UTF-8 artifact")
            if stderr_reference not in artifacts:
                raise ValueError("deterministic stderr_artifact must be allowlisted")
            try:
                output = json.loads(artifacts[stdout_reference]["resolved"].read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"deterministic stdout is not valid UTF-8 JSON: {exc}") from None
            validated = validate_grader_output(output, requirements, artifacts)
            exit_code = invocation.get("exit_code")
            if not isinstance(exit_code, int) or isinstance(exit_code, bool):
                raise ValueError("deterministic invocation exit_code must be an integer")
            if (exit_code in grader["verifier"]["pass_exit_codes"]) != validated["overall_pass"]:
                raise ValueError("deterministic exit_code/pass result contradiction")
        else:
            if set(item) != {"grader_id", "output"}:
                raise ValueError("model_rubric grader output must contain exactly grader_id and output")
            validated = validate_grader_output(item["output"], requirements, artifacts)
        grader_results[grader_id] = validated
        any_grader_failure = any_grader_failure or validated["grader_failure"]

    if any_grader_failure and run["valid"] is True:
        raise ValueError("grader failure requires run.valid=false")
    if run["valid"] is False and not any_grader_failure:
        raise ValueError("evaluation_apparatus invalid run requires a grader failure result")
    derived = derive_run_fields(case, graders, grader_results) if run["valid"] else {
        "task_pass": None,
        "process_score": None,
        "quality_score": None,
        "safety_pass": None,
        "critical_safety_incidents": 0,
        "unauthorized_side_effects": 0,
        "hard_gate_failures": [],
    }
    profile = f"{variant['role']}/{variant['mode']}"
    return {
        "run_id": run["run_id"],
        "case_id": run["case_id"],
        "variant": run["variant"],
        "repeat": run["repeat"],
        "artifact_dir": row["artifact_dir"],
        "valid": run["valid"],
        "error_type": error_type,
        "invalid_reason": invalid_reason,
        "split": case["split"],
        "tags": list(case["tags"]),
        "should_trigger": case["should_trigger"],
        "routing_evaluable": variant["mode"] == "natural_routing" and profile in case["applicable_variant_profiles"],
        "retrieved_skill_ids": list(routing["retrieved_skill_ids"]),
        "selected_skill_id": routing["selected_skill_id"],
        "skill_body_loaded": routing["skill_body_loaded"],
        "resources_loaded": list(routing["resources_loaded"]),
        "skill_incorporated": routing["skill_incorporated"],
        "skill_applied": routing["skill_applied"],
        "tokens_in": usage["tokens_in"],
        "tokens_out": usage["tokens_out"],
        "latency_ms": usage["latency_ms"],
        "tool_calls": usage["tool_calls"],
        "retries": usage["retries"],
        "context_usage": derived_context_usage,
        "graders_run": selected_grader_ids,
        "provenance": provenance,
        **derived,
    }


def verify_receipt(
    row: dict[str, Any], spec: dict[str, Any], spec_path: Path,
    case: dict[str, Any], variant: dict[str, Any], candidate_package_hash: str,
) -> dict[str, Any]:
    try:
        record = derive_verified_run(
            row, spec, spec_path, case, variant, candidate_package_hash
        )
    except FileNotFoundError as exc:
        return {"status": "incomplete", "issue": str(exc), "record": None}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "invalid", "issue": str(exc), "record": None}
    return {"status": "complete", "issue": None, "record": record}


def verify_manual_review_receipt(
    reference: str, spec: dict[str, Any], spec_path: Path,
) -> dict[str, Any]:
    spec_root = spec_path.parent.resolve()
    _, artifacts_root = resolve_bound_dir(
        spec_root, spec["artifacts"]["root"], "spec artifacts root"
    )
    normalized = normalize_relative_path(reference, "manual review receipt path")
    if normalized != reference:
        raise ValueError("manual review receipt path is not canonical")
    lexical_receipt = artifacts_root / normalized
    if lexical_receipt.is_symlink():
        raise ValueError("manual review receipt must not be a symlink")
    _, receipt_path = resolve_bound_file(
        artifacts_root, normalized, "manual review receipt"
    )
    receipt_sha256 = file_sha256(receipt_path)
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"manual review receipt is not valid UTF-8 JSON: {exc}") from None
    if not isinstance(receipt, dict) or set(receipt) != {
        "reviewer_role", "evidence", "decision", "signature",
    }:
        raise ValueError("manual review receipt fields do not match the exact contract")

    config = spec.get("manual_review")
    if not isinstance(config, dict):
        raise ValueError("manual review receipt requires a spec.manual_review declaration")
    if receipt.get("reviewer_role") != config.get("reviewer_role"):
        raise ValueError("manual review reviewer_role mismatch")
    if receipt.get("decision") not in {"approve", "hold", "reject"}:
        raise ValueError("manual review decision must be approve, hold, or reject")
    if not isinstance(receipt.get("signature"), str) or not receipt["signature"].strip():
        raise ValueError("manual review signature must be non-empty")

    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("manual review evidence must be a non-empty array")
    evidence_types: list[str] = []
    verified_evidence: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"type", "artifact", "sha256"}:
            raise ValueError("manual review evidence item fields do not match the exact contract")
        evidence_type = item.get("type")
        artifact = item.get("artifact")
        if not isinstance(evidence_type, str) or not evidence_type.strip():
            raise ValueError("manual review evidence type must be non-empty")
        if not isinstance(artifact, str):
            raise ValueError("manual review evidence artifact must be a canonical relative path")
        normalized_artifact = normalize_relative_path(artifact, "manual review evidence artifact")
        if normalized_artifact != artifact:
            raise ValueError("manual review evidence artifact path is not canonical")
        _, evidence_path = resolve_bound_file(
            artifacts_root, normalized_artifact, "manual review evidence artifact"
        )
        actual_sha256 = file_sha256(evidence_path)
        if item.get("sha256") != actual_sha256:
            raise ValueError("manual review evidence sha256 mismatch")
        evidence_types.append(evidence_type)
        verified_evidence.append({
            "type": evidence_type,
            "artifact": normalized_artifact,
            "sha256": actual_sha256,
        })
    if len(set(evidence_types)) != len(evidence_types):
        raise ValueError("manual review evidence types must be unique")
    expected_types = config.get("required_evidence")
    if not isinstance(expected_types, list) or set(evidence_types) != set(expected_types):
        raise ValueError("manual review evidence types do not match required_evidence")
    return {
        "required": config.get("required") is True,
        "status": "complete",
        "reviewer_role": receipt["reviewer_role"],
        "evidence": verified_evidence,
        "decision": receipt["decision"],
        "signature_attested": True,
        "signature_verification": "not_performed",
        "receipt_path": normalized,
        "receipt_sha256": receipt_sha256,
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
        return {"status": "not_evaluable", "reason": "target skill ID is unavailable", "n": len(rows)}
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
            "n": len(rows),
            "missing": missing[:100],
            "bad_types": bad_types[:100],
        }

    positives = [row for row in rows if row["should_trigger"]]
    negatives = [row for row in rows if not row["should_trigger"]]

    def retrieved(row: dict[str, Any]) -> bool:
        return target_skill_id in row["retrieved_skill_ids"]

    def selected(row: dict[str, Any]) -> bool:
        return row["selected_skill_id"] == target_skill_id

    tp = sum(1 for row in rows if row["should_trigger"] and selected(row))
    fn = sum(1 for row in rows if row["should_trigger"] and not selected(row))
    fp = sum(1 for row in rows if not row["should_trigger"] and selected(row))
    tn = sum(1 for row in rows if not row["should_trigger"] and not selected(row))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None

    reciprocal_ranks = []
    for row in positives:
        try:
            reciprocal_ranks.append(1.0 / (row["retrieved_skill_ids"].index(target_skill_id) + 1))
        except ValueError:
            reciprocal_ranks.append(0.0)

    failure_counts: Counter[str] = Counter()
    for row in rows:
        if row["should_trigger"]:
            if not retrieved(row):
                failure_counts["retrieval_miss"] += 1
            elif not selected(row):
                failure_counts["selection_miss"] += 1
            elif not row["skill_body_loaded"]:
                failure_counts["body_load_miss"] += 1
            elif not row["skill_incorporated"]:
                failure_counts["incorporation_miss"] += 1
            elif not row["skill_applied"]:
                failure_counts["application_miss"] += 1
        else:
            if selected(row):
                failure_counts["false_selection"] += 1
            if row["skill_body_loaded"]:
                failure_counts["false_body_load"] += 1
            if row["skill_applied"]:
                failure_counts["false_application"] += 1

    retrieval_positive = proportion(retrieved(row) for row in positives)
    retrieval_negative = proportion(retrieved(row) for row in negatives)
    selection_positive = proportion(selected(row) for row in positives)
    selection_negative = proportion(selected(row) for row in negatives)
    body_positive = proportion(row["skill_body_loaded"] for row in positives)
    body_negative = proportion(row["skill_body_loaded"] for row in negatives)
    incorporated_positive = proportion(row["skill_incorporated"] for row in positives)
    applied_positive = proportion(row["skill_applied"] for row in positives)
    applied_negative = proportion(row["skill_applied"] for row in negatives)

    return {
        "status": "complete",
        "target_skill_id": target_skill_id,
        "n": len(rows),
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
        "resources_loaded": continuous(len(row["resources_loaded"]) for row in rows),
        "stage_failure_counts": dict(sorted(failure_counts.items())),
    }


def summarize_variant(
    records: list[dict[str, Any]],
    target_skill_id: str | None,
    routing_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    valid = [record for record in records if record.get("valid") is True]
    invalid = [record for record in records if record.get("valid") is not True]
    task_values = [record["task_pass"] for record in valid if isinstance(record.get("task_pass"), bool)]
    safety_values = [record["safety_pass"] for record in valid if isinstance(record.get("safety_pass"), bool)]

    error_types = Counter(str(record.get("error_type")) for record in valid if record.get("error_type"))
    gate_failures: Counter[str] = Counter()
    for record in valid:
        for failure in record.get("hard_gate_failures", []) or []:
            gate_failures[str(failure)] += 1

    critical_values = [record["critical_safety_incidents"] for record in valid if isinstance(record.get("critical_safety_incidents"), (int, float))]
    critical = sum(critical_values) if len(critical_values) == len(valid) else None
    split_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tag_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in valid:
        split_records[str(record.get("split", "unspecified"))].append(record)
        for tag in record.get("tags", []) or []:
            tag_records[str(tag)].append(record)

    def pass_for(group: list[dict[str, Any]]) -> dict[str, Any]:
        return proportion(record["task_pass"] for record in group if isinstance(record.get("task_pass"), bool))

    numeric = {}
    for field in sorted(NUMERIC_FIELDS - {"critical_safety_incidents"}):
        numeric[field] = continuous(record[field] for record in valid if isinstance(record.get(field), (int, float)) and not isinstance(record.get(field), bool))

    split_summaries = {name: pass_for(group) for name, group in sorted(split_records.items())}
    tag_summaries = {name: pass_for(group) for name, group in sorted(tag_records.items())}
    slice_candidates = [
        {"kind": kind, "name": name, **summary}
        for kind, summaries in (("split", split_summaries), ("tag", tag_summaries))
        for name, summary in summaries.items()
        if summary["rate"] is not None
    ]
    worst_slice = min(slice_candidates, key=lambda item: (item["rate"], -item["n"], item["kind"], item["name"])) if slice_candidates else None

    return {
        "records": len(records),
        "valid_records": len(valid),
        "invalid_records": len(invalid),
        "task_pass": proportion(task_values),
        "safety_pass": proportion(safety_values),
        "safety_incident_rate": proportion(not value for value in safety_values),
        "critical_safety_incidents": critical,
        "critical_safety_incidents_n": len(critical_values),
        "routing": routing_summary(valid, target_skill_id, routing_case_ids),
        "numeric": numeric,
        "errors": dict(error_types.most_common()),
        "hard_gate_failures": dict(gate_failures.most_common()),
        "splits": split_summaries,
        "tags": tag_summaries,
        "worst_slice_task_pass": worst_slice,
    }


def paired_summary(
    records: list[dict[str, Any]],
    baseline: str,
    candidate: str,
    eligible_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    by_variant_key: dict[str, dict[tuple[str, int], dict[str, Any]]] = defaultdict(dict)
    duplicate_keys: list[str] = []
    for record in records:
        key = (record["case_id"], record["repeat"])
        if eligible_case_ids is not None and record["case_id"] not in eligible_case_ids:
            continue
        variant = record["variant"]
        if key in by_variant_key[variant]:
            duplicate_keys.append(f"{variant}:{key[0]}:{key[1]}")
        by_variant_key[variant][key] = record

    base_rows = by_variant_key.get(baseline, {})
    cand_rows = by_variant_key.get(candidate, {})
    shared = sorted(set(base_rows) & set(cand_rows))
    pairs = []
    excluded = Counter()
    for key in shared:
        base = base_rows[key]
        cand = cand_rows[key]
        if base.get("valid") is not True or cand.get("valid") is not True:
            excluded["invalid"] += 1
            continue
        if not isinstance(base.get("task_pass"), bool) or not isinstance(cand.get("task_pass"), bool):
            excluded["missing_task_pass"] += 1
            continue
        pairs.append((key, base, cand))

    wins = sum(1 for _, b, c in pairs if c["task_pass"] and not b["task_pass"])
    losses = sum(1 for _, b, c in pairs if not c["task_pass"] and b["task_pass"])
    tie_pass = sum(1 for _, b, c in pairs if c["task_pass"] and b["task_pass"])
    tie_fail = sum(1 for _, b, c in pairs if not c["task_pass"] and not b["task_pass"])
    base_values = [b["task_pass"] for _, b, _ in pairs]
    cand_values = [c["task_pass"] for _, _, c in pairs]
    field_types = {
        "task_pass": bool,
        "process_score": (int, float),
        "quality_score": (int, float),
        "safety_pass": bool,
    }
    case_difference_vectors: dict[str, list[float]] = {}
    missing_paired_fields: dict[str, int] = {}
    for field, expected_type in field_types.items():
        by_case: dict[str, list[float]] = defaultdict(list)
        missing = 0
        for key, base, cand in pairs:
            base_value = base.get(field)
            cand_value = cand.get(field)
            if expected_type is bool:
                valid_values = isinstance(base_value, bool) and isinstance(cand_value, bool)
            else:
                valid_values = (
                    isinstance(base_value, expected_type) and not isinstance(base_value, bool)
                    and isinstance(cand_value, expected_type) and not isinstance(cand_value, bool)
                )
            if not valid_values:
                missing += 1
                continue
            by_case[key[0]].append(float(cand_value) - float(base_value))
        case_difference_vectors[field] = [
            sum(values) / len(values)
            for _, values in sorted(by_case.items())
        ]
        missing_paired_fields[field] = missing
    base_rate = sum(base_values) / len(base_values) if base_values else None
    cand_rate = sum(cand_values) / len(cand_values) if cand_values else None

    both_pass = [(b, c) for _, b, c in pairs if b["task_pass"] and c["task_pass"]]
    efficiency_delta = {}
    for field in ("tokens_in", "tokens_out", "latency_ms", "tool_calls", "retries"):
        deltas = [float(c[field]) - float(b[field]) for b, c in both_pass if isinstance(b.get(field), (int, float)) and isinstance(c.get(field), (int, float))]
        efficiency_delta[field] = continuous(deltas)

    return {
        "baseline": baseline,
        "candidate": candidate,
        "shared_keys": len(shared),
        "paired_valid": len(pairs),
        "run_pair_count": len(pairs),
        "repeat_count": len({key[1] for key, _, _ in pairs}),
        "excluded": dict(excluded),
        "duplicate_variant_keys": duplicate_keys,
        "wins": wins,
        "losses": losses,
        "tie_pass": tie_pass,
        "tie_fail": tie_fail,
        "baseline_pass_rate": base_rate,
        "candidate_pass_rate": cand_rate,
        "absolute_pass_lift": cand_rate - base_rate if base_rate is not None and cand_rate is not None else None,
        "paired_task_pass_lift": cand_rate - base_rate if base_rate is not None and cand_rate is not None else None,
        "case_difference_vectors": case_difference_vectors,
        "missing_paired_fields": missing_paired_fields,
        "success_conditioned_efficiency_delta": efficiency_delta,
        "candidate_only_failures": [key[0] for key, b, c in pairs if not c["task_pass"] and b["task_pass"]],
        "candidate_only_wins": [key[0] for key, b, c in pairs if c["task_pass"] and not b["task_pass"]],
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
        "paired_case_count": count,
        "resampling_unit": "case_id",
    }


def paired_case_uncertainty(
    paired: dict[str, Any] | None,
    spec: dict[str, Any] | None,
    completeness: dict[str, Any] | None,
    field: str,
) -> dict[str, Any]:
    if spec is None:
        return {"status": "not_evaluable", "reason": "no frozen spec supplied"}
    if paired is None:
        return {"status": "not_evaluable", "reason": "baseline/candidate pair was not resolved"}
    if completeness and (
        completeness.get("missing_expected_keys_count", 0)
        or completeness.get("invalid_expected_keys_count", 0)
    ):
        return {"status": "not_evaluable", "reason": "run matrix evidence is missing or invalid"}
    if paired.get("duplicate_variant_keys"):
        return {"status": "not_evaluable", "reason": "duplicate pair keys are present"}
    if sum(paired.get("excluded", {}).values()):
        return {"status": "not_evaluable", "reason": "one or more shared pairs were excluded"}
    if paired.get("missing_paired_fields", {}).get(field):
        return {"status": "not_evaluable", "reason": f"paired {field} evidence is incomplete"}
    differences = paired.get("case_difference_vectors", {}).get(field)
    if not isinstance(differences, list) or len(differences) < 2:
        return {"status": "not_evaluable", "reason": "at least two distinct complete cases are required"}

    analysis = spec["analysis"]
    confidence = float(analysis["confidence_level"])
    iterations = int(analysis["paired_bootstrap_iterations"])
    seed = int(spec["environment"]["random_seed"])
    summary = summarize_case_differences(
        differences,
        confidence_level=confidence,
        bootstrap_iterations=iterations,
        random_seed=seed,
    )
    return {
        "status": "complete",
        "method": "case_cluster_percentile_bootstrap",
        "estimand": "candidate_task_pass_rate_minus_baseline_task_pass_rate",
        "confidence_level": confidence,
        "iterations": iterations,
        "random_seed": seed,
        "run_pair_count": paired["run_pair_count"],
        "repeat_count": paired["repeat_count"],
        **summary,
    }


def load_spec(path: Path) -> dict[str, Any]:
    value = load_contract_json(path)
    errors: list[str] = []
    warnings: list[str] = []
    check_spec(value, errors, warnings)
    if errors:
        raise ValueError("invalid evaluation spec: " + "; ".join(errors))
    return value


def infer_variant(
    spec: dict[str, Any] | None,
    preferred: str,
    role: str,
    mode: str,
    available: set[str],
) -> str | None:
    if preferred in available:
        return preferred
    if spec:
        variants = spec.get("variants")
        for variant in variants if isinstance(variants, list) else []:
            if (
                isinstance(variant, dict)
                and variant.get("role") == role
                and variant.get("mode") == mode
                and variant.get("id") in available
            ):
                return str(variant["id"])
    return None


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
    efficiency_values = {field: [] for field in CONTEXT_EFFICIENCY_FIELDS}
    for row in attributed_rows:
        context = row["context_usage"]
        values = [context.get(field) for field in CONTEXT_EFFICIENCY_FIELDS]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values):
            raise ValueError("context efficiency fields must be non-negative integers")
        if context.get("bytes") != sum(values):
            raise ValueError("context efficiency fields do not conserve total skill context bytes")
        for field, value in zip(CONTEXT_EFFICIENCY_FIELDS, values, strict=True):
            efficiency_values[field].append(value)
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
        "planned_rows": planned,
        "attributed_rows": attributed,
        "attribution_rate": coverage,
        "bytes_p95": nearest_rank(byte_values, 0.95) if complete else None,
        "tokens_p95": nearest_rank([float(value) for value in token_values], 0.95) if token_complete else None,
        "measurement_source_counts": dict(sorted(sources.items())),
        "component_bytes": dict(sorted(kind_bytes.items())),
        "component_tokens": dict(sorted(kind_tokens.items())) if token_complete else None,
        "context_efficiency": context_efficiency,
    }


def summarize_prior_skill_context(
    records: list[dict[str, Any]], cases_by_id: dict[str, dict[str, Any]],
    spec: dict[str, Any], repeats: int, candidate_summary: dict[str, Any],
) -> dict[str, Any] | None:
    """Return a prior comparison only when the spec declares a prior natural arm."""
    prior_ids = [
        variant["id"] for variant in spec["variants"]
        if variant["role"] == "prior" and variant["mode"] == "natural_routing"
    ]
    if not prior_ids:
        return None
    result: dict[str, Any] = {
        "prior_skill_context": None,
        "candidate_minus_prior_bytes_p95": None,
    }
    candidate_ids = [
        variant["id"] for variant in spec["variants"]
        if variant["role"] == "candidate" and variant["mode"] == "natural_routing"
    ]
    if len(prior_ids) != 1 or len(candidate_ids) != 1:
        return result

    prior_summary = summarize_skill_context(
        records, cases_by_id, spec, repeats, role="prior", mode="natural_routing"
    )
    result["prior_skill_context"] = prior_summary
    if candidate_summary.get("attribution_rate") != 1 or prior_summary.get("attribution_rate") != 1:
        return result

    candidate_id, prior_id = candidate_ids[0], prior_ids[0]
    candidate_profile = "candidate/natural_routing"
    prior_profile = "prior/natural_routing"
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
            or candidate_row.get("task_pass") is not True
            or prior_row.get("task_pass") is not True
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
    benefit_gate_status: str,
    guardrail_statuses: list[str],
    protected_outcome_failures: int,
    material_harm: bool,
    candidate_hard_failures: int,
) -> str:
    if level in {"L0", "L1"}:
        return "not_applicable"
    if evidence_status != "complete":
        return "inconclusive"
    if (
        candidate_hard_failures > 0
        or material_harm
        or protected_outcome_failures > 0
        or "fail" in guardrail_statuses
    ):
        return "not_supported"
    if benefit_gate_status == "fail":
        return "not_supported"
    if benefit_gate_status == "pass" and all(status == "pass" for status in guardrail_statuses):
        return "supported"
    return "inconclusive"


def derive_final_authority_status(
    *,
    usefulness_status: str,
    manual_gate_passed: bool,
    candidate_hard_failures: int,
    blocking_observations: list[str],
) -> str:
    if (
        usefulness_status == "supported"
        and manual_gate_passed
        and candidate_hard_failures == 0
        and not blocking_observations
    ):
        return "eligible"
    return "blocked"


def summarize_candidate_hard_failures(
    hard_failures_by_variant: dict[str, int],
    candidate_variant_ids: set[str],
) -> tuple[int, list[str]]:
    counts = {
        variant_id: hard_failures_by_variant.get(variant_id, 0)
        for variant_id in sorted(candidate_variant_ids)
        if hard_failures_by_variant.get(variant_id, 0)
    }
    total = sum(counts.values())
    blocking = [
        f"{variant_id}: {count} case-level hard grader failure(s)"
        for variant_id, count in counts.items()
    ]
    return total, blocking


def derive_decision_signal(level: str, usefulness_status: str) -> str:
    return "diagnostic_complete" if level == "L1" else f"usefulness_{usefulness_status}"


def decision_status_text(report: dict[str, Any]) -> str:
    return (
        f"evidence_status={report['evidence_status']} "
        f"usefulness_status={report['usefulness_status']} "
        f"final_authority_status={report['final_authority_status']} "
        f"decision_signal={report['decision_signal']}"
    )


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
) -> float | None:
    if metric == "paired_task_pass_lift":
        value = None
        if paired and not paired["duplicate_variant_keys"] and not any(paired["excluded"].values()):
            value = paired.get("paired_task_pass_lift")
        return float(value) if value is not None else None
    if metric == "paired_case_count":
        interval = paired.get("case_intervals", {}).get("task_pass") if paired else None
        value = interval.get("paired_case_count") if interval and interval.get("status") == "complete" else None
        return float(value) if value is not None else None
    lower_bound_metrics = {
        "paired_task_pass_lift_lower_bound": "task_pass",
        "paired_process_score_lift_lower_bound": "process_score",
        "paired_quality_score_lift_lower_bound": "quality_score",
        "paired_safety_pass_lift_lower_bound": "safety_pass",
    }
    if metric in lower_bound_metrics:
        interval = paired.get("case_intervals", {}).get(lower_bound_metrics[metric]) if paired else None
        value = interval.get("lower") if interval and interval.get("status") == "complete" else None
        return float(value) if value is not None else None
    context_metrics = {
        "skill_context_attribution_rate": "attribution_rate",
        "skill_context_bytes_p95": "bytes_p95",
        "skill_context_tokens_p95": "tokens_p95",
    }
    if metric in context_metrics:
        value = context_summary.get(context_metrics[metric]) if context_summary else None
        return float(value) if value is not None else None
    efficiency_metrics = {
        "repeated_static_content_bytes_max": "repeated_static_content_bytes",
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


def compare_gate(observed: float, operator: str, expected: Any) -> bool | None:
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return None
    expected_value = float(expected)
    operations = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
    }
    function = operations.get(operator)
    return function(observed, expected_value) if function else None


def evaluate_hard_gates(
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
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    benefit_gate_id = spec.get("analysis", {}).get("usefulness_benefit_gate_id")
    interval_fields = {
        "paired_task_pass_lift_lower_bound": "task_pass",
        "paired_process_score_lift_lower_bound": "process_score",
        "paired_quality_score_lift_lower_bound": "quality_score",
        "paired_safety_pass_lift_lower_bound": "safety_pass",
    }
    for index, gate in enumerate(spec.get("hard_gates", [])):
        if not isinstance(gate, dict):
            results.append({"id": f"invalid-gate-{index}", "status": "not_evaluable", "reason": "gate is not an object"})
            continue
        metric = gate.get("metric")
        operator = gate.get("operator")
        expected = gate.get("value")
        observed = resolve_gate_metric(
            metric, spec, variant_summaries, records, candidate, paired, target_skill_id,
            prior, cases_by_id, repeats, context_summary,
        )
        reason = None
        if gate.get("id") == benefit_gate_id and metric in interval_fields:
            interval = paired.get("case_intervals", {}).get(interval_fields[metric]) if paired else None
            if not interval or interval.get("status") != "complete":
                status = "not_evaluable"
                reason = interval.get("reason", "benefit interval unavailable") if interval else "benefit interval unavailable"
            elif interval["lower"] >= float(expected):
                status = "pass"
            elif interval["upper"] < float(expected):
                status = "fail"
            else:
                status = "not_evaluable"
                reason = "benefit interval overlaps the declared threshold"
        else:
            comparison = compare_gate(observed, str(operator), expected) if observed is not None else None
            status = "pass" if comparison is True else "fail" if comparison is False else "not_evaluable"
            if observed is None:
                reason = "metric unavailable or incomplete in verified candidate runs"
        results.append({
            "id": gate.get("id", f"gate-{index}"),
            "metric": metric,
            "operator": operator,
            "threshold": expected,
            "observed": observed,
            "status": status,
            "reason": reason,
        })
    return results


def fmt_rate(value: Any) -> str:
    return "n/a" if value is None else f"{100 * float(value):.1f}%"


def fmt_num(value: Any, digits: int = 2) -> str:
    return "n/a" if value is None else f"{float(value):.{digits}f}"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        f"# Skill Evaluation Run Summary",
        "",
        f"- Records: {report['record_count']}",
        f"- Variants: {', '.join(report['variants'])}",
        f"- Decision status: `{decision_status_text(report)}`",
        "- This analyzer summary does not replace the frozen evaluation contract or manual evidence review.",
        "",
        "## Variant scorecard",
        "",
        "| Variant | Valid/All | Task pass | Routing P/R/F1 | Safety pass | Critical incidents | Run-declared gate failures |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in report["variants"]:
        data = report["variant_summaries"][name]
        routing = data["routing"]
        route_text = "/".join(fmt_rate(routing.get(key)) for key in ("precision", "recall", "f1"))
        critical = "n/a" if data["critical_safety_incidents"] is None else str(data["critical_safety_incidents"])
        lines.append(
            f"| {name} | {data['valid_records']}/{data['records']} | {fmt_rate(data['task_pass']['rate'])} | {route_text} | {fmt_rate(data['safety_pass']['rate'])} | {critical} | {sum(data['hard_gate_failures'].values())} |"
        )

    lines.extend(["", "## Routing stage diagnostics", ""])
    for name, data in report["variant_summaries"].items():
        routing = data["routing"]
        if routing.get("status") != "complete":
            lines.append(f"- `{name}`: `{routing.get('status', 'not_evaluable')}` — {routing.get('reason', 'no routing evidence')}")
            continue
        lines.append(
            f"- `{name}`: retrieval recall={fmt_rate(routing['retrieval']['positive_hit_rate']['rate'])}, "
            f"MRR={fmt_num(routing['retrieval']['mrr_on_positive'])}, "
            f"selection P/R/F1={fmt_rate(routing['precision'])}/"
            f"{fmt_rate(routing['recall'])}/{fmt_rate(routing['f1'])}, "
            f"body/incorporation/application recall="
            f"{fmt_rate(routing['body_load']['positive_rate']['rate'])}/"
            f"{fmt_rate(routing['incorporation']['positive_rate']['rate'])}/"
            f"{fmt_rate(routing['application']['positive_rate']['rate'])}, "
            f"false application={fmt_rate(routing['application']['negative_rate']['rate'])}; "
            f"stage failures={routing['stage_failure_counts']}"
        )

    lines.extend(["", "## Worst observed task-pass slice", ""])
    for name in report["variants"]:
        worst = report["variant_summaries"][name].get("worst_slice_task_pass")
        if worst:
            lines.append(f"- `{name}`: {worst['kind']} `{worst['name']}` = {fmt_rate(worst['rate'])} (n={worst['n']})")
        else:
            lines.append(f"- `{name}`: n/a")

    receipt_verification = report.get("receipt_verification")
    if receipt_verification:
        lines.extend([
            "",
            "## Receipt verification",
            "",
            f"- Status: `{receipt_verification['status']}`",
            f"- Checked runs: {receipt_verification['checked_runs']}",
            "- Identity, provenance, package, fixture, artifact, and grader bindings were recomputed locally.",
        ])

    completeness = report.get("run_matrix_completeness")
    if completeness:
        lines.extend([
            "",
            "## Run matrix completeness",
            "",
            f"- Declared variants: {completeness['declared_variant_count']}",
            f"- Expected full-plan keys: {completeness['expected_plan_keys']}",
            f"- Observed full-plan keys: {completeness['observed_plan_keys']}",
            f"- Valid full-plan keys: {completeness['valid_plan_keys']}",
            f"- Attribution-eligible cases: {completeness['attribution_case_count']}",
            f"- Observed selected-pair keys: {completeness['observed_selected_pair_keys']}/{completeness['expected_selected_pair_keys']}",
            f"- Missing expected keys: {completeness['missing_expected_keys_count']}",
            f"- Invalid expected keys: {completeness['invalid_expected_keys_count']}",
            f"- Timed-out expected keys: {completeness['timed_out_expected_keys_count']}",
        ])
        for variant, counts in completeness["by_variant"].items():
            lines.append(
                f"- `{variant}` planned/present/valid/invalid/timed-out/missing: "
                f"{counts['planned']}/{counts['present']}/{counts['valid']}/"
                f"{counts['invalid']}/{counts['timed_out']}/{counts['missing']}"
            )
        if completeness["missing_expected_keys"]:
            sample = ", ".join("/".join(map(str, key)) for key in completeness["missing_expected_keys"][:10])
            suffix = " …" if completeness["missing_expected_keys_count"] > 10 else ""
            lines.append(f"- Missing sample (`variant/case/repeat`): {sample}{suffix}")
        if completeness["invalid_expected_keys"]:
            sample = ", ".join("/".join(map(str, key)) for key in completeness["invalid_expected_keys"][:10])
            suffix = " …" if completeness["invalid_expected_keys_count"] > 10 else ""
            lines.append(f"- Invalid sample (`variant/case/repeat`): {sample}{suffix}")

    paired = report.get("paired")
    if paired:
        lines.extend([
            "",
            "## Paired comparison",
            "",
            f"- Baseline: `{paired['baseline']}`",
            f"- Candidate: `{paired['candidate']}`",
            f"- Valid pairs: {paired['paired_valid']} (shared keys: {paired['shared_keys']})",
            f"- Wins / losses / tie-pass / tie-fail: {paired['wins']} / {paired['losses']} / {paired['tie_pass']} / {paired['tie_fail']}",
            f"- Paired task-pass lift: {fmt_rate(paired['paired_task_pass_lift'])}",
            f"- Candidate-only wins: {', '.join(paired['candidate_only_wins']) or 'none'}",
            f"- Candidate-only failures: {', '.join(paired['candidate_only_failures']) or 'none'}",
        ])
        uncertainty = paired.get("case_intervals", {}).get("task_pass")
        if uncertainty and uncertainty.get("status") == "complete":
            lines.append(
                f"- {uncertainty['confidence_level']:.1%} case-cluster bootstrap interval: "
                f"[{uncertainty['lower']:.3f}, {uncertainty['upper']:.3f}] "
                f"(cases={uncertainty['paired_case_count']}, run pairs={uncertainty['run_pair_count']}, "
                f"iterations={uncertainty['iterations']}, seed={uncertainty['random_seed']})"
            )
        elif uncertainty:
            lines.append(f"- Paired uncertainty: not evaluable — {uncertainty.get('reason', 'unspecified')}")

    case_gate_evidence = report.get("case_gate_evidence")
    if case_gate_evidence:
        lines.extend([
            "",
            "## Case grader evidence",
            "",
            f"- Case-level hard failures by variant: `{json.dumps(case_gate_evidence['hard_failures_by_variant'], sort_keys=True)}`",
        ])

    manual_review = report.get("manual_review")
    if manual_review:
        evidence = manual_review.get("evidence", [])
        lines.extend([
            "",
            "## Manual review",
            "",
            f"- Required: {manual_review['required']}",
            f"- Status: `{manual_review['status']}`",
            f"- Reviewer role: {manual_review.get('reviewer_role') or 'n/a'}",
            f"- Decision: `{manual_review.get('decision') or 'n/a'}`",
            f"- Evidence: {', '.join(item['artifact'] for item in evidence) or 'none'}",
            f"- Receipt SHA-256: `{manual_review.get('receipt_sha256') or 'n/a'}`",
            f"- Signature verification: `{manual_review.get('signature_verification') or 'n/a'}`",
        ])

    if report.get("hard_gates"):
        lines.extend([
            "",
            "## Frozen hard gates",
            "",
            "| Gate | Metric | Rule | Observed | Status |",
            "|---|---|---:|---:|---|",
        ])
        for gate in report["hard_gates"]:
            observed = "n/a" if gate.get("observed") is None else fmt_num(gate["observed"], 4)
            lines.append(f"| {gate.get('id')} | {gate.get('metric')} | {gate.get('operator')} {gate.get('threshold')} | {observed} | {gate.get('status')} |")

    lines.extend(["", "## Gate and evidence warning", ""])
    if report["blocking_observations"]:
        for observation in report["blocking_observations"]:
            lines.append(f"- {observation}")
    else:
        lines.append("- No blocking observation was encoded in the analyzed runs; complete the frozen contract and manual evidence review before any promotion decision.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", help="Receipt index JSONL")
    parser.add_argument("--spec", help="Frozen evaluation spec JSON whose hard gates should be evaluated")
    parser.add_argument("--baseline", help="Variant ID used as paired baseline")
    parser.add_argument("--candidate", help="Variant ID used as paired candidate")
    parser.add_argument("--target-skill", help="Target skill ID for stage-separated routing metrics; inferred from spec.target.name")
    parser.add_argument(
        "--manual-review-receipt", action="append", default=[], metavar="RELATIVE_PATH",
        help="Verified manual-review authority receipt relative to spec.artifacts.root",
    )
    parser.add_argument("--json", metavar="PATH", help="Write full summary JSON; use - for stdout")
    parser.add_argument("--markdown", help="Write a Markdown summary")
    parser.add_argument(
        "--report-only", action="store_true",
        help="Always exit 0 after a valid analysis; decision_signal still carries blocked/inconclusive status",
    )
    args = parser.parse_args()

    if bool(args.baseline) != bool(args.candidate):
        parser.error("--baseline and --candidate must be provided together")
    if len(args.manual_review_receipt) > 1:
        parser.error("--manual-review-receipt may be supplied at most once")

    try:
        spec_path = Path(args.spec).resolve() if args.spec else None
        spec = load_spec(spec_path) if spec_path else None
        if spec is None:
            raise ValueError("--spec is required for receipt verification")
        level = spec.get("level") if spec else None
        if level == "L0":
            raise ValueError("L0 specs are package audits; use audit_skill_package.py")
        index_rows = load_jsonl(Path(args.runs))
        cases_by_id = None
        if spec and spec_path:
            cases_ref = Path(spec["suite"]["cases_file"])
            cases_path = cases_ref if cases_ref.is_absolute() else spec_path.parent / cases_ref
            case_rows = load_contract_jsonl(cases_path.resolve())
            public_heldout = [case.get("case_id") for case in case_rows if case.get("split") == "heldout"]
            if public_heldout:
                raise ValueError(f"public cases file contains heldout payload rows: {public_heldout}")
            holdout = spec["suite"].get("holdout_control", {})
            if holdout:
                payload_path = (spec_path.parent / holdout["payload_file"]).resolve()
                manifest_path = (spec_path.parent / holdout["manifest_file"]).resolve()
                for bound_path, hash_field in ((payload_path, "payload_hash"), (manifest_path, "manifest_hash")):
                    if not bound_path.is_file():
                        raise ValueError(f"holdout artifact not found: {bound_path}")
                    actual_hash = file_sha256(bound_path)
                    if actual_hash != holdout.get(hash_field):
                        raise ValueError(f"holdout {hash_field} mismatch: expected {holdout.get(hash_field)}, got {actual_hash}")
                holdout_rows = load_contract_jsonl(payload_path)
                non_holdout = [case.get("case_id") for case in holdout_rows if case.get("split") != "heldout"]
                if non_holdout:
                    raise ValueError(f"holdout payload contains non-heldout rows: {non_holdout}")
                public_ids = {case.get("case_id") for case in case_rows}
                overlap = sorted(public_ids & {case.get("case_id") for case in holdout_rows})
                if overlap:
                    raise ValueError(f"case IDs overlap between public and holdout payloads: {overlap}")
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise ValueError(f"holdout manifest is not valid JSON: {exc}") from exc
                if not isinstance(manifest, dict):
                    raise ValueError("holdout manifest must be a JSON object")
                manifest_entries = manifest.get("cases", [])
                clean_holdout = [
                    {key: value for key, value in case.items() if key != "_line"}
                    for case in holdout_rows
                ]
                payload_ids = [case.get("case_id") for case in clean_holdout]
                if manifest.get("payload_sha256") != file_sha256(payload_path):
                    raise ValueError("holdout manifest payload_sha256 does not match payload")
                if manifest.get("case_count") != len(payload_ids) or manifest.get("case_ids") != payload_ids:
                    raise ValueError("holdout manifest case count/order does not match payload")
                if not isinstance(manifest_entries, list) or len(manifest_entries) != len(payload_ids):
                    raise ValueError("holdout manifest entries do not match payload count")
                for case, entry in zip(clean_holdout, manifest_entries):
                    case_id = case.get("case_id")
                    if not isinstance(entry, dict) or entry.get("case_id") != case_id:
                        raise ValueError(f"holdout manifest entry ID mismatch for {case_id}")
                    if entry.get("case_sha256") != canonical_sha256(case):
                        raise ValueError(f"holdout manifest case_sha256 mismatch for {case_id}")
                case_rows.extend(holdout_rows)

            case_errors: list[str] = []
            case_warnings: list[str] = []
            check_cases(spec, case_rows, case_errors, case_warnings)
            if case_errors:
                raise ValueError("invalid evaluation cases: " + "; ".join(case_errors))
            cases_by_id = {
                case["case_id"]: {key: value for key, value in case.items() if key != "_line"}
                for case in case_rows
            }
            if spec.get("ready_for_scored_run") is True and any(
                PLACEHOLDER_RE.search(json.dumps(case, ensure_ascii=False))
                for case in cases_by_id.values()
            ):
                raise ValueError("scored-ready case suite still contains template placeholders")
            if spec.get("ready_for_scored_run") is not True:
                raise ValueError("spec is not ready_for_scored_run")
        candidate_package_hash = resolve_candidate_package_hash(spec, spec_path)
    except ValueError as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2

    variants_by_id = {variant["id"]: variant for variant in spec["variants"]}
    seen_run_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    evidence_issues: list[dict[str, str]] = []
    evidence_status = "complete"
    for row in index_rows:
        run_id = row["run_id"]
        if run_id in seen_run_ids:
            evidence_status = "invalid"
            evidence_issues.append({"run_id": run_id, "status": "invalid", "issue": "duplicate run_id"})
            continue
        seen_run_ids.add(run_id)
        case = cases_by_id.get(row["case_id"])
        variant = variants_by_id.get(row["variant"])
        if case is None or variant is None:
            evidence_status = "invalid"
            missing = "case_id" if case is None else "variant"
            evidence_issues.append({
                "run_id": run_id,
                "status": "invalid",
                "issue": f"run index references unknown {missing}",
            })
            continue
        verification = verify_receipt(
            row, spec, spec_path, case, variant, candidate_package_hash
        )
        if verification["status"] != "complete":
            if verification["status"] == "invalid" or evidence_status == "complete":
                evidence_status = verification["status"]
            evidence_issues.append({
                "run_id": run_id,
                "status": verification["status"],
                "issue": verification["issue"],
            })
            continue
        records.append(verification["record"])

    manual_config = spec.get("manual_review", {})
    manual_required = isinstance(manual_config, dict) and manual_config.get("required") is True
    manual_review_result: dict[str, Any] | None = None
    manual_references = args.manual_review_receipt
    if not manual_references:
        manual_review_result = {
            "required": manual_required,
            "status": "incomplete" if manual_required else "not_required",
            "decision": None,
        }
        if manual_required:
            if evidence_status == "complete":
                evidence_status = "incomplete"
            evidence_issues.append({
                "run_id": "<manual-review>",
                "status": "incomplete",
                "issue": "required --manual-review-receipt is missing",
            })
    else:
        try:
            manual_review_result = verify_manual_review_receipt(
                manual_references[0], spec, spec_path
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            evidence_status = "invalid"
            manual_review_result = {
                "required": manual_required,
                "status": "invalid",
                "decision": None,
            }
            evidence_issues.append({
                "run_id": "<manual-review>",
                "status": "invalid",
                "issue": str(exc),
            })

    if evidence_status != "complete":
        failed_context_summary = summarize_skill_context(
            records, cases_by_id, spec, spec["suite"]["repeats"]
        )
        failed_prior_context = summarize_prior_skill_context(
            records, cases_by_id, spec, spec["suite"]["repeats"], failed_context_summary
        )
        failure_report = {
            "schema_version": 1,
            "evidence_status": evidence_status,
            "usefulness_status": "not_applicable" if level == "L1" else "inconclusive",
            "evidence_issues": evidence_issues,
            "manual_review": manual_review_result,
            "skill_context": failed_context_summary,
            "context_efficiency": failed_context_summary["context_efficiency"],
        }
        if failed_prior_context is not None:
            failure_report.update(failed_prior_context)
        payload = json.dumps(failure_report, indent=2, ensure_ascii=False) + "\n"
        if args.json == "-":
            print(payload, end="")
        elif args.json:
            Path(args.json).write_text(payload, encoding="utf-8")
        print(f"evidence_status={evidence_status}")
        for issue in evidence_issues:
            print(f"{issue['run_id']}: {issue['issue']}")
        return 3

    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_variant[record["variant"]].append(record)
    variants = sorted(by_variant)
    available = set(variants)
    baseline = args.baseline
    candidate = args.candidate
    comparative = level in {"L2", "L3", "L4"}
    if spec and not comparative and (baseline is not None or candidate is not None):
        print("analysis error: L1 diagnostics do not accept comparative baseline/candidate arguments", file=sys.stderr)
        return 2
    if spec and comparative and baseline is None and candidate is None:
        baseline = infer_variant(spec, "baseline", "baseline", "skill_disabled", available)
        candidate = infer_variant(spec, "candidate_natural", "candidate", "natural_routing", available)
    prior = None
    if spec:
        prior_matches = [
            variant["id"] for variant in spec["variants"]
            if variant["role"] == "prior" and variant["mode"] == "natural_routing"
        ]
        prior = prior_matches[0] if len(prior_matches) == 1 else None

    if spec and comparative and (baseline is None or candidate is None):
        print("analysis error: a spec-bound analysis requires resolvable baseline and candidate variants", file=sys.stderr)
        return 2
    if baseline is not None and baseline == candidate:
        print("analysis error: baseline and candidate variants must be different", file=sys.stderr)
        return 2

    if baseline and baseline not in by_variant:
        print(f"analysis error: baseline variant not found: {baseline}", file=sys.stderr)
        return 2
    if candidate and candidate not in by_variant:
        print(f"analysis error: candidate variant not found: {candidate}", file=sys.stderr)
        return 2

    full_key_counts = Counter((record["variant"], record["case_id"], record["repeat"]) for record in records)
    duplicate_full_keys = sorted(key for key, count in full_key_counts.items() if count > 1)
    if duplicate_full_keys:
        print(f"analysis error: duplicate variant/case/repeat keys: {duplicate_full_keys[:20]}", file=sys.stderr)
        return 2

    completeness = None
    attribution_case_ids: set[str] | None = None
    if spec and cases_by_id is not None:
        allowed_cases = set(cases_by_id)
        unknown_cases = sorted({record["case_id"] for record in records} - allowed_cases)
        if unknown_cases:
            print(f"analysis error: run file contains case IDs outside the bound suite: {unknown_cases}", file=sys.stderr)
            return 2
        variants_spec = spec["variants"]
        variant_profiles = {
            variant["id"]: f"{variant['role']}/{variant['mode']}" for variant in variants_spec
        }
        unknown_variants = sorted(set(by_variant) - set(variant_profiles))
        if unknown_variants:
            print(f"analysis error: run file contains variants outside the bound spec: {unknown_variants}", file=sys.stderr)
            return 2
        repeats = spec["suite"]["repeats"]
        out_of_range = sorted({record["repeat"] for record in records if record["repeat"] > repeats})
        if out_of_range:
            print(f"analysis error: run file contains repeat values above suite.repeats={repeats}: {out_of_range}", file=sys.stderr)
            return 2
        expected_keys = {
            (variant_id, case_id, repeat)
            for variant_id, profile in variant_profiles.items()
            for case_id, case in cases_by_id.items()
            if profile in set(case.get("applicable_variant_profiles", []))
            for repeat in range(1, repeats + 1)
        }
        observed_keys = {
            (record["variant"], record["case_id"], record["repeat"])
            for record in records
        }
        records_by_key = {
            (record["variant"], record["case_id"], record["repeat"]): record
            for record in records
        }
        unexpected_keys = sorted(observed_keys - expected_keys)
        if unexpected_keys:
            print(
                "analysis error: run file contains case/variant/repeat keys outside the frozen plan: "
                f"{unexpected_keys[:20]}",
                file=sys.stderr,
            )
            return 2
        missing_keys = sorted(expected_keys - observed_keys)
        invalid_keys = sorted(
            key for key in expected_keys & observed_keys
            if records_by_key[key].get("valid") is not True
        )
        timed_out_keys = sorted(
            key for key in expected_keys & observed_keys
            if records_by_key[key].get("error_type") == "timeout"
        )
        valid_keys = sorted(
            key for key in expected_keys & observed_keys
            if records_by_key[key].get("valid") is True
        )
        attribution_case_ids = set()
        if baseline and candidate:
            attribution_case_ids = {
                case_id for case_id, case in cases_by_id.items()
                if case.get("attribution_evaluable") is True
                and variant_profiles[baseline] in set(case.get("applicable_variant_profiles", []))
                and variant_profiles[candidate] in set(case.get("applicable_variant_profiles", []))
            }
        selected_pair_expected = {
            key for key in expected_keys
            if key[0] in {baseline, candidate} and key[1] in attribution_case_ids
        }
        by_variant_completeness = {}
        for variant_id in sorted(variant_profiles):
            planned = {key for key in expected_keys if key[0] == variant_id}
            present = planned & observed_keys
            variant_invalid = {key for key in invalid_keys if key[0] == variant_id}
            variant_timed_out = {key for key in timed_out_keys if key[0] == variant_id}
            by_variant_completeness[variant_id] = {
                "planned": len(planned),
                "present": len(present),
                "valid": len(present - variant_invalid),
                "invalid": len(variant_invalid),
                "timed_out": len(variant_timed_out),
                "missing": len(planned - present),
            }
        completeness = {
            "case_count": len(cases_by_id),
            "attribution_case_count": len(attribution_case_ids),
            "declared_variant_count": len(variant_profiles),
            "repeats": repeats,
            "expected_plan_keys": len(expected_keys),
            "observed_plan_keys": len(expected_keys & observed_keys),
            "valid_plan_keys": len(valid_keys),
            "expected_selected_pair_keys": len(selected_pair_expected),
            "observed_selected_pair_keys": len(selected_pair_expected & observed_keys),
            "missing_expected_keys_count": len(missing_keys),
            "missing_expected_keys": [list(key) for key in missing_keys[:100]],
            "missing_expected_keys_truncated": len(missing_keys) > 100,
            "invalid_expected_keys_count": len(invalid_keys),
            "invalid_expected_keys": [list(key) for key in invalid_keys[:100]],
            "invalid_expected_keys_truncated": len(invalid_keys) > 100,
            "timed_out_expected_keys_count": len(timed_out_keys),
            "timed_out_expected_keys": [list(key) for key in timed_out_keys[:100]],
            "evidence_complete": not missing_keys and not invalid_keys,
            "by_variant": by_variant_completeness,
        }

    target_skill_id = args.target_skill
    if target_skill_id is None and spec and isinstance(spec.get("target"), dict):
        target_skill_id = spec["target"].get("name")

    routing_case_ids_by_variant: dict[str, set[str] | None] = {name: None for name in variants}
    if spec and cases_by_id is not None:
        for variant in spec["variants"]:
            profile = f"{variant['role']}/{variant['mode']}"
            routing_case_ids_by_variant[variant["id"]] = {
                case_id for case_id, case in cases_by_id.items()
                if variant["mode"] == "natural_routing"
                and profile in case.get("applicable_variant_profiles", [])
            }
    variant_summaries = {
        name: summarize_variant(by_variant[name], target_skill_id, routing_case_ids_by_variant.get(name))
        for name in variants
    }
    paired = paired_summary(records, baseline, candidate, attribution_case_ids) if baseline and candidate else None
    if paired is not None:
        paired["case_intervals"] = {
            field: paired_case_uncertainty(paired, spec, completeness, field)
            for field in ("task_pass", "process_score", "quality_score", "safety_pass")
        }

    context_summary = summarize_skill_context(
        records, cases_by_id, spec, spec["suite"]["repeats"]
    )
    prior_context = summarize_prior_skill_context(
        records, cases_by_id, spec, spec["suite"]["repeats"], context_summary
    )

    hard_gates = evaluate_hard_gates(
        spec, variant_summaries, records, candidate, paired, target_skill_id,
        prior, cases_by_id, spec["suite"]["repeats"], context_summary,
    ) if spec and comparative else []
    hard_failures_by_variant: dict[str, int] = defaultdict(int)
    for record in records:
        if record["valid"]:
            hard_failures_by_variant[record["variant"]] += len(record["hard_gate_failures"])
    case_gate_evidence = {
        "hard_failures_by_variant": dict(hard_failures_by_variant),
    }
    blocking: list[str] = []
    observed_safety_block = False
    no_valid_candidate_runs = False
    candidate_variant_ids = {
        variant["id"] for variant in spec["variants"] if variant.get("role") == "candidate"
    } if spec else ({candidate} if candidate else set())
    for name, summary in variant_summaries.items():
        if name in candidate_variant_ids:
            if summary["critical_safety_incidents"]:
                observed_safety_block = True
                blocking.append(f"{name}: {summary['critical_safety_incidents']} critical safety incident(s)")
            failed_safety = summary["safety_incident_rate"]["successes"]
            if failed_safety:
                observed_safety_block = True
                blocking.append(f"{name}: {failed_safety} valid run(s) failed the safety gate")
            if summary["valid_records"] == 0:
                no_valid_candidate_runs = True
                blocking.append(f"{name}: no valid runs")
    failed_gates = [gate for gate in hard_gates if gate["status"] == "fail"]
    unknown_gates = [gate for gate in hard_gates if gate["status"] == "not_evaluable"]
    for gate in failed_gates:
        blocking.append(f"hard gate {gate['id']} failed: observed={gate['observed']} rule {gate['operator']} {gate['threshold']}")
    for gate in unknown_gates:
        blocking.append(f"hard gate {gate['id']} is not evaluable: {gate.get('reason')}")
    candidate_case_failures, candidate_failure_blockers = summarize_candidate_hard_failures(
        case_gate_evidence["hard_failures_by_variant"], candidate_variant_ids
    )
    blocking.extend(candidate_failure_blockers)
    spec_ready = spec.get("ready_for_scored_run") is True if spec and comparative else None
    if spec and comparative and not spec_ready:
        blocking.append("evaluation spec is not marked ready_for_scored_run=true")
    incomplete_matrix = bool(
        completeness
        and (
            completeness["missing_expected_keys_count"]
            or completeness["invalid_expected_keys_count"]
        )
    )
    if incomplete_matrix:
        blocking.append(
            "run matrix evidence is incomplete: "
            f"missing={completeness['missing_expected_keys_count']}, "
            f"invalid={completeness['invalid_expected_keys_count']}, "
            f"expected={completeness['expected_plan_keys']}"
        )
    manual_decision_blocks = bool(
        manual_review_result
        and manual_review_result.get("decision") in {"hold", "reject"}
    )
    if manual_decision_blocks:
        blocking.append(
            f"manual review authority decision is {manual_review_result['decision']}"
        )
    duplicate_pairs = bool(paired and paired["duplicate_variant_keys"])
    if duplicate_pairs:
        blocking.append(f"duplicate variant/case/repeat keys make pairing ambiguous: {paired['duplicate_variant_keys']}")
    if paired and paired["paired_valid"] == 0:
        blocking.append("no valid paired candidate/baseline outcomes")

    effective_evidence_status = "incomplete" if incomplete_matrix else "invalid" if duplicate_pairs else "complete"
    benefit_gate_id = spec.get("analysis", {}).get("usefulness_benefit_gate_id")
    benefit_gate = next((gate for gate in hard_gates if gate["id"] == benefit_gate_id), None)
    guardrail_gates = [gate for gate in hard_gates if gate["id"] != benefit_gate_id]
    protected_gate = next(
        (gate for gate in hard_gates if gate["metric"] == "protected_outcome_failures"),
        None,
    )
    protected_failures = int(protected_gate["observed"]) if protected_gate and protected_gate["observed"] is not None else 0
    usefulness_status = derive_usefulness_status(
        level=level,
        evidence_status=effective_evidence_status,
        benefit_gate_status=benefit_gate["status"] if benefit_gate else "not_evaluable",
        guardrail_statuses=[gate["status"] for gate in guardrail_gates],
        protected_outcome_failures=protected_failures,
        material_harm=observed_safety_block,
        candidate_hard_failures=candidate_case_failures,
    )
    decision_signal = derive_decision_signal(level, usefulness_status)
    manual_gate_passed = not manual_required or bool(
        manual_review_result and manual_review_result.get("decision") == "approve"
    )
    final_authority_status = derive_final_authority_status(
        usefulness_status=usefulness_status,
        manual_gate_passed=manual_gate_passed,
        candidate_hard_failures=candidate_case_failures,
        blocking_observations=blocking,
    )

    report: dict[str, Any] = {
        "schema_version": 1,
        "evidence_status": effective_evidence_status,
        "usefulness_status": usefulness_status,
        "final_authority_status": final_authority_status,
        "record_count": len(records),
        "run_matrix": records,
        "variants": variants,
        "variant_summaries": variant_summaries,
        "paired": paired,
        "skill_context": context_summary,
        "context_efficiency": context_summary["context_efficiency"],
        "evaluation_id": spec.get("evaluation_id") if spec else None,
        "spec_ready_for_scored_run": spec_ready,
        "hard_gates": hard_gates,
        "manual_review": manual_review_result if manual_config or manual_references else None,
        "case_gate_evidence": case_gate_evidence,
        "receipt_verification": {"status": "pass", "checked_runs": len(records)},
        "trust_boundaries": {
            "controller": "external_controller_attested",
            "fixture_producer": "local_fixture_producer_attested",
            "catalog_and_treatment": "external_identity_unverified",
            "context_budget_authority": "external_authority_reference_unverified"
        },
        "run_matrix_completeness": completeness,
        "blocking_observations": blocking,
        "decision_signal": decision_signal,
        "claim_boundary": (
            "L1 diagnostic evidence describes the bound candidate runs only; it does not support comparative or readiness claims."
            if level == "L1"
            else "Apply the frozen evaluation spec, hard gates, calibration, and manual evidence review before a promote/hold/reject decision."
        ),
    }
    if prior_context is not None:
        report.update(prior_context)

    try:
        if args.json:
            payload = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
            if args.json == "-":
                sys.stdout.write(payload)
            else:
                Path(args.json).write_text(payload, encoding="utf-8")
        if args.markdown:
            Path(args.markdown).write_text(markdown_report(report), encoding="utf-8")
    except OSError as exc:
        print(f"analysis output error: {exc}", file=sys.stderr)
        return 2

    status_stream = sys.stderr if args.json == "-" else sys.stdout
    print(f"Analyzed {len(records)} records across {len(variants)} variants.", file=status_stream)
    for name in variants:
        summary = variant_summaries[name]
        routing = summary["routing"]
        critical = "n/a" if summary["critical_safety_incidents"] is None else str(summary["critical_safety_incidents"])
        print(
            f"{name}: valid={summary['valid_records']}/{summary['records']} "
            f"task_pass={fmt_rate(summary['task_pass']['rate'])} "
            f"routing_f1={fmt_rate(routing.get('f1'))} "
            f"critical_safety={critical}",
            file=status_stream,
        )
    if paired:
        print(
            f"paired {paired['candidate']} vs {paired['baseline']}: n={paired['paired_valid']} "
            f"wins={paired['wins']} losses={paired['losses']} "
            f"tie_pass={paired['tie_pass']} tie_fail={paired['tie_fail']} "
            f"lift={fmt_rate(paired['absolute_pass_lift'])}",
            file=status_stream,
        )
    if completeness:
        print(
            "run_matrix: "
            f"observed={completeness['observed_plan_keys']}/"
            f"{completeness['expected_plan_keys']} "
            f"valid={completeness['valid_plan_keys']} "
            f"invalid={completeness['invalid_expected_keys_count']} "
            f"timed_out={completeness['timed_out_expected_keys_count']} "
            f"missing={completeness['missing_expected_keys_count']}",
            file=status_stream,
        )
    if hard_gates:
        statuses = Counter(gate["status"] for gate in hard_gates)
        print(
            "hard_gates: " + ", ".join(f"{key}={statuses.get(key, 0)}" for key in ("pass", "fail", "not_evaluable")),
            file=status_stream,
        )
    print(f"Decision status: {decision_status_text(report)}", file=status_stream)
    if args.report_only:
        return 0
    if level == "L1" or (usefulness_status == "supported" and final_authority_status == "eligible"):
        return 0
    if usefulness_status == "not_supported" or manual_decision_blocks:
        return 1
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
