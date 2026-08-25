#!/usr/bin/env python3
"""Run one bounded Frontier model-evolution campaign."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
import subprocess
import sys
from typing import Any

if __name__ == "__main__":
    sys.dont_write_bytecode = True

import evaluate_static_contracts as static_contracts
from _model_evolution_campaign import (
    build_initial_campaign,
    prepare_predecessor,
    qualification_request_ceilings,
    require_qualification_request_ceilings,
    validate_campaign,
)
from _model_evolution_apparatus import (
    audit_plan_transport,
    campaign_reserve_projection,
    plan_registration_projection,
    validate_apparatus_retry_policy,
)
from _model_evolution_contract import (
    ContractError,
    SKILL_IDS,
    canonical_bytes,
    content_hash,
    evaluator_evidence_status,
    load_json,
    make_binding,
    resolve_binding,
    validate_document,
)
from _model_evolution_qualification import (
    CRITICAL_PROBE_CAPABILITIES,
    assess_interaction_probes,
    project_observed_host,
    project_qualification,
    render_qualification_markdown,
    validate_qualification,
)
from _model_evolution_calibration import (
    CalibrationPreparationError,
    close_calibration_failure,
    prepare_calibrations,
)
from _model_evolution_calibration_receipt import (
    calibration_attempt_count,
    close_calibration_rejection,
)
from _model_evolution_materialization import (
    MaterializationError,
    prepare_candidate_plan,
    prepare_current_plan,
    validate_candidate_plan,
    validate_current_plan,
)
from _model_evolution_prior import prepare_prior_plan, validate_prior_plan
from _model_evolution_holdout import (
    prepare_holdout_plan,
    prepare_manual_review_receipt,
    validate_holdout_plan,
)
from _model_evolution_jobs import (
    render_probe_command,
    render_runner_command,
    runner_service_stopped,
    systemd_probe_argv,
    verify_systemd_user,
)
from _model_evolution_ops import (
    OperationError,
    bundle_skill_at_revision,
    bundle_version_at_revision,
    candidate_source,
    git_identity,
    preflight_operations,
    require_tracked_binding,
    run_interaction_probes,
    runner_status,
    validate_plugin_staging,
    validate_target_host_staging,
)
from _model_evolution_reporting import (
    ANALYSIS_ROLES,
    prepare_analysis,
    prepare_revision_report,
)
from _model_evolution_state import (
    CampaignStore,
    StateError,
    accept_candidate,
    advance_preflight,
    block_probes,
    close_probes,
    create_no_overwrite,
    record_evidence,
    record_observed_budget,
    refresh_current_evidence,
    rebind_product,
    register_plan,
    reserve_probes,
    reserve_budget,
    status_projection,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RECORD_ROLES = (
    "grader_calibration",
    "current_summary",
    "transition_report",
    "candidate_source",
    "candidate_summary",
    "revision_report",
    "holdout_summary",
    "plugin_build",
)
D8_REFRESH_SKILLS = (
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
)
D8_OLD_SOURCE = "283e8838caca486f795ed5f8afc0979862e333af"
D8_NEW_SOURCE = "37ed0b7e6fdcc7ed1065ff1ad331de0c935d352a"
D8_OLD_PLUGIN_TREE = "sha256:e88f947d64a3449fb601203e968d7a105c6c2decd880430c7c5baac3b176a7ac"
D8_NEW_PLUGIN_TREE = "sha256:6dd4d2310feadc69b3279fd41622ded5560f68f576285097766df20edb053e32"
D8_OLD_BUILD_DIGEST = (
    "sha256:791050386dbaa61f7c644206b6bcb53fe777207586db3c87cc02fc752fabbc25"
)
D8_NEW_BUILD_DIGEST = (
    "sha256:d349017806843f23c8fbc966b5d7d01cf8b65a8d184b80d30c76290483a71091"
)


class CliError(ValueError):
    """A deterministic CLI usage or publication failure."""


def _emit(value: Any) -> None:
    sys.stdout.buffer.write(canonical_bytes(value) + b"\n")
    sys.stdout.buffer.flush()


def _roots(args: argparse.Namespace) -> tuple[Path, Path]:
    repository = args.repository_root.resolve(strict=True)
    campaign = args.campaign_root.resolve()
    return repository, campaign


def _campaign_store(repository_root: Path, campaign_root: Path) -> CampaignStore:
    return CampaignStore(campaign_root, repository_root)


def _binding_for_path(
    path: Path,
    *,
    repository_root: Path,
    campaign_root: Path,
    tracked_repository: bool = True,
    external: bool = False,
) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if resolved.is_relative_to(repository_root):
        if tracked_repository:
            require_tracked_binding(repository_root, resolved)
        root = "repository"
    elif resolved.is_relative_to(campaign_root):
        root = "external" if external else "campaign"
    else:
        raise CliError("artifact is outside repository and campaign roots")
    return make_binding(
        resolved,
        root=root,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )


def _load_bound_document(
    binding: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    label: str,
) -> dict[str, Any]:
    value = load_json(
        resolve_binding(binding, repository_root, campaign_root), label=label
    )
    if not isinstance(value, dict):
        raise CliError(f"{label} must be a JSON object")
    return value


def _registered_plan(
    campaign: dict[str, Any], role: str, skill_id: str
) -> dict[str, Any]:
    matches = [
        item
        for item in campaign["plans"]
        if item["role"] == role and item["skill_id"] == skill_id
    ]
    if len(matches) != 1:
        raise CliError(f"evidence lacks one registered {role} plan")
    return matches[0]


def _validate_evidence_join(
    campaign: dict[str, Any],
    *,
    role: str,
    skill_id: str,
    value: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
) -> None:
    if role == "grader_calibration":
        sentinel = _load_bound_document(
            campaign["sentinel_index"],
            repository_root=repository_root,
            campaign_root=campaign_root,
            label="sentinel index",
        )
        spec = _load_bound_document(
            sentinel["skills"][skill_id]["spec_template"],
            repository_root=repository_root,
            campaign_root=campaign_root,
            label=f"{skill_id} spec template",
        )
        selected = [item for item in spec["graders"] if item["type"] == "model"]
        host = _load_bound_document(
            campaign["profiles"]["target_observed"],
            repository_root=repository_root,
            campaign_root=campaign_root,
            label="target observed Host",
        )
        grader = value.get("grader", {})
        execution = host["identity"]["execution"]
        if (
            len(selected) != 1
            or value.get("evaluation_id") != spec.get("evaluation_id")
            or grader.get("grader_id") != selected[0].get("grader_id")
            or grader.get("prompt_id") != selected[0].get("prompt_id")
            or grader.get("schema_id") != selected[0].get("schema_id")
            or grader.get("model") != execution.get("model")
            or grader.get("model_revision") != execution.get("model_revision")
            or host["identity"].get("host_id")
            not in value.get("scope", {}).get("hosts", [])
        ):
            raise CliError("grader_calibration differs from its Skill or Host")
        return
    plan_roles = {
        "current_summary": "target_current",
        "candidate_summary": "target_candidate",
        "holdout_summary": "target_holdout",
    }
    if role in plan_roles:
        registered = _registered_plan(campaign, plan_roles[role], skill_id)
        plan_path = resolve_binding(
            registered["plan"], repository_root, campaign_root
        )
        if content_hash(plan_path.read_bytes()) != registered["plan_digest"]:
            raise CliError(f"{role} registered plan bytes changed")
        plan = load_json(plan_path, label=f"{role} registered plan")
        if value.get("plan_id") != plan.get("plan_id"):
            raise CliError(f"{role} differs from its registered plan")
        return
    if role == "revision_report" and campaign["candidate"] is None:
        if campaign["profiles"]["predecessor"] is not None:
            raise CliError("candidate-null revision is only legal for bootstrap")
        current_binding = campaign["skill_evidence"][skill_id]["current_summary"]
        if current_binding is None:
            raise CliError("bootstrap revision lacks current summary evidence")
        current = _load_bound_document(
            current_binding,
            repository_root=repository_root,
            campaign_root=campaign_root,
            label="bootstrap current summary",
        )
        registered = _registered_plan(campaign, "target_current", skill_id)
        current_plan_path = resolve_binding(
            registered["plan"], repository_root, campaign_root
        )
        if content_hash(current_plan_path.read_bytes()) != registered["plan_digest"]:
            raise CliError("bootstrap current plan bytes changed")
        current_plan = load_json(
            current_plan_path,
            label="bootstrap current plan",
        )
        prior_registered = _registered_plan(campaign, "target_prior", skill_id)
        prior_plan_path = resolve_binding(
            prior_registered["plan"], repository_root, campaign_root
        )
        if content_hash(prior_plan_path.read_bytes()) != prior_registered["plan_digest"]:
            raise CliError("bootstrap prior plan bytes changed")
        prior_plan = load_json(prior_plan_path, label="bootstrap prior plan")
        inputs = value.get("inputs", [])
        candidate_inputs = [row for row in inputs if row.get("role") == "candidate"]
        prior_inputs = [row for row in inputs if row.get("role") == "prior"]
        prior_revision = (
            prior_inputs[0].get("execution_profile", {}).get("source_revision")
            if len(prior_inputs) == 1
            else None
        )
        if (
            len(inputs) != 2
            or len(candidate_inputs) != 1
            or len(prior_inputs) != 1
            or candidate_inputs[0].get("plan_id") != current.get("plan_id")
            or candidate_inputs[0].get("evaluation_id") != current.get("evaluation_id")
            or prior_inputs[0].get("plan_id") != prior_plan.get("plan_id")
            or prior_inputs[0].get("evaluation_id")
            != prior_plan.get("evaluation_id")
            or prior_inputs[0].get("evaluation_id") != current.get("evaluation_id")
            or candidate_inputs[0].get("execution_profile")
            != current_plan.get("execution_profile")
            or prior_inputs[0].get("execution_profile")
            != prior_plan.get("execution_profile")
            or candidate_inputs[0].get("execution_profile", {}).get("source_revision")
            != campaign["product"]["source_commit"]
            or not isinstance(prior_revision, str)
            or prior_revision == campaign["product"]["source_commit"]
        ):
            raise CliError("bootstrap revision must compare signed prior to current 8.0")
        try:
            git_identity(repository_root, prior_revision)
            prior_version = bundle_version_at_revision(repository_root, prior_revision)
        except OperationError as exc:
            raise CliError("bootstrap prior must be a signed repository revision") from exc
        if prior_version != "7.0.0":
            raise CliError("bootstrap prior must be Bundle 7.0.0")
        return
    required_fields = {
        "transition_report": ("current_summary",),
        "revision_report": ("current_summary", "candidate_summary"),
    }
    if role not in required_fields:
        return
    observed_plan_ids = {
        row.get("plan_id")
        for row in value.get("inputs", [])
        if isinstance(row, dict)
    }
    expected_plan_ids = set()
    for field in required_fields[role]:
        binding = campaign["skill_evidence"][skill_id][field]
        if binding is None:
            raise CliError(f"{role} lacks prior {field} evidence")
        summary = _load_bound_document(
            binding,
            repository_root=repository_root,
            campaign_root=campaign_root,
            label=f"{role} {field}",
        )
        expected_plan_ids.add(summary["plan_id"])
    if not expected_plan_ids <= observed_plan_ids:
        raise CliError(f"{role} inputs differ from the selected summaries")


def _require_initializable_sentinel(sentinel: dict[str, Any]) -> None:
    if sentinel.get("sentinel_id") == "frontier-four-skill-confirmatory-v1":
        raise CliError(
            "historical diagnostic confirmatory corpus cannot initialize a campaign"
        )


def _init(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign_root.mkdir(parents=True, exist_ok=True)
    controller_identity = git_identity(repository_root)
    product_root = (
        args.product_source_root.resolve(strict=True)
        if args.product_source_root is not None
        else repository_root
    )
    product_identity = git_identity(product_root)
    if product_identity["dirty"]:
        raise CliError("selected Bundle product source has tracked changes")
    ceilings = {
        "provider_requests": args.provider_request_ceiling,
        "execute": args.execute_ceiling,
        "model_grade": args.model_grade_ceiling,
        "reviewer": args.reviewer_ceiling,
        "optimizer": args.optimizer_ceiling,
        "download_bytes": args.download_byte_ceiling,
        "artifact_bytes": args.artifact_byte_ceiling,
        "candidates": args.candidate_ceiling,
    }
    if any(value < 0 for value in ceilings.values()):
        raise CliError("budget ceilings must be non-negative")
    if (
        ceilings["reviewer"] != 0
        or ceilings["optimizer"] != 0
        or ceilings["download_bytes"] != 0
        or ceilings["candidates"] != 1
        or ceilings["artifact_bytes"] != 1_073_741_824
    ):
        raise CliError(
            "campaign requires fixed artifact/candidate ceilings and zero reviewer/optimizer/download budget"
        )
    fixed = {
        "bundle_manifest": repository_root / "bundle-manifest.json",
        "bundle_build": repository_root / "frontier-engineering.bundle.json",
        "plugin_build": args.plugin_build_evidence.resolve(strict=True),
        "target_host": args.target_host.resolve(strict=True),
        "probe_set": args.probe_set.resolve(strict=True),
        "sentinel": args.sentinel_index.resolve(strict=True),
    }
    if args.apparatus_retry_policy is not None:
        fixed["apparatus_retry_policy"] = args.apparatus_retry_policy.resolve(
            strict=True
        )
    bindings = {
        name: _binding_for_path(
            path,
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        for name, path in fixed.items()
    }
    plugin_root = args.plugin_root.resolve(strict=True)
    if (
        args.plugin_root.is_symlink()
        or not plugin_root.is_dir()
        or not plugin_root.is_relative_to(campaign_root)
    ):
        raise CliError("plugin staging root must be a campaign-local directory")
    bundle_manifest = load_json(fixed["bundle_manifest"], label="Bundle manifest")
    bundle_build = load_json(fixed["bundle_build"], label="Bundle build")
    static_report = static_contracts.build_report(repository_root)
    if static_contracts.blocking_fact_count(static_report):
        raise CliError("static contract gate has blocking facts")
    plugin_build = validate_plugin_staging(
        repository_root=product_root,
        plugin_root=plugin_root,
        evidence_path=fixed["plugin_build"],
        expected_commit=product_identity["commit"],
        expected_bundle_id=static_report["bundle_id"],
        expected_bundle_version=bundle_manifest["bundle_version"],
        expected_skill_versions={
            skill_id: bundle_build["skills"][skill_id]["version"]
            for skill_id in SKILL_IDS
        },
    )
    target_host = validate_target_host_staging(
        fixed["target_host"],
        plugin_root,
        repository_root=repository_root,
        expected_commit=controller_identity["commit"],
        expected_tree=controller_identity["tree"],
    )
    probe_set = load_json(fixed["probe_set"], label="interaction probe set")
    validate_document(probe_set, "interaction_probes")
    expected_capabilities = [row["capability"] for row in probe_set["probes"]]
    actual_capabilities = [
        row["capability"] for row in target_host["capabilities"]
    ]
    if actual_capabilities != expected_capabilities:
        raise CliError("target Host capabilities differ from the interaction probe set")
    sentinel = load_json(fixed["sentinel"], label="sentinel index")
    validate_document(sentinel, "sentinel_index")
    _require_initializable_sentinel(sentinel)
    apparatus_policy = None
    if "apparatus_retry_policy" in fixed:
        apparatus_policy = validate_apparatus_retry_policy(
            load_json(
                fixed["apparatus_retry_policy"],
                label="apparatus retry policy",
            )
        )
        if bindings["apparatus_retry_policy"]["root"] != "campaign":
            raise CliError("apparatus retry policy must be campaign-local")
    sentinel_bootstrap_paths: set[Path] = set()
    if sentinel.get("schema_version") == "model-evolution-sentinel-index/3":
        pending: list[object] = [sentinel]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if value.get("root") == "campaign" and "path" in value:
                    sentinel_bootstrap_paths.add(
                        resolve_binding(value, repository_root, campaign_root)
                    )
                else:
                    pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
    request_ceilings = qualification_request_ceilings(
        sentinel,
        repository_root=repository_root,
        campaign_root=campaign_root,
        probe_count=len(probe_set["probes"]),
        apparatus_policy=apparatus_policy,
    )
    predecessor_paths = (
        args.predecessor_cycle,
        args.predecessor_host,
        args.predecessor_comparison,
    )
    if any(predecessor_paths) and not all(predecessor_paths):
        raise CliError("predecessor requires cycle, Host, and comparison together")
    if args.predecessor_qualification is not None and not all(predecessor_paths):
        raise CliError("predecessor qualification requires a predecessor cycle")
    predecessor = None
    if all(predecessor_paths):
        historical = {
            "cycle": _binding_for_path(
                args.predecessor_cycle,
                repository_root=repository_root,
                campaign_root=campaign_root,
                tracked_repository=False,
            ),
            "host": _binding_for_path(
                args.predecessor_host,
                repository_root=repository_root,
                campaign_root=campaign_root,
                tracked_repository=False,
            ),
            "comparison": _binding_for_path(
                args.predecessor_comparison,
                repository_root=repository_root,
                campaign_root=campaign_root,
                tracked_repository=False,
            ),
            "qualification": (
                _binding_for_path(
                    args.predecessor_qualification,
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                    tracked_repository=False,
                )
                if args.predecessor_qualification is not None
                else None
            ),
        }
        predecessor = prepare_predecessor(
            cycle_binding=historical["cycle"],
            host_binding=historical["host"],
            comparison_binding=historical["comparison"],
            qualification_binding=historical["qualification"],
            current_bundle_id=static_report["bundle_id"],
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
    try:
        require_qualification_request_ceilings(ceilings, request_ceilings)
    except ContractError as exc:
        raise CliError(str(exc)) from exc
    campaign = build_initial_campaign(
        campaign_id=args.campaign_id,
        git_identity=product_identity,
        bundle_manifest=bundle_manifest,
        bundle_manifest_binding=bindings["bundle_manifest"],
        bundle_build=bundle_build,
        bundle_build_binding=bindings["bundle_build"],
        plugin_build_binding=bindings["plugin_build"],
        plugin_root=plugin_root.relative_to(campaign_root).as_posix(),
        plugin_tree_hash=plugin_build["plugin_tree_hash"],
        calibration_requests=request_ceilings["calibration"],
        static_report=static_report,
        target_host_binding=bindings["target_host"],
        probe_set_binding=bindings["probe_set"],
        sentinel_binding=bindings["sentinel"],
        apparatus_retry_policy_binding=bindings.get("apparatus_retry_policy"),
        ceilings=ceilings,
        repository_root=repository_root,
        campaign_root=campaign_root,
        predecessor=predecessor,
    )
    if ceilings["provider_requests"] < len(probe_set["probes"]):
        raise CliError(
            "provider request ceiling cannot reserve the interaction probe set"
        )
    calibration_delta = max(
        0,
        request_ceilings["calibration_attempts"]
        - campaign["budgets"]["reserved"]["model_grade"],
    )
    if calibration_delta:
        reserve_budget(
            campaign,
            {
                "provider_requests": calibration_delta,
                "model_grade": calibration_delta,
            },
        )
        validate_campaign(campaign)
    if apparatus_policy is not None:
        reserve_budget(campaign, campaign_reserve_projection(apparatus_policy))
        validate_campaign(campaign)
    store = _campaign_store(repository_root, campaign_root)
    bootstrap_paths = {
        path for path in fixed.values() if path.is_relative_to(campaign_root)
    }
    bootstrap_paths.update(sentinel_bootstrap_paths)
    bootstrap_paths.update(path for path in plugin_root.rglob("*") if path.is_file())
    runtime_root = fixed["target_host"].with_name(
        f"{fixed['target_host'].stem}.runtime"
    )
    bootstrap_paths.update(
        runtime_root / name for name in ("codex", "codex-code-mode-host")
    )
    store.create(
        campaign,
        bootstrap_paths=tuple(sorted(bootstrap_paths)),
    )
    _emit(
        {
            "campaign_id": campaign["campaign_id"],
            "phase": campaign["phase"],
            "state_revision": campaign["state_revision"],
        }
    )


def _preflight(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("preflight expected revision is stale")
    report, env_allowlist = preflight_operations(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
        product_source_root=args.product_source_root,
    )
    if args.systemd_argv_only:
        systemd_probe_argv(
            f"frontier-{campaign['campaign_id']}-preflight",
            campaign_root / "systemd-preflight.closed",
        )
        report["operations"].append(
            {
                "operation_id": "systemd-user-argv",
                "status": "pass",
                "duration_ms": 0,
                "state_revision": campaign["state_revision"],
                "exit_code": None,
                "diagnostic": "argv projected without starting a service",
            }
        )
    else:
        report["operations"].append(
            verify_systemd_user(
                campaign["campaign_id"],
                env_allowlist,
            )
        )
    report_path = campaign_root / "apparatus-report.json"
    create_no_overwrite(report_path, report)
    report_binding = _binding_for_path(
        report_path,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    try:
        updated = store.mutate(
            args.expected_revision,
            lambda state: advance_preflight(state, report_binding),
        )
    except BaseException:
        report_path.unlink(missing_ok=True)
        raise
    _emit(
        {
            "campaign_id": updated["campaign_id"],
            "phase": updated["phase"],
            "state_revision": updated["state_revision"],
            "apparatus_report": report_binding,
        }
    )


def _rebind_product(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("rebind-product expected revision is stale")

    identity = git_identity(repository_root)
    ancestry = subprocess.run(
        [
            "git", "-C", str(repository_root), "merge-base", "--is-ancestor",
            campaign["product"]["source_commit"], identity["commit"],
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    if ancestry.returncode not in {0, 1}:
        raise CliError(f"source ancestry check failed: {ancestry.stderr.strip()}")

    plugin_root = args.plugin_root.resolve(strict=True)
    if (
        args.plugin_root.is_symlink()
        or not plugin_root.is_dir()
        or not plugin_root.is_relative_to(campaign_root)
    ):
        raise CliError("rebound plugin staging root must be campaign-local")
    plugin_binding = _binding_for_path(
        args.plugin_build_evidence,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    provisional_binding = _binding_for_path(
        args.target_host,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    observed_binding = _binding_for_path(
        args.target_observed_host,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    bundle_manifest = load_json(
        repository_root / "bundle-manifest.json", label="Bundle manifest"
    )
    bundle_build = load_json(
        repository_root / "frontier-engineering.bundle.json", label="Bundle build"
    )
    static_report = static_contracts.build_report(repository_root)
    if static_contracts.blocking_fact_count(static_report):
        raise CliError("static contract gate has blocking facts")
    plugin_build = validate_plugin_staging(
        repository_root=repository_root,
        plugin_root=plugin_root,
        evidence_path=args.plugin_build_evidence,
        expected_commit=identity["commit"],
        expected_bundle_id=static_report["bundle_id"],
        expected_bundle_version=bundle_manifest["bundle_version"],
        expected_skill_versions={
            skill_id: bundle_build["skills"][skill_id]["version"]
            for skill_id in SKILL_IDS
        },
    )
    provisional = validate_target_host_staging(
        args.target_host,
        plugin_root,
        repository_root=repository_root,
        expected_commit=identity["commit"],
        expected_tree=identity["tree"],
    )
    probe_set = _load_bound_document(
        campaign["interaction_probes"]["probe_set"],
        repository_root=repository_root,
        campaign_root=campaign_root,
        label="interaction probe set",
    )
    probe_results = _load_bound_document(
        campaign["interaction_probes"]["results"],
        repository_root=repository_root,
        campaign_root=campaign_root,
        label="interaction probe results",
    )
    expected_observed = project_observed_host(
        provisional,
        probe_set=probe_set,
        results=probe_results["requests"],
        observed_manifest_path=args.target_observed_host.resolve(),
    )
    observed = load_json(args.target_observed_host, label="rebound observed Host")
    if canonical_bytes(observed) != canonical_bytes(expected_observed):
        raise CliError("rebound observed Host differs from the frozen probe projection")

    product = copy.deepcopy(campaign["product"])
    product.update(
        {
            "bundle_id": static_report["bundle_id"],
            "bundle_version": bundle_manifest["bundle_version"],
            "source_commit": identity["commit"],
            "source_tree": identity["tree"],
            "plugin_tree": plugin_build["plugin_tree_hash"],
            "plugin_build": plugin_binding,
            "plugin_root": plugin_root.relative_to(campaign_root).as_posix(),
            "skills": {
                skill_id: {
                    "version": bundle_build["skills"][skill_id]["version"],
                    "root_hash": bundle_build["skills"][skill_id]["root_hash"],
                    "allow_implicit_invocation": bundle_build["skills"][skill_id][
                        "allow_implicit_invocation"
                    ],
                }
                for skill_id in SKILL_IDS
            },
        }
    )
    statuses = []
    for record in campaign["plans"]:
        plan_path = resolve_binding(
            record["plan"], repository_root, campaign_root
        )
        plan = load_json(plan_path, label="registered execution plan")
        statuses.append(
            runner_status(
                plan_path,
                _plan_index_path(plan_path, plan),
                repository_root=repository_root,
            )
        )

    proposed = copy.deepcopy(campaign)
    proposed["product"] = product
    proposed["profiles"]["target_provisional"] = provisional_binding
    proposed["profiles"]["target_observed"] = observed_binding
    proposed["phase"] = "declared"
    proposed["apparatus_report"] = None
    report, env_allowlist = preflight_operations(
        proposed,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    if args.systemd_argv_only:
        systemd_probe_argv(
            f"frontier-{campaign['campaign_id']}-rebind-preflight",
            campaign_root / "systemd-rebind-preflight.closed",
        )
        report["operations"].append(
            {
                "operation_id": "systemd-user-argv",
                "status": "pass",
                "duration_ms": 0,
                "state_revision": campaign["state_revision"],
                "exit_code": None,
                "diagnostic": "argv projected without starting a service",
            }
        )
    else:
        report["operations"].append(
            verify_systemd_user(campaign["campaign_id"], env_allowlist)
        )
    report_path = args.apparatus_report.resolve()
    if not report_path.is_relative_to(campaign_root):
        raise CliError("rebound apparatus report must be campaign-local")
    create_no_overwrite(report_path, report)
    report_binding = _binding_for_path(
        report_path,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    try:
        updated = store.mutate(
            args.expected_revision,
            lambda state: rebind_product(
                state,
                product=product,
                apparatus_report=report_binding,
                target_provisional=provisional_binding,
                target_observed=observed_binding,
                direct_descendant=ancestry.returncode == 0,
                runner_statuses=statuses,
            ),
        )
    except BaseException:
        report_path.unlink(missing_ok=True)
        raise
    _emit(
        {
            "campaign_id": updated["campaign_id"],
            "state_revision": updated["state_revision"],
            "phase": updated["phase"],
            "bundle_id": updated["product"]["bundle_id"],
            "apparatus_report": report_binding,
            "provider_requests": 0,
        }
    )


def _refresh_current_evidence(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("refresh-current-evidence expected revision is stale")
    rebinds = campaign.get("product_rebind_lineage", [])
    if len(rebinds) != 1:
        raise CliError("refresh-current-evidence requires exactly one D4 rebind")
    d4 = rebinds[0]
    old_product = d4.get("old_product", {})
    new_product = d4.get("new_product", {})
    if (
        old_product.get("source_commit") != D8_OLD_SOURCE
        or old_product.get("bundle_version") != "8.0.1"
        or old_product.get("plugin_tree") != D8_OLD_PLUGIN_TREE
        or new_product != campaign["product"]
        or new_product.get("source_commit") != D8_NEW_SOURCE
        or new_product.get("bundle_version") != "8.0.2"
        or new_product.get("plugin_tree") != D8_NEW_PLUGIN_TREE
        or tuple(sorted(d4.get("unchanged_skill_digests", {})))
        != tuple(sorted(D8_REFRESH_SKILLS))
    ):
        raise CliError("D4 product lineage differs from the D8 authority")

    def bound_bytes(binding: dict[str, Any], label: str) -> tuple[Path, bytes, str]:
        path = resolve_binding(binding, repository_root, campaign_root)
        if not path.is_file() or path.is_symlink():
            raise CliError(f"{label} is not a regular immutable file")
        payload = path.read_bytes()
        return path, payload, content_hash(payload)

    _, old_build_bytes, old_build_digest = bound_bytes(
        old_product["plugin_build"], "D4 old plugin build"
    )
    _, new_build_bytes, new_build_digest = bound_bytes(
        new_product["plugin_build"], "D4 new plugin build"
    )
    if (
        old_build_digest != D8_OLD_BUILD_DIGEST
        or new_build_digest != D8_NEW_BUILD_DIGEST
    ):
        raise CliError("D4 plugin build evidence digest differs from D8 authority")

    refreshed: dict[str, dict[str, Any]] = {}
    statuses: dict[str, dict[str, Any]] = {}
    stopped: dict[str, bool] = {}
    retained_wp: dict[str, Any] | None = None
    for skill_id in (*D8_REFRESH_SKILLS, "writing-plans"):
        record = _registered_plan(campaign, "target_current", skill_id)
        plan_path = resolve_binding(record["plan"], repository_root, campaign_root)
        if (
            plan_path.is_symlink()
            or content_hash(plan_path.read_bytes()) != record["plan_digest"]
        ):
            raise CliError(f"registered target_current/{skill_id} plan changed")
        plan = load_json(plan_path, label=f"target_current/{skill_id} plan")
        index = _plan_index_path(plan_path, plan)
        statuses[skill_id] = runner_status(
            plan_path, index, repository_root=repository_root
        )
        service_id = (
            f"frontier-{campaign['campaign_id']}-target_current-{skill_id}"
        )[:120]
        stopped[skill_id] = runner_service_stopped(service_id)

        summary_binding = campaign["skill_evidence"][skill_id]["current_summary"]
        if summary_binding is None:
            raise CliError(f"target_current/{skill_id} summary is not recorded")
        summary_path, _, summary_digest = bound_bytes(
            summary_binding, f"target_current/{skill_id} summary"
        )
        summary = load_json(summary_path, label=f"target_current/{skill_id} summary")
        subject = summary.get("subject", {})
        if (
            summary.get("plan_id") != plan.get("plan_id")
            or subject.get("skill_id") != skill_id
            or subject.get("source_revision") != plan.get("source_revision")
        ):
            raise CliError(f"target_current/{skill_id} summary differs from its plan")

        selected_path = plan_path.parent / "selected-plugin-build.json"
        if not selected_path.is_file() or selected_path.is_symlink():
            raise CliError(f"target_current/{skill_id} selected build is invalid")
        selected_bytes = selected_path.read_bytes()
        if skill_id in D8_REFRESH_SKILLS:
            if (
                plan.get("source_revision") != D8_OLD_SOURCE
                or selected_bytes != old_build_bytes
                or plan.get("package_digests", {}).get(skill_id)
                != d4["unchanged_skill_digests"][skill_id]
            ):
                raise CliError(f"target_current/{skill_id} is not the D4 old cycle")
            refreshed[skill_id] = {
                "old_current_summary": copy.deepcopy(summary_binding),
                "old_current_summary_digest": summary_digest,
                "old_plan": copy.deepcopy(record["plan"]),
                "old_plan_digest": record["plan_digest"],
                "unchanged_skill_digest": d4["unchanged_skill_digests"][skill_id],
                "old_plugin_build": copy.deepcopy(old_product["plugin_build"]),
                "old_plugin_build_digest": old_build_digest,
            }
            continue

        expected_packages = {
            item_id: identity["root_hash"]
            for item_id, identity in new_product["skills"].items()
        }
        catalog = {
            item.get("id"): item for item in plan.get("catalog", [])
            if isinstance(item, dict)
        }
        if (
            plan.get("source_revision") != D8_NEW_SOURCE
            or selected_bytes != new_build_bytes
            or plan.get("package_digests") != expected_packages
            or set(catalog) != set(new_product["skills"])
            or any(
                catalog[item_id].get("root_digest") != identity["root_hash"]
                or catalog[item_id].get("version") != identity["version"]
                for item_id, identity in new_product["skills"].items()
            )
        ):
            raise CliError("retained Writing Plans cycle differs from D4 new product")
        retained_wp = {
            "current_summary": copy.deepcopy(summary_binding),
            "current_summary_digest": summary_digest,
            "plan": copy.deepcopy(record["plan"]),
            "plan_digest": record["plan_digest"],
            "plugin_build": copy.deepcopy(new_product["plugin_build"]),
            "plugin_build_digest": new_build_digest,
            "source_commit": new_product["source_commit"],
            "skill_digest": new_product["skills"][skill_id]["root_hash"],
            "catalog_digest": content_hash(canonical_bytes(plan["catalog"])),
        }

    if retained_wp is None:
        raise CliError("retained Writing Plans proof was not produced")
    evidence = {
        "reason": "bundle_revision_full_product_alignment",
        "product_rebind_state_revision": d4["rebound_state_revision"],
        "refresh_before_state_revision": 26,
        "refresh_after_state_revision": 27,
        "old_product": copy.deepcopy(old_product),
        "new_product": copy.deepcopy(new_product),
        "refresh_set": list(D8_REFRESH_SKILLS),
        "refreshed_skills": refreshed,
        "retained_writing_plans": retained_wp,
    }
    updated = store.mutate(
        args.expected_revision,
        lambda state: refresh_current_evidence(
            state,
            evidence=evidence,
            runner_statuses=statuses,
            runners_stopped=stopped,
        ),
    )
    _emit({
        "campaign_id": updated["campaign_id"],
        "state_revision": updated["state_revision"],
        "phase": updated["phase"],
        "refresh_set": list(D8_REFRESH_SKILLS),
        "provider_requests": 0,
    })


def _validated_probe_inputs(
    campaign: dict[str, Any],
    approval_path: Path,
    *,
    repository_root: Path,
    campaign_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    approval = _binding_for_path(
        approval_path,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    approval_document = _load_bound_document(
        approval,
        repository_root=repository_root,
        campaign_root=campaign_root,
        label="budget approval",
    )
    validate_document(approval_document, "budget_approval")
    probe_set = _load_bound_document(
        campaign["interaction_probes"]["probe_set"],
        repository_root=repository_root,
        campaign_root=campaign_root,
        label="interaction probe set",
    )
    validate_document(probe_set, "interaction_probes")
    probe_ids = [row["probe_id"] for row in probe_set["probes"]]
    expected_approval = {
        "campaign_id": campaign["campaign_id"],
        "state_revision": campaign["state_revision"],
        "ceilings": campaign["budgets"]["ceiling"],
    }
    for field, value in expected_approval.items():
        if approval_document[field] != value:
            raise CliError(f"budget approval {field} differs from campaign")
    expected_planned = {
        "interaction_probe_requests": len(probe_ids),
        "public_plan_count": len(SKILL_IDS),
        "artifact_file_ceiling": 5_000,
        "wall_clock_seconds": 21_600,
    }
    if approval_document["planned"] != expected_planned:
        raise CliError("budget approval execution plan differs from campaign policy")
    return approval, probe_set, probe_ids


def _probe(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    with store.hold_probe_operation():
        _probe_exclusive(args, repository_root, campaign_root, store)


def _probe_exclusive(
    args: argparse.Namespace,
    repository_root: Path,
    campaign_root: Path,
    store: CampaignStore,
) -> None:
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("probe expected revision is stale")
    approval, probe_set, probe_ids = _validated_probe_inputs(
        campaign,
        args.budget_approval,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    existing = campaign["interaction_probes"]["requests"]
    resume_existing = bool(existing)
    if resume_existing:
        if campaign["interaction_probes"]["blocker"] is not None or any(
            request["status"] != "reserved" for request in existing
        ):
            raise CliError("probe reservation is not recoverable")
        reserved = campaign
    else:
        reserved = store.mutate(
            args.expected_revision,
            lambda state: reserve_probes(state, probe_ids),
        )
    try:
        outcome = run_interaction_probes(
            reserved,
            probe_set=probe_set,
            approval_binding=approval,
            repository_root=repository_root,
            campaign_root=campaign_root,
            resume_existing=resume_existing,
        )
    except (OperationError, ContractError, OSError) as error:
        reason = str(error)
        store.mutate(
            reserved["state_revision"],
            lambda state: block_probes(state, reason),
        )
        raise
    request_ids = {
        request["probe_id"]: request["request_id"]
        for request in reserved["interaction_probes"]["requests"]
    }
    critical_failures = sorted(
        row["capability"]
        for row in probe_set["probes"]
        if row["capability"] in CRITICAL_PROBE_CAPABILITIES
        and outcome["statuses"][request_ids[row["probe_id"]]] != "pass"
    )
    blocker = (
        "critical interaction probes did not pass: " + ", ".join(critical_failures)
        if critical_failures
        else None
    )
    updated = store.mutate(
        reserved["state_revision"],
        lambda state: close_probes(
            state,
            artifacts=outcome["artifacts"],
            statuses=outcome["statuses"],
            results_binding=outcome["results_binding"],
            observed_host_binding=outcome["observed_host_binding"],
            provider_requests=outcome["provider_requests"],
            blocker=blocker,
        ),
    )
    if updated["interaction_probes"]["blocker"] is not None:
        raise CliError(updated["interaction_probes"]["blocker"])
    _emit(
        {
            "campaign_id": updated["campaign_id"],
            "phase": updated["phase"],
            "state_revision": updated["state_revision"],
            "probe_results": outcome["results_binding"],
            "target_observed_host": outcome["observed_host_binding"],
        }
    )


def _plan_index_path(plan_path: Path, plan: dict[str, Any]) -> Path:
    artifacts = plan.get("artifacts")
    if not isinstance(artifacts, dict):
        raise CliError("execution plan artifact contract is missing")
    try:
        return plan_path.parent / artifacts["root"] / artifacts["index_relpath"]
    except (KeyError, TypeError) as exc:
        raise CliError("execution plan artifact paths are invalid") from exc


def _apparatus_policy_for_role(
    campaign: dict[str, Any],
    role: str,
    *,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, Any] | None:
    binding = campaign.get("apparatus_retry_policy")
    if binding is None:
        return None
    policy = validate_apparatus_retry_policy(
        _load_bound_document(
            binding,
            repository_root=repository_root,
            campaign_root=campaign_root,
            label="apparatus retry policy",
        )
    )
    return policy if role in policy["scope"]["roles"] else None


def _register_plan(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("register-plan expected revision is stale")
    if args.replace_existing != (args.superseded_plan is not None):
        raise CliError(
            "plan replacement requires --replace-existing and --superseded-plan"
        )
    plan_path = args.plan.resolve(strict=True)
    plan_binding = _binding_for_path(
        plan_path,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    if plan_binding["root"] != "campaign":
        raise CliError("formal execution plans must be campaign-root artifacts")
    plan = load_json(plan_path, label="execution plan")
    if not isinstance(plan, dict):
        raise CliError("execution plan must be an object")
    validator = {
        "target_current": validate_current_plan,
        "target_candidate": validate_candidate_plan,
        "target_prior": validate_prior_plan,
        "target_holdout": validate_holdout_plan,
    }[args.role]
    host = validator(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        plan_path=plan_path,
    )
    if args.skill_id not in plan.get("package_digests", {}):
        raise CliError("execution plan does not bind the selected Skill")
    if args.role == "target_current":
        expected_package_hash = campaign["product"]["skills"][args.skill_id][
            "root_hash"
        ]
    elif args.role == "target_candidate":
        if campaign["candidate"] is None:
            raise CliError("target_candidate plan has no accepted candidate")
        expected_package_hash = bundle_skill_at_revision(
            repository_root,
            campaign["candidate"]["candidate_commit"],
            args.skill_id,
        )["root_hash"]
    elif args.role == "target_prior":
        catalog_entries = host.get("catalog", {}).get("entries", [])
        selected = [
            item for item in catalog_entries
            if isinstance(item, dict) and item.get("id") == args.skill_id
        ]
        if len(selected) != 1 or not isinstance(
            selected[0].get("root_digest"), str
        ):
            raise CliError("target_prior Host lacks the selected Skill identity")
        expected_package_hash = selected[0]["root_digest"]
    else:
        plugin_binding = campaign["skill_evidence"]["plugin_build"]
        if plugin_binding is None:
            raise CliError("target_holdout plan has no selected plugin build")
        selected_skills = (
            campaign["candidate"]["skills"]
            if campaign["candidate"] is not None
            else campaign["product"]["skills"]
        )
        expected_package_hash = selected_skills[args.skill_id]["root_hash"]
    if plan["package_digests"][args.skill_id] != expected_package_hash:
        raise CliError("execution plan Skill package differs from its selected product")
    entries = plan.get("entries")
    if not isinstance(entries, list) or not entries or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("execute_case_payload"), dict)
        or entry["execute_case_payload"].get("subject_skill_id") != args.skill_id
        for entry in entries
    ):
        raise CliError("execution plan entries differ from the selected Skill")
    index_path = _plan_index_path(plan_path, plan)
    status = runner_status(plan_path, index_path, repository_root=repository_root)
    if (
        status["indexed_attempts"] != 0
        or status["active_attempts"]
        or status["recoverable_attempts"]
    ):
        raise CliError(
            "plan registration requires zero indexed, active, and recoverable attempts"
        )
    apparatus_policy = _apparatus_policy_for_role(
        campaign,
        args.role,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    projection = (
        plan_registration_projection(status, apparatus_policy)
        if apparatus_policy is not None
        else None
    )
    plan_record = {
        "role": args.role,
        "skill_id": args.skill_id,
        "plan": plan_binding,
        "plan_digest": content_hash(plan_path.read_bytes()),
        "host_id": host["identity"]["host_id"],
        "host_version": host["identity"]["host_version"],
        "execute_ceiling": (
            projection["execute"]
            if projection is not None
            else status["execute_case_request_ceiling"]
        ),
        "model_grade_ceiling": (
            projection["model_grade"]
            if projection is not None
            else status["model_grade_request_ceiling"]
        ),
        "runner_status": {
            "completed": status["completed_entries"],
            "total": status["selected_entries"],
            "failed": status["invalid_attempts"],
        },
    }
    old_status = None
    old_stopped = False
    if args.replace_existing:
        matches = [
            item for item in campaign["plans"]
            if item["role"] == args.role and item["skill_id"] == args.skill_id
        ]
        if len(matches) != 1:
            raise CliError("plan replacement requires one matching registered plan")
        old_record = matches[0]
        old_plan_path = args.superseded_plan.resolve(strict=True)
        old_binding = _binding_for_path(
            old_plan_path,
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        if old_binding["root"] != "campaign" or old_plan_path == plan_path:
            raise CliError("superseded plan must be a distinct campaign artifact")
        old_relative = old_plan_path.relative_to(campaign_root)
        if not old_relative.parts or old_relative.parts[0] != "superseded-plans":
            raise CliError("superseded plan must be under superseded-plans")
        if content_hash(old_plan_path.read_bytes()) != old_record["plan_digest"]:
            raise CliError("superseded plan differs from the registered plan")
        old_plan = load_json(old_plan_path, label="superseded execution plan")
        if not isinstance(old_plan, dict):
            raise CliError("superseded execution plan must be an object")
        old_index = _plan_index_path(old_plan_path, old_plan)
        old_status = runner_status(
            old_plan_path,
            old_index,
            repository_root=repository_root,
        )
        service_id = (
            f"frontier-{campaign['campaign_id']}-{args.role}-{args.skill_id}"
        )[:120]
        old_stopped = runner_service_stopped(service_id)
    updated = store.mutate(
        args.expected_revision,
        lambda state: register_plan(
            state,
            plan_record,
            replace_existing=args.replace_existing,
            old_runner_stopped=old_stopped,
            old_runner_status=old_status,
            new_runner_status=status,
        ),
    )
    command = render_runner_command(
        plan_path,
        index_path,
        attempt_budget=(
            projection["initial_attempt_budget"]
            if projection is not None
            else status["worst_case_remaining_attempts"]
        ),
        service_id=(f"frontier-{campaign['campaign_id']}-{args.role}-{args.skill_id}")[
            :120
        ],
        repository_root=repository_root,
    )
    _emit(
        {
            "campaign_id": updated["campaign_id"],
            "state_revision": updated["state_revision"],
            "phase": updated["phase"],
            "plan": plan_record,
            "runner_command": command,
        }
    )


def _prepare_calibration(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-calibration expected revision is stale")
    _emit(prepare_calibrations(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        as_of=args.as_of,
        created=args.created,
        expires=args.expires,
        max_workers=args.max_workers,
    ))


def _prepare_current(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-current expected revision is stale")
    result = prepare_current_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
    )
    _emit({
        "skill_id": args.skill_id,
        "plan_id": result["plan_id"],
        "plan_digest": result["plan_digest"],
        "plan": str(result["plan"]),
        "execute_ceiling": result["execute_ceiling"],
        "provider_requests": 0,
    })


def _prepare_candidate(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-candidate expected revision is stale")
    result = prepare_candidate_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        plugin_root=args.plugin_root,
        plugin_evidence=args.plugin_build_evidence,
    )
    _emit({
        "skill_id": args.skill_id,
        "plan_id": result["plan_id"],
        "plan_digest": result["plan_digest"],
        "plan": str(result["plan"]),
        "execute_ceiling": result["execute_ceiling"],
        "provider_requests": 0,
    })


def _prepare_prior(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-prior expected revision is stale")
    result = prepare_prior_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        prior_source_root=args.prior_source_root,
        plugin_root=args.plugin_root,
        plugin_evidence=args.plugin_build_evidence,
    )
    _emit({
        "skill_id": args.skill_id,
        "plan_id": result["plan_id"],
        "plan_digest": result["plan_digest"],
        "plan": str(result["plan"]),
        "execute_ceiling": result["execute_ceiling"],
        "provider_requests": 0,
    })


def _prepare_holdout(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-holdout expected revision is stale")
    result = prepare_holdout_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        plugin_root=args.plugin_root,
        holdout_root=args.holdout_root,
    )
    _emit({
        "skill_id": args.skill_id,
        "plan_id": result["plan_id"],
        "plan_digest": result["plan_digest"],
        "plan": str(result["plan"]),
        "execute_ceiling": result["execute_ceiling"],
        "provider_requests": 0,
    })


def _prepare_manual_review(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-manual-review expected revision is stale")
    registered = _registered_plan(campaign, "target_holdout", args.skill_id)
    plan_path = args.plan.resolve(strict=True)
    if (
        resolve_binding(registered["plan"], repository_root, campaign_root)
        != plan_path
        or content_hash(plan_path.read_bytes()) != registered["plan_digest"]
    ):
        raise CliError("manual review differs from its registered holdout plan")
    result = prepare_manual_review_receipt(
        campaign_root=campaign_root,
        skill_id=args.skill_id,
        plan_path=plan_path,
        decision=args.decision,
        signature=args.signature,
    )
    _emit({
        "skill_id": args.skill_id,
        "decision": args.decision,
        "input_binding": str(result["binding"]),
        "receipt": str(result["receipt"]),
        "provider_requests": 0,
    })


def _prepare_analysis(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-analysis expected revision is stale")
    result = prepare_analysis(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        role=args.role,
        skill_id=args.skill_id,
        analysis_variant=args.analysis_variant,
    )
    _emit({
        "skill_id": args.skill_id,
        "role": args.role,
        "summary": str(result["summary"]),
        "failure_index": str(result["failure_index"]),
        "provider_requests": 0,
    })


def _prepare_revision_report(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("prepare-revision expected revision is stale")
    result = prepare_revision_report(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
    )
    _emit({
        "skill_id": args.skill_id,
        "status": result["status"],
        "report": str(result["report"]),
        "diagnostic_index": str(result["diagnostic_index"]),
        "provider_requests": 0,
    })


def _verify_plan(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    validator = {
        "target_current": validate_current_plan,
        "target_candidate": validate_candidate_plan,
        "target_prior": validate_prior_plan,
        "target_holdout": validate_holdout_plan,
    }[args.role]
    host = validator(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        plan_path=args.plan.resolve(strict=True),
    )
    _emit({
        "status": "valid",
        "role": args.role,
        "skill_id": args.skill_id,
        "host_id": host["identity"]["host_id"],
        "host_version": host["identity"]["host_version"],
        "provider_requests": 0,
    })


def _close_calibration_failure(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    receipt = close_calibration_failure(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        output=args.output.resolve(),
    )
    binding = _binding_for_path(
        args.output.resolve(),
        repository_root=repository_root,
        campaign_root=campaign_root,
        tracked_repository=False,
        external=True,
    )
    _emit({
        "failure_receipt": binding,
        "artifact_digest": binding["digest"],
        "request_count": receipt["request_count"],
    })


def _close_calibration_rejection(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    receipt = close_calibration_rejection(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        output=args.output.resolve(),
    )
    binding = _binding_for_path(
        args.output.resolve(),
        repository_root=repository_root,
        campaign_root=campaign_root,
        tracked_repository=False,
        external=True,
    )
    _emit({
        "calibration_rejection_receipt": binding,
        "artifact_digest": binding["digest"],
        "request_count": receipt["request_count"],
    })


def _record_candidate(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("candidate_source expected revision is stale")
    sentinel = _load_bound_document(
        campaign["sentinel_index"],
        repository_root=repository_root,
        campaign_root=campaign_root,
        label="sentinel index",
    )
    candidate = candidate_source(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        sentinel=sentinel,
        base_commit=args.base_commit,
        candidate_commit=args.candidate_commit,
        owner_surface=args.owner_surface,
        root_cause_ids=args.root_cause_id,
        semantic_changes=args.semantic_change,
    )
    updated = store.mutate(
        args.expected_revision,
        lambda state: accept_candidate(state, candidate),
    )
    _emit(
        {
            "campaign_id": updated["campaign_id"],
            "state_revision": updated["state_revision"],
            "phase": updated["phase"],
            "candidate": candidate,
        }
    )


def _record(args: argparse.Namespace) -> None:
    if args.role == "candidate_source":
        _record_candidate(args)
        return
    repository_root, campaign_root = _roots(args)
    if args.artifact is None:
        raise CliError(f"record {args.role} requires --artifact")
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("record expected revision is stale")
    binding = _binding_for_path(
        args.artifact,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    path = resolve_binding(binding, repository_root, campaign_root)
    evidence_status: str | None = None
    if args.role in {
        "grader_calibration",
        "current_summary",
        "transition_report",
        "candidate_summary",
        "revision_report",
        "holdout_summary",
    }:
        expected_gates = None
        if args.role in {"current_summary", "candidate_summary", "holdout_summary"}:
            if args.skill_id is None:
                raise CliError(f"{args.role} requires skill-id")
            sentinel = _load_bound_document(
                campaign["sentinel_index"],
                repository_root=repository_root,
                campaign_root=campaign_root,
                label="sentinel index",
            )
            spec = _load_bound_document(
                sentinel["skills"][args.skill_id]["spec_template"],
                repository_root=repository_root,
                campaign_root=campaign_root,
                label=f"{args.skill_id} sentinel spec",
            )
            expected_gates = spec["hard_gates"]
        evidence_status = evaluator_evidence_status(
            path,
            kind=args.role,
            expected_gates=expected_gates,
        )
        if evidence_status == "blocked":
            raise CliError(f"{args.role} is not valid closure evidence")
        if args.skill_id is not None:
            evidence = load_json(path, label=args.role)
            if not isinstance(evidence, dict):
                raise CliError(f"{args.role} must be a JSON object")
            _validate_evidence_join(
                campaign,
                role=args.role,
                skill_id=args.skill_id,
                value=evidence,
                repository_root=repository_root,
                campaign_root=campaign_root,
            )
    elif args.role == "plugin_build":
        if args.plugin_root is None:
            raise CliError("record plugin_build requires --plugin-root")
        expected_commit = (
            campaign["candidate"]["candidate_commit"]
            if campaign["candidate"] is not None
            else campaign["product"]["source_commit"]
        )
        product_root = (
            args.product_source_root.resolve(strict=True)
            if args.product_source_root is not None
            else repository_root
        )
        product_identity = git_identity(product_root)
        if (
            product_identity["commit"] != expected_commit
            or product_identity["dirty"]
        ):
            raise CliError("plugin build is not from the selected signed clean commit")
        expected_skills = (
            campaign["candidate"]["skills"]
            if campaign["candidate"] is not None
            else campaign["product"]["skills"]
        )
        expected_bundle = load_json(
            product_root / "bundle-manifest.json",
            label="selected Bundle manifest",
        )
        expected_generated_bundle = load_json(
            product_root / "frontier-engineering.bundle.json",
            label="selected generated Bundle",
        )
        plugin_root = args.plugin_root.resolve(strict=True)
        if (
            args.plugin_root.is_symlink()
            or not plugin_root.is_dir()
            or not plugin_root.is_relative_to(campaign_root)
        ):
            raise CliError("selected plugin staging must be campaign-local")
        validate_plugin_staging(
            repository_root=product_root,
            plugin_root=plugin_root,
            evidence_path=path,
            expected_commit=expected_commit,
            expected_bundle_id=expected_generated_bundle["bundle_id"],
            expected_bundle_version=expected_bundle["bundle_version"],
            expected_skill_versions={
                skill_id: expected_skills[skill_id]["version"] for skill_id in SKILL_IDS
            },
        )
        if campaign["candidate"] is None:
            expected_root = campaign_root / campaign["product"]["plugin_root"]
            if (
                binding != campaign["product"]["plugin_build"]
                or plugin_root != expected_root
            ):
                raise CliError("current selection must reuse the frozen plugin staging")
        elif binding["root"] != "campaign":
            raise CliError("candidate plugin build evidence must be campaign-local")
    observed: dict[str, int | None] | None = None
    if args.role == "grader_calibration":
        current = campaign["budgets"]["observed"]
        sentinel = _load_bound_document(
            campaign["sentinel_index"],
            repository_root=repository_root,
            campaign_root=campaign_root,
            label="sentinel index",
        )
        calibration = sentinel["skills"][args.skill_id][
            "calibration_request_ceiling"
        ]
        attempts = calibration_attempt_count(
            campaign_root,
            args.skill_id,
            calibration,
        )
        observed = {
            "provider_requests": None
            if current["provider_requests"] is None
            else current["provider_requests"] + attempts,
            "model_grade": (current["model_grade"] or 0) + attempts,
        }
    elif args.role in {"current_summary", "candidate_summary", "holdout_summary"}:
        summary = load_json(path, label=args.role)
        attempts = summary["counts"]["attempts"]
        current = campaign["budgets"]["observed"]
        observed = {
            "execute": (current["execute"] or 0) + attempts,
            "provider_requests": None,
            "model_grade": None,
            "artifact_bytes": None,
        }

    def mutation(state: dict[str, Any]) -> None:
        record_evidence(
            state,
            role=args.role,
            binding=binding,
            skill_id=args.skill_id,
        )
        if observed is not None:
            record_observed_budget(state, observed)

    updated = store.mutate(args.expected_revision, mutation)
    _emit(
        {
            "campaign_id": updated["campaign_id"],
            "state_revision": updated["state_revision"],
            "phase": updated["phase"],
            "role": args.role,
            "skill_id": args.skill_id,
            "artifact": binding,
            "evidence_status": evidence_status,
        }
    )


def _status(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    blockers: list[dict[str, str]] = []
    statuses: list[dict[str, Any]] = []
    commands: list[str] = []
    probe_running = False
    probe_command: str | None = None
    approval_path: Path | None = None
    probe_blocker = campaign["interaction_probes"]["blocker"]
    probe_reserved = any(
        request["status"] == "reserved"
        for request in campaign["interaction_probes"]["requests"]
    )
    if probe_blocker is not None:
        blockers.append({"code": "interaction-probe", "message": probe_blocker})
    elif campaign["phase"] == "apparatus_ready":
        try:
            probe_running = store.probe_operation_running()
        except StateError as exc:
            blockers.append(
                {"code": "probe-operation-lock", "message": str(exc)}
            )
        if not blockers and not probe_running:
            if probe_reserved:
                blockers.append(
                    {
                        "code": "probe-reservation",
                        "message": "partial probe reservation requires manual diagnosis",
                    }
                )
            else:
                candidate = campaign_root / "budget-approval.json"
                if candidate.exists() or candidate.is_symlink():
                    approval_path = candidate
        if approval_path is not None:
            try:
                _validated_probe_inputs(
                    campaign,
                    approval_path,
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                )
                probe_command = render_probe_command(
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                    expected_revision=campaign["state_revision"],
                    budget_approval=approval_path,
                    service_id=(
                        f"frontier-{campaign['campaign_id']}-probe-"
                        f"r{campaign['state_revision']}"
                    )[:120],
                )
            except (CliError, ContractError, OperationError, OSError, KeyError) as exc:
                blockers.append(
                    {"code": "budget-approval-invalid", "message": str(exc)}
                )
    if campaign["profiles"]["target_observed"] is not None:
        probe_status, _, probe_gate_blockers = assess_interaction_probes(
            campaign,
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        if probe_status == "blocked":
            blockers.extend(
                {
                    "code": item["code"],
                    "message": f"{item['scope']} interaction probe is not pass",
                }
                for item in probe_gate_blockers
            )
    qualification_root = campaign_root / "qualification"
    qualification_complete = False
    if qualification_root.is_symlink():
        blockers.append(
            {
                "code": "qualification-path",
                "message": "qualification directory is symlinked",
            }
        )
    elif qualification_root.is_dir():
        try:
            _load_verified_qualification(repository_root, campaign_root, campaign)
            qualification_complete = True
        except (CliError, ContractError, OSError, KeyError, TypeError) as exc:
            blockers.append(
                {
                    "code": "qualification-invalid",
                    "message": str(exc),
                }
            )
    try:
        identity = git_identity(repository_root)
        expected_commit = campaign["product"]["source_commit"]
        expected_tree = campaign["product"]["source_tree"]
        provisional = campaign["profiles"].get("target_provisional")
        if provisional is not None:
            host = _load_bound_document(
                provisional,
                repository_root=repository_root,
                campaign_root=campaign_root,
                label="target provisional Host",
            )
            repository_identity = host.get("identity", {}).get("repository", {})
            expected_commit = repository_identity.get("revision", expected_commit)
            expected_tree = repository_identity.get("tree", expected_tree)
        if (
            identity["commit"] != expected_commit
            or identity["tree"] != expected_tree
        ):
            blockers.append(
                {
                    "code": "source-drift",
                    "message": "checked-out controller commit differs from Host authority",
                }
            )
    except OperationError as exc:
        blockers.append({"code": "source-state", "message": str(exc)})
    for plan_record in campaign["plans"]:
        try:
            plan_path = resolve_binding(
                plan_record["plan"], repository_root, campaign_root
            )
            plan = load_json(plan_path, label="registered plan")
            index = _plan_index_path(plan_path, plan)
            status = runner_status(plan_path, index, repository_root=repository_root)
            observed_counts = {
                "completed": status["completed_entries"],
                "total": status["selected_entries"],
                "failed": status["invalid_attempts"],
            }
            if observed_counts == plan_record["runner_status"]:
                registration_status = "unchanged"
            else:
                registration_status = "advanced"
            status_record = {
                "role": plan_record["role"],
                "skill_id": plan_record["skill_id"],
                "registration_status": registration_status,
                **status,
            }
            statuses.append(status_record)
            if (
                status["remaining_entries"]
                and not status["active_attempts"]
                and (
                    not status["invalid_attempts"]
                    or status["recoverable_attempts"]
                )
            ):
                apparatus_policy = _apparatus_policy_for_role(
                    campaign,
                    plan_record["role"],
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                )
                if apparatus_policy is None:
                    attempt_budget = status["worst_case_remaining_attempts"]
                elif status["recoverable_attempts"]:
                    attempt_budget = 0
                else:
                    attempt_budget = status["next_pass_new_attempts"]
                commands.append(
                    render_runner_command(
                        plan_path,
                        index,
                        attempt_budget=attempt_budget,
                        service_id=(
                            f"frontier-{campaign['campaign_id']}-{plan_record['role']}-"
                            f"{plan_record['skill_id']}"
                        )[:120],
                        repository_root=repository_root,
                        resume=bool(
                            status["indexed_attempts"]
                            or status["recoverable_attempts"]
                        ),
                    )
                )
        except (ContractError, OperationError, OSError, KeyError, TypeError) as exc:
            blockers.append(
                {
                    "code": "plan-status",
                    "message": f"{plan_record['role']}/{plan_record['skill_id']}: {exc}",
                }
            )
    projection = status_projection(
        campaign,
        plan_statuses=statuses,
        blockers=blockers,
        runner_commands=commands,
        probe_running=probe_running,
        probe_command=probe_command,
    )
    if not projection["blockers"] and campaign["plans"]:
        if projection["active_attempts"]:
            projection["next_event"] = "monitor registered plans"
        elif projection["recoverable_attempts"]:
            projection["next_event"] = "resume registered plans"
        elif commands:
            projection["next_event"] = "run registered plans"
        else:
            projection["next_event"] = "record registered plan evidence"
    if qualification_complete and not projection["blockers"]:
        projection["next_event"] = "qualification_complete"
        projection["runner_commands"] = []
    if args.json:
        _emit(projection)
    else:
        print(
            f"{projection['campaign_id']} revision={projection['state_revision']} "
            f"phase={projection['phase']} active={projection['active_attempts']} "
            f"recoverable={projection['recoverable_attempts']} "
            f"probe_running={projection['probe_running']}"
        )
        print(f"next={projection['next_event'] or 'blocked'}")
        for blocker in projection["blockers"]:
            print(f"blocker {blocker['code']}: {blocker['message']}")
        for command in projection["runner_commands"]:
            print(command)


def _apparatus_status(args: argparse.Namespace) -> None:
    """Project the bound policy across all indexed campaign plan attempts."""
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("apparatus-status expected revision is stale")
    policy_binding = campaign.get("apparatus_retry_policy")
    if policy_binding is None:
        raise CliError("campaign has no versioned apparatus retry policy")
    policy = validate_apparatus_retry_policy(
        _load_bound_document(
            policy_binding,
            repository_root=repository_root,
            campaign_root=campaign_root,
            label="apparatus retry policy",
        )
    )
    target = _registered_plan(campaign, args.role, args.skill_id)
    projections: dict[tuple[str, str], dict[str, Any]] = {}
    global_apparatus_attempts = 0
    for record in campaign["plans"]:
        plan_path = resolve_binding(record["plan"], repository_root, campaign_root)
        plan = load_json(plan_path, label="registered execution plan")
        projection = audit_plan_transport(
            plan_path,
            _plan_index_path(plan_path, plan),
            policy,
        )
        projections[(record["role"], record["skill_id"])] = projection
        global_apparatus_attempts += projection["apparatus_attempts"]
    selected = projections[(target["role"], target["skill_id"])]
    reserve = policy["request_budget"]["apparatus_attempt_reserve"]
    if selected["next_entry_id"] is None:
        action = "complete"
        reason = None
    elif global_apparatus_attempts >= reserve:
        action = "stop"
        reason = "campaign_apparatus_reserve_exhausted"
    elif selected["terminal_reason"] is not None:
        action = "stop"
        reason = selected["terminal_reason"]
    elif selected["next_attempt"] is not None and selected["next_attempt"] > 1:
        action = "retry_frontier"
        reason = None
    else:
        action = "run_natural_prefix"
        reason = None
    _emit(
        {
            "campaign_id": campaign["campaign_id"],
            "state_revision": campaign["state_revision"],
            "role": args.role,
            "skill_id": args.skill_id,
            "action": action,
            "reason": reason,
            "plan": selected,
            "campaign_apparatus_attempts": global_apparatus_attempts,
            "campaign_apparatus_remaining": max(
                0, reserve - global_apparatus_attempts
            ),
            "provider_requests": 0,
            "reviewer_requests": 0,
        }
    )


def _qualify(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)

    def projector(state: dict[str, Any]) -> tuple[dict[str, Any], str]:
        qualification = project_qualification(
            state,
            repository_root=repository_root,
            campaign_root=campaign_root,
            observed_as_of=args.observed_as_of,
            valid_until=args.valid_until,
        )
        if qualification["decision"] != "blocked" and state["phase"] != "holdout_ready":
            raise CliError("pass or limited qualification requires holdout_ready")
        return qualification, render_qualification_markdown(qualification)

    campaign, target = store.publish_qualification(args.expected_revision, projector)
    qualification = load_json(target / "qualification.json", label="qualification")
    _emit(
        {
            "qualification": _binding_for_path(
                target / "qualification.json",
                repository_root=repository_root,
                campaign_root=campaign_root,
            ),
            "decision": qualification["decision"],
            "campaign_revision": campaign["state_revision"],
        }
    )


def _load_verified_qualification(
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
) -> dict[str, Any]:
    qualification_root = campaign_root / "qualification"
    if qualification_root.is_symlink() or not qualification_root.is_dir():
        raise CliError("qualification directory is missing or symlinked")
    qualification = load_json(
        qualification_root / "qualification.json", label="qualification"
    )
    validate_qualification(qualification)
    if (
        qualification["campaign_id"] != campaign["campaign_id"]
        or qualification["terminal_state_revision"] != campaign["state_revision"]
    ):
        raise CliError("qualification identity differs from current campaign state")
    projected = project_qualification(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
        observed_as_of=qualification["validity"]["observed_as_of"],
        valid_until=qualification["validity"]["valid_until"],
    )
    if canonical_bytes(projected) != canonical_bytes(qualification):
        raise CliError("qualification differs from deterministic projection")
    markdown = (qualification_root / "qualification.md").read_text(encoding="utf-8")
    if markdown != render_qualification_markdown(qualification):
        raise CliError("qualification Markdown differs from JSON projection")
    return qualification


def _verify(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    qualification = _load_verified_qualification(
        repository_root, campaign_root, campaign
    )
    _emit(
        {
            "qualification_id": qualification["qualification_id"],
            "decision": qualification["decision"],
            "verified": True,
        }
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="Frontier source repository root",
    )
    parser.add_argument("--campaign-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--campaign-id", required=True)
    init.add_argument(
        "--product-source-root",
        type=Path,
        help="separate clean Bundle product worktree; defaults to the controller root",
    )
    init.add_argument("--plugin-root", type=Path, required=True)
    init.add_argument("--plugin-build-evidence", type=Path, required=True)
    init.add_argument("--target-host", type=Path, required=True)
    init.add_argument("--probe-set", type=Path, required=True)
    init.add_argument("--sentinel-index", type=Path, required=True)
    init.add_argument("--apparatus-retry-policy", type=Path)
    init.add_argument("--predecessor-cycle", type=Path)
    init.add_argument("--predecessor-host", type=Path)
    init.add_argument("--predecessor-comparison", type=Path)
    init.add_argument("--predecessor-qualification", type=Path)
    init.add_argument("--provider-request-ceiling", type=int, required=True)
    init.add_argument("--execute-ceiling", type=int, required=True)
    init.add_argument("--model-grade-ceiling", type=int, required=True)
    init.add_argument("--artifact-byte-ceiling", type=int, required=True)
    init.add_argument("--download-byte-ceiling", type=int, default=0)
    init.add_argument("--candidate-ceiling", type=int, default=1)
    init.add_argument("--reviewer-ceiling", type=int, default=0)
    init.add_argument("--optimizer-ceiling", type=int, default=0)

    preflight = commands.add_parser("preflight")
    preflight.add_argument("--expected-revision", type=int, required=True)
    preflight.add_argument(
        "--product-source-root",
        type=Path,
        help="clean Bundle product worktree bound by campaign product identity",
    )
    preflight.add_argument(
        "--systemd-argv-only",
        action="store_true",
        help="CI-only: validate the transient service argv without starting it",
    )

    rebind = commands.add_parser("rebind-product")
    rebind.add_argument("--expected-revision", type=int, required=True)
    rebind.add_argument("--plugin-root", type=Path, required=True)
    rebind.add_argument("--plugin-build-evidence", type=Path, required=True)
    rebind.add_argument("--target-host", type=Path, required=True)
    rebind.add_argument("--target-observed-host", type=Path, required=True)
    rebind.add_argument("--apparatus-report", type=Path, required=True)
    rebind.add_argument("--systemd-argv-only", action="store_true")

    refresh = commands.add_parser("refresh-current-evidence")
    refresh.add_argument("--expected-revision", type=int, required=True)

    probe = commands.add_parser("probe")
    probe.add_argument("--expected-revision", type=int, required=True)
    probe.add_argument("--budget-approval", type=Path, required=True)

    calibration = commands.add_parser("prepare-calibration")
    calibration.add_argument("--expected-revision", type=int, required=True)
    calibration.add_argument("--as-of", required=True)
    calibration.add_argument("--created", required=True)
    calibration.add_argument("--expires", required=True)
    calibration.add_argument(
        "--max-workers", type=int, choices=range(1, 5), default=1,
    )

    current = commands.add_parser("prepare-current")
    current.add_argument("--expected-revision", type=int, required=True)
    current.add_argument("--skill-id", choices=SKILL_IDS, required=True)

    candidate = commands.add_parser("prepare-candidate")
    candidate.add_argument("--expected-revision", type=int, required=True)
    candidate.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    candidate.add_argument("--plugin-root", type=Path, required=True)
    candidate.add_argument("--plugin-build-evidence", type=Path, required=True)

    prior = commands.add_parser("prepare-prior")
    prior.add_argument("--expected-revision", type=int, required=True)
    prior.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    prior.add_argument("--prior-source-root", type=Path, required=True)
    prior.add_argument("--plugin-root", type=Path, required=True)
    prior.add_argument("--plugin-build-evidence", type=Path, required=True)

    holdout = commands.add_parser("prepare-holdout")
    holdout.add_argument("--expected-revision", type=int, required=True)
    holdout.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    holdout.add_argument("--plugin-root", type=Path, required=True)
    holdout.add_argument("--holdout-root", type=Path, required=True)

    manual_review = commands.add_parser("prepare-manual-review")
    manual_review.add_argument("--expected-revision", type=int, required=True)
    manual_review.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    manual_review.add_argument("--plan", type=Path, required=True)
    manual_review.add_argument(
        "--decision", choices=("approve", "hold", "reject"), required=True
    )
    manual_review.add_argument("--signature", required=True)

    analysis = commands.add_parser("prepare-analysis")
    analysis.add_argument("--expected-revision", type=int, required=True)
    analysis.add_argument("--role", choices=sorted(ANALYSIS_ROLES), required=True)
    analysis.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    analysis.add_argument("--analysis-variant")

    revision = commands.add_parser("prepare-revision")
    revision.add_argument("--expected-revision", type=int, required=True)
    revision.add_argument("--skill-id", choices=SKILL_IDS, required=True)

    verify_plan = commands.add_parser("verify-plan")
    verify_plan.add_argument(
        "--role",
        choices=(
            "target_current", "target_candidate", "target_prior", "target_holdout",
        ),
        required=True,
    )
    verify_plan.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    verify_plan.add_argument("--plan", type=Path, required=True)

    failure = commands.add_parser("close-calibration-failure")
    failure.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    failure.add_argument("--output", type=Path, required=True)

    rejection = commands.add_parser("close-calibration-rejection")
    rejection.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    rejection.add_argument("--output", type=Path, required=True)

    register = commands.add_parser("register-plan")
    register.add_argument("--expected-revision", type=int, required=True)
    register.add_argument(
        "--role",
        choices=(
            "target_current", "target_candidate", "target_prior", "target_holdout",
        ),
        required=True,
    )
    register.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    register.add_argument("--plan", type=Path, required=True)
    register.add_argument("--replace-existing", action="store_true")
    register.add_argument("--superseded-plan", type=Path)

    record = commands.add_parser("record")
    record.add_argument("--expected-revision", type=int, required=True)
    record.add_argument("--role", choices=RECORD_ROLES, required=True)
    record.add_argument("--skill-id", choices=SKILL_IDS)
    record.add_argument("--artifact", type=Path)
    record.add_argument("--plugin-root", type=Path)
    record.add_argument("--base-commit")
    record.add_argument("--candidate-commit")
    record.add_argument("--owner-surface", choices=SKILL_IDS)
    record.add_argument("--product-source-root", type=Path)
    record.add_argument("--root-cause-id", action="append", default=[])
    record.add_argument("--semantic-change", action="append", default=[])

    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true")

    apparatus = commands.add_parser("apparatus-status")
    apparatus.add_argument("--expected-revision", type=int, required=True)
    apparatus.add_argument(
        "--role",
        choices=("target_current", "target_prior", "target_holdout"),
        required=True,
    )
    apparatus.add_argument("--skill-id", choices=SKILL_IDS, required=True)

    qualify = commands.add_parser("qualify")
    qualify.add_argument("--expected-revision", type=int, required=True)
    qualify.add_argument("--observed-as-of", required=True)
    qualify.add_argument("--valid-until", required=True)

    commands.add_parser("verify")
    return parser


def _validate_record_args(args: argparse.Namespace) -> None:
    candidate_fields = (
        args.base_commit,
        args.candidate_commit,
        args.owner_surface,
        args.root_cause_id,
        args.semantic_change,
    )
    if args.role == "candidate_source":
        if args.artifact is not None or args.skill_id is not None:
            raise CliError("candidate_source rejects artifact and skill-id")
        if (
            not all(candidate_fields[:3])
            or not args.root_cause_id
            or not args.semantic_change
        ):
            raise CliError(
                "candidate_source requires commits, owner, root cause, and semantic change"
            )
    elif any(candidate_fields[:3]) or args.root_cause_id or args.semantic_change:
        raise CliError("candidate-only arguments require role candidate_source")
    if args.role != "plugin_build" and args.plugin_root is not None:
        raise CliError("--plugin-root is only valid for role plugin_build")
    if args.role != "plugin_build" and args.product_source_root is not None:
        raise CliError("--product-source-root is only valid for role plugin_build")
    if args.role == "plugin_build" and args.skill_id is not None:
        raise CliError(f"{args.role} is campaign-scoped and rejects skill-id")
    if args.role not in {"plugin_build", "candidate_source"}:
        if args.skill_id is None:
            raise CliError(f"{args.role} requires skill-id")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "record":
            _validate_record_args(args)
        dispatch = {
            "init": _init,
            "preflight": _preflight,
            "rebind-product": _rebind_product,
            "refresh-current-evidence": _refresh_current_evidence,
            "probe": _probe,
            "prepare-calibration": _prepare_calibration,
            "prepare-current": _prepare_current,
            "prepare-candidate": _prepare_candidate,
            "prepare-prior": _prepare_prior,
            "prepare-holdout": _prepare_holdout,
            "prepare-manual-review": _prepare_manual_review,
            "prepare-analysis": _prepare_analysis,
            "prepare-revision": _prepare_revision_report,
            "verify-plan": _verify_plan,
            "close-calibration-failure": _close_calibration_failure,
            "close-calibration-rejection": _close_calibration_rejection,
            "register-plan": _register_plan,
            "record": _record,
            "status": _status,
            "apparatus-status": _apparatus_status,
            "qualify": _qualify,
            "verify": _verify,
        }
        dispatch[args.command](args)
        return 0
    except (
        CliError,
        CalibrationPreparationError,
        ContractError,
        MaterializationError,
        OperationError,
        StateError,
        OSError,
        ValueError,
    ) as exc:
        print(f"model_evolution: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
