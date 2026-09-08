"""Selected history stays bounded and source-located without replaying it."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skill-evaluator/scripts"))
import inspect_history


class HistoryInspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "rollout.jsonl"

    def write(self, records):
        self.path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def test_index_and_filtered_events_preserve_evidence_without_replaying(self):
        marker = self.root / "must-not-exist"
        self.write([
            {"type": "session_meta", "payload": {"id": "session", "cwd": str(self.root)}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "Please fix the skill"}]}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "UserMessage", "content": "Please fix the skill"}}},
            {"type": "response_item", "payload": {"type": "reasoning", "summary": "private reasoning"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "functions.exec", "call_id": "call-1", "input": f"touch {marker}"}},
            {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution", "command": f"touch {marker}", "exit_code": 1, "stdout": ""}}},
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call-1", "output": "command failed"}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "phase": "final", "content": [{"text": "Could not complete"}]}},
        ])
        before = self.path.read_bytes()
        index = inspect_history.inspect(self.path)
        self.assertEqual([2, 8], [e["line"] for e in index["events"]])
        events = inspect_history.inspect(self.path, view="events", match="call-1")
        self.assertEqual([5, 7], [e["line"] for e in events["events"]])
        all_events = inspect_history.inspect(self.path, view="events")
        self.assertEqual([2, 5, 6, 7, 8], [e["line"] for e in all_events["events"]])
        command = inspect_history.inspect(self.path, view="events", match="CommandExecution")
        self.assertEqual(6, command["events"][0]["line"])
        self.assertIn('"exit_code": 1', command["events"][0]["text"])
        self.assertFalse(marker.exists())
        self.assertEqual(before, self.path.read_bytes())

    def test_budget_continuation_and_invalid_input_are_explicit(self):
        records = [{"type": "session_meta", "payload": {"id": "session"}}]
        for content in ("x" * 100 + "needle" + "y" * 100, "next request"):
            records.append({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": content}]}})
        self.write(records)
        page = inspect_history.inspect(self.path, match="needle", max_chars=20, event_chars=40)
        event = page["events"][0]
        self.assertIn("needle", event["text"])
        self.assertEqual(20, len(event["text"]))
        self.assertEqual(186, event["omitted_chars"])
        self.assertEqual(95, event["text_offset"])
        self.assertEqual(3, page["next_line"])
        next_page = inspect_history.inspect(self.path, start_line=page["next_line"])
        self.assertEqual([3], [e["line"] for e in next_page["events"]])
        self.assertIsNone(next_page["next_line"])
        capped = inspect_history.inspect(self.path, max_events=1)
        self.assertEqual(1, len(capped["events"]))
        episode = inspect_history.inspect(self.path, end_line=2, max_events=1)
        self.assertEqual([2], [e["line"] for e in episode["events"]])
        self.assertIsNone(episode["next_line"])
        self.path.write_text(self.path.read_text() + '{"type":')
        with self.assertRaisesRegex(ValueError, "invalid JSON.*:4"):
            inspect_history.inspect(self.path)
        failed = subprocess.run([sys.executable, str(ROOT / "skill-evaluator/scripts/inspect_history.py"), str(self.path), "--max-events", "0"], capture_output=True, text=True)
        self.assertEqual(2, failed.returncode)
        self.assertEqual("", failed.stdout)


if __name__ == "__main__":
    unittest.main()
