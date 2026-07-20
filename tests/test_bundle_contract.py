from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import re
import stat
import unittest

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
BUNDLE_BUILDER_PATH = ROOT / "bundle" / "build_bundle_manifest.py"
BUNDLE_BUILDER_SPEC = importlib.util.spec_from_file_location("build_bundle_manifest", BUNDLE_BUILDER_PATH)
assert BUNDLE_BUILDER_SPEC is not None and BUNDLE_BUILDER_SPEC.loader is not None
BUNDLE_BUILDER = importlib.util.module_from_spec(BUNDLE_BUILDER_SPEC)
BUNDLE_BUILDER_SPEC.loader.exec_module(BUNDLE_BUILDER)
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
LOCAL_ONLY_ROOTS = {".git", ".work", "share"}
LOCAL_ONLY_FILES = {"CODEX_STATE.md"}
CODEX_SKILL_KEYS = {"name", "description", "license", "metadata", "allowed-tools"}
SUPPORTED_HOSTS = ["codex", "hermes-agent"]


def is_repository_local(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    return bool(
        relative.parts
        and (
            relative.parts[0] in LOCAL_ONLY_ROOTS
            or (len(relative.parts) == 1 and relative.name in LOCAL_ONLY_FILES)
        )
    )


def skill_frontmatter(skill_root: Path) -> dict:
    text = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError(f"missing skill frontmatter: {skill_root}")
    value = yaml.safe_load(match.group(1))
    if not isinstance(value, dict):
        raise AssertionError(f"skill frontmatter is not a mapping: {skill_root}")
    return value


def frontmatter_version(skill_root: Path) -> str:
    metadata = skill_frontmatter(skill_root).get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("version"), str):
        raise AssertionError(f"missing metadata.version: {skill_root}")
    return metadata["version"]


