from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
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

from _workflow_state import load_json, load_json_lines  # noqa: E402
import local_workflow_adapter as workflow_adapter  # noqa: E402
from local_workflow_adapter import AdapterConflict, LocalWorkflowAdapter, bootstrap_v3  # noqa: E402
from project_context import project_context  # noqa: E402
from propagate_invalidation import propagate_invalidation  # noqa: E402
from reconcile_workflow import reconcile  # noqa: E402


STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")
STATE_FIXTURE = ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json"
EVENT_FIXTURE = ROOT / "tests" / "fixtures" / "workflow-events" / "valid-events.jsonl"
NOW = "2026-07-13T11:30:00+08:00"
RESUME_NOW = "2026-07-13T13:30:00+08:00"


def _base() -> dict:
    return load_json(STATE_FIXTURE)


def _node(state: dict, node_id: str) -> dict:
    return next(item for item in state["nodes"] if item["id"] == node_id)


def _event(index: int = 0) -> dict:
    return deepcopy(load_json_lines(EVENT_FIXTURE)[index])


def _locks(state: dict, leases: list[dict]) -> dict:
    return {
        "schema_version": "sqw-locks/1",
        "workflow_id": state["workflow_id"],
        "bootstrap_operation_id": state["bootstrap"]["operation_id"],
        "scope_binding_id": state["scope_binding"]["binding_id"],
        "leases": leases,
    }


def _bootstrap(root: Path, source: Path, *, next_step: dict | None = None) -> tuple[dict, dict, dict]:
    return bootstrap_v3(
        root,
        source,
        bundle_id="frontier-engineering/6.0.0+5.0.0",
        policy_bundle_hash="sha256:" + "2" * 64,
        card_manifest_hash="sha256:" + "3" * 64,
        mode="M2",
        request_mode="change",
        entry_completion={"content_hash": "sha256:" + "4" * 64},
        scope_completion={"content_hash": "sha256:" + "5" * 64},
        scope_binding={
            "binding_id": "sha256:" + "6" * 64,
            "mode": "M2",
            "allowed_reads": ["src/**"],
            "allowed_writes": ["src/**"],
            "effects": ["LOCAL_REVERSIBLE"],
            "approval_requirements": [],
            "publication_ceiling": "none",
        },
        source_identity={"kind": "unversioned", "identity_hash": "sha256:" + "7" * 64},
        next_step=next_step or {
            "kind": "card",
            "decision_id": "sqw.select.behavior-cycle",
            "card_id": "sqw.execute.behavior-cycle",
            "card_path": "references/execution/behavior-cycle.md",
            "card_hash": "sha256:" + "8" * 64,
        },
        now_value=NOW,
    )


def _owner(parent: Path) -> tuple[Path, dict]:
    source = parent / "source"
    root = parent / "workflow"
    source.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    state, _, _ = _bootstrap(root, source)
    return root, state


def _handoff_owner(parent: Path) -> tuple[Path, dict]:
    source = parent / "source"
    root = parent / "workflow"
    source.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    state, _, _ = _bootstrap(
        root,
        source,
        next_step={
            "kind": "card",
            "decision_id": "sqw.select.delegation.admission-and-contract",
            "card_id": "sqw.delegation.admission-and-contract",
            "card_path": "references/delegation/admission-and-contract.md",
            "card_hash": "sha256:" + "9" * 64,
        },
    )
    return root, state


def _bootstrap_worker(root: Path, source: Path, checkpoint_name: str, ready: Path) -> None:
    def pause(name: str) -> None:
        if name != checkpoint_name:
            return
        ready.write_text(name + "\n", encoding="utf-8")
        while True:
            signal.pause()

    workflow_adapter._checkpoint = pause
    _bootstrap(root, source)


def _resume_worker(root: Path, checkpoint_name: str, ready: Path) -> None:
    def pause(name: str) -> None:
        if name != checkpoint_name:
            return
        ready.write_text(name + "\n", encoding="utf-8")
        while True:
            signal.pause()

    state = load_json(root / "state.json")
    locator = {
        "schema_version": "sqw-workflow-owner/1",
        "workflow_id": state["workflow_id"],
        "bootstrap_operation_id": state["bootstrap"]["operation_id"],
        "bundle_id": state["bundle_id"],
        "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
        "scope_binding_id": state["scope_binding"]["binding_id"],
        "mode": state["mode"],
        "initial_root_binding_hash": workflow_adapter._value_hash(state["bootstrap"]["initial_root_binding"]),
    }
    workflow_adapter._checkpoint = pause
    LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA).resume(
        locator,
        state["source_identity"],
        expected_bundle_id=state["bundle_id"],
        expected_policy_bundle_hash=state["policy_bundle_hash"],
        expected_card_manifest_hash=state["card_manifest_hash"],
        expected_cards={state["active_frontier"]["card_id"]: (state["active_frontier"]["card_path"], state["active_frontier"]["card_hash"])},
        now_value=RESUME_NOW,
    )


