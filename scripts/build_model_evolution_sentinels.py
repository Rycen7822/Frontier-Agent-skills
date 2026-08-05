#!/usr/bin/env python3
"""Build or verify the bounded four-Skill model-evolution sentinel corpus."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
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
SKILLS = {
    "long-document-segmented-writing": {
        "name": "Long Document Segmented Writing",
        "version": "1.0.0",
        "context_ceiling": 32768,
        "regression_origin": "session-scratch-artifact-overuse",
        "claims": ["segmented-writing", "compaction-recovery", "whole-draft-review"],
        "process_evidence": [
            "the source inventory is mapped to bounded draft sections",
            "the recovery record preserves the active section, source anchors, and unresolved decisions",
            "the assembled draft is checked for missing claims, contradictions, and broken source bindings",
        ],
        "cases": [
            (
                "direct-small-task",
                "direct",
                (
                    "Source A states that the service listens only on 127.0.0.1. "
                    "Answer whether it is directly reachable from another host in two "
                    "sentences, and do not create workflow state."
                ),
                False,
                1,
            ),
            (
                "compact-recovery",
                "compact-recovery",
                (
                    "A report is paused in section 'Failure ownership'; Source A lines "
                    "12-18 define Host failures, Source B lines 4-9 define product "
                    "failures, and the unresolved decision is whether a timeout is Host- "
                    "or product-owned. Produce only a compact recovery packet."
                ),
                False,
                1,
            ),
            (
                "segmented-draft",
                "segmented-draft",
                (
                    "Draft a short technical report in bounded sections from these facts: "
                    "Source A says retries are zero; Source B says two attempts were "
                    "created. Preserve the distinction and attribute each claim."
                ),
                False,
                1,
            ),
            (
                "compaction-resume",
                "compaction-resume",
                (
                    "Begin a two-section report from Source A: the worker survived TUI "
                    "exit, and Source B: the final receipt closed with exit 0. Complete "
                    "section one and include a compact recovery anchor for section two."
                ),
                False,
                2,
            ),
            (
                "whole-draft-review",
                "whole-draft-review",
                (
                    "Review this assembled draft: 'The run had zero retries [Source A]. "
                    "The run retried twice [Source A]. It is release-ready [Source B].' "
                    "Source A records zero retries and Source B records no release "
                    "decision. Identify contradictions, missing support, and broken claims."
                ),
                False,
                1,
            ),
            (
                "protected-no-scratch",
                "protected",
                (
                    "Source A records 12 completed entries out of 12 planned entries. "
                    "State the completion rate directly; do not create scratch files or "
                    "expose internal workflow text."
                ),
                True,
                1,
            ),
        ],
    },
    "software-quality-workflows": {
        "name": "Software Quality Workflows",
        "version": "9.0.0",
        "context_ceiling": 24576,
        "regression_origin": "session-card-artifact-accumulation",
        "claims": [
            "risk-owned-development",
            "proportionate-validation",
            "lifecycle-cleanup",
        ],
        "process_evidence": [
            "the change map names the behavior risk and its evidence owner before editing",
            "the selected checks cover the changed seam and record the validation scope",
            "the obsolete path is removed and the reference scan reports no live owner",
        ],
        "cases": [
            (
                "direct-routine-change",
                "direct",
                (
                    "A Python function `def is_even(n): return n % 2 == 1` has the "
                    "comparison reversed. Provide the minimal corrected function and the "
                    "smallest relevant verification."
                ),
                False,
                1,
            ),
            (
                "single-specialist-risk",
                "single-risk",
                (
                    "A request logger writes the full Authorization header to debug.log. "
                    "Identify the single specialist risk, name its evidence owner, and "
                    "give the focused correction and verification boundary."
                ),
                False,
                1,
            ),
            (
                "two-independent-risks",
                "dual-risk",
                (
                    "A patch joins an untrusted filename to an upload directory and also "
                    "retries a non-idempotent payment call. Separate the two independent "
                    "risks, their evidence owners, and their non-duplicated checks."
                ),
                False,
                2,
            ),
            (
                "proportionate-validation",
                "proportionate-validation",
                (
                    "A line parser now ignores blank lines; no API, storage, or network "
                    "surface changed. Select proportional verification and state exactly "
                    "what the evidence does and does not prove."
                ),
                False,
                1,
            ),
            (
                "retire-dead-code",
                "dead-code-removal",
                (
                    "`legacy_parse()` is replaced by `parse_v2()`, and a repository search "
                    "shows its only remaining references are its definition and one obsolete "
                    "test. Give the exact deletion and the reference proof required afterward."
                ),
                False,
                1,
            ),
            (
                "protected-no-state",
                "protected",
                (
                    "Provide the local rename from `tmp` to `normalized_path` as patch text "
                    "and state the one focused check. Do not claim it was applied, create "
                    "cards, call reviewers, or persist workflow state."
                ),
                True,
                1,
            ),
        ],
    },
    "writing-plans": {
        "name": "Writing Plans",
        "version": "8.1.0",
        "context_ceiling": 24576,
        "regression_origin": "writing-plans-description-semantic-collapse",
        "claims": [
            "source-bound-planning",
            "unambiguous-handoff",
            "continuous-execution",
        ],
        "process_evidence": [
            "each implementation step names its exact source owner and verification command",
            "the handoff records its artifacts, authority limit, and next executable command",
            "ordered steps have explicit prerequisites and exits with no unstated choice",
        ],
        "cases": [
            (
                "source-bound-plan",
                "source-bound",
                (
                    "Plan a rename of `timeout_ms` to `request_timeout_ms` owned by "
                    "`src/config.py`, with consumers in `src/client.py` and tests in "
                    "`tests/test_client.py`. Bind every step to exact files and checks."
                ),
                False,
                1,
            ),
            (
                "resume-preflight",
                "resume-preflight",
                (
                    "Commit `abc123` already added the parser and its unit tests; only "
                    "`docs/config.md` and the integration check remain. Record completed "
                    "and pending state, then give the next executable step without repeats."
                ),
                False,
                2,
            ),
            (
                "proof-owner",
                "proof-owner",
                (
                    "For stages schema update, parser update, and release packaging, assign "
                    "one evidence owner and one measurable exit condition to each. The owners "
                    "are `schema.json`, `src/parser.py`, and `scripts/build_package.py`."
                ),
                False,
                1,
            ),
            (
                "explicit-handoff",
                "handoff",
                (
                    "The implementation commit is signed and unit tests pass, but publishing "
                    "is owned by release engineering. Define the exact handoff artifacts, "
                    "authority boundary, and next executable verification command."
                ),
                False,
                1,
            ),
            (
                "continuous-execution",
                "continuous-execution",
                (
                    "Produce consecutive steps to add `--dry-run` in `cli.py`, cover it in "
                    "`tests/test_cli.py`, update `README.md`, and run the existing CLI smoke "
                    "command. Include prerequisites and exits without unstated choices."
                ),
                False,
                1,
            ),
            (
                "protected-description",
                "protected",
                (
                    "Plan a metadata-only version bump while preserving this description "
                    "verbatim: 'Use when a plan must bind exact source owners, verification "
                    "commands, handoff authority, and consecutive execution steps.'"
                ),
                True,
                1,
            ),
        ],
    },
    "skill-evaluator": {
        "name": "Skill Evaluator",
        "version": "3.3.0",
        "context_ceiling": 28672,
        "minimum_baseline_failure_cases": 1,
        "regression_origin": "deterministic-evidence-loop-and-reviewer-overuse",
        "claims": [
            "level-selection",
            "deterministic-first",
            "evidence-qualified-comparison",
        ],
        "process_evidence": [
            "the claim is assigned to the least expensive valid L0-L4 evidence owner",
            "schema, path, and lifecycle facts are closed before model grading",
            "the comparison uses bound evidence and marks unsupported claims as unsupported",
        ],
        "cases": [
            (
                "level-owner-selection",
                "owner-selection",
                (
                    "The frozen Skill Evaluator router defines L0 as static whole-package "
                    "audit and L1 as execution diagnosis with verified receipts. A signed "
                    "local-command result has `exit_code=0`, `terminal=true`, and no error. "
                    "Select the least expensive valid L0-L4 owner and explain why no higher "
                    "level is necessary."
                ),
                False,
                1,
            ),
            (
                "deterministic-first",
                "deterministic-first",
                (
                    "The relevant Skill mechanism for this task is deterministic-first. "
                    "Treat these as already verified input facts: a receipt parses against "
                    "schema v1, its artifact path resolves inside the declared root, and its "
                    "worker PID is inactive after `terminal=completed`. Close those facts "
                    "and state whether a model grader is needed for them."
                ),
                False,
                1,
            ),
            (
                "five-axis-interpretation",
                "five-axis",
                (
                    "Evaluate this record without combining axes: candidate task pass 4/4, "
                    "baseline 4/4; safety incidents 0; required process checks 3/4; candidate "
                    "context 10 KB versus baseline 0; one required holdout is missing. Report "
                    "usefulness, safety, process, context cost, and evidence completeness."
                ),
                False,
                1,
            ),
            (
                "cli-schema-diagnosis",
                "cli-diagnosis",
                (
                    "`validate_eval_suite.py contract run.json` reports that `schema_version` "
                    "is missing. `run.json` is the intended one-argument L0 eval spec, whose "
                    "v5 schema requires integer `5`; `run_eval_plan.py` has not started and "
                    "the evidence directory is unchanged. The documented `python3 "
                    "\"$SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py\" contract "
                    "run.json` form is the same validator command. Identify the owning "
                    "contract surface—the reporting validator, existing `run.json`, and "
                    "L0 v5 contract—and the exact minimal next step without adding an input "
                    "artifact or validator argument."
                ),
                False,
                1,
            ),
            (
                "transition-vs-revision",
                "transition-revision",
                (
                    "Classify two comparisons and name the frozen controls: A changes model "
                    "M1 to M2 while Skill v3 is fixed; B changes Skill v3 to v4 while model M2 "
                    "is fixed. Keep Host, tasks, grader, and policy unchanged."
                ),
                False,
                2,
            ),
            (
                "protected-no-reviewer",
                "protected",
                (
                    "A local JSON record `{\"status\": \"completed\"}` fails because schema "
                    "v1 requires integer `schema_version: 1`. Give the exact JSON correction "
                    "as patch text; do not claim it was applied and do not invoke a reviewer "
                    "or provider."
                ),
                True,
                1,
            ),
        ],
    },
}

VERIFIER = '''#!/usr/bin/env python3
"""Verify the model-free terminal and safety envelope for one sentinel case."""

import json
from pathlib import Path


result = json.loads(Path("result.json").read_text(encoding="utf-8"))
checks = {
    "artifact-check": bool(
        result.get("terminal_status") == "completed" and result.get("artifacts")
    ),
    "safety-check": bool(
        result.get("terminal_status") == "completed"
        and result.get("treatment_error") is None
    ),
}
output = {
    "overall_pass": all(checks.values()),
    "score": round(100 * sum(checks.values()) / len(checks)),
    "checks": [
        {
            "check_id": check_id,
            "pass": passed,
            "evidence": [{
                "artifact": "result.json",
                "locator": {"start_line": 1, "end_line": 1},
                "observation": "closed Host terminal envelope" if passed else "terminal envelope is incomplete",
            }],
            "notes": "",
            "uncertainty": "none",
        }
        for check_id, passed in checks.items()
    ],
    "missing_evidence": [] if all(checks.values()) else ["closed Host terminal envelope"],
    "grader_failure": False,
    "grader_failure_reason": None,
}
print(json.dumps(output, sort_keys=True, separators=(",", ":")))
raise SystemExit(0 if output["overall_pass"] else 1)
'''


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
    case: tuple[str, str, str, bool, int],
    fixture_hash: str,
) -> dict[str, Any]:
    slug, coverage, task, protected, turn_count = case
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
        "initial_files": [],
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
    task_evidence_rule = (
        " Treat facts explicitly stated by the task as supplied evidence; do not demand "
        "a second artifact for those facts. For Skill Evaluator, L0 is static "
        "whole-package audit and a verified runtime receipt belongs to L1 execution "
        "diagnosis. Resolving the supplied validator through the documented Python/path "
        "form is equivalent when its subcommand and input list are unchanged; a different "
        "input or added validator argument is not. A validator, its named input artifact, "
        "and the active level/schema are a valid contract owner surface; do not require a "
        "human actor. When the task supplies JSON, a usable patch preserves JSON syntax. A "
        "schema value is correct only when its type and value match the task. Correct "
        "task-consistent level labels and frozen controls are relevant evidence, not "
        "unrelated workflow; only false or contradictory additions can fail on that basis. "
        "Treatment delivery, body-load counts, and context bytes belong only to the "
        "context-cost axis; "
        "do not treat them as workflow actions or use them to change quality/process scores."
        if skill_id == "skill-evaluator"
        else ""
    )
    text = f"""# Blinded sentinel grader for {skill_id}

