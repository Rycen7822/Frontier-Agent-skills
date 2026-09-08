"""One producer-to-grader check for complete and abandoned Host observations."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill-evaluator/scripts"))
sys.path.insert(0, str(ROOT / "scripts"))
import model_grade_transport as transport
from _codex_eval_artifacts import build_command_trace, build_host_observation


def lifecycle_value(*, item_ids: list[str]) -> dict:
    return {
        "contract_version": "codex-child-lifecycle/2",
        "branch": "outcome_bearing_abandoned",
        "incomplete_items": [
            {
                "id": item_id,
                "type": "command_execution",
                "command": "printf hidden",
                "status": "in_progress",
            }
            for item_id in item_ids
        ],
        "turn_completed": True,
        "final_message_present": True,
        "usage_present": True,
        "custody_closed": True,
        "retryable": False,
        "reserve_consumption": False,
        "sample_valid": True,
        "process_gate": {
            "status": "fail",
            "reason": "command completion, exit code, and output remain unknown",
        },
        "unknown_completion": item_ids,
    }


class ModelGradeTransportContractTests(unittest.TestCase):
    def test_host_observations_preserve_unknown_command_completion(self):
        for abandoned in (False, True):
            with self.subTest(abandoned=abandoned):
                trace = build_command_trace(
                    [{"items": []}],
                    ["turn-1"],
                    workspace=ROOT,
                    workspace_alias="/workspace",
                    scratch_root="/tmp",
                    protected_scratch_roots=("/workspace", "/output"),
                    normalize_text=lambda value: value,
                    abandoned_items=[
                        {
                            "id": "gap",
                            "type": "command_execution",
                            "command": "printf hidden",
                        }
                    ]
                    if abandoned
                    else None,
                )
                observation = build_host_observation(
                    terminal_status="completed",
                    codex_status="completed",
                    turn_ids=["turn-1"],
                    changed_paths=[],
                    command_trace=trace,
                    workspace_evidence={"complete": True, "overflow": False},
                    lifecycle=lifecycle_value(item_ids=["gap"]) if abandoned else None,
                )
                encode = lambda value: json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
                assessment = transport._host_observation(encode(observation))
                consumed = transport._command_trace(encode(trace), assessment)
                self.assertEqual(consumed["complete"], not abandoned)
                if abandoned:
                    self.assertIsNone(consumed["items"][0]["exit_code"])
                    trace["complete"] = True
                    with self.assertRaises(ValueError):
                        transport._command_trace(encode(trace), assessment)


if __name__ == "__main__":
    unittest.main()
