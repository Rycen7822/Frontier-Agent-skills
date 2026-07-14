from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _workflow_state import load_json  # noqa: E402
from local_workflow_adapter import (  # noqa: E402
    probe_codex_capabilities,
    validate_codex_resume,
    validate_codex_task_envelope,
    validate_codex_task_result,
)


RESULT_SCHEMA_PATH = ROOT / "schemas" / "codex-task-result.schema.json"


def _task(worktree: Path) -> dict:
    return {
        "task_id": "TASK-CAND-0007",
        "run_id": "RUN-001",
        "role": "candidate_worker",
        "objective": "Eliminate duplicate charge under concurrent retries",
        "working_directory": str(worktree),
        "source_revision": "a" * 40,
        "contract_ref": {"artifact_ref": "artifact:contract/CC-001.json", "hash": "sha256:" + "1" * 64, "epoch": 1},
        "plan_ref": {"artifact_ref": "artifact:plan/PLAN-001.json", "hash": "sha256:" + "2" * 64},
        "policy_bundle_hash": "sha256:" + "3" * 64,
        "constraint_refs": ["HC-001", "HC-004"],
        "counterexample_refs": ["CEX-0009"],
        "allowed_write_paths": ["src/payments/**", "tests/payments/**"],
        "protected_paths": [".closure/**", "tests/holdout/**"],
        "required_outputs": ["candidate_manifest", "change_summary", "verification_requests"],
        "forbidden_actions": ["publish", "change_contract", "change_verifier_kernel", "promote", "close"],
        "stop_conditions": ["task_completed", "scope_blocked", "environment_blocked"],
        "sandbox_profile": "workspace-write",
        "network_policy": {"enabled": False, "allowed_domains": []},
        "timeout_seconds": 900,
    }


def _result() -> dict:
    return {
        "task_id": "TASK-CAND-0007",
        "status": "completed",
        "candidate_ref": "artifact:candidate/C-0007",
        "changed_paths": ["src/payments/charge.py"],
        "proposed_events": ["candidate_generated"],
        "verification_requests": ["VR-FOCUSED-001"],
        "blocker": None,
        "claims": [{
            "claim": "idempotency key is enforced atomically",
            "evidence_refs": ["artifact:diff/CAND-0007.patch", "artifact:test/CAND-0007.json"],
            "confidence_scope": "changed implementation only",
        }],
    }


