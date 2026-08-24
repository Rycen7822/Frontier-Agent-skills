import json
from pathlib import Path
import tempfile
import unittest

from scripts._codex_transport_diagnostic import capture_child, summarize_jsonl


def event(record_type: str, **fields: object) -> bytes:
    return json.dumps({"type": record_type, **fields}, separators=(",", ":")).encode()


def complete_stream() -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event(
                "item.started",
                item={"id": "item-1", "type": "command_execution"},
            ),
            event(
                "item.completed",
                item={"id": "item-1", "type": "command_execution"},
            ),
            event(
                "item.completed",
                item={"id": "item-2", "type": "agent_message"},
            ),
            event("turn.completed", turn_id="turn-1", usage={"input_tokens": 1}),
        ]
    ) + b"\n"


class CodexTransportDiagnosticTests(unittest.TestCase):
    def test_complete_stream_records_pairs_terminal_and_usage(self) -> None:
        view = summarize_jsonl(complete_stream())
        self.assertEqual(view["parse_errors"], [])
        self.assertEqual(view["incomplete_items"], [])
        self.assertEqual(view["turn_terminals"], ["turn.completed"])
        self.assertTrue(view["final_message_event_present"])
        self.assertTrue(view["usage_present"])

    def test_single_incomplete_command_is_explicit(self) -> None:
        raw = b"\n".join(
            [
                event("thread.started", thread_id="thread-1"),
                event("turn.started", turn_id="turn-1"),
                event(
                    "item.started",
                    item={"id": "item-1", "type": "command_execution"},
                ),
            ]
        )
        view = summarize_jsonl(raw)
        self.assertEqual(view["incomplete_items"], [{"id": "item-1", "type": "command_execution"}])
        self.assertEqual(view["turn_terminals"], [])

    def test_multiple_incomplete_commands_remain_same_type_facts(self) -> None:
        raw = b"\n".join(
            [
                event("item.started", item={"id": "item-1", "type": "command_execution"}),
                event("item.started", item={"id": "item-2", "type": "command_execution"}),
            ]
        )
        view = summarize_jsonl(raw)
        self.assertEqual(
            view["incomplete_items"],
            [
                {"id": "item-1", "type": "command_execution"},
                {"id": "item-2", "type": "command_execution"},
            ],
        )

    def test_non_command_incomplete_is_not_relabelled(self) -> None:
        raw = event("item.started", item={"id": "item-1", "type": "mcp_tool_call"})
        view = summarize_jsonl(raw)
        self.assertEqual(view["incomplete_items"][0]["type"], "mcp_tool_call")

    def test_size_and_malformed_jsonl_are_fail_closed(self) -> None:
        self.assertIn("stream_size", summarize_jsonl(b"x" * (4 * 1024 * 1024 + 1))["parse_errors"])
        self.assertEqual(summarize_jsonl(b"{not-json}\n")["parse_errors"], [1])

    def test_nonzero_signal_and_timeout_are_captured_without_reclassification(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            source = root / "source"
            capture = root / "capture"
            workspace.mkdir()
            source.mkdir()
            target = capture_child(
                capture,
                "signal",
                {"stdout": b"", "stderr": b"", "returncode": -9, "timed_out": True, "runtime_ms": 12.5},
                workspace=workspace,
                source_root=source,
                last_message=None,
            )
            view = json.loads((target / "audit.json").read_text())
            self.assertEqual(view["process"]["returncode"], -9)
            self.assertTrue(view["process"]["timed_out"])
            self.assertEqual(view["process"]["signal"], 9)

    def test_raw_capture_is_byte_exact_but_audit_view_redacts_paths_and_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            source = root / "source"
            capture = root / "capture"
            workspace.mkdir()
            source.mkdir()
            raw = event("item.started", item={"id": "item-1", "type": "command_execution"})
            raw += b"\n" + str(source).encode() + b" sk-secretvalue123456\n"
            target = capture_child(
                capture,
                "redaction",
                {"stdout": raw, "stderr": b"", "returncode": 0, "timed_out": False, "runtime_ms": 1.0},
                workspace=workspace,
                source_root=source,
                last_message=None,
                reset_clean=False,
            )
            self.assertEqual((target / "child-stdout.raw").read_bytes(), raw)
            audit = (target / "audit.json").read_text()
            view = json.loads(audit)
            self.assertNotIn(str(source), audit)
            self.assertNotIn("sk-secretvalue123456", audit)
            self.assertTrue(view["redaction"]["source_path_seen"])
            self.assertTrue(view["redaction"]["credential_marker_seen"])
            self.assertEqual(view["reset_custody"], "dirty")

    def test_capture_target_is_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "workspace"
            source = root / "source"
            capture = root / "capture"
            workspace.mkdir()
            source.mkdir()
            child = {"stdout": b"", "stderr": b"", "returncode": 0, "timed_out": False, "runtime_ms": 0}
            capture_child(capture, "same", child, workspace=workspace, source_root=source, last_message=None)
            with self.assertRaises(ValueError):
                capture_child(capture, "same", child, workspace=workspace, source_root=source, last_message=None)


if __name__ == "__main__":
    unittest.main()
