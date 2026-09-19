from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class QuickContracts(unittest.TestCase):
    def test_bundle_and_skill_activation_match(self) -> None:
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        generated = json.loads(
            (ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8")
        )
        self.assertEqual("11.2.0", source["bundle_version"])
        self.assertEqual(9, generated["compatible_schema_epoch"])
        self.assertEqual("frontier-engineering/11.2.0", generated["bundle_id"])
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
        explicit_skills = {"software-quality-workflows", "skill-evaluator"}
        for skill_id, item in source_skills.items():
            expected = skill_id not in explicit_skills
            self.assertIs(
                expected,
                generated["skills"][skill_id]["allow_implicit_invocation"],
                skill_id,
            )
        for skill_id in explicit_skills:
            prompt = yaml.safe_load(
                (ROOT / skill_id / "agents" / "openai.yaml").read_text(encoding="utf-8")
            )["interface"]["default_prompt"]
            self.assertIn(f"${skill_id}", prompt)


if __name__ == "__main__":
    unittest.main()
