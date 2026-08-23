from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _model_evolution_contract import ContractError  # noqa: E402
from _model_evolution_qualification import _apparatus_artifact  # noqa: E402


ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
SKILLS = {
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
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
    def test_apparatus_operation_uses_producer_verdict(self) -> None:
        operation = {
            "operation_id": "fake-candidate-analyze",
            "status": "pass",
            "duration_ms": 1,
            "state_revision": 0,
            "exit_code": 3,
            "diagnostic": None,
        }
        report = {
            "schema_version": "model-evolution-apparatus-report/2",
            "campaign_id": "campaign-test",
            "state_revision": 0,
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "status": "pass",
            "operations": [operation],
        }
        campaign = {
            "campaign_id": report["campaign_id"],
            "state_revision": 0,
            "product": {
                "source_commit": report["source_commit"],
                "source_tree": report["source_tree"],
            },
            "apparatus_report": {
                "root": "campaign",
                "path": "apparatus-report.json",
                "schema_version": "model-evolution-apparatus-report/2",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "apparatus-report.json"

            def validate(candidate: dict[str, object]) -> None:
                report["operations"] = [candidate]
                report_path.write_text(json.dumps(report), encoding="utf-8")
                _apparatus_artifact(campaign, ROOT, root)

            validate(operation)
            for exit_code in (True, "3", -1):
                with self.subTest(exit_code=exit_code):
                    with self.assertRaises(ContractError):
                        validate({**operation, "exit_code": exit_code})
            with self.assertRaises(ContractError):
                validate({**operation, "status": "fail"})

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
            self.assertEqual(SKILLS, {path.name for path in (plugin / "skills").iterdir()})

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
            self.assertEqual("frontier-engineering/8.0.1", smoke["bundle_id"])
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
                self.assertTrue(all(name.startswith("frontier-engineering-bundle/") for name in names))
                self.assertFalse(
                    any(
                        part in {".git", ".work", ".worktrees", "reference", "__pycache__"}
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
