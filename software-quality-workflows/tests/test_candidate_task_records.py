from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = Path(__file__).resolve().parent
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _workflow_state import canonical_artifact_hash, canonical_hash, load_json, validate_closure_artifact  # noqa: E402
from advance_closure import _validate_generic_artifact  # noqa: E402
from local_workflow_adapter import AdapterConflict, LocalWorkflowAdapter  # noqa: E402
from test_closure_worktree_adapter import _closure_state, _repository  # noqa: E402


STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")
RESULT_SCHEMA = load_json(ROOT / "schemas" / "codex-task-result.schema.json")
ARTIFACT_SCHEMA = load_json(ROOT / "schemas" / "closure-artifacts.schema.json")


def _search_adapter(repo: Path, revision: str) -> LocalWorkflowAdapter:
    state = _closure_state(revision)
    state["closure_run"].update({
        "phase": "SEARCHING",
        "contract_ref": {"artifact_ref": "artifact:contract/CC-001", "content_hash": "sha256:" + "1" * 64, "epoch": 1},
        "baseline_ref": {"artifact_ref": "artifact:baseline/BL-001", "content_hash": "sha256:" + "4" * 64},
        "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001", "content_hash": "sha256:" + "2" * 64, "epoch": 1},
    })
    state["state_hash"] = canonical_hash(state)
    adapter = LocalWorkflowAdapter(repo / ".closure", STATE_SCHEMA, EVENT_SCHEMA)
    adapter.initialize(state)
    return adapter


def _task(adapter: LocalWorkflowAdapter, revision: str, *, task_id: str = "TASK-CAND-0007-A01") -> dict:
    state = adapter.load_state()
    run = state["closure_run"]
    return {
        "task_id": task_id,
        "run_id": "RUN-001",
        "role": "candidate_worker",
        "objective": "Make charge return the new deterministic value.",
        "working_directory": str(adapter.root / "worktrees" / "CAND-0007"),
        "source_revision": revision,
        "contract_ref": {"artifact_ref": run["contract_ref"]["artifact_ref"], "hash": run["contract_ref"]["content_hash"], "epoch": 1},
        "plan_ref": {"artifact_ref": "artifact:plan/PLAN-001", "hash": state["plan_ref"]["content_hash"]},
        "policy_bundle_hash": state["policy_bundle_hash"],
        "constraint_refs": ["HC-001"],
        "counterexample_refs": [],
        "allowed_write_paths": ["src/payments/**", "tests/payments/**"],
        "protected_paths": [".closure-view/**", ".closure/**", "tests/holdout/**"],
        "required_outputs": ["candidate_manifest", "change_summary", "verification_requests"],
        "forbidden_actions": ["publish", "change_contract", "change_verifier_kernel", "promote", "close"],
        "stop_conditions": ["task_completed", "scope_blocked", "environment_blocked"],
        "sandbox_profile": "workspace-write",
        "network_policy": {"enabled": False, "allowed_domains": []},
        "timeout_seconds": 900,
    }


def _session(task: dict) -> dict:
    return {
        "task_id": task["task_id"],
        "session_id": "session-0007",
        "source_revision": task["source_revision"],
        "contract_hash": task["contract_ref"]["hash"],
        "contract_epoch": task["contract_ref"]["epoch"],
        "plan_hash": task["plan_ref"]["hash"],
        "policy_bundle_hash": task["policy_bundle_hash"],
        "capability_fingerprint": "sha256:" + "9" * 64,
        "events_path": f"tasks/{task['task_id']}.codex-events.jsonl",
        "result_path": f"tasks/{task['task_id']}.codex-output.json",
        "progress_path": f"tasks/{task['task_id']}.codex-progress.log",
    }


def _write_session_outputs(adapter: LocalWorkflowAdapter, session: dict, result: dict) -> None:
    for field, payload in (
        ("events_path", b'{"type":"task_started"}\n'),
        ("progress_path", b"bounded progress\n"),
        ("result_path", json.dumps(result).encode("utf-8")),
    ):
        path = adapter.root / session[field]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _result(task: dict) -> dict:
    return {
        "task_id": task["task_id"],
        "status": "completed",
        "candidate_ref": "artifact:candidate/C-0007",
        "changed_paths": ["src/payments/charge.py"],
        "proposed_events": ["candidate_generated", "verification_requested"],
        "verification_requests": ["VR-FOCUSED-001"],
        "blocker": None,
        "claims": [{"claim": "The focused behavior changed.", "evidence_refs": [], "confidence_scope": "candidate worktree only"}],
    }


