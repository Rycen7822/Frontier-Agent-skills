#!/usr/bin/env python3
"""Deterministic model qualification and observed-Host projection."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from _model_evolution_campaign import validate_campaign
from _model_evolution_contract import (
    ContractError,
    HASH,
    SAFE_ID,
    SKILL_IDS,
    evaluator_evidence_status,
    evaluator_summary_axes,
    load_json,
    parse_utc,
    resolve_binding,
    validate_document,
)


GATE_IDS = (
    "apparatus",
    "identity_comparability",
    "manual_authority",
    "critical_function",
    "safety_protected",
    "routing",
    "operational_cost",
    "loop_pathology",
    "incremental_value",
    "revision",
    "statistical_support",
    "release_identity",
)
RUNTIME_AXES = (
    "task_behavior",
    "protected_safety",
    "routing",
    "operational_cost",
    "loop_pathology",
)
CRITICAL_PROBE_CAPABILITIES = {
    "force_load",
    "natural_routing",
    "action_authorization_trace",
}


def validate_qualification(value: Any) -> dict[str, Any]:
    """Validate qualification structure, gate order, and decision."""
    qualification = validate_document(value, "qualification")
    if [gate["gate_id"] for gate in qualification["gates"]] != list(GATE_IDS):
        raise ContractError("qualification gates are not in canonical order")
    limited_gates = [
        gate["gate_id"] for gate in qualification["gates"]
        if gate["status"] == "limited_native_absorption"
    ]
    if limited_gates not in ([], ["incremental_value"]):
        raise ContractError("native absorption is valid only on incremental value")
    if any(
        issue["code"] != "native-capability-absorption"
        for issue in qualification["limits"]
    ):
        raise ContractError("qualification contains a non-native limit")
    limited_skills = [
        skill_id
        for skill_id, result in qualification["skills"].items()
        if result["task_behavior"] == "limited_native_absorption"
    ]
    sqw_implicit = qualification["identity"]["skills"][
        "software-quality-workflows"
    ]["allow_implicit_invocation"]
    if limited_gates:
        if (
            limited_skills != ["software-quality-workflows"]
            or sqw_implicit is not False
            or len(qualification["limits"]) != 1
            or qualification["limits"][0]["scope"]
            != "software-quality-workflows"
        ):
            raise ContractError("native absorption requires explicit-only SQW evidence")
    elif limited_skills or qualification["limits"]:
        raise ContractError("native absorption limit is not bound to its gate")
    if (
        derive_decision(
            qualification["gates"],
            qualification["limits"],
            qualification["blockers"],
        )
        != qualification["decision"]
    ):
        raise ContractError("qualification decision differs from ordered gates")
    return qualification


def derive_decision(
    gates: list[dict[str, Any]],
    limits: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> str:
    statuses = {gate["status"] for gate in gates}
    if blockers or statuses & {"blocked", "unobserved"}:
        return "blocked"
    if limits or "limited_native_absorption" in statuses:
        return "qualified_with_limits"
    return "qualified"


def _counts_remaining(
    ceiling: dict[str, Any], reserved: dict[str, Any]
) -> dict[str, Any]:
    return {
        field: (
            None
            if ceiling[field] is None or reserved[field] is None
            else ceiling[field] - reserved[field]
        )
        for field in ceiling
    }


def _apparatus_artifact(
    campaign: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, str] | None:
    binding = campaign["apparatus_report"]
    if binding is None:
        return None
    value = load_json(
        resolve_binding(binding, repository_root, campaign_root),
        label="apparatus report",
    )
    required = {
        "schema_version",
        "campaign_id",
        "state_revision",
        "source_commit",
        "source_tree",
        "status",
        "operations",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("apparatus report shape is invalid")
    operation_fields = {
        "operation_id",
        "status",
        "duration_ms",
        "state_revision",
        "exit_code",
        "diagnostic",
    }

    def valid_operation(operation: Any) -> bool:
        return (
            isinstance(operation, dict)
            and set(operation) == operation_fields
            and isinstance(operation.get("operation_id"), str)
            and SAFE_ID.fullmatch(operation["operation_id"]) is not None
            and operation.get("status") == "pass"
            and isinstance(operation.get("duration_ms"), int)
            and not isinstance(operation["duration_ms"], bool)
            and operation["duration_ms"] >= 0
            and isinstance(operation.get("state_revision"), int)
            and not isinstance(operation["state_revision"], bool)
            and operation["state_revision"] >= 0
            and operation.get("exit_code") in {0, None}
            and (
                operation.get("diagnostic") is None
                or isinstance(operation["diagnostic"], str)
            )
        )

    if (
        value["schema_version"] != "model-evolution-apparatus-report/2"
        or value["campaign_id"] != campaign["campaign_id"]
        or value["state_revision"] > campaign["state_revision"]
        or value["source_commit"] != campaign["product"]["source_commit"]
        or value["source_tree"] != campaign["product"]["source_tree"]
        or value["status"] != "pass"
        or not value["operations"]
        or any(not valid_operation(operation) for operation in value["operations"])
    ):
        raise ContractError("apparatus report identity or operation status is invalid")
    return binding


def _evidence_result(
    binding: dict[str, Any] | None,
    *,
    kind: str,
    repository_root: Path,
    campaign_root: Path,
) -> str:
    if binding is None:
        return "unobserved"
    path = resolve_binding(binding, repository_root, campaign_root)
    return evaluator_evidence_status(path, kind=kind)


def _summary_result(
    binding: dict[str, Any] | None,
    *,
    kind: str,
    expected_gates: list[dict[str, Any]],
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, str]:
    if binding is None:
        return {axis: "unobserved" for axis in (*RUNTIME_AXES, "apparatus", "manual_authority")}
    path = resolve_binding(binding, repository_root, campaign_root)
    return evaluator_summary_axes(
        path,
        kind=kind,
        expected_gates=expected_gates,
    )


def _combined(values: list[str], *, task_axis: bool = False) -> str:
    if "blocked" in values:
        return "blocked"
    if "unobserved" in values:
        return "unobserved"
    if task_axis and "limited_native_absorption" in values:
        return "limited_native_absorption"
    return "not_applicable" if all(value == "not_applicable" for value in values) else "pass"


def _issue(
    code: str, scope: str, evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"code": code, "scope": scope, "evidence": evidence}


def assess_interaction_probes(
    campaign: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    requests = campaign["interaction_probes"]["requests"]
    if not requests:
        return "unobserved", [], []
    probe_set = load_json(
        resolve_binding(
            campaign["interaction_probes"]["probe_set"],
            repository_root,
            campaign_root,
        ),
        label="interaction probe set",
    )
    validate_document(probe_set, "interaction_probes")
    capabilities = {row["probe_id"]: row["capability"] for row in probe_set["probes"]}
    blockers: list[dict[str, Any]] = []
    for request in requests:
        capability = capabilities[request["probe_id"]]
        if (
            request["result_status"] == "pass"
            or capability not in CRITICAL_PROBE_CAPABILITIES
        ):
            continue
        blockers.append(
            _issue("critical-probe-not-pass", capability, request["artifact"])
        )
    return ("blocked" if blockers else "pass", [], blockers)


def _gate(
    gate_id: str,
    status: str,
    evidence: dict[str, Any] | None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": status,
        "evidence": evidence,
        "reason_code": reason_code,
    }


def _final_skill_identities(
    campaign: dict[str, Any], build: dict[str, Any], *, final_plugin: bool,
) -> dict[str, Any]:
    skills = (
        campaign["candidate"]["skills"]
        if final_plugin and campaign["candidate"] is not None
        else campaign["product"]["skills"]
    )
    if not isinstance(skills, dict) or set(skills) != set(SKILL_IDS):
        raise ContractError(
            "plugin build does not bind the exact four Skill identities"
        )
    versions = build.get("skill_versions")
    activation = build.get("skill_activation")
    if (
        not isinstance(versions, dict)
        or set(versions) != set(SKILL_IDS)
        or not isinstance(activation, dict)
        or set(activation) != set(SKILL_IDS)
    ):
        raise ContractError("plugin build lacks exact Skill version and activation maps")
    result = {
        skill_id: {
            "version": skills[skill_id]["version"],
            "root_hash": skills[skill_id]["root_hash"],
            "allow_implicit_invocation": activation[skill_id],
        }
        for skill_id in SKILL_IDS
    }
    if any(
        versions[skill_id] != result[skill_id]["version"]
        or not isinstance(activation[skill_id], bool)
        for skill_id in SKILL_IDS
    ):
        raise ContractError("plugin build Skill identity differs from campaign")
    return result


def _selected_plugin_build(
    campaign: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
) -> tuple[dict[str, Any], bool]:
    final_binding = campaign["skill_evidence"]["plugin_build"]
    binding = final_binding or campaign["product"]["plugin_build"]
    evidence = load_json(
        resolve_binding(binding, repository_root, campaign_root),
        label="plugin build evidence",
    )
    if not isinstance(evidence, dict):
        raise ContractError("plugin build evidence must be an object")
    expected_bundle_id = campaign["product"]["bundle_id"]
    expected_bundle_version = campaign["product"]["bundle_version"]
    if final_binding is not None and campaign["candidate"] is not None:
        try:
            parts = tuple(int(part) for part in expected_bundle_version.split("."))
        except ValueError as exc:
            raise ContractError("campaign Bundle version is invalid") from exc
        if len(parts) != 3 or not expected_bundle_id.endswith(
            f"/{expected_bundle_version}"
        ):
            raise ContractError("campaign Bundle identity cannot derive candidate minor")
        expected_bundle_version = f"{parts[0]}.{parts[1] + 1}.0"
        expected_bundle_id = (
            expected_bundle_id.rsplit("/", 1)[0] + f"/{expected_bundle_version}"
        )
    if (
        evidence.get("schema_version") != "plugin-build-evidence/4.0"
        or evidence.get("bundle_id") != expected_bundle_id
        or evidence.get("bundle_version") != expected_bundle_version
        or not isinstance(evidence.get("source_revision"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", evidence["source_revision"])
        or not isinstance(evidence.get("source_tree_hash"), str)
        or not HASH.fullmatch(evidence["source_tree_hash"])
        or not isinstance(evidence.get("plugin_tree_hash"), str)
        or not HASH.fullmatch(evidence["plugin_tree_hash"])
    ):
        raise ContractError("plugin build evidence has an invalid identity")
    expected_revision = (
        campaign["candidate"]["candidate_commit"]
        if final_binding is not None and campaign["candidate"] is not None
        else campaign["product"]["source_commit"]
    )
    if evidence["source_revision"] != expected_revision:
        raise ContractError("plugin build source revision differs from campaign")
    if (
        (final_binding is None or campaign["candidate"] is None)
        and evidence["plugin_tree_hash"] != campaign["product"]["plugin_tree"]
    ):
        raise ContractError("plugin build tree differs from frozen product")
    return evidence, final_binding is not None


def _qualification_evidence_refs(
    campaign: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project the readable receipt and raw-artifact index for the decision."""
    receipt_bindings = [
        campaign["apparatus_report"],
        campaign["interaction_probes"]["results"],
        campaign["skill_evidence"]["plugin_build"],
        *(binding
          for skill_id in SKILL_IDS
          for binding in campaign["skill_evidence"][skill_id].values()),
    ]
    raw_bindings = [
        request["artifact"]
        for request in campaign["interaction_probes"]["requests"]
    ]

    def locators(bindings: list[Any]) -> list[str]:
        return sorted(
            {
                f"{binding['root']}:{binding['path']}"
                for binding in bindings
                if isinstance(binding, dict)
            }
        )

    return [{
        "claim_id": "qualification-decision",
        "receipt_paths": locators(receipt_bindings),
        "raw_artifact_paths": locators(raw_bindings),
    }]


