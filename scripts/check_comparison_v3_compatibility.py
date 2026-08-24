#!/usr/bin/env python3
"""Replay one immutable comparison-v3 plan in isolation and compare bytes."""

from __future__ import annotations

import argparse
import copy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def _copy(source_root: Path, target_root: Path, relative: str) -> None:
    source = source_root / relative
    target = target_root / relative
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"v3 replay input is not a regular file: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _difference_paths(left: object, right: object, path: str = "") -> list[str]:
    if type(left) is not type(right):
        return [path or "/"]
    if isinstance(left, dict):
        differences: list[str] = []
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{key}"
            if key not in left or key not in right:
                differences.append(child)
            else:
                differences.extend(_difference_paths(left[key], right[key], child))
        return differences[:12]
    if isinstance(left, list):
        if len(left) != len(right):
            return [path or "/"]
        differences = []
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(_difference_paths(left_item, right_item, f"{path}/{index}"))
        return differences[:12]
    return [] if left == right else [path or "/"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--skill-id", default="skill-evaluator")
    parser.add_argument("--v4-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    source_root = args.campaign_root.resolve(strict=True)
    plan_name = f"revision-{args.skill_id}.json"
    plan = json.loads((source_root / plan_name).read_text(encoding="utf-8"))
    if plan.get("schema_version") != 3:
        raise ValueError("compatibility replay requires comparison plan v3")
    expected_root = source_root / plan["output"]["root"]
    expected = {
        plan["output"]["report"]: (expected_root / plan["output"]["report"]).read_bytes(),
        plan["output"]["diagnostic_index"]: (expected_root / plan["output"]["diagnostic_index"]).read_bytes(),
    }
    with tempfile.TemporaryDirectory(prefix="comparison-v3-replay-") as temporary:
        target_root = Path(temporary)
        _copy(source_root, target_root, plan_name)
        for record in plan["input_bindings"].values():
            capsule_path = record["capsule"]["path"]
            _copy(source_root, target_root, capsule_path)
            capsule = json.loads((source_root / capsule_path).read_text(encoding="utf-8"))
            for binding in capsule["artifacts"].values():
                if binding is not None:
                    _copy(source_root, target_root, binding["path"])
        products = plan.get("decision_policy", {}).get("bundle_products")
        if isinstance(products, dict):
            for product in products.values():
                _copy(
                    source_root,
                    target_root,
                    product["build_evidence"]["path"],
                )
        (target_root / plan["output"]["root"]).parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "skill-evaluator/scripts/compare_cycles.py"),
                str(target_root / plan_name),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        actual_root = target_root / plan["output"]["root"]
        changed = [
            name for name, payload in expected.items()
            if (actual_root / name).read_bytes() != payload
        ]
        if changed:
            details = []
            for name in changed:
                details.extend(_difference_paths(
                    json.loads(expected[name]),
                    json.loads((actual_root / name).read_bytes()),
                    f"/{name}",
                ))
            actual_index = json.loads(
                (actual_root / plan["output"]["diagnostic_index"]).read_bytes()
            )
            details.extend(
                f"reason:{row['reason_key']}" for row in actual_index["diagnostics"]
            )
            raise RuntimeError("comparison-v3 replay differs: " + ", ".join(details))
        if args.v4_diagnostic:
            shutil.rmtree(actual_root)
            v4 = copy.deepcopy(plan)
            v4["schema_version"] = 4
            v4["decision_policy"]["minimum_distinct_cases"] = 48
            v4["decision_policy"]["estimator"] = {
                "id": "paired-difference-of-differences",
                "version": "1.0.0",
                "resampling_unit": "case",
                "confidence_level": 0.95,
                "bootstrap_iterations": 10000,
                "decision_lower_percentile": 0.05,
                "diagnostic_upper_percentile": 0.95,
                "seed_derivation": "sha256-domain-separated-length-prefixed-policy-bytes-v1",
            }
            policy_source = (
                ROOT
                / "evaluation/model-evolution/confirmatory-v1/bundle-revision-policy-v2.json"
            )
            policy_relative = "confirmatory-policy-v2.json"
            shutil.copyfile(policy_source, target_root / policy_relative)
            v4["decision_policy"]["registered_policy"] = {
                "path": policy_relative,
                "schema": "frontier-bundle-revision-policy/2",
                "digest": "sha256:" + sha256(policy_source.read_bytes()).hexdigest(),
            }
            v4["output"]["root"] = f"revision-reports-v4/{args.skill_id}"
            (target_root / "revision-reports-v4").mkdir()
            (target_root / plan_name).write_text(
                json.dumps(v4, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            v4_result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/_model_evolution_comparison_v4.py"),
                    str(target_root / plan_name),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if v4_result.returncode:
                raise RuntimeError(v4_result.stderr or v4_result.stdout)
            v4_report = json.loads(
                (
                    target_root
                    / v4["output"]["root"]
                    / v4["output"]["report"]
                ).read_text(encoding="utf-8")
            )
            if (
                v4_report.get("schema_version") != 4
                or v4_report.get("result", {}).get("status") != "not_evaluable"
                or not all(
                    metric.get("evidence_completeness") == "missing"
                    for metric in v4_report.get("metrics", [])
                )
            ):
                raise RuntimeError("comparison-v4 diagnostic projection differs")
    print("comparison-v3 isolated replay is byte-identical")
    if args.v4_diagnostic:
        print("comparison-v4 isolated diagnostic validated without authority")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
