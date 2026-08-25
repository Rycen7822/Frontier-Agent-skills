import json
import sys
import tempfile
import unittest
from pathlib import Path


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
                "id": "command-1",
                "type": "command_execution",
                "command": "printf hidden",
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
        self.assertEqual(lifecycle["reason"], "outcome_bearing")
        self.assertFalse(lifecycle["retryable"])
        self.assertTrue(lifecycle["completed_turn"])
        self.assertTrue(lifecycle["usage_present"])

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
            "schema_version": "model-evolution-probe-terminal/4",
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


if __name__ == "__main__":
    unittest.main()
