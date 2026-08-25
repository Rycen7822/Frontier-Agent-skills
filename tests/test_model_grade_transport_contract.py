import json
import sys
import unittest
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill-evaluator" / "scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

import model_grade_transport as transport  # noqa: E402
from _codex_eval_artifacts import build_command_trace, build_host_observation  # noqa: E402


def canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def host_value(*, version: str, lifecycle: dict | None = None) -> dict:
    value = {
        "schema_version": version,
        "terminal_status": "completed",
        "codex_status": "completed",
        "turn_ids": ["turn-1"],
        "changed_paths": [],
        "command_trace_complete": lifecycle is None,
        "command_trace_overflow": False,
        "workspace_evidence_complete": True,
        "workspace_evidence_overflow": False,
    }
    if lifecycle is not None:
        value["lifecycle"] = lifecycle
    return value


def lifecycle_value(*, item_ids: list[str]) -> dict:
    return {
        "contract_version": "codex-child-lifecycle/2",
        "branch": "outcome_bearing_abandoned",
        "incomplete_items": [
            {"id": item_id, "type": "command_execution", "command": "printf hidden", "status": "in_progress"}
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
    def test_producers_version_only_lifecycle_extensions(self) -> None:
        command_trace = build_command_trace([{"items": []}], ["turn-1"], workspace=ROOT, workspace_alias="/workspace", scratch_root="/tmp", protected_scratch_roots=("/workspace", "/output"), normalize_text=lambda value: value)
        abandoned_trace = build_command_trace([{"items": []}], ["turn-1"], workspace=ROOT, workspace_alias="/workspace", scratch_root="/tmp", protected_scratch_roots=("/workspace", "/output"), normalize_text=lambda value: value, abandoned_items=[{"id": "gap", "type": "command_execution", "command": "printf hidden"}])
        workspace = {"complete": True, "overflow": False}
        self.assertEqual(command_trace["schema_version"], "codex-command-trace/1")
        self.assertEqual(abandoned_trace["schema_version"], "codex-command-trace/2")
        self.assertEqual(build_host_observation(terminal_status="completed", codex_status="completed", turn_ids=["turn-1"], changed_paths=[], command_trace=command_trace, workspace_evidence=workspace)["schema_version"], "codex-host-observation/1")
        self.assertEqual(build_host_observation(terminal_status="completed", codex_status="completed", turn_ids=["turn-1"], changed_paths=[], command_trace=abandoned_trace, workspace_evidence=workspace, lifecycle=lifecycle_value(item_ids=["gap"]))["schema_version"], "codex-host-observation/2")

    def test_host_v1_v2_and_exact_legacy_compatibility(self) -> None:
        legacy = host_value(version="codex-host-observation/1")
        self.assertEqual(transport._host_observation(canonical(legacy))["schema_version"], "codex-host-observation/1")
        lifecycle = lifecycle_value(item_ids=["gap-1", "gap-2"])
        v2 = host_value(version="codex-host-observation/2", lifecycle=lifecycle)
        parsed = transport._host_observation(canonical(v2))
        self.assertEqual(parsed["_lifecycle"]["unknown_completion"], ["gap-1", "gap-2"])
        compat = host_value(version="codex-host-observation/1", lifecycle=lifecycle)
        self.assertTrue(transport._host_observation(canonical(compat))["_lifecycle_compatibility_alias"])
        for invalid in (
            host_value(version="codex-host-observation/3", lifecycle=lifecycle),
            host_value(version="codex-host-observation/2", lifecycle=lifecycle) | {"unexpected": True},
            host_value(version="codex-host-observation/1", lifecycle=lifecycle) | {"unexpected": True},
        ):
            with self.assertRaises(ValueError):
                transport._host_observation(canonical(invalid))

    def test_command_trace_abandoned_shape_is_versioned_and_blind(self) -> None:
        lifecycle = lifecycle_value(item_ids=["gap"])
        assessment = transport._host_observation(canonical(host_value(version="codex-host-observation/2", lifecycle=lifecycle)))
        abandoned = {
            "schema_version": "codex-command-trace/2",
            "complete": False,
            "overflow": False,
            "items": [{
                "ordinal": 1,
                "turn_id": "turn-1",
                "type": "command_execution",
                "item_id": "gap",
                "status": "abandoned",
                "completion": "unknown",
                "exit_code": None,
                "output_sha256": None,
                "output_bytes": None,
                "command_sha256": "sha256:" + sha256(b"printf hidden").hexdigest(),
                "command_preview": "printf hidden",
            }],
        }
        self.assertEqual(transport._command_trace(canonical(abandoned), assessment)["items"][0]["completion"], "unknown")
        for invalid in (
            abandoned | {"schema_version": "codex-command-trace/1"},
            abandoned | {"schema_version": "codex-command-trace/2", "items": []},
            abandoned | {"schema_version": "codex-command-trace/9"},
        ):
            with self.assertRaises(ValueError):
                transport._command_trace(canonical(invalid), assessment)


if __name__ == "__main__":
    unittest.main()
