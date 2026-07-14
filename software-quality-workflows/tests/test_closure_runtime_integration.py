from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _closure import eligible_events  # noqa: E402
from _workflow_state import canonical_hash, load_json  # noqa: E402
from compute_frontier import compute_frontier  # noqa: E402
from local_workflow_adapter import AdapterConflict, LocalWorkflowAdapter  # noqa: E402
from project_context import project_context  # noqa: E402
from propagate_invalidation import propagate_invalidation  # noqa: E402
from reconcile_workflow import reconcile  # noqa: E402
from validate_workflow_state import validate_state  # noqa: E402


STATE_SCHEMA = load_json(ROOT / "schemas" / "workflow-state.schema.json")
EVENT_SCHEMA = load_json(ROOT / "schemas" / "workflow-event.schema.json")
REGISTRY = load_json(ROOT / "references" / "owner-registry.json")


def _closure_state(phase: str = "SPEC_COMPILING") -> dict:
    state = load_json(ROOT / "tests" / "fixtures" / "workflow-state" / "valid-m2.json")
    state["execution_policy"] = "autonomous_closure"
    state["request_mode"] = "change"
    paths = {item["id"]: item["path"] for item in REGISTRY["owners"]}
    normative = ["authority-and-scope", "verifier-kernel", "workflow-state-contract", "workflow-modes", "verification-discipline"]
    state["active_owners"] = {
        "primary": "autonomous-closure",
        "normative": normative,
        "companions": [],
        "loaded_references": [
            {"owner_id": owner, "path": paths[owner], "reason_code": "closure_owner_required", "phase": phase}
            for owner in ["autonomous-closure", *normative]
        ],
    }
    state["closure_run"] = {
        "phase": phase,
        "policy_bundle_hash": state["policy_bundle_hash"],
        "active_candidate_refs": [],
        "active_counterexample_refs": [],
        "budget": {"iterations_used": 0, "iterations_limit": 8, "candidate_evaluations_used": 0, "candidate_evaluations_limit": 10, "review_rounds_used": 0, "review_rounds_limit": 2},
        "terminal_status": None,
        "terminal_certificate_ref": None,
    }
    state["scope"].update({
        "allowed_reads": ["src/**", "tests/**"],
        "allowed_writes": ["src/manifest/**", "tests/manifest/**", "src/payments/**", "tests/payments/**"],
        "protected_paths": [".closure/**", ".closure-view/**", "tests/holdout/**"],
    })
    state.pop("state_hash", None)
    state["state_hash"] = canonical_hash(state)
    return state


def _bound_search_state() -> dict:
    state = _closure_state("SEARCHING")
    run = state["closure_run"]
    run.update({
        "contract_ref": {"artifact_ref": "artifact:contract/CC-001.json", "content_hash": "sha256:" + "1" * 64, "epoch": 1},
        "baseline_ref": {"artifact_ref": "artifact:baseline/BASE-001.json", "content_hash": "sha256:" + "4" * 64},
        "verifier_bundle_ref": {"artifact_ref": "artifact:verifier/VB-001.json", "content_hash": "sha256:" + "2" * 64, "epoch": 1},
        "active_candidate_refs": ["artifact:candidate/CAND-001.json"],
        "active_counterexample_refs": ["artifact:counterexample/CEX-001.json"],
        "incumbent_candidate_ref": "artifact:candidate/CAND-001.json",
    })
    state["state_hash"] = canonical_hash(state)
    return state


