from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _closure_contract import ContractInputError, canonical_contract_hash, load_contract  # noqa: E402
from freeze_closure_contract import freeze_contract  # noqa: E402
from validate_closure_contract import validate_contract  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "closure-contracts"
SCHEMA_PATH = ROOT / "schemas" / "closure-contract.schema.json"


class ClosureContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valid = json.loads((FIXTURES / "valid-minimal.json").read_text(encoding="utf-8"))
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def _object_hash(value: object) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return "sha256:" + sha256(payload).hexdigest()

    def _mutated(self, case_id: str) -> dict:
        value = deepcopy(self.valid)
        if case_id == "duplicate_id":
            value["hard_constraints"].append(deepcopy(value["hard_constraints"][0]))
        elif case_id == "hard_missing_source":
            value["hard_constraints"][0]["source_anchors"] = []
        elif case_id == "hard_missing_verifier":
            value["hard_constraints"][0]["oracle_requirement_refs"] = []
        elif case_id == "soft_hard_conflict":
            value["soft_objectives"][0]["conflicts_with_hard_constraint_refs"] = ["HC-001"]
        elif case_id == "unsafe_default":
            assumption = value["assumptions"][0]
            assumption.update({"classification": "defaulted", "materiality": "high", "decision": "accepted"})
        elif case_id == "publication_exceeds_authority":
            value["publication_policy"]["ceiling"] = "draft_pr"
        elif case_id == "unknown_corner_ref":
            value["hard_constraints"][0]["applies_to_corners"] = ["CORNER-MISSING"]
        elif case_id == "protected_write_overlap":
            value["scope"]["allowed_write_paths"].append(".closure/**")
        elif case_id == "unresolved_ambiguity":
            value["ambiguities"].append(
                {
                    "id": "AMB-001",
                    "statement": "A material choice has no authoritative distinction.",
                    "materiality": "high",
                    "status": "unresolved",
                    "terminal_status": "SPEC_UNDERDETERMINED",
                    "minimal_missing_information": ["One authoritative choice between the two public semantics."],
                }
            )
        elif case_id == "reverse_plan_ref":
            value["request"]["source_anchors"].append("plan:P-001")
        elif case_id == "unknown_terminal_status":
            value["terminal_policy"]["allowed_statuses"].append("WAIT_FOR_USER")
        elif case_id == "frozen_hash_mismatch":
            value.update(
                {
                    "status": "frozen",
                    "frozen_at": "2026-07-14T01:00:00Z",
                    "content_hash": "sha256:" + "0" * 64,
                }
            )
        elif case_id == "no_hard_constraint":
            value["hard_constraints"] = []
        else:
            raise AssertionError(f"unknown negative case: {case_id}")
        return value

    def test_valid_minimal_contract_passes_freeze_validation(self) -> None:
        self.assertEqual([], validate_contract(self.valid, self.schema, for_freeze=True))

    def test_all_negative_fixtures_have_stable_semantic_codes(self) -> None:
        index = json.loads((FIXTURES / "invalid-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(13, len(index["cases"]))
        for case in index["cases"]:
            with self.subTest(case=case["id"]):
                value = self._mutated(case["id"])
                violations = validate_contract(value, self.schema, for_freeze=case["id"] != "frozen_hash_mismatch")
                self.assertIn(case["expected_code"], {item.code for item in violations})

    def test_scope_and_authority_bindings_fail_closed(self) -> None:
        violations = validate_contract(
            self.valid,
            self.schema,
            for_freeze=True,
            expected_scope_hash="sha256:" + "9" * 64,
            authority_ceiling="read_only",
        )
        self.assertTrue({"contract.scope-mismatch", "contract.authority-mismatch"} <= {item.code for item in violations})

    def test_freeze_is_atomic_separate_read_only_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = root / "contract.draft.json"
            lock = root / "contract.lock.json"
            draft.write_text(json.dumps(self.valid), encoding="utf-8")
            result = freeze_contract(
                draft,
                lock,
                SCHEMA_PATH,
                frozen_at="2026-07-14T01:00:00Z",
                expected_scope_hash=self.valid["source"]["scope_hash"],
                authority_ceiling="local_reversible",
                expected_base_revision=self.valid["source"]["base_revision"],
                expected_policy_bundle_hash=self.valid["source"]["policy_bundle_hash"],
                expected_authority_hash=self._object_hash(self.valid["authority"]),
            )
            frozen = load_contract(lock)
            self.assertEqual("frozen", frozen["status"])
            self.assertEqual(canonical_contract_hash(frozen), frozen["content_hash"])
            self.assertEqual("contract_frozen", result["event"]["event_type"])
            self.assertEqual(self.valid["source"]["scope_hash"], result["event"]["scope_hash"])
            self.assertEqual(self.valid["source"]["policy_bundle_hash"], result["event"]["policy_bundle_hash"])
            self.assertFalse(lock.stat().st_mode & stat.S_IWUSR)
            self.assertEqual("draft", json.loads(draft.read_text(encoding="utf-8"))["status"])
            with self.assertRaises(ContractInputError):
                freeze_contract(
                    draft,
                    lock,
                    SCHEMA_PATH,
                    frozen_at="2026-07-14T01:00:00Z",
                    expected_scope_hash=self.valid["source"]["scope_hash"],
                    authority_ceiling="local_reversible",
                    expected_base_revision=self.valid["source"]["base_revision"],
                    expected_policy_bundle_hash=self.valid["source"]["policy_bundle_hash"],
                    expected_authority_hash=self._object_hash(self.valid["authority"]),
                )
            os.chmod(lock, 0o600)
            with self.assertRaises(ContractInputError):
                freeze_contract(
                    draft,
                    draft,
                    SCHEMA_PATH,
                    frozen_at="2026-07-14T01:00:00Z",
                    expected_scope_hash=self.valid["source"]["scope_hash"],
                    authority_ceiling="local_reversible",
                    expected_base_revision=self.valid["source"]["base_revision"],
                    expected_policy_bundle_hash=self.valid["source"]["policy_bundle_hash"],
                    expected_authority_hash=self._object_hash(self.valid["authority"]),
                )

    def test_freeze_requires_admission_scope_and_authority_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "contract.draft.json"
            draft.write_text(json.dumps(self.valid), encoding="utf-8")
            with self.assertRaises(ContractInputError):
                freeze_contract(draft, Path(directory) / "missing-scope.json", SCHEMA_PATH, frozen_at="2026-07-14T01:00:00Z", authority_ceiling="local_reversible")
            with self.assertRaises(ContractInputError):
                freeze_contract(draft, Path(directory) / "missing-authority.json", SCHEMA_PATH, frozen_at="2026-07-14T01:00:00Z", expected_scope_hash=self.valid["source"]["scope_hash"])

    def test_freeze_requires_source_policy_and_full_authority_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "contract.draft.json"
            draft.write_text(json.dumps(self.valid), encoding="utf-8")
            common = {
                "expected_scope_hash": self.valid["source"]["scope_hash"],
                "authority_ceiling": "local_reversible",
                "expected_base_revision": self.valid["source"]["base_revision"],
                "expected_policy_bundle_hash": self.valid["source"]["policy_bundle_hash"],
                "expected_authority_hash": self._object_hash(self.valid["authority"]),
            }
            for missing in ("expected_base_revision", "expected_policy_bundle_hash", "expected_authority_hash"):
                with self.subTest(missing=missing), self.assertRaises(ContractInputError):
                    freeze_contract(draft, Path(directory) / f"{missing}.json", SCHEMA_PATH, frozen_at="2026-07-14T01:00:00Z", **{key: value for key, value in common.items() if key != missing})

    def test_source_policy_and_authority_hash_mismatches_fail_closed(self) -> None:
        violations = validate_contract(
            self.valid,
            self.schema,
            for_freeze=True,
            expected_base_revision="different-revision",
            expected_policy_bundle_hash="sha256:" + "8" * 64,
            expected_authority_hash="sha256:" + "7" * 64,
        )
        self.assertTrue({"contract.source-mismatch", "contract.policy-mismatch", "contract.authority-mismatch"} <= {item.code for item in violations})

    def test_freeze_rejects_empty_anchors_scope_protection_and_authority_conflict(self) -> None:
        value = deepcopy(self.valid)
        value["request"]["source_anchors"] = []
        value["scope"]["allowed_read_paths"] = []
        value["scope"]["allowed_write_paths"] = []
        value["protected_surfaces"] = []
        value["authority"]["preauthorized_external_actions"] = ["publish"]
        violations = validate_contract(value, self.schema, for_freeze=True)
        self.assertTrue(
            {"contract.request-source-missing", "contract.read-scope-missing", "contract.write-scope-missing", "contract.protected-surface-missing", "contract.authority-conflict"}
            <= {item.code for item in violations}
        )

    def test_freeze_semantics_require_corners_oracles_and_ordered_time(self) -> None:
        no_corner = deepcopy(self.valid)
        no_corner["hard_constraints"][0]["applies_to_corners"] = []
        self.assertIn("contract.hard-corner-missing", {item.code for item in validate_contract(no_corner, self.schema, for_freeze=True)})
        no_oracle = deepcopy(self.valid)
        no_oracle["verifier_requirements"][0]["allowed_oracle_classes"] = []
        self.assertIn("contract.verifier-oracle-missing", {item.code for item in validate_contract(no_oracle, self.schema, for_freeze=True)})
        frozen = deepcopy(self.valid)
        frozen.update({"status": "frozen", "frozen_at": None})
        frozen["content_hash"] = canonical_contract_hash(frozen)
        self.assertIn("contract.frozen-time-missing", {item.code for item in validate_contract(frozen, self.schema)})
        frozen["frozen_at"] = "2026-07-13T00:00:00Z"
        frozen["content_hash"] = canonical_contract_hash(frozen)
        self.assertIn("contract.time-order", {item.code for item in validate_contract(frozen, self.schema)})

    def test_contract_cannot_bind_future_candidate_identity(self) -> None:
        value = deepcopy(self.valid)
        value["request"]["source_anchors"].append("candidate:CAND-001")
        self.assertIn("contract.candidate-ref", {item.code for item in validate_contract(value, self.schema, for_freeze=True)})

    def test_freeze_rejects_softened_hard_rules_unsafe_paths_and_unbound_anchors(self) -> None:
        value = deepcopy(self.valid)
        value["hard_constraints"][0]["blocking"] = False
        value["hard_constraints"][0]["protected_from_candidate"] = False
        value["hard_constraints"][0]["source_anchors"] = ["unbound prose"]
        value["scope"]["allowed_write_paths"] = ["../outside/**"]
        value["source"]["observed_at"] = "2026-07-14T00:00:00"
        codes = {item.code for item in validate_contract(value, self.schema, for_freeze=True)}
        self.assertTrue(
            {"contract.hard-nonblocking", "contract.hard-unprotected", "contract.anchor-invalid", "contract.path-unsafe", "contract.time-invalid"} <= codes
        )

    def test_strict_loader_rejects_duplicate_keys_and_deep_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.json"
            duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            with self.assertRaises(ContractInputError):
                load_contract(duplicate)
            deep = Path(directory) / "deep.json"
            value: object = "leaf"
            for _ in range(45):
                value = {"nested": value}
            deep.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ContractInputError):
                load_contract(deep)
            oversized = Path(directory) / "oversized.json"
            oversized.write_text(json.dumps({"value": "x" * (2 * 1024 * 1024)}), encoding="utf-8")
            with self.assertRaises(ContractInputError):
                load_contract(oversized)
            target = Path(directory) / "target.json"
            target.write_text(json.dumps(self.valid), encoding="utf-8")
            link = Path(directory) / "contract-link.json"
            link.symlink_to(target)
            with self.assertRaises(ContractInputError):
                load_contract(link)
            nonfinite = Path(directory) / "nonfinite.json"
            nonfinite.write_text('{"value": NaN}', encoding="utf-8")
            with self.assertRaises(ContractInputError):
                load_contract(nonfinite)

    def test_validator_cli_is_total_and_emits_json(self) -> None:
        valid = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "validate_closure_contract.py"), "--schema", str(SCHEMA_PATH), "--for-freeze", str(FIXTURES / "valid-minimal.json")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertTrue(json.loads(valid.stdout)["ok"])
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "validate_closure_contract.py"), "--schema", str(SCHEMA_PATH), str(malformed)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
