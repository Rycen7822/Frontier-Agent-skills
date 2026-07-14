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

from _plan_state import MAX_INPUT_BYTES, PlanInputError, canonical_state_hash, file_hash, load_json  # noqa: E402
from check_plan_freshness import check_freshness, propagate_affected  # noqa: E402
from render_context_capsule import render  # noqa: E402
from render_plan_profile import add_novice_projection, render_brief, render_program  # noqa: E402
from validate_plan_state import validate_file  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "plan-state"
SCHEMA_PATH = ROOT / "schemas" / "plan-state.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _base() -> dict:
    return json.loads((FIXTURES / "valid-program.json").read_text(encoding="utf-8"))


def _node(state: dict, node_id: str) -> dict:
    return next(item for item in state["nodes"] if item["id"] == node_id)


def _validate(state: dict) -> list:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "plan.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return validate_file(path, SCHEMA_PATH)[1]


def _mutate(state: dict, name: str) -> None:
    if name == "schema_unknown_field":
        state["unknown_field"] = True
    elif name == "duplicate_id":
        duplicate = deepcopy(state["facts"][0])
        state["facts"].append(duplicate)
    elif name == "missing_ref":
        _node(state, "P-02")["depends_on"] = ["P-404"]
    elif name == "control_cycle":
        state["edges"].append({"id": "X-04", "kind": "control", "from": "P-02", "to": "P-01", "sensitivity": {"fields": []}})
    elif name == "stale_frontier":
        _node(state, "P-02")["status"] = "blocked"
    elif name == "done_without_evidence":
        _node(state, "P-02")["status"] = "done"
        state["current_frontier"] = []
    elif name == "scope_write":
        _node(state, "P-02")["write_set"].append("/etc/passwd")
    elif name == "source_stale":
        state["content_hash"] = "sha256:" + "f" * 64
    elif name == "snapshot_unbound":
        state["snapshots"][0]["kind"] = "line"
        state["snapshots"][0]["line_start"] = 1
    elif name == "retry_unsafe":
        node = _node(state, "P-02")
        node["side_effect_level"] = "external_non_idempotent"
        node["retry"] = {"allowed": True, "max_attempts": 2, "idempotency": "inspect_before_retry"}
    elif name == "approval_missing":
        _node(state, "P-02")["side_effect_level"] = "external_reversible"
    elif name == "effect_conflict":
        clone = deepcopy(_node(state, "P-02"))
        clone["id"] = "P-03"
        clone["outputs"] = []
        clone["verifier"]["required_evidence"] = []
        state["nodes"].append(clone)
        state["current_frontier"].append("P-03")
    elif name == "invariant_unbound":
        node = _node(state, "P-02")
        node["kind"] = "migration"
        node["inputs"] = [ref for ref in node["inputs"] if not ref.startswith("I-")]
        state["edges"] = [edge for edge in state["edges"] if not (edge["kind"] == "invariant" and edge["to"] == "P-02")]
    elif name == "fog_executed":
        _node(state, "P-02")["status"] = "fog"
    elif name == "invalidated_dependent":
        _node(state, "P-01")["status"] = "invalidated"
    elif name == "closure_premature":
        state["closure"]["status"] = "complete"
        state["closure"]["epistemic_status"] = "verified_within_scope"
    elif name == "profile_overbuilt":
        state["profile"] = "brief"
    elif name == "owner_duplicate":
        state["policy_claims"].append({"policy": "implementation-proof-mechanism", "normative_owner": "another-owner", "artifact_ref": "source:symbol:Other.compare"})
    elif name == "sensitive_unclassified":
        state["facts"][0]["statement"] = "api_key=SUPERSECRET_1234567890"
    elif name == "verifier_unresolved":
        _node(state, "P-01")["verifier"].pop("command_ref")
    elif name == "evidence_unbound":
        state["evidence"][0].pop("source_revision")
    else:
        raise AssertionError(f"unknown mutation {name}")


