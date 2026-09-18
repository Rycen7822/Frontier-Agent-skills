from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_codex_plugin import build, validate_plugin_build  # noqa: E402
from _bundle_hash import inventory, tree_hash  # noqa: E402
from _deterministic_zip import verify_deterministic_zip  # noqa: E402
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
SKILLS = {
    'code-review',
    'code-simplifier',
    'codebase-investigation',
    'debugging',
    'long-document-segmented-writing',
    'runtime-verification',
    'skill-evaluator',
    'software-design',
    'software-quality-workflows',
    'writing-plans',
}


def run_script(relative: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative), *arguments],
        cwd=ROOT,
        env=ENV,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


class ExtendedRelease(unittest.TestCase):
    def test_marketplace_build_preserves_outputs_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            marketplace = work / "marketplace"
            plugin = marketplace / "plugins" / "frontier-engineering-plugin"
            evidence = work / "build.json"
            archive = work / "marketplace.zip"
            build(ROOT, plugin, evidence, marketplace, archive)
            validate_plugin_build(plugin, evidence, source_root=ROOT)
            members = [
                (path.relative_to(marketplace).as_posix(), path, path.stat().st_mode & 0o777)
                for path in sorted(marketplace.rglob("*")) if path.is_file()
            ]
            verify_deterministic_zip(archive, members)
            original = evidence.read_bytes(), archive.read_bytes()
            with self.assertRaises(ValueError):
                build(ROOT, plugin, evidence, marketplace, archive)
            self.assertEqual(original, (evidence.read_bytes(), archive.read_bytes()))
            skill = plugin / "skills" / "writing-plans" / "SKILL.md"
            skill.write_text(skill.read_text() + "\nUnexpected package mutation.\n")
            with self.assertRaises(ValueError):
                validate_plugin_build(plugin, evidence, source_root=ROOT)
            changed = json.loads(evidence.read_text())
            changed["files"] = inventory(plugin, [path for path in plugin.rglob("*") if path.is_file()])
            changed["plugin_tree_hash"] = tree_hash(changed["files"])
            evidence.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                validate_plugin_build(plugin, evidence, source_root=ROOT)

    def test_plugin_build_and_static_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            plugin = work / "frontier-engineering-plugin"
            evidence = work / "build.json"
            built = run_script(
                "scripts/build_codex_plugin.py",
                "--source-root",
                str(ROOT),
                "--output",
                str(plugin),
                "--evidence-output",
                str(evidence),
            )
            self.assertEqual(0, built.returncode, built.stdout + built.stderr)
            self.assertEqual(
                SKILLS, {path.name for path in (plugin / "skills").iterdir()}
            )

            smoke_path = work / "smoke.json"
            smoked = run_script(
                "scripts/smoke_codex_plugin.py",
                "--plugin-root",
                str(plugin),
                "--build-evidence",
                str(evidence),
                "--output",
                str(smoke_path),
            )
            self.assertEqual(0, smoked.returncode, smoked.stdout + smoked.stderr)
            smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
            self.assertEqual("frontier-engineering/11.1.0", smoke["bundle_id"])
            self.assertFalse(smoke["actual_codex_cli_install"])

    def test_source_archives_are_clean_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            bundle_bytes = []
            for ordinal in range(2):
                archive = work / f"bundle-{ordinal}.zip"
                evidence = work / f"bundle-{ordinal}.json"
                result = run_script(
                    "scripts/build_source_archive.py",
                    "--source-root",
                    str(ROOT),
                    "--output",
                    str(archive),
                    "--evidence-output",
                    str(evidence),
                    "--layout",
                    "bundle",
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                bundle_bytes.append(archive.read_bytes())
                with zipfile.ZipFile(archive) as source:
                    names = source.namelist()
                self.assertTrue(
                    all(
                        name.startswith("frontier-engineering-bundle/")
                        for name in names
                    )
                )
                self.assertFalse(
                    any(
                        part
                        in {".git", ".work", ".worktrees", "reference", "__pycache__"}
                        for name in names
                        for part in Path(name).parts
                    )
                )
            self.assertEqual(bundle_bytes[0], bundle_bytes[1])

            skills_archive = work / "skills.zip"
            skills_evidence = work / "skills.json"
            result = run_script(
                "scripts/build_source_archive.py",
                "--source-root",
                str(ROOT),
                "--output",
                str(skills_archive),
                "--evidence-output",
                str(skills_evidence),
                "--layout",
                "skills_only",
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            with zipfile.ZipFile(skills_archive) as source:
                roots = {Path(name).parts[0] for name in source.namelist()}
            self.assertEqual(SKILLS, roots)


if __name__ == "__main__":
    unittest.main()
