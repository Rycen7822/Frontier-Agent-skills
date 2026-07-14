from __future__ import annotations

import json
from pathlib import Path
import re
import stat
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
REMOVED_WRITING_PATHS = {
    "references/compatibility-map.json",
    "references/context-compaction-resistant-upgrade-plans.md",
    "references/evidence-backed-standalone-roadmaps.md",
    "references/fillable-requirements-glossary-pattern.md",
    "references/legacy-manifest-diff-compatibility.md",
    "references/local-artifact-cleanup-and-benchmark-fixture-expansion.md",
    "references/plan-absorbed-skill.md",
    "references/research-reference-materials.md",
    "references/result-preserving-optimization-plans.md",
    "references/spike-absorbed-skill.md",
    "scripts/validate_compatibility_stubs.py",
    "scripts/migrate_legacy_plan_ids.py",
}
FORBIDDEN_PARTS = {"__pycache__", ".closure", ".workflow", "dist"}
LOCAL_LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)#]+)(?:#[^)]+)?\)")
LOCAL_ONLY_ROOTS = {".git", ".work"}
LOCAL_ONLY_FILES = {"CODEX_STATE.md"}


def is_repository_local(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return bool(
        relative.parts
        and (
            relative.parts[0] in LOCAL_ONLY_ROOTS
            or (len(relative.parts) == 1 and relative.name in LOCAL_ONLY_FILES)
        )
    )


def frontmatter_version(skill_root: Path) -> str:
    text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^version:\s*([^\s#]+)\s*$", text)
    if not match:
        raise AssertionError(f"missing skill version: {skill_root}")
    return match.group(1)


class BundleContractTests(unittest.TestCase):
    def test_repository_local_artifacts_are_ignored(self) -> None:
        ignore_path = ROOT / ".gitignore"
        self.assertTrue(ignore_path.is_file(), "repository must declare its local-only artifact boundary")
        patterns = {
            line.strip()
            for line in ignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        required = {
            "/CODEX_STATE.md",
            "/.work/*.md",
            "/.work/tmp/",
            "/.work/p4-live-canary-evidence/",
            "/.work/p4-live-canary-retry-*/",
            "/.work/p6-readiness-evidence/",
            "/tmp/",
            "/dist/",
            "*.zip",
            "*.zip.evidence.json",
            ".env",
            "__pycache__/",
        }
        self.assertFalse(required - patterns, f"missing local-only ignore patterns: {sorted(required - patterns)}")
        self.assertTrue(is_repository_local(ROOT / ".work" / "note.md"))
        self.assertTrue(is_repository_local(ROOT / "CODEX_STATE.md"))
        self.assertFalse(is_repository_local(ROOT / "README.md"))

    def test_manifest_declares_exact_skills_versions_and_profiles(self) -> None:
        self.assertEqual("1.0", MANIFEST["bundle_schema_version"])
        skills = MANIFEST["skills"]
        self.assertEqual({"writing-plans", "software-quality-workflows"}, {item["id"] for item in skills})
        for item in skills:
            skill_root = ROOT / item["path"]
            self.assertTrue(skill_root.is_dir(), f"missing bundled skill: {item['path']}")
            self.assertEqual(item["version"], frontmatter_version(skill_root))
        for profile in ("standalone", "extended"):
            self.assertEqual(3, len(MANIFEST["test_profiles"][profile]))
        self.assertEqual("LONG_DOCUMENT_SKILL_ROOT", MANIFEST["optional_external_dependencies"][0]["environment_variable"])
        self.assertEqual(
            {
                "current_level": "shadow",
                "live_autonomous_closure_default": False,
                "multi_candidate_enabled": False,
                "remote_writes": False,
                "p5_report": "evaluation/p5-shadow-report.json",
                "p5_control_evidence": "evaluation/p5-control-evidence.json",
            },
            MANIFEST["activation_policy"],
        )
        report = json.loads((ROOT / MANIFEST["activation_policy"]["p5_report"]).read_text(encoding="utf-8"))
        controls = json.loads((ROOT / MANIFEST["activation_policy"]["p5_control_evidence"]).read_text(encoding="utf-8"))
        self.assertEqual("remain_shadow", report["decision"])
        self.assertEqual("shadow", report["activation_ceiling"])
        self.assertTrue(all(item["status"] == "not_run" for item in controls["ablations"]))

    def test_removed_compatibility_and_generated_state_are_absent(self) -> None:
        writing = ROOT / "writing-plans"
        release_notes = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for relative in REMOVED_WRITING_PATHS:
            self.assertFalse((writing / relative).exists(), relative)
            self.assertIn(f"writing-plans/{relative}", release_notes)
        self.assertIn("No redirect or permanent compatibility stub is provided", release_notes)
        for skill in (writing, ROOT / "software-quality-workflows"):
            for path in skill.rglob("*"):
                relative = path.relative_to(skill)
                self.assertFalse(any(part in FORBIDDEN_PARTS for part in relative.parts), relative.as_posix())
                self.assertNotIn(path.suffix, {".pyc", ".pyo"})

    def test_all_local_markdown_links_resolve(self) -> None:
        markdown_files = [ROOT / "README.md", ROOT / "RELEASE_NOTES.md"]
        for skill in (ROOT / "writing-plans", ROOT / "software-quality-workflows"):
            self.assertTrue(skill.is_dir())
            markdown_files.extend(skill.rglob("*.md"))
        for path in markdown_files:
            text = path.read_text(encoding="utf-8")
            for target in LOCAL_LINK.findall(text):
                resolved = (path.parent / target).resolve()
                self.assertTrue(resolved.exists(), f"{path.relative_to(ROOT)} -> {target}")

    def test_json_python_and_plugin_template_are_structurally_valid(self) -> None:
        for path in ROOT.rglob("*.json"):
            if is_repository_local(path):
                continue
            json.loads(path.read_text(encoding="utf-8"))
        for pattern in ("*.yaml", "*.yml"):
            for path in ROOT.rglob(pattern):
                if is_repository_local(path):
                    continue
                self.assertIsInstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict, path)
        for path in ROOT.rglob("*.py"):
            if is_repository_local(path):
                continue
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
            if "scripts" in path.parts:
                self.assertTrue(path.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3"), path)
            if "scripts" in path.relative_to(ROOT).parts:
                self.assertTrue(path.stat().st_mode & stat.S_IXUSR, path)
        template = json.loads((ROOT / "packaging" / "codex-plugin" / "plugin.json.template").read_text(encoding="utf-8"))
        self.assertEqual("${BUNDLE_VERSION}", template["version"])
        self.assertEqual("./skills/", template["skills"])
        self.assertTrue({"mcpServers", "apps", "hooks"}.isdisjoint(template))
        self.assertEqual("software-engineering-closure-plugin", template["name"])
        self.assertIn("name", template["author"])
        self.assertTrue({"displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities"} <= set(template["interface"]))

    def test_reader_facing_bundle_has_no_developer_absolute_paths(self) -> None:
        developer_home = "/" + "home" + "/"
        mounted_data = "/" + "mnt" + "/" + "data" + "/"
        for path in ROOT.rglob("*"):
            if (
                is_repository_local(path)
                or not path.is_file()
                or path.suffix not in {".md", ".json", ".yaml", ".py", ".template"}
            ):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(developer_home, text, path.relative_to(ROOT).as_posix())
            self.assertNotIn(mounted_data, text, path.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    unittest.main()
