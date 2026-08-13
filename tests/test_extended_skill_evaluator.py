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
