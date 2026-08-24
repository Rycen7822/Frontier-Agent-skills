import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _codex_eval_artifacts import build_command_trace  # noqa: E402
from _codex_eval_events import normalize_jsonl  # noqa: E402
from _codex_lifecycle_contract import (  # noqa: E402
    LEGACY_CONTRACT,
    V2_CONTRACT,
    LifecycleContractError,
    classify_lifecycle,
)


def _raw(*, incomplete=None, terminal=True, final=True, usage=True, extra_type=None):
    incomplete = list(incomplete or [])
    records = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "item.started", "item": {"id": "command-1", "type": "command_execution", "command": "printf ok", "status": "in_progress"}},
        {"type": "item.completed", "item": {"id": "command-1", "type": "command_execution", "command": "printf ok", "aggregated_output": "ok", "exit_code": 0, "status": "completed"}},
    ]
    for item_id in incomplete:
        item_type = extra_type or "command_execution"
        records.append({"type": "item.started", "item": {"id": item_id, "type": item_type, "command": "find / -name marker", "status": "in_progress"}})
    if final:
        records.append({"type": "item.completed", "item": {"id": "agent-final", "type": "agent_message", "text": "final answer"}})
    if terminal:
        record = {"type": "turn.completed"}
        if usage:
            record["usage"] = {"input_tokens": 10, "output_tokens": 2}
        records.append(record)
    return b"\n".join(json.dumps(record, sort_keys=True).encode() for record in records) + b"\n"


_CUSTODY = {
    "process_exited": True,
    "timed_out": False,
    "live_process": False,
    "workspace_clean": True,
    "isolation_clean": True,
    "effects_captured": True,
}


class LifecycleContractTests(unittest.TestCase):
    def test_legacy_dispatch_does_not_change_projection(self):
        result = classify_lifecycle(_raw(incomplete=["gap"]), contract_version=LEGACY_CONTRACT)
        self.assertEqual(result["branch"], "legacy")

    def test_normal_complete_lifecycle(self):
        result = classify_lifecycle(_raw(), contract_version=V2_CONTRACT, custody=_CUSTODY)
        self.assertEqual(result["branch"], "complete")
        self.assertTrue(result["sample_valid"])
        self.assertEqual(result["process_gate"]["status"], "pass")

    def test_outcome_free_incomplete_is_retryable_only_with_clean_custody(self):
        result = classify_lifecycle(
            _raw(incomplete=["gap"], terminal=False, final=False, usage=False),
            contract_version=V2_CONTRACT,
            custody=_CUSTODY,
        )
        self.assertEqual(result["branch"], "outcome_free_transient")
        self.assertTrue(result["retryable"])
        self.assertTrue(result["reserve_consumption"])
        self.assertFalse(result["sample_valid"])

    def test_completed_turn_usage_final_with_one_or_many_abandoned_commands(self):
        for gaps in (["gap-1"], ["gap-1", "gap-2", "gap-3"]):
            result = classify_lifecycle(
                _raw(incomplete=gaps),
                contract_version=V2_CONTRACT,
                custody=_CUSTODY,
            )
            self.assertEqual(result["branch"], "outcome_bearing_abandoned")
            self.assertTrue(result["sample_valid"])
            self.assertFalse(result["retryable"])
            self.assertFalse(result["reserve_consumption"])
            self.assertEqual(result["unknown_completion"], gaps)
            self.assertEqual(result["process_gate"]["status"], "fail")

    def test_independent_completion_evidence_reconciles_exact_ids(self):
        raw = _raw(incomplete=["gap-1", "gap-2"])
        evidence = {
            item_id: {
                "item_id": item_id,
                "exit_code": 0,
                "output_digest": "sha256:" + "a" * 64,
            }
            for item_id in ("gap-1", "gap-2")
        }
        result = classify_lifecycle(
            raw,
            contract_version=V2_CONTRACT,
            custody=_CUSTODY,
            completion_evidence=evidence,
        )
        self.assertEqual(result["branch"], "reconciled_complete")
        self.assertTrue(result["sample_valid"])
        with self.assertRaises(LifecycleContractError):
            classify_lifecycle(
                raw,
                contract_version=V2_CONTRACT,
                custody=_CUSTODY,
                completion_evidence={"gap-1": evidence["gap-1"]},
            )

    def test_missing_usage_or_final_message_is_not_retryable(self):
        for raw in (
            _raw(incomplete=["gap"], final=False),
            _raw(incomplete=["gap"], usage=False),
            _raw(incomplete=["gap"], terminal=False),
        ):
            result = classify_lifecycle(raw, contract_version=V2_CONTRACT, custody=_CUSTODY)
            self.assertEqual(result["branch"], "unknown_mixed_or_uncustodied")
            self.assertFalse(result["retryable"])

    def test_noncommand_incomplete_is_fail_closed(self):
        result = classify_lifecycle(
            _raw(incomplete=["tool-gap"], extra_type="mcp_tool_call"),
            contract_version=V2_CONTRACT,
            custody=_CUSTODY,
        )
        self.assertEqual(result["branch"], "unknown_mixed_or_uncustodied")

    def test_dirty_workspace_or_live_process_is_fail_closed(self):
        dirty = dict(_CUSTODY, workspace_clean=False)
        live = dict(_CUSTODY, live_process=True)
        for custody in (dirty, live):
            result = classify_lifecycle(
                _raw(incomplete=["gap"]),
                contract_version=V2_CONTRACT,
                custody=custody,
            )
            self.assertEqual(result["branch"], "outcome_bearing_abandoned_pending_custody")

    def test_command_trace_retains_unknown_completion_without_fabricating_exit(self):
        normalized = normalize_jsonl(_raw(incomplete=["gap"]))
        trace = build_command_trace(
            [normalized], ["turn-1"], workspace=ROOT, workspace_alias="/workspace",
            scratch_root="/tmp", protected_scratch_roots=("/workspace", "/output"),
            normalize_text=lambda value: value,
            abandoned_items=[{"id": "gap", "type": "command_execution", "command": "find / -name marker"}],
        )
        item = next(item for item in trace["items"] if item.get("item_id") == "gap")
        self.assertFalse(trace["complete"])
        self.assertEqual(item["completion"], "unknown")
        self.assertIsNone(item["exit_code"])
        self.assertIsNone(item["output_sha256"])


if __name__ == "__main__":
    unittest.main()
