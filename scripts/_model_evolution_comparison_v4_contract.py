"""Controller-owned comparison-v4 artifact contract."""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_SCRIPTS = REPOSITORY_ROOT / "skill-evaluator/scripts"
sys.path.insert(0, str(EVALUATOR_SCRIPTS))

from comparison_contract import (  # noqa: E402
    ContractError,
    _output_root,
    _raise,
    _schema_error,
)
from evidence_io import atomic_write_directory, canonical_json_bytes, load_json  # noqa: E402
from validate_eval_suite import (  # noqa: E402
    load_epoch7_schema_registry,
    validate_epoch7_schema,
)

SCHEMA_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution/schemas"


def schema_registry() -> dict[str, dict[str, Any]]:
    registry = load_epoch7_schema_registry()
    for name in ("comparison-plan-v4.schema.json", "comparison-report-v4.schema.json"):
        registry[name] = load_json(SCHEMA_ROOT / name)
    return registry


def load_plan(
    plan_path: Path,
) -> tuple[Path, dict[str, Any], dict[str, dict[str, Any]]]:
    if plan_path.is_symlink() or not plan_path.is_file():
        _raise("plan.file", "comparison plan must be a regular non-symlink file")
    resolved = plan_path.resolve()
    try:
        plan = load_json(resolved)
        registry = schema_registry()
    except (OSError, ValueError, TypeError) as exc:
        _raise("plan.load", exc)
    diagnostics = validate_epoch7_schema(
        plan, "comparison-plan-v4.schema.json", registry
    )
    if diagnostics:
        _schema_error("comparison plan", diagnostics)
    if plan["kind"] != "revision":
        _raise("plan.kind", "comparison v4 supports revision plans only")
    return resolved, plan, registry


def commit_outputs(
    plan_path: Path,
    plan: dict[str, Any],
    report: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    registry: dict[str, dict[str, Any]],
) -> tuple[Path, Path]:
    ordered = sorted(diagnostics, key=lambda item: item["diagnostic_id"])
    identifiers = [item["diagnostic_id"] for item in ordered]
    if len(identifiers) != len(set(identifiers)):
        _raise("output.diagnostic_id", "comparison diagnostic IDs must be unique")
    index = {
        "schema_version": 2,
        "comparison_id": plan["comparison_id"],
        "item_count": len(ordered),
        "diagnostics": ordered,
    }
    report["diagnostic_index_path"] = plan["output"]["diagnostic_index"]
    for value, schema_name, label in (
        (index, "comparison-diagnostic-index-v2.schema.json", "comparison diagnostic index"),
        (report, "comparison-report-v4.schema.json", "comparison report"),
    ):
        errors = validate_epoch7_schema(value, schema_name, registry)
        if errors:
            _schema_error(label, errors)
    root = _output_root(plan_path, plan)
    report_name = plan["output"]["report"]
    index_name = plan["output"]["diagnostic_index"]
    atomic_write_directory(
        root,
        {
            report_name: canonical_json_bytes(report),
            index_name: canonical_json_bytes(index),
        },
    )
    return root / report_name, root / index_name


__all__ = ["ContractError", "commit_outputs", "load_plan", "schema_registry"]
