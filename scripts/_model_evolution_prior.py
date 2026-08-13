#!/usr/bin/env python3
"""Materialize the signed Bundle 7 public cycle used as revision prior."""

from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from _model_evolution_contract import (
    SKILL_IDS,
    canonical_bytes,
    load_json,
    resolve_binding,
)
from _model_evolution_materialization import (
    MaterializationError,
    _assert_tree_equal,
    _build_public_plan,
    _file_hash,
    _plugin_argument,
    _tree_hash,
    _validate_selected_plugin,
    _write_exact,
    promoted_model_grading_host,
)
from _model_evolution_ops import (
    OperationError,
    bundle_version_at_revision,
    git_identity,
    run_model_free_command,
)


def _prior_product(
    *,
    campaign: dict[str, Any],
    prior_source_root: Path,
    plugin_root: Path,
    plugin_evidence: Path,
) -> tuple[tuple[dict[str, Any], str, str], dict[str, str]]:
    try:
        prior_source_root = prior_source_root.resolve(strict=True)
        identity = git_identity(prior_source_root)
        version = bundle_version_at_revision(prior_source_root, identity["commit"])
        manifest = load_json(
            prior_source_root / "frontier-engineering.bundle.json",
            label="prior Bundle manifest",
        )
        skills = manifest.get("skills")
        if (
            identity["commit"] == campaign["product"]["source_commit"]
            or version != "7.0.0"
            or manifest.get("bundle_id") != "frontier-engineering/7.0.0"
            or not isinstance(skills, dict)
            or set(skills) != set(SKILL_IDS)
        ):
            raise MaterializationError("prior product is not the signed Bundle 7.0")
        run_model_free_command(
            "prior-plugin-build-check",
            [
                sys.executable,
                "scripts/build_codex_plugin.py",
                "--source-root",
                str(prior_source_root),
                "--validate-plugin-root",
                str(plugin_root),
                "--build-evidence",
                str(plugin_evidence),
            ],
            repository_root=prior_source_root,
        )
        evidence = load_json(plugin_evidence, label="prior plugin build")
        expected = {
            "source_revision": identity["commit"],
            "bundle_id": manifest["bundle_id"],
            "bundle_version": version,
            "skill_versions": {
                skill_id: skills[skill_id]["version"] for skill_id in SKILL_IDS
            },
            "output_class": "staging",
        }
        if any(evidence.get(field) != value for field, value in expected.items()):
            raise MaterializationError("prior plugin evidence differs from Bundle 7.0")
    except MaterializationError:
        raise
    except (KeyError, OSError, OperationError, ValueError) as exc:
        raise MaterializationError(f"prior product validation failed: {exc}") from exc
    product = (skills, identity["commit"], identity["tree"])
    record = {
        "schema_version": "prior-product/1",
        "source_root": str(prior_source_root),
        "source_commit": identity["commit"],
        "source_tree": identity["tree"],
        "bundle_id": "frontier-engineering/7.0.0",
    }
    return product, record


def _build_prior_plan(
    root: Path,
    *,
    final_root: Path,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    prior_source_root: Path,
    plugin_root: Path,
    plugin_evidence: Path,
    product: tuple[dict[str, Any], str, str],
    product_record: dict[str, str],
) -> dict[str, Any]:
    result = _build_public_plan(
        root,
        final_root=final_root,
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=skill_id,
        role="target_prior",
        plugin_root=plugin_root,
        plugin_evidence=plugin_evidence,
        product=product,
        source_repository_root=prior_source_root,
        verifier_source_commit=campaign["product"]["source_commit"],
        preserve_host_repository=True,
    )
    _write_exact(
        root / "selected-prior-product.json",
        canonical_bytes(product_record),
    )
    return result


