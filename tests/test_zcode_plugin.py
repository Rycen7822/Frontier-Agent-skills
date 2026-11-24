"""Check the ZCode plugin shell and marketplace entry against the source bundle."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".zcode-plugin" / "plugin.json"
MARKETPLACE = ROOT / "marketplace.json"
NAME = "frontier-engineering"
KEBAB = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,127}\Z")


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"JSON root must be an object: {path}")
    return value


class ZCodePluginShell(unittest.TestCase):
    def test_manifest_binds_the_source_bundle(self) -> None:
        manifest = load_json(MANIFEST)
        source = load_json(ROOT / "bundle-manifest.json")
        self.assertEqual(NAME, manifest["name"])
        self.assertIsNotNone(KEBAB.fullmatch(manifest["name"]))
        self.assertEqual(source["bundle_version"], manifest["version"])
        self.assertEqual(
            [f"./{item['path']}" for item in source["skills"]],
            manifest["skills"],
        )

    def test_declared_skills_are_the_canonical_skill_directories(self) -> None:
        manifest = load_json(MANIFEST)
        for declared in manifest["skills"]:
            skill_root = ROOT / declared
            self.assertTrue(skill_root.is_dir(), declared)
            self.assertTrue((skill_root / "SKILL.md").is_file(), declared)

    def test_marketplace_entry_points_at_the_repository_plugin(self) -> None:
        marketplace = load_json(MARKETPLACE)
        manifest = load_json(MANIFEST)
        self.assertIsNotNone(KEBAB.fullmatch(marketplace["name"]))
        entries = [item for item in marketplace["plugins"] if item.get("name") == NAME]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertEqual("./", entry["source"])
        self.assertEqual(manifest["version"], entry["version"])
        self.assertEqual(manifest["description"], entry["description"])


if __name__ == "__main__":
    unittest.main()
