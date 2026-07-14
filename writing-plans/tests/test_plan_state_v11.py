from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _closure_contract import canonical_contract_hash  # noqa: E402
from _plan_state import canonical_state_hash, validate_against_schema  # noqa: E402
import migrate_plan_state as migration_module  # noqa: E402
from migrate_plan_state import MigrationError, migrate_plan_state, write_migration  # noqa: E402
from check_plan_freshness import check_freshness  # noqa: E402
from render_context_capsule import render as render_capsule  # noqa: E402
from render_plan_profile import render_program  # noqa: E402
from validate_plan_state import semantic_violations  # noqa: E402


STATE_FIXTURES = ROOT / "tests" / "fixtures" / "plan-state"
CONTRACT_FIXTURES = ROOT / "tests" / "fixtures" / "closure-contracts"
SCHEMA_PATH = ROOT / "schemas" / "plan-state.schema.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class PlanStateV11Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = _load(STATE_FIXTURES / "valid-program.json")
        self.v1 = _load(STATE_FIXTURES / "v1-program.json")
        self.schema = _load(SCHEMA_PATH)
        self.contract = _load(CONTRACT_FIXTURES / "valid-minimal.json")
        self.contract.update({"status": "frozen", "frozen_at": "2026-07-14T01:00:00Z"})
        self.contract["content_hash"] = canonical_contract_hash(self.contract)

    def _closure_state(self) -> dict:
        state = deepcopy(self.state)
        state["execution_policy"] = "autonomous_closure"
        state["profile"] = "program"
        state["source"].update(
            {
                "base_revision": self.contract["source"]["base_revision"],
                "scope_hash": self.contract["source"]["scope_hash"],
                "policy_bundle_hash": self.contract["source"]["policy_bundle_hash"],
            }
        )
        state["closure_contract_ref"] = {
            "artifact_ref": "artifact:closure-contract/CC-DEMO-001",
            "content_hash": self.contract["content_hash"],
            "epoch": self.contract["epoch"],
        }
        for evidence in state["evidence"]:
            if evidence.get("status") == "observed" and evidence.get("freshness_policy", {}).get("kind") == "source_bound":
                evidence["source_revision"] = self.contract["source"]["base_revision"]
        for node in state["nodes"]:
            node["constraint_refs"] = ["HC-001"]
            node["corner_refs"] = ["CORNER-LOCAL-001"]
            node["verifier_requirement_refs"] = ["VR-BEHAVIOR-001"]
        state["content_hash"] = canonical_state_hash(state)
        return state

    def test_schema_is_1_1_and_requires_policy_decision_and_node_fields(self) -> None:
        self.assertEqual("1.1", self.schema["properties"]["schema_version"]["const"])
        self.assertTrue({"execution_policy"} <= set(self.schema["required"]))
        decision_required = set(self.schema["$defs"]["decision"]["required"])
        node_required = set(self.schema["$defs"]["node"]["required"])
        self.assertTrue({"provenance", "materiality", "reversibility", "contract_effect"} <= decision_required)
        self.assertTrue({"constraint_refs", "corner_refs", "verifier_requirement_refs"} <= node_required)
        self.assertEqual([], validate_against_schema(self.state, self.schema))
        self.assertTrue(validate_against_schema(self.v1, self.schema))

    def test_standard_plan_forbids_contract_ref(self) -> None:
        state = deepcopy(self.state)
        state["closure_contract_ref"] = {"artifact_ref": "artifact:closure-contract/x", "content_hash": "sha256:" + "1" * 64, "epoch": 1}
        self.assertIn("plan.contract-forbidden", {item.code for item in semantic_violations(state)})

    def test_autonomous_policy_requires_program_and_frozen_contract(self) -> None:
        state = deepcopy(self.state)
        state["execution_policy"] = "autonomous_closure"
        state["profile"] = "handoff"
        codes = {item.code for item in semantic_violations(state)}
        self.assertTrue({"plan.contract-missing", "plan.contract-profile"} <= codes)

    def test_closure_plan_resolves_contract_refs_and_identity(self) -> None:
        state = self._closure_state()
        contract_codes = {item.code for item in semantic_violations(state, closure_contract=self.contract) if item.code.startswith("plan.contract") or item.code.startswith("plan.node-contract")}
        self.assertEqual(set(), contract_codes)

    def test_contract_hash_epoch_source_and_node_ref_mismatches_fail(self) -> None:
        mutations = {
            "hash": ("plan.contract-stale", lambda state: state["closure_contract_ref"].update({"content_hash": "sha256:" + "9" * 64})),
            "epoch": ("plan.contract-stale", lambda state: state["closure_contract_ref"].update({"epoch": 2})),
            "source": ("plan.contract-source-mismatch", lambda state: state["source"].update({"base_revision": "other"})),
            "constraint": ("plan.node-contract-ref", lambda state: state["nodes"][0].update({"constraint_refs": ["HC-MISSING"]})),
            "plan_hash": ("plan.contract-plan-hash", lambda state: state.update({"content_hash": None})),
            "scope": ("plan.contract-scope-mismatch", lambda state: state["scope"]["allowed_writes"].append("outside/**")),
        }
        for name, (expected, mutate) in mutations.items():
            with self.subTest(name=name):
                state = self._closure_state()
                mutate(state)
                self.assertIn(expected, {item.code for item in semantic_violations(state, closure_contract=self.contract)})

    def test_validator_cli_loads_and_binds_frozen_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "plan.json"
            contract_path = Path(directory) / "contract.lock.json"
            state_path.write_text(json.dumps(self._closure_state()), encoding="utf-8")
            contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "validate_plan_state.py"), str(state_path), "--schema", str(SCHEMA_PATH), "--closure-contract", str(contract_path), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_program_and_capsule_derive_bounded_contract_projection(self) -> None:
        state = self._closure_state()
        state["gaps"][0]["blocks"] = ["P-01"]
        state["content_hash"] = canonical_state_hash(state)
        program = render_program(state, closure_contract=self.contract, state_ref="plan.json")
        self.assertIn("Execution policy: autonomous_closure", program)
        self.assertIn(self.contract["content_hash"], program)
        self.assertIn("## Constraint coverage", program)
        self.assertIn("HC-001", program)
        self.assertIn("## Strategy families", program)
        self.assertNotIn(self.contract["hard_constraints"][0]["statement"], program)
        with self.assertRaises(ValueError):
            render_program({"plan_id": "caller-shaped", "constraint_coverage": ["HC-INVENTED"]}, closure_contract=self.contract)

        capsule, metadata = render_capsule(
            state,
            "P-01",
            12000,
            closure_contract=self.contract,
            runtime_projection={"incumbent_artifact_ref": "artifact:candidate/C-001", "hard_failure_refs": ["CE-001"], "remaining_budget": {"iterations": 3}},
        )
        self.assertIn("Contract:", capsule)
        self.assertIn("Constraints: HC-001", capsule)
        self.assertIn("Blocking plan gaps: G-01", capsule)
        self.assertIn("Incumbent: artifact:candidate/C-001", capsule)
        self.assertIn("Hard failures: CE-001", capsule)
        self.assertNotIn(self.contract["hard_constraints"][0]["statement"], capsule)
        self.assertEqual(self.contract["content_hash"], metadata["contract_hash"])

    def test_projection_apis_reject_tampered_contract_refs_and_unbounded_runtime(self) -> None:
        state = self._closure_state()
        tampered = deepcopy(self.contract)
        tampered["hard_constraints"][0]["statement"] = "Tampered after freeze"
        with self.assertRaises(ValueError):
            render_program(state, closure_contract=tampered)
        with self.assertRaises(ValueError):
            render_capsule(state, "P-01", 12000, closure_contract=tampered)

        bad_ref = self._closure_state()
        bad_ref["nodes"][0]["constraint_refs"] = ["HC-MISSING"]
        bad_ref["content_hash"] = canonical_state_hash(bad_ref)
        with self.assertRaises(ValueError):
            render_program(bad_ref, closure_contract=self.contract)
        with self.assertRaises(ValueError):
            render_capsule(bad_ref, "P-01", 12000, closure_contract=self.contract)

        for runtime in (
            {"raw_logs": ["unbounded"]},
            {"hard_failure_refs": "CE-001"},
            {"remaining_budget": {"raw_log": "not a budget"}},
        ):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                render_capsule(state, "P-01", 12000, closure_contract=self.contract, runtime_projection=runtime)

    def test_freshness_contract_epoch_policy_and_epoch_decision_are_global(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = self._closure_state()
            state["snapshots"] = []
            state["content_hash"] = canonical_state_hash(state)
            state_path = root / "plan.json"
            contract_path = root / "contract.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
            fresh = check_freshness(
                state_path,
                repository_override=root,
                closure_contract_path=contract_path,
                current_policy_bundle_hash=self.contract["source"]["policy_bundle_hash"],
            )
            self.assertEqual("fresh", fresh["status"], fresh)

            changed = deepcopy(self.contract)
            changed["epoch"] = 2
            changed["content_hash"] = canonical_contract_hash(changed)
            contract_path.write_text(json.dumps(changed), encoding="utf-8")
            stale = check_freshness(
                state_path,
                repository_override=root,
                closure_contract_path=contract_path,
                current_policy_bundle_hash="sha256:" + "8" * 64,
            )
            self.assertEqual("stale", stale["status"])
            self.assertTrue({node["id"] for node in state["nodes"]} <= set(stale["affected_ids"]))
            self.assertTrue({"contract_epoch_changed", "policy_bundle_changed"} <= {issue["kind"] for issue in stale["issues"]})

    def test_candidate_identity_and_unsafe_default_never_enter_plan(self) -> None:
        state = self._closure_state()
        state["nodes"][0]["inputs"].append("candidate:CAND-001")
        state["decisions"][0].update({"provenance": "default_policy", "materiality": "high"})
        codes = {item.code for item in semantic_violations(state, closure_contract=self.contract)}
        self.assertTrue({"plan.candidate-id", "plan.default-unsafe"} <= codes)

    def test_v1_migration_is_deterministic_valid_and_noninventing(self) -> None:
        policy_hash = "sha256:" + "2" * 64
        first, report = migrate_plan_state(self.v1, policy_bundle_hash=policy_hash)
        second, second_report = migrate_plan_state(self.v1, policy_bundle_hash=policy_hash)
        self.assertEqual(first, second)
        self.assertEqual(report, second_report)
        self.assertEqual("1.1", first["schema_version"])
        self.assertEqual("standard", first["execution_policy"])
        self.assertNotIn("closure_contract_ref", first)
        self.assertEqual([], report["unresolved"])
        self.assertEqual(canonical_state_hash(first), first["content_hash"])
        self.assertEqual([], validate_against_schema(first, self.schema))
        self.assertEqual([], semantic_violations(first))

        unresolved = deepcopy(self.v1)
        unresolved["decisions"][0]["evidence_refs"] = []
        migrated, unresolved_report = migrate_plan_state(unresolved, policy_bundle_hash=policy_hash)
        self.assertNotIn("provenance", migrated["decisions"][0])
        self.assertEqual([{"decision_id": "D-01", "field": "provenance", "reason": "no explicit repository or design-audit source"}], unresolved_report["unresolved"])

    def test_migration_write_is_atomic_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v1.json"
            output = root / "v11.json"
            report = root / "migration-report.json"
            source.write_text(json.dumps(self.v1), encoding="utf-8")
            result = write_migration(source, output, report, policy_bundle_hash="sha256:" + "2" * 64)
            self.assertEqual(result["state_hash"], _load(output)["content_hash"])
            report_value = _load(report)
            self.assertEqual(result["report_hash"], report_value["report_hash"])
            self.assertEqual(canonical_state_hash(self.v1), report_value["source_state_hash"])
            with self.assertRaises(MigrationError):
                write_migration(source, output, report, policy_bundle_hash="sha256:" + "2" * 64)

    def test_migration_rejects_symlink_input_and_rolls_back_split_output_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "v1.json"
            source.write_text(json.dumps(self.v1), encoding="utf-8")
            symlink = root / "v1-link.json"
            symlink.symlink_to(source)
            with self.assertRaises(MigrationError):
                write_migration(symlink, root / "symlink-output.json", root / "symlink-report.json", policy_bundle_hash="sha256:" + "2" * 64)

            output = root / "race-output.json"
            report = root / "race-report.json"
            real_link = os.link
            calls = 0

            def raced_link(source_path: object, target_path: object) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    Path(target_path).write_text("{}", encoding="utf-8")
                    raise FileExistsError(str(target_path))
                real_link(source_path, target_path)

            with patch.object(migration_module.os, "link", side_effect=raced_link), self.assertRaises(MigrationError):
                write_migration(source, output, report, policy_bundle_hash="sha256:" + "2" * 64)
            self.assertFalse(output.exists(), "state output must roll back when report publication loses a race")

    def test_migration_cli_rejects_non_v1_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "v11.json"
            source.write_text(json.dumps(self.state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPTS / "migrate_plan_state.py"), str(source), "--output", str(Path(directory) / "out.json"), "--report", str(Path(directory) / "report.json"), "--policy-bundle-hash", "sha256:" + "2" * 64],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