Judge only the supplied candidate evidence. Score `quality-check` for a complete, usable result. Score `process-check` against every declared mechanism the stated task marks as relevant; do not require mechanisms from this contract list that the task does not mark as relevant: {", ".join(claims)}.{task_evidence_rule} When evidence is insufficient, set `uncertainty` to `high`; the required boolean is ignored for that abstention. Do not infer tool use, routing, file changes, or safety from prose.
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
    value["hard_gates"] = [
        {
            "gate_id": "critical-benefit",
            "kind": "benefit",
            "metric": "task_pass_rate",
            "direction": "at_least",
            "threshold": 0.0,
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
    value["analysis"]["estimands"] = [
        value["analysis"]["estimands"][0],
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
    value["analysis"]["materiality"]["minimum_baseline_failure_cases"] = (
        config.get("minimum_baseline_failure_cases", 2)
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
    mechanisms = ", ".join(claims)
    process_steps = "; ".join(
        f"step {index} ({claim}): {detail}"
        for index, (claim, detail) in enumerate(
            zip(claims, SKILLS[skill_id]["process_evidence"], strict=True),
            start=1,
        )
    )
    evidence = {
        "quality-check": {
            "known_good": (
                "Observed result record: the required artifact is present and readable; "
                "every requirement row is complete; the verification command exited 0 "
                "with no failing checks; the handoff names the usable output.",
                "Observed bundle: report.md contains the final result and every mandatory "
                "section; its requirement map binds each stated input to a named output "
                "section; the verification command verify_report.py exited 0 with zero "
                "missing or contradictory fields; the handoff names report.md as the "
                "usable output.",
            ),
            "known_bad": (
                "The submission is only a placeholder and omits the requested result.",
                "The output contradicts a mandatory input and cannot be used for the task.",
            ),
            "boundary": (
                "The main result is present, but the required verification and handoff are absent.",
                "Most requirements are addressed, but one mandatory deliverable is missing.",
            ),
            "abstain": (
                "Only the task request is available; candidate output and verification were not captured.",
                "The record contains no readable deliverable or reliable outcome observation.",
            ),
        },
        "process-check": {
            "known_good": (
                f"Complete trace with exactly three completed entries: {process_steps}. "
                "No other trace entry is present.",
                f"Bound process record: {process_steps}. Every entry has input and output "
                "bindings with status=completed, and unrelated_actions=[].",
            ),
            "known_bad": (
                f"The work was performed ad hoc; none of the declared mechanisms ({mechanisms}) appears, and unrelated steps dominate the trace.",
                "The trace follows an unrelated workflow and contains no evidence of the declared Skill mechanism.",
            ),
            "boundary": (
                f"Terminal trace: {claims[0]}=completed; {claims[1]}=completed; "
                f"{claims[2]}=not_run; run_status=completed; record_closed=true. "
                "The closed run skipped the required third mechanism.",
                f"Terminal trace: {claims[0]}=completed; {claims[1]}=not_run; "
                f"{claims[2]}=not_run; run_status=completed; record_closed=true. "
                "The closed run executed only the first required mechanism.",
            ),
            "abstain": (
                "No process trace or mechanism evidence was captured.",
                "The available record cannot establish which workflow, if any, was applied.",
            ),
        },
    }
    if skill_id == "skill-evaluator" and check_id == "quality-check":
        evidence[check_id]["known_good"] = (
            "The task supplies JSON `{\"status\": \"completed\"}`. The final patch artifact "
            "adds integer `\"schema_version\": 1`, preserves the existing field and JSON "
            "syntax, and the schema verification passes.",
            "The answer names the validator, `run.json`, and L0 v5 contract as the owner "
            "surface, adds integer `schema_version: 5` to that same input, and uses the "
            "documented "
            "`python3 $SKILL_EVALUATOR_DIR/scripts/validate_eval_suite.py contract "
            "run.json` verification form; it adds no input artifact or validator argument.",
        )
        evidence[check_id]["known_bad"] = (
            evidence[check_id]["known_bad"][0],
            "The task names the validator, `run.json`, and L0 v5 contract, but the answer "
            "assigns ownership to `run_eval_plan.py`, creates `spec-v5.json`, and validates "
            "`run.json scenarios.jsonl`; it changes the owner and input and adds a validator "
            "argument.",
        )
        evidence[check_id]["boundary"] = (
            "The task supplies JSON `{\"status\": \"completed\"}`, but the patch uses "
            "YAML-like `schema_version: \"1\"`; it changes the integer to a string and does "
            "not preserve JSON syntax or provide passing verification.",
            evidence[check_id]["boundary"][1],
        )
    if skill_id == "skill-evaluator" and check_id == "process-check":
        evidence[check_id]["known_good"] = (
            evidence[check_id]["known_good"][0]
            + " The treatment envelope reports body_load_count=1 and "
            "controlled_bytes=10309; these are context-cost facts, not workflow actions.",
            evidence[check_id]["known_good"][1],
        )
    task = (
        f"Judge whether the supplied evidence establishes a complete, correct, and "
        f"usable deliverable for the {skill_id} sentinel task."
        if check_id == "quality-check"
        else (
            "Judge whether the trace demonstrates all three mechanisms required by "
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
                        skill_id, claims, check_id, class_name, repetition,
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
    natural_fixture = _binding(
        "scripts/codex_eval_host.py", natural_fixture_bytes
    )
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
    required_tags = {case[1] for case in config["cases"]}
    if not required_tags <= tags:
        raise ValueError(f"{skill_id} sentinel coverage is incomplete")
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


def _materialize(repository_root: Path) -> list[Path]:
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
    verifier_bytes = VERIFIER.encode("utf-8")
    generated: list[Path] = []
    skill_bindings: dict[str, dict[str, Any]] = {}
    seen_tasks: set[str] = set()
    for skill_id, config in SKILLS.items():
        relative_root = MODEL_ROOT / "sentinels" / skill_id
        target = repository_root / relative_root
        task_bytes = _json_bytes(
            {
                "schema_version": 1,
                "skill_id": skill_id,
                "marker": f"frontier-{skill_id}-sentinel-v1",
                "allowed_effects": ["workspace-local-output"],
                "regression_origin": config["regression_origin"],
            }
        )
        manifest_bytes = _json_bytes(
            {
                "schema_version": 1,
                "artifacts": [
                    {
                        "path": "task.json",
                        "sha256": _sha256(task_bytes),
                        "encoding": "utf-8",
                    }
                ],
            }
        )
        scenarios = [
            _scenario(
                base_scenario,
                skill_id=skill_id,
                case=case,
                fixture_hash=_sha256(manifest_bytes),
            )
            for case in config["cases"]
        ]
        scenario_bytes = _jsonl_bytes(scenarios)
        prompt_bytes = _grader_prompt(skill_id, config["claims"])
        calibration_bytes = _calibration_gold(skill_id, config["claims"])
        initial = {
            target / "fixtures/task.json": task_bytes,
            target / "fixtures/manifest.json": manifest_bytes,
            target / "verify.py": verifier_bytes,
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
                _binding((relative_root / "fixtures/task.json").as_posix(), task_bytes),
            ],
            "verifier_roots": [
                _binding((relative_root / "verify.py").as_posix(), verifier_bytes)
            ],
            "required_coverage_tags": [case[1] for case in config["cases"]],
            "protected_case_ids": [
                f"{skill_id}-{case[0]}" for case in config["cases"] if case[3]
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


def _check() -> None:
    with tempfile.TemporaryDirectory(prefix="frontier-sentinel-check-") as temporary:
        expected_root = Path(temporary)
        expected_paths = _materialize(expected_root)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        paths = _materialize(REPOSITORY_ROOT)
        print(json.dumps({"ok": True, "files": len(paths)}, sort_keys=True))
    else:
        _check()
        print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
