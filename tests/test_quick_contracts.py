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
        self.assertEqual("8.0.0", source["bundle_version"])
        self.assertEqual(7, generated["compatible_schema_epoch"])
        self.assertEqual("frontier-engineering/8.0.0", generated["bundle_id"])
        self.assertFalse(source["remote_writes"])
        self.assertEqual("implicit_local_pilot", source["activation_ceiling"])

        source_skills = {item["id"]: item for item in source["skills"]}
        self.assertEqual(set(source_skills), set(generated["skills"]))
        for skill_id, item in source_skills.items():
            skill_root = ROOT / skill_id
            text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
            match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
            self.assertIsNotNone(match, skill_id)
            frontmatter = yaml.safe_load(match.group(1))
            agents = yaml.safe_load(
                (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
            )
            self.assertEqual(skill_id, frontmatter["name"])
            self.assertEqual(item["version"], frontmatter["metadata"]["version"])
            self.assertEqual(item["version"], generated["skills"][skill_id]["version"])
            self.assertIs(
                agents["policy"]["allow_implicit_invocation"],
                generated["skills"][skill_id]["allow_implicit_invocation"],
            )
        evaluator_prompt = yaml.safe_load(
            (ROOT / "skill-evaluator" / "agents" / "openai.yaml").read_text(
                encoding="utf-8"
            )
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

if __name__ == "__main__":
    unittest.main()
