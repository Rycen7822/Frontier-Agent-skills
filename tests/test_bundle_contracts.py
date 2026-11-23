from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
CODEX_EXPLICIT_ONLY = {
    "clean-code-comments",
    "codebase-improve",
    "improve-docs",
    "skill-evaluator",
    "software-quality-workflows",
}
PI_EXPLICIT_ONLY = {"clean-code-comments", "codebase-improve", "improve-docs"}


class BundleContractsTests(unittest.TestCase):
    def test_bundle_and_skill_metadata_match_release_contract(self) -> None:
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        bundle = json.loads((ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8"))
        self.assertEqual("11.6.1", source["bundle_version"])
        self.assertEqual(9, bundle["compatible_schema_epoch"])
        self.assertEqual("frontier-engineering/11.6.1", bundle["bundle_id"])
        self.assertFalse(source["remote_writes"])
        self.assertEqual("implicit_local_pilot", source["activation_ceiling"])

        self.assertEqual({item["id"] for item in source["skills"]}, set(bundle["skills"]))
        for item in source["skills"]:
            skill_id = item["id"]
            with self.subTest(skill=skill_id):
                skill_root = ROOT / item["path"]
                entry = (skill_root / "SKILL.md").read_text(encoding="utf-8")
                match = re.match(r"\A---\n(.*?)\n---\n", entry, flags=re.DOTALL)
                self.assertIsNotNone(match)
                frontmatter = yaml.safe_load(match.group(1))
                codex = yaml.safe_load(
                    (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
                )
                generated = bundle["skills"][skill_id]
                self.assertEqual(skill_id, frontmatter["name"])
                self.assertEqual(item["version"], frontmatter["metadata"]["version"])
                self.assertEqual(item["version"], generated["version"])

                implicit = skill_id not in CODEX_EXPLICIT_ONLY
                self.assertIs(implicit, codex["policy"]["allow_implicit_invocation"])
                self.assertIs(implicit, generated["allow_implicit_invocation"])
                self.assertIn(f"${skill_id}", codex["interface"]["default_prompt"])
                if skill_id in PI_EXPLICIT_ONLY:
                    self.assertIs(True, frontmatter["disable-model-invocation"])


if __name__ == "__main__":
    unittest.main()
