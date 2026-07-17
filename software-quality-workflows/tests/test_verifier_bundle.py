from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import load_json  # noqa: E402
from validate_verifier_bundle import canonical_bundle_hash, validate_bundle  # noqa: E402


SCHEMA = load_json(ROOT / "schemas" / "verifier-bundle.schema.json")
FIXTURE = ROOT / "tests" / "fixtures" / "verifier-bundles" / "valid-qualified.json"


def valid_bundle() -> dict:
    value = load_json(FIXTURE)
    value["content_hash"] = canonical_bundle_hash(value)
    return value


class VerifierBundleTests(unittest.TestCase):
    def test_valid_qualified_bundle_is_frozen_self_consistent_and_cli_accepted(self) -> None:
        bundle = valid_bundle()
        self.assertEqual([], validate_bundle(bundle, SCHEMA))
        self.assertEqual(bundle["content_hash"], canonical_bundle_hash(bundle))
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_verifier_bundle.py"), str(FIXTURE)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_schema_hash_and_expected_identity_fail_closed(self) -> None:
        unknown = valid_bundle()
        unknown["unexpected"] = True
        self.assertIn("E_SCHEMA_INVALID", {item.code for item in validate_bundle(unknown, SCHEMA)})
        changed = valid_bundle()
        changed["limitations"] = ["new limitation after hash"]
        self.assertIn("E_HASH_MISMATCH", {item.code for item in validate_bundle(changed, SCHEMA)})
        bundle = valid_bundle()
        self.assertIn("E_CONTRACT_MISMATCH", {item.code for item in validate_bundle(bundle, SCHEMA, expected_contract_hash="sha256:" + "9" * 64)})
        self.assertIn("E_SOURCE_DRIFT", {item.code for item in validate_bundle(bundle, SCHEMA, expected_source_revision="other")})

    def test_oracle_graph_and_candidate_supplementary_authority_cannot_fake_qualification(self) -> None:
        duplicate = valid_bundle()
        duplicate["oracles"].append(deepcopy(duplicate["oracles"][0]))
        duplicate["content_hash"] = canonical_bundle_hash(duplicate)
        self.assertIn("E_VERIFIER_UNRESOLVED", {item.code for item in validate_bundle(duplicate, SCHEMA)})

        candidate = valid_bundle()
        candidate["oracles"][0]["authority"] = "candidate_supplementary"
        candidate["oracles"][0]["protected_from_candidate"] = False
        candidate["oracles"][0]["qualification_level"] = "independent"
        candidate["content_hash"] = canonical_bundle_hash(candidate)
        self.assertIn("E_VERIFIER_UNRESOLVED", {item.code for item in validate_bundle(candidate, SCHEMA)})

    def test_qualified_bundle_requires_stability_discrimination_independence_and_protection(self) -> None:
        weak = valid_bundle()
        for oracle in weak["oracles"]:
            oracle["qualification_level"] = "addressable"
        weak["qualification_summary"]["discrimination_evidence_refs"] = []
        weak["qualification_summary"]["independence_evidence_refs"] = []
        weak["content_hash"] = canonical_bundle_hash(weak)
        codes = {item.code for item in validate_bundle(weak, SCHEMA)}
        self.assertIn("E_VERIFIER_UNSTABLE", codes)
        self.assertIn("E_VERIFIER_NONDISCRIMINATING", codes)

        unstable_repeat = valid_bundle()
        unstable_repeat["oracles"][0]["repeat_policy"]["runs"] = 1
        unstable_repeat["oracles"][0]["repeat_policy"]["evidence_refs"] = []
        unstable_repeat["content_hash"] = canonical_bundle_hash(unstable_repeat)
        self.assertIn("E_VERIFIER_UNSTABLE", {item.code for item in validate_bundle(unstable_repeat, SCHEMA)})

        unprotected = valid_bundle()
        unprotected["oracles"][0]["protected_from_candidate"] = False
        unprotected["content_hash"] = canonical_bundle_hash(unprotected)
        self.assertIn("E_PROTECTED_SURFACE_CHANGED", {item.code for item in validate_bundle(unprotected, SCHEMA)})
        missing_surface = valid_bundle()
        missing_surface["protected_paths"] = []
        missing_surface["content_hash"] = canonical_bundle_hash(missing_surface)
        self.assertIn("E_PROTECTED_SURFACE_CHANGED", {item.code for item in validate_bundle(missing_surface, SCHEMA)})

    def test_cli_rejects_symlink_and_malformed_bundle_with_structured_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            link = root / "bundle.json"
            link.symlink_to(FIXTURE)
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_verifier_bundle.py"), str(link)],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
