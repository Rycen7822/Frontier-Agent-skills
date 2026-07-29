"""Materialize the dynamic Writing Plans transfer study from planner receipts."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from . import artifacts, host_contract, specs, studies


def _runtime(host: dict[str, Any]) -> dict[str, dict[str, str]]:
    argv = host["command"]["argv"]
    try:
        path = argv[argv.index("--codex-bin") + 1]
        digest = argv[argv.index("--codex-bin-sha256") + 1]
    except (ValueError, IndexError):
        raise ValueError("planner host lacks a bound Codex runtime") from None
    return {"executable": {"path": path, "sha256": digest}}


def _materialize_case(
    root: Path,
    case: specs.CaseDefinition,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    if case.files:
        raise ValueError("transfer case must source files from planner bindings")
    fixture = root / "fixtures" / case.case_id
    fixture.mkdir(parents=True)
    contract_path = fixture / "case.contract.json"
    artifacts.write_json(contract_path, {
        "schema_version": "frontier-case-contract/1.0",
        "read_only": case.read_only,
        "allowed_change_paths": list(case.allowed_change_paths),
        "expected_change_paths": list(case.expected_change_paths),
        "protected_paths": list(case.protected_paths),
        "content_requirements": case.content_requirements,
        "verification_argv": (
            list(case.verification_argv)
            if case.verification_argv is not None
            else None
        ),
        "transfer_source": case.transfer_source,
    })
    contract = artifacts.artifact_binding(contract_path, root)
    return [contract], contract


def _run(arguments: list[str], root: Path, output: Path) -> None:
    completed = subprocess.run(
        arguments,
        cwd=root,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    if completed.returncode or not output.is_file() or output.is_symlink():
        diagnostic = (completed.stderr or completed.stdout).strip()[:2000]
        raise RuntimeError(
            f"Skill Evaluator producer failed ({completed.returncode}): "
            f"{diagnostic}"
        )


def _spec(
    *,
    root: Path,
    evaluator: Path,
    design: specs.StudyDesign,
    planner_spec: dict[str, Any],
    host: dict[str, Any],
    scenarios: list[dict[str, Any]],
    validator: Any,
) -> dict[str, Any]:
    template = artifacts.json_object(
        (evaluator / "templates/eval-spec.example.json").read_bytes(),
        "evaluation spec template",
    )
    treatments = studies.treatment_records(
        template=template,
        design=design,
        candidate_hash=planner_spec["subject"]["package"]["package_hash"],
        prior_hash=None,
        host_manifest=host,
    )
    template["analysis"].update({
        "confidence_level": 0.90,
        "bootstrap_iterations": 10000,
        "materiality": {"minimum_baseline_failure_cases": len(scenarios)},
    })
    scenario_path = root / "scenarios-v1.jsonl"
    artifacts.atomic_write(
        scenario_path,
        b"".join(
            artifacts.canonical_bytes(row) + b"\n" for row in scenarios
        ),
        replace=False,
    )
    graders = copy.deepcopy([
        grader
        for grader in planner_spec["graders"]
        if grader["type"] == "deterministic"
    ])
    if len(graders) != 1:
        raise ValueError("planner deterministic grader inventory differs")
    graders[0]["verifier"]["sha256"] = artifacts.file_hash(
        root / "host/host_grader.py"
    )
    graders[0]["checks"].extend({
        "check_id": check_id,
        "dimension": dimension,
        "required": True,
        "pass_condition": "The bound transfer contract passes.",
    } for _, check_id, dimension in studies.TRANSFER_REQUIREMENTS)
    graders[0]["verifier"]["argv"][2] = "--checks=" + ",".join(
        item["check_id"] for item in graders[0]["checks"]
    )
    package = planner_spec["subject"]["package"]
    template.update({
        "evaluation_id": design.study_id,
        "level": design.level,
        "subject": {
            **planner_spec["subject"],
            "package": {
                **package,
                "path": f"candidate/{design.skill_id}",
            },
        },
        "applicability": studies.applicability_records(
            template,
            design=design,
        ),
        "treatments": treatments,
        "host": {
            "manifest": artifacts.artifact_binding(
                root / "host-manifest-v1.json",
                root,
            ),
            "required_capabilities": sorted({
                capability
                for treatment in treatments
                for capability in treatment["expected_capabilities"]
            }),
        },
        "graders": graders,
        "suite": {
            **template["suite"],
            "scenarios": artifacts.artifact_binding(scenario_path, root),
            "public_scenarios": artifacts.artifact_binding(
                scenario_path,
                root,
            ),
            "holdout": None,
            "fixture_set_hash": validator.v5_fixture_set_hash(scenarios),
            "grader_set_hash": validator.v5_grader_set_hash(graders),
            "treatment_contract_hash": (
                validator.v5_treatment_contract_hash(treatments)
            ),
            "quality": {
                "path": "suite-quality-v1.json",
                "sha256": "sha256:" + "0" * 64,
            },
            "repeats": design.repeats,
            "order_seed": 20260725,
            "reset_policy": "fresh-workspace",
            "retry_policy": "apparatus-only",
        },
        "execution": {
            **planner_spec["execution"],
            "mode": "diagnostic" if design.level == "L1" else "scored",
            "ready": False,
        },
        "authority": planner_spec["authority"],
        "decision": planner_spec["decision"],
    })
    template["suite"]["grader_schedule_hash"] = (
        validator.v5_grader_schedule_hash(template, scenarios)
    )
    template["suite"]["quality_contract_hash"] = (
        validator.quality_contract_hash(template)
    )
    return template


def materialize(
    *,
    planner_root: Path,
    output_root: Path,
    evaluator_root: Path,
    validator: Any,
) -> dict[str, Any]:
    if output_root.exists() or output_root.is_symlink():
        raise ValueError("transfer output root must be absent")
    planner_spec = artifacts.load_json(planner_root / "eval-spec-v5.json")
    planner_host = artifacts.load_json(planner_root / "host-manifest-v1.json")
    design = studies.transfer_design(
        "d0-writing-plans-transfer",
        planner_root,
    )
    output_root.mkdir(parents=True)
    shutil.copytree(planner_root / "candidate", output_root / "candidate")
    package = planner_spec["subject"]["package"]
    host = host_contract.materialize(
        study_root=output_root,
        evaluator_root=evaluator_root,
        candidate_skill=(
            output_root / f"candidate/{design.skill_id}/SKILL.md"
        ),
        prior_skill=None,
        package_hash=package["package_hash"],
        repository={
            "revision": package["repository_revision"],
            "tree": package["repository_tree"],
        },
        design=design,
        codex_runtime=_runtime(planner_host),
        controller_content_hash=planner_host["identity"]["host_build"],
    )
    artifacts.write_json(output_root / "host-manifest-v1.json", host)
    scenario_template = artifacts.json_object(
        (
            evaluator_root / "templates/scenarios.example.jsonl"
        ).read_bytes().splitlines()[0],
        "scenario template",
    )
    scenarios = []
    host_binding = artifacts.artifact_binding(
        output_root / "host-manifest-v1.json",
        output_root,
    )
    for case in design.cases:
        files, contract = _materialize_case(output_root, case)
        scenarios.append(studies.scenario_from_case(
            template=scenario_template,
            case=case,
            fixture_files=files,
            contract_binding=contract,
            host_binding=host_binding,
            profiles=list(case.applicable_profiles),
            skill_id=design.skill_id,
        ))
    spec = _spec(
        root=output_root,
        evaluator=evaluator_root,
        design=design,
        planner_spec=planner_spec,
        host=host,
        scenarios=scenarios,
        validator=validator,
    )
    draft = output_root / "eval-spec-v5.draft.json"
    artifacts.write_json(draft, spec)
    proof = output_root / "suite-quality-proof.json"
    artifacts.write_json(
        proof,
        studies.quality_proof(
            spec=spec,
            scenarios=scenarios,
            study_root=output_root,
            validator=validator,
        ),
    )
    quality = output_root / "suite-quality-v1.json"
    _run([
        "python3",
        str(evaluator_root / "scripts/validate_eval_suite.py"),
        "suite-quality",
        "--spec", str(draft),
        "--proof", str(proof),
        "--output", str(quality),
    ], output_root, quality)
    ready = copy.deepcopy(spec)
    ready["execution"]["ready"] = True
    ready["suite"]["quality"]["sha256"] = artifacts.file_hash(quality)
    spec_path = output_root / "eval-spec-v5.json"
    artifacts.write_json(spec_path, ready)
    validation = output_root / "contract-validation.json"
    _run([
        "python3",
        str(evaluator_root / "scripts/validate_eval_suite.py"),
        "contract",
        str(spec_path),
        str(output_root / "scenarios-v1.jsonl"),
        str(output_root / "host-manifest-v1.json"),
        "--json", str(validation),
        "--strict",
    ], output_root, validation)
    plan = output_root / "execution-plan-v1.json"
    _run([
        "python3",
        str(evaluator_root / "scripts/compile_eval_plan.py"),
        str(spec_path),
        str(output_root / "scenarios-v1.jsonl"),
        str(output_root / "host-manifest-v1.json"),
        "--output", str(plan),
    ], output_root, plan)
    compiled = artifacts.json_object(plan.read_bytes(), plan)
    return {"plan_hash": compiled["plan_hash"], "provider_requests": 0}
