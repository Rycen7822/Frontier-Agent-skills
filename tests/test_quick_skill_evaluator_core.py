from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skill-evaluator"
SCRIPTS = SKILL_ROOT / "scripts"


def load_module(name: str, path: Path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuickSkillEvaluatorCoreTests(unittest.TestCase):
    def test_metadata_activation_and_public_examples(self) -> None:
        text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = yaml.safe_load(match.group(1))
        self.assertEqual("3.3.2", frontmatter["metadata"]["version"])
        agents = yaml.safe_load((SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertIs(agents["policy"]["allow_implicit_invocation"], False)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_eval_suite.py"),
             "contract",
             str(SKILL_ROOT / "templates" / "eval-spec.example.json"),
             str(SKILL_ROOT / "templates" / "scenarios.example.jsonl"),
             str(SKILL_ROOT / "templates" / "host-manifest.example.json")],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_public_l1_template_is_valid(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "validate_eval_suite.py"),
                "contract",
                str(SKILL_ROOT / "templates" / "eval-spec.l1.example.json"),
                str(SKILL_ROOT / "templates" / "scenarios.l1.example.jsonl"),
                str(SKILL_ROOT / "templates" / "host-manifest.example.json"),
            ],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_stable_interval_and_protected_outcome_functions(self) -> None:
        analyzer = load_module("skill_evaluator_analyzer_quick", SCRIPTS / "analyze_runs.py")
        interval = analyzer.wilson(1, 1)
        self.assertIsNotNone(interval)
        self.assertAlmostEqual(0.2065493144, interval[0])
        self.assertEqual(1.0, interval[1])
        self.assertAlmostEqual(2.5, analyzer.percentile([1.0, 2.0, 3.0, 4.0], 0.5))
        cases = {
            "protected": {
                "tags": ["protected"],
                "requirements": [{"id": "outcome", "dimension": "outcome", "required": True}],
            }
        }
        records = [
            {"variant": variant, "case_id": "protected", "repeat": 1, "valid": True, "hard_gate_failures": []}
            for variant in ("baseline", "candidate")
        ]
        self.assertEqual(0, analyzer.derive_protected_outcome_failures(
            records, cases, baseline="baseline", candidate="candidate", repeats=1,
        ))

        v5_case = {
            "tags": ["protected"],
            "requirements": [
                {
                    "requirement_id": "outcome",
                    "dimension": "outcome",
                    "required": True,
                }
            ],
        }
        plan = {
            "entries": [
                {
                    "entry_id": variant,
                    "treatment_id": variant,
                    "disposition": "execute",
                    "execute_case_payload": {"case": v5_case},
                }
                for variant in ("baseline", "candidate")
            ]
        }
        v5_records = [
            {
                "entry_id": "baseline",
                "task_pass": False,
                "hard_gate_failures": ["outcome"],
            },
            {
                "entry_id": "candidate",
                "task_pass": True,
                "hard_gate_failures": [],
            },
        ]
        self.assertEqual(
            0,
            analyzer._v5_protected_outcome_failures(
                plan,
                v5_records,
                candidate_id="candidate",
            ),
        )

    def test_context_projection_and_waste_gates_are_exact(self) -> None:
        analyzer = load_module("skill_evaluator_analyzer_projection", SCRIPTS / "analyze_runs.py")
        validator = load_module("skill_evaluator_validator_projection", SCRIPTS / "validate_eval_suite.py")
        self.assertEqual((
            "unique_static_content_bytes", "repeated_static_content_bytes",
            "protocol_output_bytes", "failed_command_output_bytes",
        ), analyzer.CONTEXT_EFFICIENCY_FIELDS)
        self.assertTrue({
            "controlled_skill_context_bytes_p95", "host_integration_duplicate_bytes_max",
            "unexplained_repeated_static_content_bytes_max",
            "unattributed_model_body_read_count_max", "protocol_output_bytes_max",
            "failed_command_output_bytes_max",
        } <= validator.GLOBAL_GATE_METRICS)
        self.assertEqual(
            ("context_usage", "controlled_core_bytes", "native"),
            analyzer.PAIRED_METRIC_SOURCES["controlled_core_skill_context_bytes"],
        )
        self.assertIn(
            "controlled_core_skill_context_bytes",
            validator.RELATIVE_EFFECT_METRICS,
        )
if __name__ == "__main__":
    unittest.main()