def project_qualification(
    campaign: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    observed_as_of: str,
    valid_until: str,
) -> dict[str, Any]:
    validate_campaign(campaign)
    if parse_utc(valid_until) <= parse_utc(observed_as_of):
        raise ContractError("qualification valid-until must be after observed-as-of")

    apparatus = _apparatus_artifact(campaign, repository_root, campaign_root)
    observed_host = campaign["profiles"]["target_observed"]
    plugin_build = campaign["skill_evidence"]["plugin_build"]
    build, final_plugin = _selected_plugin_build(
        campaign, repository_root, campaign_root,
    )
    skill_identities = _final_skill_identities(
        campaign,
        build,
        final_plugin=final_plugin,
    )
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    sentinel = validate_document(sentinel, "sentinel_index")
    skill_status: dict[str, dict[str, str]] = {}
    apparatus_axes: list[str] = []
    manual_axes: list[str] = []
    limits: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    probe_status, probe_limits, probe_blockers = assess_interaction_probes(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    limits.extend(probe_limits)
    blockers.extend(probe_blockers)
    for skill_id in SKILL_IDS:
        evidence = campaign["skill_evidence"][skill_id]
        spec = load_json(
            resolve_binding(
                sentinel["skills"][skill_id]["spec_template"],
                repository_root,
                campaign_root,
            ),
            label=f"{skill_id} sentinel spec",
        )
        if not isinstance(spec, dict) or not isinstance(spec.get("hard_gates"), list):
            raise ContractError(f"{skill_id} sentinel spec lacks hard gates")
        expected_gates = spec["hard_gates"]
        current = _summary_result(
            evidence["current_summary"],
            kind="current_summary",
            expected_gates=expected_gates,
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        holdout_axes = _summary_result(
            evidence["holdout_summary"],
            kind="holdout_summary",
            expected_gates=expected_gates,
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        transition = (
            "not_applicable"
            if campaign["profiles"]["predecessor"] is None
            else _evidence_result(
                evidence["transition_report"],
                kind="transition_report",
                repository_root=repository_root,
                campaign_root=campaign_root,
            )
        )
        revision = _evidence_result(
            evidence["revision_report"],
            kind="revision_report",
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        holdout = _combined(
            [holdout_axes[axis] for axis in RUNTIME_AXES]
        )
        merged_axes = {
            axis: _combined(
                [current[axis], holdout_axes[axis]],
                task_axis=axis == "task_behavior",
            )
            for axis in RUNTIME_AXES
        }
        if (
            merged_axes["task_behavior"] == "limited_native_absorption"
            and (
                skill_id != "software-quality-workflows"
                or skill_identities[skill_id]["allow_implicit_invocation"] is not False
            )
        ):
            merged_axes["task_behavior"] = "blocked"
        apparatus_axes.extend((current["apparatus"], holdout_axes["apparatus"]))
        manual_axes.extend((current["manual_authority"], holdout_axes["manual_authority"]))
        blocking = next(
            (
                f"{skill_id}-{name.replace('_', '-')}"
                for name, status in (
                    *merged_axes.items(),
                    ("transition", transition),
                    ("revision", revision),
                    ("holdout", holdout),
                )
                if status in {"blocked", "unobserved"}
            ),
            None,
        )
        skill_status[skill_id] = {
            **merged_axes,
            "transition": transition,
            "revision": revision,
            "holdout": holdout,
            "blocker": blocking,
        }
    if apparatus is None:
        blockers.append(_issue("apparatus-unobserved", "campaign"))
    if observed_host is None:
        blockers.append(_issue("target-host-unobserved", "host"))
    if campaign["interaction_probes"]["blocker"] is not None:
        blockers.append(_issue("interaction-probe-blocked", "host"))
    if not final_plugin:
        blockers.append(_issue("final-plugin-unobserved", "release"))
    for skill_id, result in skill_status.items():
        if result["blocker"] is not None:
            blockers.append(_issue(result["blocker"], skill_id))
    all_runtime = {
        axis: [result[axis] for result in skill_status.values()]
        for axis in RUNTIME_AXES
    }
    all_transition = [result["transition"] for result in skill_status.values()]
    all_revision = [result["revision"] for result in skill_status.values()]
    all_holdout = [result["holdout"] for result in skill_status.values()]

    def first_binding(*fields: str) -> dict[str, Any] | None:
        return next(
            (
                campaign["skill_evidence"][skill_id][field]
                for field in fields
                for skill_id in SKILL_IDS
                if campaign["skill_evidence"][skill_id][field] is not None
            ),
            None,
        )

    runtime_lanes = {
        axis: {
            "status": _combined(
                all_runtime[axis], task_axis=axis == "task_behavior",
            ),
            "evidence": first_binding("holdout_summary", "current_summary"),
        }
        for axis in RUNTIME_AXES
    }
    if runtime_lanes["task_behavior"]["status"] == "limited_native_absorption":
        limits.extend(
            _issue("native-capability-absorption", skill_id)
            for skill_id, result in skill_status.items()
            if result["task_behavior"] == "limited_native_absorption"
        )

    lanes = {
        "static_product": {
            "status": campaign["product"]["static_gate"]["status"],
            "evidence": campaign["product"]["bundle_build"],
        },
        "host_integration": {
            "status": probe_status if observed_host is not None else "unobserved",
            "evidence": observed_host,
        },
        "manual_authority": {
            "status": _combined(manual_axes),
            "evidence": first_binding("holdout_summary", "current_summary"),
        },
        **runtime_lanes,
        "longitudinal": {
            "status": _combined(all_transition + all_revision + all_holdout),
            "evidence": first_binding("revision_report", "transition_report", "holdout_summary"),
        },
    }
    apparatus_status = _combined([
        "pass" if apparatus is not None else "unobserved",
        *apparatus_axes,
    ])
    gates = [
        _gate(
            "apparatus",
            apparatus_status,
            apparatus,
            "apparatus-unobserved" if apparatus is None else None,
        ),
        _gate(
            "identity_comparability",
            probe_status if observed_host else "unobserved",
            observed_host,
            (
                "target-host-unobserved"
                if observed_host is None
                else "interaction-probe-not-pass"
                if probe_status != "pass"
                else None
            ),
        ),
        _gate(
            "manual_authority",
            lanes["manual_authority"]["status"],
            lanes["manual_authority"]["evidence"],
        ),
        _gate(
            "critical_function",
            "pass"
            if lanes["task_behavior"]["status"] == "limited_native_absorption"
            else lanes["task_behavior"]["status"],
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "safety_protected",
            lanes["protected_safety"]["status"],
            lanes["protected_safety"]["evidence"],
        ),
        _gate(
            "routing",
            lanes["routing"]["status"],
            lanes["routing"]["evidence"],
        ),
        _gate(
            "operational_cost",
            lanes["operational_cost"]["status"],
            lanes["operational_cost"]["evidence"],
        ),
        _gate(
            "loop_pathology",
            lanes["loop_pathology"]["status"],
            lanes["loop_pathology"]["evidence"],
        ),
        _gate(
            "incremental_value",
            lanes["task_behavior"]["status"],
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "revision",
            _combined(all_revision),
            first_binding("revision_report"),
        ),
        _gate(
            "statistical_support",
            _combined(all_holdout),
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "release_identity",
            "pass" if final_plugin else "unobserved",
            plugin_build,
            "final-plugin-unobserved" if not final_plugin else None,
        ),
    ]
    decision = derive_decision(gates, limits, blockers)
    host_binding = observed_host or campaign["profiles"]["target_provisional"]
    host = load_json(
        resolve_binding(host_binding, repository_root, campaign_root),
        label="target host",
    )
    execution = (
        host.get("identity", {}).get("execution", {}) if isinstance(host, dict) else {}
    )
    host_revision = (
        "/".join(
            str(item)
            for item in (
                host.get("identity", {}).get("host_version")
                if isinstance(host, dict)
                else None,
                execution.get("model_revision"),
            )
            if item
        )
        or "unobserved"
    )
    budget = campaign["budgets"]
    qualification = {
        "schema_version": "model-qualification/3",
        "qualification_id": f"qualification.r{campaign['state_revision']}",
        "campaign_id": campaign["campaign_id"],
        "terminal_state_revision": campaign["state_revision"],
        "identity": {
            "bundle_id": build["bundle_id"],
            "bundle_version": build["bundle_version"],
            "source_revision": build["source_revision"],
            "source_tree_hash": build["source_tree_hash"],
            "plugin_tree_hash": build["plugin_tree_hash"],
            "skills": skill_identities,
            "target_observed_host": observed_host,
        },
        "claim": {
            "host_model_revision": host_revision,
            "activation_modes": ["catalog", "force_loaded", "skill_disabled"],
            "skill_scope": list(SKILL_IDS),
            "task_version": sentinel["sentinel_id"],
            "sentinel_version": sentinel["sentinel_id"],
            "ceiling": "diagnostic_only"
            if decision == "blocked"
            else "bounded"
            if limits
            else "full",
        },
        "lanes": lanes,
        "skills": skill_status,
        "gates": gates,
        "budget": {
            "ceiling": budget["ceiling"],
            "reserved": budget["reserved"],
            "observed": budget["observed"],
            "remaining": _counts_remaining(budget["ceiling"], budget["reserved"]),
        },
        "decision": decision,
        "limits": limits,
        "blockers": blockers,
        "validity": {
            "observed_as_of": observed_as_of,
            "valid_until": valid_until,
            "drift_triggers": [
                "source_revision",
                "plugin_tree_hash",
                "host_identity",
                "model_revision",
                "tool_policy",
                "interaction_probe_set",
                "sentinel_index",
            ],
            "predecessor": (
                campaign["profiles"]["predecessor"]["qualification"]
                if campaign["profiles"]["predecessor"] is not None
                else None
            ),
        },
        "evidence_refs": _qualification_evidence_refs(campaign),
    }
    return validate_qualification(qualification)


def render_qualification_markdown(value: dict[str, Any]) -> str:
    validate_qualification(value)
    lines = [
        f"# Model qualification {value['qualification_id']}",
        "",
        f"Decision: `{value['decision']}`",
        f"Campaign: `{value['campaign_id']}` revision `{value['terminal_state_revision']}`",
        f"Validity: `{value['validity']['observed_as_of']}` to `{value['validity']['valid_until']}`",
        "",
        "## Ordered gates",
        "",
    ]
    lines.extend(
        f"- `{gate['gate_id']}`: `{gate['status']}`"
        + (f" ({gate['reason_code']})" if gate["reason_code"] else "")
        for gate in value["gates"]
    )
    lines.extend(["", "## Skill results", ""])
    lines.extend(
        f"- `{skill_id}`: task `{result['task_behavior']}`, safety "
        f"`{result['protected_safety']}`, cost `{result['operational_cost']}`, "
        f"holdout `{result['holdout']}`"
        for skill_id, result in value["skills"].items()
    )
    if value["limits"]:
        lines.extend(["", "## Limits", ""])
        lines.extend(
            f"- `{item['code']}` ({item['scope']})" for item in value["limits"]
        )
    if value["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(
            f"- `{item['code']}` ({item['scope']})" for item in value["blockers"]
        )
    return "\n".join([*lines, ""])


def project_observed_host(
    provisional: dict[str, Any],
    *,
    probe_set: dict[str, Any],
    results: list[dict[str, Any]],
    observed_manifest_path: Path,
) -> dict[str, Any]:
    observed = json.loads(json.dumps(provisional))
    by_probe = {row["probe_id"]: row for row in probe_set["probes"]}
    by_capability = {row["capability"]: row for row in probe_set["probes"]}
    by_result = {row["probe_id"]: row for row in results}
    if set(by_probe) != set(by_result):
        raise ContractError("probe result set differs from the frozen probe set")
    host_capabilities = {row["capability"] for row in observed["capabilities"]}
    missing = set(by_capability) - host_capabilities
    if missing:
        raise ContractError(f"target Host lacks probed capability {sorted(missing)[0]}")
    for capability in observed["capabilities"]:
        row = by_capability.get(capability["capability"])
        if row is None:
            continue
        result = by_result[row["probe_id"]]
        terminal = result["terminal"]
        capability["probe"] = {
            "status": result["status"],
            "artifact": {
                "path": terminal["path"],
                "digest": terminal["digest"],
                "encoding": "utf-8",
            },
            "locator": {
                "kind": "json_pointer",
                "artifact": terminal["path"],
                "json_pointer": "/result",
            },
            "observed": "bound interaction probe terminal",
        }
    command = observed["command"]["argv"]
    if "--host-manifest" not in command:
        raise ContractError("target Host command does not bind its manifest path")
    command[command.index("--host-manifest") + 1] = str(observed_manifest_path)
    return observed
