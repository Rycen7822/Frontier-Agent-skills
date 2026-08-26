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


def raw_failed(*, kind: str, code: str, message: str) -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event("turn.failed", error={"kind": kind, "code": code, "message": message}),
        ]
    ) + b"\n"


def raw_error_item(*, kind: str, code: str, message: str) -> bytes:
    return b"\n".join(
        [
            event("thread.started", thread_id="thread-1"),
            event("turn.started", turn_id="turn-1"),
            event(
                "item.completed",
                item={
                    "id": "error-1",
                    "type": "error",
                    "status": "completed",
                    "error": {"kind": kind, "code": code, "message": message},
                },
            ),
        ]
    ) + b"\n"


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


def emitted_for_row(
    row: dict,
    raw: bytes,
    *,
    timed_out: bool = False,
    isolated: bool = True,
) -> dict:
    input_row = {
        "schema_version": "codex-interaction-probe/1.0",
        "probe_id": row["probe_id"],
        "capability": row["capability"],
        "prompt": "probe",
        "expected_event_types": row["required_event_types"],
    }
    with captured_probe_output(
        input_row,
        raw,
        timed_out=timed_out,
        isolated=isolated,
    ) as (args, workspace, stdout):
        self_result = host._run_probe_mode(args, workspace)
        assert self_result == 0
        return json.loads(stdout.buffer.getvalue().decode())


def raw_noncritical_complete(
    *,
    routing: bool = False,
    permission: bool = False,
    command: bool = False,
    command_complete: bool = True,
    command_exit_code: int | None = 0,
    command_changes: list[dict] | None = None,
    message: str = "inert marker",
) -> bytes:
    item = {
        "id": "final-1",
        "type": "agent_message",
        "status": "completed",
        "text": message,
    }
    if routing:
        item["routing"] = {
            "declared": [],
            "discovered": [],
            "loaded": ["writing-plans"],
            "model_visible": [],
            "selected": ["writing-plans"],
            "invoked": [],
            "applied": ["writing-plans"],
            "order": ["writing-plans"],
            "composition": ["writing-plans"],
        }
    records = [
        event("thread.started", thread_id="thread-1"),
        event("turn.started", turn_id="turn-1"),
    ]
    if command:
        records.append(
            event(
                "item.started",
                item={
                    "id": "command-1",
                    "type": "command_execution",
                    "status": "in_progress",
                },
            )
        )
        if command_complete:
            command_item = {
                "id": "command-1",
                "type": "command_execution",
                "status": "completed",
            }
            if command_exit_code is not None:
                command_item["exit_code"] = command_exit_code
            if command_changes is not None:
                command_item["changes"] = command_changes
            records.append(event("item.completed", item=command_item))
    records.append(event("item.completed", item=item))
    if permission:
        records.append(event("error", error={"kind": "permission_denied"}))
    records.append(
        event("turn.completed", turn_id="turn-1", usage={"input_tokens": 2, "output_tokens": 1})
    )
    return b"\n".join(records) + b"\n"


