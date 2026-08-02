#!/usr/bin/env python3
"""Compare two or three closed Skill Evaluator cycle capsules."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

from comparison_contract import (
    ContractError,
    CycleCapsule,
    ROLE_ORDER,
    commit_outputs,
    load_comparison_plan,
    load_cycle_capsules,
    make_diagnostic,
)
from evidence_io import file_sha256


def _structural_result(
    plan_path: Path,
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    roles = sorted(capsules, key=ROLE_ORDER.__getitem__)
    pending = make_diagnostic(
        severity="medium",
        fact_type="evidence_gap",
        reason_key="policy_evaluation_pending",
        roles=roles,
        expected="the applicable comparison policy is mechanically evaluated",
        observed="cycle capsules are valid; policy evaluation is not implemented",
        locator_artifact=plan_path.name,
        json_pointer="/decision_policy",
        source_hash=file_sha256(plan_path),
    )
    if plan["kind"] == "revision":
        result = {
            "kind": "revision",
            "status": "not_evaluable",
            "target_failure_class": plan["decision_policy"]["target"][
                "failure_class"
            ],
            "closed_diagnostic_ids": [],
            "remaining_diagnostic_ids": plan["decision_policy"]["target"][
                "diagnostic_ids"
            ],
        }
    else:
        result = {
            "kind": "model_transition",
            "mode": plan["decision_policy"]["mode"],
            "classification": "apparatus_inconclusive",
            "classification_metric_ids": [],
        }
    report = {
        "schema_version": 1,
        "comparison_report_hash": "sha256:" + "0" * 64,
        "comparison_id": plan["comparison_id"],
        "comparison_plan_hash": plan["comparison_plan_hash"],
        "kind": plan["kind"],
        "claim_scope": plan["claim_scope"],
        "generator": {
            "name": "compare_cycles.py",
            "version": "3.1.0",
            "source_hash": file_sha256(Path(__file__)),
        },
        "registration_status": (
            "declared_pre_registered"
            if plan["registration"]["mode"] == "pre_registered"
            else "exploratory"
        ),
        "inputs": [
            capsules[role].report_record()
            for role in roles
        ],
        "comparability_checks": [
            {
                "check_id": "capsule-bindings",
                "status": "pass",
                "roles": roles,
                "diagnostic_ids": [],
            },
            {
                "check_id": "policy-evaluation",
                "status": "not_evaluable",
                "roles": roles,
                "diagnostic_ids": [pending["diagnostic_id"]],
            },
        ],
        "metrics": [],
        "result": result,
        "authority_eligibility": "blocked",
        "claim_ceiling": "diagnostic_only",
        "diagnostic_index_hash": "sha256:" + "0" * 64,
    }
    return report, [pending]


def _bounded_error(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= 320 else text[:317] + "..."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    args = parser.parse_args(argv)
    try:
        plan_path, plan, registry = load_comparison_plan(args.plan)
        capsules = load_cycle_capsules(plan_path, plan, registry)
        report, diagnostics = _structural_result(
            plan_path,
            plan,
            capsules,
        )
        report_path, index_path = commit_outputs(
            plan_path,
            plan,
            report,
            diagnostics,
            registry,
        )
    except ContractError as exc:
        print(
            f"comparison error [{exc.code}]: {_bounded_error(exc)}",
            file=sys.stderr,
        )
        return 2
    except (FileExistsError, OSError, KeyError, TypeError, ValueError) as exc:
        print(
            f"comparison error [comparison.failure]: {_bounded_error(exc)}",
            file=sys.stderr,
        )
        return 2

    root = plan_path.parent
    print(
        "comparison=not_evaluable "
        f"report={report_path.relative_to(root).as_posix()} "
        f"report_sha256={file_sha256(report_path)} "
        f"diagnostic_index={index_path.relative_to(root).as_posix()} "
        f"diagnostic_index_sha256={file_sha256(index_path)}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
