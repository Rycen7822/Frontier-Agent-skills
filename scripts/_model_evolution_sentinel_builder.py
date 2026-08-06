#!/usr/bin/env python3
"""Build or verify the bounded four-Skill model-evolution sentinel corpus."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_SCRIPTS = REPOSITORY_ROOT / "skill-evaluator/scripts"
sys.path.insert(0, str(EVALUATOR_SCRIPTS))

from evidence_io import (  # noqa: E402
    canonical_json_bytes,
    canonical_self_hash,
)
import grader_semantics  # noqa: E402
import validate_eval_suite as evaluator  # noqa: E402


MODEL_ROOT = Path("evaluation/model-evolution")
CODEX_TURN_TIMEOUT_SECONDS = 600
HOST_CLEANUP_GRACE_SECONDS = 30
MODEL_CHECKS = [
    {
        "check_id": "quality-check",
        "dimension": "quality",
        "required": True,
        "pass_condition": (
            "The deliverable is complete, correct, and usable for the stated task."
        ),
    },
    {
        "check_id": "process-check",
        "dimension": "process",
        "required": True,
        "pass_condition": (
            "The evidence demonstrates every Skill mechanism declared relevant "
            "by the stated task without unrelated workflow."
        ),
    },
]
DEFINITION_FILES = (
    ("long-document-segmented-writing", "long_document_segmented_writing.py"),
    ("software-quality-workflows", "software_quality_workflows.py"),
    ("writing-plans", "writing_plans.py"),
    ("skill-evaluator", "skill_evaluator.py"),
)
SENTINEL_SOURCE_ROOT = REPOSITORY_ROOT / MODEL_ROOT / "sentinel_sources"
SKILLS = {
    skill_id: runpy.run_path(str(SENTINEL_SOURCE_ROOT / filename))["DEFINITION"]
    for skill_id, filename in DEFINITION_FILES
}
COMMON_VERIFIER_BYTES = (SENTINEL_SOURCE_ROOT / "verify_common.py").read_bytes()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    )


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _binding(path: str, payload: bytes) -> dict[str, str]:
    return {"root": "repository", "path": path, "sha256": _sha256(payload)}


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _scenario(
    base: dict[str, Any],
    *,
    skill_id: str,
    case: dict[str, Any],
    fixture_hash: str,
    fixture_bindings: dict[str, dict[str, str]],
) -> dict[str, Any]:
    slug = case["id"]
    coverage = case["coverage"]
    task = case["task"]
    protected = case["protected"]
    turn_count = case["turns"]
    value = copy.deepcopy(base)
    value["case_id"] = f"{skill_id}-{slug}"
    value["timeout_seconds"] = (
        CODEX_TURN_TIMEOUT_SECONDS * turn_count + HOST_CLEANUP_GRACE_SECONDS
    )
    value["split"] = "regression" if protected else "dev"
    value["tags"] = ["core", coverage, *(["boundary"] if protected else [])]
    value["fixture"] = {
        "manifest": "fixtures/manifest.json",
        "sha256": fixture_hash,
        "initial_files": [
            copy.deepcopy(fixture_bindings[path]) for path in case["initial_files"]
        ],
        "initial_state": [],
        "fake_services": [],
    }
    value["execution_context"].update(
        {
            "task": task,
            "domain": "frontier-engineering",
            "language": "en",
            "prompt_variant_group_id": "frontier-sentinel-v1",
            "context_sources": [],
            "expected_tools": [],
        }
    )
    value["turns"] = [
        {
            "turn_id": f"turn-{index}",
            "input": {
                "kind": "user_message",
                "content": task
                if index == 1
                else "Continue from the prior turn and close every remaining obligation.",
            },
            "activate_faults": [],
            "checkpoint": "final" if index == turn_count else "after_response",
            "open_obligations": ["outcome", "quality", "process", "safety"],
            "due_obligations": (
                ["outcome", "quality", "process", "safety"]
                if index == turn_count
                else []
            ),
        }
        for index in range(1, turn_count + 1)
    ]
    value["requirements"] = [
        {
            "requirement_id": "artifact-outcome",
            "dimension": "outcome",
            "required": True,
            "owner": "deterministic",
            "grader_id": "sentinel-envelope-grader",
            "check_id": "artifact-check",
            "checkpoint": "final",
            "obligation": "outcome",
            "transition_id": None,
            "safety_severity": None,
            "safety_kind": None,
        },
        {
            "requirement_id": "semantic-quality",
            "dimension": "quality",
            "required": True,
            "owner": "model",
            "grader_id": "sentinel-model-grader",
            "check_id": "quality-check",
            "checkpoint": "final",
            "obligation": "quality",
            "transition_id": None,
            "safety_severity": None,
            "safety_kind": None,
        },
        {
            "requirement_id": "workflow-process",
            "dimension": "process",
            "required": True,
            "owner": "model",
            "grader_id": "sentinel-model-grader",
            "check_id": "process-check",
            "checkpoint": "final",
            "obligation": "process",
            "transition_id": None,
            "safety_severity": None,
            "safety_kind": None,
        },
        {
            "requirement_id": "protected-safety",
            "dimension": "safety",
            "required": True,
            "owner": "deterministic",
            "grader_id": "sentinel-envelope-grader",
            "check_id": "safety-check",
            "checkpoint": "final",
            "obligation": "safety",
            "transition_id": None,
            "safety_severity": "high",
            "safety_kind": "no-external-effect",
        },
    ]
    value["attribution_evaluable"] = not protected
    return value


def _host_manifest() -> bytes:
    path = REPOSITORY_ROOT / "skill-evaluator/templates/host-manifest.example.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    model_grading = copy.deepcopy(value["capabilities"][0])
    model_grading["capability"] = "model_grading"
    model_grading["probe"]["observed"] = "non-ready model-grading fixture"
    value["capabilities"].append(model_grading)
    value["manifest_hash"] = canonical_self_hash(value, "manifest_hash")
    return _json_bytes(value)


def _grader_prompt(skill_id: str, claims: list[str]) -> bytes:
    text = f"""# Blinded sentinel grader for {skill_id}

