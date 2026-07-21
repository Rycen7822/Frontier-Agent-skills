from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_static_contracts.py"
REPORT = ROOT / "evaluation" / "static-contract-diagnostic.json"


def load_checker():
    spec = importlib.util.spec_from_file_location("static_contract_checker", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load static contract checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuickStaticContractDiagnosticTests(unittest.TestCase):
    def test_checked_report_matches_deterministic_builder_and_exact_paths(self) -> None:
        checker = load_checker()
        first = checker.build_report(ROOT)
        second = checker.build_report(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(first, json.loads(REPORT.read_text(encoding="utf-8")))
        expected_paths = [path.relative_to(ROOT).as_posix() for path in checker.model_facing_paths(ROOT)]
        self.assertEqual(expected_paths, first["model_facing_files_checked"])
        self.assertEqual("static_contract_diagnostic", first["classification"])
        self.assertEqual(checker.LIMITATIONS, first["limitations"])
        profile_hashes = list(first["profile_command_hashes"].values())
        self.assertEqual(3, len(profile_hashes))
        self.assertEqual(3, len(set(profile_hashes)))

    def test_check_command_passes_without_model_claims(self) -> None:
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
        report = json.loads(REPORT.read_text(encoding="utf-8"))
        self.assertIn("Does not test natural routing", report["limitations"])
        self.assertEqual([], report["legacy_runtime_paths_present"])
        self.assertEqual([], report["legacy_protocol_matches"])
        self.assertEqual([], report["brainstorming_runtime_copies"])


if __name__ == "__main__":
    unittest.main()
