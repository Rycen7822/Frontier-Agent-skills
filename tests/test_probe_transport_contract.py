import json
import io
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import codex_eval_host as host  # noqa: E402
from _codex_eval_events import normalize_jsonl  # noqa: E402
from _model_evolution_ops import (  # noqa: E402
    _load_probe_terminal,
    _probe_is_official_transient,
    _validate_probe_result,
)


ROW = {
    "probe_id": "force-load",
    "capability": "force_load",
    "required_event_types": ["thread.started", "turn.completed"],
}
REQUEST = {"request_id": "probe.example.1.01"}


def event(record_type: str, **fields: object) -> bytes:
    return json.dumps(
        {"type": record_type, **fields},
        separators=(",", ":"),
    ).encode()


def raw_timeout(*, with_outcome: bool = False, malformed: bool = False) -> bytes:
    if malformed:
        return b"{not-json}\n"
    records = [
        event("thread.started", thread_id="thread-1"),
        event("turn.started", turn_id="turn-1"),
        event(
            "item.started",
            item={
                "id": "reasoning-1",
                "type": "reasoning",
                "status": "in_progress",
            },
        ),
    ]
    if with_outcome:
        records.extend(
            [
                event(
                    "item.completed",
                    item={
                        "id": "agent-1",
                        "type": "agent_message",
                        "text": "answer",
                    },
                ),
                event(
                    "turn.completed",
                    turn_id="turn-1",
                    usage={"input_tokens": 2, "output_tokens": 1},
                ),
            ]
        )
    return b"\n".join(records) + b"\n"


def raw_effect_timeout() -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event(
                "item.started",
                item={
                    "id": "command-1",
                    "type": "command_execution",
                    "command": "printf hidden",
                    "status": "in_progress",
                },
            ),
        ]
    ) + b"\n"


def raw_reasoning_vector() -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event(
                "item.completed",
                item={"id": "reasoning-1", "type": "reasoning", "status": "completed"},
            ),
            event("error", error={"kind": "diagnostic"}),
        ]
    ) + b"\n"


def raw_completed_item(item_type: str) -> bytes:
    item = {"id": f"item-{item_type}", "type": item_type, "status": "completed"}
    if item_type == "agent_message":
        item["text"] = "answer"
    elif item_type == "command_execution":
        item["command"] = "true"
    elif item_type == "mcp_tool_call":
        item.update({"server": "server", "tool": "tool"})
    elif item_type == "collab_tool_call":
        item.update({"server": "server", "tool": "tool"})
    elif item_type == "web_search":
        item["query"] = "query"
    elif item_type == "error":
        item["error"] = {"kind": "diagnostic"}
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event("item.completed", item=item),
        ]
    ) + b"\n"


def raw_reasoning_with_output() -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event(
                "item.completed",
                item={
                    "id": "reasoning-1",
                    "type": "reasoning",
                    "status": "completed",
                    "aggregated_output": "hidden",
                },
            ),
        ]
    ) + b"\n"


def raw_complete() -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event("turn.completed", turn_id="turn-1"),
        ]
    ) + b"\n"


def child(raw: bytes, *, timed_out: bool = True, reaped: bool = True) -> dict:
    return {
        "stdout": raw,
        "stderr": b"diagnostic timeout text",
        "returncode": -9 if timed_out else 0,
        "timed_out": timed_out,
        "kill_sent": timed_out,
        "reaped": reaped,
        "runtime_ms": 1,
    }


class _BinaryStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, value: str) -> int:
        return len(value)

    def flush(self) -> None:
        return None


@contextmanager
def captured_probe_output(
    input_row: dict,
    child_raw: bytes,
    *,
    timed_out: bool = False,
    isolated: bool = False,
):
    stdin = io.TextIOWrapper(
        io.BytesIO(json.dumps(input_row, separators=(",", ":")).encode() + b"\n"),
        encoding="utf-8",
    )
    stdout = _BinaryStdout()
    args = mock.Mock(
        plugin_root=Path("."),
        isolation_tool=Path("/usr/bin/bwrap") if isolated else None,
        source_root=None,
        timeout=1.0,
        model="gpt-5.6-sol",
        effort="xhigh",
        profile="default",
        sandbox="read-only",
        codex=Path("/usr/bin/codex"),
    )
    fake_child = child(child_raw, timed_out=timed_out, reaped=True)
    fake_child["stderr"] = b""
    with (
        mock.patch.object(host.sys, "stdin", stdin),
        mock.patch.object(host.sys, "stdout", stdout),
        mock.patch.object(host, "prepare_workspace"),
        mock.patch.object(host, "forced_probe_delivery", return_value=("skill", "prompt")),
        mock.patch.object(host, "observed_skill_routing", return_value=[]),
        mock.patch.object(
            host,
            "_run_child",
            return_value=fake_child,
        ),
    ):
        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace = Path(workspace_dir)
            yield args, workspace, stdout
    stdin.detach()