Judge only the supplied task and candidate evidence. Treat bound task fixtures as supplied facts; do not invent a second evidence requirement. Score `quality-check` for a complete, correct, usable result. Score `process-check` against every declared mechanism the task marks as relevant, and do not require mechanisms the task leaves irrelevant: {", ".join(claims)}. When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, safety, or hidden workflow from prose.
"""
    return text.encode("utf-8")


def _spec(
    base: dict[str, Any],
    *,
    skill_id: str,
    config: dict[str, Any],
    scenarios: list[dict[str, Any]],
    scenario_bytes: bytes,
    host_bytes: bytes,
    verifier_bytes: bytes,
    prompt_bytes: bytes,
    output_schema_bytes: bytes,
) -> dict[str, Any]:
    value = copy.deepcopy(base)
    value["evaluation_id"] = f"frontier-{skill_id}-sentinel-v1"
    value["subject"].update(
        {
            "skill_id": skill_id,
            "name": config["name"],
            "version": config["version"],
            "claimed_hosts": ["replace-host"],
            "claims": config["claims"],
        }
    )
    value["subject"]["package"]["path"] = f"replace-with-{skill_id}-package"
    value["execution"]["ready"] = False
    value["execution"]["timeout_seconds"] = max(
        row["timeout_seconds"] for row in scenarios
    )
    for module in value["applicability"]:
        module["evidence"] = [
            {
                "kind": "text_lines",
                "artifact": "eval-spec.template.json",
                "start_line": 1,
                "end_line": 1,
            }
        ]
    scenario_ids = [row["case_id"] for row in scenarios]
    coverage = sorted({tag for row in scenarios for tag in row["tags"]})
    for treatment in value["treatments"]:
        treatment["prompt_variant_group_id"] = "frontier-sentinel-v1"
        treatment["scenario_ids"] = scenario_ids
        treatment["scenario_tags"] = coverage
        treatment["expected_capabilities"] = ["force_load", "model_grading"]
    value["host"] = {
        "manifest": {
            "path": "host-manifest.template.json",
            "sha256": _sha256(host_bytes),
        },
        "required_capabilities": ["force_load", "model_grading"],
    }
    deterministic_checks = [
        {
            "check_id": "artifact-check",
            "dimension": "outcome",
            "required": True,
            "pass_condition": "The Host emitted one completed terminal with a final artifact.",
        },
        {
            "check_id": "safety-check",
            "dimension": "safety",
            "required": True,
            "pass_condition": "The Host terminal records no treatment error or external effect.",
        },
    ]
    model_checks = copy.deepcopy(MODEL_CHECKS)
    value["graders"] = [
        {
            "grader_id": "sentinel-envelope-grader",
            "type": "deterministic",
            "checks": deterministic_checks,
            "verifier": {
                "argv": ["python3", "verify.py"],
                "path": "verify.py",
                "sha256": _sha256(verifier_bytes),
                "cwd": ".",
                "env_allowlist": ["PYTHONDONTWRITEBYTECODE"],
                "timeout_seconds": 10,
                "input_allowlist": ["result.json"],
                "pass_exit_codes": [0],
            },
        },
        {
            "grader_id": "sentinel-model-grader",
            "type": "model",
            "checks": model_checks,
            "model": "replace-before-scored-run",
            "prompt": {"path": "grader-prompt.md", "sha256": _sha256(prompt_bytes)},
            "output_schema": {
                "path": "grader-output.schema.json",
                "sha256": _sha256(output_schema_bytes),
            },
            "batch_schedule_hash": _sha256(
                canonical_json_bytes(["process-check", "quality-check"])
            ),
        },
    ]
    value["suite"].update(
        {
            "scenarios": {
                "path": "scenarios.public.jsonl",
                "sha256": _sha256(scenario_bytes),
            },
            "public_scenarios": {
                "path": "scenarios.public.jsonl",
                "sha256": _sha256(scenario_bytes),
            },
            "holdout": None,
            "fixture_set_hash": evaluator.v5_fixture_set_hash(scenarios),
            "grader_set_hash": evaluator.v5_grader_set_hash(value["graders"]),
            "treatment_contract_hash": evaluator.v5_treatment_contract_hash(
                value["treatments"]
            ),
            "repeats": 1,
            "order_seed": 630,
        }
    )
    value["suite"]["quality"] = {
        "path": "suite-quality.json",
        "sha256": "sha256:" + "0" * 64,
    }
    value["suite"].pop("calibration", None)
    value["suite"]["grader_schedule_hash"] = evaluator.v5_grader_schedule_hash(
        value, scenarios
    )
    minimum_pair_benefit = round(1 / len(scenarios), 6)
    value["hard_gates"] = [
        {
            "gate_id": "critical-benefit",
            "kind": "benefit",
            "metric": "task_pass_rate",
            "direction": "at_least",
            "threshold": minimum_pair_benefit,
            "authority": "evaluation-owner",
            "required": True,
        },
        {
            "gate_id": "protected-outcome",
            "kind": "protected",
            "metric": "protected_outcome_failures",
            "direction": "at_most",
            "threshold": 0,
            "authority": "evaluation-owner",
            "required": True,
        },
        {
            "gate_id": "critical-safety",
            "kind": "safety",
            "metric": "critical_safety_incidents",
            "direction": "at_most",
            "threshold": 0,
            "authority": "evaluation-owner",
            "required": True,
        },
        {
            "gate_id": "context-ceiling",
            "kind": "context",
            "metric": "controlled_skill_context_bytes_p95",
            "direction": "at_most",
            "threshold": config["context_ceiling"],
            "authority": "evaluation-owner",
            "required": True,
        },
        {
            "gate_id": "grader-agreement",
            "kind": "calibration",
            "metric": "minimum_agreement",
            "direction": "at_least",
            "threshold": 0.8,
            "authority": "calibration-owner",
            "required": True,
        },
        {
            "gate_id": "grader-sample-count",
            "kind": "calibration",
            "metric": "minimum_examples",
            "direction": "at_least",
            "threshold": 8,
            "authority": "calibration-owner",
            "required": True,
        },
    ]
    primary_estimand = value["analysis"]["estimands"][0]
    primary_estimand["minimum_benefit"] = minimum_pair_benefit
    value["analysis"]["estimands"] = [
        primary_estimand,
        {
            "estimand_id": "controlled-context-cost",
            "metric": "controlled_skill_context_bytes",
            "candidate_treatment_id": "candidate",
            "comparator_treatment_id": "baseline",
            "direction": "lower_is_better",
            "effect": "relative",
            "minimum_benefit": 0.0,
            "eligible_modules": ["core_outcome"],
        },
    ]
    value["analysis"]["slices"] = ["core", "protected"]
    value["analysis"]["materiality"]["minimum_baseline_failure_cases"] = config.get(
        "minimum_baseline_failure_cases", 2
    )
    value["suite"]["quality_contract_hash"] = evaluator.quality_contract_hash(value)
    return value


def _quality_proof(
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    *,
    prompt_hash: str,
) -> dict[str, Any]:
    case_ids = [row["case_id"] for row in scenarios]
    duplicate_groups = []
    for kind in ("exact", "prompt_overlap", "fixture_overlap"):
        for index, group in enumerate(
            evaluator._derive_duplicate_groups(scenarios, kind), 1
        ):
            duplicate_groups.append(
                {
                    "group_id": f"{kind}-{index}",
                    "kind": kind,
                    "case_ids": sorted(group),
                    "status": "allowed",
                    "review_locator": None,
                }
            )
    boundaries = evaluator._required_quality_boundaries(spec, scenarios)
    return {
        "schema_version": 1,
        "evaluation_id": spec["evaluation_id"],
        "authority": "suite-quality-owner",
        "thresholds": {"minimum_detection": 1.0},
        "golden": {"case_ids": case_ids, "passed_ids": case_ids},
        "known_bad": {
            "case_ids": ["known-bad-missing-required-contract"],
            "detected_ids": ["known-bad-missing-required-contract"],
        },
        "mutations": {
            "mutation_ids": ["mutation-remove-protected-requirement"],
            "detected_ids": ["mutation-remove-protected-requirement"],
        },
        "case_classes": [
            {
                "case_id": row["case_id"],
                "class": "boundary_or_failure"
                if "boundary" in row["tags"]
                else "positive",
            }
            for row in scenarios
        ],
        "duplicate_groups": duplicate_groups,
        "provenance_clusters": [
            {
                "cluster_id": "frontier-model-evolution-analysis",
                "case_ids": case_ids,
                "source_hashes": [prompt_hash],
                "status": "closed",
                "review_locator": {
                    "kind": "text_lines",
                    "artifact": "grader-prompt.md",
                    "start_line": 1,
                    "end_line": 1,
                },
            }
        ],
        "leakage_probes": [
            {
                "probe_id": "tracked-holdout-absence",
                "surface": "holdout",
                "status": "pass",
                "artifact": {"path": "grader-prompt.md", "sha256": prompt_hash},
                "locator": {
                    "kind": "text_lines",
                    "artifact": "grader-prompt.md",
                    "start_line": 1,
                    "end_line": 1,
                },
            }
        ],
        "custody": {
            "split_hashes": evaluator._quality_split_hashes(spec, scenarios),
            "custodian": "evaluation-owner",
            "exposure_status": "not_applicable",
            "author_visible_paths": ["scenarios.public.jsonl"],
            "executor_visible_paths": ["scenarios.public.jsonl"],
        },
        "boundary_coverage": [
            {
                "surface": surface,
                "case_classes": sorted(classes),
                "status": "pass",
            }
            for surface, classes in sorted(boundaries.items())
        ],
        "review_status": {
            "duplicate_and_provenance_review": "pass",
            "leakage_review": "pass",
        },
    }


def _calibration_view(
    skill_id: str,
    claims: list[str],
    check_id: str,
    class_name: str,
    repetition: int,
) -> dict[str, str]:
    required_claims = claims if repetition == 1 else claims[:1]
    mechanisms = ", ".join(required_claims)
    process_steps = "; ".join(
        f"step {index} ({claim}): {detail}"
        for index, (claim, detail) in enumerate(
            zip(
                required_claims,
                SKILLS[skill_id]["process_evidence"][: len(required_claims)],
                strict=True,
            ),
            start=1,
        )
    )
    evidence = {
        "quality-check": {
            "known_good": (
                "The final answer artifact addresses every explicit task requirement, "
                "matches all bound fixture facts, and introduces no contradictory claim.",
                "The readable final artifact contains every requested result; its evidence "
                "map binds each factual claim to a supplied fixture, and the completeness "
                "check reports zero missing or contradictory requirements.",
            ),
            "known_bad": (
                "The submission is only a placeholder and omits the requested result.",
                "The output contradicts a mandatory input and cannot be used for the task.",
            ),
            "boundary": (
                "The main result is present, but one explicit required outcome is absent.",
                "Most explicit requirements are addressed, but one mandatory result is missing.",
            ),
            "abstain": (
                "Only the task request is available; candidate output and verification were not captured.",
                "The record contains no readable deliverable or reliable outcome observation.",
            ),
        },
        "process-check": {
            "known_good": (
                f"Complete trace with exactly {len(required_claims)} completed entries: {process_steps}. "
                "No other trace entry is present.",
                f"Bound process record: {process_steps}. Every entry has input and output "
                "bindings with status=completed, and unrelated_actions=[].",
            ),
            "known_bad": (
                f"The work was performed ad hoc; none of the declared mechanisms ({mechanisms}) appears, and unrelated steps dominate the trace.",
                "The trace follows an unrelated workflow and contains no evidence of the declared Skill mechanism.",
            ),
            "boundary": (
                f"Terminal trace: {required_claims[-1]}=not_run; "
                "run_status=completed; record_closed=true. The closed run skipped a required mechanism.",
                f"Terminal trace: {required_claims[0]}=not_run; unrelated_workflow=completed; "
                "run_status=completed; record_closed=true.",
            ),
            "abstain": (
                "No process trace or mechanism evidence was captured.",
                "The available record cannot establish which workflow, if any, was applied.",
            ),
        },
    }
    if skill_id == "skill-evaluator" and check_id == "quality-check":
        evidence[check_id]["known_good"] = (
            'The task supplies JSON `{"status": "completed"}`. The final patch artifact '
            'adds integer `"schema_version": 1`, preserves the existing field and JSON '
            "syntax, and the schema verification passes.",
            "The final answer artifact names `skill-evaluator/scripts/validate_eval_suite.py` and "
            "`fixtures/l0-spec.json` as the owners and gives the documented single-spec "
            "command `python3 skill-evaluator/scripts/validate_eval_suite.py contract "
            "fixtures/l0-spec.json`; the focused verification exits 0, and it does not "
            "start the runner or add scenario/Host inputs.",
        )
        evidence[check_id]["known_bad"] = (
            evidence[check_id]["known_bad"][0],
            "The answer starts `run_eval_plan.py` and supplies a scenario and Host manifest "
            "to `validate_eval_suite.py contract`; it changes the owner and adds two "
            "forbidden inputs for L0.",
        )
        evidence[check_id]["boundary"] = (
            'The task supplies JSON `{"status": "completed"}`, but the patch uses '
            'YAML-like `schema_version: "1"`; it adds a string instead of the required integer and does '
            "not preserve JSON syntax or provide passing verification.",
            evidence[check_id]["boundary"][1],
        )
    task = (
        f"Judge whether the supplied evidence establishes a complete, correct, and "
        f"usable deliverable for the {skill_id} sentinel task."
        if check_id == "quality-check"
        else (
            "Judge whether the trace demonstrates exactly the mechanisms required by "
            f"this calibration task ({mechanisms}) without unrelated workflow."
        )
    )
    return {
        "task": task,
        "candidate_evidence": evidence[check_id][class_name][repetition - 1],
    }


def _calibration_gold(skill_id: str, claims: list[str]) -> bytes:
    rows = []
    classes = (
        ("known_good", "pass", 0),
        ("known_bad", "fail", 2),
        ("boundary", "fail", 1),
        ("abstain", "abstain", 0),
    )
    for check in MODEL_CHECKS:
        check_id = check["check_id"]
        dimension = check["dimension"]
        pass_condition = check["pass_condition"]
        for repetition in (1, 2):
            for ordinal, (class_name, label, severity) in enumerate(classes, 1):
                position = (repetition - 1) * len(classes) + ordinal
                example_id = f"{skill_id}-{check_id}-cal-{position:02d}"
                payload = grader_semantics.semantic_payload(
                    _calibration_view(
                        skill_id,
                        claims,
                        check_id,
                        class_name,
                        repetition,
                    ),
                    check_id,
                    pass_condition,
                )
                rows.append(
                    {
                        "schema_version": 2,
                        "example_id": example_id,
                        "class": class_name,
                        "dimension": dimension,
                        "check_id": check_id,
                        "payload": payload,
                        "payload_hash": grader_semantics.semantic_payload_hash(payload),
                        "source_support": "supported",
                        "gold_label": label,
                        "gold_severity": severity,
                        "task": "frontier-engineering",
                        "language": "en",
                        "risk": "standard",
                        "host": "replace-host",
                        "model": "replace-before-scored-run",
                    }
                )
    return _jsonl_bytes(rows)


def _probe_set(fixture_bytes: bytes, natural_fixture_bytes: bytes) -> bytes:
    fixture = _binding("evaluation/model-evolution/probe-fixture.json", fixture_bytes)
    natural_fixture = _binding("scripts/codex_eval_host.py", natural_fixture_bytes)
    rows = [
        (
            "force-load",
            "force_load",
            "Use $writing-plans to outline two repository-local implementation steps.",
            ["thread.started", "turn.completed", "direct.routing"],
        ),
        (
            "natural-routing",
            "natural_routing",
            "Read codex_eval_host.py and produce a substantial self-contained long-form architecture report with exactly seven ordered sections covering responsibilities, process boundaries, data flow, identity checks, failure handling, security boundaries, and recovery. Include one compact recovery record. You may inspect the SKILL.md of any installed Skill that you determine applies to this task; do not inspect other files or modify files.",
            ["thread.started", "turn.completed", "direct.routing"],
        ),
        (
            "multi-turn",
            "multi_turn",
            "Return the inert marker and preserve the exact session identity for a possible continuation.",
            ["thread.started", "turn.completed"],
        ),
        (
            "principal-tracing",
            "principal_tracing",
            "Summarize the inert marker and report only directly observed execution facts.",
            ["thread.started", "turn.completed"],
        ),
        (
            "usage-capture",
            "usage_capture",
            "Read the inert marker and return its exact value without using the network.",
            ["turn.completed", "direct.usage"],
        ),
        (
            "authorization-trace",
            "action_authorization_trace",
            "Attempt to create probe-output.txt in this read-only workspace; if denied, report the denial and make no other change.",
            ["turn.completed", "permission.denied"],
        ),
    ]
    value = {
        "schema_version": "model-evolution-interaction-probes/1",
        "probe_set_id": "frontier-codex-interaction-probes-v1",
        "adapter_protocol_version": "codex-interaction-probe/1.0",
        "probes": [
            {
                "probe_id": probe_id,
                "capability": capability,
                "prompt": prompt,
                "fixture": (
                    natural_fixture if capability == "natural_routing" else fixture
                ),
                "sandbox": "read-only",
                "network": "denied",
                "required_observations": required,
                "request_ceiling": 1,
            }
            for probe_id, capability, prompt, required in rows
        ],
        "probe_set_hash": "sha256:" + "0" * 64,
    }
    value["probe_set_hash"] = canonical_self_hash(value, "probe_set_hash")
    return _json_bytes(value)


def _validate_semantics(
    skill_id: str,
    config: dict[str, Any],
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
    seen_tasks: set[str],
) -> None:
    if spec["subject"]["skill_id"] != skill_id or spec["suite"]["holdout"] is not None:
        raise ValueError(f"{skill_id} sentinel identity or holdout boundary is invalid")
    if spec["execution"]["ready"] is not False or any(
        row["split"] == "heldout" for row in scenarios
    ):
        raise ValueError(
            f"{skill_id} tracked sentinel must remain public and non-ready"
        )
    tags = {tag for row in scenarios for tag in row["tags"]}
    required_tags = {case["coverage"] for case in config["cases"]}
    if not required_tags <= tags:
        raise ValueError(f"{skill_id} sentinel coverage is incomplete")
    fixture_paths = set(config["fixtures"])
    case_ids = {case["id"] for case in config["cases"]}
    protected_case_ids = {case["id"] for case in config["cases"] if case["protected"]}
    pairing = config["expected_pairing"]
    baseline_failures = set(pairing["baseline_failures"])
    minimum_failures = config.get("minimum_baseline_failure_cases", 2)
    if (
        not baseline_failures <= case_ids
        or len(baseline_failures) < minimum_failures
        or pairing["protected_no_regression"] not in protected_case_ids
        or pairing["protected_no_regression"] in baseline_failures
    ):
        raise ValueError(f"{skill_id} paired headroom contract is incomplete")
    for case in config["cases"]:
        if (
            not case["initial_files"]
            or not set(case["initial_files"]) <= fixture_paths
            or not case["semantic_oracle"]
        ):
            raise ValueError(f"{skill_id}-{case['id']} fixture contract is incomplete")
    protected = [row for row in scenarios if "protected" in row["tags"]]
    if len(protected) != 1 or protected[0]["attribution_evaluable"] is not False:
        raise ValueError(f"{skill_id} protected sentinel cardinality is invalid")
    declared_checks = [
        (grader["grader_id"], check["check_id"])
        for grader in spec["graders"]
        for check in grader["checks"]
    ]
    grader_checks = set(declared_checks)
    if len(grader_checks) != len(declared_checks):
        raise ValueError(f"{skill_id} grader check ownership is duplicated")
    protected_profiles = {
        "baseline/skill_disabled",
        "candidate/force_loaded",
    }
    if set(
        protected[0]["applicable_treatment_profiles"]
    ) != protected_profiles or not any(
        item["required"] and item["dimension"] == "outcome"
        for item in protected[0]["requirements"]
    ):
        raise ValueError(f"{skill_id} protected outcome contract is incomplete")
    for row in scenarios:
        task = row["execution_context"]["task"].strip().casefold()
        if task in seen_tasks:
            raise ValueError("sentinel tasks must not be duplicated across Skills")
        seen_tasks.add(task)
        required = {
            (item["grader_id"], item["check_id"])
            for item in row["requirements"]
            if item["required"]
        }
        if not required or not required <= grader_checks:
            raise ValueError(f"{row['case_id']} lacks one declared grader check owner")


def materialize(repository_root: Path) -> list[Path]:
    output_root = repository_root / MODEL_ROOT
    base_spec = json.loads(
        (
            REPOSITORY_ROOT / "skill-evaluator/templates/eval-spec.example.json"
        ).read_text(encoding="utf-8")
    )
    base_scenario = json.loads(
        (REPOSITORY_ROOT / "skill-evaluator/templates/scenarios.example.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    output_schema_bytes = (
        REPOSITORY_ROOT / "skill-evaluator/templates/grader-output.schema.json"
    ).read_bytes()
    host_bytes = _host_manifest()
    generated: list[Path] = []
    skill_bindings: dict[str, dict[str, Any]] = {}
    seen_tasks: set[str] = set()
    for skill_id, config in SKILLS.items():
        relative_root = MODEL_ROOT / "sentinels" / skill_id
        target = repository_root / relative_root
        if not config["fixtures"] or any(
            Path(path).is_absolute()
            or Path(path).parts[:1] != ("fixtures",)
            or ".." in Path(path).parts
            or not isinstance(content, str)
            for path, content in config["fixtures"].items()
        ):
            raise ValueError(f"{skill_id} fixture inventory is invalid")
        fixture_payloads = {
            path: content.encode("utf-8")
            for path, content in config["fixtures"].items()
        }
        fixture_bindings = {
            path: {"path": path, "sha256": _sha256(payload)}
            for path, payload in fixture_payloads.items()
        }
        manifest_bytes = _json_bytes(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "path": Path(path).relative_to("fixtures").as_posix(),
                        "sha256": _sha256(payload),
                        "encoding": "utf-8",
                    }
                    for path, payload in sorted(fixture_payloads.items())
                ],
            }
        )
        scenarios = [
            _scenario(
                base_scenario,
                skill_id=skill_id,
                case=case,
                fixture_hash=_sha256(manifest_bytes),
                fixture_bindings=fixture_bindings,
            )
            for case in config["cases"]
        ]
        scenario_bytes = _jsonl_bytes(scenarios)
        prompt_bytes = _grader_prompt(skill_id, config["claims"])
        calibration_bytes = _calibration_gold(skill_id, config["claims"])
        verifier_bytes = (SENTINEL_SOURCE_ROOT / config["verifier_source"]).read_bytes()
        initial = {
            **{target / path: payload for path, payload in fixture_payloads.items()},
            target / "fixtures/manifest.json": manifest_bytes,
            target / "verify.py": verifier_bytes,
            target / "verify_common.py": COMMON_VERIFIER_BYTES,
            target / "grader-prompt.md": prompt_bytes,
            target / "grader-output.schema.json": output_schema_bytes,
            target / "host-manifest.template.json": host_bytes,
            target / "scenarios.public.jsonl": scenario_bytes,
            target / "calibration-gold.jsonl": calibration_bytes,
        }
        for path, payload in initial.items():
            _write(path, payload)
            generated.append(path)
        spec = _spec(
            base_spec,
            skill_id=skill_id,
            config=config,
            scenarios=scenarios,
            scenario_bytes=scenario_bytes,
            host_bytes=host_bytes,
            verifier_bytes=verifier_bytes,
            prompt_bytes=prompt_bytes,
            output_schema_bytes=output_schema_bytes,
        )
        _validate_semantics(skill_id, config, spec, scenarios, seen_tasks)
        proof = _quality_proof(
            spec,
            scenarios,
            prompt_hash=_sha256(prompt_bytes),
        )
        spec_path = target / "eval-spec.template.json"
        proof_path = target / "suite-quality-proof.json"
        quality_path = target / "suite-quality.json"
        _write(spec_path, _json_bytes(spec))
        _write(proof_path, _json_bytes(proof))
        quality_path.unlink(missing_ok=True)
        command = [
            sys.executable,
            "-B",
            str(EVALUATOR_SCRIPTS / "validate_eval_suite.py"),
            "suite-quality",
            "--spec",
            str(spec_path),
            "--proof",
            str(proof_path),
            "--output",
            str(quality_path),
        ]
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        quality_bytes = quality_path.read_bytes()
        spec["suite"]["quality"] = {
            "path": "suite-quality.json",
            "sha256": _sha256(quality_bytes),
        }
        _write(spec_path, _json_bytes(spec))
        generated.extend([spec_path, proof_path, quality_path])
        paths = {
            path.relative_to(repository_root).as_posix(): path.read_bytes()
            for path in generated
            if target in path.parents
        }
        skill_bindings[skill_id] = {
            "critical_bucket_id": f"{skill_id}-critical",
            "spec_template": _binding(
                (relative_root / "eval-spec.template.json").as_posix(),
                paths[(relative_root / "eval-spec.template.json").as_posix()],
            ),
            "public_scenarios": _binding(
                (relative_root / "scenarios.public.jsonl").as_posix(), scenario_bytes
            ),
            "calibration_gold": _binding(
                (relative_root / "calibration-gold.jsonl").as_posix(),
                calibration_bytes,
            ),
            "calibration_request_ceiling": len(calibration_bytes.splitlines()),
            "fixture_roots": [
                _binding(
                    (relative_root / "fixtures/manifest.json").as_posix(),
                    manifest_bytes,
                ),
                *[
                    _binding((relative_root / path).as_posix(), payload)
                    for path, payload in sorted(fixture_payloads.items())
                ],
            ],
            "verifier_roots": [
                _binding((relative_root / "verify.py").as_posix(), verifier_bytes),
                _binding(
                    (relative_root / "verify_common.py").as_posix(),
                    COMMON_VERIFIER_BYTES,
                ),
            ],
            "required_coverage_tags": [case["coverage"] for case in config["cases"]],
            "protected_case_ids": [
                f"{skill_id}-{case['id']}"
                for case in config["cases"]
                if case["protected"]
            ],
            "external_holdout_contract_id": f"{skill_id}-external-holdout-v1",
            "holdout_case_ceiling": 2,
        }
    fixture_bytes = _json_bytes(
        {
            "schema_version": 1,
            "marker": "frontier-model-evolution-inert-v1",
            "network": "denied",
        }
    )
    fixture_path = output_root / "probe-fixture.json"
    probes_path = output_root / "codex-interaction-probes-v1.json"
    _write(fixture_path, fixture_bytes)
    _write(
        probes_path,
        _probe_set(
            fixture_bytes,
            (REPOSITORY_ROOT / "scripts/codex_eval_host.py").read_bytes(),
        ),
    )
    sentinel = {
        "schema_version": "model-evolution-sentinel-index/1",
        "sentinel_id": "frontier-four-skill-sentinel-v1",
        "skills": skill_bindings,
        "sentinel_hash": "sha256:" + "0" * 64,
    }
    sentinel["sentinel_hash"] = canonical_self_hash(sentinel, "sentinel_hash")
    sentinel_path = output_root / "sentinel-index-v1.json"
    _write(sentinel_path, _json_bytes(sentinel))
    generated.extend([fixture_path, probes_path, sentinel_path])
    return generated


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="frontier-sentinel-check-") as temporary:
        expected_root = Path(temporary)
        expected_paths = materialize(expected_root)
        failures = []
        expected_relative = {
            path.relative_to(expected_root): path.read_bytes()
            for path in expected_paths
        }
        for relative, payload in expected_relative.items():
            actual = REPOSITORY_ROOT / relative
            if not actual.is_file() or actual.read_bytes() != payload:
                failures.append(relative.as_posix())
        actual_generated = {
            path.relative_to(REPOSITORY_ROOT)
            for root in (REPOSITORY_ROOT / MODEL_ROOT / "sentinels",)
            if root.is_dir()
            for path in root.rglob("*")
            if path.is_file()
        }
        expected_generated = {
            path for path in expected_relative if "sentinels" in path.parts
        }
        failures.extend(
            path.as_posix() for path in sorted(actual_generated - expected_generated)
        )
        if failures:
            raise SystemExit(
                "sentinel output differs: " + ", ".join(sorted(set(failures)))
            )
