"""Pure model-evolution document fixtures from the epoch-6 evaluator owners."""

from __future__ import annotations

import copy
from typing import Any

from skill_evaluator_test_support import make_epoch6_schema_examples


def _example(schema_name: str) -> dict[str, Any]:
    return copy.deepcopy(make_epoch6_schema_examples()[schema_name])


def receipt() -> dict[str, Any]:
    return _example("receipt-v5.schema.json")


def analysis_summary() -> dict[str, Any]:
    return _example("analysis-summary-v5.schema.json")


def host_manifest() -> dict[str, Any]:
    return _example("host-manifest-v2.schema.json")


def comparison_report(kind: str) -> dict[str, Any]:
    value = _example("comparison-report-v2.schema.json")
    value["comparison_id"] = f"{kind}-fixture"
    if kind == "revision":
        return value
    if kind != "model_transition":
        raise ValueError(f"unsupported comparison kind: {kind}")
    value["kind"] = kind
    value["authority_eligibility"] = "eligible"
    value["claim_ceiling"] = "transition_retention"
    value["result"] = {
        "kind": kind,
        "mode": "direct",
        "classification": "retained_specialized_value",
        "classification_metric_ids": [],
    }
    return value