def emitted_probe_result(raw: bytes, *, timed_out: bool = False, isolated: bool = False) -> dict:
    row = {
        "schema_version": "codex-interaction-probe/1.0",
        "probe_id": ROW["probe_id"],
        "capability": ROW["capability"],
        "prompt": "probe",
        "expected_event_types": ROW["required_event_types"],
    }
    with captured_probe_output(row, raw, timed_out=timed_out, isolated=isolated) as (args, workspace, stdout):
        result_code = host._run_probe_mode(args, workspace)
        assert result_code == 0
        return json.loads(stdout.buffer.getvalue().decode())


def project(
    raw: bytes,
    *,
    timed_out: bool = True,
    reaped: bool = True,
    dirty: bool = False,
    kill_sent: bool | None = None,
):
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)
        before = {"fixture.json": "sha256:" + "a" * 64}
        after = before if not dirty else {"fixture.json": "sha256:" + "b" * 64}
        last_message = workspace / "last-message.txt"
        if raw and b'"type":"turn.completed"' in raw and b'"text":"answer"' in raw:
            last_message.write_text("answer", encoding="utf-8")
        normalized = normalize_jsonl(raw)
        return host._probe_lifecycle_projection(
            {
                **child(raw, timed_out=timed_out, reaped=reaped),
                **({"kill_sent": kill_sent} if kill_sent is not None else {}),
            },
            normalized,
            workspace=workspace,
            workspace_before=before,
            workspace_after=after,
            workspace_before_ok=True,
            workspace_after_ok=True,
            last_message=last_message,
            source_root=None,
            isolated=True,
        )


