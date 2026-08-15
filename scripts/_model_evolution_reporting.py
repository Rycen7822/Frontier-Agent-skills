#!/usr/bin/env python3
"""Create bounded analysis and Bundle revision evidence from registered plans."""

from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from typing import Any

from _model_evolution_contract import (
    SAFE_ID,
    SKILL_IDS,
    canonical_bytes,
    content_hash,
    load_json,
    parse_utc,
    resolve_binding,
)
from _model_evolution_materialization import (
    MaterializationError,
    _plugin_argument,
    _write_exact,
)
from _model_evolution_ops import (
    git_identity,
    run_model_free_command,
    runner_status,
    validate_plugin_staging,
)
from _model_evolution_prior import _prior_product


POLICY_PATH = Path("evaluation/model-evolution/bundle-revision-policy.json")
ANALYSIS_ROLES = {"target_current", "target_prior", "target_holdout"}
ROLE_DIRECTORIES = {
    "target_current": "current-plans",
    "target_prior": "prior-plans",
    "target_holdout": "holdout-plans",
}
EXPECTED_AXES = {
    skill_id: [
        "task_behavior",
        "protected_safety",
        "operational_cost",
        *(["loop_pathology"] if skill_id == "software-quality-workflows" else []),
        "apparatus",
    ]
    for skill_id in SKILL_IDS
}
EXPECTED_METRICS = {
    skill_id: [
        {
            "purpose": "protected_noninferiority",
            "metric_id": "task-benefit",
            "direction": "higher_is_better",
            "margin": 0.0,
        },
        *(
            [{
                "purpose": "protected_noninferiority",
                "metric_id": "tool-call-cost",
                "direction": "lower_is_better",
                "margin": 0.0,
            }]
            if skill_id == "software-quality-workflows" else []
        ),
    ]
    for skill_id in SKILL_IDS
}
EXPECTED_ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": True,
    "writing-plans": True,
}


def validate_bundle_revision_policy(
    repository_root: Path,
) -> tuple[dict[str, Any], str]:
    """Return the exact signed-source policy and its byte digest."""
    path = repository_root / POLICY_PATH
    policy = load_json(path, label="Bundle revision policy")
    required = {
        "schema_version",
        "registered_at",
        "authority_id",
        "prior_bundle_version",
        "candidate_bundle_version",
        "candidate_activation",
        "skills",
    }
    if (
        set(policy) != required
        or policy["schema_version"] != "frontier-bundle-revision-policy/1"
        or policy["prior_bundle_version"] != "7.0.0"
        or policy["candidate_bundle_version"] != "8.0.0"
        or policy["candidate_activation"] != EXPECTED_ACTIVATION
        or set(policy["skills"]) != set(SKILL_IDS)
        or not isinstance(policy["authority_id"], str)
        or SAFE_ID.fullmatch(policy["authority_id"]) is None
    ):
        raise MaterializationError("Bundle revision policy identity is invalid")
    parse_utc(policy["registered_at"])
    for skill_id, record in policy["skills"].items():
        if (
            set(record) != {
                "minimum_distinct_cases", "required_axes", "metric_rules"
            }
            or not isinstance(record["minimum_distinct_cases"], int)
            or isinstance(record["minimum_distinct_cases"], bool)
            or record["minimum_distinct_cases"] < 2
            or record["required_axes"] != EXPECTED_AXES[skill_id]
            or record["metric_rules"] != EXPECTED_METRICS[skill_id]
        ):
            raise MaterializationError(
                f"Bundle revision policy differs for {skill_id}"
            )
    return policy, content_hash(path.read_bytes())


def _registered_plan(
    campaign: dict[str, Any], role: str, skill_id: str
) -> dict[str, Any]:
    matches = [
        record for record in campaign["plans"]
        if record["role"] == role and record["skill_id"] == skill_id
    ]
    if len(matches) != 1:
        raise MaterializationError(f"missing unique {role}/{skill_id} plan")
    return matches[0]


