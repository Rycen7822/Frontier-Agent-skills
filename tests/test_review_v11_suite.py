"""E01-E03: local validation of the prepared code-review evaluation inputs."""

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
EVALUATOR_SCRIPTS = ROOT / "skill-evaluator" / "scripts"
if str(EVALUATOR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(EVALUATOR_SCRIPTS))

import author_suite  # noqa: E402

SUITE_ROOT = ROOT / "evaluation" / "review-v11"
SUITE_PATH = SUITE_ROOT / "author-suite.json"
STUB_HOST = {"catalog": {"entries": [{"id": "code-review"}]}}
CASE_IDS = [f"RV{index:02d}" for index in range(1, 13)]
EXPECTED_PROFILES = {
    "baseline/skill_disabled",
    "candidate/force_loaded",
    "candidate/natural_routing",
}
CHECK_IDS = ["outcome", "evidence", "scope_safety"]
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


class ReviewV11SuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.author = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
        cls.suite = author_suite.normalize(cls.author, STUB_HOST, SUITE_ROOT)

    def test_e01_suite_normalizes_with_fixed_cases_requirements_and_profiles(self) -> None:
        suite = self.suite
        self.assertEqual("code-review", suite["skill_id"])
        self.assertEqual(CASE_IDS, [case["case_id"] for case in suite["cases"]])
        self.assertEqual(1, suite["repeats"])
        self.assertEqual(EXPECTED_PROFILES, {item["profile"] for item in suite["treatments"]})
        self.assertEqual(
            {"baseline", "forced", "natural"},
            {item["treatment_id"] for item in suite["treatments"]},
        )
        self.assertEqual(1, len(suite["graders"]))
        grader = suite["graders"][0]
        self.assertEqual("review-quality", grader["grader_id"])
        self.assertEqual("model", grader["type"])
        self.assertEqual("rubric.md", grader["prompt_template"]["path"])
        self.assertEqual(CHECK_IDS, [check["check_id"] for check in grader["checks"]])
        for check in grader["checks"]:
            self.assertTrue(check["required"])
        self.assertEqual(
            {"outcome": "outcome", "evidence": "quality", "scope_safety": "safety"},
            {check["check_id"]: check["dimension"] for check in grader["checks"]},
        )
        for case in suite["cases"]:
            with self.subTest(f"E01 {case['case_id']}"):
                self.assertEqual(
                    CHECK_IDS, [requirement["check_id"] for requirement in case["requirements"]]
                )
                for requirement in case["requirements"]:
                    self.assertEqual("review-quality", requirement["grader_id"])
                    self.assertTrue(requirement["required"])
                self.assertEqual(1, len(case["turns"]))
                self.assertEqual("user_message", case["turns"][0]["input"]["kind"])
                self.assertNotIn("$code-review", case["turns"][0]["input"]["content"])
                files = case["fixture"]["initial_files"]
                self.assertTrue(files)
                for binding in files:
                    path = SUITE_ROOT / binding["path"]
                    self.assertTrue(path.is_file(), binding["path"])
                    self.assertTrue(binding["path"].startswith(f"fixtures/{case['case_id']}/"))
                    self.assertNotIn("rubric.md", binding["path"])
                self.assertEqual(
                    f"fixtures/{case['case_id']}", str(Path(files[0]["path"]).parent)
                )

    def test_e01_fixture_seeds_compile_and_stay_unchanged(self) -> None:
        fixtures_root = SUITE_ROOT / "fixtures"
        before = {
            path: path.read_bytes() for path in sorted(fixtures_root.rglob("*")) if path.is_file()
        }
        # Compile in memory: the delivered fixture directory must stay free of caches.
        for path in sorted(fixtures_root.rglob("*.py")):
            with self.subTest(f"E01 compile {path.name}"):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
        for path, payload in before.items():
            with self.subTest(f"E01 {path.name}"):
                self.assertEqual(payload, path.read_bytes())
        self.assertEqual(CASE_IDS, sorted(path.name for path in fixtures_root.iterdir()))
        self.assertFalse(any(fixtures_root.rglob("__pycache__")))

    def test_e02_budgets_are_zero_and_no_provider_or_host_call_was_made(self) -> None:
        constraints = self.suite["constraints"]
        self.assertEqual(0, constraints["task_attempt_budget"])
        self.assertEqual(0, constraints["judge_invocation_budget"])
        self.assertEqual(300, constraints["timeout_seconds"])
        self.assertEqual(
            {"task_attempt_budget": 0, "judge_invocation_budget": 0, "timeout_seconds": 300},
            constraints,
        )
        self.assertFalse((SUITE_ROOT / "host.json").exists())
        self.assertFalse((SUITE_ROOT / "run").exists())
        # Local validation never imports the runner or a provider probe.
        self.assertNotIn("evaluate", sys.modules)
        self.assertNotIn("host_probe", sys.modules)
        with self.assertRaises(ValueError):
            author_suite.normalize(self.author, {"catalog": {"entries": []}}, SUITE_ROOT)

    def test_e03_activation_matrix_and_invocation_prompts(self) -> None:
        manifest = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        explicit = {"software-quality-workflows", "skill-evaluator"}
        for item in manifest["skills"]:
            agents_path = ROOT / item["path"] / "agents" / "openai.yaml"
            text = agents_path.read_text(encoding="utf-8")
            expected = "true" if item["id"] not in explicit else "false"
            self.assertIn(f"allow_implicit_invocation: {expected}\n", text, item["id"])
            self.assertIn(f"${item['id']}", text, item["id"])
        bundle = json.loads(
            (ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8")
        )
        for skill_id, record in bundle["skills"].items():
            self.assertIs(skill_id not in explicit, record["allow_implicit_invocation"], skill_id)

    def test_e01_rv11_seed_fails_before_and_passes_after_the_specified_repair(self) -> None:
        seed = SUITE_ROOT / "fixtures" / "RV11"
        original_module = (seed / "module.py").read_bytes()
        original_test = (seed / "test_module.py").read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            broken = work / "broken"
            shutil.copytree(seed, broken)
            failed = self._run_unittest(broken)
            self.assertNotEqual(0, failed.returncode, failed.stdout + failed.stderr)
            fixed = work / "fixed"
            shutil.copytree(seed, fixed)
            module_path = fixed / "module.py"
            module_path.write_text(
                module_path.read_text(encoding="utf-8").replace(
                    "return size or 64", "return 64 if size is None else size"
                ),
                encoding="utf-8",
            )
            passed = self._run_unittest(fixed)
            self.assertEqual(0, passed.returncode, passed.stdout + passed.stderr)
        self.assertEqual(original_module, (seed / "module.py").read_bytes())
        self.assertEqual(original_test, (seed / "test_module.py").read_bytes())

    def _run_unittest(self, directory: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "unittest", "test_module.py", "-v"],
            cwd=directory,
            env=ENV,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_e01_rubric_never_ships_fixture_content(self) -> None:
        rubric = (SUITE_ROOT / "rubric.md").read_text(encoding="utf-8")
        self.assertEqual(CASE_IDS, [case for case in CASE_IDS if case in rubric])
        for path in sorted((SUITE_ROOT / "fixtures").rglob("*")):
            if not path.is_file():
                continue
            with self.subTest(f"E01 rubric {path.name}"):
                body = path.read_text(encoding="utf-8")
                longest = max((line.strip() for line in body.splitlines()), key=len, default="")
                if longest:
                    self.assertNotIn(longest, rubric)


if __name__ == "__main__":
    unittest.main()
