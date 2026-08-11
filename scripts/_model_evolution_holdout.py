#!/usr/bin/env python3
"""Materialize one exposed, two-scenario holdout-stage plan without provider calls."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from _model_evolution_contract import (
    ContractError,
    SKILL_IDS,
    canonical_bytes,
    content_hash,
    load_json,
    load_jsonl,
    resolve_binding,
    validate_formal_plan_timeouts,
    validate_formal_timeout_inputs,
)
from _model_evolution_materialization import (
    MaterializationError,
    _assert_tree_equal,
    _bind_scenarios,
    _compile_and_validate,
    _copy_calibration,
    _copy_file,
    _copy_host_artifacts,
    _copy_sentinel_support,
    _copy_tree,
    _file_hash,
    _materialized_spec,
    _plugin_argument,
    _run,
    _selected_product,
    _tree_hash,
    _validate_selected_plugin,
    _write_exact,
    promoted_model_grading_host,
)


_BUNDLE_FILES = {
    "holdout-manifest.json",
    "scenarios.heldout.jsonl",
    "suite-quality-proof.json",
}


def _load_holdout_bundle(
    root: Path,
    *,
    skill_id: str,
    contract_id: str,
    case_ceiling: int,
    public_rows: list[dict[str, Any]],
    exact_members: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    if root.is_symlink():
        raise MaterializationError("holdout bundle root must not be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise MaterializationError("holdout bundle root is invalid")
    members = {path.name for path in root.iterdir()}
    if (
        (exact_members and members != _BUNDLE_FILES)
        or not _BUNDLE_FILES <= members
        or any(path.is_symlink() for path in root.iterdir())
    ):
        raise MaterializationError("holdout bundle must contain exactly three files")
    payload_path = root / "scenarios.heldout.jsonl"
    proof_path = root / "suite-quality-proof.json"
    manifest = load_json(root / "holdout-manifest.json", label="holdout manifest")
    rows = load_jsonl(payload_path, label="heldout scenarios")
    if len(rows) != case_ceiling:
        raise MaterializationError("holdout bundle scenario count differs from ceiling")
    required_manifest = {
        "schema_version",
        "external_holdout_contract_id",
        "skill_id",
        "payload_file",
        "payload_digest",
        "scenario_count",
        "scenario_ids",
        "scenarios",
        "custodian",
        "exposure_status",
        "refresh_state",
    }
    if not isinstance(manifest, dict) or set(manifest) != required_manifest:
        raise MaterializationError("holdout manifest fields differ from the contract")
    custodian = manifest.get("custodian")
    if (
        manifest.get("schema_version") != 2
        or manifest.get("external_holdout_contract_id") != contract_id
        or manifest.get("skill_id") != skill_id
        or manifest.get("payload_file") != payload_path.name
        or manifest.get("payload_digest") != _file_hash(payload_path)
        or manifest.get("scenario_count") != case_ceiling
        or manifest.get("scenario_ids") != [row.get("case_id") for row in rows]
        or not isinstance(custodian, str)
        or not custodian.strip()
        or custodian == "evaluation-owner"
        or manifest.get("exposure_status") != "exposed"
        or manifest.get("refresh_state") != "fresh"
    ):
        raise MaterializationError("holdout manifest identity or custody differs")
    scenario_projection = [
        {
            "case_id": row.get("case_id"),
            "risk": row.get("risk"),
            "tags": row.get("tags"),
        }
        for row in rows
    ]
    if manifest.get("scenarios") != scenario_projection:
        raise MaterializationError("holdout manifest scenario projection differs")
    public_ids = {item.get("case_id") for item in public_rows}
    public_tasks = {item.get("execution_context", {}).get("task") for item in public_rows}
    fixtures = {canonical_bytes(item.get("fixture")) for item in public_rows}
    observed_ids: set[str] = set()
    observed_tasks: set[str] = set()
    for row in rows:
        requirements = [
            item
            for item in row.get("requirements", [])
            if isinstance(item, dict) and item.get("required") is True
        ]
        independent = {
            (item.get("requirement_id"), item.get("check_id"), item.get("dimension"))
            for item in requirements
        }
        case_id = row.get("case_id")
        task = row.get("execution_context", {}).get("task")
        if (
            case_id in public_ids | observed_ids
            or task in public_tasks | observed_tasks
            or row.get("split") != "heldout"
            or row.get("attribution_evaluable") is not True
            or "heldout" not in row.get("tags", [])
            or set(row.get("applicable_treatment_profiles", []))
            != {"baseline/skill_disabled", "candidate/force_loaded"}
            or canonical_bytes(row.get("fixture")) not in fixtures
            or len(requirements) < 2
            or len(independent) != len(requirements)
            or len({item[1] for item in independent}) < 2
            or not {"outcome", "safety"} <= {item[2] for item in independent}
        ):
            raise MaterializationError(
                "heldout scenario violates the bounded holdout contract"
            )
        observed_ids.add(case_id)
        observed_tasks.add(task)
    proof = load_json(proof_path, label="holdout suite-quality proof")
    if not isinstance(proof, dict):
        raise MaterializationError("holdout suite-quality proof is invalid")
    classes = {
        item.get("case_id"): item.get("class")
        for item in proof.get("case_classes", [])
        if isinstance(item, dict)
    }
    protected = {
        row["case_id"] for row in rows if "protected" in row.get("tags", [])
    }
    if (
        set(classes) != observed_ids
        or set(classes.values()) != {"positive", "boundary_or_failure"}
        or not protected
        or any(classes[case_id] != "boundary_or_failure" for case_id in protected)
    ):
        raise MaterializationError("holdout proof lacks positive/protected coverage")
    return manifest, rows, proof_path


def _manual_authority(spec: dict[str, Any], root: Path) -> None:
    projection = {
        "schema_version": "manual-review-contract/1",
        "reviewer_role": "qualification-owner",
        "required_evidence": ["frozen-study-input-binding"],
    }
    contract = root / "manual-review-contract.json"
    _write_exact(contract, canonical_bytes(projection))
    spec["authority"]["manual_review"] = {
        "required": True,
        "role": projection["reviewer_role"],
        "decision_contract": {
            "path": contract.name,
            "digest": _file_hash(contract),
            "schema_version": projection["schema_version"],
        },
    }
    required_kinds = {
        gate["kind"] for gate in spec["hard_gates"] if gate.get("required") is True
    }
    additions = {
        "host": ("holdout-host", "host-feasibility", "feasible"),
        "manual": ("holdout-manual", "manual-approval", "approve"),
    }
    for kind, (gate_id, metric, threshold) in additions.items():
        if kind not in required_kinds:
            spec["hard_gates"].append(
                {
                    "gate_id": gate_id,
                    "kind": kind,
                    "metric": metric,
                    "direction": "equal",
                    "threshold": threshold,
                    "authority": "qualification-owner",
                    "required": True,
                }
            )


def _build_holdout_plan(
    root: Path,
    *,
    final_root: Path,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plugin_root: Path,
    plugin_evidence: Path,
    holdout_root: Path,
) -> dict[str, Any]:
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    record = sentinel["skills"][skill_id]
    template_path = resolve_binding(
        record["spec_template"], repository_root, campaign_root
    )
    template = load_json(template_path, label=f"{skill_id} spec template")
    public_rows = load_jsonl(
        resolve_binding(record["public_scenarios"], repository_root, campaign_root),
        label=f"{skill_id} public scenarios",
    )
    manifest, scenarios, external_proof = _load_holdout_bundle(
        holdout_root,
        skill_id=skill_id,
        contract_id=record["external_holdout_contract_id"],
        case_ceiling=record["holdout_case_ceiling"],
        public_rows=public_rows,
    )
    proof = load_json(external_proof, label="holdout suite-quality proof")
    if proof.get("evaluation_id") != template.get("evaluation_id"):
        raise MaterializationError("holdout proof differs from the selected Skill")
    tracked_proof = _copy_sentinel_support(
        record,
        template_path=template_path,
        template=template,
        repository_root=repository_root,
        campaign_root=campaign_root,
        target_root=root,
    )
    tracked_proof.unlink()
    proof_path = root / "suite-quality-proof.json"
    _copy_file(external_proof, proof_path)
    public_path = root / "scenarios.public.jsonl"
    _write_exact(public_path, b"")
    payload_path = root / "scenarios.heldout.jsonl"
    _copy_file(holdout_root / payload_path.name, payload_path)
    execution_path = root / "scenarios.execution.jsonl"
    _copy_file(payload_path, execution_path)
    manifest_path = root / "holdout-manifest.json"
    _copy_file(holdout_root / manifest_path.name, manifest_path)

    calibration_source = resolve_binding(
        campaign["skill_evidence"][skill_id]["grader_calibration"],
        repository_root,
        campaign_root,
    )
    calibration, calibration_path = _copy_calibration(
        calibration_source, target_root=root
    )
    if calibration.get("evaluation_id") != template.get("evaluation_id"):
        raise MaterializationError("calibration differs from the selected Skill")
    _, selected_skills = _validate_selected_plugin(
        campaign=campaign,
        campaign_root=campaign_root,
        role="target_holdout",
        plugin_root=plugin_root,
        evidence_path=plugin_evidence,
    )
    _copy_file(plugin_evidence, root / "selected-plugin-build.json")
    _, source_commit, source_tree = _selected_product(campaign, "target_holdout")

    base_host = load_json(
        resolve_binding(
            campaign["profiles"]["target_observed"], repository_root, campaign_root
        ),
        label="target observed Host",
    )
    _copy_host_artifacts(
        base_host,
        repository_root=repository_root,
        campaign_root=campaign_root,
        target_root=root,
    )
    host_path = root / "host.json"
    retarget = campaign.get("candidate") is not None
    if not retarget and _plugin_argument(base_host) != plugin_root.resolve(strict=True):
        raise MaterializationError("observed Host plugin differs from final staging")
    host = promoted_model_grading_host(
        base_host,
        host_path=final_root / "host.json",
        calibration_file_hash=_file_hash(calibration_path),
        plugin_root=plugin_root if retarget else None,
        selected_skills=selected_skills if retarget else None,
        repository_root=repository_root if retarget else None,
        source_commit=source_commit if retarget else None,
        source_tree=source_tree if retarget else None,
    )
    _write_exact(host_path, canonical_bytes(host))
    _copy_tree(
        plugin_root / "skills" / skill_id,
        root / "package",
        expected_hash=selected_skills[skill_id]["root_hash"],
    )
    spec = _materialized_spec(
        template,
        skill_id=skill_id,
        selected_skill=selected_skills[skill_id],
        source_commit=source_commit,
        host=host,
        calibration=calibration,
        calibration_file_hash=_file_hash(calibration_path),
        scenarios=scenarios,
    )
    spec["level"] = "L3"
    spec["suite"]["public_scenarios"] = {"path": public_path.name}
    spec["suite"]["scenarios"] = {"path": execution_path.name}
    spec["suite"]["holdout"] = {
        "manifest": {
            "path": manifest_path.name,
            "digest": _file_hash(manifest_path),
            "schema_version": "holdout-manifest/2",
        },
        "payload": {
            "path": payload_path.name,
            "digest": _file_hash(payload_path),
            "schema_version": "jsonl/scenario/1",
        },
        "custodian": manifest["custodian"],
        "exposure_status": "exposed",
    }
    _manual_authority(spec, root)
    _bind_scenarios(spec, scenarios)
    try:
        validate_formal_timeout_inputs(host, spec, scenarios)
    except ContractError as exc:
        raise MaterializationError(str(exc)) from exc
    spec_path = root / "eval-spec.json"
    _write_exact(spec_path, canonical_bytes(spec))
    quality_path = root / "suite-quality.json"
    _run(
        [
            sys.executable,
            str(repository_root / "skill-evaluator/scripts/validate_eval_suite.py"),
            "suite-quality",
            "--spec",
            str(spec_path),
            "--proof",
            str(proof_path),
            "--output",
            str(quality_path),
        ],
        repository_root=repository_root,
        label="holdout suite-quality normalization",
    )
    spec["suite"]["quality"] = {
        "path": quality_path.name,
        "digest": _file_hash(quality_path),
        "schema_version": "suite-quality/2",
    }
    spec["execution"]["ready"] = True
    spec_path.write_bytes(canonical_bytes(spec))
    plan_path = root / "plan.json"
    _compile_and_validate(
        root,
        repository_root=repository_root,
        plan_path=plan_path,
        scenarios_name=execution_path.name,
    )
    plan = load_json(plan_path, label="compiled holdout plan")
    try:
        validate_formal_plan_timeouts(host, plan)
    except ContractError as exc:
        raise MaterializationError(str(exc)) from exc
    execute = sum(item.get("disposition") == "execute" for item in plan["entries"])
    expected_execute = record["holdout_case_ceiling"] * 2
    if execute != expected_execute:
        raise MaterializationError("holdout plan execution count differs from ceiling")
    return {
        "root": root,
        "spec": spec_path,
        "host": host_path,
        "plan": plan_path,
        "plan_id": plan["plan_id"],
        "plan_digest": _file_hash(plan_path),
        "execute_ceiling": execute,
    }


def prepare_holdout_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plugin_root: Path,
    holdout_root: Path,
) -> dict[str, Any]:
    if skill_id not in SKILL_IDS or campaign["phase"] != "final_plugin_ready":
        raise MaterializationError("holdout plans require final_plugin_ready")
    binding = campaign["skill_evidence"]["plugin_build"]
    if binding is None:
        raise MaterializationError("holdout plan has no selected plugin build")
    plugin_evidence = resolve_binding(binding, repository_root, campaign_root)
    final_root = campaign_root / "holdout-plans" / skill_id
    if final_root.exists():
        raise MaterializationError(f"holdout plan already exists: {skill_id}")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{skill_id}-", dir=final_root.parent)
    )
    try:
        result = _build_holdout_plan(
            temporary,
            final_root=final_root,
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            skill_id=skill_id,
            plugin_root=plugin_root,
            plugin_evidence=plugin_evidence,
            holdout_root=holdout_root,
        )
        temporary.rename(final_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        **result,
        "root": final_root,
        "spec": final_root / "eval-spec.json",
        "host": final_root / "host.json",
        "plan": final_root / "plan.json",
    }


def validate_holdout_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plan_path: Path,
) -> dict[str, Any]:
    root = campaign_root / "holdout-plans" / skill_id
    if plan_path != (root / "plan.json").resolve(strict=True):
        raise MaterializationError("holdout plan is outside its canonical directory")
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    record = sentinel["skills"][skill_id]
    public_rows = load_jsonl(
        resolve_binding(record["public_scenarios"], repository_root, campaign_root),
        label=f"{skill_id} public scenarios",
    )
    _load_holdout_bundle(
        root,
        skill_id=skill_id,
        contract_id=record["external_holdout_contract_id"],
        case_ceiling=record["holdout_case_ceiling"],
        public_rows=public_rows,
        exact_members=False,
    )
    calibration_source = resolve_binding(
        campaign["skill_evidence"][skill_id]["grader_calibration"],
        repository_root,
        campaign_root,
    )
    calibration_path = root / "grader-calibration.json"
    if _file_hash(calibration_path) != _file_hash(calibration_source):
        raise MaterializationError("materialized holdout calibration differs")
    selected_evidence = root / "selected-plugin-build.json"
    campaign_evidence = resolve_binding(
        campaign["skill_evidence"]["plugin_build"], repository_root, campaign_root
    )
    if selected_evidence.read_bytes() != campaign_evidence.read_bytes():
        raise MaterializationError("holdout plugin evidence differs from campaign")
    host = load_json(root / "host.json", label="materialized holdout Host")
    plugin_root = _plugin_argument(host)
    _, selected_skills = _validate_selected_plugin(
        campaign=campaign,
        campaign_root=campaign_root,
        role="target_holdout",
        plugin_root=plugin_root,
        evidence_path=selected_evidence,
    )
    base_host = load_json(
        resolve_binding(
            campaign["profiles"]["target_observed"], repository_root, campaign_root
        ),
        label="target observed Host",
    )
    _, source_commit, source_tree = _selected_product(campaign, "target_holdout")
    retarget = campaign.get("candidate") is not None
    expected_host = promoted_model_grading_host(
        base_host,
        host_path=root / "host.json",
        calibration_file_hash=_file_hash(calibration_path),
        plugin_root=plugin_root if retarget else None,
        selected_skills=selected_skills if retarget else None,
        repository_root=repository_root if retarget else None,
        source_commit=source_commit if retarget else None,
        source_tree=source_tree if retarget else None,
    )
    if canonical_bytes(host) != canonical_bytes(expected_host):
        raise MaterializationError("materialized holdout Host differs from derivation")
    if _tree_hash(root / "package") != selected_skills[skill_id]["root_hash"]:
        raise MaterializationError("materialized holdout package differs")
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=".register-check-") as raw:
        temporary = Path(raw)
        bundle = temporary / "bundle"
        bundle.mkdir()
        for name in _BUNDLE_FILES:
            _copy_file(root / name, bundle / name)
        expected_root = temporary / "expected"
        _build_holdout_plan(
            expected_root,
            final_root=root,
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            skill_id=skill_id,
            plugin_root=plugin_root,
            plugin_evidence=campaign_evidence,
            holdout_root=bundle,
        )
        _assert_tree_equal(root, expected_root, label="target_holdout")
    plan = load_json(plan_path, label="holdout plan")
    execute = sum(item.get("disposition") == "execute" for item in plan["entries"])
    if execute != record["holdout_case_ceiling"] * 2:
        raise MaterializationError("holdout plan execution count differs from ceiling")
    return host
