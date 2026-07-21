from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from validate_verifier_bundle import canonical_bundle_hash, load_json, validate_bundle  # noqa: E402


SCHEMA = load_json(SKILL_ROOT / "schemas" / "verifier-bundle.schema.json")
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "verifier-bundles" / "valid-qualified.json"


class QuickVerifierBundleTests(unittest.TestCase):
    def test_valid_qualified_bundle_is_self_consistent_and_cli_accepted(self) -> None:
        bundle = load_json(FIXTURE)
        bundle["content_hash"] = canonical_bundle_hash(bundle)
        self.assertEqual([], validate_bundle(bundle, SCHEMA))
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_verifier_bundle.py"), str(FIXTURE)],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_validator_is_independent_of_deleted_workflow_runtime(self) -> None:
        source = (SCRIPTS / "validate_verifier_bundle.py").read_text(encoding="utf-8")
        self.assertNotIn("_workflow_", source)
        self.assertNotIn("route_workflow", source)


if __name__ == "__main__":
    unittest.main()