def _plan_paths(
    campaign: dict[str, Any],
    *,
    role: str,
    skill_id: str,
    repository_root: Path,
    campaign_root: Path,
) -> tuple[Path, Path, Path, Path]:
    record = _registered_plan(campaign, role, skill_id)
    plan_path = resolve_binding(record["plan"], repository_root, campaign_root)
    if content_hash(plan_path.read_bytes()) != record["plan_digest"]:
        raise MaterializationError(f"registered {role}/{skill_id} plan changed")
    root = campaign_root / ROLE_DIRECTORIES[role] / skill_id
    if plan_path != (root / "plan.json").resolve(strict=True):
        raise MaterializationError(f"registered {role}/{skill_id} path is noncanonical")
    return root, root / "eval-spec.json", root / "host.json", plan_path


def _index_path(plan_path: Path, plan: dict[str, Any]) -> Path:
    artifacts = plan_path.parent / plan["artifacts"]["root"]
    return artifacts / plan["artifacts"]["index_relpath"]


def _relative(path: Path, root: Path) -> str:
    try:
        value = path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise MaterializationError("report artifact escapes campaign root") from exc
    relative = value.as_posix()
    if relative.startswith("../") or PurePosixPath(relative).is_absolute():
        raise MaterializationError("report artifact path is unsafe")
    return relative


def _artifact(path: Path, root: Path, schema: str) -> dict[str, str]:
    return {
        "path": _relative(path, root),
        "schema": schema,
        "digest": content_hash(path.read_bytes()),
    }


