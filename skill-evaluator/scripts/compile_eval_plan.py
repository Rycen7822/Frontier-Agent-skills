#!/usr/bin/env python3
"""Compile validated Skill Evaluator v7 inputs into execution plan v3."""

from __future__ import annotations

import argparse
import copy
from hashlib import sha256
import platform
from pathlib import Path
import sys
from typing import Any, Callable

import model_grade_transport as model_transport
from evidence_io import (
    atomic_write_bytes,
    canonical_json_bytes,
    load_json,
    load_jsonl_objects,
    normalize_relative_path,
)
from validate_eval_suite import (
    EPOCH7_MODULE_CAPABILITIES,
    derive_entry_disposition,
    load_epoch7_schema_registry,
    required_epoch7_modules,
    validate_epoch7_contract_semantics,
    validate_epoch7_schema,
)


COMPILER_ALGORITHM = "skill-evaluator-plan"
COMPILER_VERSION = 2
ORDERING_ALGORITHM = "sha256-block-sort-treatment-rotation"
ORDERING_VERSION = 1
BLINDED_MODEL_PROJECTION = [
    "case_id",
    "repeat",
    "requirements",
    "captured_output",
    "artifacts",
    "observations",
]
RUNTIME_AUTHORITY_FIELDS = {
    "install",
    "publish",
    "deploy",
    "external_writes",
}