def _complete_inline(root: Path) -> tuple[dict, dict | None]:
    state = load_json(root / "state.json")
    locator = {
        "schema_version": "sqw-workflow-owner/1",
        "workflow_id": state["workflow_id"],
        "bootstrap_operation_id": state["bootstrap"]["operation_id"],
        "bundle_id": state["bundle_id"],
        "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
        "scope_binding_id": state["scope_binding"]["binding_id"],
        "mode": state["mode"],
        "initial_root_binding_hash": workflow_adapter._value_hash(state["bootstrap"]["initial_root_binding"]),
    }
    locks = load_json(root / "locks.json")
    if state["state_version"] == 1:
        previous_frontier = state["active_frontier"]
        previous_hash = state["state_hash"]
        previous_lease = locks["leases"][0]
    else:
        completion_entry = state["card_completions"][-1]
        previous_frontier = {
            "kind": "card",
            "decision_id": completion_entry["completion"]["decision_id"],
            "card_id": completion_entry["completion"]["producer_card_id"],
            "card_path": "references/execution/behavior-cycle.md",
            "card_hash": "sha256:" + "8" * 64,
        }
        previous_hash = state["last_transition"]["prior_state_hash"]
        previous_lease = {
            "lease_id": workflow_adapter._value_hash({"workflow_id": state["workflow_id"], "frontier": previous_frontier}),
            "producer_id": previous_frontier["card_id"],
            "decision_id": previous_frontier["decision_id"],
            "lease_expires_at": "2026-07-13T12:30:00+08:00",
        }
    previous = {
        "owner_locator": locator,
        "scope_binding": state["scope_binding"],
        "state_version": 1,
        "state_hash": previous_hash,
        "next_step": previous_frontier,
        "current_lease": previous_lease,
    }
    payload = {
        "artifact_id": "test-behavior-cycle",
        "producer_card_id": previous_frontier["card_id"],
        "decision_id": previous_frontier["decision_id"],
        "fields": {"claim": "proved", "observations": ["focused pass"], "limitations": [], "verdict": "pass"},
        "outcome": {"blocker": None, "decision_request": "sqw.select.test.oracle-and-lifecycle"},
    }
    completion = {**payload, "content_hash": workflow_adapter._value_hash(payload)}
    next_step = {
        "kind": "card",
        "decision_id": "sqw.select.test.oracle-and-lifecycle",
        "card_id": "sqw.test.oracle-and-lifecycle",
        "card_path": "references/test/oracle-and-lifecycle.md",
        "card_hash": "sha256:" + "9" * 64,
    }
    return LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA).complete_card(
        locator,
        previous,
        state["source_identity"],
        completion,
        lambda _state, _completion: next_step,
        expected_bundle_id=state["bundle_id"],
        expected_policy_bundle_hash=state["policy_bundle_hash"],
        expected_card_manifest_hash=state["card_manifest_hash"],
        expected_cards={
            previous_frontier["card_id"]: (previous_frontier["card_path"], previous_frontier["card_hash"]),
            next_step["card_id"]: (next_step["card_path"], next_step["card_hash"]),
        },
        now_value=NOW,
    )


def _complete_materialized(root: Path) -> tuple[dict, dict | None]:
    state = load_json(root / "state.json")
    frontier = {
        "kind": "card",
        "decision_id": "sqw.select.delegation.admission-and-contract",
        "card_id": "sqw.delegation.admission-and-contract",
        "card_path": "references/delegation/admission-and-contract.md",
        "card_hash": "sha256:" + "9" * 64,
    }
    locator = {
        "schema_version": "sqw-workflow-owner/1",
        "workflow_id": state["workflow_id"],
        "bootstrap_operation_id": state["bootstrap"]["operation_id"],
        "bundle_id": state["bundle_id"],
        "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
        "scope_binding_id": state["scope_binding"]["binding_id"],
        "mode": state["mode"],
        "initial_root_binding_hash": workflow_adapter._value_hash(state["bootstrap"]["initial_root_binding"]),
    }
    old_lease = {
        "lease_id": workflow_adapter._value_hash({"workflow_id": state["workflow_id"], "frontier": frontier}),
        "producer_id": frontier["card_id"],
        "decision_id": frontier["decision_id"],
        "lease_expires_at": "2026-07-13T12:30:00+08:00",
    }
    previous = {
        "owner_locator": locator,
        "scope_binding": state["scope_binding"],
        "state_version": 1,
        "state_hash": state["state_hash"] if state["state_version"] == 1 else state["last_transition"]["prior_state_hash"],
        "next_step": frontier,
        "current_lease": old_lease,
    }
    payload = {
        "artifact_id": "delegation-admission-and-contract",
        "producer_card_id": frontier["card_id"],
        "decision_id": frontier["decision_id"],
        "fields": {
            "objective": "bounded handoff",
            "requirements": ["preserve contract"],
            "authority_requirements": ["local only"],
            "ordered_slices": ["implement", "verify"],
            "rollback": "revert patch",
        },
        "outcome": {"blocker": None, "decision_request": None},
    }
    completion = {**payload, "content_hash": workflow_adapter._value_hash(payload)}
    artifact_bytes = workflow_adapter._compact_bytes(payload) + b"\n"
    content_locator = {
        "schema_version": "content-locator/1",
        "content_kind": "artifact",
        "artifact_id": payload["artifact_id"],
        "content_hash": completion["content_hash"],
        "bytes": len(artifact_bytes),
    }
    return LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA).complete_card(
        locator,
        previous,
        state["source_identity"],
        completion,
        lambda _state, _completion: {"kind": "terminal", "decision_id": None, "reason_codes": ["ACTIVE_QUEUE_EMPTY"]},
        materialized_payload=artifact_bytes,
        content_locator=content_locator,
        expected_bundle_id=state["bundle_id"],
        expected_policy_bundle_hash=state["policy_bundle_hash"],
        expected_card_manifest_hash=state["card_manifest_hash"],
        expected_cards={frontier["card_id"]: (frontier["card_path"], frontier["card_hash"])},
        now_value=NOW,
    )


