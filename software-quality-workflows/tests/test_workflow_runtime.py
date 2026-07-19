from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
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

from _workflow_state import load_json, load_json_lines  # noqa: E402
from local_workflow_adapter import AdapterConflict, LocalWorkflowAdapter, bootstrap_v3  # noqa: E402
from project_context import project_context  # noqa: E402
from propagate_invalidation import propagate_invalidation  # noqa: E402
from reconcile_workflow import reconcile  # noqa: E402


STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")
STATE_FIXTURE = ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json"
EVENT_FIXTURE = ROOT / "tests" / "fixtures" / "workflow-events" / "valid-events.jsonl"
NOW = "2026-07-13T11:30:00+08:00"


def _base() -> dict:
    return load_json(STATE_FIXTURE)


def _node(state: dict, node_id: str) -> dict:
    return next(item for item in state["nodes"] if item["id"] == node_id)


def _event(index: int = 0) -> dict:
    return deepcopy(load_json_lines(EVENT_FIXTURE)[index])


def _owner(parent: Path) -> tuple[Path, dict]:
    source = parent / "source"
    root = parent / "workflow"
    source.mkdir(mode=0o700)
    root.mkdir(mode=0o700)
    state, _, _ = bootstrap_v3(
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
        next_step={
            "kind": "card",
            "decision_id": "sqw.select.behavior-cycle",
            "card_id": "sqw.execute.behavior-cycle",
            "card_path": "references/execution/behavior-cycle.md",
            "card_hash": "sha256:" + "8" * 64,
        },
    )
    return root, state


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
        self.assertEqual("local", relevant["repair_type"])
        global_result = propagate_invalidation(state, {"I-01"})
        self.assertEqual("global_or_parent_replan", global_result["repair_type"])
        self.assertIn("global_invariant_changed", global_result["escalation_reasons"])

    def test_reconcile_detects_source_plan_and_artifact_drift(self) -> None:
        state = _base()
        drift = reconcile(state, current_revision="new-revision", current_scope_hash=state["source"]["scope_hash"], current_plan_hash="sha256:" + "9" * 64, verify_artifacts=False)
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
        locks = {"leases": [{
            "lease_id": "sha256:" + "8" * 64,
            "producer_id": "sqw.execute.behavior-cycle",
            "decision_id": "behavior-cycle",
            "lease_expires_at": "2026-07-13T11:00:00+08:00",
        }]}
        result = reconcile(state, verify_artifacts=False, locks=locks, now_value=NOW)
        self.assertFalse(result["resume_allowed"])
        self.assertIn("lock_expired", {item["kind"] for item in result["issues"]})

    def test_reconcile_reports_live_todo_drift_without_treating_todo_as_canonical(self) -> None:
        state = _base()
        result = reconcile(state, verify_artifacts=False, todo_snapshot={"N-01": "in_progress", "N-404": "pending"})
        kinds = {item["kind"] for item in result["issues"]}
        self.assertTrue({"todo_status_drift", "todo_missing_live_node", "todo_orphan"}.issubset(kinds))
        self.assertEqual("local", result["repair"]["repair_type"])
        self.assertIn("N-01", result["repair"]["affected"])

    def test_adapter_exposes_only_operator_event_append(self) -> None:
        removed = {"initialize", "commit_state", "acquire_lock", "release_lock", "store_artifact", "orphan_artifacts", "resume"}
        self.assertTrue(all(not hasattr(LocalWorkflowAdapter, name) for name in removed))
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
            root, _ = _owner(Path(directory))
            self.assertEqual({".adapter.lock", "artifacts", "locks.json", "projections", "state.json"}, {path.name for path in root.iterdir()})

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
    unittest.main()
