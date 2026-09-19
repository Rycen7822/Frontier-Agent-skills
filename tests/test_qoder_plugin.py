"""Check the Qoder plugin shell against the source bundle, not model behaviour."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_qoder_plugin  # noqa: E402


MANIFEST = ROOT / ".qoder-plugin" / "plugin.json"
KEBAB = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


class QoderPluginShell(unittest.TestCase):
    def test_committed_shell_matches_the_source_bundle(self) -> None:
        manifest = load_manifest()
        self.assertEqual(
            build_qoder_plugin._rendered_bytes(build_qoder_plugin.render_manifest()),
            MANIFEST.read_bytes(),
        )
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(source["bundle_version"], manifest["version"])

    def test_shell_is_the_documented_portable_shape(self) -> None:
        manifest = load_manifest()
        self.assertEqual("frontier-engineering", manifest["name"])
        self.assertIsNotNone(KEBAB.fullmatch(manifest["name"]))
        self.assertEqual(
            sorted(build_qoder_plugin.DOCUMENTED_FIELDS & set(manifest)),
            sorted(manifest),
        )
        self.assertFalse(build_qoder_plugin.RUNTIME_FIELDS & set(manifest))
        self.assertEqual({"name"}, set(manifest["author"]))

    def test_declared_skills_are_the_canonical_skill_directories(self) -> None:
        manifest = load_manifest()
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [f"./{item['path']}" for item in source["skills"]],
            manifest["skills"],
        )
        for item in source["skills"]:
            skill_root = ROOT / item["path"]
            entry = skill_root / "SKILL.md"
            self.assertFalse(skill_root.is_symlink(), item["path"])
            self.assertTrue(entry.is_file(), item["path"])
            match = re.match(r"\A---\n(.*?)\n---\n", entry.read_text(encoding="utf-8"), flags=re.DOTALL)
            self.assertIsNotNone(match, item["path"])
            frontmatter = yaml.safe_load(match.group(1))
            self.assertEqual(item["path"], frontmatter["name"], item["path"])
            self.assertTrue(str(frontmatter["description"]).strip(), item["path"])

    def test_shell_carries_no_local_path_or_placeholder(self) -> None:
        text = MANIFEST.read_text(encoding="utf-8")
        for pattern in build_qoder_plugin.LOCAL_PATH_PATTERNS:
            self.assertIsNone(pattern.search(text))
        self.assertNotIn("[" + "TODO:", text)


if __name__ == "__main__":
    unittest.main()
