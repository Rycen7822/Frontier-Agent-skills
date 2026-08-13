#!/usr/bin/env python3
"""Fresh model-evolution campaign construction and predecessor binding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _model_evolution_contract import (
    BUDGET_FIELDS,
    ContractError,
    REPOSITORY_ROOT,
    SAFE_ID,
    SKILL_IDS,
    _validate_external_schema,
    evaluator_evidence_status,
    load_json,
    resolve_binding,
    strict_json_bytes,
    validate_document,
)


CAMPAIGN_SCHEMA_VERSION = "model-evolution-campaign/3"
def validate_campaign(value: Any) -> dict[str, Any]:
    """Validate the current fresh-only campaign contract."""
    campaign = validate_document(value, "campaign")
    has_apparatus = campaign["apparatus_report"] is not None
    if (campaign["phase"] == "declared" and has_apparatus) or (
        campaign["phase"] != "declared" and not has_apparatus
    ):
        raise ContractError("campaign phase and apparatus report differ")
    observed_host = campaign["profiles"]["target_observed"]
    requests = campaign["interaction_probes"]["requests"]
    results = campaign["interaction_probes"]["results"]
    if observed_host is not None and (
        not requests
        or results is None
        or any(request["status"] != "closed" for request in requests)
    ):
        raise ContractError("observed Host lacks a closed probe result set")
    if (
        campaign["phase"] not in {"declared", "apparatus_ready"}
        and observed_host is None
    ):
        raise ContractError("campaign phase requires an observed Host")
    return campaign


def qualification_request_ceilings(
    sentinel: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    probe_count: int,
) -> dict[str, int]:
    """Compute the exact request ceilings for one fresh campaign."""
    public_cases: dict[str, int] = {}
    calibration_requests = 0
    holdout_cases = 0
    repeat_counts: set[int] = set()
    expected_retry_policy = {
        "max_attempts": 2,
        "retryable_apparatus_classes": ["official_transient"],
        "backoff_seconds": 0,
    }
    for skill_id in SKILL_IDS:
        record = sentinel["skills"][skill_id]
        spec = load_json(
            resolve_binding(
                record["spec_template"], repository_root, campaign_root
            ),
            label=f"{skill_id} sentinel spec",
        )
        repeats = spec.get("suite", {}).get("repeats")
        if isinstance(repeats, bool) or not isinstance(repeats, int):
            raise ContractError(f"{skill_id} sentinel repeats are invalid")
        repeat_counts.add(repeats)
        if spec.get("execution", {}).get("retry_policy") != expected_retry_policy:
            raise ContractError(f"{skill_id} sentinel retry policy differs")
        scenarios = resolve_binding(
            record["public_scenarios"], repository_root, campaign_root
        ).read_bytes().splitlines()
        calibration = resolve_binding(
            record["calibration_gold"], repository_root, campaign_root
        ).read_bytes().splitlines()
        if not scenarios or not calibration:
            raise ContractError(f"{skill_id} sentinel request corpus is empty")
        for index, row in enumerate((*scenarios, *calibration), start=1):
            strict_json_bytes(row, label=f"{skill_id} request row {index}")
        if len(calibration) != record["calibration_request_ceiling"]:
            raise ContractError(
                f"{skill_id} calibration request ceiling differs from gold"
            )
        public_cases[skill_id] = len(scenarios)
        calibration_requests += len(calibration)
        holdout_cases += record["holdout_case_ceiling"]

    if repeat_counts != {3}:
        raise ContractError("fresh campaign requires exactly three repeats per Skill")
    repeats = next(iter(repeat_counts))

    current_execute = sum(public_cases.values()) * 2
    candidate_cases = max(
        public_cases[owner]
        + sum(
            len(sentinel["skills"][skill_id]["protected_case_ids"]) + 1
            for skill_id in SKILL_IDS
            if skill_id != owner
        )
        for owner in SKILL_IDS
    )
    revision_execute = max(current_execute, candidate_cases * 2)
    execute = (
        (current_execute + revision_execute + holdout_cases * 2)
        * repeats
        * expected_retry_policy["max_attempts"]
    )
    model_grade = calibration_requests + execute
    return {
        "provider_requests": probe_count + execute + model_grade,
        "execute": execute,
        "model_grade": model_grade,
        "calibration": calibration_requests,
    }


def build_initial_campaign(
    *,
    campaign_id: str,
    git_identity: dict[str, str],
    bundle_manifest: dict[str, Any],
    bundle_manifest_binding: dict[str, Any],
    bundle_build: dict[str, Any],
    bundle_build_binding: dict[str, Any],
    plugin_build_binding: dict[str, Any],
    plugin_root: str,
    plugin_tree_hash: str,
    calibration_requests: int,
    static_report: dict[str, Any],
    target_host_binding: dict[str, Any],
    probe_set_binding: dict[str, Any],
    sentinel_binding: dict[str, Any],
    ceilings: dict[str, int | None],
    repository_root: Path,
    campaign_root: Path,
    predecessor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build revision zero without importing any earlier campaign state."""
    if not SAFE_ID.fullmatch(campaign_id):
        raise ContractError("campaign ID is unsafe")
    if set(bundle_build.get("skills", {})) != set(SKILL_IDS):
        raise ContractError("Bundle build does not contain the exact four Skills")
    manifest_skills = {
        item["id"]: item
        for item in bundle_manifest.get("skills", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if set(manifest_skills) != set(SKILL_IDS):
        raise ContractError(
            "Bundle source manifest does not contain the exact four Skills"
        )
    if (
        static_report.get("bundle_id")
        != f"frontier-engineering/{bundle_manifest.get('bundle_version')}"
    ):
        raise ContractError("Bundle and static report identities differ")
    probe_set = load_json(
        resolve_binding(probe_set_binding, repository_root, campaign_root),
        label="interaction probe set",
    )
    sentinel = load_json(
        resolve_binding(sentinel_binding, repository_root, campaign_root),
        label="sentinel index",
    )
    host = load_json(
        resolve_binding(target_host_binding, repository_root, campaign_root),
        label="target provisional Host",
    )
    validate_document(probe_set, "interaction_probes")
    validate_document(sentinel, "sentinel_index")
    _validate_external_schema(
        host,
        REPOSITORY_ROOT / "skill-evaluator/schemas/host-manifest-v2.schema.json",
        "target provisional Host",
    )
    if set(ceilings) != set(BUDGET_FIELDS):
        raise ContractError("campaign budget ceilings are incomplete")

    skills = {
        skill_id: {
            "version": bundle_build["skills"][skill_id]["version"],
            "root_hash": bundle_build["skills"][skill_id]["root_hash"],
            "allow_implicit_invocation": bundle_build["skills"][skill_id][
                "allow_implicit_invocation"
            ],
        }
        for skill_id in SKILL_IDS
    }
    for skill_id in SKILL_IDS:
        if skills[skill_id]["version"] != manifest_skills[skill_id]["version"]:
            raise ContractError(f"Bundle Skill version differs for {skill_id}")

    counts = {field: 0 for field in ceilings}
    observed: dict[str, int | None] = dict(counts)
    observed["artifact_bytes"] = None
    evidence_item = {
        "grader_calibration": None,
        "current_summary": None,
        "transition_report": None,
        "candidate_summary": None,
        "revision_report": None,
        "holdout_summary": None,
    }
    state = {
        "schema_version": CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "state_revision": 0,
        "phase": "declared",
        "apparatus_report": None,
        "product": {
            "bundle_id": static_report["bundle_id"],
            "bundle_version": bundle_manifest["bundle_version"],
            "source_commit": git_identity["commit"],
            "source_tree": git_identity["tree"],
            "dirty": False,
            "plugin_tree": plugin_tree_hash,
            "plugin_build": plugin_build_binding,
            "plugin_root": plugin_root,
            "calibration_requests": calibration_requests,
            "bundle_manifest": bundle_manifest_binding,
            "bundle_build": bundle_build_binding,
            "static_gate": {
                "schema_version": static_report["schema_version"],
                "status": "pass",
            },
            "skills": skills,
        },
        "profiles": {
            "predecessor": predecessor,
            "target_provisional": target_host_binding,
            "target_observed": None,
        },
        "interaction_probes": {
            "probe_set": probe_set_binding,
            "results": None,
            "requests": [],
            "blocker": None,
        },
        "sentinel_index": sentinel_binding,
        "budgets": {
            "ceiling": ceilings,
            "reserved": counts,
            "observed": observed,
            "candidate_count": 0,
        },
        "plans": [],
        "skill_evidence": {
            **{skill_id: dict(evidence_item) for skill_id in SKILL_IDS},
            "plugin_build": None,
        },
        "candidate": None,
    }
    return validate_campaign(state)


def prepare_predecessor(
    *,
    cycle_binding: dict[str, Any],
    host_binding: dict[str, Any],
    comparison_binding: dict[str, Any],
    qualification_binding: dict[str, Any] | None,
    current_bundle_id: str,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, Any]:
    """Bind one closed campaign only as exact-product comparison context."""
    cycle = load_json(
        resolve_binding(cycle_binding, repository_root, campaign_root),
        label="predecessor campaign",
    )
    validate_campaign(cycle)
    if cycle["phase"] != "holdout_ready":
        raise ContractError("predecessor campaign is not closed at holdout_ready")
    if cycle["product"]["bundle_id"] != current_bundle_id:
        raise ContractError("predecessor product differs from current Bundle")
    observed_host = cycle["profiles"]["target_observed"]
    if observed_host is None or observed_host != host_binding:
        raise ContractError("predecessor Host differs from its closed campaign")

    host = load_json(
        resolve_binding(host_binding, repository_root, campaign_root),
        label="predecessor Host",
    )
    _validate_external_schema(
        host,
        REPOSITORY_ROOT / "skill-evaluator/schemas/host-manifest-v2.schema.json",
        "predecessor Host",
    )
    comparison_path = resolve_binding(
        comparison_binding, repository_root, campaign_root
    )
    if evaluator_evidence_status(comparison_path, kind="transition_report") == "blocked":
        raise ContractError("predecessor comparison is not closed evidence")
    product_hash = cycle["product"]["plugin_tree"]
    if qualification_binding is not None:
        from _model_evolution_qualification import validate_qualification

        qualification = load_json(
            resolve_binding(qualification_binding, repository_root, campaign_root),
            label="predecessor qualification",
        )
        validate_qualification(qualification)
        if (
            qualification["campaign_id"] != cycle["campaign_id"]
            or qualification["terminal_state_revision"] != cycle["state_revision"]
        ):
            raise ContractError("predecessor qualification differs from its campaign")
        if qualification["decision"] == "blocked":
            raise ContractError("blocked qualification cannot be a predecessor")
        product_hash = qualification["identity"]["plugin_tree"]
    return {
        "cycle": cycle_binding,
        "host": host_binding,
        "plugin_tree_digest": product_hash,
        "qualification": qualification_binding,
    }
