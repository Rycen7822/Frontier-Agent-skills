from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _plan_state import (  # noqa: E402
    MAX_INPUT_BYTES,
    PlanInputError,
    apply_card_transition,
    canonical_state_hash,
    file_hash,
    load_json,
    normalize_enqueue_requests,
    initialize_program_owner,
)
import _plan_state as plan_state_runtime  # noqa: E402
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


def _rehash(state: dict) -> dict:
    state["content_hash"] = canonical_state_hash(state)
    return state


def _runtime_projection() -> dict:
    return {
        "hard_failure_refs": [],
        "remaining_budget": {
            "iterations": 1,
            "candidate_evaluations": 1,
            "review_rounds": 1,
            "changed_lines": 0,
            "total_changed_lines": 0,
        },
    }


def _write_state(path: Path, state: dict) -> None:
    _rehash(state)
    path.write_text(json.dumps(state), encoding="utf-8")


def _program_candidate(root: Path, source: Path) -> dict:
    state = _base()
    root_info = root.stat()
    source_info = source.stat()
    binding = {"dev": root_info.st_dev, "ino": root_info.st_ino, "uid": root_info.st_uid, "mode": root_info.st_mode & 0o777}
    source_binding = {"dev": source_info.st_dev, "ino": source_info.st_ino}
    state["initial_root_binding"] = binding
    state["established_root_identity"] = binding
    state["source_root_binding"] = source_binding
    state["source_identity"]["root_binding"] = source_binding
    return _rehash(state)