def prepare_prior_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    prior_source_root: Path,
    plugin_root: Path,
    plugin_evidence: Path,
) -> dict[str, Any]:
    if (
        skill_id not in SKILL_IDS
        or campaign["phase"] != "decision_ready"
        or campaign.get("candidate") is not None
        or campaign["profiles"].get("predecessor") is not None
    ):
        raise MaterializationError(
            "prior plans require a candidate-null bootstrap at decision_ready"
        )
    product, product_record = _prior_product(
        campaign=campaign,
        prior_source_root=prior_source_root,
        plugin_root=plugin_root,
        plugin_evidence=plugin_evidence,
    )
    final_root = campaign_root / "prior-plans" / skill_id
    if final_root.exists():
        raise MaterializationError(f"prior plan already exists: {skill_id}")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{skill_id}-", dir=final_root.parent))
    try:
        result = _build_prior_plan(
            temporary,
            final_root=final_root,
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            skill_id=skill_id,
            prior_source_root=prior_source_root,
            plugin_root=plugin_root,
            plugin_evidence=plugin_evidence,
            product=product,
            product_record=product_record,
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


def validate_prior_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plan_path: Path,
) -> dict[str, Any]:
    root = campaign_root / "prior-plans" / skill_id
    if plan_path != (root / "plan.json").resolve(strict=True):
        raise MaterializationError("prior plan is outside its canonical directory")
    calibration_source = resolve_binding(
        campaign["skill_evidence"][skill_id]["grader_calibration"],
        repository_root,
        campaign_root,
    )
    calibration_path = root / "grader-calibration.json"
    if _file_hash(calibration_path) != _file_hash(calibration_source):
        raise MaterializationError("materialized prior calibration differs")
    product_record = load_json(
        root / "selected-prior-product.json", label="selected prior product"
    )
    if not isinstance(product_record.get("source_root"), str):
        raise MaterializationError("selected prior product lacks source worktree")
    prior_source_root = Path(product_record["source_root"])
    host = load_json(root / "host.json", label="materialized prior Host")
    plugin_root = _plugin_argument(host)
    selected_evidence = root / "selected-plugin-build.json"
    product, expected_product_record = _prior_product(
        campaign=campaign,
        prior_source_root=prior_source_root,
        plugin_root=plugin_root,
        plugin_evidence=selected_evidence,
    )
    if canonical_bytes(product_record) != canonical_bytes(expected_product_record):
        raise MaterializationError("selected prior product identity differs")
    _, selected_skills = _validate_selected_plugin(
        campaign=campaign,
        campaign_root=campaign_root,
        role="target_prior",
        plugin_root=plugin_root,
        evidence_path=selected_evidence,
        product=product,
    )
    base_host = load_json(
        resolve_binding(
            campaign["profiles"]["target_observed"], repository_root, campaign_root
        ),
        label="target observed Host",
    )
    _, source_commit, source_tree = product
    expected_host = promoted_model_grading_host(
        base_host,
        host_path=root / "host.json",
        calibration_file_hash=_file_hash(calibration_path),
        plugin_root=plugin_root,
        selected_skills=selected_skills,
        repository_root=prior_source_root,
        source_commit=source_commit,
        source_tree=source_tree,
        preserve_repository_identity=True,
    )
    if canonical_bytes(host) != canonical_bytes(expected_host):
        raise MaterializationError("materialized prior Host differs from derivation")
    if _tree_hash(root / "package") != selected_skills[skill_id]["root_hash"]:
        raise MaterializationError("materialized prior package differs")
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=".register-check-") as raw:
        expected_root = Path(raw) / "expected"
        _build_prior_plan(
            expected_root,
            final_root=root,
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            skill_id=skill_id,
            prior_source_root=prior_source_root,
            plugin_root=plugin_root,
            plugin_evidence=selected_evidence,
            product=product,
            product_record=expected_product_record,
        )
        _assert_tree_equal(root, expected_root, label="target_prior")
    plan = load_json(plan_path, label="prior execution plan")
    if (
        plan.get("source_revision") != source_commit
        or plan.get("compiler", {}).get("source_revision")
        != campaign["product"]["source_commit"]
        or host.get("identity", {}).get("repository", {}).get("revision")
        != campaign["product"]["source_commit"]
    ):
        raise MaterializationError("prior subject or apparatus identity differs")
    return host
