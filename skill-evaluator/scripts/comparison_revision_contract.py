"""Revision-specific identity, evidence, and allowed-difference contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from comparison_contract import CycleCapsule, make_diagnostic
from evidence_io import canonical_json_bytes, file_sha256


_FIXED_EXECUTION_IDENTITY = (
    "model_hash",
    "harness_hash",
    "prompt_hash",
    "tool_surface_hash",
    "policy_hash",
    "runtime_hash",
    "tokenizer_pricing_hash",
    "clock_hash",
)
_SPEC_STABLE_FIELDS = (
    "schema_version",
    "level",
    "risk_tier",
    "applicability",
    "treatments",
    "graders",
    "analysis",
    "hard_gates",
    "execution",
    "authority",
    "decision",
    "artifacts",
)
_PLAN_STABLE_FIELDS = (
    "schema_version",
    "grader_set_hash",
    "calibration_hash",
    "subject_shape",
    "module_decisions",
    "dimension_coverage",
    "expected_counts",
    "ordering",
    "compiler",
    "authority",
    "artifacts",
)
_TREATMENT_DERIVED_FIELDS = {
    "base_catalog_hash",
    "delivery_transform_hash",
    "host_identity",
    "implementation_hash",
}


def same(left: Any, right: Any) -> bool:
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _difference_paths(
    left: Any,
    right: Any,
    path: str = "",
) -> list[str]:
    if type(left) is not type(right):
        return [path or "/"]
    if isinstance(left, dict):
        paths = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{key}"
            if key not in left or key not in right:
                paths.append(child)
            else:
                paths.extend(_difference_paths(left[key], right[key], child))
            if len(paths) >= 16:
                break
        return paths[:16]
    if isinstance(left, list):
        if len(left) != len(right):
            return [path or "/"]
        paths = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            paths.extend(_difference_paths(
                left_item,
                right_item,
                f"{path}/{index}",
            ))
            if len(paths) >= 16:
                break
        return paths[:16]
    return [] if left == right else [path or "/"]


def _project_subject(subject: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(subject)
    package = projected["package"]
    projected["package"] = {
        "path": package["path"],
        "dirty_state": package["dirty_state"],
    }
    projected.pop("version", None)
    return projected


def _project_suite(suite: dict[str, Any]) -> dict[str, Any]:
    projected = deepcopy(suite)
    for binding_name in ("scenarios", "public_scenarios"):
        projected[binding_name].pop("sha256", None)
    holdout = projected.get("holdout")
    if isinstance(holdout, dict):
        holdout["manifest"].pop("sha256", None)
        holdout["payload"].pop("sha256", None)
    quality = projected.get("quality")
    if isinstance(quality, dict):
        quality.pop("sha256", None)
    projected.pop("fixture_set_hash", None)
    projected.pop("quality_contract_hash", None)
    return projected


def _project_spec(spec: dict[str, Any]) -> dict[str, Any]:
    projected = {field: deepcopy(spec[field]) for field in _SPEC_STABLE_FIELDS}
    projected["subject"] = _project_subject(spec["subject"])
    projected["suite"] = _project_suite(spec["suite"])
    projected["host_required_capabilities"] = deepcopy(
        spec["host"]["required_capabilities"],
    )
    return projected


def _project_treatment(treatment: dict[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(value)
        for key, value in treatment.items()
        if key not in _TREATMENT_DERIVED_FIELDS
    }


def _project_catalog_entries(
    entries: list[dict[str, Any]],
    subject_id: str,
) -> list[dict[str, Any]]:
    projected_entries = []
    for entry in entries:
        projected = deepcopy(entry)
        if projected["id"] == subject_id:
            projected.pop("root_hash", None)
            projected.pop("version", None)
        projected_entries.append(projected)
    return projected_entries


def _project_entry(
    entry: dict[str, Any],
    subject_id: str,
) -> dict[str, Any]:
    projected = deepcopy(entry)
    for field in (
        "entry_id",
        "artifact_relpath",
        "workspace",
        "catalog_hash",
        "treatment_hash",
        "scenario_hash",
        "fixture_hash",
    ):
        projected.pop(field, None)
    payload = projected.get("execute_case_payload")
    if isinstance(payload, dict):
        payload.pop("workspace", None)
        payload["catalog"] = _project_catalog_entries(
            payload["catalog"],
            subject_id,
        )
        payload["treatment"] = _project_treatment(payload["treatment"])
        payload["fixture"].pop("sha256", None)
        payload["case"]["fixture"].pop("sha256", None)
    return projected


def _project_plan(plan: dict[str, Any], subject_id: str) -> dict[str, Any]:
    projected = {field: deepcopy(plan[field]) for field in _PLAN_STABLE_FIELDS}
    projected["catalog"] = _project_catalog_entries(
        plan["catalog"],
        subject_id,
    )
    projected["treatments"] = [
        _project_treatment(item) for item in plan["treatments"]
    ]
    projected["entries"] = [
        _project_entry(entry, subject_id)
        for entry in plan["entries"]
    ]
    return projected


def cycle_spec_projection(spec: dict[str, Any]) -> dict[str, Any]:
    """Return cycle semantics with identity-derived bindings removed."""
    return _project_spec(spec)


def cycle_plan_projection(
    plan: dict[str, Any],
    subject_id: str,
) -> dict[str, Any]:
    """Return execution semantics with cycle-derived identities removed."""
    return _project_plan(plan, subject_id)


def _project_catalog(
    catalog: dict[str, Any],
    subject_id: str,
) -> list[dict[str, Any]]:
    return _project_catalog_entries(catalog["entries"], subject_id)


def _project_host(host: dict[str, Any], subject_id: str) -> dict[str, Any]:
    identity = host["identity"]
    execution = deepcopy(identity["execution"])
    execution.pop("skill_hash", None)
    execution.pop("catalog_hash", None)
    return {
        "identity": {
            "host_id": identity["host_id"],
            "host_name": identity["host_name"],
            "host_version": identity["host_version"],
            "host_build": identity["host_build"],
            "adapter": deepcopy(identity["adapter"]),
            "platform": deepcopy(identity["platform"]),
            "repository_dirty": identity["repository"]["dirty"],
            "session_topology": identity["session"]["topology"],
            "execution": execution,
        },
        "catalog_entries": _project_catalog(host["catalog"], subject_id),
        "capabilities": deepcopy(host["capabilities"]),
        "capture": deepcopy(host["capture"]),
        "command": deepcopy(host["command"]),
        "policy": deepcopy(host["policy"]),
        "reset": deepcopy(host["reset"]),
    }


def _subject_package_bindings(
    capsule: CycleCapsule,
    subject_id: str,
) -> dict[str, str | None]:
    catalog_hashes = [
        item["root_hash"]
        for item in capsule.host_manifest["catalog"]["entries"]
        if item["id"] == subject_id
    ]
    return {
        "spec.package_hash": capsule.spec["subject"]["package"]["package_hash"],
        "plan.package_hash": capsule.execution_plan["package_hashes"].get(
            subject_id,
        ),
        "plan.subject_hash": capsule.execution_plan["execution_identity"][
            "subject_hash"
        ],
        "host.skill_hash": capsule.host_manifest["identity"]["execution"][
            "skill_hash"
        ],
        "host.catalog_root_hash": (
            catalog_hashes[0] if len(catalog_hashes) == 1 else None
        ),
    }


def estimand(spec: dict[str, Any], metric_id: str) -> dict[str, Any] | None:
    matches = [
        item
        for item in spec["analysis"]["estimands"]
        if item["estimand_id"] == metric_id
    ]
    return matches[0] if len(matches) == 1 else None


def artifact_source(
    plan: dict[str, Any],
    capsule: CycleCapsule,
    artifact: str,
) -> tuple[str, str]:
    path = plan["input_bindings"][capsule.role][artifact]["path"]
    source_hash = capsule.file_hashes[artifact]
    assert isinstance(source_hash, str)
    return path, source_hash


def capsule_diagnostic(
    plan: dict[str, Any],
    capsule: CycleCapsule,
    artifact: str,
    *,
    fact_type: str,
    reason_key: str,
    expected: Any,
    observed: Any,
    json_pointer: str,
    roles: list[str] | None = None,
    case_ids: list[str] | None = None,
    requirement_ids: list[str] | None = None,
    metric_ids: list[str] | None = None,
) -> dict[str, Any]:
    path, source_hash = artifact_source(plan, capsule, artifact)
    return make_diagnostic(
        severity="high",
        fact_type=fact_type,
        reason_key=reason_key,
        roles=roles or [capsule.role],
        expected=expected,
        observed=observed,
        locator_artifact=path,
        json_pointer=json_pointer,
        source_hash=source_hash,
        case_ids=case_ids,
        requirement_ids=requirement_ids,
        metric_ids=metric_ids,
    )


def plan_diagnostic(
    plan_path: Path,
    *,
    fact_type: str,
    reason_key: str,
    expected: Any,
    observed: Any,
    json_pointer: str,
    roles: list[str] | None = None,
) -> dict[str, Any]:
    return make_diagnostic(
        severity="high",
        fact_type=fact_type,
        reason_key=reason_key,
        roles=roles or ["prior", "candidate"],
        expected=expected,
        observed=observed,
        locator_artifact=plan_path.name,
        json_pointer=json_pointer,
        source_hash=file_sha256(plan_path),
    )


def identity_diagnostics(
    plan: dict[str, Any],
    prior: CycleCapsule,
    candidate: CycleCapsule,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    prior_identity = prior.execution_plan["execution_identity"]
    candidate_identity = candidate.execution_plan["execution_identity"]
    identity_mismatches = [
        field
        for field in _FIXED_EXECUTION_IDENTITY
        if prior_identity[field] != candidate_identity[field]
    ]
    if identity_mismatches:
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "execution_plan",
            fact_type="identity_mismatch",
            reason_key="revision_execution_identity_drift",
            expected="model, harness, prompt, tools, policy, runtime, tokenizer, and clock match",
            observed=identity_mismatches,
            json_pointer="/execution_identity",
        ))

    if not same(
        cycle_spec_projection(prior.spec),
        cycle_spec_projection(candidate.spec),
    ):
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "spec",
            fact_type="identity_mismatch",
            reason_key="revision_spec_contract_drift",
            expected="the non-package evaluation contract matches the prior cycle",
            observed="the stable spec projection differs",
            json_pointer="",
        ))
    subject_id = prior.spec["subject"]["skill_id"]
    prior_plan_projection = cycle_plan_projection(
        prior.execution_plan,
        subject_id,
    )
    candidate_plan_projection = cycle_plan_projection(
        candidate.execution_plan,
        subject_id,
    )
    if not same(prior_plan_projection, candidate_plan_projection):
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "execution_plan",
            fact_type="identity_mismatch",
            reason_key="revision_execution_contract_drift",
            expected="suite, treatment, fixture, grader, ordering, and count projections match",
            observed=_difference_paths(
                prior_plan_projection,
                candidate_plan_projection,
            ),
            json_pointer="",
        ))

    if candidate.spec["subject"]["skill_id"] != subject_id or not same(
        _project_host(prior.host_manifest, subject_id),
        _project_host(candidate.host_manifest, subject_id),
    ):
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "host_manifest",
            fact_type="identity_mismatch",
            reason_key="revision_host_contract_drift",
            expected="host behavior is unchanged outside the subject Skill binding",
            observed="the stable host projection or subject Skill ID differs",
            json_pointer="",
        ))

    change_set = plan["decision_policy"]["change_set"]
    candidate_hash = change_set["candidate_hash"]
    package_root = PurePosixPath(candidate.spec["subject"]["package"]["path"])
    invalid_paths = [
        path
        for path in change_set["paths"]
        if not PurePosixPath(path).is_relative_to(package_root)
    ]
    prior_hash = prior.spec["subject"]["package"]["package_hash"]
    inconsistent_bindings = {
        capsule.role: [
            label
            for label, value in _subject_package_bindings(
                capsule,
                subject_id,
            ).items()
            if value != capsule.spec["subject"]["package"]["package_hash"]
        ]
        for capsule in (prior, candidate)
    }
    candidate_binding_mismatches = [
        label
        for label, value in _subject_package_bindings(
            candidate,
            subject_id,
        ).items()
        if value != candidate_hash
    ]
    prior_other_packages = {
        key: value
        for key, value in prior.execution_plan["package_hashes"].items()
        if key != subject_id
    }
    candidate_other_packages = {
        key: value
        for key, value in candidate.execution_plan["package_hashes"].items()
        if key != subject_id
    }
    if (
        invalid_paths
        or any(inconsistent_bindings.values())
        or candidate_binding_mismatches
        or prior_other_packages != candidate_other_packages
        or prior_hash == candidate_hash
    ):
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "spec",
            fact_type="identity_mismatch",
            reason_key="revision_change_set_binding_invalid",
            expected="one changed package binds the declared paths and candidate hash",
            observed={
                "invalid_paths": invalid_paths,
                "inconsistent_cycle_bindings": inconsistent_bindings,
                "candidate_hash_mismatches": candidate_binding_mismatches,
                "other_packages_match": (
                    prior_other_packages == candidate_other_packages
                ),
                "candidate_differs_from_prior": prior_hash != candidate_hash,
            },
            json_pointer="/subject/package",
        ))
    return diagnostics


def evidence_diagnostics(
    plan: dict[str, Any],
    capsules: tuple[CycleCapsule, CycleCapsule],
) -> list[dict[str, Any]]:
    diagnostics = []
    for capsule in capsules:
        summary = capsule.summary
        observed = {
            "analysis_ready": summary["analysis_ready"],
            "evidence_status": summary["evidence_status"],
            "feasibility_status": summary["feasibility_status"],
        }
        if observed != {
            "analysis_ready": True,
            "evidence_status": "complete",
            "feasibility_status": "feasible",
        }:
            diagnostics.append(capsule_diagnostic(
                plan,
                capsule,
                "summary",
                fact_type="evidence_gap",
                reason_key="revision_cycle_evidence_incomplete",
                expected="analysis-ready, complete, feasible cycle evidence",
                observed=observed,
                json_pointer="/analysis_ready",
            ))
    return diagnostics


def failure_index_complete(capsule: CycleCapsule) -> bool:
    index = capsule.failure_index
    return bool(
        index is not None
        and index["truncated"] is False
        and index["omitted_count"] == 0
    )