def _program_init_worker(root: Path, source: Path, checkpoint: str, ready: Path) -> None:
    def pause(name: str) -> None:
        if name != checkpoint:
            return
        ready.write_text(name + "\n", encoding="utf-8")
        while True:
            signal.pause()

    plan_state_runtime._checkpoint = pause
    initialize_program_owner(root, source, _program_candidate(root, source))


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
    elif name == "completion_premature":
        state["completion"]["status"] = "complete"
        state["completion"]["epistemic_status"] = "verified_within_scope"
    elif name == "terminal_queue":
        state["status"] = "completed"
    elif name == "owner_duplicate":
        state["policy_claims"].append({"policy_id": "sqw.verify.completion-evidence", "bundle_version": "frontier-engineering/6.0.0+5.0.0", "policy_hash": "sha256:" + "5" * 64})
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

    def test_v3_policy_invariant_effect_and_bundle_identity_are_schema_owned(self) -> None:
        state = _base()
        self.assertEqual([], _validate(state))
        self.assertEqual("frontier-engineering/6.0.0+5.0.0", state["bundle_id"])
        self.assertRegex(state["manifest_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual({"binding_kind", "binding_id", "producer_card_id", "initial_source_identity_hash", "allowed_reads", "allowed_plan_outputs", "effect_ceiling", "approval_requirements", "publication_ceiling"}, set(state["scope_binding"]))
        self.assertEqual({"policy_id", "bundle_version", "policy_hash"}, set(state["policy_claims"][0]))
        self.assertNotIn(".md", json.dumps(state["policy_claims"]))
        self.assertTrue({"locality", "applicability", "targets"} <= set(state["global_invariants"][0]))
        self.assertTrue(all("effect_set" in node for node in state["nodes"]))

        legacy = _base()
        legacy["policy_claims"][0] = {
            "policy": "implementation-proof-mechanism",
            "normative_owner": "references/verification-discipline.md",
            "artifact_ref": "references/verification-discipline.md",
        }
        self.assertIn("plan.schema", {item.code for item in _validate(legacy)})

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
        contract = "\n".join(
            (ROOT / "operator" / name).read_text(encoding="utf-8")
            for name in ("plan-state-runtime.md", "error-codes.md")
        )
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

    def test_queue_normalizer_preserves_order_and_separates_instance_domains(self) -> None:
        requests = [
            {"decision_id": "wp.select.slicing.context-capsules", "subject_ref": "P-01"},
            {"decision_id": "wp.select.slicing.context-capsules", "subject_ref": "P-02"},
        ]
        initial_specs, initial = normalize_enqueue_requests(requests, domain="initial", initialization_id="sha256:" + "1" * 64)
        derived_specs, derived = normalize_enqueue_requests(
            requests,
            domain="derived",
            plan_id="wp-plan:" + "a" * 64,
            prior_content_hash="sha256:" + "2" * 64,
            completion_id="sha256:" + "3" * 64,
        )
        self.assertEqual([0, 1], [item["ordinal"] for item in initial_specs])
        self.assertEqual(requests, [{"decision_id": item["decision_id"], "subject_ref": item["subject_ref"]} for item in derived_specs])
        self.assertEqual(["P-01", "P-02"], [item["subject_ref"] for item in derived])
        self.assertNotEqual([item["card_instance_id"] for item in initial], [item["card_instance_id"] for item in derived])
        with self.assertRaises(PlanInputError):
            normalize_enqueue_requests([{**requests[0], "ordinal": 4}], domain="initial", initialization_id="sha256:" + "1" * 64)
        with self.assertRaises(PlanInputError):
            normalize_enqueue_requests([{**requests[0], "card_instance_id": "sha256:" + "4" * 64}], domain="initial", initialization_id="sha256:" + "1" * 64)

    def test_card_transition_commits_once_and_full_completion_selects_operation(self) -> None:
        state = _base()
        queue_head = state["pending_card_instances"][0]["card_instance_id"]
        enqueue = [{"decision_id": "wp.select.slicing.context-capsules", "subject_ref": "P-02"}]
        common = {
            "expected_state_version": state["state_version"],
            "expected_content_hash": state["content_hash"],
            "scope_binding_id": state["scope_binding"]["binding_id"],
            "completed_card_instance_id": queue_head,
            "operations": [],
            "enqueue_requests": enqueue,
        }
        first = apply_card_transition(state, completion={"outcome": "accepted", "rationale": "first"}, **common)
        second = apply_card_transition(state, completion={"outcome": "accepted", "rationale": "second"}, **common)
        self.assertEqual(state["state_version"] + 1, first["state_version"])
        self.assertEqual(1, len(first["pending_card_instances"]))
        self.assertNotEqual(first["last_transition"]["completion_id"], second["last_transition"]["completion_id"])
        self.assertNotEqual(first["last_transition"]["operation_id"], second["last_transition"]["operation_id"])
        with self.assertRaisesRegex(PlanInputError, "stale"):
            apply_card_transition(first, completion={"outcome": "accepted", "rationale": "first"}, **common)

    def test_card_transition_rejects_model_queue_and_identity_fields(self) -> None:
        state = _base()
        common = {
            "expected_state_version": state["state_version"],
            "expected_content_hash": state["content_hash"],
            "scope_binding_id": state["scope_binding"]["binding_id"],
            "completed_card_instance_id": state["pending_card_instances"][0]["card_instance_id"],
            "completion": {"outcome": "accepted"},
            "enqueue_requests": [],
        }
        with self.assertRaisesRegex(PlanInputError, "not model writable"):
            apply_card_transition(
                state,
                operations=[{"operation": "replace_field", "target": "pending_card_instances", "value": []}],
                **common,
            )

    def test_program_owner_init_exact_replay_and_root_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "source"
            root = parent / "program"
            source.mkdir(mode=0o700)
            root.mkdir(mode=0o700)
            candidate = _program_candidate(root, source)
            state, locator, replayed = initialize_program_owner(root, source, candidate)
            self.assertFalse(replayed)
            self.assertEqual(candidate, state)
            self.assertEqual("wp-program-owner/1", locator["schema_version"])
            self.assertEqual([".plan-state.lock", "artifacts", "plan-state.json", "projections"], sorted(path.name for path in root.iterdir()))
            identity = {
                name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes())
                for name in (".plan-state.lock", "plan-state.json")
            }
            replay_state, replay_locator, replayed = initialize_program_owner(root, source, candidate)
            self.assertTrue(replayed)
            self.assertEqual((state, locator), (replay_state, replay_locator))
            self.assertEqual(identity, {name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes()) for name in identity})

            nested = source / "nested"
            nested.mkdir(mode=0o700)
            with self.assertRaises(PlanInputError):
                initialize_program_owner(nested, source, _program_candidate(nested, source))
            self.assertEqual([], list(nested.iterdir()))

    def test_program_init_real_sigkill_prefixes_converge(self) -> None:
        checkpoints = (
            "plan_lock_temp_fsynced",
            "plan_lock_linked",
            "plan_lock_link_parent_synced",
            "plan_lock_cleaned",
            "plan_lock_cleanup_parent_synced",
            "plan_state_temp_fsynced",
            "plan_artifacts_created",
            "plan_projections_created",
            "plan_state_linked",
            "plan_state_link_parent_synced",
            "plan_state_cleaned",
            "plan_state_cleanup_parent_synced",
            "plan_init_before_return",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                source = parent / "source"
                root = parent / "program"
                ready = parent / "ready"
                source.mkdir(mode=0o700)
                root.mkdir(mode=0o700)
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--program-init-worker", str(root), str(source), checkpoint, str(ready)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                if not ready.exists():
                    if process.poll() is None:
                        process.kill()
                    stdout, stderr = process.communicate(timeout=1)
                    self.fail(f"worker did not reach {checkpoint}: {stdout}{stderr}")
                process.kill()
                process.communicate(timeout=5)
                candidate = _program_candidate(root, source)
                state, _, _ = initialize_program_owner(root, source, candidate)
                self.assertEqual(candidate, state)
                self.assertEqual([".plan-state.lock", "artifacts", "plan-state.json", "projections"], sorted(path.name for path in root.iterdir()))
                replay = initialize_program_owner(root, source, candidate)
                self.assertTrue(replay[2])

    def test_capsule_redacts_and_fails_closed_before_mandatory_truncation(self) -> None:
        state = _base()
        decision = state["decisions"][0]
        decision["sensitive"] = True
        decision["statement"] = "SECRET_DO_NOT_RENDER"
        state["evidence"][2]["claim"] = "api_key=UNMARKED_SECRET_1234567890"
        state["evidence"][2]["sensitive"] = True
        extra = deepcopy(_node(state, "P-02"))
        extra["id"] = "P-03"
        extra["status"] = "blocked"
        state["nodes"].append(extra)
        _rehash(state)
        full_text, full_metadata = render(state, "P-02", 8192, _runtime_projection())
        self.assertNotIn("SECRET_DO_NOT_RENDER", full_text)
        self.assertNotIn("UNMARKED_SECRET_1234567890", full_text)
        self.assertIn("E-03: [REDACTED]", full_text)
        self.assertIn("D-01: [REDACTED]", full_text)
        self.assertEqual(0, full_metadata["mandatory_truncation_count"])
        self.assertEqual("wp.slicing.context-capsules", full_metadata["card_refs"][0]["card_id"])
        self.assertRegex(full_metadata["projection_hash"], r"^sha256:[0-9a-f]{64}$")
        with self.assertRaisesRegex(ValueError, "mandatory capsule exceeds budget"):
            render(state, "P-02", full_metadata["mandatory_bytes"] - 1, _runtime_projection())
        text, metadata = render(state, "P-02", full_metadata["mandatory_bytes"] + 20, _runtime_projection())
        self.assertNotIn("SECRET_DO_NOT_RENDER", text)
        self.assertEqual(0, metadata["mandatory_truncation_count"])
        self.assertIn("P-03", metadata["omitted_refs"])
        self.assertIn("State: version=", text)
        self.assertIn("Global invariants", text)

    def test_frontier_detects_read_write_effect_and_invariant_applicability_conflicts(self) -> None:
        state = _base()
        clone = deepcopy(_node(state, "P-02"))
        clone.update({"id": "P-03", "depends_on": [], "inputs": ["I-01"], "outputs": [], "write_set": [], "resource_set": [], "effect_set": ["workspace:other"]})
        clone["verifier"]["required_evidence"] = []
        state["nodes"].append(clone)
        state["current_frontier"].append("P-03")
        self.assertIn("plan.effect-conflict", {item.code for item in _validate(state)})

        effects = _base()
        clone = deepcopy(_node(effects, "P-02"))
        clone.update({"id": "P-03", "depends_on": [], "inputs": ["I-01"], "outputs": [], "read_set": [], "write_set": [], "resource_set": [], "effect_set": ["workspace:manifest-owner"]})
        clone["verifier"]["required_evidence"] = []
        effects["nodes"].append(clone)
        effects["current_frontier"].append("P-03")
        self.assertIn("plan.effect-conflict", {item.code for item in _validate(effects)})

        locality = _base()
        locality["global_invariants"][0].update({"locality": "node_set", "applicability": "when_target_active", "targets": ["P-01"]})
        _node(locality, "P-02")["kind"] = "migration"
        self.assertIn("plan.invariant-unbound", {item.code for item in _validate(locality)})

    def test_freshness_distinguishes_local_and_global_staleness(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            target = repository / "tests" / "manifest" / "legacy-fixture.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}\n", encoding="utf-8")
            state = _base()
            state["snapshots"][0]["content_hash"] = file_hash(target)
            state_path = repository / "plan.json"
            _write_state(state_path, state)
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
            _write_state(state_path, state)
            unbound = check_freshness(state_path, repository_override=repository)
            self.assertIn("symbol_unbound", {item["kind"] for item in unbound["issues"]})

            state["snapshots"][-1]["symbol"] = "RefreshPlanner.removed_method"
            _write_state(state_path, state)
            missing = check_freshness(state_path, repository_override=repository)
            self.assertIn("symbol_missing", {item["kind"] for item in missing["issues"]})

            state["snapshots"][-1]["symbol"] = "RefreshPlanner.compare_manifest"
            _write_state(state_path, state)
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
            _write_state(state_path, state)
            stale = check_freshness(state_path, repository_override=repository)
            kinds = {item["kind"] for item in stale["issues"]}
            self.assertTrue({"line_drift", "verifier_unresolved"} <= kinds, stale)

            verifier = repository / "tests" / "check.sh"
            verifier.write_text("exit 0\n", encoding="utf-8")
            snapshot["line_end"] = 1
            _node(state, "P-01")["verifier"]["command_ref"] = "path:tests/check.sh"
            _write_state(state_path, state)
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
            _write_state(state_path, state)
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
            _write_state(state_path, state)
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
            _write_state(state_path, state)
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
            _write_state(state_path, state)
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
            _write_state(state_path, state)
            stale = check_freshness(state_path, repository_override=repository)
            self.assertIn("verifier_unresolved", {item["kind"] for item in stale["issues"]})

    def test_context_projection_identity_never_enters_canonical_state(self) -> None:
        state = _base()
        _, metadata = render(state, "P-02", 8192, _runtime_projection())
        encoded = json.dumps(state)
        for forbidden in ("projection_hash", "projection_spec_id", "plan_state_hash", "card_refs"):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(state["content_hash"], metadata["state_hash"])
        legacy = deepcopy(state)
        legacy["snapshots"].append(
            {"id": "S-02", "kind": "capsule", "path": "context.md", "projection_hash": metadata["projection_hash"]}
        )
        self.assertIn("plan.schema", {item.code for item in _validate(legacy)})

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
        brief = render_brief({"outcome": "Visible change", "scope": "Owner", "invariants": "Stable", "approach": "Patch owner", "proof": "Focused check", "completion": "needs_repair"})
        self.assertIn("# Change Card", brief)
        state = _base()
        projection_data = {
            "state_hash": canonical_state_hash(state),
            "source_revision": state["source_identity"]["identity_hash"],
            "scope_hash": state["scope_binding"]["binding_id"],
            "novice_steps": ["Run the bounded verifier"],
        }
        program = add_novice_projection(render_program(state), projection_data)
        self.assertIn("non-canonical", program)
        self.assertIn(projection_data["state_hash"], program)
        self.assertIn(projection_data["scope_hash"], program)

    def test_program_default_is_reconstructable_current_frontier_under_budget(self) -> None:
        state = _base()
        state["decisions"].append(
            {
                "id": "D-99",
                "statement": "UNRELATED_FUTURE_DECISION " + "x" * 9000,
                "alternatives_rejected": [{"option": "future", "reason": "not current"}],
                "evidence_refs": [],
                "provenance": "source",
                "materiality": "low",
                "reversibility": "local",
            }
        )
        _rehash(state)
        program = render_program(state)
        self.assertLessEqual(len(program.encode("utf-8")), 8192)
        self.assertIn("P-02", program)
        self.assertNotIn("UNRELATED_FUTURE_DECISION", program)
        self.assertNotIn("P-01: Establish", program)
        self.assertIn("canonical_artifacts", program)

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
    if len(sys.argv) == 6 and sys.argv[1] == "--program-init-worker":
        _program_init_worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]))
    else:
        unittest.main()