class CodexAdapterContractTests(unittest.TestCase):
    def test_result_schema_is_strict_draft_2020_12_and_semantically_bound(self) -> None:
        schema = load_json(RESULT_SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "worktrees"
            worktree = root / "CAND-0007"
            task = _task(worktree)
            self.assertEqual([], validate_codex_task_envelope(task, worktrees_root=root))
            self.assertEqual([], validate_codex_task_result(_result(), schema, task=task))

            unknown = {**_result(), "canonical_transition": "CLOSED"}
            self.assertTrue(any("E_SCHEMA_INVALID" in item for item in validate_codex_task_result(unknown, schema, task=task)))

            protected = deepcopy(_result())
            protected["changed_paths"] = ["tests/holdout/secret_case.py"]
            self.assertTrue(any("E_PROTECTED_SURFACE_CHANGED" in item for item in validate_codex_task_result(protected, schema, task=task)))

            escaped = deepcopy(_result())
            escaped["changed_paths"] = ["../controller/state.json"]
            self.assertTrue(any("E_SCOPE_VIOLATION" in item for item in validate_codex_task_result(escaped, schema, task=task)))

    def test_blocked_and_completed_results_have_typed_outcomes(self) -> None:
        schema = load_json(RESULT_SCHEMA_PATH)
        with tempfile.TemporaryDirectory() as directory:
            task = _task(Path(directory) / "worktrees" / "CAND-0007")
            blocked = deepcopy(_result())
            blocked.update({
                "status": "blocked",
                "candidate_ref": None,
                "changed_paths": [],
                "proposed_events": ["task_blocked"],
                "blocker": {"code": "E_SCOPE_VIOLATION", "summary": "Required file is outside scope.", "evidence_refs": [], "retryable": False},
                "claims": [],
            })
            self.assertEqual([], validate_codex_task_result(blocked, schema, task=task))
            blocked["blocker"] = None
            self.assertTrue(any("E_SCHEMA_INVALID" in item for item in validate_codex_task_result(blocked, schema, task=task)))

            wrong_event = deepcopy(blocked)
            wrong_event["blocker"] = {"code": "E_SCOPE_VIOLATION", "summary": "Blocked.", "evidence_refs": [], "retryable": False}
            wrong_event["proposed_events"] = ["task_failed"]
            self.assertTrue(any("E_SCHEMA_INVALID" in item for item in validate_codex_task_result(wrong_event, schema, task=task)))

            completed = _result()
            completed["candidate_ref"] = None
            self.assertTrue(any("E_SCHEMA_INVALID" in item for item in validate_codex_task_result(completed, schema, task=task)))

            leaked = _result()
            leaked["claims"][0]["claim"] = "password=RAW_SECRET_1234567890"
            self.assertTrue(any("E_SCOPE_VIOLATION@/claims" in item for item in validate_codex_task_result(leaked, schema, task=task)))

    def test_task_envelope_rejects_authority_scope_and_worktree_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "worktrees"
            task = _task(root / "CAND-0007")
            overlap = deepcopy(task)
            overlap["allowed_write_paths"].append(".closure/**")
            self.assertTrue(any("E_PROTECTED_SURFACE_CHANGED" in item for item in validate_codex_task_envelope(overlap, worktrees_root=root)))

            escaped = deepcopy(task)
            escaped["working_directory"] = str(Path(directory) / "controller")
            self.assertTrue(any("E_SCOPE_VIOLATION" in item for item in validate_codex_task_envelope(escaped, worktrees_root=root)))

            unauthorized = deepcopy(task)
            unauthorized["forbidden_actions"].remove("close")
            self.assertTrue(any("E_UNAUTHORIZED_TRANSITION" in item for item in validate_codex_task_envelope(unauthorized, worktrees_root=root)))

            incomplete = deepcopy(task)
            incomplete["required_outputs"].remove("candidate_manifest")
            incomplete["stop_conditions"].remove("scope_blocked")
            incomplete["working_directory"] = str(root / "ANOTHER-CANDIDATE" / "nested")
            incomplete["objective"] = "Use password=RAW_SECRET_1234567890"
            violations = validate_codex_task_envelope(incomplete, worktrees_root=root)
            self.assertTrue(any("E_SCHEMA_INVALID@/required_outputs" in item for item in violations))
            self.assertTrue(any("E_SCHEMA_INVALID@/stop_conditions" in item for item in violations))
            self.assertTrue(any("E_SCOPE_VIOLATION@/working_directory" in item for item in violations))
            self.assertTrue(any("E_SCOPE_VIOLATION@/objective" in item for item in violations))

            reviewer = deepcopy(task)
            reviewer.update({"task_id": "TASK-REVIEW-0007", "role": "reviewer", "sandbox_profile": "workspace-write"})
            self.assertTrue(any("E_SCOPE_VIOLATION@/sandbox_profile" in item for item in validate_codex_task_envelope(reviewer, worktrees_root=root)))

    def test_task_envelope_can_bind_every_frozen_workflow_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "worktrees"
            task = _task(root / "CAND-0007")
            state = {
                "source": {"observed_revision": task["source_revision"]},
                "policy_bundle_hash": task["policy_bundle_hash"],
                "plan_ref": {"content_hash": task["plan_ref"]["hash"]},
                "closure_run": {"contract_ref": {"content_hash": task["contract_ref"]["hash"], "epoch": task["contract_ref"]["epoch"]}},
            }
            self.assertEqual([], validate_codex_task_envelope(task, worktrees_root=root, state=state))
            state["source"]["observed_revision"] = "b" * 40
            self.assertTrue(any("E_ARTIFACT_STALE@/source_revision" in item for item in validate_codex_task_envelope(task, worktrees_root=root, state=state)))

    def test_resume_requires_identical_task_contract_source_plan_and_policy_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task = _task(Path(directory) / "worktrees" / "CAND-0007")
            session = {
                "task_id": task["task_id"],
                "session_id": "session-123",
                "source_revision": task["source_revision"],
                "contract_hash": task["contract_ref"]["hash"],
                "contract_epoch": task["contract_ref"]["epoch"],
                "plan_hash": task["plan_ref"]["hash"],
                "policy_bundle_hash": task["policy_bundle_hash"],
            }
            self.assertEqual([], validate_codex_resume(session, task))
            for path, replacement in (
                (("source_revision",), "b" * 40),
                (("contract_ref", "hash"), "sha256:" + "4" * 64),
                (("contract_ref", "epoch"), 2),
                (("plan_ref", "hash"), "sha256:" + "5" * 64),
                (("policy_bundle_hash",), "sha256:" + "6" * 64),
            ):
                changed = deepcopy(task)
                target = changed
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = replacement
                self.assertTrue(any("E_ARTIFACT_STALE" in item for item in validate_codex_resume(session, changed)), path)

    def test_capability_probe_is_explicit_and_never_invokes_a_model(self) -> None:
        calls: list[list[str]] = []

        class Result:
            returncode = 0
            stderr = ""

        def runner(command: list[str], **_: object) -> Result:
            calls.append(command)
            result = Result()
            result.stdout = "--ask-for-approval" if command == ["codex", "--help"] else "--json --output-schema --output-last-message --sandbox -C resume"
            return result

        qualified = probe_codex_capabilities("codex", runner=runner)
        self.assertTrue(qualified["qualified"])
        self.assertEqual([["codex", "--help"], ["codex", "exec", "--help"]], calls)

        def missing_runner(command: list[str], **_: object) -> Result:
            result = Result()
            result.stdout = "--ask-for-approval" if command == ["codex", "--help"] else "--json --sandbox -C"
            return result

        unqualified = probe_codex_capabilities("codex", runner=missing_runner)
        self.assertFalse(unqualified["qualified"])
        self.assertIn("--output-schema", unqualified["missing"])

    def test_adapter_docs_and_agent_metadata_exist_without_enabling_live_execution(self) -> None:
        adapter = (ROOT / "adapters" / "codex-exec.md").read_text(encoding="utf-8")
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn("capability probe", adapter.lower())
        self.assertIn("advance_closure.py", adapter)
        self.assertIn("remote writes", adapter.lower())
        self.assertNotIn("danger-full-access", adapter)
        self.assertIn("allow_implicit_invocation", metadata)


if __name__ == "__main__":
    unittest.main()