def prepare_analysis(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    role: str,
    skill_id: str,
) -> dict[str, Path]:
    """Analyze one completed registered cycle into two canonical views."""
    if role not in ANALYSIS_ROLES or skill_id not in SKILL_IDS:
        raise MaterializationError("analysis role or Skill is invalid")
    root, spec_path, _, plan_path = _plan_paths(
        campaign,
        role=role,
        skill_id=skill_id,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    plan = load_json(plan_path, label=f"{role} plan")
    index = _index_path(plan_path, plan)
    status = runner_status(plan_path, index, repository_root=repository_root)
    if (
        status.get("completed_entries") != status.get("execute_entries")
        or status.get("remaining_entries") != 0
        or status.get("active_attempts")
        or status.get("recoverable_attempts")
    ):
        raise MaterializationError(f"{role}/{skill_id} execution is incomplete")

    final_root = campaign_root / "analysis" / role / skill_id
    if final_root.exists():
        raise MaterializationError(f"analysis already exists: {role}/{skill_id}")
    final_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{skill_id}-", dir=final_root.parent))
    try:
        summary = temporary / "summary.json"
        failures = temporary / "failure-index.json"
        argv = [
            sys.executable,
            "skill-evaluator/scripts/analyze_runs.py",
            str(index),
            "--spec",
            str(spec_path),
            "--json",
            str(summary),
            "--failure-index",
            str(failures),
        ]
        if role == "target_holdout":
            receipt = root / plan["artifacts"]["root"] / "manual-review-receipt.json"
            if not receipt.is_file() or receipt.is_symlink():
                raise MaterializationError(
                    f"holdout manual receipt is missing: {skill_id}"
                )
            argv.extend(("--manual-review-receipt", str(receipt)))
        run_model_free_command(
            f"analyze-{role}-{skill_id}",
            argv,
            repository_root=repository_root,
            acceptable={0, 1, 3},
        )
        for path in (summary, failures):
            if not path.is_file() or path.is_symlink():
                raise MaterializationError("analyzer omitted a required output")
        analyzed = load_json(summary, label=f"{role} summary")
        failure_index = load_json(failures, label=f"{role} failure index")
        if (
            analyzed.get("plan_id") != plan["plan_id"]
            or failure_index.get("plan_id") != plan["plan_id"]
            or failure_index.get("truncated") is not False
            or failure_index.get("omitted_count") != 0
        ):
            raise MaterializationError("analysis identity or completeness is invalid")
        temporary.rename(final_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        "summary": final_root / "summary.json",
        "failure_index": final_root / "failure-index.json",
    }


def _product_identity(
    source_root: Path,
    evidence_path: Path,
) -> dict[str, Any]:
    bundle = load_json(
        source_root / "frontier-engineering.bundle.json",
        label="selected Bundle manifest",
    )
    evidence = load_json(evidence_path, label="selected plugin build")
    skills = bundle.get("skills")
    if not isinstance(skills, dict) or set(skills) != set(SKILL_IDS):
        raise MaterializationError("selected Bundle Skill set is invalid")
    identity = {
        "bundle_id": bundle.get("bundle_id"),
        "bundle_version": evidence.get("bundle_version"),
        "source_revision": evidence.get("source_revision"),
        "source_tree_hash": evidence.get("source_tree_hash"),
        "plugin_tree_hash": evidence.get("plugin_tree_hash"),
        "skills": copy.deepcopy(skills),
    }
    expected_versions = {
        skill_id: row["version"] for skill_id, row in skills.items()
    }
    expected_activation = {
        skill_id: row["allow_implicit_invocation"]
        for skill_id, row in skills.items()
    }
    if (
        identity["bundle_id"]
        != f"frontier-engineering/{identity['bundle_version']}"
        or evidence.get("skill_versions") != expected_versions
        or evidence.get("skill_activation") != expected_activation
        or any(
            set(row) != {"version", "root_hash", "allow_implicit_invocation"}
            for row in skills.values()
        )
    ):
        raise MaterializationError("plugin evidence differs from its Bundle manifest")
    return identity


def _cycle_capsule(
    *,
    campaign_root: Path,
    role: str,
    cycle_id: str,
    spec_path: Path,
    host_path: Path,
    plan_path: Path,
    summary_path: Path,
    failure_path: Path,
) -> dict[str, Any]:
    spec = load_json(spec_path, label=f"{role} spec")
    plan = load_json(plan_path, label=f"{role} plan")
    summary = load_json(summary_path, label=f"{role} summary")
    if (
        summary.get("evaluation_id") != spec.get("evaluation_id")
        or summary.get("plan_id") != plan.get("plan_id")
    ):
        raise MaterializationError(f"{role} capsule identity differs")
    return {
        "schema_version": "comparison-cycle-capsule/3",
        "cycle_id": cycle_id,
        "evaluation_id": spec["evaluation_id"],
        "plan_id": plan["plan_id"],
        "execution_profile": plan["execution_profile"],
        "artifacts": {
            "spec": _artifact(spec_path, campaign_root, "eval-spec-v7"),
            "execution_plan": _artifact(
                plan_path, campaign_root, "execution-plan-v3"
            ),
            "host_manifest": _artifact(
                host_path, campaign_root, "host-manifest-v2"
            ),
            "summary": _artifact(
                summary_path, campaign_root, "analysis-summary-v6"
            ),
            "failure_index": _artifact(
                failure_path, campaign_root, "failure-index-v2"
            ),
            "observations": None,
        },
    }


def _current_product(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    plan_root: Path,
) -> dict[str, Any]:
    identity = git_identity(repository_root, campaign["product"]["source_commit"])
    if (
        identity["commit"] != campaign["product"]["source_commit"]
        or identity["tree"] != campaign["product"]["source_tree"]
    ):
        raise MaterializationError("current signed source identity changed")
    evidence = plan_root / "selected-plugin-build.json"
    campaign_evidence = resolve_binding(
        campaign["product"]["plugin_build"], repository_root, campaign_root
    )
    if evidence.read_bytes() != campaign_evidence.read_bytes():
        raise MaterializationError("current plan plugin evidence changed")
    plugin_root = campaign_root / campaign["product"]["plugin_root"]
    validate_plugin_staging(
        repository_root=repository_root,
        plugin_root=plugin_root,
        evidence_path=evidence,
        expected_commit=campaign["product"]["source_commit"],
        expected_bundle_id=campaign["product"]["bundle_id"],
        expected_bundle_version=campaign["product"]["bundle_version"],
        expected_skill_versions={
            skill_id: row["version"]
            for skill_id, row in campaign["product"]["skills"].items()
        },
    )
    product = _product_identity(repository_root, evidence)
    product["build_evidence"] = _artifact(
        evidence, campaign_root, "plugin-build-evidence/4.0"
    )
    return product


def _prior_product_identity(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    plan_root: Path,
) -> dict[str, Any]:
    record = load_json(
        plan_root / "selected-prior-product.json",
        label="selected prior product",
    )
    source_root = Path(record["source_root"])
    host = load_json(plan_root / "host.json", label="prior Host")
    evidence = plan_root / "selected-plugin-build.json"
    _prior_product(
        campaign=campaign,
        prior_source_root=source_root,
        plugin_root=_plugin_argument(host),
        plugin_evidence=evidence,
    )
    product = _product_identity(source_root, evidence)
    product["build_evidence"] = _artifact(
        evidence, campaign_root, "plugin-build-evidence/4.0"
    )
    return product


def _capsule_binding(
    path: Path,
    capsule: dict[str, Any],
    campaign_root: Path,
) -> dict[str, Any]:
    return {
        "cycle_id": capsule["cycle_id"],
        "expected_identity": {
            "evaluation_id": capsule["evaluation_id"],
            "plan_id": capsule["plan_id"],
            "execution_profile": capsule["execution_profile"],
        },
        "capsule": _artifact(
            path, campaign_root, "comparison-cycle-capsule/3"
        ),
    }


def _bundle_revision_plan(
    *,
    campaign_root: Path,
    comparison_id: str,
    registered_at: str,
    authority_id: str,
    capsules: dict[str, tuple[Path, dict[str, Any]]],
    products: dict[str, dict[str, Any]],
    policy_digest: str,
    change_paths: list[str],
    metric_rules: list[dict[str, Any]],
    minimum_distinct_cases: int,
    required_axes: list[str],
    output_root: str,
) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "comparison_id": comparison_id,
        "kind": "revision",
        "claim_scope": "revision_noninferiority",
        "registration": {
            "mode": "pre_registered",
            "registered_at": registered_at,
            "authority_id": authority_id,
        },
        "owner_attestation": {
            "owner_id": authority_id,
            "scope": "bundle_revision_noninferiority",
            "attested_at": registered_at,
        },
        "input_bindings": {
            role: _capsule_binding(path, capsule, campaign_root)
            for role, (path, capsule) in capsules.items()
        },
        "decision_policy": {
            "kind": "revision",
            "mode": "bundle_noninferiority",
            "policy_digest": policy_digest,
            "target": None,
            "bundle_products": products,
            "change_set": {
                "category": "bundle",
                "paths": change_paths,
                "candidate_revision": products["candidate"]["source_revision"],
            },
            "metric_rules": metric_rules,
            "minimum_distinct_cases": minimum_distinct_cases,
            "required_axes": required_axes,
            "require_candidate_failure_index": True,
        },
        "output": {
            "root": output_root,
            "report": "comparison-report.json",
            "diagnostic_index": "comparison-diagnostic-index.json",
        },
    }