class ProbeTransportContractTests(unittest.TestCase):
    def test_reasoning_only_d35_event_vector_uses_real_emitter_and_terminal_loader(self):
        result = emitted_probe_result(raw_reasoning_vector(), timed_out=True, isolated=True)
        _validate_probe_result(result, ROW)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["lifecycle"]["completed_item_types"], ["reasoning"])
        self.assertEqual(result["lifecycle"]["non_effect_progress_item_types"], ["reasoning"])
        self.assertTrue(result["lifecycle"]["retryable"])
        attempts = [
            {
                "attempt": index,
                "attempt_id": REQUEST["request_id"] + f".attempt-{index}",
                "status": result["status"],
                "diagnostics": result["diagnostics"],
                "stderr": "",
                "lifecycle": result["lifecycle"],
            }
            for index in (1, 2)
        ]
        terminal = {
            "schema_version": "model-evolution-probe-terminal/5",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 2,
            "attempts": attempts,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/5")

    def test_all_normalized_item_types_are_classified_without_content(self):
        for item_type in (
            "agent_message",
            "reasoning",
            "command_execution",
            "file_change",
            "mcp_tool_call",
            "collab_tool_call",
            "web_search",
            "todo_list",
            "error",
        ):
            lifecycle, status, _ = project(raw_completed_item(item_type))
            self.assertEqual(status, "unknown", item_type)
            self.assertNotIn("command", lifecycle, item_type)
            self.assertNotIn("output", lifecycle, item_type)
            self.assertNotIn("command_action_effect", lifecycle, item_type)
            if item_type in {"reasoning", "todo_list", "error"}:
                self.assertFalse(lifecycle["effect_capable"], item_type)
            elif item_type == "agent_message":
                self.assertTrue(lifecycle["outcome_evidence"], item_type)
            else:
                self.assertTrue(lifecycle["effect_capable"], item_type)

    def test_real_host_emitter_output_is_validator_and_terminal_input(self):
        result = emitted_probe_result(raw_complete())
        self.assertEqual(
            result["event_types"],
            ["thread.started", "turn.completed", "turn.started"],
        )
        _validate_probe_result(result, ROW)
        terminal = {
            "schema_version": "model-evolution-probe-terminal/5",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 1,
            "attempts": [{
                "attempt": 1,
                "attempt_id": REQUEST["request_id"] + ".attempt-1",
                "status": result["status"],
                "diagnostics": result["diagnostics"],
                "stderr": "",
                "lifecycle": result["lifecycle"],
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["result"], result)

    def test_transient_then_pass_terminal_is_valid(self):
        transient_lifecycle, transient_status, transient_diagnostics = project(raw_timeout())
        complete_lifecycle, complete_status, complete_diagnostics = project(
            raw_complete(), timed_out=False
        )
        self.assertEqual(complete_status, "pass")
        transient = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": transient_status,
            "observed": "required direct Codex events were not established",
            "session_id": "thread-1",
            "event_types": transient_lifecycle["event_types"],
            "direct_observations": [],
            "routing": [],
            "usage": None,
            "diagnostics": transient_diagnostics,
            "lifecycle": transient_lifecycle,
        }
        complete = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": complete_status,
            "observed": "required direct Codex events observed",
            "session_id": "thread-1",
            "event_types": complete_lifecycle["event_types"],
            "direct_observations": ["direct.usage"],
            "routing": [],
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "diagnostics": complete_diagnostics,
            "lifecycle": complete_lifecycle,
        }
        terminal = {
            "schema_version": "model-evolution-probe-terminal/5",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": complete,
            "stderr": "",
            "attempt_count": 2,
            "attempts": [
                {
                    "attempt": 1,
                    "attempt_id": REQUEST["request_id"] + ".attempt-1",
                    "status": transient_status,
                    "diagnostics": transient_diagnostics,
                    "stderr": "",
                    "lifecycle": transient_lifecycle,
                },
                {
                    "attempt": 2,
                    "attempt_id": REQUEST["request_id"] + ".attempt-2",
                    "status": complete_status,
                    "diagnostics": complete_diagnostics,
                    "stderr": "",
                    "lifecycle": complete_lifecycle,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["attempt_count"], 2)

    def test_two_transient_attempts_exhaust_without_success(self):
        lifecycle, status, diagnostics = project(raw_timeout())
        result = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": status,
            "observed": "required direct Codex events were not established",
            "session_id": "thread-1",
            "event_types": lifecycle["event_types"],
            "direct_observations": [],
            "routing": [],
            "usage": None,
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }
        terminal = {
            "schema_version": "model-evolution-probe-terminal/5",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 2,
            "attempts": [
                {
                    "attempt": index,
                    "attempt_id": REQUEST["request_id"] + f".attempt-{index}",
                    "status": status,
                    "diagnostics": diagnostics,
                    "stderr": "",
                    "lifecycle": lifecycle,
                }
                for index in (1, 2)
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["attempt_count"], 2)
        self.assertEqual(loaded["result"]["status"], "unknown")

    def test_outcome_free_timeout_is_retryable_only_after_closed_custody(self):
        lifecycle, status, diagnostics = project(raw_timeout())
        self.assertEqual(status, "unknown")
        self.assertEqual(lifecycle["branch"], "outcome_free_transient")
        self.assertTrue(lifecycle["custody_closed"])
        self.assertTrue(lifecycle["retryable"])
        value = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": status,
            "observed": "required direct Codex events were not established",
            "session_id": "thread-1",
            "event_types": lifecycle["event_types"],
            "direct_observations": [],
            "routing": [],
            "usage": None,
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }
        _validate_probe_result(value, ROW)
        self.assertTrue(_probe_is_official_transient(value))

    def test_two_transient_attempts_are_not_hidden_as_success(self):
        lifecycle, status, diagnostics = project(raw_timeout())
        self.assertTrue(_probe_is_official_transient({
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "status": status,
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }))
        self.assertEqual(lifecycle["branch"], "outcome_free_transient")

    def test_outcome_bearing_timeout_is_unknown_and_not_retryable(self):
        lifecycle, status, _ = project(raw_timeout(with_outcome=True))
        self.assertEqual(status, "unknown")
        self.assertEqual(lifecycle["reason"], "outcome_evidence")
        self.assertFalse(lifecycle["retryable"])
        self.assertTrue(lifecycle["completed_turn"])
        self.assertTrue(lifecycle["usage_present"])

    def test_effect_capable_item_is_not_probe_retryable(self):
        lifecycle, status, _ = project(raw_effect_timeout())
        self.assertEqual(status, "unknown")
        self.assertFalse(lifecycle["retryable"])
        self.assertEqual(lifecycle["effect_capable_item_types"], ["command_execution"])
        self.assertEqual(lifecycle["reason"], "effect_capable")

    def test_non_effect_type_with_output_is_effect_capable(self):
        lifecycle, status, _ = project(raw_reasoning_with_output())
        self.assertEqual(status, "unknown")
        self.assertTrue(lifecycle["effect_capable"])
        self.assertEqual(lifecycle["effect_capable_item_types"], ["reasoning"])
        self.assertNotIn("aggregated_output", lifecycle)

    def test_malformed_dirty_and_unreaped_custody_fail_closed(self):
        for raw, kwargs in (
            (raw_timeout(malformed=True), {}),
            (raw_timeout(), {"dirty": True}),
            (raw_timeout(), {"reaped": False}),
        ):
            lifecycle, status, _ = project(raw, **kwargs)
            self.assertEqual(status, "unknown")
            self.assertFalse(lifecycle["retryable"])
            self.assertFalse(lifecycle["custody_closed"])

    def test_timeout_without_kill_proof_is_not_retryable(self):
        lifecycle, status, _ = project(
            raw_timeout(), timed_out=True, reaped=True, kill_sent=False
        )
        self.assertEqual(status, "unknown")
        self.assertFalse(lifecycle["retryable"])
        self.assertFalse(lifecycle["custody_closed"])

    def test_version_and_terminal_shape_fail_closed(self):
        lifecycle, status, diagnostics = project(raw_timeout(with_outcome=True), timed_out=False)
        result = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": status,
            "observed": "not established",
            "session_id": "thread-1",
            "event_types": sorted(set(lifecycle["event_types"])),
            "direct_observations": ["direct.usage"],
            "routing": [],
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }
        with self.assertRaises(ValueError):
            _validate_probe_result({**result, "schema_version": "codex-probe-result/unknown"}, ROW)
        with self.assertRaises(ValueError):
            _validate_probe_result({**result, "lifecycle": {**lifecycle, "extra": True}}, ROW)

    def test_external_unordered_or_duplicate_event_types_fail_closed(self):
        lifecycle, status, diagnostics = project(raw_timeout(with_outcome=True), timed_out=False)
        result = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": status,
            "observed": "required direct Codex events observed",
            "session_id": "thread-1",
            "event_types": ["turn.completed", "thread.started", "thread.started"],
            "direct_observations": ["direct.usage"],
            "routing": [],
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }
        with self.assertRaises(ValueError):
            _validate_probe_result(result, ROW)

    def test_historical_terminal_v3_replay_remains_exact_and_not_reclassified(self):
        result = {
            "schema_version": "codex-interaction-probe-result/1.1",
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": "unknown",
            "observed": "required direct Codex events were not established",
            "session_id": None,
            "event_types": [],
            "direct_observations": [],
            "routing": [],
            "usage": None,
            "diagnostics": [{
                "kind": "child_process",
                "index": None,
                "message": "Codex child timed out",
            }],
        }
        terminal = {
            "schema_version": "model-evolution-probe-terminal/3",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "diagnostic",
            "attempts": [{
                "attempt": 1,
                "status": "unknown",
                "diagnostics": result["diagnostics"],
                "stderr": "diagnostic",
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/3")
        self.assertFalse(_probe_is_official_transient(result))

    def test_versioned_terminal_binds_attempt_identity_and_lifecycle(self):
        lifecycle, status, diagnostics = project(raw_timeout(with_outcome=True), timed_out=False)
        self.assertEqual(status, "unknown")
        result = {
            "schema_version": host.PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": status,
            "observed": "required direct Codex events were not established",
            "session_id": "thread-1",
            "event_types": lifecycle["event_types"],
            "direct_observations": ["direct.usage"],
            "routing": [],
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }
        terminal = {
            "schema_version": "model-evolution-probe-terminal/5",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "diagnostic",
            "attempt_count": 1,
            "attempts": [{
                "attempt": 1,
                "attempt_id": REQUEST["request_id"] + ".attempt-1",
                "status": status,
                "diagnostics": diagnostics,
                "stderr": "diagnostic",
                "lifecycle": lifecycle,
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["attempt_count"], 1)

    def test_historical_terminal_v4_replay_remains_exact(self):
        lifecycle = {
            "schema_version": "codex-probe-lifecycle/1",
            "child_timed_out": True,
            "child_kill_sent": True,
            "child_reaped": True,
            "process_exited": True,
            "isolation_custody": True,
            "jsonl_bounded": True,
            "jsonl_classified": True,
            "event_count": 3,
            "event_types": ["thread.started", "turn.started"],
            "incomplete_item_types": [],
            "completed_turn": False,
            "final_message_present": False,
            "usage_present": False,
            "command_action_effect": False,
            "workspace_pre_digest": "sha256:" + "a" * 64,
            "workspace_post_digest": "sha256:" + "a" * 64,
            "workspace_clean": True,
            "source_path_exposed": False,
            "credential_marker_seen": False,
            "custody_closed": True,
            "retryable": False,
            "branch": "unknown",
            "reason": "unknown_lifecycle",
        }
        result = {
            "schema_version": "codex-interaction-probe-result/1.2",
            "probe_id": ROW["probe_id"],
            "capability": ROW["capability"],
            "status": "unknown",
            "observed": "not established",
            "session_id": "thread-1",
            "event_types": ["thread.started", "turn.started"],
            "direct_observations": [],
            "routing": [],
            "usage": None,
            "diagnostics": [],
            "lifecycle": lifecycle,
        }
        terminal = {
            "schema_version": "model-evolution-probe-terminal/4",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 1,
            "attempts": [{
                "attempt": 1,
                "attempt_id": REQUEST["request_id"] + ".attempt-1",
                "status": "unknown",
                "diagnostics": [],
                "stderr": "",
                "lifecycle": lifecycle,
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/4")


if __name__ == "__main__":
    unittest.main()