def _complete_worker(root: Path, checkpoint_name: str, ready: Path) -> None:
    def pause(name: str) -> None:
        if name != checkpoint_name:
            return
        ready.write_text(name + "\n", encoding="utf-8")
        while True:
            signal.pause()

    workflow_adapter._checkpoint = pause
    _complete_inline(root)


def _complete_materialized_worker(root: Path, checkpoint_name: str, ready: Path) -> None:
    def pause(name: str) -> None:
        if name != checkpoint_name:
            return
        ready.write_text(name + "\n", encoding="utf-8")
        while True:
            signal.pause()

    workflow_adapter._checkpoint = pause
    _complete_materialized(root)


class WorkflowRuntimeTests(unittest.TestCase):
    def test_context_projection_is_bounded_state_versioned_and_secret_safe(self) -> None:
        state = _base()
        state["artifacts"][0]["sensitive"] = True
        state["artifacts"][0]["claim"] = "api_key=RAW_SECRET_1234567890"
        _node(state, "N-02")["sensitive"] = True
        _node(state, "N-02")["objective"] = "Repair private customer Alice record."
        _node(state, "N-02")["read_set"] = ["private/customer-alice.json"]
        card_refs = [{"card_id": "sqw.verify.gate-selection-and-execution", "card_hash": "sha256:a4dc0c6f807fc54269fb2418e90354517c9050feec1a9267b62e1f8c0aeb2d6a"}]
        projections = {"runtime-test": {"purpose": "secret-safe frontier projection"}}
        with self.assertRaisesRegex(ValueError, "mandatory context exceeds budget"):
            project_context(state, budget_bytes=900, card_refs=card_refs, artifact_projections=projections)
        text, metadata = project_context(
            state,
            budget_bytes=8192,
            card_refs=card_refs,
            artifact_projections=projections,
        )
        self.assertIn("state_version: 3", text)
        self.assertIn("local_reversible", text)
        self.assertIn("I-01", text)
        self.assertIn("N-02", text)
        self.assertNotIn("RAW_SECRET_1234567890", text)
        self.assertNotIn("customer Alice", text)
        self.assertNotIn("customer-alice.json", text)
        self.assertIn("[SENSITIVE_POINTER]", text)
        self.assertLessEqual(metadata["actual_bytes"], 8192)
        self.assertEqual(card_refs, metadata["card_refs"])
        self.assertEqual(["runtime-test"], metadata["artifact_projection_ids"])
        self.assertEqual(0, metadata["mandatory_truncation_count"])
        self.assertTrue(metadata["requires_on_demand_read"])

    def test_invalidation_is_field_precise_and_preserves_unrelated_branch(self) -> None:
        state = _base()
        unrelated = deepcopy(_node(state, "N-02"))
        unrelated["id"] = "N-99"
        unrelated["input_refs"] = ["plan:plan-manifest-refresh#D-99"]
        unrelated["output_refs"] = ["EV-99"]
        unrelated["verifier_refs"] = []
        unrelated["depends_on"] = []
        unrelated["write_set"] = ["docs/unrelated.md"]
        unrelated["resource_set"] = ["unrelated"]
        state["nodes"].append(unrelated)
        irrelevant = propagate_invalidation(state, {"EV-01"}, changed_fields={"EV-01": {"observation.duration_ms"}})
        self.assertNotIn("N-02", irrelevant["affected"])
        self.assertIn("N-02", irrelevant["preserved"])
        relevant = propagate_invalidation(state, {"EV-01"}, changed_fields={"EV-01": {"observation.exit_code"}})
        self.assertTrue({"EV-01", "N-02", "EV-02"}.issubset(relevant["affected"]))
        self.assertIn("N-99", relevant["preserved"])
        self.assertIn("scope_binding.binding_id", relevant["required_rechecks"])
        self.assertNotIn("source.scope_hash", relevant["required_rechecks"])
        self.assertEqual("local", relevant["repair_type"])
        global_result = propagate_invalidation(state, {"I-01"})
        self.assertEqual("global_or_parent_replan", global_result["repair_type"])
        self.assertIn("global_invariant_changed", global_result["escalation_reasons"])

    def test_reconcile_detects_source_plan_and_artifact_drift(self) -> None:
        state = _base()
        drift = reconcile(state, current_revision="new-revision", current_scope_binding_id=state["scope_binding"]["binding_id"], current_plan_hash="sha256:" + "9" * 64, verify_artifacts=False)
        self.assertFalse(drift["resume_allowed"])
        self.assertEqual("global_or_parent_replan", drift["repair"]["repair_type"])
        kinds = {item["kind"] for item in drift["issues"]}
        self.assertTrue({"source_revision_drift", "plan_hash_drift"}.issubset(kinds))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / ".workflow" / "artifacts" / "EV-01.json"
            artifact.parent.mkdir(parents=True)
            artifact.write_text("first\n", encoding="utf-8")
            state["artifacts"][0]["content_hash"] = "sha256:" + sha256(artifact.read_bytes()).hexdigest()
            fresh = reconcile(state, workflow_root=root / ".workflow", verify_artifacts=True)
            self.assertEqual("fresh", fresh["status"])
            artifact.write_text("tampered\n", encoding="utf-8")
            changed = reconcile(state, workflow_root=root / ".workflow", verify_artifacts=True)
            self.assertIn("artifact_content_changed", {item["kind"] for item in changed["issues"]})
            self.assertIn("N-02", changed["repair"]["affected"])

    def test_reconcile_accepts_event_lag_and_rejects_future_state(self) -> None:
        state = _base()
        events = load_json_lines(EVENT_FIXTURE)
        self.assertEqual("fresh", reconcile(state, verify_artifacts=False, events=events, event_schema=EVENT_SCHEMA)["status"])
        events[-1]["state_version"] = 4
        result = reconcile(state, verify_artifacts=False, events=events, event_schema=EVENT_SCHEMA)
        self.assertFalse(result["resume_allowed"])
        self.assertIn("event_future_state", {item["kind"] for item in result["issues"]})

    def test_reconcile_blocks_resume_when_a_resource_lease_expired_mid_run(self) -> None:
        state = _base()
        locks = _locks(state, [{
            "lease_id": "sha256:" + "8" * 64,
            "producer_id": state["active_frontier"]["card_id"],
            "decision_id": state["active_frontier"]["decision_id"],
            "lease_expires_at": "2026-07-13T11:00:00+08:00",
        }])
        result = reconcile(state, verify_artifacts=False, locks=locks, now_value=NOW)
        self.assertFalse(result["resume_allowed"])
        self.assertIn("lock_expired", {item["kind"] for item in result["issues"]})

        foreign = deepcopy(locks)
        foreign["workflow_id"] = "sqw-workflow:" + "b" * 64
        foreign_result = reconcile(state, verify_artifacts=False, locks=foreign, now_value=NOW)
        self.assertFalse(foreign_result["resume_allowed"])
        self.assertIn("locks_owner_invalid", {item["kind"] for item in foreign_result["issues"]})

    def test_reconcile_reports_live_todo_drift_without_treating_todo_as_canonical(self) -> None:
        state = _base()
        result = reconcile(state, verify_artifacts=False, todo_snapshot={"N-01": "in_progress", "N-404": "pending"})
        kinds = {item["kind"] for item in result["issues"]}
        self.assertTrue({"todo_status_drift", "todo_missing_live_node", "todo_orphan"}.issubset(kinds))
        self.assertEqual("local", result["repair"]["repair_type"])
        self.assertIn("N-01", result["repair"]["affected"])

    def test_adapter_exposes_only_operator_event_append_and_internal_resume(self) -> None:
        removed = {"initialize", "commit_state", "acquire_lock", "release_lock", "store_artifact", "orphan_artifacts"}
        self.assertTrue(all(not hasattr(LocalWorkflowAdapter, name) for name in removed))
        self.assertTrue(callable(LocalWorkflowAdapter.resume))
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "local_workflow_adapter.py"), "/tmp/non-owner", "init"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("invalid choice", result.stderr)

    def test_bootstrap_keeps_operator_event_stream_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state = _owner(Path(directory))
            self.assertEqual({".adapter.lock", "artifacts", "locks.json", "projections", "state.json"}, {path.name for path in root.iterdir()})
            info = root.stat()
            semantics = {
                "bundle_id": "frontier-engineering/6.0.0+5.0.0",
                "mode": "M2",
                "entry_completion_id": "sha256:" + "4" * 64,
                "scope_binding_id": "sha256:" + "6" * 64,
                "source_identity": {"kind": "unversioned", "identity_hash": "sha256:" + "7" * 64},
                "initial_root_binding": {"dev": info.st_dev, "ino": info.st_ino, "uid": info.st_uid, "mode": info.st_mode & 0o777},
            }
            expected = "sha256:" + sha256(json.dumps(semantics, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self.assertEqual(expected, state["bootstrap"]["operation_id"])

    def test_bootstrap_real_sigkill_prefixes_converge_by_exact_retry(self) -> None:
        checkpoints = (
            "lock_temp_fsynced",
            "lock_linked",
            "lock_link_parent_synced",
            "lock_cleaned",
            "lock_cleanup_parent_synced",
            "state_temp_fsynced",
            "initial_locks_temp_fsynced",
            "initial_locks_linked",
            "initial_locks_link_parent_synced",
            "initial_locks_cleaned",
            "initial_locks_cleanup_parent_synced",
            "artifacts_created",
            "projections_created",
            "state_linked",
            "state_link_parent_synced",
            "state_cleaned",
            "state_cleanup_parent_synced",
            "lease_temp_fsynced",
            "lease_replaced",
            "lease_parent_synced",
        )
        prefixes = {
            "lock_temp_fsynced": {".adapter.lock.tmp"},
            "lock_linked": {".adapter.lock", ".adapter.lock.tmp"},
            "lock_link_parent_synced": {".adapter.lock", ".adapter.lock.tmp"},
            "lock_cleaned": {".adapter.lock"},
            "lock_cleanup_parent_synced": {".adapter.lock"},
            "state_temp_fsynced": {".adapter.lock", ".state.json.tmp"},
            "initial_locks_temp_fsynced": {".adapter.lock", ".state.json.tmp", ".locks.json.tmp"},
            "initial_locks_linked": {".adapter.lock", ".state.json.tmp", ".locks.json.tmp", "locks.json"},
            "initial_locks_link_parent_synced": {".adapter.lock", ".state.json.tmp", ".locks.json.tmp", "locks.json"},
            "initial_locks_cleaned": {".adapter.lock", ".state.json.tmp", "locks.json"},
            "initial_locks_cleanup_parent_synced": {".adapter.lock", ".state.json.tmp", "locks.json"},
            "artifacts_created": {".adapter.lock", ".state.json.tmp", "locks.json", "artifacts"},
            "projections_created": {".adapter.lock", ".state.json.tmp", "locks.json", "artifacts", "projections"},
            "state_linked": {".adapter.lock", ".state.json.tmp", "state.json", "locks.json", "artifacts", "projections"},
            "state_link_parent_synced": {".adapter.lock", ".state.json.tmp", "state.json", "locks.json", "artifacts", "projections"},
            "state_cleaned": {".adapter.lock", "state.json", "locks.json", "artifacts", "projections"},
            "state_cleanup_parent_synced": {".adapter.lock", "state.json", "locks.json", "artifacts", "projections"},
            "lease_temp_fsynced": {".adapter.lock", "state.json", "locks.json", ".locks.json.tmp", "artifacts", "projections"},
            "lease_replaced": {".adapter.lock", "state.json", "locks.json", "artifacts", "projections"},
            "lease_parent_synced": {".adapter.lock", "state.json", "locks.json", "artifacts", "projections"},
        }
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                source = parent / "source"
                root = parent / "workflow"
                ready = parent / "ready"
                source.mkdir(mode=0o700)
                root.mkdir(mode=0o700)
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--bootstrap-worker", str(root), str(source), checkpoint, str(ready)],
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
                    self.fail(f"worker did not reach {checkpoint}: rc={process.returncode} stdout={stdout!r} stderr={stderr!r}")
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(-signal.SIGKILL, process.returncode, stdout + stderr)
                self.assertEqual(prefixes[checkpoint], {path.name for path in root.iterdir()})
                self.assertFalse((root / "events.jsonl").exists())
                if checkpoint == "state_cleaned":
                    self.assertEqual([], json.loads((root / "locks.json").read_text(encoding="utf-8"))["leases"])
                if checkpoint == "lease_temp_fsynced":
                    self.assertEqual([], json.loads((root / "locks.json").read_text(encoding="utf-8"))["leases"])
                    self.assertEqual(1, len(json.loads((root / ".locks.json.tmp").read_text(encoding="utf-8"))["leases"]))
                if checkpoint in {"lease_replaced", "lease_parent_synced"}:
                    self.assertEqual(1, len(json.loads((root / "locks.json").read_text(encoding="utf-8"))["leases"]))

                state, locator, lease = _bootstrap(root, source)
                self.assertEqual(state["workflow_id"], locator["workflow_id"])
                self.assertEqual(state["active_frontier"]["card_id"], lease["producer_id"])
                self.assertEqual({".adapter.lock", "artifacts", "locks.json", "projections", "state.json"}, {path.name for path in root.iterdir()})
                identities = {
                    name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes())
                    for name in (".adapter.lock", "state.json", "locks.json")
                }
                replay = _bootstrap(root, source)
                self.assertEqual((state, locator, lease), replay)
                self.assertEqual(
                    identities,
                    {name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes()) for name in identities},
                )

    def test_resume_replacement_lease_real_sigkill_prefixes_converge(self) -> None:
        for checkpoint in ("route_lease_temp_fsynced", "route_lease_replaced", "route_lease_parent_synced"):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, state = _owner(parent)
                ready = parent / "ready"
                locator = {
                    "schema_version": "sqw-workflow-owner/1",
                    "workflow_id": state["workflow_id"],
                    "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                    "bundle_id": state["bundle_id"],
                    "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
                    "scope_binding_id": state["scope_binding"]["binding_id"],
                    "mode": state["mode"],
                    "initial_root_binding_hash": workflow_adapter._value_hash(state["bootstrap"]["initial_root_binding"]),
                }
                state_identity = ((root / "state.json").stat().st_ino, (root / "state.json").stat().st_mtime_ns, (root / "state.json").read_bytes())
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--resume-worker", str(root), checkpoint, str(ready)],
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
                    self.fail(f"worker did not reach {checkpoint}: rc={process.returncode} stdout={stdout!r} stderr={stderr!r}")
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(-signal.SIGKILL, process.returncode, stdout + stderr)
                if checkpoint == "route_lease_temp_fsynced":
                    self.assertTrue((root / ".locks.json.tmp").is_file())
                else:
                    self.assertFalse((root / ".locks.json.tmp").exists())

                adapter = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA)
                resume_args = {
                    "expected_bundle_id": state["bundle_id"],
                    "expected_policy_bundle_hash": state["policy_bundle_hash"],
                    "expected_card_manifest_hash": state["card_manifest_hash"],
                    "expected_cards": {state["active_frontier"]["card_id"]: (state["active_frontier"]["card_path"], state["active_frontier"]["card_hash"])},
                    "now_value": RESUME_NOW,
                }
                resumed_state, lease = adapter.resume(locator, state["source_identity"], **resume_args)
                self.assertEqual(state, resumed_state)
                self.assertEqual(state["active_frontier"]["card_id"], lease["producer_id"])
                self.assertEqual(1, len(load_json(root / "locks.json")["leases"]))
                self.assertFalse((root / ".locks.json.tmp").exists())
                self.assertEqual(
                    state_identity,
                    ((root / "state.json").stat().st_ino, (root / "state.json").stat().st_mtime_ns, (root / "state.json").read_bytes()),
                )
                locks_identity = ((root / "locks.json").stat().st_ino, (root / "locks.json").stat().st_mtime_ns, (root / "locks.json").read_bytes())
                replay_state, replay_lease = adapter.resume(locator, state["source_identity"], **resume_args)
                self.assertEqual((resumed_state, lease), (replay_state, replay_lease))
                self.assertEqual(
                    locks_identity,
                    ((root / "locks.json").stat().st_ino, (root / "locks.json").stat().st_mtime_ns, (root / "locks.json").read_bytes()),
                )

    def test_inline_completion_real_sigkill_prefixes_converge(self) -> None:
        checkpoints = (
            "card_state_temp_fsynced",
            "card_state_replaced",
            "card_state_parent_synced",
            "card_locks_temp_fsynced",
            "card_locks_replaced",
            "card_locks_parent_synced",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, _ = _owner(parent)
                ready = parent / "ready"
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--complete-worker", str(root), checkpoint, str(ready)],
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
                    self.fail(f"worker did not reach {checkpoint}: rc={process.returncode} stdout={stdout!r} stderr={stderr!r}")
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(-signal.SIGKILL, process.returncode, stdout + stderr)

                committed, lease = _complete_inline(root)
                self.assertEqual((2, "sqw.test.oracle-and-lifecycle"), (committed["state_version"], committed["active_frontier"]["card_id"]))
                self.assertEqual(lease, load_json(root / "locks.json")["leases"][0])
                self.assertFalse((root / ".state.json.tmp").exists())
                self.assertFalse((root / ".locks.json.tmp").exists())
                identities = {
                    name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes())
                    for name in ("state.json", "locks.json")
                }
                replay = _complete_inline(root)
                self.assertEqual((committed, lease), replay)
                self.assertEqual(
                    identities,
                    {name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes()) for name in identities},
                )

    def test_resume_aborts_prepared_inline_completion_without_human_input(self) -> None:
        for drifted in (False, True):
            with self.subTest(drifted=drifted), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, state = _owner(parent)
                ready = parent / "ready"
                control_identity = {
                    name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes())
                    for name in ("state.json", "locks.json")
                }
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--complete-worker", str(root), "card_state_temp_fsynced", str(ready)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "worker did not prepare state temp")
                process.kill()
                process.communicate(timeout=5)
                self.assertTrue((root / ".state.json.tmp").is_file())
                locator = {
                    "schema_version": "sqw-workflow-owner/1",
                    "workflow_id": state["workflow_id"],
                    "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                    "bundle_id": state["bundle_id"],
                    "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
                    "scope_binding_id": state["scope_binding"]["binding_id"],
                    "mode": state["mode"],
                    "initial_root_binding_hash": workflow_adapter._value_hash(state["bootstrap"]["initial_root_binding"]),
                }
                source_identity = {"kind": "unversioned", "identity_hash": "sha256:" + ("0" if drifted else "7") * 64}
                adapter = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA)
                arguments = {
                    "expected_bundle_id": state["bundle_id"],
                    "expected_policy_bundle_hash": state["policy_bundle_hash"],
                    "expected_card_manifest_hash": state["card_manifest_hash"],
                    "expected_cards": {
                        state["active_frontier"]["card_id"]: (state["active_frontier"]["card_path"], state["active_frontier"]["card_hash"]),
                        "sqw.test.oracle-and-lifecycle": ("references/test/oracle-and-lifecycle.md", "sha256:" + "9" * 64),
                    },
                    "now_value": NOW,
                }
                if drifted:
                    with self.assertRaises(workflow_adapter.AdapterSourceDrift):
                        adapter.resume(locator, source_identity, **arguments)
                else:
                    resumed, lease = adapter.resume(locator, source_identity, **arguments)
                    self.assertEqual((state, load_json(root / "locks.json")["leases"][0]), (resumed, lease))
                self.assertFalse((root / ".state.json.tmp").exists())
                self.assertEqual(
                    control_identity,
                    {
                        name: ((root / name).stat().st_ino, (root / name).stat().st_mtime_ns, (root / name).read_bytes())
                        for name in ("state.json", "locks.json")
                    },
                )

    def test_locator_only_resume_finishes_postcommit_locks(self) -> None:
        checkpoints = (
            "card_state_replaced",
            "card_state_parent_synced",
            "card_locks_temp_fsynced",
            "card_locks_replaced",
            "card_locks_parent_synced",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, initial = _owner(parent)
                ready = parent / "ready"
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--complete-worker", str(root), checkpoint, str(ready)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), f"worker did not reach {checkpoint}")
                process.kill()
                process.communicate(timeout=5)
                committed = load_json(root / "state.json")
                self.assertEqual(2, committed["state_version"])
                locator = {
                    "schema_version": "sqw-workflow-owner/1",
                    "workflow_id": committed["workflow_id"],
                    "bootstrap_operation_id": committed["bootstrap"]["operation_id"],
                    "bundle_id": committed["bundle_id"],
                    "initial_source_identity_hash": committed["bootstrap"]["initial_source_identity_hash"],
                    "scope_binding_id": committed["scope_binding"]["binding_id"],
                    "mode": committed["mode"],
                    "initial_root_binding_hash": workflow_adapter._value_hash(committed["bootstrap"]["initial_root_binding"]),
                }
                adapter = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA)
                resumed, lease = adapter.resume(
                    locator,
                    committed["source_identity"],
                    expected_bundle_id=committed["bundle_id"],
                    expected_policy_bundle_hash=committed["policy_bundle_hash"],
                    expected_card_manifest_hash=committed["card_manifest_hash"],
                    expected_cards={
                        initial["active_frontier"]["card_id"]: (initial["active_frontier"]["card_path"], initial["active_frontier"]["card_hash"]),
                        committed["active_frontier"]["card_id"]: (committed["active_frontier"]["card_path"], committed["active_frontier"]["card_hash"]),
                    },
                    now_value=NOW,
                )
                self.assertEqual(committed, resumed)
                self.assertEqual(committed["active_frontier"]["card_id"], lease["producer_id"])
                self.assertEqual([lease], load_json(root / "locks.json")["leases"])
                self.assertFalse((root / ".state.json.tmp").exists())
                self.assertFalse((root / ".locks.json.tmp").exists())

    def test_materialized_completion_real_sigkill_prefixes_converge(self) -> None:
        checkpoints = (
            "card_state_temp_fsynced",
            "card_artifact_temp_fsynced",
            "card_artifact_linked",
            "card_artifact_link_parent_synced",
            "card_artifact_cleaned",
            "card_artifact_cleanup_parent_synced",
            "card_state_replaced",
            "card_state_parent_synced",
            "card_locks_temp_fsynced",
            "card_locks_replaced",
            "card_locks_parent_synced",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, _ = _handoff_owner(parent)
                ready = parent / "ready"
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--complete-materialized-worker", str(root), checkpoint, str(ready)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), f"worker did not reach {checkpoint}")
                process.kill()
                process.communicate(timeout=5)
                committed, lease = _complete_materialized(root)
                self.assertEqual((2, "completed", None), (committed["state_version"], committed["status"], lease))
                entry = committed["card_completions"][-1]
                final_name, temp_name = workflow_adapter._artifact_names(entry["content_locator"])
                self.assertTrue((root / "artifacts" / final_name).is_file())
                self.assertFalse((root / "artifacts" / temp_name).exists())
                self.assertEqual([], load_json(root / "locks.json")["leases"])
                self.assertFalse((root / ".state.json.tmp").exists())
                identities = {
                    str(path.relative_to(root)): (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                    for path in (root / "state.json", root / "locks.json", root / "artifacts" / final_name)
                }
                replay = _complete_materialized(root)
                self.assertEqual((committed, lease), replay)
                self.assertEqual(
                    identities,
                    {
                        str(path.relative_to(root)): (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes())
                        for path in (root / "state.json", root / "locks.json", root / "artifacts" / final_name)
                    },
                )

    def test_resume_aborts_prepared_materialized_completion_and_preserves_final_orphan(self) -> None:
        for checkpoint, final_expected in (
            ("card_artifact_temp_fsynced", False),
            ("card_artifact_linked", True),
            ("card_artifact_cleaned", True),
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root, state = _handoff_owner(parent)
                ready = parent / "ready"
                process = subprocess.Popen(
                    [sys.executable, "-B", __file__, "--complete-materialized-worker", str(root), checkpoint, str(ready)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                deadline = time.monotonic() + 5
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), f"worker did not reach {checkpoint}")
                process.kill()
                process.communicate(timeout=5)
                prepared = load_json(root / ".state.json.tmp")
                artifact_entry = prepared["card_completions"][-1]
                final_name, temp_name = workflow_adapter._artifact_names(artifact_entry["content_locator"])
                locator = {
                    "schema_version": "sqw-workflow-owner/1",
                    "workflow_id": state["workflow_id"],
                    "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                    "bundle_id": state["bundle_id"],
                    "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
                    "scope_binding_id": state["scope_binding"]["binding_id"],
                    "mode": state["mode"],
                    "initial_root_binding_hash": workflow_adapter._value_hash(state["bootstrap"]["initial_root_binding"]),
                }
                resumed, lease = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA).resume(
                    locator,
                    state["source_identity"],
                    expected_bundle_id=state["bundle_id"],
                    expected_policy_bundle_hash=state["policy_bundle_hash"],
                    expected_card_manifest_hash=state["card_manifest_hash"],
                    expected_cards={state["active_frontier"]["card_id"]: (state["active_frontier"]["card_path"], state["active_frontier"]["card_hash"])},
                    now_value=NOW,
                )
                self.assertEqual(state, resumed)
                self.assertEqual(state["active_frontier"]["card_id"], lease["producer_id"])
                self.assertFalse((root / ".state.json.tmp").exists())
                self.assertFalse((root / "artifacts" / temp_name).exists())
                self.assertEqual(final_expected, (root / "artifacts" / final_name).exists())

    def test_bootstrap_rejects_skipped_or_foreign_prefix_before_mutation(self) -> None:
        for entry in ("projections", ".state.json.tmp"):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                source = parent / "source"
                root = parent / "workflow"
                source.mkdir(mode=0o700)
                root.mkdir(mode=0o700)
                target = root / entry
                if entry == "projections":
                    target.mkdir(mode=0o700)
                else:
                    target.write_bytes(b"foreign-prepared-state\n")
                    os.chmod(target, 0o600)
                before = (sorted(path.name for path in root.iterdir()), target.stat().st_ino, target.stat().st_mtime_ns, target.read_bytes() if target.is_file() else None)
                with self.assertRaises(AdapterConflict):
                    _bootstrap(root, source)
                after = (sorted(path.name for path in root.iterdir()), target.stat().st_ino, target.stat().st_mtime_ns, target.read_bytes() if target.is_file() else None)
                self.assertEqual(before, after)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root, _ = _owner(parent)
            event = _event(0)
            sidecar = root / "events.jsonl"
            sidecar.write_bytes((json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
            os.chmod(sidecar, 0o600)
            before = {path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None) for path in root.iterdir()}
            with self.assertRaisesRegex(AdapterConflict, "another owner"):
                _bootstrap(root, parent / "source")
            self.assertEqual(before, {path.name: (path.stat().st_ino, path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None) for path in root.iterdir()})

    def test_operator_event_first_followup_and_exact_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state = _owner(Path(directory))
            adapter = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA)
            event = _event(0)
            event["workflow_id"] = state["workflow_id"]
            state_before = (root / "state.json").read_bytes(), (root / "state.json").stat().st_mtime_ns
            locks_before = (root / "locks.json").read_bytes(), (root / "locks.json").stat().st_mtime_ns
            self.assertFalse(adapter.append_event(event, expected_last_sequence=0))
            first_stat = (root / "events.jsonl").stat()
            os.link(root / "events.jsonl", root / ".events.jsonl.tmp")
            self.assertTrue(adapter.append_event(event, expected_last_sequence=0))
            self.assertFalse((root / ".events.jsonl.tmp").exists())
            self.assertEqual(first_stat.st_ino, (root / "events.jsonl").stat().st_ino)
            self.assertEqual(first_stat.st_mtime_ns, (root / "events.jsonl").stat().st_mtime_ns)
            followup = _event(1)
            followup["workflow_id"] = state["workflow_id"]
            followup["state_version"] = state["state_version"]
            self.assertFalse(adapter.append_event(followup, expected_last_sequence=1))
            self.assertEqual([event, followup], load_json_lines(root / "events.jsonl"))
            self.assertFalse((root / ".events.jsonl.tmp").exists())
            event_before = (root / "events.jsonl").read_bytes(), (root / "events.jsonl").stat().st_mtime_ns
            replay_state, _, _ = _bootstrap(root, Path(directory) / "source")
            self.assertEqual(state, replay_state)
            self.assertEqual(event_before, ((root / "events.jsonl").read_bytes(), (root / "events.jsonl").stat().st_mtime_ns))
            self.assertEqual(state_before, ((root / "state.json").read_bytes(), (root / "state.json").stat().st_mtime_ns))
            self.assertEqual(locks_before, ((root / "locks.json").read_bytes(), (root / "locks.json").stat().st_mtime_ns))

    def test_operator_event_recovers_matching_fixed_first_write_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state = _owner(Path(directory))
            event = _event(0)
            event["workflow_id"] = state["workflow_id"]
            (root / ".events.jsonl.tmp").write_bytes((json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode())
            os.chmod(root / ".events.jsonl.tmp", 0o600)
            self.assertFalse(LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA).append_event(event, expected_last_sequence=0))
            self.assertEqual([event], load_json_lines(root / "events.jsonl"))
            self.assertFalse((root / ".events.jsonl.tmp").exists())

    def test_operator_event_rejects_future_owner_and_fork_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root, state = _owner(Path(directory))
            adapter = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA)
            future = _event(0)
            future["workflow_id"] = state["workflow_id"]
            future["state_version"] = state["state_version"] + 1
            with self.assertRaisesRegex(AdapterConflict, "current workflow owner"):
                adapter.append_event(future, expected_last_sequence=0)
            wrong_owner = _event(0)
            with self.assertRaisesRegex(AdapterConflict, "current workflow owner"):
                adapter.append_event(wrong_owner, expected_last_sequence=0)
            self.assertFalse((root / "events.jsonl").exists())
            self.assertFalse((root / ".events.jsonl.tmp").exists())

            event = _event(0)
            event["workflow_id"] = state["workflow_id"]
            adapter.append_event(event, expected_last_sequence=0)
            fork = deepcopy(event)
            fork["event_id"] = "evt-fork"
            with self.assertRaisesRegex(AdapterConflict, "stale event sequence"):
                adapter.append_event(fork, expected_last_sequence=0)
            self.assertEqual([event], load_json_lines(root / "events.jsonl"))

    def test_plugin_adapter_is_documented_as_gated_fallback_only(self) -> None:
        local = (ROOT / "adapters" / "local-filesystem.md").read_text(encoding="utf-8")
        plugin = (ROOT / "adapters" / "plugin-runtime.md").read_text(encoding="utf-8")
        self.assertIn("M2", local)
        self.assertIn("atomic", local.lower())
        self.assertIn("empirical_validation_required", plugin)
        self.assertIn("local-filesystem", plugin)
        self.assertNotIn("enabled: true", plugin.lower())


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--bootstrap-worker":
        _bootstrap_worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]))
    elif len(sys.argv) == 5 and sys.argv[1] == "--resume-worker":
        _resume_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    elif len(sys.argv) == 5 and sys.argv[1] == "--complete-worker":
        _complete_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    elif len(sys.argv) == 5 and sys.argv[1] == "--complete-materialized-worker":
        _complete_materialized_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
    else:
        unittest.main()
