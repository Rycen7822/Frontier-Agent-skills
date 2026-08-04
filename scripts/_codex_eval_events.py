"""Normalize bounded Codex exec JSONL without inferring hidden behavior."""

from __future__ import annotations

import json
from typing import Any


MAX_JSONL_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 10_000
RECORD_REQUIREMENTS = {
    "thread.started": {"thread_id"},
    "turn.started": set(),
    "turn.completed": set(),
    "turn.failed": set(),
    "item.started": {"item"},
    "item.completed": {"item"},
    "error": set(),
}
ITEM_TYPES = {
    "agent_message",
    "reasoning",
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "collab_tool_call",
    "web_search",
    "todo_list",
    "error",
}
TOKEN_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
ROUTING_FIELDS = (
    "declared",
    "discovered",
    "loaded",
    "model_visible",
    "selected",
    "invoked",
    "applied",
    "order",
    "composition",
)


def _diagnostic(kind: str, message: str, index: int | None = None) -> dict[str, Any]:
    return {"kind": kind, "index": index, "message": message}


def _item_fact(item: dict[str, Any], phase: str) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "id": item["id"],
        "type": item["type"],
        "phase": phase,
    }
    for field in ("status", "command", "exit_code", "server", "tool", "query"):
        value = item.get(field)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            fact[field] = value
    error = item.get("error")
    if isinstance(error, dict):
        fact["error"] = {
            field: error[field]
            for field in ("kind", "code")
            if isinstance(error.get(field), str)
        }
    return fact


def _routing_fact(item: dict[str, Any]) -> dict[str, list[str]] | None:
    value = item.get("routing")
    if value is None:
        return None
    if (
        not isinstance(value, dict)
        or set(value) != set(ROUTING_FIELDS)
        or any(
            not isinstance(value[field], list)
            or any(not isinstance(item_id, str) for item_id in value[field])
            for field in ROUTING_FIELDS
        )
    ):
        raise ValueError("direct routing evidence has an invalid shape")
    return {field: list(value[field]) for field in ROUTING_FIELDS}


