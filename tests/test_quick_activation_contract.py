from __future__ import annotations

import json
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": True,
    "writing-plans": False,
}


class QuickActivationContractTests(unittest.TestCase):
    def test_agents_generated_bundle_and_source_boundary_match(self) -> None:
        observed = {}
        for skill_id in EXPECTED:
            agents = yaml.safe_load((ROOT / skill_id / "agents" / "openai.yaml").read_text(encoding="utf-8"))
            observed[skill_id] = agents["policy"]["allow_implicit_invocation"]
        self.assertEqual(EXPECTED, observed)

        generated = json.loads((ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(EXPECTED, {
            skill_id: value["allow_implicit_invocation"]
            for skill_id, value in generated["skills"].items()
        })
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        self.assertIs(source["remote_writes"], False)
        self.assertIs(generated["remote_writes"], False)
        self.assertTrue(all(set(item) == {"id", "path", "version"} for item in source["skills"]))

    def test_explicit_only_prompts_name_the_skill(self) -> None:
        for skill_id in ("skill-evaluator", "writing-plans"):
            agents = yaml.safe_load((ROOT / skill_id / "agents" / "openai.yaml").read_text(encoding="utf-8"))
            self.assertIn(f"${skill_id}", agents["interface"]["default_prompt"])

    def test_writing_plans_explicit_body_prevents_redundant_self_load(self) -> None:
        entry = (ROOT / "writing-plans" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("supplies this body in full", entry)
        self.assertIn("do not reopen `SKILL.md`", entry)


if __name__ == "__main__":
    unittest.main()
