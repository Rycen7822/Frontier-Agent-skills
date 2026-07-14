from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
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
from compute_frontier import compute_frontier  # noqa: E402
from local_workflow_adapter import AdapterConflict, LocalWorkflowAdapter, append_trace  # noqa: E402
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


class WorkflowRuntimeTests(unittest.TestCase):
    def test_frontier_computes_ready_and_parallel_conflict_batches(self) -> None:
        state = _base()
        base = compute_frontier(state, now_value=NOW, actor="session-main")
        self.assertEqual(["N-02"], base["ready"])
        self.assertEqual([["N-02"]], base["parallel_batches"])
        clone = deepcopy(_node(state, "N-02"))
        clone["id"] = "N-03"
        clone["output_refs"] = ["EV-03"]
        state["nodes"].append(clone)
        result = compute_frontier(state, now_value=NOW, actor="session-main")
        self.assertEqual(["N-02", "N-03"], result["ready"])
        self.assertEqual([["N-02"], ["N-03"]], result["parallel_batches"])
        self.assertTrue(any("conflict" in warning for warning in result["warnings"]))

    def test_frontier_blocks_missing_input_approval_lock_and_unknown_invariant(self) -> None:
        state = _base()
        node = _node(state, "N-02")
        node["input_refs"].append("EV-404")
        node["side_effect"] = "external_reversible"
        state["authority"]["risk_ceiling"] = "external_reversible"
        state["authority"]["external_writes"] = "approved"
        state["global_invariants"][0]["status"] = "unknown"
        state["locks"] = [{
            "id": "LOCK-01", "resource": "working-tree", "owner": "other-session",
            "acquired_at": "2026-07-13T10:00:00+08:00", "lease_expires_at": "2026-07-13T12:00:00+08:00", "state_version": 3
        }]
        result = compute_frontier(state, now_value=NOW, actor="session-main")
        reasons = result["blocked"]["N-02"]
        self.assertTrue(any(item.startswith("missing:EV-404") for item in reasons))
        self.assertTrue(any(item.startswith("approval:") for item in reasons))
        self.assertIn("resource-lock:working-tree", reasons)
        self.assertIn("invariant:I-01:unknown", reasons)
        state["locks"][0]["lease_expires_at"] = "2026-07-13T11:00:00+08:00"
        reasons = compute_frontier(state, now_value=NOW, actor="session-main")["blocked"]["N-02"]
        self.assertIn("expired-lock:LOCK-01", reasons)

    def test_frontier_blocks_artifact_schema_mismatch(self) -> None:
        state = _base()
        state["artifacts"][0]["schema_id"] = "sqw.other-result/1.0"
        reasons = compute_frontier(state, now_value=NOW, actor="session-main")["blocked"]["N-02"]
        self.assertIn("schema-mismatch:EV-01", reasons)

    def test_context_projection_is_bounded_state_versioned_and_secret_safe(self) -> None:
        state = _base()
        state["artifacts"][0]["sensitive"] = True
        state["artifacts"][0]["claim"] = "api_key=RAW_SECRET_1234567890"
        _node(state, "N-02")["sensitive"] = True
        _node(state, "N-02")["objective"] = "Repair private customer Alice record."
        _node(state, "N-02")["read_set"] = ["private/customer-alice.json"]
        text, metadata = project_context(state, budget_chars=900)
        self.assertIn("state_version: 3", text)
        self.assertIn("local_reversible", text)
        self.assertIn("I-01", text)
        self.assertIn("N-02", text)
        self.assertNotIn("RAW_SECRET_1234567890", text)
        self.assertNotIn("customer Alice", text)
        self.assertNotIn("customer-alice.json", text)
        self.assertIn("[SENSITIVE_POINTER]", text)
        self.assertTrue(metadata["budget_exceeded"])
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

    def test_reconcile_detects_event_state_projection_drift(self) -> None:
        state = _base()
        events = load_json_lines(EVENT_FIXTURE)
        self.assertEqual("fresh", reconcile(state, verify_artifacts=False, events=events, event_schema=EVENT_SCHEMA)["status"])
        events[-1]["state_version"] = 4
        result = reconcile(state, verify_artifacts=False, events=events, event_schema=EVENT_SCHEMA)
        self.assertFalse(result["resume_allowed"])
        self.assertIn("state_event_projection_drift", {item["kind"] for item in result["issues"]})

    def test_reconcile_blocks_resume_when_a_resource_lease_expired_mid_run(self) -> None:
        state = _base()
        state["locks"] = [{
            "id": "LOCK-01", "resource": "working-tree", "owner": "session-a",
            "acquired_at": "2026-07-13T10:00:00+08:00", "lease_expires_at": "2026-07-13T11:00:00+08:00", "state_version": 3
        }]
        result = reconcile(state, verify_artifacts=False, now_value=NOW)
        self.assertFalse(result["resume_allowed"])
        self.assertIn("lock_expired", {item["kind"] for item in result["issues"]})

    def test_reconcile_reports_live_todo_drift_without_treating_todo_as_canonical(self) -> None:
        state = _base()
        result = reconcile(state, verify_artifacts=False, todo_snapshot={"N-01": "in_progress", "N-404": "pending"})
        kinds = {item["kind"] for item in result["issues"]}
        self.assertTrue({"todo_status_drift", "todo_missing_live_node", "todo_orphan"}.issubset(kinds))
        self.assertEqual("local", result["repair"]["repair_type"])
        self.assertIn("N-01", result["repair"]["affected"])

    def test_adapter_atomic_commit_crash_and_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalWorkflowAdapter(Path(directory) / ".workflow", STATE_SCHEMA, EVENT_SCHEMA)
            adapter.initialize(_base())
            orphan = adapter.store_artifact(b"artifact-before-state-commit\n", sensitive=False)
            proposed = _base()
            proposed["state_version"] = 4
            proposed["frontier"] = []
            _node(proposed, "N-02")["status"] = "running"
            with self.assertRaises(RuntimeError):
                adapter.commit_state(proposed, expected_state_version=3, failpoint="after_fsync")
            self.assertEqual(3, adapter.load_state()["state_version"])
            self.assertIn(orphan["artifact_ref"], adapter.orphan_artifacts())
            adapter.commit_state(proposed, expected_state_version=3)
            self.assertEqual(4, adapter.load_state()["state_version"])
            with self.assertRaises(AdapterConflict):
                adapter.commit_state(proposed, expected_state_version=3)

    def test_adapter_events_locks_artifacts_and_orphan_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalWorkflowAdapter(Path(directory) / ".workflow", STATE_SCHEMA, EVENT_SCHEMA)
            adapter.initialize(_base())
            adapter.append_event(_event(0), expected_last_sequence=0)
            adapter.append_event(_event(1), expected_last_sequence=1)
            with self.assertRaises(AdapterConflict):
                adapter.append_event(_event(2), expected_last_sequence=1)
            lease = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            adapter.acquire_lock("working-tree", "session-a", lease_expires_at=lease, expected_state_version=3)
            effective = adapter.load_effective_state()
            self.assertEqual("session-a", effective["locks"][0]["owner"])
            self.assertIn("resource-lock:working-tree", compute_frontier(effective, actor="session-b")["blocked"]["N-02"])
            with self.assertRaises(AdapterConflict):
                adapter.acquire_lock("working-tree", "session-b", lease_expires_at=lease, expected_state_version=3)
            adapter.release_lock("working-tree", "session-a")
            with self.assertRaises(ValueError):
                adapter.store_artifact(b"password=RAW_SECRET_1234567890", sensitive=False)
            with self.assertRaises(ValueError):
                adapter.store_artifact(b"private customer record\n", sensitive=True)
            stored = adapter.store_artifact(b"bounded evidence\n", sensitive=False)
            self.assertTrue((adapter.root / stored["artifact_ref"]).is_file())
            self.assertIn(stored["artifact_ref"], adapter.orphan_artifacts())

    def test_adapter_refuses_to_claim_a_nonempty_unmanaged_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".workflow"
            root.mkdir()
            user_file = root / "user-owned.txt"
            user_file.write_text("preserve me\n", encoding="utf-8")
            adapter = LocalWorkflowAdapter(root, STATE_SCHEMA, EVENT_SCHEMA)
            with self.assertRaises(AdapterConflict):
                adapter.initialize(_base())
            self.assertEqual("preserve me\n", user_file.read_text(encoding="utf-8"))

    def test_adapter_recovers_interrupted_initialization_before_state_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalWorkflowAdapter(Path(directory) / ".workflow", STATE_SCHEMA, EVENT_SCHEMA)
            with self.assertRaises(RuntimeError):
                adapter.initialize(_base(), failpoint="before_state")
            self.assertFalse(adapter.state_path.exists())
            self.assertTrue((adapter.root / ".initializing.json").exists())
            adapter.initialize(_base())
            self.assertEqual(3, adapter.load_state()["state_version"])
            self.assertFalse((adapter.root / ".initializing.json").exists())

    def test_adapter_resume_revalidates_complete_local_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalWorkflowAdapter(Path(directory) / ".workflow", STATE_SCHEMA, EVENT_SCHEMA)
            payload = b"focused expected-red evidence\n"
            digest = sha256(payload).hexdigest()
            state = _base()
            state["artifacts"][0]["artifact_ref"] = f".workflow/artifacts/sha256-{digest}.bin"
            state["artifacts"][0]["content_hash"] = f"sha256:{digest}"
            adapter.initialize(state)
            stored = adapter.store_artifact(payload, sensitive=False)
            self.assertEqual(f"artifacts/sha256-{digest}.bin", stored["artifact_ref"])
            for index, event in enumerate(load_json_lines(EVENT_FIXTURE)):
                adapter.append_event(event, expected_last_sequence=index)
            result = adapter.resume(
                current_revision="explicit-unversioned",
                current_scope_hash=state["source"]["scope_hash"],
                current_plan_hash=state["plan_ref"]["content_hash"],
                now_value=NOW,
            )
            self.assertEqual("fresh", result["status"])
            self.assertTrue(result["resume_allowed"])

    def test_m1_trace_append_creates_no_state_or_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace_path = Path(directory) / "trace" / "events.jsonl"
            event = _event(0)
            event["type"] = "route_selected"
            append_trace(trace_path, event, EVENT_SCHEMA, expected_last_sequence=0)
            self.assertEqual([event], load_json_lines(trace_path))
            self.assertFalse((trace_path.parent / "state.json").exists())
            self.assertFalse((trace_path.parent / "locks.json").exists())

    def test_m1_trace_cli_uses_explicit_task_owned_path_without_graph_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_root = Path(directory) / "task"
            task_root.mkdir()
            event_path = task_root / "event.json"
            event = _event(0)
            event["type"] = "route_selected"
            event_path.write_text(json.dumps(event), encoding="utf-8")
            command = [
                sys.executable,
                "-B",
                str(SCRIPTS / "local_workflow_adapter.py"),
                str(task_root),
                "append-trace",
                str(event_path),
                "--trace-path",
                "trace/events.jsonl",
                "--expected-sequence",
                "0",
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            trace_path = task_root / "trace" / "events.jsonl"
            self.assertEqual("trace/events.jsonl", payload["trace_path"])
            self.assertEqual([event], load_json_lines(trace_path))
            self.assertFalse((task_root / ".workflow").exists())
            self.assertFalse((task_root / "state.json").exists())
            self.assertFalse((task_root / "locks.json").exists())

            stale = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(1, stale.returncode)
            self.assertIn("stale trace sequence", stale.stdout)
            self.assertEqual([event], load_json_lines(trace_path))

            escaped_command = list(command)
            escaped_command[escaped_command.index("trace/events.jsonl")] = "../outside.jsonl"
            escaped = subprocess.run(escaped_command, capture_output=True, text=True, check=False)
            self.assertEqual(1, escaped.returncode)
            self.assertIn("inside the explicit task root", escaped.stdout)
            self.assertFalse((Path(directory) / "outside.jsonl").exists())

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
