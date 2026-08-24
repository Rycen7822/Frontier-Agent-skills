"""Explicit lifecycle classification for Codex child JSONL streams.

The legacy Host path remains the owner of historical behavior.  This module is
opted into by a versioned Host command binding and never invents command
completion, exit codes, output, or external effects.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from _codex_eval_events import normalize_jsonl


LEGACY_CONTRACT = "codex-child-lifecycle/legacy"
V2_CONTRACT = "codex-child-lifecycle/2"
SUPPORTED_CONTRACTS = frozenset({LEGACY_CONTRACT, V2_CONTRACT})


class LifecycleContractError(ValueError):
    """The explicit lifecycle contract cannot establish a safe classification."""


def _records(raw: bytes) -> list[dict[str, Any]]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise LifecycleContractError("child JSONL is not UTF-8") from exc
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line:
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise LifecycleContractError("child JSONL record is not an object")
        records.append(value)
    return records


def _item_lifecycles(records: list[dict[str, Any]]) -> tuple[dict[str, str], dict[str, str], list[dict[str, Any]]]:
    started: dict[str, str] = {}
    completed: dict[str, str] = {}
    for record in records:
        record_type = record.get("type")
        item = record.get("item")
        if record_type not in {"item.started", "item.updated", "item.completed"}:
            continue
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("type"), str):
            continue
        item_id = item["id"]
        item_type = item["type"]
        if record_type == "item.started":
            started[item_id] = item_type
        elif record_type == "item.completed":
            completed[item_id] = item_type
    incomplete = []
    for item_id, item_type in started.items():
        if item_id in completed:
            continue
        item = {"id": item_id, "type": item_type}
        for record in records:
            candidate = record.get("item")
            if record.get("type") == "item.started" and isinstance(candidate, dict) and candidate.get("id") == item_id:
                if isinstance(candidate.get("command"), str):
                    item["command"] = candidate["command"]
                if isinstance(candidate.get("status"), str):
                    item["status"] = candidate["status"]
                break
        incomplete.append(item)
    return started, completed, incomplete


def _diagnostic_only_incomplete(normalized: dict[str, Any]) -> bool:
    diagnostics = normalized.get("diagnostics")
    if not isinstance(diagnostics, list) or not diagnostics:
        return False
    return all(
        isinstance(item, dict)
        and (
            (
                item.get("kind") == "item_lifecycle"
                and "incomplete items:" in str(item.get("message", ""))
            )
            or (
                item.get("kind") == "missing_terminal"
                and "lacks a turn terminal" in str(item.get("message", ""))
            )
        )
        for item in diagnostics
    )


def _custody_closed(custody: Mapping[str, Any] | None) -> bool:
    if not isinstance(custody, Mapping):
        return False
    required = (
        "process_exited",
        "workspace_clean",
        "isolation_clean",
        "effects_captured",
    )
    return (
        all(custody.get(field) is True for field in required)
        and custody.get("live_process") is False
        and custody.get("timed_out") is False
    )


def _usage_present(normalized: dict[str, Any]) -> bool:
    usage = normalized.get("usage")
    return isinstance(usage, dict) and bool(usage)


def _final_message_present(normalized: dict[str, Any]) -> bool:
    value = normalized.get("final_message")
    return isinstance(value, str) and bool(value)


def _completion_evidence(
    incomplete: list[dict[str, Any]],
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if evidence is None:
        return None
    if not isinstance(evidence, Mapping):
        raise LifecycleContractError("completion evidence must be an object")
    bound: list[dict[str, Any]] = []
    expected_ids = [item["id"] for item in incomplete]
    if set(evidence) != set(expected_ids):
        raise LifecycleContractError("completion evidence does not cover exactly the incomplete items")
    for item in incomplete:
        item_id = item["id"]
        record = evidence.get(item_id)
        if not isinstance(record, Mapping) or set(record) != {"item_id", "exit_code", "output_digest"}:
            raise LifecycleContractError("completion evidence record shape is invalid")
        if record["item_id"] != item_id or isinstance(record["exit_code"], bool) or not isinstance(record["exit_code"], int):
            raise LifecycleContractError("completion evidence item identity or exit code is invalid")
        digest = record["output_digest"]
        if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:"):
            raise LifecycleContractError("completion evidence output digest is invalid")
        try:
            int(digest[7:], 16)
        except ValueError as exc:
            raise LifecycleContractError("completion evidence output digest is invalid") from exc
        bound.append(dict(record))
    return {"status": "reconciled", "items": bound}


def classify_lifecycle(
    raw: bytes,
    *,
    contract_version: str,
    custody: Mapping[str, Any] | None = None,
    completion_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one child stream without inferring hidden command behavior."""
    if contract_version not in SUPPORTED_CONTRACTS:
        raise LifecycleContractError(f"unsupported lifecycle contract {contract_version!r}")
    if contract_version == LEGACY_CONTRACT:
        return {"contract_version": LEGACY_CONTRACT, "branch": "legacy"}

    records = _records(raw)
    normalized = normalize_jsonl(raw)
    _, _, incomplete = _item_lifecycles(records)
    incomplete_types = {item["type"] for item in incomplete}
    turn_completed = "turn.completed" in normalized.get("event_types", [])
    final_message = _final_message_present(normalized)
    usage = _usage_present(normalized)
    completion = _completion_evidence(incomplete, completion_evidence)
    custody_ok = _custody_closed(custody)
    common = {
        "contract_version": V2_CONTRACT,
        "incomplete_items": incomplete,
        "turn_completed": turn_completed,
        "final_message_present": final_message,
        "usage_present": usage,
        "custody_closed": custody_ok,
        "retryable": False,
        "reserve_consumption": False,
        "sample_valid": False,
        "process_gate": {"status": "fail", "reason": "lifecycle evidence is not closed"},
    }
    only_commands = bool(incomplete) and incomplete_types == {"command_execution"}
    diagnostics_only = _diagnostic_only_incomplete(normalized)

    if not incomplete and normalized.get("status") == "completed" and turn_completed and final_message and usage:
        return common | {
            "branch": "complete",
            "sample_valid": True,
            "process_gate": {"status": "pass", "reason": "complete lifecycle"},
        }

    if only_commands and diagnostics_only and completion is not None and custody_ok and turn_completed and final_message and usage:
        return common | {
            "branch": "reconciled_complete",
            "completion_evidence": completion,
            "sample_valid": True,
            "process_gate": {"status": "pass", "reason": "every incomplete item has byte-bound completion evidence"},
        }

    if only_commands and diagnostics_only and not turn_completed and not final_message and not usage:
        if not custody_ok:
            return common | {
                "branch": "outcome_free_transient_pending_custody",
                "retryable": True,
                "reserve_consumption": True,
            }
        return common | {
            "branch": "outcome_free_transient",
            "retryable": True,
            "reserve_consumption": True,
            "process_gate": {"status": "not_applicable", "reason": "no completed turn, final message, or usage"},
        }

    if only_commands and diagnostics_only and turn_completed and final_message and usage and completion is None:
        if not custody_ok:
            return common | {
                "branch": "outcome_bearing_abandoned_pending_custody",
                "sample_valid": True,
                "unknown_completion": [item["id"] for item in incomplete],
            }
        return common | {
            "branch": "outcome_bearing_abandoned",
            "sample_valid": True,
            "process_gate": {"status": "fail", "reason": "command completion, exit code, and output remain unknown"},
            "unknown_completion": [item["id"] for item in incomplete],
        }

    return common | {
        "branch": "unknown_mixed_or_uncustodied",
        "reason": "required lifecycle evidence or custody is missing, mixed, or inconsistent",
    }


def digest_projection(value: Mapping[str, Any]) -> str:
    """Return a stable digest for machine-readable diagnostic projection."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
