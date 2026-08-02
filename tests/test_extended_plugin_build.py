from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_codex_plugin.py"
EXPECTED_ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": False,
    "writing-plans": False,
}
TEST_REVISION = "a" * 40


def load_builder():
    spec = importlib.util.spec_from_file_location("extended_plugin_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load plugin builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_static_smoke():
    path = ROOT / "scripts" / "smoke_codex_plugin.py"
    spec = importlib.util.spec_from_file_location("extended_plugin_static_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load static plugin smoke")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_hash(value: dict) -> str:
    return "sha256:" + sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


class ExtendedPluginBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = load_builder()

    def build_staging(self, root: Path) -> tuple[Path, Path, dict]:
        output = root / "frontier-engineering-plugin"
        evidence_path = root / "plugin-build-evidence.json"
        with mock.patch.object(
            self.builder, "_source_revision", return_value=TEST_REVISION,
        ):
            evidence = self.builder.build(ROOT, output, None, evidence_path)
        return output, evidence_path, evidence

    def test_source_revision_rejects_nested_non_repository_root(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            with self.assertRaisesRegex(ValueError, "canonical Git revision"):
                self.builder._source_revision(Path(directory))

    def test_staging_is_atomic_schema_valid_and_activation_aware(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, evidence_path, evidence = self.build_staging(root)
            self.assertTrue(output.is_dir())
            self.assertTrue(evidence_path.is_file())
            self.assertFalse((root / "plugin-build-staging").exists())
            schema = json.loads((ROOT / "packaging" / "schemas" / "plugin-build-evidence.schema.json").read_text())
            Draft202012Validator(schema).validate(evidence)
            unhashed = dict(evidence)
            observed_hash = unhashed.pop("evidence_hash")
            self.assertEqual(canonical_hash(unhashed), observed_hash)
            self.assertEqual(EXPECTED_ACTIVATION, evidence["skill_activation"])
            for skill_id, expected in EXPECTED_ACTIVATION.items():
                agents = yaml.safe_load((output / "skills" / skill_id / "agents" / "openai.yaml").read_text())
                self.assertIs(agents["policy"]["allow_implicit_invocation"], expected)

    def test_staged_skill_files_are_exact_source_copies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output, _, evidence = self.build_staging(Path(directory))
            for record in evidence["files"]:
                if not record["path"].startswith("skills/"):
                    continue
                relative = record["path"].removeprefix("skills/")
                source = ROOT / relative
                staged = output / record["path"]
                self.assertEqual(source.read_bytes(), staged.read_bytes(), relative)
            writing_plans = output / "skills" / "writing-plans"
            self.assertEqual({
                "SKILL.md",
                "agents/openai.yaml",
                "tests/test_quick_skill_contract.py",
            }, {
                path.relative_to(writing_plans).as_posix()
                for path in writing_plans.rglob("*") if path.is_file()
            })

    def test_static_smoke_is_hash_bound_and_preserves_mixed_activation(self) -> None:
        smoke = load_static_smoke()
        with tempfile.TemporaryDirectory() as directory:
            output, evidence_path, evidence = self.build_staging(Path(directory))
            result = smoke.isolated_smoke(output, evidence_path)
            schema = json.loads((ROOT / "packaging" / "schemas" / "static-plugin-smoke.schema.json").read_text())
            Draft202012Validator(schema).validate(result)
            self.assertEqual(EXPECTED_ACTIVATION, {
                skill_id: record["implicit_eligible"]
                for skill_id, record in result["discovered_skills"].items()
            })
            target = output / "skills" / "writing-plans" / "SKILL.md"
            target.write_text(target.read_text(encoding="utf-8") + "\nmutation\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                smoke.isolated_smoke(output, evidence_path)
            self.assertEqual("staging", evidence["output_class"])

    def test_no_overwrite_preserves_first_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, evidence_path, evidence = self.build_staging(root)
            before = evidence_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "no-overwrite"):
                self.builder.build(ROOT, output, None, evidence_path)
            self.assertEqual(before, evidence_path.read_bytes())
            self.assertEqual(evidence["plugin_tree_hash"], self.builder.tree_hash(self.builder.inventory(
                output, [path for path in output.rglob("*") if path.is_file() or path.is_symlink()],
            )))

    def test_symlinked_output_component_is_rejected_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real"
            real.mkdir()
            linked = root / "linked"
            linked.symlink_to(real, target_is_directory=True)
            output = linked / "frontier-engineering-plugin"
            evidence = root / "plugin-build-evidence.json"
            with self.assertRaisesRegex(ValueError, "symlinked output path component"):
                self.builder.build(ROOT, output, None, evidence)
            self.assertFalse(output.exists())
            self.assertFalse(evidence.exists())


if __name__ == "__main__":
    unittest.main()
