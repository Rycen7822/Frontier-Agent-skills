#!/usr/bin/env python3
"""Exercise the complete evaluator/reporting lifecycle without a provider."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

from _model_evolution_contract import (
    canonical_bytes,
    content_hash,
    evaluator_evidence_status,
    load_json,
    load_jsonl,
)
from _model_evolution_ops import OperationError, run_model_free_command
from _model_evolution_reporting import (
    _artifact,
    _bundle_revision_plan,
    _cycle_capsule,
)


FIXTURE_FILES = (
    "grader-output.schema.json",
    "host-manifest-v2.json",
    "scenarios-v1.jsonl",
    "spec-v7.json",
    "suite-quality-proof.json",
    "suite-quality-v2.json",
    "synthetic-host.py",
)


def _materialize(repository_root: Path, target: Path) -> dict[str, Path]:
    source = repository_root / "evaluation/fixtures/skill-evaluator"
    if target.exists() and any(target.iterdir()):
        raise OperationError("evaluator fixture target is not empty")
    target.mkdir(parents=True, exist_ok=True)
    for name in FIXTURE_FILES:
        path = source / name
        if not path.is_file() or path.is_symlink():
            raise OperationError(f"evaluator fixture is missing or unsafe: {name}")
        shutil.copy2(path, target / name)
    return {
        "spec": target / "spec-v7.json",
        "scenarios": target / "scenarios-v1.jsonl",
        "host": target / "host-manifest-v2.json",
    }


def _bind_identity(
    paths: dict[str, Path],
    *,
    revision: str,
    package_digest: str,
    skill_version: str,
) -> None:
    spec = load_json(paths["spec"], label="fake identity spec")
    spec["subject"]["version"] = skill_version
    spec["subject"]["package"].update(
        source_revision=revision,
        package_digest=package_digest,
    )
    for grader in spec["graders"]:
        if grader["type"] == "deterministic":
            grader["verifier"]["source_revision"] = revision
    paths["spec"].write_bytes(canonical_bytes(spec))
    host = load_json(paths["host"], label="fake identity Host")
    host["identity"]["repository"].update(revision=revision, tree=revision)
    host["catalog"]["entries"][0].update(
        version=skill_version,
        root_digest=package_digest,
    )
    paths["host"].write_bytes(canonical_bytes(host))
    scenarios = load_jsonl(paths["scenarios"], label="fake identity scenarios")
    for scenario in scenarios:
        scenario["fixture"]["sha256"] = content_hash(paths["host"].read_bytes())
    paths["scenarios"].write_bytes(
        b"".join(canonical_bytes(row) + b"\n" for row in scenarios)
    )


def _run_cycle(
    repository_root: Path,
    root: Path,
    operations: list[dict[str, Any]],
    *,
    role: str,
    revision: str,
    package_digest: str,
    skill_version: str,
) -> dict[str, Any]:
    cycle_root = root / role
    paths = _materialize(repository_root, cycle_root)
    _bind_identity(
        paths,
        revision=revision,
        package_digest=package_digest,
        skill_version=skill_version,
    )
    plan = cycle_root / "plan.json"
    fact, _ = run_model_free_command(
        f"fake-{role}-compile",
        [
            sys.executable,
            "skill-evaluator/scripts/compile_eval_plan.py",
            str(paths["spec"]),
            str(paths["scenarios"]),
            str(paths["host"]),
            "--output",
            str(plan),
        ],
        repository_root=repository_root,
    )
    operations.append(fact)
    compiled = load_json(plan, label=f"fake {role} plan")
    index = cycle_root / compiled["artifacts"]["root"] / compiled["artifacts"][
        "index_relpath"
    ]
    fact, result = run_model_free_command(
        f"fake-{role}-status",
        [
            sys.executable,
            "skill-evaluator/scripts/run_eval_plan.py",
            str(plan),
            "--index",
            str(index),
            "--status",
        ],
        repository_root=repository_root,
    )
    operations.append(fact)
    status = json.loads(result.stdout)
    fact, _ = run_model_free_command(
        f"fake-{role}-run",
        [
            sys.executable,
            "skill-evaluator/scripts/run_eval_plan.py",
            str(plan),
            "--index",
            str(index),
            "--new-attempt-budget",
            str(status["next_pass_new_attempts"]),
        ],
        repository_root=repository_root,
    )
    operations.append(fact)
    summary = cycle_root / "summary.json"
    failures = cycle_root / "failure-index.json"
    fact, _ = run_model_free_command(
        f"fake-{role}-analyze",
        [
            sys.executable,
            "skill-evaluator/scripts/analyze_runs.py",
            str(index),
            "--spec",
            str(paths["spec"]),
            "--json",
            str(summary),
            "--failure-index",
            str(failures),
        ],
        repository_root=repository_root,
        acceptable={0, 1, 3},
    )
    operations.append(fact)
    bundle_version = "7.0.0" if role == "prior" else "8.0.0"
    product = {
        "bundle_id": f"frontier-engineering/{bundle_version}",
        "bundle_version": bundle_version,
        "source_revision": revision,
        "source_tree_hash": "sha256:" + revision[0] * 64,
        "plugin_tree_hash": "sha256:" + package_digest[-1] * 64,
        "skills": {
            "skill-evaluator": {
                "version": skill_version,
                "root_hash": package_digest,
                "allow_implicit_invocation": False,
            }
        },
    }
    build = cycle_root / "plugin-build.json"
    build.write_bytes(canonical_bytes({
        "schema_version": "plugin-build-evidence/4.0",
        "source_revision": product["source_revision"],
        "source_tree_hash": product["source_tree_hash"],
        "plugin_tree_hash": product["plugin_tree_hash"],
        "bundle_id": product["bundle_id"],
        "bundle_version": product["bundle_version"],
        "skill_versions": {"skill-evaluator": skill_version},
        "skill_activation": {"skill-evaluator": False},
        "output_class": "staging",
    }))
    product["build_evidence"] = _artifact(
        build, root, "plugin-build-evidence/4.0"
    )
    return {
        "paths": paths,
        "plan": plan,
        "summary": summary,
        "failures": failures,
        "product": product,
    }


def run_fake_full_chain(repository_root: Path) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="frontier-model-evolution-preflight-"
    ) as raw:
        root = Path(raw)
        cycles = {
            "prior": _run_cycle(
                repository_root,
                root,
                operations,
                role="prior",
                revision="1" * 40,
                package_digest="sha256:" + "2" * 64,
                skill_version="5.0.0",
            ),
            "candidate": _run_cycle(
                repository_root,
                root,
                operations,
                role="candidate",
                revision="3" * 40,
                package_digest="sha256:" + "4" * 64,
                skill_version="6.0.0",
            ),
        }
        capsule_values: dict[str, tuple[Path, dict[str, Any]]] = {}
        for role, record in cycles.items():
            capsule = _cycle_capsule(
                campaign_root=root,
                role=role,
                cycle_id=f"fake-{role}",
                spec_path=record["paths"]["spec"],
                host_path=record["paths"]["host"],
                plan_path=record["plan"],
                summary_path=record["summary"],
                failure_path=record["failures"],
            )
            path = root / f"{role}-capsule.json"
            path.write_bytes(canonical_bytes(capsule))
            capsule_values[role] = (path, capsule)
        comparison = _bundle_revision_plan(
            campaign_root=root,
            comparison_id="fake-bundle-revision",
            registered_at="2026-08-13T00:00:00Z",
            authority_id="fixture-owner",
            capsules=capsule_values,
            products={role: record["product"] for role, record in cycles.items()},
            policy_digest="sha256:" + "5" * 64,
            change_paths=["skill-evaluator"],
            metric_rules=[{
                "purpose": "protected_noninferiority",
                "metric_id": "task-benefit",
                "direction": "higher_is_better",
                "margin": 0.0,
            }],
            minimum_distinct_cases=2,
            required_axes=["task_behavior"],
            output_root="revision-output",
        )
        plan_path = root / "comparison-plan.json"
        plan_path.write_bytes(canonical_bytes(comparison))
        fact, _ = run_model_free_command(
            "fake-bundle-comparison",
            [
                sys.executable,
                "skill-evaluator/scripts/compare_cycles.py",
                str(plan_path),
            ],
            repository_root=repository_root,
        )
        operations.append(fact)
        report = root / "revision-output/comparison-report.json"
        if evaluator_evidence_status(report, kind="revision_report") != "pass":
            value = load_json(report, label="fake Bundle revision report")
            raise OperationError(
                f"fake Bundle revision report did not close: {value['result']['status']}"
            )
    return operations