class BundleContractTests(unittest.TestCase):
    def test_release_bundle_identity_is_exact_and_reproducible(self) -> None:
        generated = BUNDLE_BUILDER.build_manifest()
        checked_in = json.loads((ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(generated, checked_in)
        schema = json.loads(
            (ROOT / "bundle" / "frontier-engineering-bundle.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(checked_in)))
        self.assertEqual("frontier-engineering/8.0.0+7.0.0", checked_in["bundle_id"])
        self.assertEqual(2, checked_in["compatible_schema_epoch"])
        self.assertEqual(
            {"software-quality-workflows": "8.0.0", "writing-plans": "7.0.0"},
            {skill_id: item["version"] for skill_id, item in checked_in["skills"].items()},
        )
        for item in checked_in["skills"].values():
            self.assertRegex(item["root_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(item["policy_registry"]["content_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(item["reference_card_manifest"]["content_hash"], r"^sha256:[0-9a-f]{64}$")

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
            "/share/",
            "/.work/*.md",
            "/.work/tmp/",
            "/.work/frontier-engineering-*/",
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
        self.assertEqual("2.0", MANIFEST["bundle_schema_version"])
        self.assertEqual("4.0.0", MANIFEST["bundle_version"])
        skills = MANIFEST["skills"]
        self.assertEqual({"writing-plans", "software-quality-workflows"}, {item["id"] for item in skills})
        self.assertEqual(
            {"writing-plans": "7.0.0", "software-quality-workflows": "8.0.0"},
            {item["id"]: item["version"] for item in skills},
        )
        for item in skills:
            skill_root = ROOT / item["path"]
            self.assertTrue(skill_root.is_dir(), f"missing bundled skill: {item['path']}")
            frontmatter = skill_frontmatter(skill_root)
            self.assertFalse(set(frontmatter) - CODEX_SKILL_KEYS)
            self.assertEqual(item["id"], frontmatter["name"])
            metadata = frontmatter["metadata"]
            self.assertEqual(SUPPORTED_HOSTS, metadata["hosts"])
            self.assertIsInstance(metadata["author"], str)
            self.assertTrue(metadata["author"])
            hermes = metadata["hermes"]
            self.assertEqual("software-development", hermes["category"])
            self.assertIsInstance(hermes["tags"], list)
            self.assertIsInstance(hermes["related_skills"], list)
            self.assertEqual(item["version"], frontmatter_version(skill_root))
            agent_metadata = yaml.safe_load((skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8"))
            interface = agent_metadata["interface"]
            self.assertIsInstance(interface["display_name"], str)
            self.assertGreaterEqual(len(interface["short_description"]), 25)
            self.assertLessEqual(len(interface["short_description"]), 64)
            self.assertIn(f"${item['id']}", interface["default_prompt"])
            self.assertIs(agent_metadata["policy"]["allow_implicit_invocation"], True)
        for profile in ("standalone", "extended"):
            self.assertEqual(3, len(MANIFEST["test_profiles"][profile]))
        self.assertEqual("LONG_DOCUMENT_SKILL_ROOT", MANIFEST["optional_external_dependencies"][0]["environment_variable"])
        self.assertEqual(
            {
                "current_level": "implicit_local_pilot",
                "implicit_routing_default": True,
                "remote_writes": False,
            },
            MANIFEST["activation_policy"],
        )
        self.assertEqual(
            ["plan-to-workflow", "workflow-plan-change-proposal"],
            MANIFEST["cross_skill_contracts"],
        )
        routes = MANIFEST["cross_skill_routes"]
        self.assertEqual("frontier-cross-skill-routes/1", routes["schema_version"])
        self.assertEqual(["sqw-to-writing-plans", "writing-plans-to-sqw"], [row["route_id"] for row in routes["routes"]])

    def test_retired_candidate_evidence_and_schema_names_are_absent(self) -> None:
        retired = [
            "evaluation/p5-control-evidence.json",
            "evaluation/p5-shadow-report.json",
            "evaluation/corpus/p5-shadow-corpus.json",
            "evaluation/schemas/p5-control-evidence.schema.json",
            "evaluation/schemas/p5-eval-corpus.schema.json",
            "evaluation/schemas/p5-eval-report.schema.json",
            "evaluation/schemas/p5-eval-run.schema.json",
            "packaging/schemas/p6-plugin-build-evidence.schema.json",
            "packaging/schemas/p6-release-evidence.schema.json",
            "packaging/schemas/p6-static-smoke.schema.json",
            "packaging/schemas/p6-cli-smoke.schema.json",
        ]
        self.assertEqual([], [path for path in retired if (ROOT / path).exists()])
        current = [
            "packaging/schemas/plugin-build-evidence.schema.json",
            "packaging/schemas/release-evidence.schema.json",
            "packaging/schemas/static-plugin-smoke.schema.json",
            "packaging/schemas/cli-install-smoke.schema.json",
            "packaging/schemas/source-archive-evidence.schema.json",
        ]
        for relative in current:
            schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self.assertIn("/frontier-engineering/", schema["$id"])

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

    def test_release_candidate_has_no_retired_identity_or_explicit_only_default(self) -> None:
        forbidden = (
            "software-engineering-" + "closure",
            "autonomous_" + "closure",
            "autonomous-" + "closure",
            "eligible_for_" + "p6" + "_" + "canary",
            "p4_live_" + "success_canary",
            "p5" + "_" + "real_" + "cohort",
            "allow_implicit_invocation:" + " false",
        )
        allowed_historical = ROOT / "RELEASE_NOTES.md"
        hits: list[str] = []
        for path in ROOT.rglob("*"):
            if is_repository_local(path) or path == allowed_historical or not path.is_file():
                continue
            if path.suffix not in {".md", ".json", ".yaml", ".py", ".template"}:
                continue
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in relative or token in text:
                    hits.append(f"{relative}:{token}")
        self.assertEqual([], hits)

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
        self.assertEqual("frontier-engineering-plugin", template["name"])
        self.assertEqual("Frontier Engineering", template["interface"]["displayName"])
        self.assertFalse({"closure", "autonomous"} & {item.lower() for item in template["keywords"]})
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
