"""Validate the code-review evaluation inputs without running a model."""

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
EVALUATOR_SCRIPTS = ROOT / "skills" / "skill-evaluator" / "scripts"
if str(EVALUATOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_SCRIPTS))

import author_suite  # noqa: E402

SUITE_ROOT = ROOT / "evaluation" / "review-v11"
FIXTURES = SUITE_ROOT / "fixtures"
REVIEW_CATALOG = {"catalog": {"entries": [{"id": "code-review"}]}}
EXPECTED_CASE_IDS = [f"RV{index:02d}" for index in range(1, 13)]
CACHE_SIZE_REPAIR_CASE = "RV11"
GRADER_ID = "review-quality"
CHECK_DIMENSIONS = {"outcome": "outcome", "evidence": "quality", "scope_safety": "safety"}


def run_fixture_tests(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "unittest", "test_module.py", "-v"],
        cwd=directory,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class CodeReviewEvaluationSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.author = json.loads((SUITE_ROOT / "author-suite.json").read_text(encoding="utf-8"))
        cls.suite = author_suite.normalize(cls.author, REVIEW_CATALOG, SUITE_ROOT)

    def test_suite_declares_expected_treatments_and_grader(self) -> None:
        self.assertEqual("code-review", self.suite["skill_id"])
        self.assertEqual(1, self.suite["repeats"])
        self.assertEqual(
            {
                "baseline": "baseline/skill_disabled",
                "forced": "candidate/force_loaded",
                "natural": "candidate/natural_routing",
            },
            {item["treatment_id"]: item["profile"] for item in self.suite["treatments"]},
        )
        self.assertEqual(1, len(self.suite["graders"]))
        grader = self.suite["graders"][0]
        self.assertEqual(GRADER_ID, grader["grader_id"])
        self.assertEqual("model", grader["type"])
        self.assertEqual("rubric.md", grader["prompt_template"]["path"])
        self.assertEqual(
            CHECK_DIMENSIONS,
            {check["check_id"]: check["dimension"] for check in grader["checks"]},
        )
        for check in grader["checks"]:
            self.assertTrue(check["required"], check["check_id"])

    def test_cases_bind_required_checks_and_their_own_fixtures(self) -> None:
        cases = self.suite["cases"]
        self.assertEqual(EXPECTED_CASE_IDS, [case["case_id"] for case in cases])
        for case in cases:
            case_id = case["case_id"]
            with self.subTest(case=case_id):
                self.assertEqual(
                    list(CHECK_DIMENSIONS), [item["check_id"] for item in case["requirements"]]
                )
                for requirement in case["requirements"]:
                    self.assertEqual(GRADER_ID, requirement["grader_id"])
                    self.assertTrue(requirement["required"], requirement["check_id"])

                self.assertEqual(1, len(case["turns"]))
                task = case["turns"][0]["input"]
                self.assertEqual("user_message", task["kind"])
                self.assertNotIn("$code-review", task["content"])

                files = case["fixture"]["initial_files"]
                self.assertTrue(files)
                case_dir = Path("fixtures") / case_id
                for binding in files:
                    path = Path(binding["path"])
                    self.assertTrue(path.is_relative_to(case_dir), path)
                    self.assertNotEqual("rubric.md", path.name)

    def test_fixture_seeds_compile_without_writing_caches(self) -> None:
        self.assertEqual(EXPECTED_CASE_IDS, sorted(path.name for path in FIXTURES.iterdir()))
        for path in sorted(FIXTURES.rglob("*.py")):
            with self.subTest(fixture=path.relative_to(FIXTURES)):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
        self.assertFalse(any(FIXTURES.rglob("__pycache__")))

    def test_suite_has_zero_execution_budgets_and_no_run_artifacts(self) -> None:
        self.assertEqual(
            {"task_attempt_budget": 0, "judge_invocation_budget": 0, "timeout_seconds": 300},
            self.suite["constraints"],
        )
        self.assertFalse((SUITE_ROOT / "host.json").exists())
        self.assertFalse((SUITE_ROOT / "run").exists())

    def test_normalization_rejects_catalog_without_review_skill(self) -> None:
        with self.assertRaisesRegex(ValueError, "skill must occur exactly once in the Host catalog"):
            author_suite.normalize(self.author, {"catalog": {"entries": []}}, SUITE_ROOT)

    def test_cache_size_fixture_preserves_zero_after_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "fixture"
            shutil.copytree(FIXTURES / CACHE_SIZE_REPAIR_CASE, workspace)

            before = run_fixture_tests(workspace)
            self.assertEqual(1, before.returncode, before.stdout + before.stderr)
            self.assertIn("FAIL: test_zero_is_preserved", before.stderr)

            module = workspace / "module.py"
            source = module.read_text(encoding="utf-8")
            module.write_text(
                source.replace("return size or 64", "return 64 if size is None else size"),
                encoding="utf-8",
            )
            after = run_fixture_tests(workspace)
            self.assertEqual(0, after.returncode, after.stdout + after.stderr)

    def test_rubric_covers_each_case_without_copying_fixture_snippets(self) -> None:
        rubric = (SUITE_ROOT / "rubric.md").read_text(encoding="utf-8")
        for case_id in EXPECTED_CASE_IDS:
            self.assertIn(f"| {case_id} |", rubric)
        for path in sorted(FIXTURES.rglob("*")):
            if path.is_file():
                body = path.read_text(encoding="utf-8")
                longest = max((line.strip() for line in body.splitlines()), key=len, default="")
                if longest:
                    with self.subTest(fixture=path.relative_to(FIXTURES)):
                        self.assertNotIn(longest, rubric)


if __name__ == "__main__":
    unittest.main()
