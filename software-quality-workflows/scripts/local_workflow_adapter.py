#!/usr/bin/env python3
"""Crash-safe M1 trace appends and M2/M3 local workflow state."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any, Iterator

try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows host
    fcntl = None
try:
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - POSIX host
    msvcrt = None

from _workflow_state import canonical_hash, contains_secret_like, load_json, load_json_lines
from reconcile_workflow import reconcile
from validate_workflow_state import validate_event_stream, validate_state, validate_transition


class AdapterConflict(RuntimeError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes, *, failpoint: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if failpoint == "after_fsync":
            raise RuntimeError("injected crash after temp fsync")
        os.replace(temp_path, path)
        _sync_directory(path.parent)
    finally:
        temp_path.unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _exclusive_guard(root: Path) -> Iterator[None]:
    try:
        root.mkdir(parents=True, exist_ok=True)
        root_info = root.lstat()
    except OSError as exc:
        raise AdapterConflict(f"adapter root is unavailable: {root}: {exc}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise AdapterConflict(f"adapter root is not a safe directory: {root}")
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise AdapterConflict(f"adapter root is not a safe directory: {root}: {exc}") from exc
    opened_root = os.fstat(root_fd)
    if (opened_root.st_dev, opened_root.st_ino) != (root_info.st_dev, root_info.st_ino):
        os.close(root_fd)
        raise AdapterConflict(f"adapter root changed while opening: {root}")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(".adapter.lock", flags, 0o600, dir_fd=root_fd)
    except OSError as exc:
        os.close(root_fd)
        raise AdapterConflict(f"unsafe or unavailable adapter lock: {root / '.adapter.lock'}: {exc}") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        os.close(root_fd)
        raise AdapterConflict("adapter lock is not a regular file")
    locked = False
    try:
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AdapterConflict("adapter lock already held") from exc
        elif msvcrt is not None:  # pragma: no cover - Windows host
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - unusual host
            raise AdapterConflict("host provides no supported process-scoped file lock")
        locked = True
        if fcntl is not None:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"pid={os.getpid()} acquired={datetime.now(timezone.utc).isoformat()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        if locked and fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif locked and msvcrt is not None:  # pragma: no cover - Windows host
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)
        os.close(root_fd)


def _managed_directory(root: Path, name: str) -> Path:
    if not name or "/" in name or name in {".", ".."}:
        raise AdapterConflict("managed directory must be a direct child")
    target = root / name
    target.mkdir(mode=0o700, exist_ok=True)
    info = target.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or target.resolve().parent != root.resolve():
        raise AdapterConflict(f"managed directory is unsafe: {target}")
    return target


def _write_once(directory: Path, name: str, data: bytes) -> None:
    if not name or "/" in name or name in {".", ".."}:
        raise AdapterConflict("immutable artifact name must be a direct child")
    target = directory / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError:
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or target.read_bytes() != data:
            raise AdapterConflict(f"immutable artifact replacement or collision: {target}")
        return
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    _sync_directory(directory)


class LocalWorkflowAdapter:
    def __init__(self, root: Path, state_schema: dict[str, Any], event_schema: dict[str, Any]) -> None:
        raw_root = Path(os.path.abspath(os.fspath(root)))
        if os.path.lexists(raw_root):
            info = raw_root.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise AdapterConflict(f"controller root is not a safe directory: {raw_root}")
            self.root = raw_root.resolve(strict=True)
        else:
            parent = raw_root.parent.resolve(strict=True)
            self.root = parent / raw_root.name
        self.state_schema = state_schema
        self.event_schema = event_schema
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"
        self.locks_path = self.root / "locks.json"

    def _validated_state(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(state)
        candidate["state_hash"] = canonical_hash(candidate)
        violations = validate_state(candidate, self.state_schema)
        if violations:
            raise ValueError("invalid workflow state: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
        return candidate

    def initialize(self, state: dict[str, Any], *, failpoint: str | None = None) -> None:
        if state.get("mode") not in {"M2_SPARSE", "M3_FULL"}:
            raise ValueError("local durable adapter is only for M2/M3")
        with _exclusive_guard(self.root):
            candidate = self._validated_state(state)
            marker = self.root / ".initializing.json"
            if self.state_path.exists():
                existing = self.load_state()
                if existing.get("workflow_id") == candidate.get("workflow_id") and canonical_hash(existing) == canonical_hash(candidate):
                    marker.unlink(missing_ok=True)
                    return
                raise AdapterConflict("workflow already initialized")
            existing_names = {path.name for path in self.root.iterdir() if path.name != ".adapter.lock"}
            allowed_retry = {".initializing.json", "artifacts", "events.jsonl", "locks.json", "README.md"}
            if existing_names and ".initializing.json" not in existing_names:
                raise AdapterConflict(f"workflow root is not empty/task-owned: {sorted(existing_names)}")
            if existing_names - allowed_retry:
                raise AdapterConflict(f"interrupted initialization contains unmanaged paths: {sorted(existing_names - allowed_retry)}")
            if marker.exists() and load_json(marker).get("workflow_id") != candidate.get("workflow_id"):
                raise AdapterConflict("initialization marker belongs to another workflow")
            if not marker.exists():
                _atomic_write(marker, _json_bytes({"workflow_id": candidate["workflow_id"], "mode": candidate["mode"]}))
            _managed_directory(self.root, "artifacts")
            _atomic_write(self.events_path, b"")
            _atomic_write(self.locks_path, _json_bytes(candidate.get("locks", [])))
            _atomic_write(self.root / "README.md", b"# Task-owned workflow state\n\nGenerated for M2/M3; use the SQW local adapter for validated updates.\n")
            if failpoint == "before_state":
                raise RuntimeError("injected crash before initial state commit")
            _atomic_write(self.state_path, _json_bytes(candidate))
            marker.unlink(missing_ok=True)
            _sync_directory(self.root)

    def load_state(self) -> dict[str, Any]:
        value = load_json(self.state_path)
        if not isinstance(value, dict):
            raise ValueError("state.json must contain an object")
        return value

    def load_effective_state(self) -> dict[str, Any]:
        state = deepcopy(self.load_state())
        state["locks"] = load_json(self.locks_path)
        state["state_hash"] = canonical_hash(state)
        return state

    def commit_state(self, state: dict[str, Any], *, expected_state_version: int, failpoint: str | None = None) -> None:
        with _exclusive_guard(self.root):
            previous = self.load_effective_state()
            if previous.get("state_version") != expected_state_version:
                raise AdapterConflict(f"stale state version: expected {expected_state_version}, current {previous.get('state_version')}")
            proposed = deepcopy(state)
            proposed["locks"] = load_json(self.locks_path)
            candidate = self._validated_state(proposed)
            errors = validate_transition(previous, candidate)
            if errors:
                raise ValueError("invalid transition: " + "; ".join(f"{item.code}@{item.path}" for item in errors))
            _atomic_write(self.state_path, _json_bytes(candidate), failpoint=failpoint)

    def append_event(self, event: dict[str, Any], *, expected_last_sequence: int) -> None:
        with _exclusive_guard(self.root):
            events = load_json_lines(self.events_path)
            actual = events[-1]["sequence"] if events else 0
            if actual != expected_last_sequence:
                raise AdapterConflict(f"stale event sequence: expected {expected_last_sequence}, current {actual}")
            candidate = events + [deepcopy(event)]
            violations = validate_event_stream(candidate, self.event_schema)
            if violations:
                raise ValueError("invalid event append: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
            payload = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode() for item in candidate)
            _atomic_write(self.events_path, payload)

    def acquire_lock(self, resource: str, owner: str, *, lease_expires_at: str, expected_state_version: int) -> dict[str, Any]:
        expires = datetime.fromisoformat(lease_expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None or expires <= now:
            raise ValueError("lock lease must be timezone-aware and in the future")
        with _exclusive_guard(self.root):
            state = self.load_state()
            if state.get("state_version") != expected_state_version:
                raise AdapterConflict("stale state version")
            locks = load_json(self.locks_path)
            for lock in locks:
                if lock.get("resource") == resource:
                    if lock.get("owner") == owner:
                        return lock
                    raise AdapterConflict(f"resource already locked by {lock.get('owner')}: {resource}")
            acquired_at = now.isoformat()
            digest = sha256(f"{resource}\0{owner}\0{acquired_at}".encode()).hexdigest()[:16]
            lock = {"id": f"LOCK-{digest}", "resource": resource, "owner": owner, "acquired_at": acquired_at, "lease_expires_at": lease_expires_at, "state_version": expected_state_version}
            _atomic_write(self.locks_path, _json_bytes([*locks, lock]))
            return lock

    def release_lock(self, resource: str, owner: str) -> None:
        with _exclusive_guard(self.root):
            locks = load_json(self.locks_path)
            if any(item.get("resource") == resource and item.get("owner") != owner for item in locks):
                raise AdapterConflict(f"cannot release another owner's lock: {resource}")
            _atomic_write(self.locks_path, _json_bytes([item for item in locks if not (item.get("resource") == resource and item.get("owner") == owner)]))

    def store_artifact(self, data: bytes, *, sensitive: bool) -> dict[str, str]:
        if not self.state_path.is_file():
            raise AdapterConflict("initialize state before storing artifacts")
        if sensitive or contains_secret_like(data.decode("utf-8", errors="replace")):
            raise ValueError("sensitive or credential-shaped data requires an external controlled pointer")
        digest = sha256(data).hexdigest()
        relative = Path("artifacts") / f"sha256-{digest}.bin"
        _write_once(_managed_directory(self.root, "artifacts"), relative.name, data)
        return {"artifact_ref": relative.as_posix(), "content_hash": f"sha256:{digest}", "classification": "internal"}

    def orphan_artifacts(self) -> list[str]:
        referenced = {Path(item.get("artifact_ref", "")).as_posix().removeprefix(".workflow/") for item in self.load_state().get("artifacts", [])}
        directory = _managed_directory(self.root, "artifacts")
        entries = list(directory.iterdir())
        if len(entries) > 10000:
            raise AdapterConflict("artifact directory exceeds bounded orphan scan limit")
        observed: list[str] = []
        for entry in entries:
            info = entry.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise AdapterConflict(f"artifact store contains an unsafe entry: {entry.name}")
            relative = f"artifacts/{entry.name}"
            if relative not in referenced:
                observed.append(relative)
        return sorted(observed)

    def resume(self, *, current_revision: str | None = None, current_scope_hash: str | None = None, current_plan_hash: str | None = None, now_value: str | None = None) -> dict[str, Any]:
        return reconcile(
            self.load_effective_state(),
            current_revision=current_revision,
            current_scope_hash=current_scope_hash,
            current_plan_hash=current_plan_hash,
            workflow_root=self.root,
            verify_artifacts=True,
            events=load_json_lines(self.events_path),
            event_schema=self.event_schema,
            now_value=now_value,
        )


def append_trace(trace_path: Path, event: dict[str, Any], event_schema: dict[str, Any], *, expected_last_sequence: int) -> None:
    with _exclusive_guard(trace_path.resolve().parent):
        events = load_json_lines(trace_path) if trace_path.exists() else []
        actual = events[-1]["sequence"] if events else 0
        if actual != expected_last_sequence:
            raise AdapterConflict(f"stale trace sequence: expected {expected_last_sequence}, current {actual}")
        candidate = events + [deepcopy(event)]
        violations = validate_event_stream(candidate, event_schema)
        if violations:
            raise ValueError("invalid trace event: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
        payload = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode() for item in candidate)
        _atomic_write(trace_path, payload)


def _task_owned_trace_path(root: Path, raw_path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = (raw_path if raw_path.is_absolute() else resolved_root / raw_path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("M1 trace path must resolve inside the explicit task root")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--state-schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "workflow-state.schema.json")
    parser.add_argument("--event-schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "workflow-event.schema.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("state", type=Path)
    commit = subparsers.add_parser("commit")
    commit.add_argument("state", type=Path)
    commit.add_argument("--expected-version", required=True, type=int)
    append = subparsers.add_parser("append-event")
    append.add_argument("event", type=Path)
    append.add_argument("--expected-sequence", required=True, type=int)
    trace = subparsers.add_parser("append-trace")
    trace.add_argument("event", type=Path)
    trace.add_argument("--trace-path", required=True, type=Path)
    trace.add_argument("--expected-sequence", required=True, type=int)
    subparsers.add_parser("resume")
    args = parser.parse_args(argv)
    try:
        event_schema = load_json(args.event_schema)
        if args.command == "append-trace":
            trace_path = _task_owned_trace_path(args.root, args.trace_path)
            append_trace(trace_path, load_json(args.event), event_schema, expected_last_sequence=args.expected_sequence)
            result = {"status": "trace_appended", "trace_path": trace_path.relative_to(args.root.resolve()).as_posix()}
        else:
            adapter = LocalWorkflowAdapter(args.root, load_json(args.state_schema), event_schema)
            if args.command == "init":
                adapter.initialize(load_json(args.state))
                result = {"status": "initialized"}
            elif args.command == "commit":
                adapter.commit_state(load_json(args.state), expected_state_version=args.expected_version)
                result = {"status": "committed"}
            elif args.command == "append-event":
                adapter.append_event(load_json(args.event), expected_last_sequence=args.expected_sequence)
                result = {"status": "appended"}
            else:
                result = adapter.resume()
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (AdapterConflict, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