class ClosureRuntimeIntegrationTests(unittest.TestCase):
    def test_local_adapter_cannot_commit_or_append_closure_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            adapter = LocalWorkflowAdapter(Path(directory) / ".closure", STATE_SCHEMA, EVENT_SCHEMA)
            state = _closure_state()
            adapter.initialize(state)
            proposed = deepcopy(state)
            proposed["state_version"] += 1
            proposed["closure_run"]["phase"] = "CONTRACT_FROZEN"
            proposed["state_hash"] = canonical_hash(proposed)
            with self.assertRaisesRegex(AdapterConflict, "advance_closure.py"):
                adapter.commit_state(proposed, expected_state_version=state["state_version"])
            with self.assertRaisesRegex(AdapterConflict, "advance_closure.py"):
                adapter.append_event({"type": "contract_frozen"}, expected_last_sequence=0)
            self.assertEqual(state["state_version"], adapter.load_state()["state_version"])
            self.assertEqual(b"", adapter.events_path.read_bytes())

    def test_frontier_projects_phase_prerequisites_without_worker_transition_authority(self) -> None:
        state = _closure_state()
        result = compute_frontier(state, actor="worker-01")
        self.assertEqual([], result["ready"])
        self.assertEqual("SPEC_COMPILING", result["closure"]["phase"])
        self.assertEqual("controller", result["closure"]["transition_authority"])
        self.assertEqual(sorted(eligible_events(state)), result["closure"]["eligible_controller_events"])
        self.assertEqual([], result["closure"]["worker_transition_events"])
        self.assertIn("spec_auditor", result["closure"]["eligible_task_roles"])

        malformed = _closure_state("CONTRACT_FROZEN")
        blocked = compute_frontier(malformed)
        self.assertIn("missing:contract_ref", blocked["closure"]["blocked_reasons"])
        self.assertFalse(blocked["closure"]["phase_ready"])
        malformed["closure_run"]["contract_ref"] = {"artifact_ref": "bad", "content_hash": "bad", "epoch": 0}
        self.assertIn("missing:contract_ref", compute_frontier(malformed)["closure"]["blocked_reasons"])
        drifted = compute_frontier(state, current_revision="different")
        self.assertIn("source:revision-drift", drifted["closure"]["blocked_reasons"])
        exhausted = _bound_search_state()
        exhausted["closure_run"]["budget"]["iterations_used"] = exhausted["closure_run"]["budget"]["iterations_limit"]
        self.assertEqual([], compute_frontier(exhausted)["closure"]["eligible_task_roles"])

    def test_closure_global_and_local_invalidation_use_epoch_restart_semantics(self) -> None:
        state = _bound_search_state()
        self.assertEqual([], validate_state(state, STATE_SCHEMA))
        contract_ref = state["closure_run"]["contract_ref"]["artifact_ref"]
        closure_graph = {
            contract_ref: ["artifact:baseline/BASE-001.json", "artifact:verifier/VB-001.json", "artifact:candidate/CAND-001.json", "artifact:counterexample/CEX-001.json", "artifact:signoff/SIGN-001.json"],
            "artifact:counterexample/CEX-001.json": ["artifact:candidate/CAND-001.json"],
            "artifact:candidate/CAND-001.json": ["artifact:signoff/SIGN-001.json"],
        }
        global_result = propagate_invalidation(state, {contract_ref}, closure_graph=closure_graph)
        self.assertEqual("global_or_parent_replan", global_result["repair_type"])
        self.assertTrue(global_result["closure"]["new_epoch_required"])
        self.assertEqual("SPEC_COMPILING", global_result["closure"]["restart_phase"])
        self.assertIn("artifact:candidate/CAND-001.json", global_result["affected"])
        self.assertIn("artifact:signoff/SIGN-001.json", global_result["affected"])

        local_result = propagate_invalidation(state, {"artifact:counterexample/CEX-001.json"}, closure_graph=closure_graph)
        self.assertFalse(local_result["closure"]["new_epoch_required"])
        self.assertEqual("SEARCHING", local_result["closure"]["restart_phase"])
        self.assertIn("artifact:candidate/CAND-001.json", local_result["affected"])
        self.assertIn("artifact:signoff/SIGN-001.json", local_result["affected"])
        plan_result = propagate_invalidation(state, {"plan"}, closure_graph=closure_graph)
        self.assertTrue(plan_result["closure"]["new_epoch_required"])
        self.assertEqual("SPEC_COMPILING", plan_result["closure"]["restart_phase"])
        self.assertIn("N-02", plan_result["frontier"])

    def test_context_has_a_hard_budget_closure_anchors_and_reference_unload_set(self) -> None:
        state = _bound_search_state()
        state["active_owners"]["loaded_references"].append({
            "owner_id": "risk-based-testing",
            "path": "references/risk-based-testing.md",
            "reason_code": "old_phase_companion",
            "phase": "BASELINING",
        })
        text, metadata = project_context(state, budget_chars=2500)
        self.assertLessEqual(len(text), 2500)
        self.assertIn("## Autonomous closure", text)
        self.assertIn("phase: SEARCHING", text)
        self.assertIn("artifact:contract/CC-001.json", text)
        self.assertIn("transition authority: controller", text)
        self.assertIn("references/risk-based-testing.md", metadata["unload_refs"])
        self.assertNotIn("references/risk-based-testing.md", metadata["loaded_refs"])
        self.assertIn("artifact:candidate/CAND-001.json", metadata["closure_anchor_refs"])

    def test_reconcile_blocks_source_pending_transition_and_orphan_runtime_state(self) -> None:
        state = _bound_search_state()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".closure"
            (root / "worktrees" / "CAND-ORPHAN").mkdir(parents=True)
            (root / "worktree-metadata").mkdir()
            (root / "worktree-metadata" / "CAND-MISSING.json").write_text(json.dumps({
                "schema_version": "1.0", "kind": "candidate", "identifier": "CAND-MISSING",
                "workflow_id": state["workflow_id"], "base_revision": state["source"]["observed_revision"],
                "writer_id": "worker-01", "worktree_path": "worktrees/CAND-MISSING",
                "allowed_write_paths": ["src/**"], "protected_paths": [".closure/**"], "view_hashes": {},
            }), encoding="utf-8")
            (root / "tasks").mkdir()
            (root / "tasks" / "TASK-CAND-0001.task.json").write_text(json.dumps({"task_id": "TASK-CAND-0001"}), encoding="utf-8")
            (root / "tasks" / "TASK-ORPHAN.result.json").write_text(json.dumps({"task_id": "TASK-ORPHAN"}), encoding="utf-8")
            (root / ".advance-pending.json").write_text(json.dumps({"workflow_id": state["workflow_id"]}), encoding="utf-8")
            result = reconcile(
                state,
                current_revision="new-revision",
                workflow_root=root,
                verify_artifacts=False,
            )
            kinds = {item["kind"] for item in result["issues"]}
            self.assertTrue({
                "source_revision_drift", "pending_closure_transition", "orphan_worktree",
                "worktree_missing", "task_pending", "task_result_orphan",
            }.issubset(kinds))
            self.assertFalse(result["resume_allowed"])
            self.assertIn("start_new_source_epoch", result["resume_actions"])
            self.assertIn("replay_pending_advance", result["resume_actions"])

    def test_reconcile_rejects_symlinked_runtime_records_without_following_them(self) -> None:
        state = _bound_search_state()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".closure"
            (root / "tasks").mkdir(parents=True)
            (root / "worktree-metadata").mkdir()
            external = Path(directory) / "external.json"
            external.write_text(json.dumps({"task_id": "TASK-LINK"}), encoding="utf-8")
            (root / "tasks" / "TASK-LINK.task.json").symlink_to(external)
            (root / "worktree-metadata" / "CAND-LINK.archive.json").symlink_to(external)
            result = reconcile(state, workflow_root=root, verify_artifacts=False)
            kinds = {item["kind"] for item in result["issues"]}
            self.assertIn("task_record_invalid", kinds)
            self.assertIn("archive_record_invalid", kinds)
            self.assertFalse(result["resume_allowed"])
            self.assertEqual({"task_id": "TASK-LINK"}, json.loads(external.read_text(encoding="utf-8")))

            (root / "tasks" / "TASK-LINK.task.json").unlink()
            (root / "worktree-metadata" / "CAND-LINK.archive.json").unlink()
            clean = reconcile(state, workflow_root=root, verify_artifacts=False)
            self.assertEqual("fresh", clean["status"])
            self.assertTrue(clean["resume_allowed"])


if __name__ == "__main__":
    unittest.main()