def _usage_fact(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("turn usage is not an object")
    fact: dict[str, int] = {}
    for field in TOKEN_FIELDS:
        item = value.get(field)
        if item is None:
            continue
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError(f"turn usage {field} is invalid")
        fact[field] = item
    return fact or None


def _failure_fact(
    source: str,
    failure_id: str,
    value: dict[str, Any],
) -> dict[str, str] | None:
    error = value.get("error")
    if isinstance(error, dict):
        fact = {
            field: error[field]
            for field in ("kind", "code", "message")
            if isinstance(error.get(field), str) and error[field]
        }
    else:
        fact = {}
    message = value.get("message")
    if "message" not in fact and isinstance(message, str) and message:
        fact["message"] = message
    if not fact:
        return None
    fact.setdefault("kind", "codex_error")
    return {"source": source, "id": failure_id, **fact}


def normalize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return direct Codex facts and typed apparatus diagnostics."""
    diagnostics: list[dict[str, Any]] = []
    event_types: list[str] = []
    item_facts: list[dict[str, Any]] = []
    started_items: dict[str, dict[str, Any]] = {}
    completed_items: set[str] = set()
    final_messages: list[str] = []
    permission_denials: list[str] = []
    failures: list[dict[str, str]] = []
    usage: dict[str, int] | None = None
    routing: dict[str, list[str]] | None = None
    thread_id: str | None = None
    turn_started = 0
    terminal_type: str | None = None

    for index, record in enumerate(records, 1):
        record_type = record.get("type")
        if not isinstance(record_type, str) or record_type not in RECORD_REQUIREMENTS:
            diagnostics.append(
                _diagnostic("unknown_record_type", "unknown Codex record type", index)
            )
            continue
        missing = RECORD_REQUIREMENTS[record_type] - set(record)
        if missing:
            diagnostics.append(
                _diagnostic(
                    "missing_record_field",
                    f"{record_type} lacks required fields",
                    index,
                )
            )
            continue
        if terminal_type is not None:
            kind = (
                "duplicate_terminal"
                if record_type in {"turn.completed", "turn.failed"}
                else "post_terminal_event"
            )
            diagnostics.append(
                _diagnostic(kind, "Codex emitted a record after turn terminal", index)
            )
            continue
        event_types.append(record_type)
        if record_type == "thread.started":
            value = record["thread_id"]
            if not isinstance(value, str) or not value or thread_id is not None:
                diagnostics.append(
                    _diagnostic(
                        "thread_identity",
                        "Codex thread identity is invalid or duplicated",
                        index,
                    )
                )
            else:
                thread_id = value
        elif record_type == "turn.started":
            turn_started += 1
        elif record_type in {"turn.completed", "turn.failed"}:
            terminal_type = record_type
            if record_type == "turn.completed":
                try:
                    usage = _usage_fact(record.get("usage"))
                except ValueError as exc:
                    diagnostics.append(_diagnostic("usage", str(exc), index))
            else:
                failure = _failure_fact("turn", f"turn-{index}", record)
                if failure is not None:
                    failures.append(failure)
        elif record_type in {"item.started", "item.completed"}:
            item = record["item"]
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not item["id"]
                or item.get("type") not in ITEM_TYPES
            ):
                diagnostics.append(
                    _diagnostic(
                        "unknown_item", "Codex item identity or type is invalid", index
                    )
                )
                continue
            item_id = item["id"]
            phase = record_type.removeprefix("item.")
            item_facts.append(_item_fact(item, phase))
            if phase == "started":
                if item_id in started_items or item_id in completed_items:
                    diagnostics.append(
                        _diagnostic(
                            "item_lifecycle", "Codex item started more than once", index
                        )
                    )
                else:
                    started_items[item_id] = item
            else:
                if item_id in completed_items:
                    diagnostics.append(
                        _diagnostic(
                            "item_lifecycle",
                            "Codex item completed more than once",
                            index,
                        )
                    )
                completed_items.add(item_id)
                started = started_items.get(item_id)
                if started is not None and started.get("type") != item["type"]:
                    diagnostics.append(
                        _diagnostic(
                            "item_lifecycle",
                            "Codex item type changed across its lifecycle",
                            index,
                        )
                    )
                if item["type"] == "agent_message":
                    text = item.get("text")
                    if not isinstance(text, str):
                        diagnostics.append(
                            _diagnostic(
                                "agent_message",
                                "completed agent message lacks text",
                                index,
                            )
                        )
                    else:
                        final_messages.append(text)
                error = item.get("error")
                if isinstance(error, dict) and error.get("kind") == "permission_denied":
                    permission_denials.append(item_id)
                failure = _failure_fact("item", item_id, item)
                if failure is not None:
                    failures.append(failure)
                try:
                    observed_routing = _routing_fact(item)
                except ValueError as exc:
                    diagnostics.append(_diagnostic("routing", str(exc), index))
                else:
                    if observed_routing is not None:
                        if routing is not None:
                            diagnostics.append(
                                _diagnostic(
                                    "routing",
                                    "Codex emitted duplicate direct routing evidence",
                                    index,
                                )
                            )
                        routing = observed_routing
        else:
            error = record.get("error")
            if isinstance(error, dict) and error.get("kind") == "permission_denied":
                permission_denials.append(f"error-{index}")
            failure = _failure_fact("record", f"error-{index}", record)
            if failure is not None:
                failures.append(failure)

    if thread_id is None:
        diagnostics.append(
            _diagnostic(
                "thread_identity", "Codex stream lacks one thread.started record"
            )
        )
    if turn_started != 1:
        diagnostics.append(
            _diagnostic(
                "turn_lifecycle", "Codex stream requires one turn.started record"
            )
        )
    if terminal_type is None:
        diagnostics.append(
            _diagnostic("missing_terminal", "Codex stream lacks a turn terminal")
        )
    if started_items.keys() - completed_items:
        diagnostics.append(
            _diagnostic("item_lifecycle", "Codex stream has incomplete items")
        )
    status = (
        "protocol_error"
        if diagnostics
        else "completed"
        if terminal_type == "turn.completed"
        else "failed"
    )
    return {
        "status": status,
        "thread_id": thread_id,
        "event_types": event_types,
        "items": item_facts,
        "final_message": final_messages[-1] if final_messages else None,
        "tool_call_ids": sorted(
            {
                item["id"]
                for item in item_facts
                if item["type"] in {"command_execution", "mcp_tool_call"}
            }
        ),
        "permission_denials": sorted(set(permission_denials)),
        "failures": failures,
        "usage": usage,
        "routing": routing,
        "diagnostics": diagnostics,
    }


def normalize_jsonl(raw: bytes) -> dict[str, Any]:
    """Parse one bounded Codex JSONL turn and normalize it."""
    if len(raw) > MAX_JSONL_BYTES:
        return normalize_records([]) | {
            "status": "protocol_error",
            "diagnostics": [
                _diagnostic("stream_size", "Codex JSONL exceeds the bounded size")
            ],
        }
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return normalize_records([]) | {
            "status": "protocol_error",
            "diagnostics": [_diagnostic("non_utf8", "Codex JSONL is not UTF-8")],
        }
    records: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        if len(records) >= MAX_RECORDS:
            return normalize_records(records) | {
                "status": "protocol_error",
                "diagnostics": [
                    _diagnostic(
                        "record_count", "Codex JSONL exceeds the record bound", index
                    )
                ],
            }
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return normalize_records(records) | {
                "status": "protocol_error",
                "diagnostics": [
                    _diagnostic(
                        "malformed_jsonl", "Codex JSONL contains malformed JSON", index
                    )
                ],
            }
        if not isinstance(value, dict):
            return normalize_records(records) | {
                "status": "protocol_error",
                "diagnostics": [
                    _diagnostic(
                        "malformed_jsonl", "Codex JSONL record is not an object", index
                    )
                ],
            }
        records.append(value)
    return normalize_records(records)


def host_protocol_error(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    """Project one direct diagnostic onto the existing Host protocol error."""
    first = (
        diagnostics[0]
        if diagnostics
        else {
            "kind": "malformed_record",
            "index": None,
            "message": "Codex adapter protocol failed",
        }
    )
    kind = first.get("kind")
    return {
        "kind": (
            kind
            if kind
            in {
                "non_utf8",
                "sequence_gap",
                "duplicate_terminal",
                "post_terminal_event",
                "identity_mismatch",
                "malformed_record",
            }
            else "malformed_record"
        ),
        "message": str(first.get("message") or "Codex adapter protocol failed"),
        "seq": first.get("index") if isinstance(first.get("index"), int) else None,
        "artifact": None,
    }


def base_host_result(
    request: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Build the common honest-missing Host result projection."""
    return {
        "record_type": "skill-evaluator-host-result/1",
        "terminal": True,
        "terminal_status": "completed",
        "envelope": request["envelope"],
        "request_hash": request["request_hash"],
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "principals": [],
        "handoffs": [],
        "actions": [],
        "artifacts": [],
        "state": [],
        "cleanup": {"status": "clean", "state": "not_applicable"},
        "usage": {
            "pricing_identity": manifest["identity"]["execution"]["pricing_id"],
            "host_safety_review": {
                "capture_status": "missing",
                "host_safety_review_count": 0,
                "host_safety_review_latency_ms": 0,
            },
            "records": [],
        },
        "context": {
            "status": "missing",
            "bytes": 0,
            "tokens": None,
            "controlled_bytes": 0,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": 0,
            "components": [],
        },
        "assertions": [],
    }


def model_grade_schema(batch: dict[str, Any]) -> dict[str, Any]:
    """Build a provider-supported shape; runtime validation binds identities."""
    check_counts = [len(item["checks"]) for item in batch["items"]]
    if len(set(check_counts)) != 1:
        raise ValueError("model-grade batch check cardinality differs")
    check_schema = {
        "type": "object",
        "required": ["id", "pass", "notes", "uncertainty"],
        "properties": {
            "id": {"type": "string"},
            "pass": {"type": "boolean"},
            "notes": {"type": "string"},
            "uncertainty": {
                "type": "string",
                "enum": ["none", "low", "medium", "high"],
            },
        },
        "additionalProperties": False,
    }
    item_schema = {
        "type": "object",
        "required": ["item_id", "checks"],
        "properties": {
            "item_id": {"type": "string"},
            "checks": {
                "type": "array",
                "items": check_schema,
                "minItems": check_counts[0],
                "maxItems": check_counts[0],
            },
        },
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "required": ["batch_id", "items"],
        "properties": {
            "batch_id": {"type": "string", "enum": [batch["batch_id"]]},
            "items": {
                "type": "array",
                "items": item_schema,
                "minItems": len(batch["items"]),
                "maxItems": len(batch["items"]),
            },
        },
        "additionalProperties": False,
    }


def execute_evidence_diagnostics(
    payload: dict[str, Any],
    normalized_turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return direct-evidence blockers without guessing unsupported behavior."""
    diagnostics = [
        diagnostic for turn in normalized_turns for diagnostic in turn["diagnostics"]
    ]
    if any(turn["status"] != "completed" for turn in normalized_turns):
        diagnostics.append(
            {
                "kind": "malformed_record",
                "index": None,
                "message": "Codex turn did not reach a completed terminal",
            }
        )
    slots = payload.get("execution_context", {}).get("expected_principal_slots")
    collaboration_observed = any(
        item["type"] == "collab_tool_call"
        for turn in normalized_turns
        for item in turn["items"]
    )
    if collaboration_observed:
        unsupported = (
            "Codex stream contains collab tool calls outside the single-principal contract"
        )
    else:
        unsupported = (
            "Codex JSONL lacks direct principal and handoff evidence"
            if payload.get("coordination") is not None
            else "single-principal Codex adapter requires one plan slot"
            if not isinstance(slots, list) or len(slots) != 1
            else "Codex adapter does not inject scenario faults"
            if payload.get("fault_script")
            else "execute case payload is missing"
            if not isinstance(payload.get("case"), dict)
            else "Codex JSONL lacks bound state snapshot evidence"
            if payload["case"].get("state_model", {}).get("scope") != "none"
            else "Codex JSONL lacks complete authorization and effect traces"
            if payload.get("execution_context", {}).get("expected_tools")
            else None
        )
    if unsupported is not None:
        diagnostics.append(
            {"kind": "malformed_record", "index": None, "message": unsupported}
        )
    routing_contract = payload.get("case", {}).get("routing_contract")
    if routing_contract is not None and any(
        turn["routing"] is None for turn in normalized_turns
    ):
        diagnostics.append(
            {
                "kind": "malformed_record",
                "index": None,
                "message": "Codex stream lacks direct routing evidence required by the case",
            }
        )
    return diagnostics


def _principal_record(
    payload: dict[str, Any],
    manifest: dict[str, Any],
    session_id: str,
    started_at: str,
    ended_at: str,
    completed_turns: int,
    status: str,
) -> dict[str, Any]:
    execution = manifest["identity"]["execution"]
    slots = payload["execution_context"]["expected_principal_slots"]
    if len(slots) != 1:
        raise ValueError("single-principal Codex adapter requires one plan slot")
    requested_budget = {
        "turns": len(payload["turns"]),
        "tokens": 0,
        "seconds": payload["case"]["timeout_seconds"],
        "tool_calls": 0,
    }
    slot_id = slots[0]
    return {
        "principal_id": f"principal-{slot_id}",
        "slot_id": slot_id,
        "parent_principal_id": None,
        "role": "lead",
        "provider": execution["provider"],
        "model": execution["model"],
        "model_revision": execution["model_revision"],
        "session_id": session_id,
        "worktree_id": manifest["identity"]["repository"]["tree"],
        "sandbox_id": f"sandbox-{session_id}",
        "context_mode": "single",
        "inherited_context_hash": None,
        "untrusted_input_hash": None,
        "prompt_hash": execution["prompt_hash"],
        "skill_hash": execution["skill_hash"],
        "catalog_hash": execution["catalog_hash"],
        "tool_schema_hash": execution["tool_schema_hash"],
        "policy_hash": execution["policy_hash"],
        "authority_hash": payload["permission_policy"],
        "requested_budget": requested_budget,
        "effective_budget": {
            **requested_budget,
            "turns": completed_turns,
            "seconds": 0,
        },
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "span_id": f"span-{slot_id}",
        "parent_span_id": None,
    }


def project_execute_result(
    *,
    request: dict[str, Any],
    manifest: dict[str, Any],
    normalized_turns: list[dict[str, Any]],
    session_id: str,
    started_at: str,
    ended_at: str,
    artifacts: list[dict[str, str]],
    assertions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Project completed Codex turns onto Host events and one terminal result."""
    payload = request["payload"]
    events: list[dict[str, Any]] = []
    checkpoints: list[dict[str, Any]] = []
    principal_id = (
        f"principal-{payload['execution_context']['expected_principal_slots'][0]}"
    )
    for seq, (turn, normalized) in enumerate(
        zip(payload["turns"], normalized_turns, strict=True)
    ):
        checkpoint = {
            "checkpoint_id": f"{turn['checkpoint']}-{seq}",
            "turn_id": turn["turn_id"],
            "seq": seq,
            "state_artifact": None,
        }
        checkpoints.append(checkpoint)
        event_payload: dict[str, Any] = {
            "obligations": {
                "open": list(turn["open_obligations"]),
                "due": list(turn["due_obligations"]),
            },
            "codex": {
                "event_types": normalized["event_types"],
                "permission_denials": normalized["permission_denials"],
                "failures": normalized["failures"],
                "tool_call_ids": normalized["tool_call_ids"],
                "usage": normalized["usage"],
            },
        }
        if normalized["routing"] is not None:
            event_payload["routing"] = normalized["routing"]
        events.append(
            {
                "record_type": "skill-evaluator-host-event/1",
                "seq": seq,
                "parent_seq": seq - 1 if seq else None,
                "principal_id": principal_id,
                "event_type": (
                    "codex_turn_completed"
                    if normalized["status"] == "completed"
                    else "codex_turn_failed"
                ),
                "turn_id": turn["turn_id"],
                "checkpoint": checkpoint,
                "payload": event_payload,
                "artifact_locator": None,
                "action": None,
            }
        )
    complete = len(normalized_turns) == len(payload["turns"]) and all(
        turn["status"] == "completed" for turn in normalized_turns
    )
    status = "completed" if complete else "failed"
    result = base_host_result(request, manifest)
    result.update(
        {
            "terminal_status": status,
            "treatment_error": None if complete else "Codex turn failed",
            "principals": [
                _principal_record(
                    payload,
                    manifest,
                    session_id,
                    started_at,
                    ended_at,
                    len(normalized_turns),
                    status,
                )
            ],
            "artifacts": artifacts,
            "state": checkpoints,
            "assertions": assertions,
        }
    )
    return events, result