def prepare_revision_report(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
) -> dict[str, Any]:
    """Bind current/prior cycles and produce one Bundle noninferiority report."""
    if skill_id not in SKILL_IDS or campaign.get("candidate") is not None:
        raise MaterializationError("Bundle revision requires candidate-null bootstrap")
    policy, policy_digest = validate_bundle_revision_policy(repository_root)
    roots: dict[str, Path] = {}
    paths: dict[str, tuple[Path, Path, Path]] = {}
    analyses: dict[str, tuple[Path, Path]] = {}
    for role in ("target_prior", "target_current"):
        root, spec, host, plan = _plan_paths(
            campaign,
            role=role,
            skill_id=skill_id,
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        summary_root = campaign_root / "analysis" / role / skill_id
        summary = summary_root / "summary.json"
        failures = summary_root / "failure-index.json"
        if any(not path.is_file() or path.is_symlink() for path in (summary, failures)):
            raise MaterializationError(f"{role}/{skill_id} analysis is missing")
        roots[role] = root
        paths[role] = (spec, host, plan)
        analyses[role] = (summary, failures)

    current_summary = resolve_binding(
        campaign["skill_evidence"][skill_id]["current_summary"],
        repository_root,
        campaign_root,
    )
    if current_summary != analyses["target_current"][0].resolve(strict=True):
        raise MaterializationError("recorded current summary is noncanonical")
    products = {
        "prior": _prior_product_identity(
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            plan_root=roots["target_prior"],
        ),
        "candidate": _current_product(
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            plan_root=roots["target_current"],
        ),
    }
    if (
        products["prior"]["bundle_version"] != policy["prior_bundle_version"]
        or products["candidate"]["bundle_version"]
        != policy["candidate_bundle_version"]
        or {
            skill: row["allow_implicit_invocation"]
            for skill, row in products["candidate"]["skills"].items()
        }
        != policy["candidate_activation"]
    ):
        raise MaterializationError("Bundle products differ from registered policy")

    output_root = campaign_root / "revision-reports" / skill_id
    report_path = output_root / "comparison-report.json"
    index_path = output_root / "comparison-diagnostic-index.json"
    if output_root.exists():
        if not report_path.is_file() or not index_path.is_file():
            raise MaterializationError("existing revision report is incomplete")
        report = load_json(report_path, label="existing revision report")
        by_role = {row["role"]: row for row in report.get("inputs", [])}
        if (
            report.get("claim_scope") != "revision_noninferiority"
            or report.get("registration_policy_digest") != policy_digest
            or set(by_role) != {"prior", "candidate"}
            or any(
                by_role[role].get("product_identity") != products[role]
                for role in products
            )
        ):
            raise MaterializationError("existing revision report identity changed")
        return {"report": report_path, "diagnostic_index": index_path, "status": report["result"]["status"]}

    capsules: dict[str, tuple[Path, dict[str, Any]]] = {}
    created: list[Path] = []
    try:
        for capsule_role, plan_role in (
            ("prior", "target_prior"),
            ("candidate", "target_current"),
        ):
            spec, host, plan = paths[plan_role]
            summary, failures = analyses[plan_role]
            cycle_id = f"{campaign['campaign_id']}.{capsule_role}.{skill_id}"
            if SAFE_ID.fullmatch(cycle_id) is None:
                raise MaterializationError("revision cycle ID is invalid")
            capsule = _cycle_capsule(
                campaign_root=campaign_root,
                role=capsule_role,
                cycle_id=cycle_id,
                spec_path=spec,
                host_path=host,
                plan_path=plan,
                summary_path=summary,
                failure_path=failures,
            )
            capsule_path = campaign_root / f"cycle-{capsule_role}-{skill_id}.json"
            _write_exact(capsule_path, canonical_bytes(capsule))
            created.append(capsule_path)
            capsules[capsule_role] = (capsule_path, capsule)

        skill_policy = policy["skills"][skill_id]
        comparison = _bundle_revision_plan(
            campaign_root=campaign_root,
            comparison_id=f"bundle-8-vs-7-{skill_id}",
            registered_at=policy["registered_at"],
            authority_id=policy["authority_id"],
            capsules=capsules,
            products=products,
            policy_digest=policy_digest,
            change_paths=sorted(SKILL_IDS),
            metric_rules=skill_policy["metric_rules"],
            minimum_distinct_cases=skill_policy["minimum_distinct_cases"],
            required_axes=skill_policy["required_axes"],
            output_root=f"revision-reports/{skill_id}",
        )
        plan_path = campaign_root / f"revision-{skill_id}.json"
        _write_exact(plan_path, canonical_bytes(comparison))
        created.append(plan_path)
        run_model_free_command(
            f"compare-bundle-{skill_id}",
            [
                sys.executable,
                "skill-evaluator/scripts/compare_cycles.py",
                str(plan_path),
            ],
            repository_root=repository_root,
        )
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        if output_root.exists():
            shutil.rmtree(output_root, ignore_errors=True)
        raise
    report = load_json(report_path, label="Bundle revision report")
    return {
        "report": report_path,
        "diagnostic_index": index_path,
        "status": report["result"]["status"],
    }
