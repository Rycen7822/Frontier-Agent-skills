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
)
from comparison_revision import evaluate_revision
from comparison_transition import evaluate_transition
from evidence_io import file_sha256


def _report(
    plan: dict[str, Any],
    capsules: dict[str, CycleCapsule],
    decision: dict[str, Any],
) -> dict[str, Any]:
    roles = sorted(capsules, key=ROLE_ORDER.__getitem__)
    return {
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
        "registration_status": decision["registration_status"],
        "inputs": [
            capsules[role].report_record()
            for role in roles
        ],
        "comparability_checks": decision["comparability_checks"],
        "metrics": decision["metrics"],
        "result": decision["result"],
        "authority_eligibility": decision["authority_eligibility"],
        "claim_ceiling": decision["claim_ceiling"],
        "diagnostic_index_hash": "sha256:" + "0" * 64,
    }


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
        decision, diagnostics = (
            evaluate_revision(plan_path, plan, capsules)
            if plan["kind"] == "revision"
            else evaluate_transition(plan_path, plan, capsules)
        )
        report = _report(plan, capsules, decision)
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
    outcome = decision["result"].get(
        "status",
        decision["result"].get("classification", "not_evaluable"),
    )
    print(
        f"comparison={outcome} "
        f"report={report_path.relative_to(root).as_posix()} "
        f"report_sha256={file_sha256(report_path)} "
        f"diagnostic_index={index_path.relative_to(root).as_posix()} "
        f"diagnostic_index_sha256={file_sha256(index_path)}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
