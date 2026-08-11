from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_static_contracts.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("static_contract_checker", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load static contract checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuickStaticContractDiagnosticTests(unittest.TestCase):
    def test_model_facing_graph_recurses_and_fails_closed(self) -> None:
        checker = load_checker()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "docs" / "nested").mkdir(parents=True)
            (root / "declared").mkdir()
            (root / "entry.md").write_text(
                "[child](docs/child.md)\n[data](asset.json)\n[missing](missing.md)\n"
                "[escape](../outside.md)\n[symlink](asset-link.json)\n",
                encoding="utf-8",
            )
            (root / "docs" / "child.md").write_text(
                "[grandchild](nested/grandchild.md)\n", encoding="utf-8"
            )
            (root / "docs" / "nested" / "grandchild.md").write_text(
                "[cycle](../child.md)\n", encoding="utf-8"
            )
            (root / "asset.json").write_text("{}\n", encoding="utf-8")
            (root / "declared" / "seed.txt").write_text("seed\n", encoding="utf-8")
            (root / "asset-link.json").symlink_to(root / "asset.json")

            paths, errors = checker.model_facing_graph(root, ("entry.md",), ("declared",))
            relative_paths = {path.relative_to(root).as_posix() for path in paths}
            self.assertEqual(
                {"asset.json", "declared/seed.txt", "docs/child.md", "docs/nested/grandchild.md", "entry.md"},
                relative_paths,
            )
            self.assertEqual(
                {"../outside.md", "asset-link.json", "missing.md"},
                {item["target"] for item in errors},
            )

    def test_live_report_is_deterministic_and_source_bound(self) -> None:
        checker = load_checker()
        first = checker.build_report(ROOT)
        second = checker.build_report(ROOT)
        self.assertEqual(first, second)
        expected_paths = [path.relative_to(ROOT).as_posix() for path in checker.model_facing_paths(ROOT)]
        self.assertEqual(expected_paths, first["model_facing_files_checked"])
        self.assertEqual("static_contract_diagnostic", first["classification"])
        self.assertEqual("frontier-engineering/7.0.0", first["bundle_id"])
        self.assertEqual("7.0.0", first["version"])
        self.assertEqual(6, first["schema_epoch"])
        self.assertEqual("4.0.0", first["skill_versions"]["skill-evaluator"])
        self.assertEqual(checker.LIMITATIONS, first["limitations"])

    def test_check_command_passes_without_model_claims(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, help_result.returncode, help_result.stdout + help_result.stderr)
        self.assertIn("Evaluate the current Frontier static contracts from source", help_result.stdout)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            {"ok": True, "blocking_facts": 0}, json.loads(result.stdout)
        )

        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "static-evidence.json"
            emitted = subprocess.run(
                [sys.executable, str(SCRIPT), "--check", "--output", str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(0, emitted.returncode, emitted.stdout + emitted.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual([], report["markdown_link_errors"])


if __name__ == "__main__":
    unittest.main()
