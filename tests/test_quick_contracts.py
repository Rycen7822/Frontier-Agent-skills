from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = {
    "long-document-segmented-writing": "2.0.0",
    "skill-evaluator": "4.0.0",
    "software-quality-workflows": "10.0.0",
    "writing-plans": "8.3.0",
}
ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": True,
    "writing-plans": True,
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


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


class QuickContracts(unittest.TestCase):
    def test_bundle_and_skill_activation_match(self) -> None:
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        generated = json.loads(
            (ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8")
        )
        self.assertEqual("7.0.0", source["bundle_version"])
        self.assertEqual(6, generated["compatible_schema_epoch"])
        self.assertEqual("frontier-engineering/7.0.0", generated["bundle_id"])
        self.assertEqual(VERSIONS, {item["id"]: item["version"] for item in source["skills"]})
        self.assertEqual(VERSIONS, {name: item["version"] for name, item in generated["skills"].items()})
        self.assertFalse(source["remote_writes"])
        self.assertEqual("implicit_local_pilot", source["activation_ceiling"])

        for skill_id, version in VERSIONS.items():
            skill_root = ROOT / skill_id
            text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
            self.assertIsNotNone(match, skill_id)
            frontmatter = yaml.safe_load(match.group(1))
            agents = yaml.safe_load(
                (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(skill_id, frontmatter["name"])
            self.assertEqual(version, frontmatter["metadata"]["version"])
            self.assertIs(
                agents["policy"]["allow_implicit_invocation"],
                ACTIVATION[skill_id],
            )
        evaluator_prompt = yaml.safe_load(
            (ROOT / "skill-evaluator" / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )["interface"]["default_prompt"]
        self.assertIn("$skill-evaluator", evaluator_prompt)

    def test_public_evaluator_template_is_accepted_as_non_ready(self) -> None:
        skill = ROOT / "skill-evaluator"
        result = run_script(
            "skill-evaluator/scripts/validate_eval_suite.py",
            "contract",
            str(skill / "templates" / "eval-spec.example.json"),
            str(skill / "templates" / "scenarios.example.jsonl"),
            str(skill / "templates" / "host-manifest.example.json"),
            "--json",
            "-",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([], report["errors"])
        self.assertEqual(
            {
                "non_ready.execution",
                "non_ready.quality",
                "non_ready.verifier",
            },
            {warning["code"] for warning in report["warnings"]},
        )

    def test_deterministic_source_gates_pass(self) -> None:
        commands = (
            ("bundle/build_bundle_manifest.py", "--check"),
            ("scripts/build_model_evolution_sentinels.py", "--check"),
            ("scripts/evaluate_static_contracts.py", "--check"),
        )
        for command in commands:
            with self.subTest(command=command[0]):
                result = run_script(*command)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        static_report = json.loads(run_script(*commands[-1]).stdout)
        self.assertEqual({"ok": True, "blocking_facts": 0}, static_report)


if __name__ == "__main__":
    unittest.main()
