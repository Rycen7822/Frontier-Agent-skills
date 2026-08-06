"""Pure model-evolution document fixtures backed by tracked seeds."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from _model_evolution_contract import (
    _validate_external_schema,
    load_json,
    verify_self_hash,
    with_self_hash,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests/fixtures/skill_evaluator"
SCHEMA_ROOT = REPOSITORY_ROOT / "skill-evaluator/schemas"
HASH = "sha256:" + "1" * 64


def _seed(name: str, hash_field: str) -> dict[str, Any]:
    value = load_json(FIXTURE_ROOT / f"{name}.json", label=f"{name} seed")
    _validate_external_schema(value, SCHEMA_ROOT / f"{name}.schema.json", name)
    verify_self_hash(value, hash_field)
    return copy.deepcopy(value)


def receipt() -> dict[str, Any]:
    return _seed("receipt-v4", "receipt_hash")


def analysis_summary() -> dict[str, Any]:
    return _seed("analysis-summary-v4", "summary_hash")


def host_manifest() -> dict[str, Any]:
    return _seed("host-manifest-v1", "manifest_hash")


def _comparison_input(role: str) -> dict[str, Any]:
    execution_identity = {
        "as_of": "2026-01-01T00:00:00Z",
        **{
            field: HASH
            for field in (
                "clock_hash",
                "harness_hash",
                "host_hash",
                "model_hash",
                "policy_hash",
                "prompt_hash",
                "repository_hash",
                "runtime_hash",
                "subject_hash",
                "tokenizer_pricing_hash",
                "tool_surface_hash",
            )
        },
    }
    return {
        "role": role,
        "evaluation_id": "evaluation-fixture",
        "plan_id": "pl-fixture",
        "plan_hash": HASH,
        "spec_hash": HASH,
        "summary_hash": HASH,
        "host_manifest_hash": HASH,
        "observations_hash": HASH,
        "failure_index_hash": None,
        "execution_identity": execution_identity,
        "file_hashes": {
            "execution_plan": HASH,
            "failure_index": None,
            "host_manifest": HASH,
            "observations": HASH,
            "spec": HASH,
            "summary": HASH,
        },
    }


def comparison_report(kind: str) -> dict[str, Any]:
    if kind == "model_transition":
        result = {
            "kind": "model_transition",
            "mode": "direct",
            "classification": "retained_specialized_value",
            "classification_metric_ids": [],
        }
    elif kind == "revision":
        result = {
            "kind": "revision",
            "status": "closed",
            "target_failure_class": "quality_regression",
            "closed_diagnostic_ids": [],
            "remaining_diagnostic_ids": [],
        }
    else:
        raise ValueError(f"unsupported comparison kind: {kind}")
    value = with_self_hash(
        {
            "schema_version": 1,
            "comparison_id": f"{kind}-fixture",
            "comparison_plan_hash": HASH,
            "kind": kind,
            "claim_scope": "diagnostic_only",
            "claim_ceiling": "diagnostic_only",
            "registration_status": "declared_pre_registered",
            "authority_eligibility": "eligible",
            "generator": {
                "name": "compare_cycles.py",
                "version": "3.3.0",
                "source_hash": HASH,
            },
            "inputs": [
                _comparison_input("prior"),
                _comparison_input("candidate"),
            ],
            "comparability_checks": [],
            "metrics": [],
            "diagnostic_index_hash": HASH,
            "result": result,
        },
        "comparison_report_hash",
    )
    _validate_external_schema(
        value,
        SCHEMA_ROOT / "comparison-report-v1.schema.json",
        f"{kind} comparison",
    )
    verify_self_hash(value, "comparison_report_hash")
    return value
