#!/usr/bin/env python3
"""SQW v3 durable-owner bootstrap and operator-only audit appends."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable, Iterator

try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Windows host
    fcntl = None

from _workflow_state import load_json
from validate_workflow_state import validate_event_stream, validate_state, validate_transition


class AdapterConflict(RuntimeError):
    pass


class AdapterSourceDrift(AdapterConflict):
    pass


EVENT_MAX_BYTES = 262_144
EVENT_MAX_LINE_BYTES = 4_096
EVENT_MAX_RECORDS = 4_096


def _checkpoint(_name: str) -> None:
    """No-op durability seam replaced only by real child-process kill tests."""


def _write_and_fsync(path: Path, payload: bytes, checkpoint: str | None = None) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("workflow owner write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        if checkpoint is not None:
            _checkpoint(checkpoint)
    finally:
        os.close(descriptor)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _compact_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _value_hash(value: Any) -> str:
    return "sha256:" + sha256(_compact_bytes(value)).hexdigest()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 71 and value.startswith("sha256:") and all(character in "0123456789abcdef" for character in value[7:])


def _artifact_names(locator: dict[str, Any]) -> tuple[str, str]:
    artifact_id = locator.get("artifact_id")
    content_hash = locator.get("content_hash")
    if (
        locator.get("schema_version") != "content-locator/1"
        or locator.get("content_kind") != "artifact"
        or not isinstance(artifact_id, str)
        or not artifact_id
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in artifact_id)
        or not _is_hash(content_hash)
    ):
        raise AdapterConflict("artifact locator is invalid")
    final_name = f"{artifact_id}--{content_hash[7:]}.json"
    return final_name, f".{final_name}.tmp"


def _validate_artifact_bytes(payload: bytes, locator: dict[str, Any]) -> None:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AdapterConflict("materialized completion is invalid") from exc
    if (
        not isinstance(value, dict)
        or payload != _compact_bytes(value) + b"\n"
        or locator.get("bytes") != len(payload)
        or locator.get("content_hash") != _value_hash(value)
        or locator.get("artifact_id") != value.get("artifact_id")
    ):
        raise AdapterConflict("materialized completion does not match its locator")


def project_source_snapshot(observation: dict[str, Any], identity: dict[str, Any], scope_binding: dict[str, Any]) -> dict[str, Any]:
    patterns = sorted(set(scope_binding["allowed_reads"]) | set(scope_binding["allowed_writes"]))
    scoped = [record for record in observation["records"] if any(fnmatchcase(record["path"], pattern) for pattern in patterns)]
    scoped_paths = {record["path"] for record in scoped}
    exterior = [record for record in observation["records"] if record["path"] not in scoped_paths]
    return {
        "kind": identity["kind"],
        "identity_hash": identity["identity_hash"],
        "root_binding": observation["root_binding"],
        "head_commit": observation.get("head_commit"),
        "head_tree": observation.get("head_tree"),
        "scoped_records": scoped,
        "exterior_guard_hash": _value_hash(exterior),
    }


def _eligible_source_transition(before: dict[str, Any], after: dict[str, Any], allowed_writes: list[str]) -> dict[str, Any] | None:
    if before["identity_hash"] == after["identity_hash"]:
        return None
    if before["kind"] != after["kind"] or before["root_binding"] != after["root_binding"]:
        raise AdapterSourceDrift("source kind or root identity changed")
    if before.get("head_commit") != after.get("head_commit") or before.get("head_tree") != after.get("head_tree"):
        raise AdapterSourceDrift("repository HEAD or tree changed")
    if before["exterior_guard_hash"] != after["exterior_guard_hash"]:
        raise AdapterSourceDrift("source changed outside the immutable scope binding")
    before_records = {item["path"]: item for item in before["scoped_records"]}
    after_records = {item["path"]: item for item in after["scoped_records"]}
    changed: list[dict[str, str]] = []
    for path in sorted(set(before_records) | set(after_records)):
        if path not in before_records:
            status = "added"
        elif path not in after_records:
            status = "deleted"
        elif before_records[path] != after_records[path]:
            status = "modified"
        else:
            continue
        if not any(fnmatchcase(path, pattern) for pattern in allowed_writes):
            raise AdapterSourceDrift("source changed outside allowed_writes")
        changed.append({"path": path, "status": status})
    if not changed:
        raise AdapterSourceDrift("source identity changed without a scoped path transition")
    return {
        "before_identity_hash": before["identity_hash"],
        "after_identity_hash": after["identity_hash"],
        "changed_paths": changed,
        "changed_paths_hash": _value_hash(changed),
    }


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


def _prepare_immutable_file(root: Path, temp_name: str, payload: bytes, checkpoint: str) -> None:
    temporary = root / temp_name
    temp_info = _optional_lstat(temporary)
    if temp_info is not None:
        temp_bytes, temp_stat = _safe_regular_bytes(temporary)
        if temp_bytes != payload or stat.S_IMODE(temp_stat.st_mode) != 0o600 or temp_stat.st_nlink != 1:
            raise AdapterConflict("workflow bootstrap temp conflicts")
        return
    _write_and_fsync(temporary, payload, checkpoint)


def _publish_prepared_immutable(
    root: Path,
    final_name: str,
    temp_name: str,
    payload: bytes,
    *,
    checkpoint_prefix: str,
) -> None:
    final = root / final_name
    temporary = root / temp_name
    final_info = _optional_lstat(final)
    temp_info = _optional_lstat(temporary)
    if final_info is not None:
        final_bytes, final_stat = _safe_regular_bytes(final)
        if final_bytes != payload or stat.S_IMODE(final_stat.st_mode) != 0o600:
            raise AdapterConflict("workflow bootstrap final conflicts")
        if temp_info is None:
            if final_stat.st_nlink != 1:
                raise AdapterConflict("workflow bootstrap final conflicts")
            _sync_directory(root)
            _checkpoint(f"{checkpoint_prefix}_cleanup_parent_synced")
            return
        temp_bytes, temp_stat = _safe_regular_bytes(temporary)
        if (
            temp_bytes != payload
            or (final_stat.st_dev, final_stat.st_ino) != (temp_stat.st_dev, temp_stat.st_ino)
            or final_stat.st_nlink != 2
            or temp_stat.st_nlink != 2
        ):
            raise AdapterConflict("workflow bootstrap temp conflicts")
        _sync_directory(root)
        _checkpoint(f"{checkpoint_prefix}_link_parent_synced")
        temporary.unlink()
        _checkpoint(f"{checkpoint_prefix}_cleaned")
        _sync_directory(root)
        _checkpoint(f"{checkpoint_prefix}_cleanup_parent_synced")
        return
    if temp_info is None:
        raise AdapterConflict("workflow bootstrap prepared temp is absent")
    temp_bytes, temp_stat = _safe_regular_bytes(temporary)
    if temp_bytes != payload or stat.S_IMODE(temp_stat.st_mode) != 0o600 or temp_stat.st_nlink != 1:
        raise AdapterConflict("workflow bootstrap temp conflicts")
    os.link(temporary, final, follow_symlinks=False)
    _checkpoint(f"{checkpoint_prefix}_linked")
    _sync_directory(root)
    _checkpoint(f"{checkpoint_prefix}_link_parent_synced")
    temporary.unlink()
    _checkpoint(f"{checkpoint_prefix}_cleaned")
    _sync_directory(root)
    _checkpoint(f"{checkpoint_prefix}_cleanup_parent_synced")


def _publish_bootstrap_file(
    root: Path,
    final_name: str,
    temp_name: str,
    payload: bytes,
    *,
    checkpoint_prefix: str,
) -> None:
    if _optional_lstat(root / final_name) is None:
        _prepare_immutable_file(root, temp_name, payload, f"{checkpoint_prefix}_temp_fsynced")
    _publish_prepared_immutable(
        root,
        final_name,
        temp_name,
        payload,
        checkpoint_prefix=checkpoint_prefix,
    )


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


def _exact_bootstrap_file(path: Path, payload: bytes, *, links: set[int]) -> os.stat_result:
    observed, info = _safe_regular_bytes(path)
    if observed != payload or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink not in links:
        raise AdapterConflict("workflow bootstrap file conflicts")
    return info


def _validate_empty_directory(path: Path) -> None:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700 or any(path.iterdir()):
        raise AdapterConflict("workflow bootstrap directory conflicts")


def _validate_optional_event_file(path: Path, workflow_id: str) -> None:
    payload, info = _safe_regular_bytes(path)
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or not payload or len(payload) > EVENT_MAX_BYTES:
        raise AdapterConflict("workflow event sidecar is unsafe")
    first_line = payload.split(b"\n", 1)[0]
    if not first_line or len(first_line) + 1 > EVENT_MAX_LINE_BYTES:
        raise AdapterConflict("workflow event sidecar is invalid")
    try:
        first_event = json.loads(first_line)
    except json.JSONDecodeError as exc:
        raise AdapterConflict("workflow event sidecar is invalid") from exc
    if not isinstance(first_event, dict) or first_event.get("workflow_id") != workflow_id:
        raise AdapterConflict("workflow event sidecar belongs to another owner")


def _locks_kind(payload: bytes, empty_locks: dict[str, Any], lease_owner_fields: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AdapterConflict("workflow locks are invalid") from exc
    if not isinstance(value, dict) or payload != _compact_bytes(value) + b"\n":
        raise AdapterConflict("workflow locks are not canonical")
    if value == empty_locks:
        return "empty", None
    leases = value.get("leases")
    if {key: item for key, item in value.items() if key != "leases"} != {key: item for key, item in empty_locks.items() if key != "leases"} or not isinstance(leases, list) or len(leases) != 1:
        raise AdapterConflict("workflow locks belong to another bootstrap")
    lease = leases[0]
    if (
        not isinstance(lease, dict)
        or set(lease) != {*lease_owner_fields, "lease_id", "lease_expires_at"}
        or {key: lease.get(key) for key in lease_owner_fields} != lease_owner_fields
        or not _is_hash(lease.get("lease_id"))
        or not isinstance(lease.get("lease_expires_at"), str)
    ):
        raise AdapterConflict("workflow lease belongs to another bootstrap")
    try:
        expiry = datetime.fromisoformat(lease["lease_expires_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdapterConflict("workflow lease expiry is invalid") from exc
    if expiry.tzinfo is None:
        raise AdapterConflict("workflow lease expiry is invalid")
    return "leased", lease


def _validate_bootstrap_prefix(
    root: Path,
    *,
    lock_bytes: bytes,
    state_bytes: bytes,
    empty_locks: dict[str, Any],
    empty_locks_bytes: bytes,
    lease_owner_fields: dict[str, Any],
    workflow_id: str,
) -> None:
    allowed = {
        ".adapter.lock", ".adapter.lock.tmp", ".state.json.tmp", "state.json",
        ".locks.json.tmp", "locks.json", "artifacts", "projections", "events.jsonl", ".events.jsonl.tmp",
    }
    names = {path.name for path in root.iterdir()}
    if names - allowed:
        raise AdapterConflict("workflow root contains foreign or interrupted state")

    lock_final = root / ".adapter.lock"
    lock_temp = root / ".adapter.lock.tmp"
    has_lock = _optional_lstat(lock_final) is not None
    has_lock_temp = _optional_lstat(lock_temp) is not None
    if not has_lock:
        if names - ({".adapter.lock.tmp"} if has_lock_temp else set()):
            raise AdapterConflict("workflow bootstrap skipped the lock owner")
        if has_lock_temp:
            _exact_bootstrap_file(lock_temp, lock_bytes, links={1})
        return
    lock_info = _exact_bootstrap_file(lock_final, lock_bytes, links={1, 2})
    if has_lock_temp:
        temp_info = _exact_bootstrap_file(lock_temp, lock_bytes, links={2})
        if (lock_info.st_dev, lock_info.st_ino) != (temp_info.st_dev, temp_info.st_ino) or names != {".adapter.lock", ".adapter.lock.tmp"}:
            raise AdapterConflict("workflow lock publication prefix conflicts")
        return
    if lock_info.st_nlink != 1:
        raise AdapterConflict("workflow lock owner has an unsafe link count")

    state_final = root / "state.json"
    state_temp = root / ".state.json.tmp"
    has_state = _optional_lstat(state_final) is not None
    has_state_temp = _optional_lstat(state_temp) is not None
    locks_final = root / "locks.json"
    locks_temp = root / ".locks.json.tmp"
    has_locks = _optional_lstat(locks_final) is not None
    has_locks_temp = _optional_lstat(locks_temp) is not None
    has_artifacts = _optional_lstat(root / "artifacts") is not None
    has_projections = _optional_lstat(root / "projections") is not None
    event_paths = [root / name for name in ("events.jsonl", ".events.jsonl.tmp") if _optional_lstat(root / name) is not None]

    if has_state_temp:
        _exact_bootstrap_file(state_temp, state_bytes, links={2} if has_state else {1})
    if has_artifacts:
        _validate_empty_directory(root / "artifacts")
    if has_projections:
        _validate_empty_directory(root / "projections")
    if has_projections and not has_artifacts:
        raise AdapterConflict("workflow bootstrap directory prefix is out of order")

    if not has_state:
        if event_paths:
            raise AdapterConflict("workflow event sidecar precedes committed state")
        if (has_locks or has_locks_temp or has_artifacts or has_projections) and not has_state_temp:
            raise AdapterConflict("workflow bootstrap components lack prepared state")
        if has_locks:
            locks_info = _exact_bootstrap_file(locks_final, empty_locks_bytes, links={1, 2})
            if has_locks_temp:
                temp_info = _exact_bootstrap_file(locks_temp, empty_locks_bytes, links={2})
                if (locks_info.st_dev, locks_info.st_ino) != (temp_info.st_dev, temp_info.st_ino) or has_artifacts or has_projections:
                    raise AdapterConflict("workflow locks publication prefix conflicts")
            elif locks_info.st_nlink != 1:
                raise AdapterConflict("workflow locks owner has an unsafe link count")
        elif has_locks_temp:
            _exact_bootstrap_file(locks_temp, empty_locks_bytes, links={1})
            if has_artifacts or has_projections:
                raise AdapterConflict("workflow bootstrap skipped initial locks")
        elif has_artifacts or has_projections:
            raise AdapterConflict("workflow bootstrap skipped initial locks")
        return

    state_info = _exact_bootstrap_file(state_final, state_bytes, links={1, 2})
    if not (has_locks and has_artifacts and has_projections):
        raise AdapterConflict("committed workflow state lacks bootstrap components")
    if has_state_temp:
        temp_info = _exact_bootstrap_file(state_temp, state_bytes, links={2})
        if (state_info.st_dev, state_info.st_ino) != (temp_info.st_dev, temp_info.st_ino):
            raise AdapterConflict("workflow state publication prefix conflicts")
    elif state_info.st_nlink != 1:
        raise AdapterConflict("workflow state owner has an unsafe link count")
    final_locks_bytes, final_locks_info = _safe_regular_bytes(locks_final)
    final_kind, _ = _locks_kind(final_locks_bytes, empty_locks, lease_owner_fields)
    if stat.S_IMODE(final_locks_info.st_mode) != 0o600 or final_locks_info.st_nlink != 1:
        raise AdapterConflict("workflow locks owner is unsafe")
    if has_locks_temp:
        temp_locks_bytes, temp_locks_info = _safe_regular_bytes(locks_temp)
        temp_kind, _ = _locks_kind(temp_locks_bytes, empty_locks, lease_owner_fields)
        if stat.S_IMODE(temp_locks_info.st_mode) != 0o600 or temp_locks_info.st_nlink != 1 or temp_kind != "leased":
            raise AdapterConflict("workflow lease temp conflicts")
        if final_kind == "leased" and final_locks_bytes != temp_locks_bytes:
            raise AdapterConflict("workflow lease temp forks committed locks")
    for event_path in event_paths:
        _validate_optional_event_file(event_path, workflow_id)


def _ensure_bootstrap_directory(root: Path, name: str, checkpoint: str) -> None:
    path = root / name
    if _optional_lstat(path) is not None:
        _validate_empty_directory(path)
        return
    path.mkdir(mode=0o700)
    _sync_directory(root)
    _checkpoint(checkpoint)


def _commit_initial_lease(
    root: Path,
    *,
    empty_locks: dict[str, Any],
    lease_owner_fields: dict[str, Any],
    proposed_lease: dict[str, Any],
) -> dict[str, Any]:
    final = root / "locks.json"
    temporary = root / ".locks.json.tmp"
    final_bytes, final_info = _safe_regular_bytes(final)
    final_kind, final_lease = _locks_kind(final_bytes, empty_locks, lease_owner_fields)
    if stat.S_IMODE(final_info.st_mode) != 0o600 or final_info.st_nlink != 1:
        raise AdapterConflict("workflow locks owner is unsafe")
    temp_info = _optional_lstat(temporary)
    if final_kind == "leased":
        if temp_info is not None:
            temp_bytes, observed = _safe_regular_bytes(temporary)
            temp_kind, _ = _locks_kind(temp_bytes, empty_locks, lease_owner_fields)
            if temp_kind != "leased" or temp_bytes != final_bytes or stat.S_IMODE(observed.st_mode) != 0o600 or observed.st_nlink != 1:
                raise AdapterConflict("workflow lease temp conflicts")
            _sync_directory(root)
            temporary.unlink()
            _sync_directory(root)
        else:
            _sync_directory(root)
        _checkpoint("lease_parent_synced")
        if final_lease is None:  # defensive against future classifier changes
            raise AdapterConflict("workflow lease classification is inconsistent")
        return final_lease

    if temp_info is not None:
        candidate_bytes, observed = _safe_regular_bytes(temporary)
        candidate_kind, candidate_lease = _locks_kind(candidate_bytes, empty_locks, lease_owner_fields)
        if candidate_kind != "leased" or stat.S_IMODE(observed.st_mode) != 0o600 or observed.st_nlink != 1:
            raise AdapterConflict("workflow lease temp conflicts")
        if candidate_lease is None:  # defensive against future classifier changes
            raise AdapterConflict("workflow lease classification is inconsistent")
    else:
        candidate_lease = proposed_lease
        candidate_bytes = _compact_bytes({**empty_locks, "leases": [candidate_lease]}) + b"\n"
        _write_and_fsync(temporary, candidate_bytes, "lease_temp_fsynced")
    os.replace(temporary, final)
    _checkpoint("lease_replaced")
    _sync_directory(root)
    _checkpoint("lease_parent_synced")
    return candidate_lease


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
    source_snapshot: dict[str, Any] | None = None,
    next_step: dict[str, Any],
    now_value: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create or replay the v3 M2/M3 owner bootstrap without creating the root."""
    if mode not in {"M2", "M3"}:
        raise AdapterConflict("durable workflow mode must be M2 or M3")
    resolved, initial_root_binding = _validate_v3_root(root, source_root)
    if source_snapshot is None:
        source_info = source_root.lstat()
        source_snapshot = {
            "kind": source_identity["kind"],
            "identity_hash": source_identity["identity_hash"],
            "root_binding": {"dev": source_info.st_dev, "ino": source_info.st_ino},
            "head_commit": None,
            "head_tree": None,
            "scoped_records": [],
            "exterior_guard_hash": _value_hash([]),
        }
    if source_snapshot["identity_hash"] != source_identity["identity_hash"]:
        raise AdapterConflict("source snapshot does not bind source identity")
    initial_root_binding_hash = _value_hash(initial_root_binding)
    bootstrap_semantics = {
        "bundle_id": bundle_id,
        "mode": mode,
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
    lease_owner_fields = {
        "producer_id": next_step["card_id"],
        "decision_id": next_step["decision_id"],
    }
    try:
        lease_now = datetime.fromisoformat(now_value.replace("Z", "+00:00")) if now_value else datetime.now(timezone.utc)
    except ValueError as exc:
        raise AdapterConflict("workflow lease clock is invalid") from exc
    if lease_now.tzinfo is None:
        raise AdapterConflict("workflow lease clock is invalid")
    proposed_lease = {
        "lease_id": _value_hash({"workflow_id": workflow_id, "frontier": next_step}),
        **lease_owner_fields,
        "lease_expires_at": (lease_now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    empty_locks = {
        "schema_version": "sqw-locks/1",
        "workflow_id": workflow_id,
        "bootstrap_operation_id": bootstrap_operation_id,
        "scope_binding_id": scope_binding["binding_id"],
        "leases": [],
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
            "initial_source_identity_hash": source_identity["identity_hash"],
            "initial_root_binding": initial_root_binding,
            "established_root_identity": initial_root_binding,
        },
        "scope_binding": scope_binding,
        "source_identity": source_identity,
        "source_snapshot": source_snapshot,
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
            {
                "storage": "inline", "operation_id": entry_completion["content_hash"],
                "prior_state_version": 0, "prior_state_hash": None, "completion": entry_completion,
            },
            {
                "storage": "inline", "operation_id": bootstrap_operation_id,
                "prior_state_version": 0, "prior_state_hash": None, "completion": scope_completion,
            },
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
    empty_locks_bytes = _compact_bytes(empty_locks) + b"\n"
    state_bytes = _compact_bytes(state) + b"\n"

    if len(state_bytes) > 2 * 1024 * 1024:
        raise AdapterConflict("workflow state exceeds the 2 MiB budget")
    _validate_bootstrap_prefix(
        resolved,
        lock_bytes=lock_bytes,
        state_bytes=state_bytes,
        empty_locks=empty_locks,
        empty_locks_bytes=empty_locks_bytes,
        lease_owner_fields=lease_owner_fields,
        workflow_id=workflow_id,
    )
    _publish_bootstrap_file(
        resolved,
        ".adapter.lock",
        ".adapter.lock.tmp",
        lock_bytes,
        checkpoint_prefix="lock",
    )
    lock_descriptor = os.open(resolved / ".adapter.lock", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened_lock = os.fstat(lock_descriptor)
        observed_lock = (resolved / ".adapter.lock").lstat()
        if (
            not stat.S_ISREG(opened_lock.st_mode)
            or opened_lock.st_uid != os.geteuid()
            or stat.S_IMODE(opened_lock.st_mode) != 0o600
            or opened_lock.st_nlink != 1
            or (opened_lock.st_dev, opened_lock.st_ino) != (observed_lock.st_dev, observed_lock.st_ino)
        ):
            raise AdapterConflict("workflow adapter lock changed while opening")
        if fcntl is None:
            raise AdapterConflict("host provides no supported workflow lock")
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _validate_bootstrap_prefix(
            resolved,
            lock_bytes=lock_bytes,
            state_bytes=state_bytes,
            empty_locks=empty_locks,
            empty_locks_bytes=empty_locks_bytes,
            lease_owner_fields=lease_owner_fields,
            workflow_id=workflow_id,
        )
        if _optional_lstat(resolved / "state.json") is None:
            _prepare_immutable_file(resolved, ".state.json.tmp", state_bytes, "state_temp_fsynced")
            _publish_bootstrap_file(
                resolved,
                "locks.json",
                ".locks.json.tmp",
                empty_locks_bytes,
                checkpoint_prefix="initial_locks",
            )
            _ensure_bootstrap_directory(resolved, "artifacts", "artifacts_created")
            _ensure_bootstrap_directory(resolved, "projections", "projections_created")
        _publish_prepared_immutable(
            resolved,
            "state.json",
            ".state.json.tmp",
            state_bytes,
            checkpoint_prefix="state",
        )
        lease = _commit_initial_lease(
            resolved,
            empty_locks=empty_locks,
            lease_owner_fields=lease_owner_fields,
            proposed_lease=proposed_lease,
        )
    finally:
        if fcntl is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
    _checkpoint("bootstrap_before_return")
    return state, locator, lease


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
        _write_and_fsync(path, payload)
    except FileExistsError:
        observed, info = _safe_regular_bytes(path)
        if observed != payload or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise AdapterConflict("fixed event temp conflicts with requested append")


def _replace_fixed_mutable(
    root: Path,
    final_name: str,
    temp_name: str,
    *,
    expected_bytes: bytes,
    candidate_bytes: bytes,
    checkpoint_prefix: str,
) -> bool:
    final = root / final_name
    temporary = root / temp_name
    final_payload, final_info = _safe_regular_bytes(final)
    if stat.S_IMODE(final_info.st_mode) != 0o600 or final_info.st_nlink != 1:
        raise AdapterConflict("mutable owner final is unsafe")
    temp_exists = _optional_lstat(temporary) is not None
    if final_payload == candidate_bytes:
        if temp_exists:
            temp_payload, temp_info = _safe_regular_bytes(temporary)
            if temp_payload != candidate_bytes or stat.S_IMODE(temp_info.st_mode) != 0o600 or temp_info.st_nlink != 1:
                raise AdapterConflict("mutable owner temp conflicts")
            _sync_directory(root)
            temporary.unlink()
            _sync_directory(root)
        else:
            _sync_directory(root)
        return True
    if final_payload != expected_bytes:
        raise AdapterConflict("mutable owner final conflicts")
    if temp_exists:
        temp_payload, temp_info = _safe_regular_bytes(temporary)
        if temp_payload != candidate_bytes or stat.S_IMODE(temp_info.st_mode) != 0o600 or temp_info.st_nlink != 1:
            raise AdapterConflict("mutable owner temp conflicts")
    else:
        _write_and_fsync(temporary, candidate_bytes, f"{checkpoint_prefix}_temp_fsynced")
    os.replace(temporary, final)
    _checkpoint(f"{checkpoint_prefix}_replaced")
    _sync_directory(root)
    _checkpoint(f"{checkpoint_prefix}_parent_synced")
    return False


def _projection_header(payload: bytes) -> dict[str, Any]:
    first_line = payload.split(b"\n", 1)[0]
    if not first_line.startswith(b"<!-- ") or not first_line.endswith(b" -->"):
        raise AdapterConflict("workflow context projection header is invalid")
    try:
        header = json.loads(first_line[5:-4])
    except json.JSONDecodeError as exc:
        raise AdapterConflict("workflow context projection header is invalid") from exc
    required = {
        "schema_version",
        "workflow_id",
        "state_version",
        "state_hash",
        "frontier_decision_id",
        "frontier_card_id",
        "frontier_card_hash",
        "renderer_hash",
    }
    if not isinstance(header, dict) or set(header) != required or header.get("schema_version") != "sqw-workflow-context/1":
        raise AdapterConflict("workflow context projection header is invalid")
    return header


def _publish_disposable_projection(root: Path, payload: bytes) -> bool:
    final = root / "workflow-context.md"
    temporary = root / "workflow-context.md.tmp"
    names = {path.name for path in root.iterdir()}
    if names - {final.name, temporary.name}:
        raise AdapterConflict("workflow projection directory contains foreign entries")
    final_exists = _optional_lstat(final) is not None
    temp_exists = _optional_lstat(temporary) is not None
    final_bytes = None
    if final_exists:
        final_bytes, final_info = _safe_regular_bytes(final)
        _projection_header(final_bytes)
        if stat.S_IMODE(final_info.st_mode) != 0o600 or final_info.st_nlink != 1:
            raise AdapterConflict("workflow context projection final is unsafe")
    if temp_exists:
        temp_bytes, temp_info = _safe_regular_bytes(temporary)
        _projection_header(temp_bytes)
        if temp_bytes != payload or stat.S_IMODE(temp_info.st_mode) != 0o600 or temp_info.st_nlink != 1:
            raise AdapterConflict("workflow context projection temp conflicts")
    if final_bytes == payload:
        if temp_exists:
            _sync_directory(root)
            temporary.unlink()
            _sync_directory(root)
        else:
            _sync_directory(root)
        return True
    if not temp_exists:
        _write_and_fsync(temporary, payload, "projection_temp_fsynced")
    os.replace(temporary, final)
    _checkpoint("projection_replaced")
    _sync_directory(root)
    _checkpoint("projection_parent_synced")
    return False


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
        artifact_root = self.root / "artifacts"
        for entry in state.get("card_completions", []):
            if entry.get("storage") != "materialized":
                continue
            final_name, temp_name = _artifact_names(entry["content_locator"])
            if _optional_lstat(artifact_root / temp_name) is not None:
                raise AdapterConflict("committed materialized completion has a prepared temp")
            artifact_bytes, artifact_info = _safe_regular_bytes(artifact_root / final_name)
            if stat.S_IMODE(artifact_info.st_mode) != 0o600 or artifact_info.st_nlink != 1:
                raise AdapterConflict("committed materialized completion is unsafe")
            _validate_artifact_bytes(artifact_bytes, entry["content_locator"])
        return state

    def _validate_inventory(self) -> None:
        allowed = {".adapter.lock", "state.json", ".state.json.tmp", "locks.json", ".locks.json.tmp", "artifacts", "projections", "events.jsonl", ".events.jsonl.tmp"}
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
        for name in (".state.json.tmp", ".locks.json.tmp", "events.jsonl", ".events.jsonl.tmp"):
            path = self.root / name
            if _optional_lstat(path) is not None:
                _, info = _safe_regular_bytes(path)
                if stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink not in {1, 2} or (name in {".state.json.tmp", ".locks.json.tmp"} and info.st_nlink != 1):
                    raise AdapterConflict("workflow optional owner file is unsafe")
                optional[name] = info
        event_entries = {name: info for name, info in optional.items() if name in {"events.jsonl", ".events.jsonl.tmp"}}
        linked_pair = len(event_entries) == 2 and len({(info.st_dev, info.st_ino) for info in event_entries.values()}) == 1
        if any(info.st_nlink == 2 for info in event_entries.values()) and not linked_pair:
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

    def _validate_projection_surface(self, state: dict[str, Any], *, cleanup_matching_temp: bool) -> None:
        projection_root = self.root / "projections"
        names = {path.name for path in projection_root.iterdir()}
        if names - {"workflow-context.md", "workflow-context.md.tmp"}:
            raise AdapterConflict("workflow projection directory contains foreign entries")
        renderer_hash = "sha256:" + sha256((Path(__file__).parent / "project_context.py").read_bytes()).hexdigest()
        frontier = state.get("active_frontier")
        expected = {
            "schema_version": "sqw-workflow-context/1",
            "workflow_id": state["workflow_id"],
            "state_version": state["state_version"],
            "state_hash": state["state_hash"],
            "frontier_decision_id": frontier["decision_id"] if isinstance(frontier, dict) else None,
            "frontier_card_id": frontier["card_id"] if isinstance(frontier, dict) else None,
            "frontier_card_hash": frontier["card_hash"] if isinstance(frontier, dict) else None,
            "renderer_hash": renderer_hash,
        }
        final = projection_root / "workflow-context.md"
        if _optional_lstat(final) is not None:
            final_bytes, final_info = _safe_regular_bytes(final)
            final_header = _projection_header(final_bytes)
            if final_header["workflow_id"] != state["workflow_id"] or final_header["renderer_hash"] != renderer_hash or stat.S_IMODE(final_info.st_mode) != 0o600 or final_info.st_nlink != 1:
                raise AdapterConflict("workflow context projection final is foreign")
        temporary = projection_root / "workflow-context.md.tmp"
        if _optional_lstat(temporary) is not None:
            temp_bytes, temp_info = _safe_regular_bytes(temporary)
            if _projection_header(temp_bytes) != expected or stat.S_IMODE(temp_info.st_mode) != 0o600 or temp_info.st_nlink != 1:
                raise AdapterConflict("workflow context projection temp is stale or foreign")
            if cleanup_matching_temp:
                _sync_directory(projection_root)
                temporary.unlink()
                _sync_directory(projection_root)

    def append_event(self, event: dict[str, Any], *, expected_last_sequence: int) -> bool:
        """Append one operator audit event; return True for exact replay."""
        with self._locked_state() as state:
            self._validate_projection_surface(state, cleanup_matching_temp=False)
            if _optional_lstat(self.root / ".state.json.tmp") is not None:
                raise AdapterConflict("prepared card state blocks operator event append")
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
                    _sync_directory(self.root)
                    self.event_temp_path.unlink()
                    _sync_directory(self.root)
                return True

            if temp_exists:
                temp_payload, _ = _safe_regular_bytes(self.event_temp_path)
                if temp_payload != candidate_payload:
                    raise AdapterConflict("fixed event temp conflicts with requested append")
            else:
                _write_fixed_temp(self.event_temp_path, candidate_payload)
                _checkpoint("event_temp_fsynced")
            if final_exists:
                os.replace(self.event_temp_path, self.events_path)
                _checkpoint("event_replaced")
                _sync_directory(self.root)
                _checkpoint("event_parent_synced")
            else:
                os.link(self.event_temp_path, self.events_path, follow_symlinks=False)
                _checkpoint("event_linked")
                _sync_directory(self.root)
                _checkpoint("event_link_parent_synced")
                self.event_temp_path.unlink()
                _checkpoint("event_temp_cleaned")
                _sync_directory(self.root)
                _checkpoint("event_cleanup_parent_synced")
            _checkpoint("event_before_return")
            return False

    def _abort_prepared_completion(self, state: dict[str, Any], expected_cards: dict[str, tuple[str, str]]) -> None:
        temporary = self.root / ".state.json.tmp"
        if _optional_lstat(temporary) is None:
            return
        if _optional_lstat(self.root / ".locks.json.tmp") is not None:
            raise AdapterConflict("prepared card state has an illegal precommit locks temp")
        payload, _ = _safe_regular_bytes(temporary)
        try:
            candidate = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise AdapterConflict("prepared card state is invalid") from exc
        if not isinstance(candidate, dict) or payload != _compact_bytes(candidate) + b"\n":
            raise AdapterConflict("prepared card state is not canonical")
        violations = validate_state(candidate, self.state_schema) + validate_transition(state, candidate)
        if violations:
            raise AdapterConflict("prepared card state is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
        mutable = {"card_completions", "state_version", "state_hash", "status", "active_frontier", "last_transition"}
        if {key: value for key, value in candidate.items() if key not in mutable} != {key: value for key, value in state.items() if key not in mutable}:
            raise AdapterConflict("prepared card state changes fields outside one completion")
        if candidate["card_completions"][:-1] != state["card_completions"] or len(candidate["card_completions"]) != len(state["card_completions"]) + 1:
            raise AdapterConflict("prepared card state does not append exactly one completion")
        entry = candidate["card_completions"][-1]
        completion = entry.get("completion") if entry.get("storage") == "inline" else None
        completion_id = completion.get("content_hash") if isinstance(completion, dict) else entry.get("completion_id")
        producer_card_id = completion.get("producer_card_id") if isinstance(completion, dict) else entry.get("card_id")
        transition = candidate["last_transition"]
        frontier = state.get("active_frontier")
        producer_decision_id = completion.get("decision_id") if isinstance(completion, dict) else frontier.get("decision_id") if isinstance(frontier, dict) else None
        if (
            entry.get("storage") not in {"inline", "materialized"}
            or not isinstance(frontier, dict)
            or entry.get("prior_state_version") != state["state_version"]
            or entry.get("prior_state_hash") != state["state_hash"]
            or producer_card_id != frontier.get("card_id")
            or producer_decision_id != frontier.get("decision_id")
            or transition.get("transition_kind") != "card"
            or transition.get("prior_state_version") != state["state_version"]
            or transition.get("prior_state_hash") != state["state_hash"]
            or transition.get("completion_id") != completion_id
            or transition.get("operation_id") != entry.get("operation_id")
        ):
            raise AdapterConflict("prepared card state does not bind the current frontier")
        next_decision = transition["next_decision_id"]
        expected_operation = _value_hash({
            "contract_id": "sqw.complete.card/1",
            "workflow_id": state["workflow_id"],
            "prior_state_version": state["state_version"],
            "prior_state_hash": state["state_hash"],
            "completion_id": completion_id,
            "next_decision_id": next_decision,
        })
        next_frontier = candidate["active_frontier"]
        terminal = next_decision is None
        if entry["operation_id"] != expected_operation or candidate["state_version"] != state["state_version"] + 1:
            raise AdapterConflict("prepared card operation identity is invalid")
        if terminal:
            if candidate["status"] != "completed" or next_frontier is not None:
                raise AdapterConflict("prepared terminal state is invalid")
        elif (
            candidate["status"] != "active"
            or not isinstance(next_frontier, dict)
            or next_frontier.get("decision_id") != next_decision
            or expected_cards.get(next_frontier.get("card_id")) != (next_frontier.get("card_path"), next_frontier.get("card_hash"))
        ):
            raise AdapterConflict("prepared next frontier is invalid")
        if entry["storage"] == "materialized":
            artifact_root = self.root / "artifacts"
            final_name, temp_name = _artifact_names(entry["content_locator"])
            final_path, temp_path = artifact_root / final_name, artifact_root / temp_name
            final_info, temp_info = _optional_lstat(final_path), _optional_lstat(temp_path)
            if final_info is not None:
                final_bytes, final_stat = _safe_regular_bytes(final_path)
                _validate_artifact_bytes(final_bytes, entry["content_locator"])
                if temp_info is None:
                    if final_stat.st_nlink != 1:
                        raise AdapterConflict("prepared artifact final is unsafe")
                else:
                    temp_bytes, temp_stat = _safe_regular_bytes(temp_path)
                    _validate_artifact_bytes(temp_bytes, entry["content_locator"])
                    if (final_stat.st_dev, final_stat.st_ino) != (temp_stat.st_dev, temp_stat.st_ino) or final_stat.st_nlink != 2 or temp_stat.st_nlink != 2:
                        raise AdapterConflict("prepared artifact pair conflicts")
                    _sync_directory(artifact_root)
                    temp_path.unlink()
                    _sync_directory(artifact_root)
            elif temp_info is not None:
                temp_bytes, temp_stat = _safe_regular_bytes(temp_path)
                _validate_artifact_bytes(temp_bytes, entry["content_locator"])
                if temp_stat.st_nlink != 1:
                    raise AdapterConflict("prepared artifact temp is unsafe")
                _sync_directory(artifact_root)
                temp_path.unlink()
                _sync_directory(artifact_root)
        _sync_directory(self.root)
        temporary.unlink()
        _sync_directory(self.root)

    def resume(
        self,
        locator: dict[str, Any],
        current_source_identity: dict[str, Any],
        current_source_snapshot: dict[str, Any] | None = None,
        *,
        current_source_observation: dict[str, Any] | None = None,
        expected_bundle_id: str,
        expected_policy_bundle_hash: str,
        expected_card_manifest_hash: str,
        expected_cards: dict[str, tuple[str, str]],
        now_value: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, bool, str | None]:
        """Return the committed frontier and reuse or replace its independent lease."""
        with self._locked_state() as state:
            expected_locator = {
                "schema_version": "sqw-workflow-owner/1",
                "workflow_id": state["workflow_id"],
                "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                "bundle_id": state["bundle_id"],
                "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
                "scope_binding_id": state["scope_binding"]["binding_id"],
                "mode": state["mode"],
                "initial_root_binding_hash": _value_hash(state["bootstrap"]["initial_root_binding"]),
            }
            if locator != expected_locator:
                raise AdapterConflict("workflow locator does not bind this owner")
            if (
                state["bundle_id"] != expected_bundle_id
                or state["policy_bundle_hash"] != expected_policy_bundle_hash
                or state["card_manifest_hash"] != expected_card_manifest_hash
            ):
                raise AdapterConflict("workflow owner contract is stale")
            self._abort_prepared_completion(state, expected_cards)
            self._validate_projection_surface(state, cleanup_matching_temp=True)
            if current_source_observation is not None:
                current_source_snapshot = project_source_snapshot(current_source_observation, current_source_identity, state["scope_binding"])
            if current_source_snapshot is None:
                if current_source_identity != state["source_identity"]:
                    raise AdapterSourceDrift("current source identity lacks a verifiable scoped snapshot")
                current_source_snapshot = state["source_snapshot"]
            blocked_reason = None
            try:
                if current_source_snapshot["identity_hash"] != current_source_identity["identity_hash"]:
                    raise AdapterSourceDrift("source transition is unverifiable")
                pending_transition = _eligible_source_transition(
                    state["source_snapshot"],
                    current_source_snapshot,
                    state["scope_binding"]["allowed_writes"],
                )
            except AdapterSourceDrift as exc:
                pending_transition = None
                message = str(exc)
                blocked_reason = "source-kind-or-root-changed" if "kind or root" in message else "source-revision-changed" if "HEAD or tree" in message else "source-transition-unverifiable" if "unverifiable" in message or "without a scoped" in message else "source-out-of-scope"
            source_fresh = pending_transition is None and blocked_reason is None
            frontier = state.get("active_frontier")
            empty_locks = {
                "schema_version": "sqw-locks/1",
                "workflow_id": state["workflow_id"],
                "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                "scope_binding_id": state["scope_binding"]["binding_id"],
                "leases": [],
            }
            final_path = self.root / "locks.json"
            final_bytes, _ = _safe_regular_bytes(final_path)
            try:
                now = datetime.fromisoformat(now_value.replace("Z", "+00:00")) if now_value else datetime.now(timezone.utc)
            except ValueError as exc:
                raise AdapterConflict("workflow lease clock is invalid") from exc
            if now.tzinfo is None:
                raise AdapterConflict("workflow lease clock is invalid")
            temp_path = self.root / ".locks.json.tmp"
            old_owner = None
            if state["last_transition"]["transition_kind"] == "card":
                matches = [entry for entry in state["card_completions"] if entry["operation_id"] == state["last_transition"]["operation_id"]]
                if len(matches) == 1 and matches[0]["storage"] == "inline":
                    old_completion = matches[0]["completion"]
                    old_owner = {"producer_id": old_completion.get("producer_card_id"), "decision_id": old_completion.get("decision_id")}
                elif len(matches) == 1 and matches[0]["storage"] == "materialized":
                    final_name, _ = _artifact_names(matches[0]["content_locator"])
                    old_completion = json.loads(_safe_regular_bytes(self.root / "artifacts" / final_name)[0])
                    old_owner = {"producer_id": old_completion.get("producer_card_id"), "decision_id": old_completion.get("decision_id")}

            empty_bytes = _compact_bytes(empty_locks) + b"\n"
            if blocked_reason is not None:
                current_owner = {"producer_id": frontier["card_id"], "decision_id": frontier["decision_id"]} if isinstance(frontier, dict) else old_owner
                if final_bytes != empty_bytes:
                    try:
                        final_kind, final_lease = _locks_kind(final_bytes, empty_locks, current_owner or {})
                    except AdapterConflict:
                        if old_owner is None:
                            raise
                        final_kind, final_lease = _locks_kind(final_bytes, empty_locks, old_owner)
                    if final_kind != "leased" or final_lease is None:
                        raise AdapterConflict("blocked workflow locks are foreign")
                if _optional_lstat(temp_path) is not None:
                    temp_bytes, _ = _safe_regular_bytes(temp_path)
                    if temp_bytes != empty_bytes:
                        temp_kind, temp_lease = _locks_kind(temp_bytes, empty_locks, current_owner or {})
                        if temp_kind != "leased" or temp_lease is None:
                            raise AdapterConflict("blocked workflow locks temp conflicts")
                        _sync_directory(self.root)
                        temp_path.unlink()
                        _sync_directory(self.root)
                _replace_fixed_mutable(
                    self.root,
                    "locks.json",
                    ".locks.json.tmp",
                    expected_bytes=final_bytes,
                    candidate_bytes=empty_bytes,
                    checkpoint_prefix="route_lease",
                )
                _checkpoint("route_before_return")
                return state, None, None, False, blocked_reason
            if frontier is None:
                if state["status"] != "completed":
                    raise AdapterConflict("terminal workflow status is invalid")
                if final_bytes != empty_bytes:
                    if old_owner is None:
                        raise AdapterConflict("terminal workflow locks are foreign")
                    old_kind, old_lease = _locks_kind(final_bytes, empty_locks, old_owner)
                    if old_kind != "leased" or old_lease is None:
                        raise AdapterConflict("terminal workflow locks are foreign")
                if _optional_lstat(temp_path) is not None:
                    temp_bytes, _ = _safe_regular_bytes(temp_path)
                    if temp_bytes != empty_bytes:
                        raise AdapterConflict("terminal workflow locks temp conflicts")
                _replace_fixed_mutable(
                    self.root,
                    "locks.json",
                    ".locks.json.tmp",
                    expected_bytes=final_bytes,
                    candidate_bytes=empty_bytes,
                    checkpoint_prefix="route_lease",
                )
                _checkpoint("route_before_return")
                return state, None, None, source_fresh, None
            if not isinstance(frontier, dict) or expected_cards.get(frontier["card_id"]) != (frontier["card_path"], frontier["card_hash"]):
                raise AdapterConflict("workflow frontier is stale")
            lease_owner = {"producer_id": frontier["card_id"], "decision_id": frontier["decision_id"]}
            pending_lease_id = _value_hash({"workflow_id": state["workflow_id"], "state_hash": state["state_hash"], "frontier": frontier, "source_transition": pending_transition}) if pending_transition is not None else None
            if _optional_lstat(temp_path) is not None and _safe_regular_bytes(temp_path)[0] == empty_bytes:
                _sync_directory(self.root)
                temp_path.unlink()
                _sync_directory(self.root)
            try:
                final_kind, final_lease = _locks_kind(final_bytes, empty_locks, lease_owner)
            except AdapterConflict:
                if old_owner is None:
                    raise
                old_kind, old_lease = _locks_kind(final_bytes, empty_locks, old_owner)
                if old_kind != "leased" or old_lease is None:
                    raise AdapterConflict("workflow locks are foreign")
                final_kind, final_lease = "old", None
            if _optional_lstat(temp_path) is not None:
                candidate_bytes, _ = _safe_regular_bytes(temp_path)
                candidate_kind, candidate_lease = _locks_kind(candidate_bytes, empty_locks, lease_owner)
                if candidate_kind != "leased" or candidate_lease is None:
                    raise AdapterConflict("workflow replacement lease temp conflicts")
                if pending_lease_id is not None and candidate_lease["lease_id"] != pending_lease_id:
                    raise AdapterConflict("workflow pending-transition lease temp conflicts")
            elif final_kind == "leased" and final_lease is not None and datetime.fromisoformat(final_lease["lease_expires_at"].replace("Z", "+00:00")) > now and (
                pending_transition is None
                or final_lease["lease_id"] == pending_lease_id
            ):
                _checkpoint("route_before_return")
                return state, final_lease, pending_transition, source_fresh, None
            else:
                issued_at = now.isoformat().replace("+00:00", "Z")
                candidate_lease = {
                    "lease_id": pending_lease_id or _value_hash({"workflow_id": state["workflow_id"], "state_hash": state["state_hash"], "frontier": frontier, "issued_at": issued_at}),
                    **lease_owner,
                    "lease_expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                }
                candidate_bytes = _compact_bytes({**empty_locks, "leases": [candidate_lease]}) + b"\n"
            _replace_fixed_mutable(
                self.root,
                "locks.json",
                ".locks.json.tmp",
                expected_bytes=final_bytes,
                candidate_bytes=candidate_bytes,
                checkpoint_prefix="route_lease",
            )
            _checkpoint("route_before_return")
            return state, candidate_lease, pending_transition, source_fresh, None

    def render_context(
        self,
        locator: dict[str, Any],
        current_source_identity: dict[str, Any],
        render: Callable[[dict[str, Any]], tuple[bytes, dict[str, Any], dict[str, Any]]],
        *,
        expected_state_version: int,
        expected_state_hash: str,
        expected_bundle_id: str,
        expected_policy_bundle_hash: str,
        expected_card_manifest_hash: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
        """Render the one fixed owner-disposable context projection without changing state."""
        with self._locked_state() as state:
            expected_locator = {
                "schema_version": "sqw-workflow-owner/1",
                "workflow_id": state["workflow_id"],
                "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                "bundle_id": state["bundle_id"],
                "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
                "scope_binding_id": state["scope_binding"]["binding_id"],
                "mode": state["mode"],
                "initial_root_binding_hash": _value_hash(state["bootstrap"]["initial_root_binding"]),
            }
            if locator != expected_locator:
                raise AdapterConflict("workflow locator does not bind this owner")
            if (
                state["bundle_id"] != expected_bundle_id
                or state["policy_bundle_hash"] != expected_policy_bundle_hash
                or state["card_manifest_hash"] != expected_card_manifest_hash
            ):
                raise AdapterConflict("workflow owner contract is stale")
            if current_source_identity != state["source_identity"]:
                raise AdapterSourceDrift("context render requires fresh source identity")
            if state["state_version"] != expected_state_version or state["state_hash"] != expected_state_hash:
                raise AdapterConflict("context render receipt is stale")
            if _optional_lstat(self.root / ".state.json.tmp") is not None:
                raise AdapterConflict("prepared card state blocks context render")
            self._validate_projection_surface(state, cleanup_matching_temp=False)
            payload, metadata, projection_locator = render(state)
            header = _projection_header(payload)
            frontier = state.get("active_frontier")
            if (
                not isinstance(frontier, dict)
                or header["workflow_id"] != state["workflow_id"]
                or header["state_version"] != state["state_version"]
                or header["state_hash"] != state["state_hash"]
                or header["frontier_decision_id"] != frontier["decision_id"]
                or header["frontier_card_id"] != frontier["card_id"]
                or header["frontier_card_hash"] != frontier["card_hash"]
                or header["renderer_hash"] != "sha256:" + sha256((Path(__file__).parent / "project_context.py").read_bytes()).hexdigest()
                or projection_locator != {
                    "schema_version": "content-locator/1",
                    "content_kind": "projection",
                    "artifact_id": "workflow-context",
                    "content_hash": "sha256:" + sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            ):
                raise AdapterConflict("rendered workflow context does not bind current owner")
            replayed = _publish_disposable_projection(self.root / "projections", payload)
            _checkpoint("projection_before_return")
            return state, metadata, projection_locator, replayed

    def complete_card(
        self,
        locator: dict[str, Any],
        previous_receipt: dict[str, Any],
        current_source_identity: dict[str, Any],
        completion: dict[str, Any],
        select_next: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        *,
        current_source_snapshot: dict[str, Any] | None = None,
        materialized_payload: bytes | None = None,
        content_locator: dict[str, Any] | None = None,
        expected_bundle_id: str,
        expected_policy_bundle_hash: str,
        expected_card_manifest_hash: str,
        expected_cards: dict[str, tuple[str, str]],
        now_value: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
        """Commit one inline or materialized card completion and its derived lease."""
        materialized = materialized_payload is not None or content_locator is not None
        if materialized != (materialized_payload is not None and content_locator is not None):
            raise AdapterConflict("materialized completion inputs are incomplete")
        if materialized:
            _validate_artifact_bytes(materialized_payload, content_locator)
            if content_locator["content_hash"] != completion.get("content_hash"):
                raise AdapterConflict("materialized completion hash is inconsistent")
        artifact_ready = False
        with self._locked_state() as state:
            expected_locator = {
                "schema_version": "sqw-workflow-owner/1",
                "workflow_id": state["workflow_id"],
                "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                "bundle_id": state["bundle_id"],
                "initial_source_identity_hash": state["bootstrap"]["initial_source_identity_hash"],
                "scope_binding_id": state["scope_binding"]["binding_id"],
                "mode": state["mode"],
                "initial_root_binding_hash": _value_hash(state["bootstrap"]["initial_root_binding"]),
            }
            if locator != expected_locator:
                raise AdapterConflict("workflow locator does not bind this owner")
            if (
                state["bundle_id"] != expected_bundle_id
                or state["policy_bundle_hash"] != expected_policy_bundle_hash
                or state["card_manifest_hash"] != expected_card_manifest_hash
            ):
                raise AdapterConflict("workflow owner contract is stale")
            self._validate_projection_surface(state, cleanup_matching_temp=False)
            if previous_receipt.get("owner_locator") != locator or previous_receipt.get("scope_binding") != state["scope_binding"]:
                raise AdapterConflict("card receipt does not bind this workflow owner")

            prior_version = previous_receipt.get("state_version")
            prior_hash = previous_receipt.get("state_hash")
            previous_frontier = previous_receipt.get("next_step")
            if not isinstance(prior_version, int) or not _is_hash(prior_hash) or not isinstance(previous_frontier, dict):
                raise AdapterConflict("card receipt lacks semantic CAS bindings")
            if previous_frontier.get("kind") != "card" or expected_cards.get(previous_frontier.get("card_id")) != (previous_frontier.get("card_path"), previous_frontier.get("card_hash")):
                raise AdapterConflict("card receipt frontier is stale")
            if completion.get("producer_card_id") != previous_frontier["card_id"] or completion.get("decision_id") != previous_frontier["decision_id"]:
                raise AdapterConflict("completion does not bind the routed card")
            if current_source_snapshot is None:
                if current_source_identity != state["source_identity"]:
                    raise AdapterSourceDrift("current source identity lacks a verifiable scoped snapshot")
                current_source_snapshot = state["source_snapshot"]
            if current_source_snapshot["identity_hash"] != current_source_identity["identity_hash"]:
                raise AdapterSourceDrift("current source snapshot does not bind its identity")
            pending_transition = previous_receipt.get("pending_source_transition")
            if completion.get("source_transition") != pending_transition:
                raise AdapterConflict("completion does not bind the routed source transition")
            precommit = state["state_version"] == prior_version and state["state_hash"] == prior_hash
            postcommit = state["state_version"] == prior_version + 1 and state["last_transition"]["prior_state_hash"] == prior_hash and state["last_transition"]["completion_id"] == completion["content_hash"]
            delivery_blocked_reason = None
            if precommit:
                calculated_transition = _eligible_source_transition(
                    state["source_snapshot"],
                    current_source_snapshot,
                    state["scope_binding"]["allowed_writes"],
                )
                if calculated_transition != pending_transition:
                    raise AdapterSourceDrift("card receipt source transition is stale")
            elif postcommit:
                if current_source_identity != state["source_identity"]:
                    try:
                        _eligible_source_transition(state["source_snapshot"], current_source_snapshot, state["scope_binding"]["allowed_writes"])
                        delivery_blocked_reason = "source-transition-unverifiable"
                    except AdapterSourceDrift as exc:
                        message = str(exc)
                        delivery_blocked_reason = "source-kind-or-root-changed" if "kind or root" in message else "source-revision-changed" if "HEAD or tree" in message else "source-out-of-scope"

            now = datetime.fromisoformat(now_value.replace("Z", "+00:00")) if now_value else datetime.now(timezone.utc)
            if now.tzinfo is None:
                raise AdapterConflict("workflow lease clock is invalid")
            empty_locks = {
                "schema_version": "sqw-locks/1",
                "workflow_id": state["workflow_id"],
                "bootstrap_operation_id": state["bootstrap"]["operation_id"],
                "scope_binding_id": state["scope_binding"]["binding_id"],
                "leases": [],
            }
            old_lease = previous_receipt.get("current_lease")
            if not isinstance(old_lease, dict):
                raise AdapterConflict("card receipt lacks its current lease")
            old_locks_bytes = _compact_bytes({**empty_locks, "leases": [old_lease]}) + b"\n"

            if precommit:
                if state.get("active_frontier") != previous_frontier:
                    raise AdapterConflict("card receipt does not bind the active frontier")
                final_locks, _ = _safe_regular_bytes(self.root / "locks.json")
                if final_locks != old_locks_bytes or _optional_lstat(self.root / ".locks.json.tmp") is not None:
                    raise AdapterConflict("current card lease is missing or has a precommit temp")
                try:
                    lease_expiry = datetime.fromisoformat(old_lease["lease_expires_at"].replace("Z", "+00:00"))
                except (KeyError, ValueError) as exc:
                    raise AdapterConflict("current card lease is invalid") from exc
                if lease_expiry.tzinfo is None or lease_expiry <= now:
                    raise AdapterConflict("current card lease expired")
                next_step = select_next(state, completion)
                next_decision_id = next_step["decision_id"]
                operation_id = _value_hash({
                    "contract_id": "sqw.complete.card/1",
                    "workflow_id": state["workflow_id"],
                    "prior_state_version": prior_version,
                    "prior_state_hash": prior_hash,
                    "completion_id": completion["content_hash"],
                    "next_decision_id": next_decision_id,
                })
                candidate = json.loads(json.dumps(state))
                if materialized:
                    completion_entry = {
                        "storage": "materialized",
                        "operation_id": operation_id,
                        "prior_state_version": prior_version,
                        "prior_state_hash": prior_hash,
                        "completion_id": completion["content_hash"],
                        "card_id": completion["producer_card_id"],
                        "artifact_id": completion["artifact_id"],
                        "source_hash": current_source_identity["identity_hash"],
                        "scope_binding_id": state["scope_binding"]["binding_id"],
                        "content_locator": content_locator,
                        "outcome": completion["outcome"],
                    }
                else:
                    completion_entry = {
                        "storage": "inline",
                        "operation_id": operation_id,
                        "prior_state_version": prior_version,
                        "prior_state_hash": prior_hash,
                        "completion": completion,
                    }
                candidate["card_completions"].append(completion_entry)
                candidate["state_version"] = prior_version + 1
                if pending_transition is not None:
                    candidate["source_identity"] = current_source_identity
                    candidate["source_snapshot"] = current_source_snapshot
                    candidate["source"]["observed_revision"] = current_source_identity["identity_hash"]
                candidate["status"] = "completed" if next_step["kind"] == "terminal" else "active"
                candidate["active_frontier"] = None if next_step["kind"] == "terminal" else next_step
                candidate["last_transition"] = {
                    "transition_kind": "card",
                    "operation_id": operation_id,
                    "prior_state_version": prior_version,
                    "prior_state_hash": prior_hash,
                    "completion_id": completion["content_hash"],
                    "next_decision_id": next_decision_id,
                }
                candidate["state_hash"] = _value_hash({key: value for key, value in candidate.items() if key != "state_hash"})
                violations = validate_state(candidate, self.state_schema) + validate_transition(state, candidate)
                if violations:
                    raise AdapterConflict("candidate workflow state is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
                state_bytes, candidate_bytes = _safe_regular_bytes(self.state_path)[0], _compact_bytes(candidate) + b"\n"
                if materialized:
                    state_temp = self.root / ".state.json.tmp"
                    if _optional_lstat(state_temp) is None:
                        _write_and_fsync(state_temp, candidate_bytes, "card_state_temp_fsynced")
                    else:
                        prepared_bytes, prepared_info = _safe_regular_bytes(state_temp)
                        if prepared_bytes != candidate_bytes or stat.S_IMODE(prepared_info.st_mode) != 0o600 or prepared_info.st_nlink != 1:
                            raise AdapterConflict("prepared card state conflicts")
                    final_name, temp_name = _artifact_names(content_locator)
                    _publish_bootstrap_file(
                        self.root / "artifacts",
                        final_name,
                        temp_name,
                        materialized_payload,
                        checkpoint_prefix="card_artifact",
                    )
                    artifact_ready = True
                _replace_fixed_mutable(
                    self.root,
                    "state.json",
                    ".state.json.tmp",
                    expected_bytes=state_bytes,
                    candidate_bytes=candidate_bytes,
                    checkpoint_prefix="card_state",
                )
                state = candidate
            elif postcommit:
                expected_operation = _value_hash({
                    "contract_id": "sqw.complete.card/1",
                    "workflow_id": state["workflow_id"],
                    "prior_state_version": prior_version,
                    "prior_state_hash": prior_hash,
                    "completion_id": completion["content_hash"],
                    "next_decision_id": state["last_transition"]["next_decision_id"],
                })
                if state["last_transition"]["operation_id"] != expected_operation:
                    raise AdapterConflict("committed card transition is a fork")
                matches = [entry for entry in state["card_completions"] if entry["operation_id"] == expected_operation]
                if len(matches) != 1 or (matches[0]["storage"] == "materialized") != materialized:
                    raise AdapterConflict("committed completion persistence is a fork")
                if materialized and matches[0]["content_locator"] != content_locator:
                    raise AdapterConflict("committed materialized completion is a fork")
                if _optional_lstat(self.root / ".state.json.tmp") is not None:
                    temp_bytes, _ = _safe_regular_bytes(self.root / ".state.json.tmp")
                    if temp_bytes != _compact_bytes(state) + b"\n":
                        raise AdapterConflict("committed card state temp conflicts")
                    _sync_directory(self.root)
                    (self.root / ".state.json.tmp").unlink()
                    _sync_directory(self.root)
            else:
                raise AdapterConflict("workflow state advanced beyond the card receipt")

            if materialized and not artifact_ready:
                final_name, temp_name = _artifact_names(content_locator)
                _publish_bootstrap_file(
                    self.root / "artifacts",
                    final_name,
                    temp_name,
                    materialized_payload,
                    checkpoint_prefix="card_artifact",
                )

            frontier = state.get("active_frontier")
            final_locks, _ = _safe_regular_bytes(self.root / "locks.json")
            temp_path = self.root / ".locks.json.tmp"
            temp_exists = _optional_lstat(temp_path) is not None
            outcome = "committed" if precommit else "replayed"
            empty_bytes = _compact_bytes(empty_locks) + b"\n"
            if delivery_blocked_reason is not None:
                new_owner = {"producer_id": frontier["card_id"], "decision_id": frontier["decision_id"]} if isinstance(frontier, dict) else None
                if final_locks not in {old_locks_bytes, empty_bytes}:
                    if new_owner is None:
                        raise AdapterConflict("postcommit blocked locks are foreign")
                    final_kind, final_lease = _locks_kind(final_locks, empty_locks, new_owner)
                    if final_kind != "leased" or final_lease is None:
                        raise AdapterConflict("postcommit blocked locks are foreign")
                if temp_exists:
                    temp_bytes, _ = _safe_regular_bytes(temp_path)
                    if temp_bytes != empty_bytes:
                        if new_owner is None:
                            raise AdapterConflict("postcommit blocked locks temp conflicts")
                        temp_kind, temp_lease = _locks_kind(temp_bytes, empty_locks, new_owner)
                        if temp_kind != "leased" or temp_lease is None:
                            raise AdapterConflict("postcommit blocked locks temp conflicts")
                        _sync_directory(self.root)
                        temp_path.unlink()
                        _sync_directory(self.root)
                _replace_fixed_mutable(
                    self.root,
                    "locks.json",
                    ".locks.json.tmp",
                    expected_bytes=final_locks,
                    candidate_bytes=empty_bytes,
                    checkpoint_prefix="card_locks",
                )
                _checkpoint("card_before_return")
                return state, None, f"replayed_blocked:{delivery_blocked_reason}"
            if frontier is None:
                candidate_lease = None
                candidate_locks = empty_bytes
            else:
                new_owner = {"producer_id": frontier["card_id"], "decision_id": frontier["decision_id"]}
                candidate_lease = None
                if temp_exists and _safe_regular_bytes(temp_path)[0] == empty_bytes:
                    _sync_directory(self.root)
                    temp_path.unlink()
                    _sync_directory(self.root)
                    temp_exists = False
                if temp_exists:
                    candidate_locks, _ = _safe_regular_bytes(temp_path)
                    _, candidate_lease = _locks_kind(candidate_locks, empty_locks, new_owner)
                elif final_locks != old_locks_bytes:
                    if final_locks != empty_bytes:
                        _, candidate_lease = _locks_kind(final_locks, empty_locks, new_owner)
                    if candidate_lease is not None and datetime.fromisoformat(candidate_lease["lease_expires_at"].replace("Z", "+00:00")) > now:
                        _checkpoint("card_before_return")
                        return state, candidate_lease, outcome
                if candidate_lease is None:
                    issued_at = now.isoformat().replace("+00:00", "Z")
                    candidate_lease = {
                        "lease_id": _value_hash({"workflow_id": state["workflow_id"], "state_hash": state["state_hash"], "frontier": frontier, "issued_at": issued_at}),
                        **new_owner,
                        "lease_expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    }
                    candidate_locks = _compact_bytes({**empty_locks, "leases": [candidate_lease]}) + b"\n"
            _replace_fixed_mutable(
                self.root,
                "locks.json",
                ".locks.json.tmp",
                expected_bytes=final_locks,
                candidate_bytes=candidate_locks,
                checkpoint_prefix="card_locks",
            )
            _checkpoint("card_before_return")
            return state, candidate_lease, outcome


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