class ContractFailure(ValueError):
    """A valid CLI request whose evaluation contract cannot be compiled."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InternalInvariantError(RuntimeError):
    """An implementation or output invariant failure."""


def _sorted_values(values: list[Any]) -> list[Any]:
    return sorted(values, key=canonical_json_bytes)


def _structured_id(kind: str, *parts: object) -> str:
    identifier = ".".join((kind, *(str(part) for part in parts)))
    if len(identifier) > 128:
        raise ContractFailure(
            "compiler.semantic_id_length",
            f"structured {kind} identifier exceeds 128 characters",
        )
    return identifier


def _normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(spec)
    subject = normalized["subject"]
    for field in ("mechanisms", "claimed_hosts"):
        subject[field] = _sorted_values(subject[field])
    normalized["applicability"] = sorted(
        normalized["applicability"], key=lambda item: item["module"],
    )
    for treatment in normalized["treatments"]:
        for field in (
            "intervention_axes",
            "expected_capabilities",
            "scenario_ids",
            "scenario_tags",
            "exclusions",
        ):
            treatment[field] = _sorted_values(treatment[field])
    normalized["treatments"] = sorted(
        normalized["treatments"], key=lambda item: item["treatment_id"],
    )
    normalized["host"]["required_capabilities"] = _sorted_values(
        normalized["host"]["required_capabilities"],
    )
    normalized["authority"]["runner_capabilities"] = _sorted_values(
        normalized["authority"]["runner_capabilities"],
    )
    return normalized


def _normalize_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(scenario)
    for field in ("tags", "applicable_treatment_profiles"):
        normalized[field] = _sorted_values(normalized[field])
    return normalized


def _normalize_host(host: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(host)
    normalized["capabilities"] = sorted(
        normalized["capabilities"], key=lambda item: item["capability"],
    )
    normalized["command"]["env_allowlist"] = _sorted_values(
        normalized["command"]["env_allowlist"],
    )
    normalized["reset"]["scopes"] = _sorted_values(
        normalized["reset"]["scopes"],
    )
    for field in ("available", "missing"):
        normalized["capture"][field] = _sorted_values(
            normalized["capture"][field],
        )
    return normalized


def _first_diagnostic(
    diagnostics: list[dict[str, str]],
) -> tuple[str, str]:
    diagnostic = diagnostics[0]
    return (
        diagnostic["code"],
        f"{diagnostic['path']}: {diagnostic['message']}",
    )


def _load_ready_contract(
    spec_path: Path,
    scenarios_path: Path,
    host_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    spec = load_json(spec_path)
    scenarios = [
        row for _, row in load_jsonl_objects(scenarios_path)
    ]
    host = load_json(host_path)
    registry = load_epoch7_schema_registry()
    diagnostics = validate_epoch7_schema(
        spec, "eval-spec-v7.schema.json", registry,
    )
    for index, scenario in enumerate(scenarios):
        for diagnostic in validate_epoch7_schema(
            scenario, "scenario-v1.schema.json", registry,
        ):
            diagnostics.append({
                **diagnostic,
                "path": f"/scenarios/{index}{diagnostic['path']}",
            })
    for diagnostic in validate_epoch7_schema(
        host, "host-manifest-v2.schema.json", registry,
    ):
        diagnostics.append({
            **diagnostic,
            "path": f"/host{diagnostic['path']}",
        })
    if diagnostics:
        raise ContractFailure(*_first_diagnostic(diagnostics))
    if spec["level"] == "L0" or spec["execution"]["ready"] is not True:
        raise ContractFailure(
            "compiler.not_ready",
            "compiler requires an execution-ready L1+ contract",
        )
    semantic_errors, warnings = validate_epoch7_contract_semantics(
        spec,
        scenarios,
        host,
        spec_path=spec_path,
        scenarios_path=scenarios_path,
        host_path=host_path,
        registry=registry,
    )
    if semantic_errors:
        raise ContractFailure(*_first_diagnostic(semantic_errors))
    if warnings:
        raise ContractFailure(*_first_diagnostic(warnings))
    return spec, scenarios, host, registry


def _compiler_identity(
    source_revision: str,
    runtime_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    if runtime_override is None:
        executable = Path(sys.executable).resolve()
        runtime = {
            "python_executable": str(executable),
            "python_version": platform.python_version(),
        }
    else:
        runtime = {
            field: runtime_override[field]
            for field in ("python_executable", "python_version")
        }
    return {
        "algorithm": COMPILER_ALGORITHM,
        "version": COMPILER_VERSION,
        "source_revision": source_revision,
        **runtime,
    }


def _execution_profile(
    spec: dict[str, Any],
    host: dict[str, Any],
) -> dict[str, Any]:
    package = spec["subject"]["package"]
    host_identity = host["identity"]
    host_execution = host["identity"]["execution"]
    return {
        "source_revision": package["source_revision"],
        "host_id": host_identity["host_id"],
        "host_version": host_identity["host_version"],
        "provider": host_execution["provider"],
        "model": host_execution["model"],
        "model_revision": host_execution["model_revision"],
        "harness": host_execution["harness"],
        "harness_version": host_execution["harness_version"],
        "platform": copy.deepcopy(host_identity["platform"]),
        "command_id": host["command"]["command_id"],
        "catalog_ids": [
            entry["id"] for entry in host["catalog"]["entries"]
        ],
        "prompt_id": host_execution["prompt_id"],
        "tool_schema_id": host_execution["tool_schema_id"],
        "policy_id": host_execution["policy_id"],
        "tokenizer_id": host_execution["tokenizer_id"],
        "pricing_id": host_execution["pricing_id"],
        "utc_clock_id": host_execution["utc_clock_id"],
        "monotonic_clock_id": host_execution["monotonic_clock_id"],
        "as_of": spec["execution"]["as_of"],
    }


def _catalog_for_scenario(
    host: dict[str, Any],
    scenario: dict[str, Any],
) -> list[dict[str, Any]]:
    entries = host["catalog"]["entries"]
    by_id = {entry["id"]: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ContractFailure(
            "compiler.catalog_duplicate",
            "host catalog entry IDs must be unique",
        )
    overlay = scenario["catalog_overlay"]
    referenced = set(overlay["add"]) | set(overlay["remove"]) | set(
        overlay["order"],
    )
    unknown = referenced - set(by_id)
    if unknown:
        raise ContractFailure(
            "compiler.catalog_unknown",
            f"scenario catalog overlay references unknown IDs: {sorted(unknown)}",
        )
    active = [
        entry for entry in entries if entry["id"] not in set(overlay["remove"])
    ]
    active_ids = {entry["id"] for entry in active}
    for entry_id in overlay["add"]:
        if entry_id not in active_ids:
            active.append(by_id[entry_id])
            active_ids.add(entry_id)
    if overlay["order"]:
        if (
            len(overlay["order"]) != len(active)
            or set(overlay["order"]) != active_ids
        ):
            raise ContractFailure(
                "compiler.catalog_order",
                "catalog overlay order must name every active entry exactly once",
            )
        active = [by_id[entry_id] for entry_id in overlay["order"]]
    return copy.deepcopy(active)


def _validate_routing_contract(
    scenario: dict[str, Any],
    catalog: list[dict[str, Any]],
) -> None:
    contract = scenario.get("routing_contract")
    if contract is None:
        return
    catalog_ids = [item["id"] for item in catalog]
    catalog_set = set(catalog_ids)
    referenced = {
        value
        for expectation in contract["expectations"]
        for field in (
            "declared", "discovered", "loaded", "model_visible",
            "selected", "invoked", "applied", "order", "composition",
        )
        for value in expectation[field]
    } | set(contract["participants"]) | {contract["target_skill_id"]}
    if not referenced <= catalog_set:
        raise ContractFailure(
            "compiler.routing_unknown",
            "routing contract references IDs outside the effective catalog",
        )
    if any(
        expectation["order"] != catalog_ids
        for expectation in contract["expectations"]
    ):
        raise ContractFailure(
            "compiler.routing_order",
            "routing expectation order must equal the full effective catalog",
        )


def _treatment_applies(
    treatment: dict[str, Any],
    scenario: dict[str, Any],
) -> bool:
    covered = (
        scenario["case_id"] in treatment["scenario_ids"]
        or bool(set(scenario["tags"]) & set(treatment["scenario_tags"]))
    )
    return (
        covered
        and scenario["case_id"] not in treatment["exclusions"]
        and treatment["profile"] in scenario["applicable_treatment_profiles"]
    )


def _selected_requirements(
    scenario: dict[str, Any],
) -> tuple[list[str], list[str]]:
    return (
        sorted({item["grader_id"] for item in scenario["requirements"]}),
        sorted({item["check_id"] for item in scenario["requirements"]}),
    )


def _required_capabilities(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    treatment: dict[str, Any],
    grader_ids: list[str],
) -> list[str]:
    capabilities = set(spec["host"]["required_capabilities"])
    capabilities.update(treatment["expected_capabilities"])
    for module in required_epoch7_modules(spec):
        capabilities.update(EPOCH7_MODULE_CAPABILITIES.get(module, set()))
    graders = {
        grader["grader_id"]: grader for grader in spec["graders"]
    }
    if any(graders[grader_id]["type"] == "model" for grader_id in grader_ids):
        capabilities.add("model_grading")
    if scenario["execution_context"]["expected_tools"]:
        capabilities.update({
            "action_authorization_trace",
            "render_effect_capture",
            "tool_schema_model_visible_capture",
        })
    return sorted(capabilities)


def _feasibility(
    required_capabilities: list[str],
    host: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    records = {
        item["capability"]: item for item in host["capabilities"]
    }
    missing = set(required_capabilities) - set(records)
    if missing:
        raise ContractFailure(
            "compiler.capability_missing",
            f"required capability probes are missing: {sorted(missing)}",
        )
    disposition, derived = derive_entry_disposition(
        set(required_capabilities), host,
    )
    return disposition, {
        "required_capabilities": list(required_capabilities),
        "probes": [
            copy.deepcopy(records[capability]["probe"])
            for capability in required_capabilities
        ],
        "derived_status": derived,
    }


def _required_authority(scenario: dict[str, Any]) -> list[str]:
    required = {"local_execution"}
    required.update(
        set(scenario["execution_context"]["expected_policy_surfaces"])
        & RUNTIME_AUTHORITY_FIELDS
    )
    return sorted(required)


def _validate_execute_authority(
    spec: dict[str, Any],
    required: list[str],
) -> None:
    authority = spec["authority"]
    missing: list[str] = []
    if (
        "local_execution" in required
        and "local_execution" not in authority["runner_capabilities"]
    ):
        missing.append("local_execution")
    missing.extend(
        name for name in required
        if name != "local_execution" and authority.get(name) is not True
    )
    if missing:
        raise ContractFailure(
            "compiler.authority_missing",
            f"execute entry lacks runtime authority: {sorted(missing)}",
        )


def _model_grade_specs(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    grader_ids: list[str],
) -> list[dict[str, Any]]:
    graders = {
        grader["grader_id"]: grader for grader in spec["graders"]
    }
    result: list[dict[str, Any]] = []
    for grader_id in grader_ids:
        grader = graders[grader_id]
        if grader["type"] != "model":
            continue
        result.append({
            "grader_id": grader_id,
            "blinded_projection": list(BLINDED_MODEL_PROJECTION),
            "prompt_id": grader["prompt_id"],
            "prompt": copy.deepcopy(grader["prompt"]),
            "schema_id": grader["schema_id"],
            "schema": copy.deepcopy(grader["output_schema"]),
            "schedule_id": grader["batch_schedule_id"],
        })
    return result


def _bind_model_grade_batches(
    entries: list[dict[str, Any]],
) -> None:
    groups: dict[
        tuple[str, str],
        list[tuple[dict[str, Any], dict[str, Any]]],
    ] = {}
    for entry in entries:
        for model_spec in entry["model_grade_specs"]:
            groups.setdefault(
                (entry["case_id"], model_spec["grader_id"]),
                [],
            ).append((entry, model_spec))
    for (case_id, grader_id), group in groups.items():
        executable = [
            item for item in group if item[0]["disposition"] == "execute"
        ]
        members = sorted(
            executable or group,
            key=lambda item: item[0]["entry_ordinal"],
        )
        if len(members) > model_transport.MAX_BATCH_ITEMS:
            raise InternalInvariantError(
                "model grader batch exceeds the transport item limit",
            )
        entry_ids = [entry["entry_id"] for entry, _ in members]
        batch_id = _structured_id("batch", case_id, grader_id)
        schedule_ids = {item["schedule_id"] for _, item in group}
        if len(schedule_ids) != 1:
            raise InternalInvariantError(
                "one model grader batch has multiple schedules",
            )
        owner = entry_ids[-1]
        for _, model_spec in group:
            model_spec.update({
                "batch_id": batch_id,
                "batch_entry_ids": entry_ids,
                "batch_owner_entry_id": owner,
            })


def _declared_handoff_ids(scenario: dict[str, Any]) -> list[str]:
    coordination = scenario.get("coordination")
    if coordination is None:
        return []
    return [
        _structured_id("handoff", edge["from"], edge["to"])
        for edge in coordination["dependency_edges"]
    ]


def _declared_action_ids(scenario: dict[str, Any]) -> list[str]:
    return [
        _structured_id("action", tool_id)
        for tool_id in scenario["execution_context"]["expected_tools"]
    ]


def _projection_digest(value: Any) -> bytes:
    return sha256(canonical_json_bytes(value)).digest()


def _build_entry(
    *,
    spec: dict[str, Any],
    scenario: dict[str, Any],
    treatment: dict[str, Any],
    host: dict[str, Any],
    repeat: int,
    ordinal: int,
    seen_entry_ids: set[str],
) -> dict[str, Any]:
    catalog = _catalog_for_scenario(host, scenario)
    _validate_routing_contract(scenario, catalog)
    grader_ids, check_ids = _selected_requirements(scenario)
    required_capabilities = _required_capabilities(
        spec, scenario, treatment, grader_ids,
    )
    disposition, feasibility = _feasibility(required_capabilities, host)
    required_authority = _required_authority(scenario)
    if disposition == "execute":
        _validate_execute_authority(spec, required_authority)
    entry_id = _structured_id(
        "entry", scenario["case_id"], treatment["treatment_id"], f"r{repeat}",
    )
    if entry_id in seen_entry_ids:
        raise ContractFailure(
            "compiler.entry_id_collision",
            f"duplicate structured entry identifier: {entry_id}",
        )
    seen_entry_ids.add(entry_id)
    observations = scenario.get("observation_contracts", [])
    return {
        "entry_id": entry_id,
        "entry_ordinal": ordinal,
        "disposition": disposition,
        "feasibility": feasibility,
        "case_id": scenario["case_id"],
        "treatment_id": treatment["treatment_id"],
        "repeat": repeat,
        "attempt_policy": copy.deepcopy(spec["execution"]["retry_policy"]),
        "execute_case_payload": {
            "subject_skill_id": spec["subject"]["skill_id"],
            "case": copy.deepcopy(scenario),
            "treatment": copy.deepcopy(treatment),
            "repeat": repeat,
            "workspace": f"workspaces/{entry_id}",
            "fixture": copy.deepcopy(scenario["fixture"]),
            "catalog": catalog,
            "execution_context": copy.deepcopy(
                scenario["execution_context"],
            ),
            "coordination": copy.deepcopy(scenario.get("coordination")),
            "turns": copy.deepcopy(scenario["turns"]),
            "fault_script": copy.deepcopy(scenario["fault_script"]),
            "model_policy": treatment["model_identity"],
            "tool_policy": treatment["tool_policy_id"],
            "network_policy": treatment["network_policy_id"],
            "permission_policy": treatment["permission_policy_id"],
            "context_policy": treatment["context_policy_id"],
            "observation_contracts": copy.deepcopy(observations),
            "artifact_contract": copy.deepcopy(spec["artifacts"]),
            "capture_contract": copy.deepcopy(host["capture"]),
        },
        "model_grade_specs": _model_grade_specs(
            spec, scenario, grader_ids,
        ),
        "grader_ids": grader_ids,
        "check_ids": check_ids,
        "principal_slot_ids": sorted(
            scenario["execution_context"]["expected_principal_slots"],
        ),
        "handoff_ids": _declared_handoff_ids(scenario),
        "action_ids": _declared_action_ids(scenario),
        "observation_ids": sorted(
            observation["observation_id"] for observation in observations
        ),
        "timeout_seconds": min(
            spec["execution"]["timeout_seconds"],
            scenario["timeout_seconds"],
        ),
        "reset_policy": spec["execution"]["reset_policy"],
        "cleanup_policy": (
            "required"
            if spec["artifacts"]["cleanup_required"]
            else "not_required"
        ),
        "required_authority": required_authority,
        "required_capabilities": required_capabilities,
        "artifact_relpath": f"entries/{entry_id}",
    }


def _ordered_blocks(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    *,
    digest_fn: Callable[[Any], bytes],
) -> list[tuple[bytes, dict[str, Any], int]]:
    blocks: list[tuple[bytes, bytes, dict[str, Any], int]] = []
    seen: dict[bytes, bytes] = {}
    for scenario in scenarios:
        for repeat in range(1, spec["suite"]["repeats"] + 1):
            projection = {
                "case_id": scenario["case_id"],
                "evaluation_id": spec["evaluation_id"],
                "ordering_seed": spec["suite"]["order_seed"],
                "repeat": repeat,
            }
            payload = canonical_json_bytes(projection)
            digest = digest_fn(projection)
            if not isinstance(digest, bytes) or len(digest) != 32:
                raise InternalInvariantError(
                    "block digest must contain 32 bytes",
                )
            previous = seen.get(digest)
            if previous is not None and previous != payload:
                raise ContractFailure(
                    "compiler.block_collision",
                    "distinct case/repeat blocks have the same digest",
                )
            seen[digest] = payload
            blocks.append((digest, payload, scenario, repeat))
    blocks.sort(key=lambda item: item[0])
    return [
        (digest, scenario, repeat)
        for digest, _, scenario, repeat in blocks
    ]


def _rotated_treatments(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    block_digest: bytes,
) -> list[dict[str, Any]]:
    treatments = sorted(
        (
            treatment for treatment in spec["treatments"]
            if _treatment_applies(treatment, scenario)
        ),
        key=lambda item: item["treatment_id"],
    )
    selected_ids = {
        treatment["treatment_id"] for treatment in treatments
    }
    if scenario["attribution_evaluable"]:
        for estimand in spec["analysis"]["estimands"]:
            pair = {
                estimand["candidate_treatment_id"],
                estimand["comparator_treatment_id"],
            }
            if selected_ids & pair and not pair <= selected_ids:
                raise ContractFailure(
                    "compiler.causal_matrix",
                    (
                        f"scenario {scenario['case_id']} does not include both "
                        f"treatments for estimand {estimand['estimand_id']}"
                    ),
                )
    if not treatments:
        raise ContractFailure(
            "compiler.matrix_empty",
            f"scenario {scenario['case_id']} has no applicable treatment",
        )
    rotation_digest = sha256(canonical_json_bytes({
        "block_digest": "sha256:" + block_digest.hex(),
        "purpose": "treatment-rotation",
    })).digest()
    offset = int.from_bytes(rotation_digest, "big") % len(treatments)
    return treatments[offset:] + treatments[:offset]


def _package_digests(
    spec: dict[str, Any],
    host: dict[str, Any],
) -> dict[str, str]:
    result = {
        entry["id"]: entry["root_digest"]
        for entry in host["catalog"]["entries"]
    }
    skill_id = spec["subject"]["skill_id"]
    package_digest = spec["subject"]["package"]["package_digest"]
    if skill_id in result and result[skill_id] != package_digest:
        raise ContractFailure(
            "compiler.package_identity",
            "subject package digest differs from its catalog entry",
        )
    result[skill_id] = package_digest
    return dict(sorted(result.items()))


def compile_plan(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    host: dict[str, Any],
    *,
    runtime_override: dict[str, str] | None = None,
    digest_fn: Callable[[Any], bytes] = _projection_digest,
) -> dict[str, Any]:
    normalized_spec = _normalize_spec(spec)
    normalized_scenarios = sorted(
        (_normalize_scenario(scenario) for scenario in scenarios),
        key=lambda item: item["case_id"],
    )
    normalized_host = _normalize_host(host)
    source_revision = normalized_spec["subject"]["package"][
        "source_revision"
    ]
    verifier_revisions = {
        grader["verifier"]["source_revision"]
        for grader in normalized_spec["graders"]
        if grader["type"] == "deterministic"
    }
    if len(verifier_revisions) > 1:
        raise ContractFailure(
            "compiler.verifier_identity",
            "deterministic verifiers must share one apparatus revision",
        )
    compiler_revision = next(iter(verifier_revisions), source_revision)
    compiler = _compiler_identity(compiler_revision, runtime_override)

    seen_entry_ids: set[str] = set()
    entries: list[dict[str, Any]] = []
    for block_digest, scenario, repeat in _ordered_blocks(
        normalized_spec,
        normalized_scenarios,
        digest_fn=digest_fn,
    ):
        for treatment in _rotated_treatments(
            normalized_spec, scenario, block_digest,
        ):
            entries.append(_build_entry(
                spec=normalized_spec,
                scenario=scenario,
                treatment=treatment,
                host=normalized_host,
                repeat=repeat,
                ordinal=len(entries),
                seen_entry_ids=seen_entry_ids,
            ))
    if not entries:
        raise ContractFailure(
            "compiler.matrix_empty",
            "semantic case/treatment/repeat matrix is empty",
        )
    _bind_model_grade_batches(entries)
    plan_id = _structured_id("plan", normalized_spec["evaluation_id"])
    counts = {
        disposition: sum(
            entry["disposition"] == disposition for entry in entries
        )
        for disposition in ("execute", "unsupported", "not_evaluable")
    }
    dimensions = sorted({
        requirement["dimension"]
        for scenario in normalized_scenarios
        for requirement in scenario["requirements"]
    })
    plan: dict[str, Any] = {
        "schema_version": 3,
        "plan_id": plan_id,
        "evaluation_id": normalized_spec["evaluation_id"],
        "source_revision": source_revision,
        "package_digests": _package_digests(
            normalized_spec, normalized_host,
        ),
        "compiler": compiler,
        "subject_shape": normalized_spec["subject"]["shape"],
        "module_decisions": copy.deepcopy(
            normalized_spec["applicability"],
        ),
        "treatments": copy.deepcopy(normalized_spec["treatments"]),
        "catalog": copy.deepcopy(normalized_host["catalog"]["entries"]),
        "execution_profile": _execution_profile(
            normalized_spec, normalized_host,
        ),
        "ordering": {
            "algorithm": ORDERING_ALGORITHM,
            "version": ORDERING_VERSION,
            "seed": normalized_spec["suite"]["order_seed"],
        },
        "expected_counts": {
            "total": len(entries),
            **counts,
        },
        "dimension_coverage": {
            dimension: sum(
                requirement["dimension"] == dimension
                for entry in entries
                for requirement in entry["execute_case_payload"]["case"][
                    "requirements"
                ]
            )
            for dimension in dimensions
        },
        "entries": entries,
        "artifacts": {
            "root": normalize_relative_path(
                normalized_spec["artifacts"]["root"],
                "artifacts root",
            ),
            "index_relpath": normalize_relative_path(
                normalized_spec["artifacts"]["index_relpath"],
                "artifacts index",
            ),
            "retention": normalized_spec["artifacts"]["retention"],
            "immutable": True,
        },
        "authority": {
            "runner_capabilities": list(
                normalized_spec["authority"]["runner_capabilities"],
            ),
            "external_effects_allowed": any(
                normalized_spec["authority"][field]
                for field in (
                    "install",
                    "publish",
                    "deploy",
                    "release",
                    "external_writes",
                )
            ),
        },
    }
    if plan["artifacts"]["index_relpath"].split("/", 1)[0] == "entries":
        raise ContractFailure(
            "compiler.index_path",
            "artifacts index_relpath must not be inside an entry directory",
        )
    return plan


def validate_compiled_plan(
    plan: dict[str, Any],
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    host: dict[str, Any],
    *,
    registry: dict[str, dict[str, Any]],
    runtime_override: dict[str, str] | None = None,
    digest_fn: Callable[[Any], bytes] = _projection_digest,
) -> None:
    diagnostics = validate_epoch7_schema(
        plan, "execution-plan-v3.schema.json", registry,
    )
    if diagnostics:
        code, message = _first_diagnostic(diagnostics)
        raise ContractFailure("compiler.output_schema", f"{code}: {message}")
    expected = compile_plan(
        spec,
        scenarios,
        host,
        runtime_override=runtime_override,
        digest_fn=digest_fn,
    )
    if canonical_json_bytes(plan) != canonical_json_bytes(expected):
        raise ContractFailure(
            "compiler.plan_semantics",
            "plan bytes differ from the deterministic input projection",
        )


def _commit_plan(
    output_path: Path,
    plan: dict[str, Any],
    *,
    validate_written: Callable[[dict[str, Any]], None],
) -> None:
    payload = canonical_json_bytes(plan)
    if output_path.exists():
        if output_path.read_bytes() == payload:
            validate_written(load_json(output_path))
            return
        existing = load_json(output_path)
        if (
            isinstance(existing, dict)
            and existing.get("plan_id") == plan["plan_id"]
        ):
            raise ContractFailure(
                "compiler.plan_id_collision",
                "existing output has the same plan_id and different bytes",
            )
        raise FileExistsError(
            f"refusing to overwrite different output bytes: {output_path}",
        )
    atomic_write_bytes(output_path, payload)
    written = load_json(output_path)
    validate_written(written)
    if canonical_json_bytes(written) != payload:
        raise InternalInvariantError(
            "post-write plan bytes differ from compiled bytes",
        )


def _compile_command(args: argparse.Namespace) -> int:
    spec_path = Path(args.spec)
    scenarios_path = Path(args.scenarios)
    host_path = Path(args.host)
    output_path = Path(args.output)
    try:
        spec, scenarios, host, registry = _load_ready_contract(
            spec_path, scenarios_path, host_path,
        )
        plan = compile_plan(
            spec,
            scenarios,
            host,
        )

        def validate_written(value: dict[str, Any]) -> None:
            validate_compiled_plan(
                value,
                spec,
                scenarios,
                host,
                registry=registry,
            )

        validate_written(plan)
        _commit_plan(
            output_path,
            plan,
            validate_written=validate_written,
        )
    except ContractFailure as exc:
        print(f"ERROR {exc.code}: {exc}", file=sys.stderr)
        return 1
    except (
        FileExistsError,
        InternalInvariantError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"compiler error: {exc}", file=sys.stderr)
        return 2
    counts = plan["expected_counts"]
    print(
        f"PLAN VALID: {plan['plan_id']} "
        f"execute={counts['execute']} unsupported={counts['unsupported']} "
        f"not_evaluable={counts['not_evaluable']}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec")
    parser.add_argument("scenarios")
    parser.add_argument("host")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return _compile_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
