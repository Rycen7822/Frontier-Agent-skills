#!/usr/bin/env python3
"""Run one bounded Frontier model-evolution campaign."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Callable

if __name__ == "__main__":
    sys.dont_write_bytecode = True

from _model_evolution_contract import (
    CRITICAL_PROBE_CAPABILITIES,
    ContractError,
    SKILL_IDS,
    _is_child_environment_isolation_correction,
    _is_multiturn_timeout_correction,
    _is_single_principal_exec_correction,
    _is_source_workspace_isolation_correction,
    _is_systemd_environment_correction,
    assess_interaction_probes,
    build_initial_campaign,
    canonical_bytes,
    content_hash,
    evaluator_evidence_status,
    load_json,
    make_binding,
    prepare_predecessor,
    prepare_supersedes,
    project_qualification,
    qualification_request_ceilings,
    render_qualification_markdown,
    resolve_binding,
    validate_all_bindings,
    validate_document,
    verify_self_hash,
    with_self_hash,
)
from _model_evolution_calibration import (
    CalibrationPreparationError,
    close_calibration_failure,
    prepare_calibrations,
)
from _model_evolution_calibration_receipt import close_calibration_rejection
from _model_evolution_materialization import (
    MaterializationError,
    prepare_candidate_plan,
    prepare_current_plan,
    validate_candidate_plan,
    validate_current_plan,
)
from _model_evolution_holdout import prepare_holdout_plan, validate_holdout_plan
from _model_evolution_ops import (
    OperationError,
    bundle_skill_at_revision,
    candidate_source,
    git_blob_matches,
    git_identity,
    preflight_operations,
    render_runner_command,
    require_tracked_binding,
    run_interaction_probes,
    runner_status,
    systemd_probe_argv,
    validate_plugin_staging,
    validate_target_host_staging,
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
    return CampaignStore(
        campaign_root,
        repository_root,
        repository_blob_matches=lambda revision, path, expected_hash: git_blob_matches(
            repository_root, revision, path, expected_hash
        ),
    )


def _repository_fallback(
    repository_root: Path, revision: str
) -> Callable[[str, str], bool]:
    return lambda path, expected_hash: git_blob_matches(
        repository_root, revision, path, expected_hash
    )


def _binding_for_path(
    path: Path,
    *,
    repository_root: Path,
    campaign_root: Path,
    tracked_repository: bool = True,
) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if resolved.is_relative_to(repository_root):
        if tracked_repository:
            require_tracked_binding(repository_root, resolved)
        root = "repository"
    elif resolved.is_relative_to(campaign_root):
        root = "campaign"
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
            or grader.get("prompt_hash")
            != selected[0].get("prompt", {}).get("sha256")
            or grader.get("schema_hash")
            != selected[0].get("output_schema", {}).get("sha256")
            or grader.get("model") != execution.get("model")
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
        plan = _load_bound_document(
            registered["plan"],
            repository_root=repository_root,
            campaign_root=campaign_root,
            label=f"{role} registered plan",
        )
        if value.get("plan_hash") != plan.get("plan_hash"):
            raise CliError(f"{role} differs from its registered plan")
        if value.get("host_manifest_hash") != registered["host_hash"]:
            raise CliError(f"{role} differs from its registered Host")
        return
    required_fields = {
        "transition_report": ("current_summary",),
        "revision_report": ("current_summary", "candidate_summary"),
    }
    if role not in required_fields:
        return
    observed_hashes = {
        row.get("summary_hash")
        for row in value.get("inputs", [])
        if isinstance(row, dict)
    }
    expected_hashes = set()
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
        expected_hashes.add(summary["summary_hash"])
    if not expected_hashes <= observed_hashes:
        raise CliError(f"{role} inputs differ from the selected summaries")


def _cumulative_request_ceilings(
    request_ceilings: dict[str, int],
    supersedes: dict[str, Any] | None,
    *,
    reuse_calibration_reservation: bool = True,
) -> dict[str, int]:
    expected = {
        field: request_ceilings[field]
        for field in ("provider_requests", "execute", "model_grade")
    }
    if supersedes is None:
        return expected
    imported_reserved = supersedes["imported_reserved"]
    imported_observed = supersedes["imported_observed"]
    reusable_calibration = (
        request_ceilings["calibration"]
        if reuse_calibration_reservation
        else 0
    )
    for field in expected:
        future = request_ceilings[field]
        if field in {"provider_requests", "model_grade"}:
            future -= reusable_calibration
        expected[field] = max(
            imported_reserved[field], imported_observed[field],
        ) + future
    return expected


def _init(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign_root.mkdir(parents=True, exist_ok=True)
    identity = git_identity(repository_root)
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
        "static_report": repository_root / "evaluation/static-contract-diagnostic.json",
        "plugin_build": args.plugin_build_evidence.resolve(strict=True),
        "target_host": args.target_host.resolve(strict=True),
        "probe_set": args.probe_set.resolve(strict=True),
        "sentinel": args.sentinel_index.resolve(strict=True),
    }
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
    static_report = load_json(fixed["static_report"], label="static report")
    plugin_build = validate_plugin_staging(
        repository_root=repository_root,
        plugin_root=plugin_root,
        evidence_path=fixed["plugin_build"],
        expected_commit=identity["commit"],
        expected_bundle_id=static_report["bundle_id"],
        expected_bundle_version=bundle_manifest["bundle_version"],
        expected_skill_versions={
            skill_id: bundle_build["skills"][skill_id]["version"]
            for skill_id in SKILL_IDS
        },
    )
    validate_target_host_staging(
        fixed["target_host"],
        plugin_root,
        repository_root=repository_root,
        expected_commit=identity["commit"],
        expected_tree=identity["tree"],
    )
    probe_set = load_json(fixed["probe_set"], label="interaction probe set")
    sentinel = load_json(fixed["sentinel"], label="sentinel index")
    request_ceilings = qualification_request_ceilings(
        sentinel,
        repository_root=repository_root,
        campaign_root=campaign_root,
        probe_count=len(probe_set["probes"]),
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
            current_bundle_id=load_json(fixed["static_report"], label="static report")[
                "bundle_id"
            ],
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
    supersedes = None
    reuse_calibration_reservation = True
    if (
        args.supersession_failure_receipt is not None
        or args.supersession_calibration_rejection_receipt is not None
    ) and args.supersedes is None:
        raise CliError("supersession receipt requires --supersedes")
    if args.supersedes is not None:
        supersedes = prepare_supersedes(
            campaign_binding=_binding_for_path(
                args.supersedes,
                repository_root=repository_root,
                campaign_root=campaign_root,
                tracked_repository=False,
            ),
            target_host_binding=bindings["target_host"],
            failure_receipt_binding=(
                _binding_for_path(
                    args.supersession_failure_receipt,
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                    tracked_repository=False,
                )
                if args.supersession_failure_receipt is not None
                else None
            ),
            calibration_rejection_receipt_binding=(
                _binding_for_path(
                    args.supersession_calibration_rejection_receipt,
                    repository_root=repository_root,
                    campaign_root=campaign_root,
                    tracked_repository=False,
                )
                if args.supersession_calibration_rejection_receipt is not None
                else None
            ),
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        superseded_campaign = load_json(
            args.supersedes.resolve(strict=True),
            label="superseded campaign",
        )
        reuse_calibration_reservation = not (
            _is_multiturn_timeout_correction(superseded_campaign)
            or _is_child_environment_isolation_correction(superseded_campaign)
            or _is_single_principal_exec_correction(superseded_campaign)
            or _is_source_workspace_isolation_correction(superseded_campaign)
            or _is_systemd_environment_correction(superseded_campaign)
        )
    expected_request_ceilings = _cumulative_request_ceilings(
        request_ceilings,
        supersedes,
        reuse_calibration_reservation=reuse_calibration_reservation,
    )
    for field, expected in expected_request_ceilings.items():
        if ceilings[field] != expected:
            raise CliError(
                f"{field} ceiling must equal the cumulative worst-case budget {expected}"
            )
    campaign = build_initial_campaign(
        campaign_id=args.campaign_id,
        git_identity=identity,
        bundle_manifest=bundle_manifest,
        bundle_manifest_binding=bindings["bundle_manifest"],
        bundle_build=bundle_build,
        bundle_build_binding=bindings["bundle_build"],
        plugin_build_binding=bindings["plugin_build"],
        plugin_root=plugin_root.relative_to(campaign_root).as_posix(),
        plugin_tree_hash=plugin_build["plugin_tree_hash"],
        calibration_requests=request_ceilings["calibration"],
        static_report=static_report,
        static_report_binding=bindings["static_report"],
        target_host_binding=bindings["target_host"],
        probe_set_binding=bindings["probe_set"],
        sentinel_binding=bindings["sentinel"],
        ceilings=ceilings,
        repository_root=repository_root,
        campaign_root=campaign_root,
        predecessor=predecessor,
        supersedes=supersedes,
    )
    if ceilings["provider_requests"] < len(probe_set["probes"]):
        raise CliError(
            "provider request ceiling cannot reserve the interaction probe set"
        )
    calibration_delta = max(
        0,
        request_ceilings["calibration"]
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
        campaign = with_self_hash(campaign, "campaign_hash")
        validate_document(campaign, "campaign")
    store = _campaign_store(repository_root, campaign_root)
    bootstrap_paths = {
        path for path in fixed.values() if path.is_relative_to(campaign_root)
    }
    bootstrap_paths.update(path for path in plugin_root.rglob("*") if path.is_file())
    store.create(
        campaign,
        bootstrap_paths=tuple(sorted(bootstrap_paths)),
    )
    _emit(
        {
            "campaign_id": campaign["campaign_id"],
            "phase": campaign["phase"],
            "state_revision": campaign["state_revision"],
            "campaign_hash": campaign["campaign_hash"],
        }
    )


def _preflight(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("preflight expected revision is stale")
    report = preflight_operations(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
        check_systemd=not args.systemd_argv_only,
    )
    if args.systemd_argv_only:
        argv = systemd_probe_argv(
            f"frontier-{campaign['campaign_id']}-preflight",
            campaign_root / "systemd-preflight.closed",
        )
        report["operations"].append(
            {
                "operation_id": "systemd-user-argv",
                "input_hash": content_hash(canonical_bytes(campaign["campaign_id"])),
                "command_hash": content_hash(canonical_bytes(argv)),
                "status": "pass",
                "duration_ms": 0,
            }
        )
        report = with_self_hash(report, "apparatus_report_hash")
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
            "apparatus_report_hash": report["apparatus_report_hash"],
        }
    )


def _probe(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("probe expected revision is stale")
    approval = _binding_for_path(
        args.budget_approval,
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
        "campaign_hash": campaign["campaign_hash"],
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


def _register_plan(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    store = _campaign_store(repository_root, campaign_root)
    campaign = store.read()
    if campaign["state_revision"] != args.expected_revision:
        raise CliError("register-plan expected revision is stale")
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
    verify_self_hash(plan, "plan_hash")
    validator = {
        "target_current": validate_current_plan,
        "target_candidate": validate_candidate_plan,
        "target_holdout": validate_holdout_plan,
    }[args.role]
    host = validator(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=args.skill_id,
        plan_path=plan_path,
    )
    if plan.get("host_manifest_hash") != host.get("manifest_hash"):
        raise CliError("execution plan Host differs from its exact Host evidence")
    if args.skill_id not in plan.get("package_hashes", {}):
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
    if plan["package_hashes"][args.skill_id] != expected_package_hash:
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
    plan_record = {
        "role": args.role,
        "skill_id": args.skill_id,
        "plan": plan_binding,
        "host_hash": host["manifest_hash"],
        "execute_ceiling": status["execute_case_request_ceiling"],
        "model_grade_ceiling": status["model_grade_request_ceiling"],
        "runner_status_hash": content_hash(canonical_bytes(status)),
    }
    updated = store.mutate(
        args.expected_revision,
        lambda state: register_plan(state, plan_record),
    )
    command = render_runner_command(
        plan_path,
        index_path,
        attempt_budget=status["worst_case_remaining_attempts"],
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
        "plan_hash": result["plan_hash"],
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
        "plan_hash": result["plan_hash"],
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
        "plan_hash": result["plan_hash"],
        "plan": str(result["plan"]),
        "execute_ceiling": result["execute_ceiling"],
        "provider_requests": 0,
    })


def _verify_plan(args: argparse.Namespace) -> None:
    repository_root, campaign_root = _roots(args)
    campaign = _campaign_store(repository_root, campaign_root).read()
    validator = {
        "target_current": validate_current_plan,
        "target_candidate": validate_candidate_plan,
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
        "host_manifest_hash": host["manifest_hash"],
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
    )
    _emit({
        "failure_receipt": binding,
        "artifact_sha256": binding["sha256"],
        "document_self_hash": receipt["failure_receipt_hash"],
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
    )
    _emit({
        "calibration_rejection_receipt": binding,
        "artifact_sha256": binding["sha256"],
        "document_self_hash": receipt["calibration_rejection_receipt_hash"],
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
        evidence_status = evaluator_evidence_status(path, kind=args.role)
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
        if git_identity(repository_root)["commit"] != expected_commit:
            raise CliError("plugin build is not from the selected signed clean commit")
        expected_skills = (
            campaign["candidate"]["skills"]
            if campaign["candidate"] is not None
            else campaign["product"]["skills"]
        )
        expected_bundle = load_json(
            repository_root / "bundle-manifest.json",
            label="selected Bundle manifest",
        )
        plugin_root = args.plugin_root.resolve(strict=True)
        if (
            args.plugin_root.is_symlink()
            or not plugin_root.is_dir()
            or not plugin_root.is_relative_to(campaign_root)
        ):
            raise CliError("selected plugin staging must be campaign-local")
        validate_plugin_staging(
            repository_root=repository_root,
            plugin_root=plugin_root,
            evidence_path=path,
            expected_commit=expected_commit,
            expected_bundle_id=campaign["product"]["bundle_id"],
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
        observed = {
            "provider_requests": None
            if current["provider_requests"] is None
            else current["provider_requests"] + calibration,
            "model_grade": (current["model_grade"] or 0) + calibration,
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
    probe_blocker = campaign["interaction_probes"]["blocker"]
    if probe_blocker is not None:
        blockers.append({"code": "interaction-probe", "message": probe_blocker})
    elif any(
        request["status"] == "reserved"
        for request in campaign["interaction_probes"]["requests"]
    ):
        blockers.append(
            {
                "code": "probe-reservation",
                "message": "partial probe reservation requires manual diagnosis",
            }
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
    expected_commit = (
        campaign["candidate"]["candidate_commit"]
        if campaign["candidate"] is not None
        else campaign["product"]["source_commit"]
    )
    try:
        identity = git_identity(repository_root)
        if identity["commit"] != expected_commit:
            blockers.append(
                {
                    "code": "source-drift",
                    "message": "checked-out signed commit differs from campaign source",
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
            if (
                content_hash(canonical_bytes(status))
                == plan_record["runner_status_hash"]
            ):
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
                commands.append(
                    render_runner_command(
                        plan_path,
                        index,
                        attempt_budget=status["worst_case_remaining_attempts"],
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
    )
    if qualification_complete and not blockers:
        projection["next_event"] = "qualification_complete"
        projection["runner_commands"] = []
    if args.json:
        _emit(projection)
    else:
        print(
            f"{projection['campaign_id']} revision={projection['state_revision']} "
            f"phase={projection['phase']} active={projection['active_attempts']} "
            f"recoverable={projection['recoverable_attempts']}"
        )
        print(f"next={projection['next_event'] or 'blocked'}")
        for blocker in blockers:
            print(f"blocker {blocker['code']}: {blocker['message']}")
        for command in projection["runner_commands"]:
            print(command)


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
            repository_fallback=_repository_fallback(
                repository_root, state["product"]["source_commit"]
            ),
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
    validate_document(qualification, "qualification")
    fallback = _repository_fallback(
        repository_root, campaign["product"]["source_commit"]
    )
    validate_all_bindings(
        qualification,
        repository_root,
        campaign_root,
        fallback,
    )
    if qualification["campaign_hash"] != campaign["campaign_hash"]:
        raise CliError("qualification campaign hash differs from current state")
    projected = project_qualification(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
        observed_as_of=qualification["validity"]["observed_as_of"],
        valid_until=qualification["validity"]["valid_until"],
        repository_fallback=fallback,
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
    init.add_argument("--plugin-root", type=Path, required=True)
    init.add_argument("--plugin-build-evidence", type=Path, required=True)
    init.add_argument("--target-host", type=Path, required=True)
    init.add_argument("--probe-set", type=Path, required=True)
    init.add_argument("--sentinel-index", type=Path, required=True)
    init.add_argument("--predecessor-cycle", type=Path)
    init.add_argument("--predecessor-host", type=Path)
    init.add_argument("--predecessor-comparison", type=Path)
    init.add_argument("--predecessor-qualification", type=Path)
    init.add_argument("--supersedes", type=Path)
    init.add_argument("--supersession-failure-receipt", type=Path)
    init.add_argument("--supersession-calibration-rejection-receipt", type=Path)
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
        "--systemd-argv-only",
        action="store_true",
        help="CI-only: validate the transient service argv without starting it",
    )

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

    holdout = commands.add_parser("prepare-holdout")
    holdout.add_argument("--expected-revision", type=int, required=True)
    holdout.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    holdout.add_argument("--plugin-root", type=Path, required=True)
    holdout.add_argument("--holdout-root", type=Path, required=True)

    verify_plan = commands.add_parser("verify-plan")
    verify_plan.add_argument(
        "--role",
        choices=("target_current", "target_candidate", "target_holdout"),
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
        choices=("target_current", "target_candidate", "target_holdout"),
        required=True,
    )
    register.add_argument("--skill-id", choices=SKILL_IDS, required=True)
    register.add_argument("--plan", type=Path, required=True)

    record = commands.add_parser("record")
    record.add_argument("--expected-revision", type=int, required=True)
    record.add_argument("--role", choices=RECORD_ROLES, required=True)
    record.add_argument("--skill-id", choices=SKILL_IDS)
    record.add_argument("--artifact", type=Path)
    record.add_argument("--plugin-root", type=Path)
    record.add_argument("--base-commit")
    record.add_argument("--candidate-commit")
    record.add_argument("--owner-surface", choices=SKILL_IDS)
    record.add_argument("--root-cause-id", action="append", default=[])
    record.add_argument("--semantic-change", action="append", default=[])

    status = commands.add_parser("status")
    status.add_argument("--json", action="store_true")

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
            "probe": _probe,
            "prepare-calibration": _prepare_calibration,
            "prepare-current": _prepare_current,
            "prepare-candidate": _prepare_candidate,
            "prepare-holdout": _prepare_holdout,
            "verify-plan": _verify_plan,
            "close-calibration-failure": _close_calibration_failure,
            "close-calibration-rejection": _close_calibration_rejection,
            "register-plan": _register_plan,
            "record": _record,
            "status": _status,
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