class PlanStateTests(unittest.TestCase):
    def test_valid_program_has_no_violations(self) -> None:
        self.assertEqual([], _validate(_base()))

    def test_each_stable_violation_code_has_a_negative_fixture(self) -> None:
        catalog = json.loads((FIXTURES / "invalid-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(21, len(catalog["cases"]))
        for case in catalog["cases"]:
            with self.subTest(case=case["id"]):
                state = _base()
                _mutate(state, case["mutation"])
                codes = {item.code for item in _validate(state)}
                self.assertIn(case["expected_code"], codes, sorted(codes))

    def test_schema_contract_enums_and_codes_do_not_drift(self) -> None:
        contract = (ROOT / "references" / "plan-state-contract.md").read_text(encoding="utf-8")
        catalog = json.loads((FIXTURES / "invalid-cases.json").read_text(encoding="utf-8"))
        for case in catalog["cases"]:
            self.assertIn(case["expected_code"], contract)
        for value in SCHEMA["properties"]["status"]["enum"] + SCHEMA["$defs"]["node"]["properties"]["status"]["enum"] + SCHEMA["$defs"]["edge"]["properties"]["kind"]["enum"]:
            self.assertIn(value, contract)

    def test_canonical_hash_is_stable_and_self_excluding(self) -> None:
        state = _base()
        first = canonical_state_hash(state)
        reordered = json.loads(json.dumps(state, sort_keys=True))
        self.assertEqual(first, canonical_state_hash(reordered))
        state["content_hash"] = first
        self.assertEqual(first, canonical_state_hash(state))
        state["goal"] += " changed"
        self.assertNotEqual(first, canonical_state_hash(state))

    def test_capsule_redacts_sensitive_objects_and_reports_budget(self) -> None:
        state = _base()
        decision = state["decisions"][0]
        decision["sensitive"] = True
        decision["statement"] = "SECRET_DO_NOT_RENDER"
        state["evidence"][2]["claim"] = "api_key=UNMARKED_SECRET_1234567890"
        extra = deepcopy(_node(state, "P-02"))
        extra["id"] = "P-03"
        extra["status"] = "blocked"
        state["nodes"].append(extra)
        full_text, full_metadata = render(state, "P-02", 10_000)
        self.assertNotIn("SECRET_DO_NOT_RENDER", full_text)
        self.assertNotIn("UNMARKED_SECRET_1234567890", full_text)
        self.assertIn("E-03: [REDACTED]", full_text)
        self.assertIn("D-01: [REDACTED]", full_text)
        self.assertFalse(full_metadata["budget_exceeded"])
        text, metadata = render(state, "P-02", 500)
        self.assertNotIn("SECRET_DO_NOT_RENDER", text)
        self.assertTrue(metadata["budget_exceeded"])
        self.assertIn("P-03", metadata["omitted_refs"])
        self.assertIn("State: version=", text)
        self.assertIn("Global invariants", text)

    def test_freshness_distinguishes_local_and_global_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            target = repository / "tests" / "manifest" / "legacy-fixture.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(target)
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            fresh = check_freshness(state_path, repository_override=repository, now_value="2026-07-13T14:00:00+00:00")
            self.assertEqual("fresh", fresh["status"])
            target.write_text('{"changed": true}\n', encoding="utf-8")
            partial = check_freshness(state_path, repository_override=repository, now_value="2026-07-13T14:00:00+00:00")
            self.assertEqual("partially_stale", partial["status"])
            self.assertEqual(["S-01"], partial["affected_ids"])
            stale = check_freshness(state_path, repository_override=repository, current_scope_hash="sha256:" + "9" * 64, now_value="2026-07-13T14:00:00+00:00")
            self.assertEqual("stale", stale["status"])
            self.assertIn("scope", stale["affected_ids"])

    def test_freshness_resolves_symbol_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            source = repository / "src" / "planner.py"
            source.parent.mkdir()
            source.write_text("class RefreshPlanner:\n    def compare_manifest(self):\n        pass\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            state["snapshots"].append(
                {
                    "id": "S-02",
                    "kind": "symbol",
                    "path": "src/planner.py",
                    "source_revision": "explicit-unversioned",
                    "sensitive": False,
                }
            )
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            unbound = check_freshness(state_path, repository_override=repository)
            self.assertIn("symbol_unbound", {item["kind"] for item in unbound["issues"]})

            state["snapshots"][-1]["symbol"] = "RefreshPlanner.removed_method"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            missing = check_freshness(state_path, repository_override=repository)
            self.assertIn("symbol_missing", {item["kind"] for item in missing["issues"]})

            state["snapshots"][-1]["symbol"] = "RefreshPlanner.compare_manifest"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            fresh = check_freshness(state_path, repository_override=repository)
            self.assertEqual("fresh", fresh["status"], fresh)

    def test_freshness_resolves_line_end_and_done_verifier_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            state = _base()
            snapshot = state["snapshots"][0]
            snapshot.update(
                {
                    "kind": "line",
                    "line_start": 1,
                    "line_end": 99,
                    "source_revision": "explicit-unversioned",
                    "content_hash": file_hash(fixture),
                }
            )
            _node(state, "P-01")["verifier"]["command_ref"] = "path:tests/missing-verifier.sh"
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            stale = check_freshness(state_path, repository_override=repository)
            kinds = {item["kind"] for item in stale["issues"]}
            self.assertTrue({"line_drift", "verifier_unresolved"} <= kinds, stale)

            verifier = repository / "tests" / "check.sh"
            verifier.write_text("exit 0\n", encoding="utf-8")
            snapshot["line_end"] = 1
            _node(state, "P-01")["verifier"]["command_ref"] = "path:tests/check.sh"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            fresh = check_freshness(state_path, repository_override=repository)
            self.assertEqual("fresh", fresh["status"], fresh)

    def test_freshness_checks_caller_expected_external_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            state["evidence"].append(
                {
                    "id": "E-06",
                    "status": "observed",
                    "claim": "External interface version was inspected.",
                    "observed_at": "2026-07-13T13:30:00+00:00",
                    "external_version": "v1",
                    "freshness_policy": {
                        "kind": "external_time_bound",
                        "max_age_hours": 24,
                        "expected_version": "v2",
                    },
                    "sensitive": False,
                }
            )
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = check_freshness(
                state_path,
                repository_override=repository,
                now_value="2026-07-13T14:00:00+00:00",
            )
            self.assertEqual("partially_stale", result["status"], result)
            self.assertIn("evidence_version_changed", {item["kind"] for item in result["issues"]})

    def test_validator_covers_top_level_secrets_symbol_binding_and_done_verifier(self) -> None:
        secret = _base()
        secret["goal"] = "Deploy with api_key=SUPERSECRET_1234567890"
        self.assertIn("plan.sensitive-unclassified", {item.code for item in _validate(secret)})

        symbol = _base()
        symbol["snapshots"][0].update(
            {"kind": "symbol", "source_revision": "explicit-unversioned"}
        )
        self.assertIn("plan.snapshot-unbound", {item.code for item in _validate(symbol)})

        verifier = _base()
        _node(verifier, "P-01")["verifier"].pop("command_ref")
        self.assertIn("plan.verifier-unresolved", {item.code for item in _validate(verifier)})

        evidence = _base()
        evidence["evidence"][0].pop("freshness_policy")
        self.assertIn("plan.evidence-unbound", {item.code for item in _validate(evidence)})

    def test_controlled_secret_pointer_is_not_misclassified_as_raw_secret(self) -> None:
        state = _base()
        state["goal"] = "Deploy using api_key=env:DEPLOY_API_KEY"
        self.assertNotIn("plan.sensitive-unclassified", {item.code for item in _validate(state)})

    def test_freshness_reports_non_file_bindings_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            (repository / "src").mkdir()
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            state["snapshots"].append(
                {
                    "id": "S-02",
                    "kind": "symbol",
                    "path": "src",
                    "symbol": "RefreshPlanner.compare_manifest",
                    "source_revision": "explicit-unversioned",
                    "sensitive": False,
                }
            )
            state["snapshots"].append(
                {
                    "id": "S-03",
                    "kind": "path",
                    "path": "src",
                    "content_hash": "sha256:" + "2" * 64,
                    "sensitive": False,
                }
            )
            state["evidence"].append(
                {
                    "id": "E-06",
                    "status": "observed",
                    "claim": "A local artifact was inspected.",
                    "artifact_ref": "file:src",
                    "content_hash": "sha256:" + "1" * 64,
                    "freshness_policy": {"kind": "stable"},
                    "sensitive": False,
                }
            )
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = check_freshness(state_path, repository_override=repository)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertTrue({"snapshot_not_file", "artifact_not_file"} <= kinds, result)

    def test_observed_evidence_requires_usable_freshness_bindings(self) -> None:
        state = _base()
        state["evidence"][0].pop("source_revision")
        self.assertIn("plan.evidence-unbound", {item.code for item in _validate(state)})
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            state["evidence"].append(
                {
                    "id": "E-06",
                    "status": "observed",
                    "claim": "External version was inspected without a time observation.",
                    "external_version": "v2",
                    "freshness_policy": {
                        "kind": "external_time_bound",
                        "max_age_hours": 24,
                        "expected_version": "v2",
                    },
                    "sensitive": False,
                }
            )
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            result = check_freshness(state_path, repository_override=repository)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertTrue({"evidence_revision_unbound", "evidence_time_unbound"} <= kinds, result)

    def test_artifact_mtime_binding_detects_same_content_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            artifact = repository / "artifacts" / "proof.txt"
            artifact.parent.mkdir()
            artifact.write_text("same content\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            state["evidence"].append(
                {
                    "id": "E-06",
                    "status": "observed",
                    "claim": "The local proof artifact was inspected.",
                    "artifact_ref": "file:artifacts/proof.txt",
                    "artifact_mtime_ns": artifact.stat().st_mtime_ns,
                    "freshness_policy": {"kind": "stable"},
                    "sensitive": False,
                }
            )
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual("fresh", check_freshness(state_path, repository_override=repository)["status"])
            stat = artifact.stat()
            os.utime(artifact, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
            stale = check_freshness(state_path, repository_override=repository)
            self.assertIn("artifact_mtime_changed", {item["kind"] for item in stale["issues"]})

    def test_done_noncommand_verifier_reference_is_still_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            verifier = _node(state, "P-01")["verifier"]
            verifier["kind"] = "schema"
            verifier["command_ref"] = "schema:schemas/missing.json"
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            stale = check_freshness(state_path, repository_override=repository)
            self.assertIn("verifier_unresolved", {item["kind"] for item in stale["issues"]})

    def test_capsule_snapshot_hash_excludes_generated_snapshot_self_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            fixture = repository / "tests" / "manifest" / "legacy-fixture.json"
            fixture.parent.mkdir(parents=True)
            fixture.write_text("{}\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(fixture)
            capsule_text, metadata = render(state, "P-02", 10_000)
            capsule = repository / ".workflow" / "capsules" / "P-02.md"
            capsule.parent.mkdir(parents=True)
            capsule.write_text(capsule_text, encoding="utf-8")
            state["snapshots"].append(
                {
                    "id": "S-02",
                    "kind": "capsule",
                    "path": ".workflow/capsules/P-02.md",
                    "source_revision": "explicit-unversioned",
                    "content_hash": file_hash(capsule),
                    "plan_state_hash": metadata["state_hash"],
                    "plan_state_version": metadata["state_version"],
                    "sensitive": False,
                }
            )
            state_path = repository / "plan.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            fresh = check_freshness(state_path, repository_override=repository)
            self.assertEqual("fresh", fresh["status"], fresh)
            state["state_version"] += 1
            state_path.write_text(json.dumps(state), encoding="utf-8")
            stale = check_freshness(state_path, repository_override=repository)
            self.assertIn("capsule_stale", {item["kind"] for item in stale["issues"]})

    def test_invalidation_cascades_without_touching_unrelated_branch(self) -> None:
        state = _base()
        unrelated = deepcopy(_node(state, "P-02"))
        unrelated["id"] = "P-99"
        unrelated["depends_on"] = []
        unrelated["inputs"] = ["E-02"]
        unrelated["outputs"] = []
        unrelated["write_set"] = ["docs/unrelated.md"]
        state["nodes"].append(unrelated)
        impact = propagate_affected(state, {"F-01"})
        self.assertTrue({"F-01", "P-01", "E-03", "P-02", "E-04", "E-05"}.issubset(impact["affected_ids"]))
        self.assertIn("P-99", impact["preserved_ids"])
        self.assertEqual("local", impact["repair_type"])

    def test_edge_field_sensitivity_prevents_over_invalidation(self) -> None:
        state = _base()
        irrelevant = propagate_affected(state, {"E-03"}, changed_fields={"E-03": {"observed_at"}})
        self.assertNotIn("P-02", irrelevant["affected_ids"])
        self.assertIn("P-02", irrelevant["preserved_ids"])
        relevant = propagate_affected(state, {"E-03"}, changed_fields={"E-03": {"status"}})
        self.assertIn("P-02", relevant["affected_ids"])

    def test_freshness_cli_accepts_field_level_change_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "plan.json"
            state_path.write_text(json.dumps(_base()), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPTS / "check_plan_freshness.py"),
                    str(state_path),
                    "--repository",
                    directory,
                    "--changed-ref",
                    "E-03",
                    "--changed-field",
                    "E-03=observed_at",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(1, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("partially_stale", payload["status"])
        self.assertNotIn("P-02", payload["affected_ids"])
        self.assertIn("P-02", payload["preserved_ids"])

    def test_invariant_change_escalates_but_unknown_ref_is_bounded(self) -> None:
        global_impact = propagate_affected(_base(), {"I-01"})
        self.assertEqual("global_or_parent_replan", global_impact["repair_type"])
        self.assertIn("global_invariant_changed", global_impact["escalation_reasons"])
        unknown = propagate_affected(_base(), {"F-404"})
        self.assertEqual(["F-404"], unknown["affected_ids"])
        self.assertEqual("local", unknown["repair_type"])

    def test_profile_renderer_binds_novice_projection(self) -> None:
        brief = render_brief({"outcome": "Visible change", "scope": "Owner", "invariants": "Stable", "approach": "Patch owner", "proof": "Focused check", "closure": "needs_repair"})
        self.assertIn("# Change Card", brief)
        state = _base()
        projection_data = {
            "state_hash": canonical_state_hash(state),
            "source_revision": state["source"]["base_revision"],
            "scope_hash": state["source"]["scope_hash"],
            "novice_steps": ["Run the bounded verifier"],
        }
        program = add_novice_projection(render_program(state, state_ref="plan.json"), projection_data)
        self.assertIn("non-canonical", program)
        self.assertIn(projection_data["state_hash"], program)
        self.assertIn(projection_data["scope_hash"], program)

    def test_parser_rejects_duplicate_keys_deep_and_oversized_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(PlanInputError):
                load_json(duplicate)
            deep = root / "deep.json"
            deep.write_text("[" * 45 + "0" + "]" * 45, encoding="utf-8")
            with self.assertRaises(PlanInputError):
                load_json(deep)
            large = root / "large.json"
            large.write_text(json.dumps({"payload": "x" * MAX_INPUT_BYTES}), encoding="utf-8")
            with self.assertRaises(PlanInputError):
                load_json(large)

    def test_malformed_refs_large_arrays_and_unknown_versions_fail_boundedly(self) -> None:
        malformed_ref = _base()
        _node(malformed_ref, "P-02")["depends_on"] = ["not-a-plan-ref"]
        self.assertIn("plan.schema", {item.code for item in _validate(malformed_ref)})
        large_array = _base()
        large_array["non_goals"] = [f"item-{index}" for index in range(1001)]
        self.assertIn("plan.schema", {item.code for item in _validate(large_array)})
        unknown_version = _base()
        unknown_version["schema_version"] = "999.0"
        self.assertIn("plan.schema", {item.code for item in _validate(unknown_version)})
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.json"
            malformed.write_text('{"broken":', encoding="utf-8")
            with self.assertRaises(PlanInputError):
                load_json(malformed)


if __name__ == "__main__":
    unittest.main()
