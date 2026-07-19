#!/usr/bin/env python3
"""SQW v3 durable-owner bootstrap and operator-only audit appends."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Iterator

try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows host
    fcntl = None
try:
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - POSIX host
    msvcrt = None

from _workflow_state import load_json
from validate_workflow_state import validate_event_stream, validate_state


class AdapterConflict(RuntimeError):
    pass


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _compact_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _value_hash(value: Any) -> str:
    return "sha256:" + sha256(_compact_bytes(value)).hexdigest()


def _optional_lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _safe_regular_bytes(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise AdapterConflict("workflow owner contains an unsafe file") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink not in {1, 2}:
            raise AdapterConflict("workflow owner contains an unsafe file")
        payload = bytearray()
        while len(payload) <= 2 * 1024 * 1024:
            chunk = os.read(descriptor, min(65_536, 2 * 1024 * 1024 + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(payload) > 2 * 1024 * 1024 or any(getattr(before, key) != getattr(after, key) for key in stable):
            raise AdapterConflict("workflow owner file is unstable")
        return bytes(payload), before
    finally:
        os.close(descriptor)


def _publish_bootstrap_file(root: Path, final_name: str, temp_name: str, payload: bytes) -> None:
    final = root / final_name
    temporary = root / temp_name
    final_info = _optional_lstat(final)
    temp_info = _optional_lstat(temporary)
    if final_info is not None:
        final_bytes, final_stat = _safe_regular_bytes(final)
        if final_bytes != payload or stat.S_IMODE(final_stat.st_mode) != 0o600:
            raise AdapterConflict("workflow bootstrap final conflicts")
        if temp_info is None:
            return
        temp_bytes, temp_stat = _safe_regular_bytes(temporary)
        if temp_bytes != payload or (final_stat.st_dev, final_stat.st_ino) != (temp_stat.st_dev, temp_stat.st_ino):
            raise AdapterConflict("workflow bootstrap temp conflicts")
        temporary.unlink()
        _sync_directory(root)
        return
    if temp_info is not None:
        temp_bytes, temp_stat = _safe_regular_bytes(temporary)
        if temp_bytes != payload or stat.S_IMODE(temp_stat.st_mode) != 0o600 or temp_stat.st_nlink != 1:
            raise AdapterConflict("workflow bootstrap temp conflicts")
    else:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.link(temporary, final, follow_symlinks=False)
    _sync_directory(root)
    temporary.unlink()
    _sync_directory(root)


def _validate_v3_root(root: Path, source_root: Path) -> tuple[Path, dict[str, int]]:
    try:
        info = root.lstat()
        resolved = root.resolve(strict=True)
        source = source_root.resolve(strict=True)
    except OSError as exc:
        raise AdapterConflict("workflow root is unavailable") from exc
    if (
        root.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or resolved != root.absolute()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
        or resolved == source
        or resolved.is_relative_to(source)
        or source.is_relative_to(resolved)
    ):
        raise AdapterConflict("workflow root is unsafe")
    return resolved, {"dev": info.st_dev, "ino": info.st_ino, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)}


def bootstrap_v3(
    root: Path,
    source_root: Path,
    *,
    bundle_id: str,
    policy_bundle_hash: str,
    card_manifest_hash: str,
    mode: str,
    request_mode: str,
    entry_completion: dict[str, Any],
    scope_completion: dict[str, Any],
    scope_binding: dict[str, Any],
    source_identity: dict[str, Any],
    next_step: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create or replay the v3 M2/M3 owner bootstrap without creating the root."""
    if mode not in {"M2", "M3"}:
        raise AdapterConflict("durable workflow mode must be M2 or M3")
    resolved, initial_root_binding = _validate_v3_root(root, source_root)
    initial_root_binding_hash = _value_hash(initial_root_binding)
    bootstrap_semantics = {
        "bundle_id": bundle_id,
        "policy_bundle_hash": policy_bundle_hash,
        "card_manifest_hash": card_manifest_hash,
        "mode": mode,
        "request_mode": request_mode,
        "entry_completion_id": entry_completion["content_hash"],
        "scope_binding_id": scope_binding["binding_id"],
        "source_identity": source_identity,
        "initial_root_binding": initial_root_binding,
    }
    bootstrap_operation_id = _value_hash(bootstrap_semantics)
    workflow_id = "sqw-workflow:" + bootstrap_operation_id.removeprefix("sha256:")
    locator = {
        "schema_version": "sqw-workflow-owner/1",
        "workflow_id": workflow_id,
        "bootstrap_operation_id": bootstrap_operation_id,
        "bundle_id": bundle_id,
        "initial_source_identity_hash": source_identity["identity_hash"],
        "scope_binding_id": scope_binding["binding_id"],
        "mode": mode,
        "initial_root_binding_hash": initial_root_binding_hash,
    }
    lock_header = {
        "schema_version": "sqw-lock/1",
        "workflow_id": workflow_id,
        "bootstrap_operation_id": bootstrap_operation_id,
        "initial_root_binding_hash": initial_root_binding_hash,
        "established_root_identity_hash": initial_root_binding_hash,
        "scope_binding_id": scope_binding["binding_id"],
        "mode": mode,
    }
    lease = {
        "lease_id": _value_hash({"workflow_id": workflow_id, "frontier": next_step}),
        "producer_id": next_step["card_id"],
        "decision_id": next_step["decision_id"],
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    locks = {
        "schema_version": "sqw-locks/1",
        "workflow_id": workflow_id,
        "bootstrap_operation_id": bootstrap_operation_id,
        "scope_binding_id": scope_binding["binding_id"],
        "leases": [lease],
    }
    state_without_hash = {
        "schema_version": "3.0",
        "workflow_id": workflow_id,
        "bundle_id": bundle_id,
        "policy_bundle_hash": policy_bundle_hash,
        "card_manifest_hash": card_manifest_hash,
        "mode": mode,
        "request_mode": request_mode,
        "status": "active",
        "bootstrap": {
            "operation_id": bootstrap_operation_id,
            "entry_completion_id": entry_completion["content_hash"],
            "initial_root_binding": initial_root_binding,
            "established_root_identity": initial_root_binding,
        },
        "scope_binding": scope_binding,
        "source_identity": source_identity,
        "source": {
            "repository": "unversioned",
            "base_revision": source_identity["identity_hash"],
            "observed_revision": source_identity["identity_hash"],
            "scope_hash": scope_binding["binding_id"],
        },
        "authority": {
            "risk_ceiling": "local_reversible",
            "external_writes": "forbidden",
            "destructive_actions": "forbidden",
            "approvals": [],
        },
        "scope": {
            "allowed_reads": scope_binding["allowed_reads"],
            "allowed_writes": scope_binding["allowed_writes"],
            "protected_paths": [],
            "coverage": "affected",
        },
        "global_invariants": [],
        "active_owners": {"primary": "card-cycle", "normative": [], "companions": []},
        "nodes": [],
        "verifiers": [],
        "edges": [],
        "frontier": [],
        "active_frontier": next_step,
        "card_completions": [
            {"storage": "inline", "operation_id": entry_completion["content_hash"], "completion": entry_completion},
            {"storage": "inline", "operation_id": scope_completion["content_hash"], "completion": scope_completion},
        ],
        "artifacts": [],
        "recent_failures": [],
        "pending_background": [],
        "state_version": 1,
        "last_transition": {
            "transition_kind": "bootstrap",
            "operation_id": bootstrap_operation_id,
            "prior_state_version": 0,
            "prior_state_hash": None,
            "completion_id": scope_completion["content_hash"],
            "next_decision_id": next_step["decision_id"],
        },
    }
    state = {**state_without_hash, "state_hash": _value_hash(state_without_hash)}
    lock_bytes = _compact_bytes(lock_header) + b"\n"
    locks_bytes = _compact_bytes(locks) + b"\n"
    state_bytes = _compact_bytes(state) + b"\n"

    names = {path.name for path in resolved.iterdir()}
    steady_names = {".adapter.lock", "state.json", "locks.json", "artifacts", "projections"}
    if names:
        if names != steady_names:
            raise AdapterConflict("workflow root contains foreign or interrupted state")
        observed_lock, _ = _safe_regular_bytes(resolved / ".adapter.lock")
        observed_state, _ = _safe_regular_bytes(resolved / "state.json")
        observed_locks_bytes, _ = _safe_regular_bytes(resolved / "locks.json")
        try:
            observed_locks = json.loads(observed_locks_bytes)
        except json.JSONDecodeError as exc:
            raise AdapterConflict("workflow locks are invalid") from exc
        expected_lock_fields = {key: value for key, value in locks.items() if key != "leases"}
        observed_lock_fields = {key: value for key, value in observed_locks.items() if key != "leases"}
        observed_leases = observed_locks.get("leases")
        if (
            (observed_lock, observed_state) != (lock_bytes, state_bytes)
            or observed_locks_bytes != _compact_bytes(observed_locks) + b"\n"
            or set(observed_locks) != {"schema_version", "workflow_id", "bootstrap_operation_id", "scope_binding_id", "leases"}
            or observed_lock_fields != expected_lock_fields
            or not isinstance(observed_leases, list)
            or len(observed_leases) != 1
            or set(observed_leases[0]) != {"lease_id", "producer_id", "decision_id", "lease_expires_at"}
            or {key: value for key, value in observed_leases[0].items() if key != "lease_expires_at"}
            != {key: value for key, value in lease.items() if key != "lease_expires_at"}
            or not isinstance(observed_leases[0].get("lease_expires_at"), str)
        ):
            raise AdapterConflict("workflow owner belongs to another bootstrap")
        for name in ("artifacts", "projections"):
            child = resolved / name
            child_info = child.lstat()
            if (
                child.is_symlink()
                or not stat.S_ISDIR(child_info.st_mode)
                or child_info.st_uid != os.geteuid()
                or stat.S_IMODE(child_info.st_mode) != 0o700
                or any(child.iterdir())
            ):
                raise AdapterConflict("workflow owner directory is invalid")
        return state, locator, observed_leases[0]

    _publish_bootstrap_file(resolved, ".adapter.lock", ".adapter.lock.tmp", lock_bytes)
    lock_descriptor = os.open(resolved / ".adapter.lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        if fcntl is None:
            raise AdapterConflict("host provides no supported workflow lock")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _publish_bootstrap_file(resolved, "locks.json", ".locks.json.tmp", locks_bytes)
        (resolved / "artifacts").mkdir(mode=0o700)
        _sync_directory(resolved)
        (resolved / "projections").mkdir(mode=0o700)
        _sync_directory(resolved)
        _publish_bootstrap_file(resolved, "state.json", ".state.json.tmp", state_bytes)
    finally:
        if fcntl is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
    return state, locator, lease


EVENT_MAX_BYTES = 262_144
EVENT_MAX_LINE_BYTES = 4_096
EVENT_MAX_RECORDS = 4_096


def _event_bytes(events: list[dict[str, Any]]) -> bytes:
    payload = b"".join(_compact_bytes(event) + b"\n" for event in events)
    if len(events) > EVENT_MAX_RECORDS or len(payload) > EVENT_MAX_BYTES:
        raise AdapterConflict("event stream exceeds its bounded audit budget")
    if any(len(line) > EVENT_MAX_LINE_BYTES for line in payload.splitlines(keepends=True)):
        raise AdapterConflict("event record exceeds its bounded line budget")
    return payload


def _parse_event_bytes(payload: bytes) -> list[dict[str, Any]]:
    if len(payload) > EVENT_MAX_BYTES:
        raise AdapterConflict("event stream exceeds its bounded audit budget")
    lines = payload.splitlines(keepends=True)
    if len(lines) > EVENT_MAX_RECORDS or any(not line.endswith(b"\n") or len(line) > EVENT_MAX_LINE_BYTES for line in lines):
        raise AdapterConflict("event stream is not bounded canonical JSONL")
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterConflict("event stream is not valid JSONL") from exc
        if not isinstance(event, dict) or _compact_bytes(event) + b"\n" != line:
            raise AdapterConflict("event stream is not canonical JSONL")
        events.append(event)
    return events


def _write_fixed_temp(path: Path, payload: bytes) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        observed, info = _safe_regular_bytes(path)
        if observed != payload or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise AdapterConflict("fixed event temp conflicts with requested append")
        return
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class LocalWorkflowAdapter:
    """Read an established v3 owner and expose only operator audit append."""

    def __init__(self, root: Path, state_schema: dict[str, Any], event_schema: dict[str, Any]) -> None:
        raw_root = Path(os.path.abspath(os.fspath(root)))
        try:
            info = raw_root.lstat()
            resolved = raw_root.resolve(strict=True)
        except OSError as exc:
            raise AdapterConflict("established workflow owner is unavailable") from exc
        if raw_root.is_symlink() or not stat.S_ISDIR(info.st_mode) or resolved != raw_root.absolute() or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise AdapterConflict("established workflow owner is unsafe")
        self.root = resolved
        self.state_schema = state_schema
        self.event_schema = event_schema
        self.state_path = resolved / "state.json"
        self.events_path = resolved / "events.jsonl"
        self.event_temp_path = resolved / ".events.jsonl.tmp"
        self.lock_path = resolved / ".adapter.lock"

    def _read_state(self) -> dict[str, Any]:
        payload, info = _safe_regular_bytes(self.state_path)
        if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise AdapterConflict("workflow state owner is unsafe")
        try:
            state = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise AdapterConflict("workflow state is invalid") from exc
        if not isinstance(state, dict) or payload != _compact_bytes(state) + b"\n":
            raise AdapterConflict("workflow state is not canonical")
        violations = validate_state(state, self.state_schema)
        if violations:
            raise AdapterConflict("workflow state is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
        root_info = self.root.lstat()
        expected_root = {"dev": root_info.st_dev, "ino": root_info.st_ino, "uid": root_info.st_uid, "mode": stat.S_IMODE(root_info.st_mode)}
        if state.get("bootstrap", {}).get("established_root_identity") != expected_root:
            raise AdapterConflict("workflow root identity does not match state owner")
        return state

    def _validate_inventory(self) -> None:
        allowed = {".adapter.lock", "state.json", "locks.json", "artifacts", "projections", "events.jsonl", ".events.jsonl.tmp"}
        names = {path.name for path in self.root.iterdir()}
        if not {".adapter.lock", "state.json", "locks.json", "artifacts", "projections"}.issubset(names) or names - allowed:
            raise AdapterConflict("workflow owner inventory is invalid")
        for name in ("artifacts", "projections"):
            info = (self.root / name).lstat()
            if (self.root / name).is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise AdapterConflict("workflow owner directory is invalid")
        _, locks_info = _safe_regular_bytes(self.root / "locks.json")
        if stat.S_IMODE(locks_info.st_mode) != 0o600 or locks_info.st_nlink != 1:
            raise AdapterConflict("workflow locks owner is unsafe")
        optional: dict[str, os.stat_result] = {}
        for name in ("events.jsonl", ".events.jsonl.tmp"):
            path = self.root / name
            if _optional_lstat(path) is not None:
                _, info = _safe_regular_bytes(path)
                if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink not in {1, 2}:
                    raise AdapterConflict("workflow event owner is unsafe")
                optional[name] = info
        linked_pair = len(optional) == 2 and len({(info.st_dev, info.st_ino) for info in optional.values()}) == 1
        if any(info.st_nlink == 2 for info in optional.values()) and not linked_pair:
            raise AdapterConflict("workflow event hard-link prefix is unsafe")

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        self._validate_inventory()
        lock_payload, lock_info = _safe_regular_bytes(self.lock_path)
        if stat.S_IMODE(lock_info.st_mode) != 0o600 or lock_info.st_nlink != 1:
            raise AdapterConflict("workflow adapter lock is unsafe")
        try:
            lock_header = json.loads(lock_payload)
        except json.JSONDecodeError as exc:
            raise AdapterConflict("workflow adapter lock header is invalid") from exc
        if not isinstance(lock_header, dict) or lock_payload != _compact_bytes(lock_header) + b"\n":
            raise AdapterConflict("workflow adapter lock header is not canonical")
        descriptor = os.open(self.lock_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        locked = False
        try:
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (lock_info.st_dev, lock_info.st_ino):
                raise AdapterConflict("workflow adapter lock changed while opening")
            if fcntl is None:
                raise AdapterConflict("host provides no supported workflow lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            self._validate_inventory()
            state = self._read_state()
            expected_header = {
                "schema_version": "sqw-lock/1",
                "workflow_id": state["workflow_id"],
                "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                "initial_root_binding_hash": _value_hash(state["bootstrap"]["initial_root_binding"]),
                "established_root_identity_hash": _value_hash(state["bootstrap"]["established_root_identity"]),
                "scope_binding_id": state["scope_binding"]["binding_id"],
                "mode": state["mode"],
            }
            if lock_header != expected_header:
                raise AdapterConflict("workflow adapter lock belongs to another owner")
            yield state
        finally:
            if locked and fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def append_event(self, event: dict[str, Any], *, expected_last_sequence: int) -> bool:
        """Append one operator audit event; return True for exact replay."""
        with self._locked_state() as state:
            final_exists = _optional_lstat(self.events_path) is not None
            temp_exists = _optional_lstat(self.event_temp_path) is not None
            final_payload = _safe_regular_bytes(self.events_path)[0] if final_exists else b""
            events = _parse_event_bytes(final_payload)
            violations = validate_event_stream(events, self.event_schema)
            if violations:
                raise AdapterConflict("existing event stream is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
            if any(item["workflow_id"] != state["workflow_id"] or item["state_version"] > state["state_version"] for item in events):
                raise AdapterConflict("event stream does not belong to current workflow state")

            actual = events[-1]["sequence"] if events else 0
            exact_replay = actual == expected_last_sequence + 1 and bool(events) and events[-1] == event
            if actual != expected_last_sequence and not exact_replay:
                raise AdapterConflict(f"stale event sequence: expected {expected_last_sequence}, current {actual}")
            candidate_events = events if exact_replay else [*events, event]
            candidate_payload = _event_bytes(candidate_events)
            candidate_violations = validate_event_stream(candidate_events, self.event_schema)
            if candidate_violations:
                raise ValueError("invalid event append: " + "; ".join(f"{item.code}@{item.path}" for item in candidate_violations[:8]))
            if event.get("workflow_id") != state["workflow_id"] or not isinstance(event.get("state_version"), int) or event["state_version"] > state["state_version"]:
                raise AdapterConflict("event does not bind the current workflow owner")
            if not exact_replay and event["state_version"] != state["state_version"] and not temp_exists:
                raise AdapterConflict("fresh event append must bind current state_version")

            if exact_replay:
                if temp_exists:
                    temp_payload, _ = _safe_regular_bytes(self.event_temp_path)
                    if temp_payload != candidate_payload:
                        raise AdapterConflict("fixed event temp conflicts with committed append")
                    self.event_temp_path.unlink()
                    _sync_directory(self.root)
                return True

            if temp_exists:
                temp_payload, _ = _safe_regular_bytes(self.event_temp_path)
                if temp_payload != candidate_payload:
                    raise AdapterConflict("fixed event temp conflicts with requested append")
            else:
                _write_fixed_temp(self.event_temp_path, candidate_payload)
            if final_exists:
                os.replace(self.event_temp_path, self.events_path)
                _sync_directory(self.root)
            else:
                os.link(self.event_temp_path, self.events_path, follow_symlinks=False)
                _sync_directory(self.root)
                self.event_temp_path.unlink()
                _sync_directory(self.root)
            return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--state-schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "workflow-state.schema.json")
    parser.add_argument("--event-schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "workflow-event.schema.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    append = subparsers.add_parser("append-event")
    append.add_argument("event", type=Path)
    append.add_argument("--expected-sequence", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        event_schema = load_json(args.event_schema)
        adapter = LocalWorkflowAdapter(args.root, load_json(args.state_schema), event_schema)
        replayed = adapter.append_event(load_json(args.event), expected_last_sequence=args.expected_sequence)
        result = {"status": "already_appended" if replayed else "appended"}
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (AdapterConflict, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
