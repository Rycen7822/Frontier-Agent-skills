#!/usr/bin/env python3
"""Shared stdlib-only helpers for writing-plans state tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from copy import deepcopy
from datetime import datetime
from contextlib import contextmanager
from fnmatch import fnmatchcase
from hashlib import sha256
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Callable, Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 40
MAX_COLLECTION_ITEMS = 1000
PROGRAM_STATE_MAX_BYTES = 65_536
PROGRAM_STATE_LIVE_MAX_BYTES = 57_344
PROGRAM_TRANSITION_MAX_BYTES = 8_192
INLINE_RENDER_MAX_BYTES = 8_192
RUNTIME_PROJECTION_MAX_BYTES = 6_144


def _checkpoint(_name: str) -> None:
    return
LOCAL_ID_RE = re.compile(r"^(I|F|D|E|P|R|G|X|AP|S)-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXTERNAL_REF_RE = re.compile(r"^[a-z_]+:[A-Za-z0-9._:-]+#[A-Za-z0-9._-]+$")
SECRET_LIKE_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*[\"']?[^\s,\"'}]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
CONTROLLED_SECRET_POINTER = re.compile(
    r"(?i)^(?:env|vault|secret|keyring|credential)(?:://|:)[A-Za-z0-9_./@-]+$"
)
VERIFIER_REF_SCHEMES = {"command", "path", "pytest", "schema", "script", "test"}


class PlanInputError(ValueError):
    pass


class ProgramOwnerConflict(PlanInputError):
    pass


class ProgramStateAdvanced(ProgramOwnerConflict):
    pass


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str
    object_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if result["object_id"] is None:
            result.pop("object_id")
        return result


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _check_bounds(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise PlanInputError(f"input nesting exceeds {MAX_DEPTH}")
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PlanInputError(f"object exceeds {MAX_COLLECTION_ITEMS} items")
        for child in value.values():
            _check_bounds(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PlanInputError(f"array exceeds {MAX_COLLECTION_ITEMS} items")
        for child in value:
            _check_bounds(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise PlanInputError("non-finite JSON number is not allowed")


def load_json(path: str | Path) -> Any:
    source = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise PlanInputError(f"input is not a regular file: {source}")
            if metadata.st_size > MAX_INPUT_BYTES:
                raise PlanInputError(f"input is {metadata.st_size} bytes; maximum is {MAX_INPUT_BYTES}")
            payload = stream.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise PlanInputError(f"input exceeds maximum of {MAX_INPUT_BYTES} bytes")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError, PlanInputError) as exc:
        raise PlanInputError(str(exc)) from exc
    _check_bounds(value)
    return value


def pointer(parts: Iterable[str | int]) -> str:
    escaped = [str(p).replace("~", "~0").replace("/", "~1") for p in parts]
    return "/" + "/".join(escaped) if escaped else ""


def canonical_state_hash(state: dict[str, Any]) -> str:
    clean = dict(state)
    clean.pop("content_hash", None)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def canonical_object_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def normalize_enqueue_requests(
    requests: list[dict[str, Any]],
    *,
    domain: str,
    initialization_id: str | None = None,
    plan_id: str | None = None,
    prior_content_hash: str | None = None,
    completion_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if domain not in {"initial", "derived"} or not isinstance(requests, list) or len(requests) > MAX_COLLECTION_ITEMS:
        raise PlanInputError("enqueue request list is invalid")
    if domain == "initial" and not initialization_id:
        raise PlanInputError("initial enqueue requires initialization_id")
    if domain == "derived" and not all((plan_id, prior_content_hash, completion_id)):
        raise PlanInputError("derived enqueue requires plan and completion identity")
    specs: list[dict[str, Any]] = []
    instances: list[dict[str, Any]] = []
    ids: set[str] = set()
    for ordinal, request in enumerate(requests):
        if not isinstance(request, dict) or set(request) != {"decision_id", "subject_ref"}:
            raise PlanInputError("enqueue requests contain only decision_id and subject_ref")
        decision_id = request.get("decision_id")
        subject_ref = request.get("subject_ref")
        if not isinstance(decision_id, str) or not decision_id.startswith("wp.select."):
            raise PlanInputError("enqueue decision_id is invalid")
        if subject_ref is not None and (not isinstance(subject_ref, str) or not LOCAL_ID_RE.fullmatch(subject_ref) or not subject_ref.startswith("P-")):
            raise PlanInputError("enqueue subject_ref must be a local plan node or null")
        spec = {"ordinal": ordinal, "decision_id": decision_id, "subject_ref": subject_ref}
        if domain == "initial":
            identity = {
                "domain": "wp-initial-card-instance/1",
                "initialization_id": initialization_id,
                **spec,
            }
        else:
            identity = {
                "domain": "wp-enqueued-card-instance/1",
                "plan_id": plan_id,
                "prior_content_hash": prior_content_hash,
                "completion_id": completion_id,
                **spec,
            }
        card_instance_id = canonical_object_hash(identity)
        if card_instance_id in ids:
            raise PlanInputError("derived card instance IDs must be unique")
        ids.add(card_instance_id)
        specs.append(spec)
        instances.append({"card_instance_id": card_instance_id, "decision_id": decision_id, "subject_ref": subject_ref})
    return specs, instances


def _apply_typed_operations(candidate: dict[str, Any], operations: list[dict[str, Any]]) -> None:
    collections = {"approvals", "facts", "decisions", "evidence", "nodes", "edges", "risks", "gaps", "snapshots", "global_invariants", "policy_claims"}
    replaceable = {"status", "current_frontier", "completion", "rollback"}
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) != {"operation", "target", "value"}:
            raise PlanInputError("typed plan operation is invalid")
        kind = operation["operation"]
        target = operation["target"]
        value = deepcopy(operation["value"])
        if kind == "replace_field" and target in replaceable:
            candidate[target] = value
        elif kind == "upsert_by_identity" and target in collections:
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise PlanInputError("upsert_by_identity requires a typed object ID")
            current = candidate[target]
            matches = [index for index, item in enumerate(current) if isinstance(item, dict) and item.get("id") == value["id"]]
            if len(matches) > 1:
                raise PlanInputError("upsert target identity is duplicated")
            if matches:
                current[matches[0]] = value
            else:
                current.append(value)
        elif kind == "rebind_source":
            raise PlanInputError("rebind_source is CLI-derived and cannot be model supplied")
        else:
            raise PlanInputError("operation target is not model writable")


def canonical_completion_id(completion: dict[str, Any]) -> str:
    if not isinstance(completion, dict):
        raise PlanInputError("canonical completion is invalid")
    body = deepcopy(completion)
    declared = body.pop("content_hash", None)
    completion_id = canonical_object_hash(body)
    if declared is not None and declared != completion_id:
        raise PlanInputError("canonical completion hash is invalid")
    return completion_id


def card_transition_identity(
    *,
    plan_id: str,
    prior_state_version: int,
    prior_content_hash: str,
    scope_binding_id: str,
    completed_card_instance_id: str,
    completion: dict[str, Any],
    operations: list[dict[str, Any]],
    enqueue_requests: list[dict[str, Any]],
    source_identity: dict[str, Any] | None,
    artifact_entry: dict[str, Any] | None,
    inline_render_completion: dict[str, Any] | None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]:
    completion_id = canonical_completion_id(completion)
    specs, derived = normalize_enqueue_requests(
        enqueue_requests,
        domain="derived",
        plan_id=plan_id,
        prior_content_hash=prior_content_hash,
        completion_id=completion_id,
    )
    operation_identity = {
        "contract_id": "wp.apply-card-transition/1",
        "plan_id": plan_id,
        "prior_state_version": prior_state_version,
        "prior_content_hash": prior_content_hash,
        "scope_binding_id": scope_binding_id,
        "completed_card_instance_id": completed_card_instance_id,
        "completion": completion,
        "operations": operations,
        "enqueue_specs": specs,
        "enqueued_card_instance_ids": [item["card_instance_id"] for item in derived],
        "source_identity": source_identity,
        "artifact_entry": artifact_entry,
        "inline_render_completion": inline_render_completion,
    }
    return completion_id, specs, derived, canonical_object_hash(operation_identity)


def apply_card_transition(
    state: dict[str, Any],
    *,
    expected_state_version: int,
    expected_content_hash: str,
    scope_binding_id: str,
    completed_card_instance_id: str,
    completion: dict[str, Any],
    operations: list[dict[str, Any]],
    enqueue_requests: list[dict[str, Any]],
    source_identity: dict[str, Any] | None = None,
    artifact_entry: dict[str, Any] | None = None,
    inline_render_completion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if state.get("schema_version") != "3.0" or state.get("profile") != "program":
        raise PlanInputError("card transition requires Program state 3.0")
    if state.get("content_hash") != canonical_state_hash(state):
        raise PlanInputError("current Program content hash is invalid")
    if (state.get("state_version"), state.get("content_hash")) != (expected_state_version, expected_content_hash):
        raise PlanInputError("Program receipt is stale")
    if state.get("scope_binding", {}).get("binding_id") != scope_binding_id:
        raise PlanInputError("Program transition scope binding is stale")
    queue = state.get("pending_card_instances", [])
    if not queue or queue[0].get("card_instance_id") != completed_card_instance_id:
        raise PlanInputError("Program completion does not bind the queue head")
    completion_id, specs, derived, operation_id = card_transition_identity(
        plan_id=state["plan_id"],
        prior_state_version=state["state_version"],
        prior_content_hash=state["content_hash"],
        scope_binding_id=scope_binding_id,
        completed_card_instance_id=completed_card_instance_id,
        completion=completion,
        operations=operations,
        enqueue_requests=enqueue_requests,
        source_identity=source_identity,
        artifact_entry=artifact_entry,
        inline_render_completion=inline_render_completion,
    )
    candidate = deepcopy(state)
    candidate["pending_card_instances"] = deepcopy(queue[1:])
    _apply_typed_operations(candidate, operations)
    if source_identity is not None:
        if not isinstance(source_identity, dict):
            raise PlanInputError("CLI source identity is invalid")
        candidate["source_identity"] = deepcopy(source_identity)
    existing_ids = {item["card_instance_id"] for item in candidate["pending_card_instances"]}
    if any(item["card_instance_id"] in existing_ids for item in derived):
        raise PlanInputError("derived card instance ID duplicates the pending queue")
    candidate["pending_card_instances"].extend(derived)
    if artifact_entry is not None:
        if not isinstance(artifact_entry, dict) or artifact_entry.get("completion_id") != completion_id:
            raise PlanInputError("artifact entry does not bind the completion")
        if any(item.get("completion_id") == completion_id for item in candidate.get("artifacts", [])):
            raise PlanInputError("artifact completion is already registered")
        candidate["artifacts"].append(deepcopy(artifact_entry))
    if inline_render_completion is not None:
        inline_bytes = canonical_bytes(inline_render_completion)
        runtime_bytes = canonical_bytes(inline_render_completion.get("runtime_projection")) if isinstance(inline_render_completion, dict) else b""
        if len(inline_bytes) > INLINE_RENDER_MAX_BYTES or len(runtime_bytes) > RUNTIME_PROJECTION_MAX_BYTES:
            raise PlanInputError("inline render completion exceeds its budget")
    candidate["state_version"] = state["state_version"] + 1
    candidate["last_transition"] = {
        "transition_kind": "card",
        "operation_id": operation_id,
        "prior_state_version": state["state_version"],
        "prior_content_hash": state["content_hash"],
        "scope_binding_id": scope_binding_id,
        "completion_id": completion_id,
        "completed_card_instance_id": completed_card_instance_id,
        "enqueued_card_instance_ids": [item["card_instance_id"] for item in derived],
        "inline_render_completion": deepcopy(inline_render_completion),
    }
    candidate["content_hash"] = canonical_state_hash(candidate)
    rendered = canonical_bytes(candidate) + b"\n"
    terminal = candidate.get("status") in {"blocked", "completed", "superseded"} and not candidate["pending_card_instances"]
    limit = PROGRAM_STATE_MAX_BYTES if terminal else PROGRAM_STATE_LIVE_MAX_BYTES
    if len(rendered) > limit:
        raise PlanInputError("Program state exceeds its semantic budget")
    transition_growth = max(0, len(rendered) - len(canonical_bytes(state) + b"\n"))
    if transition_growth > PROGRAM_TRANSITION_MAX_BYTES:
        raise PlanInputError("Program transition exceeds its byte budget")
    schema = load_json(Path(__file__).resolve().parents[1] / "schemas" / "plan-state.schema.json")
    schema_errors = validate_against_schema(candidate, schema)
    if schema_errors:
        raise PlanInputError("candidate Program state violates schema")
    from validate_plan_state import semantic_violations

    semantic_errors = semantic_violations(candidate)
    if semantic_errors:
        raise PlanInputError("candidate Program state violates semantic invariants")
    return candidate


def _program_safe_bytes(path: Path, *, links: set[int] = {1}) -> tuple[bytes, os.stat_result]:
    try:
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink not in links:
            raise ProgramOwnerConflict(f"unsafe Program owner file: {path.name}")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            payload = os.read(descriptor, PROGRAM_STATE_MAX_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ProgramOwnerConflict(f"Program owner file is unavailable: {path.name}") from exc
    if len(payload) > PROGRAM_STATE_MAX_BYTES:
        raise ProgramOwnerConflict(f"Program owner file exceeds budget: {path.name}")
    return payload, info


def _program_sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _program_write_temp(path: Path, payload: bytes, checkpoint: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    _checkpoint(checkpoint)


def _program_publish_immutable(root: Path, final_name: str, temp_name: str, payload: bytes, *, prefix: str) -> bool:
    final = root / final_name
    temporary = root / temp_name
    final_exists = final.exists() or final.is_symlink()
    temp_exists = temporary.exists() or temporary.is_symlink()
    if final_exists:
        final_payload, final_info = _program_safe_bytes(final, links={1, 2})
        if final_payload != payload:
            raise ProgramOwnerConflict(f"Program {final_name} belongs to another operation")
        if temp_exists:
            temp_payload, temp_info = _program_safe_bytes(temporary, links={1, 2})
            if temp_payload != payload or (final_info.st_dev, final_info.st_ino) != (temp_info.st_dev, temp_info.st_ino):
                raise ProgramOwnerConflict(f"Program {temp_name} conflicts")
            _program_sync_directory(root)
            temporary.unlink()
            _checkpoint(f"{prefix}_cleaned")
            _program_sync_directory(root)
            _checkpoint(f"{prefix}_cleanup_parent_synced")
        else:
            _program_sync_directory(root)
        return True
    if not temp_exists:
        _program_write_temp(temporary, payload, f"{prefix}_temp_fsynced")
    else:
        temp_payload, _ = _program_safe_bytes(temporary)
        if temp_payload != payload:
            raise ProgramOwnerConflict(f"Program {temp_name} conflicts")
    os.link(temporary, final, follow_symlinks=False)
    _checkpoint(f"{prefix}_linked")
    _program_sync_directory(root)
    _checkpoint(f"{prefix}_link_parent_synced")
    temporary.unlink()
    _checkpoint(f"{prefix}_cleaned")
    _program_sync_directory(root)
    _checkpoint(f"{prefix}_cleanup_parent_synced")
    return False


def _program_validate_root(root: Path, source_root: Path) -> tuple[Path, dict[str, int], dict[str, int]]:
    try:
        info = root.lstat()
        source_info = source_root.lstat()
        resolved = root.resolve(strict=True)
        source = source_root.resolve(strict=True)
    except OSError as exc:
        raise ProgramOwnerConflict("Program root is unavailable") from exc
    if (
        root.is_symlink()
        or source_root.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or not stat.S_ISDIR(source_info.st_mode)
        or resolved != root.absolute()
        or source != source_root.absolute()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
        or resolved == source
        or resolved.is_relative_to(source)
        or source.is_relative_to(resolved)
    ):
        raise ProgramOwnerConflict("Program root is unsafe")
    root_binding = {"dev": info.st_dev, "ino": info.st_ino, "uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)}
    source_binding = {"dev": source_info.st_dev, "ino": source_info.st_ino}
    return resolved, root_binding, source_binding


def _program_lock_header(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wp-lock/1",
        "plan_id": state["plan_id"],
        "initialization_id": state["initialization"]["initialization_id"],
        "initial_root_binding_hash": canonical_object_hash(state["initial_root_binding"]),
        "established_root_identity_hash": canonical_object_hash(state["established_root_identity"]),
        "planning_scope_binding_id": state["scope_binding"]["binding_id"],
    }


def _program_validate_candidate(state: dict[str, Any]) -> None:
    schema = load_json(Path(__file__).resolve().parents[1] / "schemas" / "plan-state.schema.json")
    errors = validate_against_schema(state, schema)
    if errors:
        raise ProgramOwnerConflict("Program candidate violates schema")
    from validate_plan_state import semantic_violations

    if semantic_violations(state):
        raise ProgramOwnerConflict("Program candidate violates semantic invariants")
    if state["content_hash"] != canonical_state_hash(state):
        raise ProgramOwnerConflict("Program candidate content hash is invalid")


def initialize_program_owner(root: Path, source_root: Path, candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Create or replay the one Program owner without creating its external root."""
    resolved, root_binding, source_binding = _program_validate_root(root, source_root)
    _program_validate_candidate(candidate)
    if candidate["state_version"] != 1 or candidate["last_transition"]["transition_kind"] != "init":
        raise ProgramOwnerConflict("Program initialization candidate must be version 1")
    if candidate["initial_root_binding"] != root_binding or candidate["established_root_identity"] != root_binding or candidate["source_root_binding"] != source_binding:
        raise ProgramOwnerConflict("Program initialization root binding is stale")
    if candidate["source_identity"]["root_binding"] != source_binding:
        raise ProgramOwnerConflict("Program initialization source binding is stale")
    lock_payload = canonical_bytes(_program_lock_header(candidate)) + b"\n"
    state_payload = canonical_bytes(candidate) + b"\n"
    allowed = {
        ".plan-state.lock",
        ".plan-state.lock.tmp",
        "plan-state.json",
        ".plan-state.tmp",
        "artifacts",
        "projections",
    }
    names = {path.name for path in resolved.iterdir()}
    if names - allowed:
        raise ProgramOwnerConflict("Program root contains foreign entries")
    if "projections" in names and "artifacts" not in names:
        raise ProgramOwnerConflict("Program directories were created out of order")
    for directory_name in ("artifacts", "projections"):
        directory = resolved / directory_name
        if directory_name in names:
            info = directory.lstat()
            if directory.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700 or any(directory.iterdir()):
                raise ProgramOwnerConflict(f"Program {directory_name} directory conflicts")
    final_state = resolved / "plan-state.json"
    state_committed = False
    if final_state.exists() or final_state.is_symlink():
        observed, _ = _program_safe_bytes(final_state, links={1, 2})
        if observed == state_payload:
            state_committed = True
        else:
            try:
                current = json.loads(observed)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ProgramOwnerConflict("Program state conflicts") from exc
            if current.get("plan_id") == candidate["plan_id"] and current.get("state_version", 0) > 1:
                raise ProgramStateAdvanced("Program owner already advanced")
            raise ProgramOwnerConflict("Program state conflicts")
    _program_publish_immutable(resolved, ".plan-state.lock", ".plan-state.lock.tmp", lock_payload, prefix="plan_lock")
    lock_descriptor = os.open(resolved / ".plan-state.lock", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        if fcntl is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        if _program_safe_bytes(resolved / ".plan-state.lock")[0] != lock_payload:
            raise ProgramOwnerConflict("Program lock header conflicts")
        state_temp = resolved / ".plan-state.tmp"
        if state_temp.exists() or state_temp.is_symlink():
            temp_payload, temp_info = _program_safe_bytes(state_temp, links={1, 2})
            if temp_payload != state_payload:
                raise ProgramOwnerConflict("prepared Program initialization conflicts")
            if state_committed:
                final_info = (resolved / "plan-state.json").lstat()
                if (temp_info.st_dev, temp_info.st_ino) != (final_info.st_dev, final_info.st_ino):
                    raise ProgramOwnerConflict("committed Program initialization temp conflicts")
        elif not state_committed:
            _program_write_temp(state_temp, state_payload, "plan_state_temp_fsynced")
        for directory_name in ("artifacts", "projections"):
            directory = resolved / directory_name
            if not directory.exists():
                directory.mkdir(mode=0o700)
                _checkpoint(f"plan_{directory_name}_created")
                _program_sync_directory(resolved)
        replayed = _program_publish_immutable(resolved, "plan-state.json", ".plan-state.tmp", state_payload, prefix="plan_state")
    finally:
        if fcntl is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
    locator = {
        "schema_version": "wp-program-owner/1",
        "plan_id": candidate["plan_id"],
        "initialization_id": candidate["initialization"]["initialization_id"],
        "bundle_id": candidate["bundle_id"],
        "initial_source_identity_hash": candidate["scope_binding"]["initial_source_identity_hash"],
        "planning_scope_binding_id": candidate["scope_binding"]["binding_id"],
    }
    _checkpoint("plan_init_before_return")
    return candidate, locator, replayed


def _program_locator(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "wp-program-owner/1",
        "plan_id": state["plan_id"],
        "initialization_id": state["initialization"]["initialization_id"],
        "bundle_id": state["bundle_id"],
        "initial_source_identity_hash": state["scope_binding"]["initial_source_identity_hash"],
        "planning_scope_binding_id": state["scope_binding"]["binding_id"],
    }


def _program_artifact_names(locator: dict[str, Any]) -> tuple[str, str]:
    artifact_id = locator.get("artifact_id")
    content_hash = locator.get("content_hash")
    if not isinstance(artifact_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", artifact_id) or not isinstance(content_hash, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash):
        raise ProgramOwnerConflict("Program artifact locator is invalid")
    final = f"{artifact_id}.{content_hash[7:]}.json"
    return final, f".{final}.tmp"


def _program_registered_artifacts(state: dict[str, Any], root: Path) -> set[str]:
    expected: set[str] = set()
    for entry in state.get("artifacts", []):
        locator = entry["content_locator"]
        final_name, _ = _program_artifact_names(locator)
        if final_name in expected:
            raise ProgramOwnerConflict("Program artifact filename is duplicated")
        expected.add(final_name)
        payload, _ = _program_safe_bytes(root / final_name)
        if len(payload) != locator["bytes"] or "sha256:" + sha256(payload).hexdigest() != locator["content_hash"]:
            raise ProgramOwnerConflict("Program hard artifact is missing or stale")
    return expected


@contextmanager
def _locked_program_owner(root: Path, source_root: Path, locator: dict[str, Any]) -> Iterable[tuple[Path, dict[str, Any]]]:
    resolved, root_binding, source_binding = _program_validate_root(root, source_root)
    allowed = {".plan-state.lock", "plan-state.json", ".plan-state.tmp", "artifacts", "projections"}
    names = {path.name for path in resolved.iterdir()}
    if names - allowed or not {".plan-state.lock", "plan-state.json", "artifacts", "projections"} <= names:
        raise ProgramOwnerConflict("established Program owner inventory conflicts")
    for directory_name in ("artifacts", "projections"):
        directory = resolved / directory_name
        info = directory.lstat()
        if directory.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ProgramOwnerConflict(f"Program {directory_name} directory conflicts")
    lock_descriptor = os.open(resolved / ".plan-state.lock", os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        if fcntl is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        state_payload, _ = _program_safe_bytes(resolved / "plan-state.json")
        try:
            state = json.loads(state_payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProgramOwnerConflict("Program state is invalid JSON") from exc
        _program_validate_candidate(state)
        if state["initial_root_binding"] != root_binding or state["established_root_identity"] != root_binding or state["source_root_binding"] != source_binding:
            raise ProgramOwnerConflict("Program owner root binding changed")
        if locator != _program_locator(state):
            raise ProgramOwnerConflict("Program locator does not bind this owner")
        lock_payload, _ = _program_safe_bytes(resolved / ".plan-state.lock")
        if lock_payload != canonical_bytes(_program_lock_header(state)) + b"\n":
            raise ProgramOwnerConflict("Program lock header does not bind state")
        _program_registered_artifacts(state, resolved / "artifacts")
        yield resolved, state
    finally:
        if fcntl is not None:
            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def _source_identity_status(state: dict[str, Any], current: dict[str, Any]) -> str:
    schema = load_json(Path(__file__).resolve().parents[1] / "schemas" / "plan-state.schema.json")
    probe = {"$schema": schema.get("$schema"), "$defs": schema["$defs"], "$ref": "#/$defs/source_identity"}
    if validate_against_schema(current, probe):
        raise ProgramOwnerConflict("current Program source identity is invalid")
    previous = state["source_identity"]
    if current == previous:
        return "fresh"
    immutable_fields = ("kind", "root_binding", "head_commit", "head_tree", "exterior_guard_hash")
    if any(current[field] != previous[field] for field in immutable_fields):
        return "blocked"
    previous_records = {record["path"]: record for record in previous["scoped_records"]}
    current_records = {record["path"]: record for record in current["scoped_records"]}
    if len(previous_records) != len(previous["scoped_records"]) or len(current_records) != len(current["scoped_records"]):
        return "blocked"
    changed_paths = {
        path
        for path in previous_records.keys() | current_records.keys()
        if previous_records.get(path) != current_records.get(path)
    }
    allowed_reads = state["scope_binding"]["allowed_reads"]
    if not changed_paths or any(not any(fnmatchcase(path, pattern) for pattern in allowed_reads) for path in changed_paths):
        return "blocked"
    if not state["pending_card_instances"]:
        return "terminal_stale"
    return "source_rebind_required"


def _program_projection_payload(
    state: dict[str, Any],
    *,
    kind: str,
    body: bytes,
    renderer_contract_hash: str,
    completion_id: str,
) -> bytes:
    if kind not in {"program", "context-capsule"} or not re.fullmatch(r"sha256:[0-9a-f]{64}", renderer_contract_hash):
        raise ProgramOwnerConflict("Program projection contract is invalid")
    header = {
        "schema_version": "wp-owner-projection/1",
        "projection_kind": kind,
        "plan_id": state["plan_id"],
        "state_version": state["state_version"],
        "content_hash": state["content_hash"],
        "completion_id": completion_id,
        "renderer_contract_hash": renderer_contract_hash,
    }
    payload = b"<!-- " + canonical_bytes(header) + b" -->\n" + body
    if len(payload) > 8192:
        raise ProgramOwnerConflict("Program projection exceeds 8192 bytes")
    return payload


def _program_projection_header(payload: bytes) -> dict[str, Any]:
    first = payload.split(b"\n", 1)[0]
    if not first.startswith(b"<!-- ") or not first.endswith(b" -->"):
        raise ProgramOwnerConflict("Program projection header is invalid")
    try:
        header = json.loads(first[5:-4])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProgramOwnerConflict("Program projection header is invalid") from exc
    required = {"schema_version", "projection_kind", "plan_id", "state_version", "content_hash", "completion_id", "renderer_contract_hash"}
    if not isinstance(header, dict) or set(header) != required or header.get("schema_version") != "wp-owner-projection/1":
        raise ProgramOwnerConflict("Program projection header is invalid")
    return header


def _program_validate_projection_directory(
    root: Path,
    plan_id: str,
    *,
    allow_matching_temp: tuple[str, bytes] | None = None,
    allow_current_temp: tuple[int, str] | None = None,
) -> None:
    allowed = {"program.md", "program.md.tmp", "context-capsule.md", "context-capsule.md.tmp"}
    names = {path.name for path in root.iterdir()}
    if names - allowed:
        raise ProgramOwnerConflict("Program projection directory contains foreign entries")
    for name in names:
        payload, _ = _program_safe_bytes(root / name)
        header = _program_projection_header(payload)
        if header.get("plan_id") != plan_id:
            raise ProgramOwnerConflict("Program projection belongs to another owner")
        if name.endswith(".tmp"):
            exact = allow_matching_temp is not None and name == allow_matching_temp[0] and payload == allow_matching_temp[1]
            current = allow_current_temp is not None and (header.get("state_version"), header.get("content_hash")) == allow_current_temp
            if not exact and not current:
                raise ProgramOwnerConflict("Program projection temp conflicts")


def _program_publish_projection(root: Path, kind: str, payload: bytes) -> bool:
    final = root / f"{kind}.md"
    temporary = root / f"{kind}.md.tmp"
    final_payload = _program_safe_bytes(final)[0] if final.exists() or final.is_symlink() else None
    if temporary.exists() or temporary.is_symlink():
        if _program_safe_bytes(temporary)[0] != payload:
            raise ProgramOwnerConflict("Program projection temp conflicts")
    if final_payload == payload:
        if temporary.exists() or temporary.is_symlink():
            _program_sync_directory(root)
            temporary.unlink()
            _program_sync_directory(root)
        return True
    if not (temporary.exists() or temporary.is_symlink()):
        _program_write_temp(temporary, payload, f"{kind}_projection_temp_fsynced")
    os.replace(temporary, final)
    _checkpoint(f"{kind}_projection_replaced")
    _program_sync_directory(root)
    _checkpoint(f"{kind}_projection_parent_synced")
    return False


def apply_program_owner_transition(
    root: Path,
    source_root: Path,
    locator: dict[str, Any],
    *,
    expected_state_version: int,
    expected_content_hash: str,
    scope_binding_id: str,
    completed_card_instance_id: str,
    completion: dict[str, Any],
    operations: list[dict[str, Any]],
    enqueue_requests: list[dict[str, Any]],
    current_source_identity: dict[str, Any],
    source_rebind: dict[str, Any] | None = None,
    artifact_id: str | None = None,
    artifact_payload: bytes | None = None,
    inline_render_completion: dict[str, Any] | None = None,
    projection_kind: str | None = None,
    projection_builder: Callable[[dict[str, Any]], bytes] | None = None,
    renderer_contract_hash: str | None = None,
) -> tuple[dict[str, Any], bool, dict[str, Any] | None, bool]:
    completion_id = canonical_completion_id(completion)
    if (artifact_id is None) != (artifact_payload is None):
        raise ProgramOwnerConflict("Program artifact destination is incomplete")
    artifact_entry = None
    artifact_locator = None
    if artifact_payload is not None and artifact_id is not None:
        artifact_locator = {
            "schema_version": "content-locator/1",
            "content_kind": "artifact",
            "artifact_id": artifact_id,
            "content_hash": "sha256:" + sha256(artifact_payload).hexdigest(),
            "bytes": len(artifact_payload),
        }
        artifact_entry = {
            "completion_id": completion_id,
            "artifact_id": artifact_id,
            "scope_binding_id": scope_binding_id,
            "content_locator": artifact_locator,
        }
    if (projection_kind is None) != (projection_builder is None) or (projection_kind is None) != (renderer_contract_hash is None):
        raise ProgramOwnerConflict("Program projection destination is incomplete")
    _, _, _, operation_id = card_transition_identity(
        plan_id=locator.get("plan_id", ""),
        prior_state_version=expected_state_version,
        prior_content_hash=expected_content_hash,
        scope_binding_id=scope_binding_id,
        completed_card_instance_id=completed_card_instance_id,
        completion=completion,
        operations=operations,
        enqueue_requests=enqueue_requests,
        source_identity=source_rebind,
        artifact_entry=artifact_entry,
        inline_render_completion=inline_render_completion,
    )
    with _locked_program_owner(root, source_root, locator) as (resolved, state):
        artifacts_root = resolved / "artifacts"
        projections_root = resolved / "projections"
        replayed = False
        if state["state_version"] == expected_state_version:
            if state["content_hash"] != expected_content_hash:
                raise ProgramOwnerConflict("Program receipt is stale")
            source_status = _source_identity_status(state, current_source_identity)
            if source_rebind is None and source_status != "fresh":
                raise ProgramOwnerConflict(f"Program source status is {source_status}")
            if source_rebind is not None and (current_source_identity != source_rebind or source_status != "source_rebind_required"):
                raise ProgramOwnerConflict("Program source rebind is ineligible or stale")
            candidate = apply_card_transition(
                state,
                expected_state_version=expected_state_version,
                expected_content_hash=expected_content_hash,
                scope_binding_id=scope_binding_id,
                completed_card_instance_id=completed_card_instance_id,
                completion=completion,
                operations=operations,
                enqueue_requests=enqueue_requests,
                source_identity=source_rebind,
                artifact_entry=artifact_entry,
                inline_render_completion=inline_render_completion,
            )
            if candidate["last_transition"]["operation_id"] != operation_id:
                raise ProgramOwnerConflict("Program operation identity is inconsistent")
            projection_payload = None
            if projection_builder is not None and projection_kind is not None and renderer_contract_hash is not None:
                body = projection_builder(candidate)
                if not isinstance(body, bytes):
                    raise ProgramOwnerConflict("Program projection renderer must return bytes")
                projection_payload = _program_projection_payload(
                    candidate,
                    kind=projection_kind,
                    body=body,
                    renderer_contract_hash=renderer_contract_hash,
                    completion_id=completion_id,
                )
            _program_validate_projection_directory(projections_root, state["plan_id"])
            registered = _program_registered_artifacts(state, artifacts_root)
            artifact_names = {path.name for path in artifacts_root.iterdir()}
            allowed_artifact_names = set(registered)
            if artifact_locator is not None:
                final_name, temp_name = _program_artifact_names(artifact_locator)
                allowed_artifact_names.update({final_name, temp_name})
            if artifact_names - allowed_artifact_names:
                raise ProgramOwnerConflict("Program artifact directory contains foreign entries")
            candidate_payload = canonical_bytes(candidate) + b"\n"
            state_temp = resolved / ".plan-state.tmp"
            if state_temp.exists() or state_temp.is_symlink():
                if _program_safe_bytes(state_temp)[0] != candidate_payload:
                    raise ProgramOwnerConflict("prepared Program state conflicts")
            else:
                _program_write_temp(state_temp, candidate_payload, "program_state_temp_fsynced")
            if artifact_locator is not None and artifact_payload is not None:
                final_name, temp_name = _program_artifact_names(artifact_locator)
                _program_publish_immutable(artifacts_root, final_name, temp_name, artifact_payload, prefix="program_artifact")
            os.replace(state_temp, resolved / "plan-state.json")
            _checkpoint("program_state_replaced")
            _program_sync_directory(resolved)
            _checkpoint("program_state_parent_synced")
            state = candidate
        elif state["state_version"] == expected_state_version + 1:
            transition = state["last_transition"]
            if (
                transition.get("operation_id") != operation_id
                or transition.get("prior_state_version") != expected_state_version
                or transition.get("prior_content_hash") != expected_content_hash
                or transition.get("completion_id") != completion_id
            ):
                raise ProgramOwnerConflict("Program state committed another operation")
            replayed = True
            state_temp = resolved / ".plan-state.tmp"
            if state_temp.exists() or state_temp.is_symlink():
                if _program_safe_bytes(state_temp)[0] != canonical_bytes(state) + b"\n":
                    raise ProgramOwnerConflict("committed Program state temp conflicts")
                _program_sync_directory(resolved)
                state_temp.unlink()
                _program_sync_directory(resolved)
            if artifact_locator is not None and artifact_payload is not None:
                if artifact_entry not in state["artifacts"]:
                    raise ProgramOwnerConflict("committed Program artifact binding differs")
                final_name, temp_name = _program_artifact_names(artifact_locator)
                _program_publish_immutable(artifacts_root, final_name, temp_name, artifact_payload, prefix="program_artifact")
            projection_payload = None
            if projection_builder is not None and projection_kind is not None and renderer_contract_hash is not None:
                body = projection_builder(state)
                if not isinstance(body, bytes):
                    raise ProgramOwnerConflict("Program projection renderer must return bytes")
                projection_payload = _program_projection_payload(
                    state,
                    kind=projection_kind,
                    body=body,
                    renderer_contract_hash=renderer_contract_hash,
                    completion_id=completion_id,
                )
        else:
            raise ProgramStateAdvanced("Program owner advanced beyond the receipt")

        projection_locator = None
        if projection_builder is not None and projection_kind is not None:
            assert projection_payload is not None
            _program_validate_projection_directory(
                projections_root,
                state["plan_id"],
                allow_matching_temp=(f"{projection_kind}.md.tmp", projection_payload),
            )
            _program_publish_projection(projections_root, projection_kind, projection_payload)
            projection_locator = {
                "schema_version": "content-locator/1",
                "content_kind": "projection",
                "artifact_id": projection_kind,
                "content_hash": "sha256:" + sha256(projection_payload).hexdigest(),
                "bytes": len(projection_payload),
            }
        blocked_after_commit = replayed and _source_identity_status(state, current_source_identity) != "fresh"
        _checkpoint("program_apply_before_return")
        return state, replayed, projection_locator or artifact_locator, blocked_after_commit


def resume_program_owner(
    root: Path,
    source_root: Path,
    locator: dict[str, Any],
    *,
    current_source_identity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
    with _locked_program_owner(root, source_root, locator) as (resolved, state):
        source_status = _source_identity_status(state, current_source_identity)
        if source_status == "blocked":
            raise ProgramOwnerConflict("Program source identity drift is ineligible")
        state_temp = resolved / ".plan-state.tmp"
        if state_temp.exists() or state_temp.is_symlink():
            prepared_payload, _ = _program_safe_bytes(state_temp)
            try:
                prepared = json.loads(prepared_payload)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ProgramOwnerConflict("prepared Program state is invalid") from exc
            _program_validate_candidate(prepared)
            transition = prepared["last_transition"]
            if (
                prepared["plan_id"] != state["plan_id"]
                or prepared["scope_binding"] != state["scope_binding"]
                or prepared["state_version"] != state["state_version"] + 1
                or transition.get("transition_kind") != "card"
                or transition.get("prior_state_version") != state["state_version"]
                or transition.get("prior_content_hash") != state["content_hash"]
                or not state["pending_card_instances"]
                or transition.get("completed_card_instance_id") != state["pending_card_instances"][0]["card_instance_id"]
            ):
                raise ProgramOwnerConflict("prepared Program operation cannot be proven")
            current_completion_ids = {item["completion_id"] for item in state["artifacts"]}
            prepared_entries = [item for item in prepared["artifacts"] if item["completion_id"] not in current_completion_ids]
            if len(prepared_entries) > 1:
                raise ProgramOwnerConflict("prepared Program operation has multiple artifacts")
            if prepared_entries:
                final_name, temp_name = _program_artifact_names(prepared_entries[0]["content_locator"])
                artifact_root = resolved / "artifacts"
                final = artifact_root / final_name
                temporary = artifact_root / temp_name
                if temporary.exists() or temporary.is_symlink():
                    temp_payload, temp_info = _program_safe_bytes(temporary, links={1, 2})
                    locator_value = prepared_entries[0]["content_locator"]
                    if len(temp_payload) != locator_value["bytes"] or "sha256:" + sha256(temp_payload).hexdigest() != locator_value["content_hash"]:
                        raise ProgramOwnerConflict("prepared Program artifact temp conflicts")
                    if final.exists() or final.is_symlink():
                        final_payload, final_info = _program_safe_bytes(final, links={1, 2})
                        if final_payload != temp_payload or (final_info.st_dev, final_info.st_ino) != (temp_info.st_dev, temp_info.st_ino):
                            raise ProgramOwnerConflict("prepared Program artifact pair conflicts")
                    _program_sync_directory(artifact_root)
                    temporary.unlink()
                    _program_sync_directory(artifact_root)
            _program_sync_directory(resolved)
            state_temp.unlink()
            _program_sync_directory(resolved)
        projections_root = resolved / "projections"
        _program_validate_projection_directory(
            projections_root,
            state["plan_id"],
            allow_current_temp=(state["state_version"], state["content_hash"]),
        )
        for name in ("program.md.tmp", "context-capsule.md.tmp"):
            temporary = projections_root / name
            if temporary.exists() or temporary.is_symlink():
                payload, _ = _program_safe_bytes(temporary)
                header = _program_projection_header(payload)
                if header.get("content_hash") != state["content_hash"] or header.get("state_version") != state["state_version"]:
                    raise ProgramOwnerConflict("Program projection temp is stale or foreign")
                _program_sync_directory(projections_root)
                temporary.unlink()
                _program_sync_directory(projections_root)
        queue_head = state["pending_card_instances"][0] if state["pending_card_instances"] else None
        _checkpoint("program_resume_before_return")
        return state, queue_head, source_status


def capsule_source_hash(state: dict[str, Any]) -> str:
    """Hash canonical plan semantics while excluding generated capsule records."""
    clean = dict(state)
    clean["snapshots"] = [
        snapshot
        for snapshot in state.get("snapshots", [])
        if not isinstance(snapshot, dict) or snapshot.get("kind") != "capsule"
    ]
    return canonical_state_hash(clean)


def file_hash(path: str | Path) -> str:
    return "sha256:" + sha256(Path(path).read_bytes()).hexdigest()


def contains_secret_like(value: Any) -> bool:
    """Conservatively identify raw credential-shaped values in state payloads."""
    if isinstance(value, str):
        assignment_pattern, *direct_patterns = SECRET_LIKE_PATTERNS
        for match in assignment_pattern.finditer(value):
            parts = re.split(r"\s*[:=]\s*", match.group(0), maxsplit=1)
            assigned = parts[1].strip("\"'") if len(parts) == 2 else ""
            if not CONTROLLED_SECRET_POINTER.fullmatch(assigned):
                return True
        return any(pattern.search(value) for pattern in direct_patterns)
    if isinstance(value, dict):
        return any(contains_secret_like(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_secret_like(child) for child in value)
    return False


def redact_secret_like(value: str) -> str:
    """Defense-in-depth redaction for generated projections."""
    result = value
    for pattern in SECRET_LIKE_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return result


def is_local_id(value: Any) -> bool:
    return isinstance(value, str) and LOCAL_ID_RE.fullmatch(value) is not None


def verifier_ref_is_structured(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    scheme, separator, target = value.partition(":")
    return separator == ":" and scheme in VERIFIER_REF_SCHEMES and bool(target.strip())


def is_ref(value: Any) -> bool:
    return is_local_id(value) or (isinstance(value, str) and EXTERNAL_REF_RE.fullmatch(value) is not None)


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise PlanInputError(f"unsupported schema ref: {ref}")
    current: Any = root_schema
    for segment in ref[2:].split("/"):
        current = current[segment.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise PlanInputError(f"schema ref does not resolve to object: {ref}")
    return current


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _valid_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_against_schema(value: Any, schema: dict[str, Any], root_schema: dict[str, Any] | None = None, parts: tuple[str | int, ...] = ()) -> list[Violation]:
    root = root_schema or schema
    if "$ref" in schema:
        return validate_against_schema(value, _resolve_ref(root, schema["$ref"]), root, parts)
    if "oneOf" in schema:
        candidates = [validate_against_schema(value, candidate, root, parts) for candidate in schema["oneOf"]]
        if sum(not errors for errors in candidates) != 1:
            return [Violation("plan.schema", pointer(parts), "value must satisfy exactly one schema alternative")]
        return []

    violations: list[Violation] = []
    expected = schema.get("type")
    if expected and not _type_matches(value, expected):
        return [Violation("plan.schema", pointer(parts), f"expected {expected}, got {type(value).__name__}")]
    if "const" in schema and value != schema["const"]:
        violations.append(Violation("plan.schema", pointer(parts), f"expected constant {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        violations.append(Violation("plan.schema", pointer(parts), f"value is not in enum {schema['enum']}"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            violations.append(Violation("plan.schema", pointer(parts), "string is shorter than minLength"))
        if len(value) > schema.get("maxLength", 10**9):
            violations.append(Violation("plan.schema", pointer(parts), "string exceeds maxLength"))
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            violations.append(Violation("plan.schema", pointer(parts), f"string does not match {pattern}"))
        if schema.get("format") == "date-time" and not _valid_datetime(value):
            violations.append(Violation("plan.schema", pointer(parts), "invalid RFC3339/ISO date-time"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            violations.append(Violation("plan.schema", pointer(parts), "number is below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            violations.append(Violation("plan.schema", pointer(parts), "number exceeds maximum"))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            violations.append(Violation("plan.schema", pointer(parts), "number is not above exclusiveMinimum"))

    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10**9):
            violations.append(Violation("plan.schema", pointer(parts), "array exceeds maxItems"))
        item_schema = schema.get("items")
        if item_schema:
            for index, child in enumerate(value):
                violations.extend(validate_against_schema(child, item_schema, root, parts + (index,)))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                violations.append(Violation("plan.schema", pointer(parts + (required,)), "required property is missing"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    violations.append(Violation("plan.schema", pointer(parts + (key,)), "unknown property"))
        for key, child_schema in properties.items():
            if key in value:
                violations.extend(validate_against_schema(value[key], child_schema, root, parts + (key,)))
    return violations


def normalized_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix().lstrip("./")


def path_allowed(path: str, patterns: list[str]) -> bool:
    candidate = normalized_path(path)
    for pattern in patterns:
        normalized = normalized_path(pattern)
        if fnmatchcase(candidate, normalized) or fnmatchcase(candidate, normalized.rstrip("/**") + "/**"):
            return True
        prefix = normalized.split("*", 1)[0].rstrip("/")
        if prefix and (candidate == prefix or candidate.startswith(prefix + "/")):
            return True
    return False


def _static_prefix(pattern: str) -> str:
    return normalized_path(pattern).split("*", 1)[0].rstrip("/")


def patterns_may_overlap(left: str, right: str) -> bool:
    a, b = normalized_path(left), normalized_path(right)
    if a == b or fnmatchcase(a, b) or fnmatchcase(b, a):
        return True
    pa, pb = _static_prefix(a), _static_prefix(b)
    if not pa or not pb:
        return True
    return pa == pb or pa.startswith(pb + "/") or pb.startswith(pa + "/")


def json_output(ok: bool, violations: list[Violation], **extra: Any) -> dict[str, Any]:
    return {"ok": ok, "violations": [item.as_dict() for item in violations], **extra}
