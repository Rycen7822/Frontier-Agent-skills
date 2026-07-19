#!/usr/bin/env python3
"""Reconcile workflow state with source, plan, artifacts, locks, and events."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, load_json, load_json_lines
from propagate_invalidation import propagate_invalidation
from validate_workflow_state import validate_event_stream


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_SCHEMA = ROOT / "schemas" / "workflow-event.schema.json"


def _now(value: str | None) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else datetime.now(timezone.utc)


def _artifact_path(workflow_root: Path, artifact_ref: str) -> Path | None:
    raw = Path(artifact_ref)
    if raw.is_absolute():
        return None
    if raw.parts and raw.parts[0] == ".workflow":
        raw = Path(*raw.parts[1:])
    candidate = (workflow_root / raw).resolve()
    root = workflow_root.resolve()
    return candidate if candidate.is_relative_to(root) else None


def reconcile(
    state: dict[str, Any],
    *,
    current_revision: str | None = None,
    current_scope_hash: str | None = None,
    current_plan_hash: str | None = None,
    workflow_root: Path | None = None,
    verify_artifacts: bool = True,
    events: list[dict[str, Any]] | None = None,
    event_schema: dict[str, Any] | None = None,
    locks: dict[str, Any] | None = None,
    todo_snapshot: dict[str, str] | None = None,
    now_value: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    changed: set[str] = set()
    flags: set[str] = set()

    def add(ref: str, kind: str, message: str, *, escalation: str | None = None) -> None:
        issues.append({"ref": ref, "kind": kind, "message": message})
        changed.add(ref)
        if escalation:
            flags.add(escalation)

    source = state.get("source", {})
    if current_revision and source.get("observed_revision") != current_revision:
        add("source", "source_revision_drift", f"observed {source.get('observed_revision')} != current {current_revision}")
    if current_scope_hash and source.get("scope_hash") != current_scope_hash:
        add("scope", "scope_hash_drift", "current scope hash differs from workflow")
    if current_plan_hash and state.get("plan_ref", {}).get("content_hash") != current_plan_hash:
        add("plan", "plan_hash_drift", "current plan hash differs from workflow")

    if verify_artifacts:
        if workflow_root is None:
            raise ValueError("workflow_root is required when verify_artifacts is true")
        for artifact in state.get("artifacts", []):
            ref = artifact["id"]
            path = _artifact_path(workflow_root, artifact.get("artifact_ref", ""))
            if path is None:
                add(ref, "artifact_pointer_unsafe", "artifact pointer is outside workflow root", escalation="unmodeled_artifact_state")
            elif not path.is_file():
                add(ref, "artifact_missing", f"artifact does not exist: {path}")
            else:
                observed = "sha256:" + sha256(path.read_bytes()).hexdigest()
                if artifact.get("content_hash") != observed:
                    add(ref, "artifact_content_changed", f"content hash differs for {path}")

    now = _now(now_value)
    for lock in (locks or {}).get("leases", []):
        expires = datetime.fromisoformat(lock["lease_expires_at"].replace("Z", "+00:00"))
        if expires <= now:
            add(lock["lease_id"], "lock_expired", f"lease expired for {lock['producer_id']}", escalation="expired_lock_requires_reconciliation")
    if state.get("pending_background"):
        add("workflow-background", "background_pending", f"pending runs: {state['pending_background']}", escalation="pending_background_work")

    if events is not None:
        if event_schema is None:
            raise ValueError("event_schema is required when events are supplied")
        for violation in validate_event_stream(events, event_schema):
            issues.append({"ref": violation.object_id or "events", "kind": violation.code, "message": violation.message})
            changed.add("events")
            flags.add("event_stream_invalid")
        if any(event.get("workflow_id") != state.get("workflow_id") for event in events):
            add("events", "event_owner_mismatch", "event stream belongs to another workflow", escalation="event_stream_invalid")
        if any(not isinstance(event.get("state_version"), int) or event["state_version"] > state.get("state_version", 0) for event in events):
            add("events", "event_future_state", "event stream references an uncommitted state version", escalation="event_stream_invalid")

    if todo_snapshot is not None:
        if not isinstance(todo_snapshot, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in todo_snapshot.items()):
            raise ValueError("todo_snapshot must map node IDs to status strings")
        nodes = {item["id"]: item for item in state.get("nodes", [])}
        expected_status = {
            "pending": "pending", "ready": "pending", "failed": "pending", "invalidated": "pending",
            "running": "in_progress", "blocked": "blocked",
            "done": "completed", "skipped": "completed", "superseded": "completed", "cancelled": "completed",
        }
        for node_id, node in nodes.items():
            expected = expected_status.get(node.get("status"))
            if node_id not in todo_snapshot and node.get("status") in {"pending", "ready", "running", "blocked", "failed", "invalidated"}:
                add(node_id, "todo_missing_live_node", "live session todo is missing a current workflow node")
            elif node_id in todo_snapshot and expected != todo_snapshot[node_id]:
                add(node_id, "todo_status_drift", f"todo={todo_snapshot[node_id]} workflow={node.get('status')}")
        for todo_id in sorted(set(todo_snapshot) - set(nodes)):
            add(todo_id, "todo_orphan", "live todo has no canonical workflow node")

    repair = propagate_invalidation(state, changed, escalation_flags=flags)
    blocking_kinds = {
        "lock_expired", "background_pending", "workflow.event-schema", "workflow.event-order", "workflow.event-version", "event_owner_mismatch", "event_future_state",
        "source_revision_drift", "scope_hash_drift", "plan_hash_drift", "artifact_pointer_unsafe",
    }
    resume_allowed = not issues or (repair["repair_type"] == "local" and not any(item["kind"] in blocking_kinds for item in issues))
    resume_actions = ["start_new_source_epoch"] if any(item["kind"] in {"source_revision_drift", "scope_hash_drift", "plan_hash_drift"} for item in issues) else []
    return {
        "workflow_id": state.get("workflow_id"),
        "state_version": state.get("state_version"),
        "status": "fresh" if not issues else ("blocked" if not resume_allowed else "repair_required"),
        "resume_allowed": resume_allowed,
        "issues": issues,
        "repair": repair,
        "resume_actions": resume_actions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--current-revision")
    parser.add_argument("--current-scope-hash")
    parser.add_argument("--current-plan-hash")
    parser.add_argument("--events", type=Path)
    parser.add_argument("--locks", type=Path)
    parser.add_argument("--todo", type=Path, help="optional live todo node-status mapping")
    parser.add_argument("--event-schema", type=Path, default=DEFAULT_EVENT_SCHEMA)
    parser.add_argument("--now")
    parser.add_argument("--skip-artifacts", action="store_true")
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        events = load_json_lines(args.events) if args.events else None
        locks = load_json(args.locks) if args.locks else None
        event_schema = load_json(args.event_schema) if events is not None else None
        todo_snapshot = load_json(args.todo) if args.todo else None
        result = reconcile(
            state,
            current_revision=args.current_revision,
            current_scope_hash=args.current_scope_hash,
            current_plan_hash=args.current_plan_hash,
            workflow_root=args.workflow_root,
            verify_artifacts=not args.skip_artifacts,
            events=events,
            event_schema=event_schema,
            locks=locks,
            todo_snapshot=todo_snapshot,
            now_value=args.now,
        )
    except (InputError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"ok": result["status"] == "fresh", **result}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "fresh" else 1


if __name__ == "__main__":
    sys.exit(main())
