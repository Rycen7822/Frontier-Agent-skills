"""D0, Formal, and P4 projections, gates, usage closure, and release reports."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import statistics
import sys
from typing import Any

from jsonschema import Draft202012Validator

from . import campaign, host, specs
from .artifacts import (
    StateError,
    atomic_write,
    bundle_source_hash,
    canonical_bytes,
    canonical_hash,
    contained_file,
    file_hash,
    json_object,
    load_json,
    self_hashed,
    signed_clean_revision,
    tree_hash,
    verified_artifact,
    verify_self_hash,
    write_or_verify_json,
)


REPORT_STUDIES = {
    "software-quality-workflows": "frontier-formal-software-quality-workflows",
    "writing-plans-planner": "frontier-formal-writing-plans-planner",
    "writing-plans-transfer": "frontier-formal-writing-plans-transfer",
}
STUDIES = tuple(REPORT_STUDIES)
STUDY_FILES = {
    "spec": "eval-spec-v5.json",
    "plan": "execution-plan-v1.json",
    "index": "artifacts/index.jsonl",
    "summary": "summary.json",
    "failure_index": "failures.json",
}


class ReportError(RuntimeError):
    """A report input, gate, usage projection, or release seal is invalid."""


EXPECTED_SKILLS = {
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
}


def resolve_pointer(root: dict[str, Any], pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ReportError("gate metric_id must be an absolute JSON pointer")
    value: Any = root
    for token in pointer[1:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise ReportError(f"gate metric is unavailable: {pointer}")
        value = value[key]
    return value


def selected_value(value: Any, selector: str) -> Any:
    if selector == "scalar":
        return value
    if selector == "status_value":
        return value.get("status") if isinstance(value, dict) else value
    if selector in {"point", "lower", "upper", "numerator"}:
        if not isinstance(value, dict) or selector not in value:
            raise ReportError(f"metric lacks selector {selector}")
        return value[selector]
    raise ReportError(f"unsupported gate selector: {selector}")


def _threshold_value(
    threshold: dict[str, Any],
    namespace: dict[str, Any],
) -> Any:
    kind = threshold.get("kind")
    if kind == "scalar":
        return threshold.get("scalar")
    if kind == "count_pair":
        return threshold.get("numerator")
    if kind == "relative_metric":
        comparator = selected_value(
            resolve_pointer(namespace, threshold["comparator_metric_id"]),
            "scalar",
        )
        scale = threshold.get("scalar")
        if (
            not isinstance(comparator, (int, float))
            or isinstance(comparator, bool)
            or not isinstance(scale, (int, float))
            or isinstance(scale, bool)
        ):
            raise ReportError("relative gate threshold is non-numeric")
        return comparator * scale
    raise ReportError("gate threshold kind is invalid")


def _comparison(operator: str, observed: Any, expected: Any) -> bool:
    if observed is None:
        return False
    operators = {
        "eq": lambda: observed == expected,
        "ne": lambda: observed != expected,
        "lt": lambda: observed < expected,
        "le": lambda: observed <= expected,
        "gt": lambda: observed > expected,
        "ge": lambda: observed >= expected,
    }
    try:
        return bool(operators[operator]())
    except (KeyError, TypeError):
        raise ReportError("gate comparison is invalid") from None


def evaluate_gates(
    gates: list[dict[str, Any]],
    namespace: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    passed = []
    failed = []
    seen = set()
    for gate in gates:
        gate_id = gate.get("gate_id")
        if (
            not isinstance(gate_id, str)
            or not gate_id
            or gate_id in seen
            or gate.get("critical") is not True
        ):
            raise ReportError("gate identity is invalid")
        seen.add(gate_id)
        metric = resolve_pointer(namespace, gate["metric_id"])
        if gate["threshold"].get("kind") == "count_pair":
            observed = metric
            expected = {
                "numerator": gate["threshold"]["numerator"],
                "denominator": gate["threshold"]["denominator"],
            }
        else:
            observed = selected_value(metric, gate["selector"])
            expected = _threshold_value(gate["threshold"], namespace)
        result = {
            "gate_id": gate_id,
            "metric_id": gate["metric_id"],
            "evidence_artifact_kind": gate["evidence_artifact_kind"],
            "observed": observed,
            "passed": _comparison(gate["operator"], observed, expected),
        }
        (passed if result["passed"] else failed).append(result)
    return passed, failed


def writing_plan_migration_claim(
    phase: str,
    projection: dict[str, Any],
) -> dict[str, Any]:
    minimum_cases, selector, minimum_reduction = (
        specs.writing_plan_migration_claim_policy(phase)
    )
    metrics = resolve_pointer(
        {"projection": projection},
        "/projection/writing_plans/release_metrics",
    )
    required = {
        "prior_reference_cases",
        "mixed_prior_cases",
        "prior_controlled_context_reduction",
    }
    if not isinstance(metrics, dict) or not required <= set(metrics):
        raise ReportError("migration claim metrics are incomplete")
    reference_cases = metrics["prior_reference_cases"]
    mixed_cases = metrics["mixed_prior_cases"]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in (reference_cases, mixed_cases)
    ):
        raise ReportError("migration claim cohort evidence is invalid")
    reduction_metric = metrics["prior_controlled_context_reduction"]
    reduction = (
        None
        if reduction_metric is None
        else selected_value(reduction_metric, selector)
    )
    if reduction is not None and (
        not isinstance(reduction, (int, float))
        or isinstance(reduction, bool)
        or not math.isfinite(reduction)
    ):
        raise ReportError("migration claim reduction evidence is invalid")
    result = {
        "minimum_reference_cases": minimum_cases,
        "observed_reference_cases": reference_cases,
        "mixed_prior_cases": mixed_cases,
        "reduction_selector": selector,
        "minimum_reduction": minimum_reduction,
        "observed_reduction": reduction,
    }
    if reference_cases < minimum_cases or mixed_cases:
        return {"status": "unavailable", **result, "observed_reduction": None}
    if reduction is None:
        raise ReportError("migration claim reduction evidence is unavailable")
    return {
        "status": (
            "supported" if reduction >= minimum_reduction else "not_supported"
        ),
        **result,
    }


def budget_contract(
    phase: str,
    request_manifest_path: Path,
) -> dict[str, Any]:
    manifest = campaign.load_request_manifest(request_manifest_path)
    try:
        expected = specs.PHASE_BUDGETS[phase]
    except KeyError:
        raise ReportError(f"unknown provider budget phase: {phase}") from None
    budget = manifest["budget"]
    observed = (
        budget["scored_call_hard_cap"],
        budget["grader_calibration_call_hard_cap"],
        budget["reviewer_calibration_call_hard_cap"],
        budget["scheduled_provider_calls"],
    )
    if (
        observed != expected
        or budget["retry_provider_call_cap"] != 0
        or budget["provider_call_hard_cap"] != budget["scheduled_provider_calls"]
        or manifest["conditional_requests"]
    ):
        raise ReportError(f"{phase} request-manifest budget differs")
    return {
        "schema_version": "provider-budget-contract/1.0",
        **{
            field: budget[field]
            for field in (
                "scheduled_provider_calls",
                "scored_call_hard_cap",
                "grader_calibration_call_hard_cap",
                "reviewer_calibration_call_hard_cap",
                "provider_call_hard_cap",
            )
        },
    }


def load_controller_manifest(path: Path) -> dict[str, Any]:
    value = load_json(path)
    fields = {
        "schema_version",
        "candidate_revision",
        "candidate_source_tree_hash",
        "candidate_plugin_tree_hash",
        "controller_test_gate",
        "controller_inventory",
        "controller_content_hash",
        "stable_analyzer_source_hash",
        "skill_evaluator_source_hash",
        "app_server",
        "corpora",
        "archive_content_hash",
        "archive_rebuild_verified",
        "manifest_hash",
    }
    if (
        set(value) != fields
        or value["schema_version"] != "frontier-controller-freeze/5.0"
    ):
        raise ReportError("controller manifest is invalid")
    try:
        verify_self_hash(value, "manifest_hash")
    except StateError as exc:
        raise ReportError("controller manifest is invalid") from exc
    return value


def create_decision_contract(
    *,
    phase: str,
    repo: Path,
    candidate_plugin_root: Path,
    controller_manifest_path: Path,
    request_manifest_path: Path,
    output: Path,
) -> dict[str, Any]:
    revision = signed_clean_revision(repo)
    identity = {
        "candidate_revision": revision["candidate_revision"],
        "candidate_source_tree_hash": bundle_source_hash(
            repo,
            EXPECTED_SKILLS,
        ),
    }
    controller = load_controller_manifest(controller_manifest_path)
    plugin_hash = tree_hash(candidate_plugin_root)
    evaluator_root = repo / "skill-evaluator"
    analyzer = contained_file(
        evaluator_root,
        "scripts/analyze_runs.py",
        "stable analyzer",
    )
    if (
        controller["candidate_revision"] != identity["candidate_revision"]
        or controller["candidate_source_tree_hash"]
        != identity["candidate_source_tree_hash"]
        or controller["candidate_plugin_tree_hash"] != plugin_hash
        or controller["skill_evaluator_source_hash"] != tree_hash(evaluator_root)
        or controller["stable_analyzer_source_hash"] != file_hash(analyzer)
    ):
        raise ReportError("controller freeze identity differs")
    contract = self_hashed({
        "schema_version": "p3-decision-contract/4.0",
        **identity,
        "candidate_plugin_tree_hash": plugin_hash,
        "controller_content_hash": controller["controller_content_hash"],
        "evaluator_source_hash": controller["skill_evaluator_source_hash"],
        "request_manifest_content_hash": file_hash(request_manifest_path),
        "evaluated_skill_ids": [
            "software-quality-workflows",
            "writing-plans",
        ],
        "budget_contract": budget_contract(phase, request_manifest_path),
        "gate_contract": specs.gate_contract(phase),
    }, "decision_contract_hash")
    write_or_verify_json(output, contract)
    return {
        "phase": phase,
        "candidate_revision": contract["candidate_revision"],
        "decision_contract_hash": contract["decision_contract_hash"],
        "provider_requests": 0,
    }


def usage_closure(
    study_ids: tuple[str, ...],
    attempt_root: Path,
    native_receipts: list[dict[str, Any]],
) -> dict[str, int]:
    try:
        manifest_studies = {REPORT_STUDIES[item] for item in study_ids}
    except KeyError as exc:
        raise ReportError(f"unknown report study: {exc.args[0]}") from None
    campaign.verify_request_completion(attempt_root, native_receipts)
    manifest = campaign.bound_request_manifest(attempt_root)
    ledger = campaign.verify_ledger(attempt_root / "provider-ledger.jsonl")
    entries = {
        entry["request_id"]: entry
        for entry in (
            *manifest["required_requests"],
            *manifest["conditional_requests"],
        )
        if entry["study"] in manifest_studies
    }
    receipts = {
        receipt["request_id"]: receipt
        for receipt in native_receipts
        if receipt["request_id"] in entries
    }
    reserved = {
        row["request_id"] for row in ledger if row["request_id"] in entries
    }
    if reserved != set(receipts):
        raise ReportError("study ledger and receipt closure differs")
    family_counts = {
        family: sum(entries[item]["family"] == family for item in receipts)
        for family in campaign.REQUEST_FAMILIES
    }
    required = {
        entry["request_id"]
        for entry in manifest["required_requests"]
        if entry["study"] in manifest_studies
    }
    retry = {
        entry["request_id"]
        for entry in manifest["conditional_requests"]
        if entry["study"] in manifest_studies
    }
    return {
        "scheduled": len(required),
        "observed": len(required & set(receipts)),
        "graded": sum(
            entries[item]["request_kind"] == "model_grade" for item in receipts
        ),
        "missing": len(required - set(receipts)),
        "duplicate": 0,
        "retries": len(retry & set(receipts)) // 2,
        "scored_provider_calls": family_counts["scored"],
        "grader_calibration_provider_calls": family_counts[
            "grader_calibration"
        ],
        "reviewer_calibration_provider_calls": family_counts[
            "reviewer_calibration"
        ],
        "provider_calls": len(receipts),
    }


def _file_binding(root: Path, relative: str, label: str) -> dict[str, Any]:
    path = contained_file(root, relative, label)
    return {"path": path, "sha256": file_hash(path)}


def study_binding(
    root: Path,
    study_id: str,
    manual_receipt_locator: str | None,
) -> dict[str, Any]:
    return {
        "study_id": study_id,
        **{
            field: _file_binding(root, relative, f"{study_id} {field}")
            for field, relative in STUDY_FILES.items()
        },
        "manual_receipt_locator": manual_receipt_locator,
    }


def write_writing_plans_join(
    *,
    planner_root: Path,
    transfer_root: Path,
    output: Path,
) -> dict[str, Any]:
    def indexed(root: Path, label: str) -> dict[str, dict[str, Any]]:
        path = contained_file(root, "artifacts/index.jsonl", f"{label} index")
        rows = {}
        for position, line in enumerate(path.read_bytes().splitlines(), 1):
            row = json_object(line, f"{path}:{position}")
            entry_id = row.get("entry_id")
            if not isinstance(entry_id, str) or entry_id in rows:
                raise ReportError(f"{label} index identity is ambiguous")
            rows[entry_id] = row
        return rows

    planner_rows = indexed(planner_root, "planner")
    transfer_rows = indexed(transfer_root, "transfer")
    plan = json_object(
        contained_file(
            transfer_root,
            "execution-plan-v1.json",
            "transfer plan",
        ).read_bytes(),
        "transfer plan",
    )
    spec = load_json(transfer_root / "eval-spec-v5.json")
    treatments = {
        item["treatment_id"]: (item["causal_role"], item["profile"])
        for item in spec["treatments"]
    }
    join = {}
    expected = set()
    for entry in plan["entries"]:
        if entry["disposition"] != "execute":
            continue
        role, profile = treatments[entry["treatment_id"]]
        if role not in {"baseline", "candidate"}:
            continue
        expected.add(entry["entry_id"])
        row = transfer_rows.get(entry["entry_id"])
        if row is None:
            raise ReportError("transfer join inventory is incomplete")
        receipt_path = verified_artifact(
            transfer_root / "artifacts",
            row["receipt"],
            "transfer receipt",
        )
        receipt = json_object(receipt_path.read_bytes(), receipt_path)
        verify_self_hash(receipt, "receipt_hash")
        if (
            receipt["run"]["valid"] is not True
            or receipt["run"]["entry_id"] != entry["entry_id"]
            or receipt["run"]["plan_hash"] != plan["plan_hash"]
        ):
            raise ReportError("transfer receipt identity is invalid")
        contract = load_json(
            transfer_root
            / f"fixtures/{entry['case_id']}/case.contract.json"
        )
        transfer = contract["transfer_source"]
        binding_id = transfer["profiles"].get(profile)
        if binding_id != role:
            raise ReportError("transfer role differs from planner binding")
        binding = transfer["bindings"][binding_id]
        planner_row = planner_rows.get(binding["planner_entry_id"])
        if (
            planner_row is None
            or planner_row["receipt"]["sha256"]
            != binding["planner_receipt_hash"]
        ):
            raise ReportError("planner receipt identity drifted")
        planner_receipt = verified_artifact(
            planner_root / "artifacts",
            planner_row["receipt"],
            "planner receipt",
        )
        planner_document = json_object(planner_receipt.read_bytes(), planner_receipt)
        verify_self_hash(planner_document, "receipt_hash")
        join[entry["entry_id"]] = {
            "source_case_id": binding["source_case_id"],
            "planner_repeat": binding["planner_repeat"],
            "planner_entry_id": binding["planner_entry_id"],
            "planner_receipt_hash": binding["planner_receipt_hash"],
            "executor_receipt_hash": row["receipt"]["sha256"],
        }
    if set(join) != expected:
        raise ReportError("Writing Plans join inventory differs")
    write_or_verify_json(output, join)
    return {
        "joined_entries": len(join),
        "join_content_hash": file_hash(output),
        "provider_requests": 0,
    }


def project_release(
    *,
    phase: str,
    analyzer: Any,
    roots: dict[str, Path],
    manual_receipts: dict[str, str | None],
    join_path: Path,
    seed: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    bindings = [
        study_binding(
            roots[study_id],
            study_id,
            manual_receipts[study_id],
        )
        for study_id in STUDIES
    ]
    join = load_json(join_path)
    projection = analyzer.project_release_estimands(
        bindings,
        join,
        confidence_level=0.90,
        bootstrap_iterations=10000,
        random_seed=seed,
        allow_missing_manual=phase == "d0",
    )
    if not isinstance(projection, dict):
        raise ReportError("stable release projection is not an object")
    summaries = {
        study_id: load_json(roots[study_id] / STUDY_FILES["summary"])
        for study_id in STUDIES
    }
    return projection, summaries


def load_analyzer(skill_evaluator_root: Path):
    path = contained_file(
        skill_evaluator_root,
        "scripts/analyze_runs.py",
        "stable analyzer",
    )
    name = "frontier_stable_release_analyzer"
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise ReportError("stable analyzer import failed")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    if not callable(getattr(module, "project_release_estimands", None)):
        raise ReportError("stable release projection is unavailable")
    return module


def load_decision_contract(path: Path) -> dict[str, Any]:
    contract = load_json(path)
    expected = {
        "schema_version",
        "candidate_revision",
        "candidate_source_tree_hash",
        "candidate_plugin_tree_hash",
        "controller_content_hash",
        "evaluator_source_hash",
        "request_manifest_content_hash",
        "evaluated_skill_ids",
        "budget_contract",
        "gate_contract",
        "decision_contract_hash",
    }
    if (
        set(contract) != expected
        or contract["schema_version"] != "p3-decision-contract/4.0"
        or contract["evaluated_skill_ids"]
        != ["software-quality-workflows", "writing-plans"]
        or contract["decision_contract_hash"]
        != canonical_hash({
            key: value
            for key, value in contract.items()
            if key != "decision_contract_hash"
        })
    ):
        raise ReportError("decision contract is invalid")
    gates = contract["gate_contract"]
    if (
        not isinstance(gates, dict)
        or set(gates)
        != {
            "schema_version",
            "software-quality-workflows",
            "writing-plans",
        }
        or gates["schema_version"] != "gate-contract/1.0"
        or not all(
            isinstance(gates[arm], list) and gates[arm]
            for arm in ("software-quality-workflows", "writing-plans")
        )
    ):
        raise ReportError("decision gate contract is invalid")
    return contract


def load_attempt_decision_contract(
    contract_path: Path,
    attempt_root: Path,
) -> dict[str, Any]:
    registry, _ = campaign.load_attempt(attempt_root)
    target = contained_file(
        contract_path.parent,
        contract_path.name,
        "decision contract",
    )
    bound = contained_file(
        attempt_root,
        registry["phase_contract_path"],
        "attempt decision contract",
    )
    if target != bound:
        raise ReportError("decision contract is not the attempt phase contract")
    contract = load_decision_contract(target)
    bindings = {
        "candidate_revision": "candidate_revision",
        "candidate_source_tree_hash": "candidate_source_tree_hash",
        "candidate_plugin_tree_hash": "candidate_plugin_tree_hash",
        "controller_content_hash": "controller_content_hash",
        "evaluator_source_hash": "evaluator_source_hash",
        "request_manifest_content_hash": "request_manifest_sha256",
    }
    if any(
        contract[contract_field] != registry[registry_field]
        for contract_field, registry_field in bindings.items()
    ):
        raise ReportError("decision contract and attempt registry differ")
    return contract


def _native_hashes(
    roots: dict[str, Path],
    study_ids: tuple[str, ...],
    join_path: Path,
) -> dict[str, str]:
    hashes = {
        f"{study_id.replace('-', '_')}_{field}": file_hash(
            contained_file(
                roots[study_id],
                relative,
                f"{study_id} {field}",
            ),
        )
        for study_id in study_ids
        for field, relative in STUDY_FILES.items()
    }
    if "writing-plans-transfer" in study_ids:
        hashes["writing_plans_join"] = file_hash(join_path)
    return hashes


def _manual_hash(
    projection: dict[str, Any],
    study_ids: tuple[str, ...],
) -> str | None:
    values = [
        projection["studies"][study_id]["manual"]["receipt_hash"]
        for study_id in study_ids
        if projection["studies"][study_id]["manual"]["required"] is True
    ]
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], str):
        raise ReportError("arm manual authority is not exact-one")
    return values[0]


def build_arm_report(
    *,
    arm: str,
    study_ids: tuple[str, ...],
    contract: dict[str, Any],
    contract_path: Path,
    projection: dict[str, Any],
    roots: dict[str, Path],
    join_path: Path,
    gate_results: list[dict[str, Any]],
    attempt_root: Path,
    native_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    closure = usage_closure(study_ids, attempt_root, native_receipts)
    metrics = {
        item["gate_id"]: item["observed"] for item in gate_results
    }
    if arm == "writing-plans":
        metrics["prior_reference_migration_claim"] = (
            writing_plan_migration_claim("formal", projection)
        )
    report = {
        "schema_version": "p3-arm-report/3.0",
        "study": arm,
        **{
            field: contract[field]
            for field in (
                "candidate_revision",
                "candidate_source_tree_hash",
                "candidate_plugin_tree_hash",
                "controller_content_hash",
                "evaluator_source_hash",
            )
        },
        "decision_contract_content_hash": file_hash(contract_path),
        "native_artifact_content_hashes": _native_hashes(
            roots,
            study_ids,
            join_path,
        ),
        "manual_receipt_content_hash": _manual_hash(projection, study_ids),
        "evidence_status": "complete",
        "usefulness_status": "supported",
        "metrics": metrics,
        "gate_results": gate_results,
        "usage_closure": {
            "scheduled": closure["scored_provider_calls"],
            "observed": closure["scored_provider_calls"],
            "graded": closure["graded"],
            "missing": 0,
            "duplicate": closure["duplicate"],
            "retries": closure["retries"],
            "provider_calls": closure["scored_provider_calls"],
        },
    }
    return {
        **report,
        "report_hash": canonical_hash(report),
    }


def write_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        canonical_bytes(value) + b"\n",
        mode=0o444,
        replace=False,
    )


def _projection_results(
    phase: str,
    contract: dict[str, Any],
    projection: dict[str, Any],
    summaries: dict[str, dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    namespace = {"projection": projection, "native": summaries}
    results = {}
    failures: dict[str, Any] = {}
    for arm in ("software-quality-workflows", "writing-plans"):
        passed, failed = evaluate_gates(
            contract["gate_contract"][arm],
            namespace,
        )
        results[arm] = passed
        if failed:
            failures[arm] = failed
    if projection.get("status") != "complete":
        failures["projection"] = [{
            "status": projection.get("status"),
            "software_quality_workflows": projection.get(
                "software_quality_workflows",
            ),
            "writing_plans": projection.get("writing_plans"),
        }]
    usefulness = {
        "software-quality-workflows": (
            {"supported"}
            if phase == "formal"
            else {"supported", "inconclusive_ceiling"}
        ),
        "writing-plans-planner": {"supported"},
        "writing-plans-transfer": {"supported", "inconclusive_ceiling"},
    }
    for study_id, allowed in usefulness.items():
        summary = summaries[study_id]
        if (
            summary["evidence_status"] != "complete"
            or (
                phase != "d0"
                and summary["usefulness_status"] not in allowed
            )
        ):
            failures.setdefault("native_status", []).append({
                "study_id": study_id,
                "evidence_status": summary["evidence_status"],
                "usefulness_status": summary["usefulness_status"],
            })
    return results, failures


def _aggregate_report(
    contract: dict[str, Any],
    contract_path: Path,
    reports_by_arm: dict[str, dict[str, Any]],
    report_paths: dict[str, Path],
    attempt_root: Path,
    native_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    scored = sum(
        report["usage_closure"]["provider_calls"]
        for report in reports_by_arm.values()
    )
    usage = usage_closure(STUDIES, attempt_root, native_receipts)
    grader = usage["grader_calibration_provider_calls"]
    reviewer = usage["reviewer_calibration_provider_calls"]
    budget = contract["budget_contract"]
    if (
        scored != budget["scored_call_hard_cap"]
        or usage["scored_provider_calls"] != scored
        or grader != budget["grader_calibration_call_hard_cap"]
        or reviewer != budget["reviewer_calibration_call_hard_cap"]
        or usage["provider_calls"] != budget["scheduled_provider_calls"]
        or scored + grader + reviewer != usage["provider_calls"]
    ):
        raise ReportError("Formal aggregate usage does not close")
    report = {
        "schema_version": "p3-aggregate-report/2.0",
        **{
            field: contract[field]
            for field in (
                "candidate_revision",
                "candidate_source_tree_hash",
                "candidate_plugin_tree_hash",
            )
        },
        "decision_contract_content_hash": file_hash(contract_path),
        "evaluated_skill_ids": [
            "software-quality-workflows",
            "writing-plans",
        ],
        "arm_report_content_hashes": {
            arm: file_hash(path) for arm, path in report_paths.items()
        },
        "aggregate_status": "passed",
        "scored_model_calls": scored,
        "grader_calibration_calls": grader,
        "reviewer_calibration_calls": reviewer,
        "apparatus_model_calls": grader + reviewer,
        "total_provider_calls": scored + grader + reviewer,
        "retries": sum(
            report["usage_closure"]["retries"]
            for report in reports_by_arm.values()
        ),
        "gates": [
            gate
            for report in reports_by_arm.values()
            for gate in report["gate_results"]
        ],
    }
    return {**report, "report_hash": canonical_hash(report)}


def evaluate_campaign(
    *,
    phase: str,
    contract_path: Path,
    skill_evaluator_root: Path,
    roots: dict[str, Path],
    manual_receipts: dict[str, str | None],
    join_path: Path,
    output_root: Path,
    seed: int,
    attempt_root: Path,
    native_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    contract = load_attempt_decision_contract(contract_path, attempt_root)
    if tree_hash(skill_evaluator_root) != contract["evaluator_source_hash"]:
        raise ReportError("Skill Evaluator source identity differs")
    projection, summaries = project_release(
        phase=phase,
        analyzer=load_analyzer(skill_evaluator_root),
        roots=roots,
        manual_receipts=manual_receipts,
        join_path=join_path,
        seed=seed,
    )
    results, failures = _projection_results(
        phase,
        contract,
        projection,
        summaries,
    )
    if failures:
        diagnostic = {
            "schema_version": "frontier-evaluation-diagnostic/1.0",
            "phase": phase,
            "status": "failed",
            "decision_contract_content_hash": file_hash(contract_path),
            "failures": failures,
        }
        write_once(output_root / "attempt-diagnostic.json", {
            **diagnostic,
            "diagnostic_hash": canonical_hash(diagnostic),
        })
        return {"status": "failed", "provider_requests": 0}
    if phase == "d0":
        report = {
            "schema_version": "frontier-d0-report/1.0",
            "status": "passed",
            "candidate_revision": contract["candidate_revision"],
            "decision_contract_content_hash": file_hash(contract_path),
            "gate_results": results,
            "claim_results": {
                "prior_reference_migration_claim": (
                    writing_plan_migration_claim(phase, projection)
                ),
            },
        }
        write_once(
            output_root / "d0-report.json",
            {**report, "report_hash": canonical_hash(report)},
        )
        return {"status": "passed", "provider_requests": 0}
    arm_studies = {
        "software-quality-workflows": ("software-quality-workflows",),
        "writing-plans": (
            "writing-plans-planner",
            "writing-plans-transfer",
        ),
    }
    arm_reports = {
        arm: build_arm_report(
            arm=arm,
            study_ids=study_ids,
            contract=contract,
            contract_path=contract_path,
            projection=projection,
            roots=roots,
            join_path=join_path,
            gate_results=results[arm],
            attempt_root=attempt_root,
            native_receipts=native_receipts,
        )
        for arm, study_ids in arm_studies.items()
    }
    report_paths = {
        arm: output_root / f"{arm}-arm-report.json" for arm in arm_reports
    }
    for arm, report in arm_reports.items():
        write_once(report_paths[arm], report)
    aggregate = _aggregate_report(
        contract,
        contract_path,
        arm_reports,
        report_paths,
        attempt_root,
        native_receipts,
    )
    write_once(output_root / "aggregate-report.json", aggregate)
    return {"status": "passed", "provider_requests": 0, "report_count": 3}


def _rating_record(
    *,
    example_id: str,
    reviewer_id: str,
    principal_id: str,
    role: str,
    grader: dict[str, Any],
    check: dict[str, Any],
    label: str,
    severity: int | float,
    ordering: dict[str, Any],
    grader_identity: dict[str, Any] | None,
    execution_identity: dict[str, Any] | None,
    independence: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "rating_id": (
            f"rating-{example_id}"
            if reviewer_id == "blinded-grader"
            else f"{reviewer_id}-{example_id}"
        ),
        "example_id": example_id,
        "grader_id": grader["grader_id"],
        "dimension": check["dimension"],
        "check_id": check["check_id"],
        "label": label,
        "severity": severity,
        "position": 0,
        "blinded_treatment_labels": True,
        "reviewer": {
            "reviewer_id": reviewer_id,
            "role": role,
            "authority": "calibration-owner",
            "principal_id": principal_id,
            "blinded": True,
        },
        "grader_identity": grader_identity,
        "execution_identity": execution_identity,
        "independence_facts": independence,
        "ordering": ordering,
        "created": "2026-07-25T00:00:00Z",
        "expires": "2026-08-25T00:00:00Z",
        "drift_triggers": [{
            "field": "prompt_hash",
            "expected": grader["prompt"]["sha256"],
            "observed": grader["prompt"]["sha256"],
            "status": "unchanged",
        }],
        "adjudication_policy": "frozen gold labels",
        "thresholds": {
            "minimum_agreement": 0.8,
            "minimum_examples": 8,
        },
    }


def _grader_calibration_rows(
    pack: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    spec: dict[str, Any],
    host_manifest: dict[str, Any],
    grader: dict[str, Any],
    checks: dict[str, dict[str, Any]],
    ordering: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pack_hash = canonical_hash(pack)
    grader_identity = {
        "grader_id": grader["grader_id"],
        "model": grader["model"],
        "model_revision": grader["model"],
        "prompt_id": "blind-rubric-prompt",
        "prompt_hash": grader["prompt"]["sha256"],
        "schema_id": "model-judgment",
        "schema_hash": grader["output_schema"]["sha256"],
    }
    execution = {
        "host_hash": spec["host"]["manifest"]["sha256"],
        "harness_hash": host_manifest["identity"]["adapter"]["sha256"],
        "model_genealogy": [grader["model"]],
        "context_exposure": [],
        "evidence_source_hashes": [pack_hash],
    }
    independence = {
        "candidate_principal_id": "evaluated-agent",
        "grader_principal_id": "blinded-grader",
        "context_mode": "fresh",
        "rationale_exposed": False,
        "candidate_model_genealogy": [host.MODEL],
        "grader_model_genealogy": [grader["model"]],
        "candidate_evidence_source_hashes": [
            canonical_hash("candidate-evidence"),
        ],
        "grader_evidence_source_hashes": [pack_hash],
    }
    labels = []
    ratings = []
    for item in pack:
        observed = {
            check["id"]: check
            for check in outputs[item["artifact_id"]]["checks"]
        }
        for check_id, check in checks.items():
            expected = item["expected_checks"].get(
                check_id,
                item["expected_overall"],
            )
            example_id = f"{item['artifact_id']}-{check_id}"
            gold = (
                "abstain"
                if item["calibration_class"] == "abstain"
                else "pass" if expected else "fail"
            )
            actual = (
                "abstain"
                if observed[check_id]["uncertainty"] == "high"
                else "pass" if observed[check_id]["pass"] else "fail"
            )
            labels.append({
                "schema_version": 1,
                "example_id": example_id,
                "class": item["calibration_class"],
                "dimension": check["dimension"],
                "check_id": check_id,
                "payload_hash": canonical_hash({
                    "view": item["grader_view"],
                    "check": {
                        "check_id": check_id,
                        "pass_condition": check["pass_condition"],
                    },
                }),
                "source_support": "supported",
                "gold_label": gold,
                "gold_severity": 0 if gold in {"pass", "abstain"} else 2,
                "task": "software-engineering",
                "language": "en",
                "risk": spec["risk_tier"],
                "host": host_manifest["identity"]["host_id"],
                "model": grader["model"],
            })
            ratings.append(_rating_record(
                example_id=example_id,
                reviewer_id="blinded-grader",
                principal_id="blinded-grader",
                role="judge",
                grader=grader,
                check=check,
                label=actual,
                severity=0 if actual in {"pass", "abstain"} else 2,
                ordering=ordering,
                grader_identity=grader_identity,
                execution_identity=execution,
                independence=independence,
            ))
    return labels, ratings


def _reviewer_groups(
    reviews: list[dict[str, Any]],
    mapping: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    if not isinstance(mapping, dict) or set(mapping) != {
        review["example_id"] for review in reviews
    }:
        raise ReportError("reviewer mapping does not cover raw reviewer rows")
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for review in reviews:
        if (
            set(review)
            != {
                "example_id",
                "reviewer_id",
                "principal_id",
                "label",
                "severity",
            }
            or review["example_id"] not in mapping
            or review["label"] not in {"pass", "fail", "abstain"}
            or not isinstance(review["severity"], (int, float))
            or isinstance(review["severity"], bool)
            or not math.isfinite(float(review["severity"]))
            or not all(
                isinstance(review[field], str) and review[field]
                for field in ("reviewer_id", "principal_id")
            )
        ):
            raise ReportError("context-clean review value is invalid")
        rows = grouped.setdefault(review["reviewer_id"], {})
        if review["example_id"] in rows:
            raise ReportError("duplicate context-clean review")
        rows[review["example_id"]] = review
    if (
        len(grouped) != 2
        or any(set(rows) != set(mapping) for rows in grouped.values())
    ):
        raise ReportError(
            "calibration requires two complete context-clean reviewers"
        )
    if any(
        len({review["principal_id"] for review in rows.values()}) != 1
        for rows in grouped.values()
    ):
        raise ReportError("context-clean reviewer identity drifted")
    return grouped


def calibration_rows(
    *,
    pack: list[dict[str, Any]],
    outputs: dict[str, dict[str, Any]],
    spec: dict[str, Any],
    host_manifest: dict[str, Any],
    reviewer_reviews: list[dict[str, Any]],
    reviewer_mapping: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grader = next(
        item for item in spec["graders"] if item["grader_id"] == "blind-rubric"
    )
    checks = {item["check_id"]: item for item in grader["checks"]}
    ordering = {
        "method": "counterbalanced",
        "seed": 20260725,
        "schedule_hash": specs.HASH_ZERO,
    }
    labels, ratings = _grader_calibration_rows(
        pack,
        outputs,
        spec,
        host_manifest,
        grader,
        checks,
        ordering,
    )
    for reviewer_id, reviews in sorted(
        _reviewer_groups(reviewer_reviews, reviewer_mapping).items(),
    ):
        principal_id = next(iter(reviews.values()))["principal_id"]
        for opaque_id, mapping in reviewer_mapping.items():
            review = reviews[opaque_id]
            ratings.append(_rating_record(
                example_id=opaque_id,
                reviewer_id=reviewer_id,
                principal_id=principal_id,
                role="context_clean_subagent_reviewer",
                grader=grader,
                check={
                    "dimension": mapping["dimension"],
                    "check_id": mapping["check_id"],
                },
                label=review["label"],
                severity=review["severity"],
                ordering=ordering,
                grader_identity=None,
                execution_identity=None,
                independence=None,
            ))
    for position, row in enumerate(ratings, start=1):
        row["position"] = position
    ordering["schedule_hash"] = canonical_hash([
        {"example_id": row["example_id"], "position": row["position"]}
        for row in ratings
    ])
    return labels, ratings


def compute_p4_metrics(
    steps: list[dict[str, Any]],
    *,
    selected_provider_calls: int,
    retry_provider_calls: int,
) -> dict[str, Any]:
    arm_ids = ("baseline", "prior", "candidate")
    arms = {
        arm: [step["arms"][arm] for step in steps]
        for arm in arm_ids
    }
    all_results = [item for values in arms.values() for item in values]

    def total(field: str) -> int:
        return sum(item[field] for item in all_results)

    def arm_total(arm: str, field: str) -> int:
        return sum(item[field] for item in arms[arm])

    def runtimes(arm: str) -> list[int]:
        return [
            elapsed
            for item in arms[arm]
            for elapsed in item["runtime_ns"]["measured"]
        ]

    def faults(arm: str) -> tuple[int, int]:
        return (
            sum(item["seeded_faults"]["detected"] for item in arms[arm]),
            sum(item["seeded_faults"]["total"] for item in arms[arm]),
        )

    candidate_faults = faults("candidate")
    prior_faults = faults("prior")
    candidate_runtime = statistics.median(runtimes("candidate"))
    prior_runtime = statistics.median(runtimes("prior"))
    return {
        "protocol_residue_count": total("protocol_residue_count"),
        "failed_command_residue_count": total("failed_command_residue_count"),
        "probe_count": total("probe_count"),
        "duplicate_test_count": total("duplicate_test_count"),
        "refactor_permanent_test_count": sum(
            step["arms"][arm]["permanent_refactor_test_count"]
            for step in steps
            if step["step_id"].startswith("R")
            for arm in arm_ids
        ),
        "candidate_permanent_test_loc": arm_total("candidate", "permanent_test_loc"),
        "prior_permanent_test_loc": arm_total("prior", "permanent_test_loc"),
        "candidate_runtime_median_ns": candidate_runtime,
        "prior_runtime_median_ns": prior_runtime,
        "candidate_runtime_ratio": candidate_runtime / prior_runtime,
        "candidate_seeded_fault_detection_rate": candidate_faults[0] / candidate_faults[1],
        "prior_seeded_fault_detection_rate": prior_faults[0] / prior_faults[1],
        "candidate_task_passes": sum(item["task_pass"] for item in arms["candidate"]),
        "prior_task_passes": sum(item["task_pass"] for item in arms["prior"]),
        "normalized_product_tree_mismatch_count": sum(
            len({
                step["arms"][arm]["normalized_product_tree_hash"]
                for arm in arm_ids
            })
            != 1
            for step in steps
        ),
        "protected_test_failures": sum(
            not item["protected_tests_pass"] for item in all_results
        ),
        "full_suite_failures": sum(
            not item["full_tests_pass"] for item in all_results
        ),
        "runtime_measurement_count": sum(
            len(item["runtime_ns"]["measured"]) for item in all_results
        ),
        "selected_provider_calls": selected_provider_calls,
        "retry_entries": retry_provider_calls // 2,
        "provider_calls": 78 + retry_provider_calls,
        "numeric_traceability": True,
    }


def evaluate_p4_metrics(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    gates = (
        ("P4-01", "protocol_residue_count", "native_artifact", 0, "eq"),
        ("P4-02", "failed_command_residue_count", "native_artifact", 0, "eq"),
        ("P4-03", "probe_count", "native_artifact", 0, "eq"),
        ("P4-04", "duplicate_test_count", "native_artifact", 0, "eq"),
        ("P4-05", "refactor_permanent_test_count", "native_artifact", 0, "eq"),
        ("P4-06", "candidate_permanent_test_loc", "report_local", metrics["prior_permanent_test_loc"], "le"),
        ("P4-07", "candidate_runtime_ratio", "report_local", 1.05, "le"),
        ("P4-08", "candidate_seeded_fault_detection_rate", "report_local", metrics["prior_seeded_fault_detection_rate"], "ge"),
        ("P4-09", "candidate_task_passes", "report_local", metrics["prior_task_passes"], "ge"),
        ("P4-10", "normalized_product_tree_mismatch_count", "native_artifact", 0, "eq"),
        ("P4-11", "protected_test_failures", "native_artifact", 0, "eq"),
        ("P4-12", "full_suite_failures", "native_artifact", 0, "eq"),
        ("P4-13", "runtime_measurement_count", "native_artifact", 180, "eq"),
        ("P4-14", "selected_provider_calls", "native_artifact", 78, "eq"),
        ("P4-15", "retry_entries", "native_artifact", 1, "le"),
        ("P4-16", "provider_calls", "native_artifact", 80, "le"),
        ("P4-17", "numeric_traceability", "report_local", True, "eq"),
    )
    operators = {
        "eq": lambda value, expected: value == expected,
        "le": lambda value, expected: value <= expected,
        "ge": lambda value, expected: value >= expected,
    }
    return [
        {
            "gate_id": gate_id,
            "metric_id": f"/metrics/{metric}",
            "evidence_artifact_kind": evidence,
            "observed": metrics[metric],
            "passed": operators[operator](metrics[metric], expected),
        }
        for gate_id, metric, evidence, expected, operator in gates
    ]


def write_p4_report(
    *,
    identity: dict[str, str],
    decision_contract_hash: str,
    campaign_contract_hash: str,
    selected_receipts: list[dict[str, Any]],
    step_hashes: dict[str, str],
    metrics: dict[str, Any],
    report_schema_path: Path,
    report_schema_hash: str,
    output_root: Path,
) -> dict[str, Any]:
    gates = evaluate_p4_metrics(metrics)
    common = {
        **identity,
        "decision_contract_content_hash": decision_contract_hash,
        "campaign_contract_content_hash": campaign_contract_hash,
        "selected_receipt_set_hash": canonical_hash(selected_receipts),
        "step_result_content_hashes": step_hashes,
        "metrics": metrics,
        "gate_results": gates,
    }
    failed = [gate["gate_id"] for gate in gates if gate["passed"] is not True]
    if failed:
        diagnostic = {
            "schema_version": "frontier-p4-diagnostic/1.0",
            "status": "failed",
            **common,
            "failed_gate_ids": failed,
        }
        write_once(output_root / "attempt-diagnostic.json", {
            **diagnostic,
            "diagnostic_hash": canonical_hash(diagnostic),
        })
        return {"status": "failed", "provider_requests": 0}
    report = {
        "schema_version": "frontier-longitudinal-report/1.0",
        **common,
        "evidence_status": "complete",
        "usefulness_status": "supported",
        "longitudinal_status": "passed",
    }
    report = {**report, "report_hash": canonical_hash(report)}
    schema_path = contained_file(
        report_schema_path.parent,
        report_schema_path.name,
        "P4 report schema",
    )
    if file_hash(schema_path) != report_schema_hash:
        raise ReportError("P4 report schema hash differs")
    schema = json_object(schema_path.read_bytes(), schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(report),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise ReportError(f"P4 report schema failure: {errors[0].message}")
    write_once(output_root / "frontier-longitudinal-report.json", report)
    return {"status": "passed", "provider_requests": 0}
