from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skill-evaluator"
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

from comparison_contract import CycleCapsule  # noqa: E402
from _model_evolution_comparison_v4 import metric_result as v4_metric_result  # noqa: E402
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
READY_FIXTURES = (
    "grader-output.schema.json",
    "host-manifest-v2.json",
    "scenarios-v1.jsonl",
    "spec-v7.json",
    "suite-quality-proof.json",
    "suite-quality-v2.json",
    "synthetic-host.py",
)


def run_script(relative: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative), *arguments],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


class ExtendedSkillEvaluator(unittest.TestCase):
    @staticmethod
    def _v4_capsule(role: str, values: dict[str, float], *, bounds=(-0.1, 0.2), estimand="task-benefit") -> CycleCapsule:
        case_ids = sorted(values)
        return CycleCapsule(
            role=role,
            cycle_id=f"cycle-{role}",
            capsule_digest="sha256:" + "1" * 64,
            spec={
                "analysis": {
                    "confidence_level": 0.95,
                    "bootstrap_iterations": 10000,
                    "resampling_unit": "case",
                    "estimands": [{
                        "estimand_id": estimand,
                        "metric": "task-benefit",
                        "direction": "higher_is_better",
                        "effect": "absolute",
                        "minimum_benefit": 0.0,
                    }],
                }
            },
            execution_plan={
                "entries": [
                    {"case_id": case_id, "disposition": "execute"}
                    for case_id in case_ids
                ]
            },
            host_manifest={},
            summary={
                "paired_metrics": {
                    "task-benefit": {
                        "status": "inconclusive_ceiling",
                        "direction": "higher_is_better",
                        "effect": "absolute",
                        "point": sum(values.values()) / len(values),
                        "lower": bounds[0],
                        "upper": bounds[1],
                        "case_count": len(values),
                        "excluded_pairs": 0,
                        "case_differences": values,
                    }
                }
            },
            failure_index=None,
            observations=None,
            paths={"summary": None},
            source_refs={"summary": f"{role}-summary.json"},
            artifact_digests={"summary": None},
        )

    @staticmethod
    def _v4_plan() -> dict:
        return {
            "decision_policy": {
                "minimum_distinct_cases": 48,
                "estimator": {
                    "id": "paired-difference-of-differences",
                    "version": "1.0.0",
                    "resampling_unit": "case",
                    "confidence_level": 0.95,
                    "bootstrap_iterations": 10000,
                    "decision_lower_percentile": 0.05,
                    "diagnostic_upper_percentile": 0.95,
                    "seed_derivation": "sha256-domain-separated-length-prefixed-policy-bytes-v1",
                },
            }
        }

    def test_v4_complete_evidence_is_independent_of_absolute_decision(self) -> None:
        cases = {f"confirmatory-case-{index:02d}": 0.0 for index in range(48)}
        prior = self._v4_capsule("prior", cases)
        candidate = self._v4_capsule(
            "candidate", {case_id: 0.1 for case_id in cases}
        )
        rule = {
            "metric_id": "task-benefit",
            "purpose": "protected_noninferiority",
            "direction": "higher_is_better",
            "margin": 0.0,
        }
        first, diagnostics = v4_metric_result(self._v4_plan(), prior, candidate, rule)
        second, _ = v4_metric_result(self._v4_plan(), prior, candidate, rule)
        self.assertEqual([], diagnostics)
        self.assertEqual("complete", first["evidence_completeness"])
        self.assertEqual("inconclusive", first["absolute_threshold_decision"])
        self.assertEqual("pass", first["revision_decision"])
        self.assertEqual(first, second)
        shifted = {f"confirmatory-shifted-{index:02d}": 0.0 for index in range(48)}
        shifted_result, _ = v4_metric_result(
            self._v4_plan(),
            self._v4_capsule("prior", shifted),
            self._v4_capsule("candidate", {case_id: 0.1 for case_id in shifted}),
            rule,
        )
        self.assertNotEqual(
            first["estimator"]["seed"], shifted_result["estimator"]["seed"]
        )

    def test_v4_rejects_missing_mismatched_and_regressed_evidence(self) -> None:
        cases = {f"confirmatory-case-{index:02d}": 0.0 for index in range(48)}
        prior = self._v4_capsule("prior", cases)
        rule = {
            "metric_id": "task-benefit",
            "purpose": "protected_noninferiority",
            "direction": "higher_is_better",
            "margin": 0.0,
        }
        missing = self._v4_capsule("candidate", cases)
        missing.summary["paired_metrics"]["task-benefit"]["lower"] = None
        result, _ = v4_metric_result(self._v4_plan(), prior, missing, rule)
        self.assertEqual("missing", result["evidence_completeness"])
        self.assertEqual("not_evaluable", result["revision_decision"])

        mismatch = self._v4_capsule("candidate", cases, estimand="different")
        result, _ = v4_metric_result(self._v4_plan(), prior, mismatch, rule)
        self.assertEqual("missing", result["evidence_completeness"])

        regression = self._v4_capsule(
            "candidate", {case_id: -0.1 for case_id in cases}
        )
        result, _ = v4_metric_result(self._v4_plan(), prior, regression, rule)
        self.assertEqual("complete", result["evidence_completeness"])
        self.assertEqual("fail", result["revision_decision"])

    def test_comparison_dispatch_rejects_unknown_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text('{"schema_version":99}\n', encoding="utf-8")
            result = run_script("scripts/_model_evolution_comparison_v4.py", str(plan))
        self.assertEqual(2, result.returncode)
        self.assertIn("comparison error", result.stderr)

    def test_invalid_contract_is_rejected(self) -> None:
        base = json.loads(
            (SKILL / "templates" / "eval-spec.example.json").read_text(encoding="utf-8")
        )
        base["unexpected"] = True
        with tempfile.TemporaryDirectory() as directory:
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(base), encoding="utf-8")
            result = run_script(
                "skill-evaluator/scripts/validate_eval_suite.py",
                "contract",
                str(spec_path),
                str(SKILL / "templates" / "scenarios.example.jsonl"),
                str(SKILL / "templates" / "host-manifest.example.json"),
                "--json",
                "-",
            )
        self.assertEqual(1, result.returncode)
        self.assertIn(
            "schema.additionalProperties",
            {error["code"] for error in json.loads(result.stdout)["errors"]},
        )

    def test_compile_run_and_analyze_public_lifecycle(self) -> None:
        fixture_root = ROOT / "evaluation" / "fixtures" / "skill-evaluator"
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in READY_FIXTURES:
                shutil.copy2(fixture_root / name, work / name)

            plan = work / "plan.json"
            compiled = run_script(
                "skill-evaluator/scripts/compile_eval_plan.py",
                str(work / "spec-v7.json"),
                str(work / "scenarios-v1.jsonl"),
                str(work / "host-manifest-v2.json"),
                "--output",
                str(plan),
            )
            self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)
            plan_value = json.loads(plan.read_text(encoding="utf-8"))
            self.assertEqual(3, plan_value["schema_version"])
            self.assertEqual(
                {"execute": 4, "not_evaluable": 0, "total": 4, "unsupported": 0},
                plan_value["expected_counts"],
            )

            index = work / "artifacts" / "index.jsonl"
            executed = run_script(
                "skill-evaluator/scripts/run_eval_plan.py",
                str(plan),
                "--index",
                str(index),
                "--new-attempt-budget",
                "4",
            )
            self.assertEqual(0, executed.returncode, executed.stdout + executed.stderr)

            summary = work / "summary.json"
            failures = work / "failures.json"
            analyzed = run_script(
                "skill-evaluator/scripts/analyze_runs.py",
                str(index),
                "--spec",
                str(work / "spec-v7.json"),
                "--json",
                str(summary),
                "--failure-index",
                str(failures),
            )
            self.assertEqual(3, analyzed.returncode, analyzed.stdout + analyzed.stderr)
            summary_value = json.loads(summary.read_text())
            self.assertEqual(6, summary_value["schema_version"])
            self.assertEqual("complete", summary_value["evidence_status"])
            self.assertEqual("inconclusive_ceiling", summary_value["usefulness_status"])
            self.assertTrue(summary_value["baseline_ceiling"])
            self.assertEqual(4, len(list(work.glob("artifacts/entries/*/attempt-0001/receipt.json"))))
            self.assertEqual([], list(work.glob("artifacts/entries/*/attempt-0002")))


if __name__ == "__main__":
    unittest.main()
