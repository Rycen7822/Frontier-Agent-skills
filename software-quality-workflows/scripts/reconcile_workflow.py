#!/usr/bin/env python3
"""Reconcile workflow state with source, plan, artifacts, locks, and events."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from _workflow_state import InputError, load_json, load_json_lines
from propagate_invalidation import propagate_invalidation
from validate_workflow_state import validate_event_stream


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_SCHEMA = ROOT / "schemas" / "workflow-event.schema.json"
MAX_RUNTIME_ENTRIES = 1000


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
    if not candidate.is_relative_to(root):
        return None
    return candidate


def _runtime_directory(path: Path) -> tuple[list[Path], str | None]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        return [], str(exc)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return [], "path is not a safe regular directory"
    try:
        entries = list(path.iterdir())
    except OSError as exc:
        return [], str(exc)
    if len(entries) > MAX_RUNTIME_ENTRIES:
        return [], f"directory exceeds {MAX_RUNTIME_ENTRIES} entries"
    return entries, None


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
    for lock in state.get("locks", []):
        expires = datetime.fromisoformat(lock["lease_expires_at"].replace("Z", "+00:00"))
        if expires <= now:
            add(lock["id"], "lock_expired", f"lease expired for {lock['resource']}", escalation="expired_lock_requires_reconciliation")
    if state.get("pending_background"):
        add("workflow-background", "background_pending", f"pending runs: {state['pending_background']}", escalation="pending_background_work")

    if events is not None:
        if event_schema is None:
            raise ValueError("event_schema is required when events are supplied")
        for violation in validate_event_stream(events, event_schema):
            issues.append({"ref": violation.object_id or "events", "kind": violation.code, "message": violation.message})
            changed.add("events")
            flags.add("event_stream_invalid")
        if events and events[-1].get("state_version") != state.get("state_version"):
            issues.append({"ref": "events", "kind": "state_event_projection_drift", "message": f"latest event state_version {events[-1].get('state_version')} != state {state.get('state_version')}"})
            changed.add("events")
            flags.add("state_event_projection_drift")

    resume_actions: set[str] = set()
    if workflow_root is not None and state.get("execution_policy") == "autonomous_closure":
        pending = workflow_root / ".advance-pending.json"
        if os.path.lexists(pending):
            try:
                if not stat.S_ISREG(pending.lstat().st_mode) or pending.is_symlink():
                    raise ValueError("pending journal is not a safe regular file")
                journal = load_json(pending)
                if not isinstance(journal, dict) or journal.get("workflow_id") not in {None, state.get("workflow_id")}:
                    raise ValueError("pending journal workflow identity mismatch")
                add("closure-pending", "pending_closure_transition", "advance_closure transaction journal requires deterministic replay", escalation="pending_closure_transition")
                resume_actions.add("replay_pending_advance")
            except (OSError, ValueError) as exc:
                add("closure-pending", "pending_closure_transition_invalid", str(exc), escalation="pending_closure_transition")
                resume_actions.add("quarantine_invalid_pending_advance")

        worktree_entries, worktree_error = _runtime_directory(workflow_root / "worktrees")
        metadata_entries, metadata_error = _runtime_directory(workflow_root / "worktree-metadata")
        if worktree_error:
            add("worktrees", "runtime_surface_unsafe", worktree_error, escalation="orphan_runtime_state")
        if metadata_error:
            add("worktree-metadata", "runtime_surface_unsafe", metadata_error, escalation="orphan_runtime_state")
        worktree_ids: set[str] = set()
        for entry in worktree_entries:
            try:
                mode = entry.lstat().st_mode
            except OSError as exc:
                add(entry.name, "worktree_unsafe", str(exc), escalation="orphan_runtime_state")
                continue
            if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
                worktree_ids.add(entry.name)
            else:
                add(entry.name, "worktree_unsafe", "managed worktree entry is not a safe directory", escalation="orphan_runtime_state")
        metadata_ids: set[str] = set()
        metadata_kinds: dict[str, str] = {}
        archived_ids: set[str] = set()
        for entry in metadata_entries:
            name = entry.name
            if name.endswith(".archive.json"):
                identifier = name.removesuffix(".archive.json")
                try:
                    if not stat.S_ISREG(entry.lstat().st_mode) or entry.is_symlink():
                        raise ValueError("archive record is not a safe regular file")
                    archive_record = load_json(entry)
                    if not isinstance(archive_record, dict) or set(archive_record) != {"candidate_id", "snapshot_hash", "archive_artifact"} or archive_record.get("candidate_id") != identifier:
                        raise ValueError("archive record identity or shape is invalid")
                    archived_ids.add(identifier)
                except (OSError, ValueError) as exc:
                    add(identifier, "archive_record_invalid", str(exc), escalation="orphan_runtime_state")
                continue
            if not name.endswith(".json"):
                add(name, "worktree_metadata_invalid", "unexpected worktree metadata filename", escalation="orphan_runtime_state")
                continue
            identifier = name.removesuffix(".json")
            try:
                if not stat.S_ISREG(entry.lstat().st_mode) or entry.is_symlink():
                    raise ValueError("metadata is not a safe regular file")
                metadata = load_json(entry)
                required_metadata = {
                    "schema_version", "kind", "identifier", "workflow_id", "base_revision", "writer_id",
                    "worktree_path", "allowed_write_paths", "protected_paths", "view_hashes",
                }
                if not isinstance(metadata, dict) or set(metadata) != required_metadata or metadata.get("identifier") != identifier:
                    raise ValueError("metadata identity differs from filename")
                metadata_ids.add(identifier)
                metadata_kinds[identifier] = metadata.get("kind")
            except (OSError, ValueError) as exc:
                add(identifier, "worktree_metadata_invalid", str(exc), escalation="orphan_runtime_state")
        for identifier in sorted(worktree_ids - metadata_ids):
            add(identifier, "orphan_worktree", "worktree has no controller-owned metadata", escalation="orphan_runtime_state")
            resume_actions.add("reconcile_or_archive_orphan_worktree")
        for identifier in sorted(metadata_ids - worktree_ids - archived_ids):
            add(identifier, "worktree_missing", "active worktree metadata points to no worktree", escalation="orphan_runtime_state")
            resume_actions.add("repair_or_abort_missing_worktree")
        for identifier in sorted(archived_ids - metadata_ids):
            add(identifier, "archive_record_orphan", "archive record has no immutable worktree metadata", escalation="orphan_runtime_state")
            resume_actions.add("quarantine_orphan_archive_record")
        for identifier in sorted(worktree_ids & metadata_ids):
            if metadata_kinds.get(identifier) != "integration":
                continue
            artifact_path = workflow_root / "integration" / f"{identifier}.json"
            try:
                if not stat.S_ISREG(artifact_path.lstat().st_mode) or artifact_path.is_symlink():
                    raise ValueError("integration artifact is not a safe regular file")
                artifact = load_json(artifact_path)
                if not isinstance(artifact, dict) or artifact.get("artifact_id") != identifier:
                    raise ValueError("integration artifact identity mismatch")
            except FileNotFoundError:
                add(identifier, "integration_incomplete", "integration worktree has no validated reproduction artifact", escalation="orphan_runtime_state")
                resume_actions.add("replay_or_remove_incomplete_integration")
            except (OSError, ValueError) as exc:
                add(identifier, "integration_artifact_invalid", str(exc), escalation="orphan_runtime_state")
                resume_actions.add("quarantine_invalid_integration")

        task_entries, task_error = _runtime_directory(workflow_root / "tasks")
        if task_error:
            add("tasks", "runtime_surface_unsafe", task_error, escalation="orphan_runtime_state")
        task_ids: set[str] = set()
        result_ids: set[str] = set()
        for entry in task_entries:
            suffix = ".task.json" if entry.name.endswith(".task.json") else (".result.json" if entry.name.endswith(".result.json") else None)
            if suffix is None:
                continue
            identifier = entry.name.removesuffix(suffix)
            try:
                if not stat.S_ISREG(entry.lstat().st_mode) or entry.is_symlink():
                    raise ValueError("task record is not a safe regular file")
                payload = load_json(entry)
                if not isinstance(payload, dict) or payload.get("task_id") != identifier:
                    raise ValueError("task record identity differs from filename")
                (task_ids if suffix == ".task.json" else result_ids).add(identifier)
            except (OSError, ValueError) as exc:
                add(identifier, "task_record_invalid", str(exc), escalation="orphan_runtime_state")
        for identifier in sorted(task_ids - result_ids):
            add(identifier, "task_pending", "task envelope has no structured result", escalation="orphan_runtime_state")
            resume_actions.add("inspect_or_cancel_pending_task")
        for identifier in sorted(result_ids - task_ids):
            add(identifier, "task_result_orphan", "structured result has no task envelope", escalation="orphan_runtime_state")
            resume_actions.add("quarantine_orphan_task_result")

    if any(item["kind"] in {"source_revision_drift", "scope_hash_drift", "plan_hash_drift"} for item in issues):
        resume_actions.add("start_new_source_epoch")

    if todo_snapshot is not None:
        if not isinstance(todo_snapshot, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in todo_snapshot.items()):
            raise ValueError("todo_snapshot must be an object mapping node IDs to status strings")
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
        "lock_expired", "background_pending", "workflow.event-schema", "workflow.event-order", "workflow.event-version",
        "source_revision_drift", "scope_hash_drift", "plan_hash_drift", "pending_closure_transition",
        "pending_closure_transition_invalid", "orphan_worktree", "worktree_missing", "worktree_unsafe",
        "worktree_metadata_invalid", "archive_record_invalid", "archive_record_orphan", "runtime_surface_unsafe",
        "integration_incomplete", "integration_artifact_invalid", "task_pending", "task_result_orphan", "task_record_invalid",
    }
    resume_allowed = not issues or (repair["repair_type"] == "local" and not any(item["kind"] in blocking_kinds for item in issues))
    return {
        "workflow_id": state.get("workflow_id"),
        "state_version": state.get("state_version"),
        "status": "fresh" if not issues else ("blocked" if not resume_allowed else "repair_required"),
        "resume_allowed": resume_allowed,
        "issues": issues,
        "repair": repair,
        "resume_actions": sorted(resume_actions),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--workflow-root", type=Path)
    parser.add_argument("--current-revision")
    parser.add_argument("--current-scope-hash")
    parser.add_argument("--current-plan-hash")
    parser.add_argument("--events", type=Path)
    parser.add_argument("--todo", type=Path, help="optional live todo node-status mapping")
    parser.add_argument("--event-schema", type=Path, default=DEFAULT_EVENT_SCHEMA)
    parser.add_argument("--now")
    parser.add_argument("--skip-artifacts", action="store_true")
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        events = load_json_lines(args.events) if args.events else None
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