def raw_noncritical_command_sequence(
    command_events: list[tuple[str, str, dict[str, object]]],
) -> bytes:
    records = [
        event("thread.started", thread_id="thread-1"),
        event("turn.started", turn_id="turn-1"),
    ]
    for command_id, phase, fields in command_events:
        records.append(
            event(
                f"item.{phase}",
                item={
                    "id": command_id,
                    "type": "command_execution",
                    **fields,
                },
            )
        )
    records.extend(
        [
            event(
                "item.completed",
                item={
                    "id": "final-1",
                    "type": "agent_message",
                    "status": "completed",
                    "text": "inert marker",
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
    def test_d38_noncritical_capabilities_close_unknown_without_diagnostic(self):
        for capability in ("multi_turn", "principal_tracing"):
            row = {
                "probe_id": capability,
                "capability": capability,
                "required_event_types": ["thread.started", "turn.completed"],
            }
            result = emitted_for_row(row, raw_noncritical_complete())
            _validate_probe_result(result, row)
            self.assertEqual(result["schema_version"], host.PROBE_RESULT_SCHEMA_VERSION)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["diagnostics"], [])
            self.assertEqual(result["lifecycle"]["branch"], "noncritical_unknown")
            self.assertTrue(result["lifecycle"]["required_events_complete"])
            self.assertFalse(result["lifecycle"]["capability_observable"])
            self.assertFalse(result["lifecycle"]["retryable"])

    def test_d40_completed_command_custody_closes_principal_tracing_unknown(self):
        row = {
            "probe_id": "principal-tracing",
            "capability": "principal_tracing",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        result = emitted_for_row(row, raw_noncritical_complete(command=True))
        _validate_probe_result(result, row)
        self.assertEqual(result["schema_version"], host.PROBE_RESULT_SCHEMA_VERSION)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["diagnostics"], [])
        lifecycle = result["lifecycle"]
        self.assertEqual(lifecycle["schema_version"], host.PROBE_LIFECYCLE_SCHEMA_VERSION)
        self.assertEqual(lifecycle["effect_capable_item_types"], ["command_execution"])
        self.assertTrue(lifecycle["command_custody"]["effect_custody_closed"])
        self.assertFalse(lifecycle["retryable"])
        serialized = json.dumps(lifecycle, sort_keys=True)
        self.assertNotIn('"command":', serialized)
        self.assertNotIn("aggregated_output", serialized)
        terminal = {
            "schema_version": "model-evolution-probe-terminal/12",
            "request_id": REQUEST["request_id"],
            "probe_id": row["probe_id"],
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
            loaded = _load_probe_terminal(path, request=REQUEST, row=row)
        self.assertEqual(loaded["result"]["status"], "unknown")

    def test_d43_sequence_safe_command_custody_closes_one_and_three_commands(self):
        row = {
            "probe_id": "principal-tracing",
            "capability": "principal_tracing",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        raw_values = (
            raw_noncritical_complete(command=True),
            raw_noncritical_command_sequence(
                [
                    ("command-1", "started", {"status": "in_progress"}),
                    ("command-2", "started", {"status": "in_progress"}),
                    ("command-3", "started", {"status": "in_progress"}),
                    ("command-2", "completed", {"status": "completed", "exit_code": 0}),
                    ("command-1", "completed", {"status": "completed", "exit_code": 0}),
                    ("command-3", "completed", {"status": "completed", "exit_code": 0}),
                ]
            ),
        )
        for command_count, raw in enumerate(raw_values, 1):
            result = emitted_for_row(row, raw)
            _validate_probe_result(result, row)
            custody = result["lifecycle"]["command_custody"]
            expected_count = 1 if command_count == 1 else 3
            self.assertEqual(custody["item_count"], expected_count)
            self.assertEqual(custody["started_count"], expected_count)
            self.assertEqual(custody["completed_count"], expected_count)
            self.assertEqual(custody["zero_exit_count"], expected_count)
            self.assertTrue(custody["paired"])
            self.assertTrue(custody["effect_custody_closed"])
            self.assertEqual(set(custody["reason_counts"].values()), {0})
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["diagnostics"], [])
            projection = json.dumps(custody, sort_keys=True)
            for forbidden in (
                "command-1",
                "command-2",
                "command-3",
                "aggregated_output",
                '"command"',
                "inert marker",
            ):
                self.assertNotIn(forbidden, projection)
            terminal = {
                "schema_version": "model-evolution-probe-terminal/12",
                "request_id": REQUEST["request_id"],
                "probe_id": row["probe_id"],
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
                terminal_path = Path(temporary) / "terminal.json"
                terminal_path.write_text(json.dumps(terminal), encoding="utf-8")
                loaded = _load_probe_terminal(
                    terminal_path,
                    request=REQUEST,
                    row=row,
                )
            self.assertEqual(
                loaded["schema_version"],
                "model-evolution-probe-terminal/12",
            )

    def test_d43_sequence_command_custody_fails_closed_on_phase_and_result_faults(self):
        negative_items = (
            [
                {"id": "command-1", "type": "command_execution", "phase": "started"},
                {"id": "command-1", "type": "command_execution", "phase": "started"},
                {"id": "command-1", "type": "command_execution", "phase": "completed", "status": "completed", "exit_code": 0},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started"},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started"},
                {"id": "command-2", "type": "command_execution", "phase": "completed", "status": "completed", "exit_code": 0},
            ],
            [
                {"id": "", "type": "command_execution", "phase": "started"},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "mystery"},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started"},
                {"id": "command-1", "type": "command_execution", "phase": "completed", "status": "completed"},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started"},
                {"id": "command-1", "type": "command_execution", "phase": "completed", "status": "completed", "exit_code": 1},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started", "error": {"kind": "failure"}},
                {"id": "command-1", "type": "command_execution", "phase": "completed", "status": "completed", "exit_code": 0},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started", "changes": [{"kind": "write"}]},
                {"id": "command-1", "type": "command_execution", "phase": "completed", "status": "completed", "exit_code": 0},
            ],
            [
                {"id": "command-1", "type": "command_execution", "phase": "started"},
                {"id": "command-1", "type": "command_execution", "phase": "completed", "status": "incomplete", "exit_code": 0},
            ],
        )
        for items in negative_items:
            custody = host._probe_command_custody({"items": items})
            self.assertFalse(custody["effect_custody_closed"], items)
            self.assertFalse(custody["successful"], items)
            self.assertTrue(any(custody["reason_counts"].values()), items)

    def test_d43_dirty_workspace_remains_conjunctive_with_safe_command_sequence(self):
        raw = raw_noncritical_command_sequence(
            [
                ("command-1", "started", {"status": "in_progress"}),
                ("command-1", "completed", {"status": "completed", "exit_code": 0}),
            ]
        )
        lifecycle, status, diagnostics = project(raw, timed_out=False, dirty=True)
        self.assertTrue(lifecycle["command_custody"]["effect_custody_closed"])
        self.assertFalse(lifecycle["workspace_clean"])
        self.assertFalse(lifecycle["custody_closed"])
        self.assertEqual(status, "unknown")
        self.assertTrue(diagnostics)

    def test_d44_failed_nonzero_command_closes_effect_custody_without_success(self):
        row = {
            "probe_id": "principal-tracing",
            "capability": "principal_tracing",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        raw = raw_noncritical_command_sequence(
            [
                ("command-1", "started", {"status": "in_progress"}),
                ("command-1", "completed", {"status": "failed", "exit_code": 7}),
            ]
        )
        result = emitted_for_row(row, raw)
        _validate_probe_result(result, row)
        custody = result["lifecycle"]["command_custody"]
        self.assertFalse(custody["successful"])
        self.assertEqual(custody["zero_exit_count"], 0)
        self.assertEqual(custody["failed_nonzero_count"], 1)
        self.assertTrue(custody["effect_custody_closed"])
        self.assertTrue(result["lifecycle"]["effect_custody_closed"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["diagnostics"], [])
        self.assertFalse(result["lifecycle"]["retryable"])

    def test_d44_credential_projection_distinguishes_safe_and_possible_exposure(self):
        row = {
            "probe_id": "principal-tracing",
            "capability": "principal_tracing",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        safe = emitted_for_row(row, raw_noncritical_complete(message="TOKEN=redacted"))
        _validate_probe_result(safe, row)
        safe_observation = safe["lifecycle"]["credential_observation"]
        self.assertTrue(safe_observation["marker_seen"])
        self.assertFalse(safe_observation["exposure_possible"])
        self.assertEqual(safe_observation["markers"][0]["value_shape"], "safe_placeholder")
        self.assertEqual(safe["status"], "unknown")
        self.assertEqual(safe["diagnostics"], [])
        for message, expected_shape in (
            ("TOKEN=ordinary-value", "non_placeholder"),
            ("sk-exampleSecretValue", "secret_like"),
            ("authorization: withheld", "unattributed"),
        ):
            result = emitted_for_row(row, raw_noncritical_complete(message=message))
            _validate_probe_result(result, row)
            observation = result["lifecycle"]["credential_observation"]
            self.assertTrue(observation["marker_seen"], message)
            self.assertTrue(observation["exposure_possible"], message)
            self.assertIn(expected_shape, {item["value_shape"] for item in observation["markers"]})
            self.assertFalse(result["lifecycle"]["custody_closed"], message)
            self.assertTrue(result["diagnostics"], message)
            serialized = json.dumps(result, sort_keys=True)
            self.assertNotIn(message, serialized)

    def test_d45_structured_credential_provenance_is_source_sensitive_and_deduplicated(self):
        command_records = b"\n".join(
            [
                event("thread.started", thread_id="thread-1"),
                event("turn.started", turn_id="turn-1"),
                event("item.started", item={"id": "command-1", "type": "command_execution", "command": "TOKEN=ordinary-value", "status": "in_progress"}),
                event("item.completed", item={"id": "command-1", "type": "command_execution", "command": "TOKEN=ordinary-value", "aggregated_output": "ok", "status": "completed", "exit_code": 0}),
                event("turn.completed", turn_id="turn-1", usage={"input_tokens": 2, "output_tokens": 1}),
            ]
        ) + b"\n"
        command = host._probe_credential_observation(command_records, b"")
        self.assertTrue(command["structured_coverage_complete"])
        self.assertFalse(command["exposure_possible"])
        self.assertEqual(command["occurrence_count"], 1)
        self.assertEqual(command["markers"], [{"kind": "assignment", "source": "command_text", "count": 1, "value_shape": "command_syntax"}])

        output_records = command_records.replace(b'"aggregated_output":"ok"', b'"aggregated_output":"TOKEN=ordinary-value"')
        output = host._probe_credential_observation(output_records, b"")
        self.assertTrue(output["exposure_possible"])
        self.assertIn("command_output", {row["source"] for row in output["markers"]})

        secret = host._probe_credential_observation(command_records.replace(b"ordinary-value", b"sk-exampleSecretValue"), b"")
        self.assertTrue(secret["exposure_possible"])
        self.assertIn("secret_like", {row["value_shape"] for row in secret["markers"]})

    def test_d45_structured_credential_provenance_fails_closed_on_unknown_raw_and_stderr(self):
        unknown = b'{"type":"turn.started","future":"TOKEN=ordinary-value"}\n'
        observation = host._probe_credential_observation(unknown, b"")
        self.assertTrue(observation["exposure_possible"])
        self.assertEqual(observation["markers"][0]["source"], "unknown")

        malformed = host._probe_credential_observation(b'{not-json TOKEN=ordinary-value}\n', b"")
        self.assertFalse(malformed["structured_coverage_complete"])
        self.assertTrue(malformed["exposure_possible"])
        self.assertEqual(malformed["markers"][0]["source"], "raw_unattributed")

        stderr = host._probe_credential_observation(raw_complete(), b"TOKEN=ordinary-value")
        self.assertTrue(stderr["exposure_possible"])
        self.assertEqual(stderr["markers"][0]["source"], "child_stderr")

    def test_d44_terminal_v11_replays_under_strict_historical_shape(self):
        result = emitted_probe_result(raw_complete())
        result["schema_version"] = host.PROBE_RESULT_SCHEMA_VERSION_D44
        result["lifecycle"]["schema_version"] = host.PROBE_LIFECYCLE_SCHEMA_VERSION_D44
        result["lifecycle"]["credential_observation"].pop("structured_coverage_complete")
        terminal = {
            "schema_version": "model-evolution-probe-terminal/11",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 1,
            "attempts": [{"attempt": 1, "attempt_id": REQUEST["request_id"] + ".attempt-1", "status": result["status"], "diagnostics": result["diagnostics"], "stderr": "", "lifecycle": result["lifecycle"]}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/11")

    def test_d44_current_projection_excludes_sensitive_content(self):
        raw = raw_noncritical_command_sequence(
            [
                ("command-sensitive", "started", {"status": "in_progress", "command": "print secret"}),
                ("command-sensitive", "completed", {"status": "failed", "exit_code": 3, "aggregated_output": "hidden output"}),
            ]
        )
        lifecycle, _, _ = project(raw, timed_out=False)
        serialized = json.dumps(lifecycle, sort_keys=True)
        for forbidden in ("command-sensitive", "print secret", "hidden output", "aggregated_output"):
            self.assertNotIn(forbidden, serialized)

    def test_d43_terminal_v10_replays_under_strict_historical_shape(self):
        row = {
            "probe_id": "principal-tracing",
            "capability": "principal_tracing",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        result = emitted_for_row(row, raw_noncritical_complete(command=True))
        result["schema_version"] = host.PROBE_RESULT_SCHEMA_VERSION_D43
        lifecycle = result["lifecycle"]
        lifecycle["schema_version"] = host.PROBE_LIFECYCLE_SCHEMA_VERSION_D43
        lifecycle.pop("credential_exposure_possible")
        lifecycle.pop("credential_observation")
        lifecycle.pop("effect_custody_closed")
        custody = lifecycle["command_custody"]
        reasons = custody["reason_counts"]
        reasons["invalid_completed_status"] = reasons.pop("unknown_completed_status")
        reasons["nonzero_exit_code"] = reasons.pop("status_exit_mismatch")
        custody["safe_completed"] = custody["successful"]
        custody.pop("failed_nonzero_count")
        custody.pop("effect_custody_closed")
        terminal = {
            "schema_version": "model-evolution-probe-terminal/10",
            "request_id": REQUEST["request_id"],
            "probe_id": row["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 1,
            "attempts": [{
                "attempt": 1,
                "attempt_id": REQUEST["request_id"] + ".attempt-1",
                "status": result["status"],
                "diagnostics": result["diagnostics"],
                "stderr": "",
                "lifecycle": lifecycle,
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=row)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/10")

    def test_d40_command_custody_negative_shapes_fail_closed(self):
        row = {
            "probe_id": "principal-tracing",
            "capability": "principal_tracing",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        for raw in (
            raw_noncritical_complete(command=True, command_complete=False),
            raw_noncritical_complete(command=True, command_exit_code=1),
            raw_noncritical_complete(command=True, command_changes=[{"path": "fixture"}]),
        ):
            result = emitted_for_row(row, raw)
            _validate_probe_result(result, row)
            self.assertEqual(result["status"], "unknown")
            self.assertTrue(result["diagnostics"])
            self.assertFalse(result["lifecycle"]["command_custody"]["effect_custody_closed"])
            self.assertFalse(result["lifecycle"]["retryable"])

    def test_d39_result_1_5_terminal_7_replays_without_d40_custody_field(self):
        row = {
            "probe_id": "multi-turn",
            "capability": "multi_turn",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        current = emitted_for_row(row, raw_noncritical_complete())
        historical = json.loads(json.dumps(current))
        historical["schema_version"] = host.PROBE_RESULT_SCHEMA_VERSION_D39
        historical["lifecycle"]["schema_version"] = host.PROBE_LIFECYCLE_SCHEMA_VERSION_D39
        historical["lifecycle"].pop("command_custody")
        historical["lifecycle"].pop("credential_exposure_possible")
        historical["lifecycle"].pop("credential_observation")
        historical["lifecycle"].pop("effect_custody_closed")
        historical_observation = historical["lifecycle"]["failure_observation"]
        historical_observation.pop("occurrence_count")
        historical_observation.pop("source_counts")
        terminal = {
            "schema_version": "model-evolution-probe-terminal/7",
            "request_id": REQUEST["request_id"],
            "probe_id": row["probe_id"],
            "result": historical,
            "stderr": "",
            "attempt_count": 1,
            "attempts": [{
                "attempt": 1,
                "attempt_id": REQUEST["request_id"] + ".attempt-1",
                "status": historical["status"],
                "diagnostics": historical["diagnostics"],
                "stderr": "",
                "lifecycle": historical["lifecycle"],
            }],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "d39-terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=row)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/7")

    def test_d38_missing_required_event_is_diagnostic_and_not_retryable(self):
        row = {
            "probe_id": "multi-turn",
            "capability": "multi_turn",
            "required_event_types": ["thread.started", "turn.completed", "direct.routing"],
        }
        result = emitted_for_row(row, raw_noncritical_complete())
        _validate_probe_result(result, row)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["diagnostics"])
        self.assertEqual(result["lifecycle"]["branch"], "unknown")
        self.assertFalse(result["lifecycle"]["retryable"])

    def test_d38_effect_capable_noncritical_observation_fails_closed(self):
        row = {
            "probe_id": "multi-turn",
            "capability": "multi_turn",
            "required_event_types": ["thread.started", "turn.completed"],
        }
        result = emitted_for_row(row, raw_effect_timeout(), timed_out=False)
        _validate_probe_result(result, row)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["diagnostics"])
        self.assertEqual(result["lifecycle"]["reason"], "effect_capable")
        self.assertFalse(result["lifecycle"]["retryable"])

    def test_d38_critical_probe_projection_still_passes_expected_observation(self):
        for capability, raw in (
            ("force_load", raw_noncritical_complete()),
            ("natural_routing", raw_noncritical_complete(routing=True)),
            ("usage_capture", raw_noncritical_complete()),
            ("action_authorization_trace", raw_noncritical_complete(permission=True)),
        ):
            row = {
                "probe_id": capability,
                "capability": capability,
                "required_event_types": [
                    "thread.started",
                    "turn.completed",
                    *(["direct.routing"] if capability == "force_load" else []),
                ],
            }
            result = emitted_for_row(row, raw)
            _validate_probe_result(result, row)
            self.assertEqual(result["status"], "pass", capability)

    def test_reasoning_only_d35_event_vector_uses_real_emitter_and_terminal_loader(self):
        result = emitted_probe_result(raw_reasoning_vector(), timed_out=True, isolated=True)
        _validate_probe_result(result, ROW)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["lifecycle"]["completed_item_types"], ["reasoning"])
        self.assertEqual(result["lifecycle"]["non_effect_progress_item_types"], ["reasoning"])
        self.assertFalse(result["lifecycle"]["retryable"])
        self.assertEqual(
            result["lifecycle"]["failure_observation"]["failure_class"],
            "provider_nonretryable",
        )
        attempts = [
            {
                "attempt": 1,
                "attempt_id": REQUEST["request_id"] + ".attempt-1",
                "status": result["status"],
                "diagnostics": result["diagnostics"],
                "stderr": "",
                "lifecycle": result["lifecycle"],
            }
        ]
        terminal = {
            "schema_version": "model-evolution-probe-terminal/12",
            "request_id": REQUEST["request_id"],
            "probe_id": ROW["probe_id"],
            "result": result,
            "stderr": "",
            "attempt_count": 1,
            "attempts": attempts,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "terminal.json"
            path.write_text(json.dumps(terminal), encoding="utf-8")
            loaded = _load_probe_terminal(path, request=REQUEST, row=ROW)
        self.assertEqual(loaded["schema_version"], "model-evolution-probe-terminal/12")

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
            "schema_version": "model-evolution-probe-terminal/12",
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
            "schema_version": "model-evolution-probe-terminal/12",
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
            "schema_version": "model-evolution-probe-terminal/12",
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

    def test_d39_empty_timeout_and_exact_transients_are_retryable(self):
        lifecycle, _, _ = project(raw_timeout())
        self.assertTrue(lifecycle["retryable"])
        self.assertEqual(lifecycle["failure_observation"]["failure_class"], "none")
        capacity_lifecycle, _, _ = project(
            raw_failed(
                kind="codex_error",
                code="capacity",
                message=host.MODEL_CAPACITY_MESSAGE,
            ),
            timed_out=False,
        )
        self.assertTrue(capacity_lifecycle["retryable"])
        self.assertEqual(
            capacity_lifecycle["failure_observation"]["failure_class"],
            "capacity_transient",
        )
        transport = child(raw_timeout(), timed_out=True)
        transport["stderr"] = b"responses_websocket: failed to connect to websocket: IO error: tls handshake eof"
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            lifecycle, _, _ = host._probe_lifecycle_projection(
                transport,
                normalize_jsonl(raw_timeout()),
                workspace=workspace,
                workspace_before={"fixture": "sha256:" + "a" * 64},
                workspace_after={"fixture": "sha256:" + "a" * 64},
                workspace_before_ok=True,
                workspace_after_ok=True,
                last_message=workspace / "missing-last-message",
                source_root=None,
                isolated=True,
            )
        self.assertTrue(lifecycle["retryable"])
        self.assertEqual(
            lifecycle["failure_observation"]["failure_class"],
            "transport_transient",
        )

    def test_d39_error_bearing_timeout_classes_are_never_retryable(self):
        for kind, code, message, expected in (
            ("authentication_error", "unauthorized", "credential rejected", "authentication"),
            ("configuration_error", "invalid_request", "invalid request", "configuration"),
            ("provider_error", "usage_limit", "usage limit reached", "usage_limit"),
            ("provider_error", "bad_gateway", "provider failed", "provider_nonretryable"),
        ):
            lifecycle, _, _ = project(
                raw_error_item(kind=kind, code=code, message=message)
            )
            self.assertFalse(lifecycle["retryable"], expected)
            self.assertEqual(
                lifecycle["failure_observation"]["failure_class"], expected
            )
            serialized = json.dumps(lifecycle, sort_keys=True)
            if expected == "provider_nonretryable":
                self.assertIn("provider failed", serialized)
            else:
                self.assertNotIn(message, serialized)

    def test_d42_failure_projection_deduplicates_redacts_and_preserves_runtime(self):
        prompt = "D42-PROMPT-CONTENT"
        source_root = Path("/source/private/controller")
        failure = {
            "kind": "provider_error",
            "code": "bad_gateway",
            "message": (
                "gateway unavailable D42-PROMPT-CONTENT "
                "/source/private/controller/file.py /workspace/private/output "
                "sk-secret-token"
            ),
        }
        records = [
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started"},
            *({"type": "error", "error": failure} for _ in range(8)),
            {
                "type": "item.completed",
                "item": {"id": "error-item", "type": "error", "error": failure},
            },
        ]
        normalized = normalize_jsonl(
            b"\n".join(
                event(
                    row["type"],
                    **{key: value for key, value in row.items() if key != "type"},
                )
                for row in records
            )
            + b"\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            observation = host._probe_failure_observation(
                {
                    "runtime_ms": 900000.4,
                    "timed_out": True,
                    "stderr": b"",
                    "returncode": -9,
                },
                normalized,
                workspace=workspace,
                source_root=source_root,
                excluded_values=(prompt, "/workspace/private/output"),
            )
        self.assertEqual(observation["runtime_ms"], 900000)
        self.assertEqual(observation["occurrence_count"], 9)
        self.assertEqual(
            observation["source_counts"],
            [{"source": "item", "count": 1}, {"source": "record", "count": 8}],
        )
        self.assertEqual(len(observation["failures"]), 1)
        projected = observation["failures"][0]
        self.assertEqual(projected["count"], 9)
        self.assertEqual(projected["source_counts"], observation["source_counts"])
        self.assertRegex(projected["signature"], r"^sha256:[0-9a-f]{64}$")
        self.assertIn("gateway unavailable", projected["detail"])
        serialized = json.dumps(observation, sort_keys=True)
        for excluded in (
            prompt,
            "sk-secret-token",
            str(source_root),
            "/workspace/private/output",
        ):
            self.assertNotIn(excluded, serialized)

    def test_d42_timeout_runtime_never_collapses_positive_float_to_zero(self):
        self.assertEqual(host._integer_runtime_ms(0.1), 1)
        self.assertEqual(host._integer_runtime_ms(12.5), 13)
        self.assertEqual(host._integer_runtime_ms(900000.0), 900000)

    def test_d39_mixed_and_malformed_fail_closed(self):
        mixed_raw = b"\n".join(
            [
                event("thread.started", thread_id="thread-1"),
                event("turn.started", turn_id="turn-1"),
                event("error", error={"kind": "authentication_error", "code": "unauthorized"}),
                event("error", error={"kind": "provider_error", "code": "bad_gateway"}),
            ]
        ) + b"\n"
        lifecycle, _, _ = project(mixed_raw)
        self.assertFalse(lifecycle["retryable"])
        self.assertEqual(lifecycle["failure_observation"]["failure_class"], "mixed")
        lifecycle, _, _ = project(raw_timeout(malformed=True))
        self.assertFalse(lifecycle["retryable"])
        self.assertEqual(lifecycle["failure_observation"]["failure_class"], "malformed")

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
            "schema_version": "model-evolution-probe-terminal/12",
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
