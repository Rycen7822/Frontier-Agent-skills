from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSIONS = {
    "long-document-segmented-writing": "1.1.0",
    "skill-evaluator": "3.3.3",
    "software-quality-workflows": "9.0.3",
    "writing-plans": "8.2.4",
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuickBundleContractTests(unittest.TestCase):
    def test_source_and_generated_bundle_are_exact_and_deterministic(self) -> None:
        source = json.loads((ROOT / "bundle-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("3.0", source["bundle_schema_version"])
        self.assertEqual("6.3.0", source["bundle_version"])
        self.assertEqual(EXPECTED_VERSIONS, {item["id"]: item["version"] for item in source["skills"]})
        self.assertEqual({"quick", "extended", "release"}, set(source["test_profiles"]))
        self.assertEqual(3, len({tuple(commands) for commands in source["test_profiles"].values()}))
        extended = source["test_profiles"]["extended"]
        required_modules = {
            2: {
                "tests/test_extended_codex_eval_host.py",
                "tests/test_model_evolution_materialization.py",
                "tests/test_extended_runner_lifecycle.py",
                "tests/test_extended_lifecycle_conformance.py",
            },
            3: {
                "tests/test_extended_eval_comparison.py",
                "tests/test_extended_eval_revision.py",
                "tests/test_extended_eval_transition.py",
            },
        }
        for command_index, expected in required_modules.items():
            command_modules = set(shlex.split(extended[command_index]))
            self.assertLessEqual(expected, command_modules)
            for module in expected:
                self.assertEqual(1, sum(module in shlex.split(command) for command in extended), module)

        builder = load_module("frontier_bundle_builder", ROOT / "bundle" / "build_bundle_manifest.py")
        generated = json.loads((ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(builder.build_manifest(), generated)
        self.assertEqual("frontier-engineering-bundle/2.0", generated["schema_version"])
        self.assertEqual(5, generated["compatible_schema_epoch"])
        self.assertEqual(EXPECTED_VERSIONS, {key: value["version"] for key, value in generated["skills"].items()})
        self.assertEqual(
            {"version", "allow_implicit_invocation", "root_hash"},
            set(next(iter(generated["skills"].values()))),
        )

    def test_packaging_owners_use_the_same_four_skill_identity(self) -> None:
        expected = set(EXPECTED_VERSIONS)
        modules = {
            "plugin": ROOT / "scripts" / "build_codex_plugin.py",
            "archive": ROOT / "scripts" / "build_source_archive.py",
            "static_smoke": ROOT / "scripts" / "smoke_codex_plugin.py",
            "cli_smoke": ROOT / "scripts" / "smoke_codex_cli_install.py",
        }
        for name, path in modules.items():
            module = load_module(f"contract_{name}", path)
            self.assertEqual(expected, set(module.EXPECTED_SKILLS), name)

        schema_names = (
            "plugin-build-evidence.schema.json", "source-archive-evidence.schema.json",
            "static-plugin-smoke.schema.json", "cli-install-smoke.schema.json",
            "release-authorization-v1.schema.json",
        )
        for name in schema_names:
            text = (ROOT / "packaging" / "schemas" / name).read_text(encoding="utf-8")
            self.assertNotIn('"brainstorming"', text, name)
            self.assertNotIn('frontier-engineering/4.0.0', text, name)

    def test_builder_check_passes_without_mutating_output(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(ROOT / "bundle" / "build_bundle_manifest.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
        self.assertIn("Frontier 6.3", help_result.stdout)
        self.assertNotIn("Frontier 5.0", help_result.stdout)
        result = subprocess.run(
            [sys.executable, str(ROOT / "bundle" / "build_bundle_manifest.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