def _manifest(adapter: LocalWorkflowAdapter, task: dict, snapshot: dict) -> dict:
    state = adapter.load_state()
    run = state["closure_run"]
    artifact = {
        "schema_id": "sqw://closure-artifacts/candidate-manifest/1.0",
        "artifact_id": "CM-0007",
        "workflow_id": state["workflow_id"],
        "closure_epoch": run["contract_ref"]["epoch"],
        "source_revision": state["source"]["observed_revision"],
        "scope_hash": state["source"]["scope_hash"],
        "contract_hash": run["contract_ref"]["content_hash"],
        "verifier_bundle_hash": run["verifier_bundle_ref"]["content_hash"],
        "created_at": "2026-07-14T14:00:00+08:00",
        "producer": {"actor": "controller", "run_id": task["run_id"]},
        "classification": "internal",
        "content_hash": "sha256:" + "0" * 64,
        "payload": {
            "candidate_id": "C-0007",
            "parent": None,
            "strategy_family_ref": "SF-001",
            "objective": task["objective"],
            "hypothesis": "A bounded implementation change satisfies the focused contract.",
            "target_counterexample_refs": [],
            "allowed_writes": task["allowed_write_paths"],
            "protected_paths": task["protected_paths"],
            "worktree_ref": "artifact:worktree/CAND-0007",
            "base_candidate_hash": "sha256:" + sha256(task["source_revision"].encode("ascii")).hexdigest(),
            "patch_hash": snapshot["patch_hash"],
            "status": "created",
            "expected_disproof_oracles": ["ORACLE-BEHAVIOR-001"],
        },
    }
    artifact["content_hash"] = canonical_artifact_hash(artifact)
    return artifact


