"""Revision-specific identity, evidence, and allowed-difference contract."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

from comparison_contract import CycleCapsule, make_diagnostic
from evidence_io import (
    canonical_json_bytes,
    file_sha256,
    load_json,
    normalize_relative_path,
    resolve_contained_path,
)


_FIXED_EXECUTION_PROFILE = (
    "host_id",
    "host_version",
    "provider",
    "model",
    "model_revision",
    "harness",
    "harness_version",
    "platform",
    "command_id",
    "catalog_ids",
    "prompt_id",
    "tool_schema_id",
    "policy_id",
    "tokenizer_id",
    "pricing_id",
    "utc_clock_id",
    "monotonic_clock_id",
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
    "subject_shape",
    "module_decisions",
    "dimension_coverage",
    "expected_counts",
    "ordering",
    "authority",
    "artifacts",
)


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
    holdout = projected.get("holdout")
    if isinstance(holdout, dict):
        holdout["manifest"].pop("digest", None)
        holdout["payload"].pop("digest", None)
    for field in ("quality", "calibration"):
        binding = projected.get(field)
        if isinstance(binding, dict):
            binding.pop("digest", None)
    return projected


def _project_graders(graders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = deepcopy(graders)
    for grader in projected:
        verifier = grader.get("verifier")
        if isinstance(verifier, dict):
            verifier.pop("source_revision", None)
    return projected


def _project_spec(spec: dict[str, Any]) -> dict[str, Any]:
    projected = {field: deepcopy(spec[field]) for field in _SPEC_STABLE_FIELDS}
    projected["subject"] = _project_subject(spec["subject"])
    projected["suite"] = _project_suite(spec["suite"])
    projected["graders"] = _project_graders(spec["graders"])
    projected["host_required_capabilities"] = deepcopy(
        spec["host"]["required_capabilities"],
    )
    return projected


def _project_treatment(treatment: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(treatment)


def _project_catalog_entries(
    entries: list[dict[str, Any]],
    subject_id: str,
    *,
    bundle_mode: bool = False,
) -> list[dict[str, Any]]:
    projected_entries = []
    for entry in entries:
        projected = deepcopy(entry)
        if bundle_mode or projected["id"] == subject_id:
            projected.pop("root_digest", None)
            projected.pop("version", None)
        if bundle_mode:
            projected.pop("description", None)
        projected_entries.append(projected)
    return projected_entries


def _project_entry(
    entry: dict[str, Any],
    subject_id: str,
    *,
    bundle_mode: bool = False,
) -> dict[str, Any]:
    projected = deepcopy(entry)
    projected.pop("artifact_relpath", None)
    payload = projected.get("execute_case_payload")
    if isinstance(payload, dict):
        payload.pop("workspace", None)
        payload["catalog"] = _project_catalog_entries(
            payload["catalog"],
            subject_id,
            bundle_mode=bundle_mode,
        )
        payload["treatment"] = _project_treatment(payload["treatment"])
        payload["fixture"].pop("sha256", None)
        payload["case"]["fixture"].pop("sha256", None)
    return projected


def _project_plan(
    plan: dict[str, Any], subject_id: str, *, bundle_mode: bool = False
) -> dict[str, Any]:
    projected = {field: deepcopy(plan[field]) for field in _PLAN_STABLE_FIELDS}
    projected["compiler"] = {
        key: deepcopy(value)
        for key, value in plan["compiler"].items()
        if key != "source_revision"
    }
    projected["catalog"] = _project_catalog_entries(
        plan["catalog"],
        subject_id,
        bundle_mode=bundle_mode,
    )
    projected["treatments"] = [
        _project_treatment(item) for item in plan["treatments"]
    ]
    projected["entries"] = [
        _project_entry(entry, subject_id, bundle_mode=bundle_mode)
        for entry in plan["entries"]
    ]
    return projected


def cycle_spec_projection(spec: dict[str, Any]) -> dict[str, Any]:
    """Return cycle semantics with identity-derived bindings removed."""
    return _project_spec(spec)


def cycle_plan_projection(
    plan: dict[str, Any],
    subject_id: str,
    *,
    bundle_mode: bool = False,
) -> dict[str, Any]:
    """Return execution semantics with cycle-derived identities removed."""
    return _project_plan(plan, subject_id, bundle_mode=bundle_mode)


def _project_catalog(
    catalog: dict[str, Any],
    subject_id: str,
    *,
    bundle_mode: bool = False,
) -> list[dict[str, Any]]:
    return _project_catalog_entries(
        catalog["entries"], subject_id, bundle_mode=bundle_mode
    )


def _project_host(
    host: dict[str, Any], subject_id: str, *, bundle_mode: bool = False
) -> dict[str, Any]:
    identity = host["identity"]
    execution = deepcopy(identity["execution"])
    command = deepcopy(host["command"])
    if bundle_mode:
        execution.pop("catalog_id", None)
        argv = command["argv"]
        for option in ("--host-manifest", "--plugin-root"):
            positions = [index for index, item in enumerate(argv) if item == option]
            if len(positions) == 1 and positions[0] + 1 < len(argv):
                argv[positions[0] + 1] = f"<{option[2:]}>"
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
        "catalog_entries": _project_catalog(
            host["catalog"], subject_id, bundle_mode=bundle_mode
        ),
        "capabilities": deepcopy(host["capabilities"]),
        "capture": deepcopy(host["capture"]),
        "command": command,
        "policy": deepcopy(host["policy"]),
        "reset": deepcopy(host["reset"]),
    }


def _subject_package_bindings(
    capsule: CycleCapsule,
    subject_id: str,
) -> dict[str, str | None]:
    catalog_digests = [
        item["root_digest"]
        for item in capsule.host_manifest["catalog"]["entries"]
        if item["id"] == subject_id
    ]
    return {
        "spec.package_digest": capsule.spec["subject"]["package"][
            "package_digest"
        ],
        "plan.package_digest": capsule.execution_plan["package_digests"].get(
            subject_id,
        ),
        "host.catalog_root_digest": (
            catalog_digests[0] if len(catalog_digests) == 1 else None
        ),
        "spec.source_revision": capsule.spec["subject"]["package"][
            "source_revision"
        ],
        "plan.source_revision": capsule.execution_plan["source_revision"],
        "profile.source_revision": capsule.execution_plan[
            "execution_profile"
        ]["source_revision"],
    }


def _bundle_product_problems(
    capsule: CycleCapsule,
    product: dict[str, Any],
) -> list[str]:
    plan = capsule.execution_plan
    subject = capsule.spec["subject"]
    catalog_rows = capsule.host_manifest["catalog"]["entries"]
    catalog = {
        row["id"]: row
        for row in catalog_rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    skill_ids = set(product["skills"])
    problems: list[str] = []
    if (
        product["source_revision"] != plan["source_revision"]
        or product["source_revision"]
        != plan["execution_profile"]["source_revision"]
        or product["source_revision"]
        != subject["package"]["source_revision"]
    ):
        problems.append("source revision differs from the cycle")
    if (
        skill_ids != set(plan["package_digests"])
        or skill_ids != set(catalog)
        or len(catalog) != len(catalog_rows)
    ):
        problems.append("Skill set differs from plan or Host catalog")
        return problems
    for skill_id, expected in product["skills"].items():
        row = catalog[skill_id]
        if (
            expected["root_hash"] != plan["package_digests"][skill_id]
            or expected["root_hash"] != row["root_digest"]
        ):
            problems.append(f"{skill_id} root hash differs")
        if expected["version"] != row["version"]:
            problems.append(f"{skill_id} version differs")
    subject_id = subject["skill_id"]
    if product["skills"][subject_id]["version"] != subject["version"]:
        problems.append("subject version differs")
    return problems


def _bundle_build_problems(
    plan_path: Path,
    role: str,
    product: dict[str, Any],
) -> list[str]:
    binding = product["build_evidence"]
    try:
        relative = normalize_relative_path(
            binding["path"], f"{role} Bundle build evidence"
        )
        cursor = plan_path.parent
        for part in PurePosixPath(relative).parts:
            cursor /= part
            if cursor.is_symlink():
                raise ValueError("path contains a symlink")
        _, path = resolve_contained_path(
            plan_path.parent,
            relative,
            f"{role} Bundle build evidence",
            kind="file",
        )
        if file_sha256(path) != binding["digest"]:
            raise ValueError("digest differs")
        evidence = load_json(path)
    except (OSError, TypeError, ValueError) as exc:
        return [f"build evidence is invalid: {exc}"]
    expected = {
        "schema_version": "plugin-build-evidence/4.0",
        "source_revision": product["source_revision"],
        "source_tree_hash": product["source_tree_hash"],
        "plugin_tree_hash": product["plugin_tree_hash"],
        "bundle_id": product["bundle_id"],
        "bundle_version": product["bundle_version"],
        "skill_versions": {
            skill_id: row["version"] for skill_id, row in product["skills"].items()
        },
        "skill_activation": {
            skill_id: row["allow_implicit_invocation"]
            for skill_id, row in product["skills"].items()
        },
        "output_class": "staging",
    }
    return [
        f"build evidence {field} differs"
        for field, value in expected.items()
        if evidence.get(field) != value
    ]


def _bundle_identity_diagnostics(
    plan_path: Path,
    plan: dict[str, Any],
    prior: CycleCapsule,
    candidate: CycleCapsule,
) -> list[dict[str, Any]]:
    policy = plan["decision_policy"]
    products = policy["bundle_products"]
    assert isinstance(products, dict)
    problems = {
        role: [
            *_bundle_product_problems(capsule, products[role]),
            *_bundle_build_problems(plan_path, role, products[role]),
        ]
        for role, capsule in (("prior", prior), ("candidate", candidate))
    }
    prior_skills = products["prior"]["skills"]
    candidate_skills = products["candidate"]["skills"]
    change_set = policy["change_set"]
    if set(prior_skills) != set(candidate_skills):
        problems["cross_cycle"] = ["Bundle Skill sets differ"]
    else:
        cross_cycle = []
        if products["prior"]["source_revision"] == products["candidate"]["source_revision"]:
            cross_cycle.append("source revisions are identical")
        if products["prior"]["plugin_tree_hash"] == products["candidate"]["plugin_tree_hash"]:
            cross_cycle.append("plugin tree hashes are identical")
        if products["candidate"]["source_revision"] != change_set["candidate_revision"]:
            cross_cycle.append("candidate revision differs from the change set")
        if change_set["category"] != "bundle":
            cross_cycle.append("change-set category is not bundle")
        if set(change_set["paths"]) != set(candidate_skills):
            cross_cycle.append("change-set paths differ from the Bundle Skill roots")
        if not any(
            prior_skills[skill_id]["root_hash"]
            != candidate_skills[skill_id]["root_hash"]
            for skill_id in candidate_skills
        ):
            cross_cycle.append("no Skill package changed")
        problems["cross_cycle"] = cross_cycle
    if not any(problems.values()):
        return []
    return [capsule_diagnostic(
        plan,
        candidate,
        "spec",
        fact_type="identity_mismatch",
        reason_key="revision_bundle_binding_invalid",
        expected="two internally bound Bundle products with one declared revision boundary",
        observed=problems,
        json_pointer="/subject/package",
    )]


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
) -> str:
    del plan
    path = capsule.source_refs[artifact]
    assert isinstance(path, str)
    return path


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
    path = artifact_source(plan, capsule, artifact)
    return make_diagnostic(
        severity="high",
        fact_type=fact_type,
        reason_key=reason_key,
        roles=roles or [capsule.role],
        expected=expected,
        observed=observed,
        locator_artifact=path,
        json_pointer=json_pointer,
        source_ref=path,
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
        source_ref=plan_path.name,
    )


def identity_diagnostics(
    plan_path: Path,
    plan: dict[str, Any],
    prior: CycleCapsule,
    candidate: CycleCapsule,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    bundle_mode = plan["decision_policy"]["mode"] == "bundle_noninferiority"
    prior_identity = prior.execution_plan["execution_profile"]
    candidate_identity = candidate.execution_plan["execution_profile"]
    identity_mismatches = [
        field
        for field in _FIXED_EXECUTION_PROFILE
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
            json_pointer="/execution_profile",
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
        bundle_mode=bundle_mode,
    )
    candidate_plan_projection = cycle_plan_projection(
        candidate.execution_plan,
        subject_id,
        bundle_mode=bundle_mode,
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
        _project_host(prior.host_manifest, subject_id, bundle_mode=bundle_mode),
        _project_host(candidate.host_manifest, subject_id, bundle_mode=bundle_mode),
    ):
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "host_manifest",
            fact_type="identity_mismatch",
            reason_key="revision_host_contract_drift",
            expected=(
                "host behavior is unchanged outside Bundle product identity"
                if bundle_mode
                else "host behavior is unchanged outside the subject Skill binding"
            ),
            observed="the stable host projection or subject Skill ID differs",
            json_pointer="",
        ))

    if bundle_mode:
        diagnostics.extend(
            _bundle_identity_diagnostics(plan_path, plan, prior, candidate)
        )
        return diagnostics

    change_set = plan["decision_policy"]["change_set"]
    candidate_revision = change_set["candidate_revision"]
    package_root = PurePosixPath(candidate.spec["subject"]["package"]["path"])
    invalid_paths = [
        path
        for path in change_set["paths"]
        if not PurePosixPath(path).is_relative_to(package_root)
    ]
    prior_digest = prior.spec["subject"]["package"]["package_digest"]
    candidate_digest = candidate.spec["subject"]["package"]["package_digest"]
    inconsistent_bindings: dict[str, list[str]] = {}
    for capsule in (prior, candidate):
        bindings = _subject_package_bindings(capsule, subject_id)
        expected_digest = bindings["spec.package_digest"]
        expected_revision = bindings["spec.source_revision"]
        inconsistent_bindings[capsule.role] = [
            label
            for label, value in bindings.items()
            if (
                label.endswith("digest") and value != expected_digest
            ) or (
                label.endswith("revision") and value != expected_revision
            )
        ]
    prior_other_packages = {
        key: value
        for key, value in prior.execution_plan["package_digests"].items()
        if key != subject_id
    }
    candidate_other_packages = {
        key: value
        for key, value in candidate.execution_plan["package_digests"].items()
        if key != subject_id
    }
    if (
        invalid_paths
        or any(inconsistent_bindings.values())
        or candidate.spec["subject"]["package"]["source_revision"]
        != candidate_revision
        or prior_other_packages != candidate_other_packages
        or prior.spec["subject"]["package"]["source_revision"]
        == candidate_revision
        or prior_digest == candidate_digest
    ):
        diagnostics.append(capsule_diagnostic(
            plan,
            candidate,
            "spec",
            fact_type="identity_mismatch",
            reason_key="revision_change_set_binding_invalid",
            expected="one changed package binds the declared paths, revision, and digest",
            observed={
                "invalid_paths": invalid_paths,
                "inconsistent_cycle_bindings": inconsistent_bindings,
                "candidate_revision_matches": (
                    candidate.spec["subject"]["package"]["source_revision"]
                    == candidate_revision
                ),
                "other_packages_match": (
                    prior_other_packages == candidate_other_packages
                ),
                "candidate_differs_from_prior": (
                    prior_digest != candidate_digest
                ),
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