class CandidateTaskRecordTests(unittest.TestCase):
    def test_task_session_result_snapshot_and_manifest_form_one_immutable_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _search_adapter(repo, revision)
            adapter.create_candidate_worktree(
                repo, candidate_id="CAND-0007", base_revision=revision, writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
            )
            task = _task(adapter, revision)
            before_state = adapter.state_path.read_bytes()
            before_events = adapter.events_path.read_bytes()
            prepared = adapter.prepare_codex_task(task)
            self.assertEqual("task_prepared", prepared["status"])
            with self.assertRaises(AdapterConflict):
                adapter.record_codex_result(repo, _result(task), candidate_manifest={})
            session = _session(task)
            _write_session_outputs(adapter, session, _result(task))
            adapter.record_codex_session(task["task_id"], session)

            worktree = Path(task["working_directory"])
            (worktree / "src" / "payments" / "charge.py").write_text("def charge():\n    return 'new'\n", encoding="utf-8")
            snapshot = adapter.inspect_candidate_snapshot(
                repo, candidate_id="CAND-0007", expected_base_revision=revision,
                allowed_write_paths=task["allowed_write_paths"], protected_paths=task["protected_paths"],
            )
            manifest = _manifest(adapter, task, snapshot)
            self.assertEqual([], validate_closure_artifact(
                manifest, ARTIFACT_SCHEMA,
                expected_workflow_id=adapter.load_state()["workflow_id"], expected_closure_epoch=1,
                expected_source_revision=revision, expected_scope_hash=adapter.load_state()["source"]["scope_hash"],
                expected_contract_hash=task["contract_ref"]["hash"],
                expected_verifier_bundle_hash=adapter.load_state()["closure_run"]["verifier_bundle_ref"]["content_hash"],
            ))
            bad_output = adapter.root / session["result_path"]
            bad_output.write_text(json.dumps({**_result(task), "task_id": "TASK-WRONG"}), encoding="utf-8")
            with self.assertRaises(AdapterConflict):
                adapter.record_codex_result(repo, _result(task), candidate_manifest=manifest)
            bad_output.write_text(json.dumps(_result(task)), encoding="utf-8")
            recorded = adapter.record_codex_result(repo, _result(task), candidate_manifest=manifest)
            self.assertEqual("candidate_created", recorded["event_proposal"]["type"])
            self.assertEqual(snapshot["snapshot_hash"], recorded["snapshot"]["snapshot_hash"])
            self.assertTrue((adapter.root / "tasks" / f"{task['task_id']}.result.json").is_file())
            self.assertTrue((adapter.root / "candidate" / "C-0007.json").is_file())
            self.assertTrue((adapter.root / "worktree" / "CAND-0007.json").is_file())
            worktree_artifact = load_json(adapter.root / "worktree" / "CAND-0007.json")
            self.assertEqual([], _validate_generic_artifact("artifact:worktree/CAND-0007", worktree_artifact, adapter.load_state()))
            self.assertEqual(before_state, adapter.state_path.read_bytes())
            self.assertEqual(before_events, adapter.events_path.read_bytes())

            stale = _result(task)
            stale["changed_paths"] = ["tests/payments/test_charge.py"]
            with self.assertRaises(AdapterConflict):
                adapter.record_codex_result(repo, stale, candidate_manifest=manifest)

    def test_session_drift_and_structured_blocker_fail_closed_without_candidate_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _search_adapter(repo, revision)
            adapter.create_candidate_worktree(
                repo, candidate_id="CAND-0007", base_revision=revision, writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
            )
            task = _task(adapter, revision, task_id="TASK-CAND-0007-BLOCKED")
            adapter.prepare_codex_task(task)
            stale_session = _session(task)
            _write_session_outputs(adapter, stale_session, _result(task))
            stale_session["contract_epoch"] = 2
            with self.assertRaises(AdapterConflict):
                adapter.record_codex_session(task["task_id"], stale_session)
            blocked = _result(task)
            blocked.update({
                "status": "blocked", "candidate_ref": None, "changed_paths": [],
                "proposed_events": ["task_blocked"], "verification_requests": [], "claims": [],
                "blocker": {"code": "E_SCOPE_VIOLATION", "summary": "Needed path is outside scope.", "evidence_refs": [], "retryable": False},
            })
            session = _session(task)
            _write_session_outputs(adapter, session, blocked)
            adapter.record_codex_session(task["task_id"], session)
            recorded = adapter.record_codex_result(repo, blocked, candidate_manifest=None)
            self.assertEqual("task_blocked", recorded["event_proposal"]["type"])
            self.assertNotIn("snapshot", recorded)
            self.assertEqual(3, len(recorded["diagnostic_artifacts"]))
            self.assertFalse((adapter.root / "candidate" / "C-0007.json").exists())

    def test_nonzero_codex_exit_without_last_message_maps_to_typed_capacity_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _search_adapter(repo, revision)
            adapter.create_candidate_worktree(
                repo, candidate_id="CAND-0007", base_revision=revision, writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
            )
            task = _task(adapter, revision, task_id="TASK-CAND-0007-CAPACITY")
            adapter.prepare_codex_task(task)
            before_state = adapter.state_path.read_bytes()
            before_events = adapter.events_path.read_bytes()
            session = {
                **_session(task),
                "termination": "failed",
                "exit_code": 1,
            }
            events_path = adapter.root / session["events_path"]
            events_path.parent.mkdir(parents=True, exist_ok=True)
            events_path.write_text(
                '{"type":"error","message":"usage limit reached"}\n'
                '{"type":"turn.failed","error":{"message":"usage limit reached"}}\n',
                encoding="utf-8",
            )
            (adapter.root / session["progress_path"]).write_bytes(b"")

            adapter.record_codex_session(task["task_id"], session)
            recorded = adapter.record_codex_execution_failure(repo, task_id=task["task_id"])

            self.assertEqual("task_blocked", recorded["event_proposal"]["type"])
            self.assertEqual("E_AGENT_CAPACITY", recorded["result"]["blocker"]["code"])
            self.assertTrue(recorded["result"]["blocker"]["retryable"])
            self.assertEqual([], recorded["result"]["changed_paths"])
            self.assertFalse((adapter.root / "candidate" / "C-0007.json").exists())
            self.assertEqual(before_state, adapter.state_path.read_bytes())
            self.assertEqual(before_events, adapter.events_path.read_bytes())

    def test_pre_result_failure_mapping_refuses_partial_agent_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo, revision = _repository(Path(directory))
            adapter = _search_adapter(repo, revision)
            adapter.create_candidate_worktree(
                repo, candidate_id="CAND-0007", base_revision=revision, writer_id="worker-01",
                allowed_write_paths=["src/payments/**", "tests/payments/**"],
                protected_paths=[".closure-view/**", ".closure/**", "tests/holdout/**"],
            )
            task = _task(adapter, revision, task_id="TASK-CAND-0007-PARTIAL")
            adapter.prepare_codex_task(task)
            session = {**_session(task), "termination": "failed", "exit_code": 1}
            events_path = adapter.root / session["events_path"]
            events_path.parent.mkdir(parents=True, exist_ok=True)
            events_path.write_text('{"type":"turn.failed","error":{"message":"execution failed"}}\n', encoding="utf-8")
            (adapter.root / session["progress_path"]).write_bytes(b"")
            adapter.record_codex_session(task["task_id"], session)
            worktree = Path(task["working_directory"])
            (worktree / "src" / "payments" / "charge.py").write_text("partial\n", encoding="utf-8")

            with self.assertRaisesRegex(AdapterConflict, "E_UNBOUND_AGENT_CHANGES"):
                adapter.record_codex_execution_failure(repo, task_id=task["task_id"])
            self.assertFalse((adapter.root / "tasks" / f"{task['task_id']}.result.json").exists())


if __name__ == "__main__":
    unittest.main()
