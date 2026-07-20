#!/usr/bin/env python3
"""Run one bounded Writing Plans route or card completion cycle."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import sys
import time
from typing import Any

from jsonschema import Draft202012Validator

from _writing_reference_cards import load_json, strict_json_bytes
from assess_plan_mode import assess, validate_plan_route_result
from _plan_state import (
    PROGRAM_STATE_MAX_BYTES,
    ProgramOwnerConflict,
    ProgramStateAdvanced,
    PlanInputError,
    _program_locator,
    apply_program_owner_transition,
    canonical_completion_id,
    canonical_object_hash,
    canonical_state_hash,
    initialize_program_owner,
    normalize_enqueue_requests,
    render_program_owner_projection,
    resume_program_owner,
)
from render_context_capsule import render as render_context_capsule
from render_plan_profile import render_brief, render_handoff
from render_plan_profile import render_program


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "card-protocol.schema.json"
REGISTRY_PATH = ROOT / "registries" / "artifact-family-contracts.json"
MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
HANDOFF_SCHEMA_PATH = ROOT / "schemas" / "plan-execution-handoff.schema.json"
COMMAND_MAX_BYTES = 65_536
RECEIPT_MAX_BYTES = 12_288
INPUT_CONTRACT_MAX_BYTES = 544
ROUTE_HELP_MAX_BYTES = 1_024
SOURCE_FILE_MAX_BYTES = 8 * 1024 * 1024
SOURCE_TOTAL_MAX_BYTES = 32 * 1024 * 1024
SOURCE_MAX_FILES = 4_096
GIT_SMALL_OUTPUT_MAX = 65_536
GIT_LARGE_OUTPUT_MAX = 8_388_608
GIT_DEADLINE_SECONDS = 30.0
GIT_CONFIG_PATTERN = (
    r"^(include(\..*)?|includeif\..*|extensions\.worktreeconfig|filter\..*\."
    r"(clean|smudge|process)|diff\..*\.(command|textconv)|core\."
    r"(fsmonitor|hookspath|worktree|attributesfile|excludesfile|filemode|ignorestat|trustctime|checkstat)"
    r"|submodule\..*\.update)$"
)
GIT_ENV = {
    "PATH": "/bin:/usr/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_NO_LAZY_FETCH": "1",
}
SUPPORT_MAP_PATH = ROOT / "references" / "package-support-map.md"


class CycleError(ValueError):
    def __init__(self, code: str, message: str, *, exit_code: int = 2, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.retryable = retryable


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_json(value: Any) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _renderer_contract_hash(paths: tuple[str, ...]) -> str:
    support_map = SUPPORT_MAP_PATH.read_text(encoding="utf-8")
    records = []
    for relative in sorted(paths):
        content_hash = _hash_bytes((ROOT / relative).read_bytes())
        pattern = rf"^- \[`{re.escape(relative)}` · `{re.escape(content_hash)}`\]"
        if re.search(pattern, support_map, re.MULTILINE) is None:
            raise CycleError("E_CONTRACT_INVALID", "renderer support-map binding is stale", exit_code=5)
        records.append({"path": relative, "content_hash": content_hash})
    return _hash_json(records)


def _load_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    schema = load_json(SCHEMA_PATH)
    registry = load_json(REGISTRY_PATH)
    manifest = load_json(MANIFEST_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        registry_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/artifactContractRegistry",
        }
        errors = list(Draft202012Validator(registry_schema).iter_errors(registry))
    except (KeyError, TypeError, ValueError) as exc:
        raise CycleError("E_CONTRACT_INVALID", "card protocol contract is invalid", exit_code=5) from exc
    if errors:
        raise CycleError("E_CONTRACT_INVALID", "artifact registry is invalid", exit_code=5)
    families = registry["families"]
    if set(registry["artifacts"].values()) != set(families):
        raise CycleError("E_CONTRACT_INVALID", "artifact registry contains missing or unused families", exit_code=5)
    for family in families.values():
        for field in ("human_def", "payload_def"):
            if family[field].split("/")[-1] not in schema["$defs"]:
                raise CycleError("E_CONTRACT_INVALID", "artifact registry references an unknown definition", exit_code=5)
    direct_cards = {
        "wp.profiles.brief", "wp.profiles.handoff", "wp.profiles.program",
        "wp.experiments.disposable-spike", "wp.bridges.long-document-handoff",
    }
    for card in manifest.get("cards", []):
        _card_input_contract(schema, registry, card, program=True)
        if card.get("card_id") in direct_cards:
            _card_input_contract(schema, registry, card, program=False)
    return schema, registry, manifest


def _read_command() -> dict[str, Any]:
    data = sys.stdin.buffer.read(COMMAND_MAX_BYTES + 1)
    if len(data) > COMMAND_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "command exceeds the byte limit", exit_code=4)
    try:
        command = strict_json_bytes(data, source="stdin")
    except ValueError as exc:
        raise CycleError("E_COMMAND_SCHEMA", "command is not strict UTF-8 JSON") from exc
    if not isinstance(command, dict):
        raise CycleError("E_COMMAND_SCHEMA", "command must be one JSON object")
    return command


def _validate(
    schema: dict[str, Any],
    definition: str,
    value: Any,
    code: str,
    *,
    exit_code: int = 2,
) -> None:
    validator_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": f"#/$defs/{definition}",
    }
    errors = sorted(Draft202012Validator(validator_schema).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        field = "/".join(str(part) for part in errors[0].absolute_path) or definition
        raise CycleError(code, f"{definition} field is invalid: {field}", exit_code=exit_code)


def _stable_stat(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _read_source_file(path: Path) -> tuple[str, int, str]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source file cannot be opened", exit_code=5) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > SOURCE_FILE_MAX_BYTES:
            raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an unsafe file", exit_code=5)
        payload = bytearray()
        while len(payload) <= SOURCE_FILE_MAX_BYTES:
            chunk = os.read(descriptor, min(65_536, SOURCE_FILE_MAX_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) > SOURCE_FILE_MAX_BYTES or _stable_stat(before) != _stable_stat(after):
            raise CycleError("E_SOURCE_DRIFT", "source changed during observation", exit_code=3, retryable=True)
        data = bytes(payload)
        return _hash_bytes(data), len(data), f"{stat.S_IMODE(before.st_mode):04o}"
    finally:
        os.close(descriptor)


def _source_observation(source_root: Path) -> dict[str, Any]:
    try:
        info = source_root.lstat()
        resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is unavailable", exit_code=5) from exc
    if source_root.is_symlink() or not stat.S_ISDIR(info.st_mode) or resolved != source_root.absolute():
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is not canonical", exit_code=5)
    if (resolved / ".git").exists():
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository source requires the repository observer", exit_code=5)

    records: list[dict[str, Any]] = []
    total = 0
    for current, directories, filenames in os.walk(resolved, followlinks=False):
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        for name in directories:
            entry_info = (current_path / name).lstat()
            if stat.S_ISLNK(entry_info.st_mode) or not stat.S_ISDIR(entry_info.st_mode):
                raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an unsafe directory", exit_code=5)
        for name in filenames:
            entry = current_path / name
            relative = entry.relative_to(resolved).as_posix()
            if any(ord(character) < 32 for character in relative):
                raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an invalid path", exit_code=5)
            content_hash, size, mode = _read_source_file(entry)
            total += size
            if total > SOURCE_TOTAL_MAX_BYTES or len(records) >= SOURCE_MAX_FILES:
                raise CycleError("E_SOURCE_UNAVAILABLE", "source observation exceeds its bound", exit_code=5)
            records.append({"path": relative, "content_hash": content_hash, "bytes": size, "mode": mode})
    return {"kind": "unversioned", "root_binding": {"dev": info.st_dev, "ino": info.st_ino}, "records": records}


def _validated_source_root(source_root: Path) -> tuple[Path, os.stat_result]:
    try:
        info = source_root.lstat()
        resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository source root is unavailable", exit_code=5) from exc
    if source_root.is_symlink() or not stat.S_ISDIR(info.st_mode) or resolved != source_root.absolute():
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository source root is not canonical", exit_code=5)
    return resolved, info


def _repository_marker(source_root: Path) -> bool:
    current = source_root
    while True:
        try:
            (current / ".git").lstat()
            return True
        except FileNotFoundError:
            pass
        if current.parent == current:
            return False
        current = current.parent


def _terminate_git(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)


def _bounded_git(
    source_root: Path,
    arguments: tuple[str, ...],
    *,
    stdout_cap: int,
    deadline: float,
    allowed_exit: tuple[int, ...] = (0,),
) -> tuple[int, bytes]:
    argv = [
        "git", "--no-pager", "-C", str(source_root),
        "-c", "core.fsmonitor=false", "-c", "diff.external=", *arguments,
    ]
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=GIT_ENV,
            close_fds=True,
        )
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository observer could not start", exit_code=5) from exc
    assert process.stdout is not None and process.stderr is not None
    stdout_descriptor = process.stdout.fileno()
    stderr_descriptor = process.stderr.fileno()
    streams = {stdout_descriptor: stdout_cap, stderr_descriptor: GIT_SMALL_OUTPUT_MAX}
    captured = {descriptor: bytearray() for descriptor in streams}
    selector = selectors.DefaultSelector()
    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            for key, _ in selector.select(remaining):
                descriptor = int(key.fd)
                chunk = os.read(descriptor, 65_536)
                if not chunk:
                    selector.unregister(descriptor)
                    continue
                captured[descriptor].extend(chunk)
                if len(captured[descriptor]) > streams[descriptor]:
                    raise OverflowError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return_code = process.wait(timeout=remaining)
    except (TimeoutError, subprocess.TimeoutExpired, OverflowError, OSError) as exc:
        _terminate_git(process)
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository observer exceeded its fixed boundary", exit_code=5) from exc
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
    stdout = bytes(captured[stdout_descriptor])
    stderr = bytes(captured[stderr_descriptor])
    if return_code not in allowed_exit or stderr:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository observer rejected the source", exit_code=5)
    return return_code, stdout


def _validate_repository_config(source_root: Path, deadline: float) -> None:
    return_code, payload = _bounded_git(
        source_root,
        ("config", "--local", "--no-includes", "--null", "--get-regexp", GIT_CONFIG_PATTERN),
        stdout_cap=GIT_SMALL_OUTPUT_MAX,
        deadline=deadline,
        allowed_exit=(0, 1),
    )
    if return_code == 1:
        if payload:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository config response is invalid", exit_code=5)
        return
    safe = {
        "core.filemode": "true",
        "core.ignorestat": "false",
        "core.trustctime": "true",
        "core.checkstat": "default",
    }
    observed: set[str] = set()
    for record in payload.split(b"\0"):
        if not record:
            continue
        if record.count(b"\n") != 1:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository config response is invalid", exit_code=5)
        raw_key, raw_value = record.split(b"\n", 1)
        try:
            key = raw_key.decode("ascii").lower()
            value = raw_value.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository config response is invalid", exit_code=5) from exc
        if key in observed or key not in safe or safe[key] != value:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository config weakens source observation", exit_code=5)
        observed.add(key)


def _canonical_source_path(raw: bytes) -> str:
    try:
        value = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository path encoding is invalid", exit_code=5) from exc
    path = PurePosixPath(value)
    if (
        not value or path.is_absolute() or value in {".", ".."}
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository path is invalid", exit_code=5)
    return path.as_posix()


def _parse_index(payload: bytes) -> dict[str, dict[str, str]]:
    records: dict[str, dict[str, str]] = {}
    for raw in payload.split(b"\0"):
        if not raw:
            continue
        try:
            prefix, raw_path = raw.split(b"\t", 1)
            tag = chr(prefix[0])
            mode, object_id, stage = prefix[2:].decode("ascii").split(" ")
        except (ValueError, UnicodeError, IndexError) as exc:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository index response is invalid", exit_code=5) from exc
        if tag.islower() or tag == "S" or stage != "0":
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository index uses an unsupported state", exit_code=5)
        path = _canonical_source_path(raw_path)
        if path in records:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository index contains duplicate paths", exit_code=5)
        records[path] = {"index_mode": mode, "index_object": object_id}
    return records


def _parse_status(payload: bytes) -> dict[str, str]:
    fields = payload.split(b"\0")
    result: dict[str, str] = {}
    index = 0
    while index < len(fields):
        raw = fields[index]
        index += 1
        if not raw:
            continue
        kind = raw[:1]
        if kind == b"1":
            parts = raw.split(b" ", 8)
            if len(parts) != 9:
                raise CycleError("E_SOURCE_UNAVAILABLE", "repository status response is invalid", exit_code=5)
            code, raw_path = parts[1], parts[8]
            path = _canonical_source_path(raw_path)
            result[path] = "deleted" if b"D" in code else "added" if b"A" in code else "modified"
        elif kind == b"2":
            parts = raw.split(b" ", 9)
            if len(parts) != 10 or index >= len(fields):
                raise CycleError("E_SOURCE_UNAVAILABLE", "repository rename response is invalid", exit_code=5)
            new_path = _canonical_source_path(parts[9])
            old_path = _canonical_source_path(fields[index])
            index += 1
            result[old_path] = "deleted"
            result[new_path] = "added"
        elif kind == b"?":
            if not raw.startswith(b"? "):
                raise CycleError("E_SOURCE_UNAVAILABLE", "repository status response is invalid", exit_code=5)
            result[_canonical_source_path(raw[2:])] = "added"
        elif kind in {b"u", b"!"}:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository status uses an unsupported state", exit_code=5)
        else:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository status response is invalid", exit_code=5)
    return result


def _repository_observation(source_root: Path, root_info: os.stat_result, deadline: float) -> tuple[dict[str, Any], tuple[bytes, bytes, bytes]]:
    _, revision_raw = _bounded_git(
        source_root, ("rev-parse", "HEAD^{commit}", "HEAD^{tree}"),
        stdout_cap=GIT_SMALL_OUTPUT_MAX, deadline=deadline,
    )
    _, index_raw = _bounded_git(
        source_root, ("ls-files", "-v", "--stage", "-z"),
        stdout_cap=GIT_LARGE_OUTPUT_MAX, deadline=deadline,
    )
    index_records = _parse_index(index_raw)
    _, status_raw = _bounded_git(
        source_root, ("status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=all"),
        stdout_cap=GIT_LARGE_OUTPUT_MAX, deadline=deadline,
    )
    try:
        revision_parts = revision_raw.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository revision response is invalid", exit_code=5) from exc
    if (
        len(revision_parts) != 2
        or any(len(value) not in {40, 64} for value in revision_parts)
        or any(character not in "0123456789abcdef" for value in revision_parts for character in value)
    ):
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository revision response is invalid", exit_code=5)
    statuses = _parse_status(status_raw)
    paths = sorted(
        {path for path in index_records if statuses.get(path) != "deleted"}
        | {path for path, value in statuses.items() if value != "deleted"}
    )
    if len(paths) > SOURCE_MAX_FILES:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository source exceeds its file bound", exit_code=5)
    records: list[dict[str, Any]] = []
    total = 0
    for relative in paths:
        content_hash, size, mode = _read_source_file(source_root / relative)
        total += size
        if total > SOURCE_TOTAL_MAX_BYTES:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository source exceeds its byte bound", exit_code=5)
        records.append({
            "path": relative, "status": statuses.get(relative, "unchanged"),
            "content_hash": content_hash, "bytes": size, "mode": mode,
        })
    for relative, status_value in sorted(statuses.items()):
        if status_value == "deleted" and relative not in paths:
            records.append({"path": relative, "status": "deleted", "content_hash": None, "bytes": 0, "mode": "0000"})
    root_binding = {"dev": root_info.st_dev, "ino": root_info.st_ino}
    semantic = {
        "kind": "repository", "root_binding": root_binding,
        "head_commit": revision_parts[0], "head_tree": revision_parts[1], "scoped_records": records,
        "exterior_guard_hash": _hash_json({"root_binding": root_binding, "outside_allowed_reads": []}),
    }
    return {**semantic, "identity_hash": _hash_json(semantic)}, (revision_raw, index_raw, status_raw)


def _open_repository_capture(source_root: Path) -> tuple[Path, os.stat_result, float]:
    resolved, info = _validated_source_root(source_root)
    deadline = time.monotonic() + GIT_DEADLINE_SECONDS
    _validate_repository_config(resolved, deadline)
    _, top_raw = _bounded_git(
        resolved, ("rev-parse", "--show-toplevel"),
        stdout_cap=GIT_SMALL_OUTPUT_MAX, deadline=deadline,
    )
    try:
        top_text = top_raw.decode("utf-8", errors="strict")
        top = Path(top_text.removesuffix("\n")).resolve(strict=True)
    except (OSError, UnicodeError) as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "repository root response is invalid", exit_code=5) from exc
    if top_raw != (str(top) + "\n").encode("utf-8") or top != resolved:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root must be the repository top level", exit_code=5)
    return resolved, info, deadline


def _repository_fence(session: tuple[Path, os.stat_result, float]) -> dict[str, Any]:
    resolved, info, deadline = session
    opening, opening_raw = _repository_observation(resolved, info, deadline)
    closing, closing_raw = _repository_observation(resolved, info, deadline)
    if opening_raw != closing_raw or opening != closing:
        raise CycleError("E_SOURCE_DRIFT", "repository changed during the stability fence", exit_code=3, retryable=True)
    return opening


def _capture_repository(source_root: Path) -> dict[str, Any]:
    return _repository_fence(_open_repository_capture(source_root))


def _capture_source(source_root: Path) -> dict[str, str]:
    resolved, _ = _validated_source_root(source_root)
    if _repository_marker(resolved):
        current = _capture_repository(resolved)
        return {key: current[key] for key in ("kind", "identity_hash")}
    opening = _source_observation(source_root)
    closing = _source_observation(source_root)
    if opening != closing:
        raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    return {"kind": "unversioned", "identity_hash": _hash_json(opening)}


def _capture_program_source(source_root: Path) -> dict[str, Any]:
    resolved, _ = _validated_source_root(source_root)
    if _repository_marker(resolved):
        return _capture_repository(resolved)
    opening = _source_observation(source_root)
    closing = _source_observation(source_root)
    if opening != closing:
        raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    identity_hash = _hash_json(opening)
    return {
        "kind": "unversioned",
        "identity_hash": identity_hash,
        "root_binding": opening["root_binding"],
        "head_commit": None,
        "head_tree": None,
        "scoped_records": [{**record, "status": "unchanged"} for record in opening["records"]],
        "exterior_guard_hash": _hash_json({"source_root": opening["root_binding"], "outside": []}),
    }


def _open_publication_capture(source_root: Path) -> tuple[str, Any, dict[str, Any]]:
    resolved, info = _validated_source_root(source_root)
    if _repository_marker(resolved):
        session = _open_repository_capture(resolved)
        return "repository", session, _repository_fence(session)
    opening = _source_observation(resolved)
    closing = _source_observation(resolved)
    if opening != closing:
        raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    return "unversioned", (resolved, info), opening


def _publication_fence(kind: str, session: Any) -> dict[str, Any]:
    try:
        if kind == "repository":
            return _repository_fence(session)
        resolved, _ = session
        opening = _source_observation(resolved)
        closing = _source_observation(resolved)
        if opening != closing:
            raise CycleError("E_POST_PUBLISH_UNVERIFIED", "source changed after publication", exit_code=5)
        return opening
    except CycleError as exc:
        if exc.code == "E_POST_PUBLISH_UNVERIFIED":
            raise
        raise CycleError("E_POST_PUBLISH_UNVERIFIED", "source could not be verified after publication", exit_code=5) from exc


def _observation_identity(observation: dict[str, Any]) -> dict[str, str]:
    if observation["kind"] == "repository":
        return {"kind": "repository", "identity_hash": observation["identity_hash"]}
    return {"kind": "unversioned", "identity_hash": _hash_json(observation)}


def _identity_without_paths(observation: dict[str, Any], excluded: set[str]) -> dict[str, str]:
    if observation["kind"] == "repository":
        semantic = {
            key: value
            for key, value in observation.items()
            if key != "identity_hash"
        }
        semantic["scoped_records"] = [record for record in semantic["scoped_records"] if record["path"] not in excluded]
        return {"kind": "repository", "identity_hash": _hash_json(semantic)}
    semantic = {**observation, "records": [record for record in observation["records"] if record["path"] not in excluded]}
    return {"kind": "unversioned", "identity_hash": _hash_json(semantic)}


def _publication_transition(
    before: dict[str, Any],
    after: dict[str, Any],
    relative: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    immutable = ("kind", "root_binding", "head_commit", "head_tree")
    if any(before.get(key) != after.get(key) for key in immutable):
        raise CycleError("E_POST_PUBLISH_UNVERIFIED", "source identity changed during publication", exit_code=5)
    record_key = "scoped_records" if before["kind"] == "repository" else "records"
    before_records = {record["path"]: record for record in before[record_key]}
    after_records = {record["path"]: record for record in after[record_key]}
    changed = {
        path for path in before_records.keys() | after_records.keys()
        if before_records.get(path) != after_records.get(path)
    }
    if changed - {relative} or relative not in after_records:
        raise CycleError("E_POST_PUBLISH_UNVERIFIED", "publication changed an unauthorized source path", exit_code=5)
    after_identity = _observation_identity(after)
    baseline_identity = _identity_without_paths(after, {relative})
    transition = {
        "operation_kind": "plan-output",
        "before_identity_hash": baseline_identity["identity_hash"],
        "after_identity_hash": after_identity["identity_hash"],
        "changed_paths": [{"path": relative, "status": "added"}],
    }
    return after_identity, transition


def _observation_paths(observation: dict[str, Any]) -> set[str]:
    key = "scoped_records" if observation["kind"] == "repository" else "records"
    return {record["path"] for record in observation[key]}


def _relative_to_source(source_root: Path, path: Path) -> str:
    try:
        return path.relative_to(source_root).as_posix()
    except ValueError as exc:
        raise CycleError("E_ROOT_ROLE", "delivery root is outside the source") from exc


def _publication_filename(contract_id: str, locator: dict[str, Any]) -> str:
    digest = locator["content_hash"][7:]
    if contract_id == "wp.complete.brief/2":
        return f"plan-brief--{digest}.md"
    if contract_id == "wp.complete.handoff/2":
        return f"plan-handoff--{digest}.json"
    if contract_id == "wp.complete.card/2":
        return f"{locator['artifact_id']}--{digest}.json"
    if contract_id == "wp.render.handoff/2":
        return f"plan-handoff--{digest}.md"
    raise CycleError("E_UNSUPPORTED_VARIANT", "source-contained output is not active for this contract", exit_code=4)


def _validate_delivery_root(path: Path) -> tuple[Path, dict[str, int]]:
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_ROOT_ROLE", "projection root is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISDIR(info.st_mode)
        or resolved != path.absolute()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise CycleError("E_ROOT_ROLE", "projection root is unsafe")
    return resolved, {"dev": info.st_dev, "ino": info.st_ino}


def _receipt_id(receipt: dict[str, Any]) -> str:
    return _hash_json({key: value for key, value in receipt.items() if key != "receipt_id"})


def _base_receipt(manifest: dict[str, Any], source_identity: dict[str, str], next_step: dict[str, Any]) -> dict[str, Any]:
    if next_step.get("kind") == "card":
        card = _card(manifest, next_step.get("card_id", ""))
        next_step = {
            **next_step,
            "input_contract": _card_input_contract(
                load_json(SCHEMA_PATH), load_json(REGISTRY_PATH), card, program=next_step.get("card_instance_id") is not None
            ),
        }
    return {
        "schema_version": "wp-card-receipt/2",
        "receipt_kind": "route",
        "receipt_id": "",
        "bundle_id": manifest["bundle_id"],
        "skill_id": "writing-plans",
        "source_identity": source_identity,
        "next_step": next_step,
        "route_context": None,
        "completion": None,
        "planning_scope_binding": None,
        "content_locator": None,
        "owner_locator": None,
        "already_completed": False,
        "source_fresh": None,
        "source_rebind_required": False,
        "source_transition": None,
        "state_version": None,
        "state_hash": None,
    }


def _card(manifest: dict[str, Any], card_id: str) -> dict[str, Any]:
    matches = [card for card in manifest.get("cards", []) if card.get("card_id") == card_id]
    if len(matches) != 1:
        raise CycleError("E_CONTRACT_INVALID", "selected card is unavailable", exit_code=5)
    return matches[0]


def _definition(schema: dict[str, Any], reference: str) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not reference.startswith(prefix) or "/" in reference[len(prefix):]:
        raise CycleError("E_CONTRACT_INVALID", "human definition reference is not direct", exit_code=5)
    definition = schema["$defs"].get(reference[len(prefix):])
    if not isinstance(definition, dict) or definition.get("type") != "object" or not isinstance(definition.get("properties"), dict):
        raise CycleError("E_CONTRACT_INVALID", "human definition is unavailable", exit_code=5)
    return definition


def _input_contract(
    schema: dict[str, Any],
    registry: dict[str, Any],
    card: dict[str, Any],
    completion_contract_id: str,
    field_reference: str,
    *,
    always: list[str],
    conditional: list[dict[str, Any]],
) -> dict[str, Any]:
    artifact_ids = card.get("produced_artifact_ids")
    if not isinstance(artifact_ids, list) or len(artifact_ids) != 1:
        raise CycleError("E_CONTRACT_INVALID", "selected card must produce exactly one artifact", exit_code=5)
    artifact_id = artifact_ids[0]
    family_name = registry.get("artifacts", {}).get(artifact_id)
    family = registry.get("families", {}).get(family_name)
    allowed_persistence = {"semantic_inline", "immutable_projection", "boundary_by_contract", "owner_disposable_projection"}
    if not isinstance(family, dict) or family.get("persistence_class") not in allowed_persistence:
        raise CycleError("E_CONTRACT_INVALID", "selected artifact family is unavailable", exit_code=5)
    fields = _definition(schema, field_reference)
    required = sorted(fields.get("required", []))
    properties = fields["properties"]
    if any(name not in properties for name in required):
        raise CycleError("E_CONTRACT_INVALID", "human definition required fields are inconsistent", exit_code=5)
    known_roots = {"--source-root", "--work-root", "--artifact-root", "--projection-root"}
    if len(always) != len(set(always)) or set(always) - known_roots:
        raise CycleError("E_CONTRACT_INVALID", "input contract has an unknown root role", exit_code=5)
    for condition in conditional:
        definition = properties.get(condition.get("field"), {})
        if condition.get("arg") not in known_roots or not isinstance(definition.get("enum"), list) or not set(condition.get("in", [])) <= set(definition["enum"]):
            raise CycleError("E_CONTRACT_INVALID", "input contract conditional root is invalid", exit_code=5)
    contract = {
        "completion_contract_id": completion_contract_id,
        "artifact_id": artifact_id,
        "persistence_class": family["persistence_class"],
        "required_fields": required,
        "optional_fields": sorted(set(properties) - set(required)),
        "enum_values": {name: properties[name]["enum"] for name in sorted(properties) if isinstance(properties[name], dict) and "enum" in properties[name]},
        "human_max_bytes": family["human_max_bytes"],
        "required_root_args": {"always": always, "conditional": conditional},
    }
    if len(_canonical(contract)) > INPUT_CONTRACT_MAX_BYTES:
        raise CycleError("E_CONTRACT_INVALID", "input contract exceeds the byte limit", exit_code=5)
    return contract


def _card_input_contract(schema: dict[str, Any], registry: dict[str, Any], card: dict[str, Any], *, program: bool) -> dict[str, Any]:
    card_id = card.get("card_id")
    family_name = registry.get("artifacts", {}).get(card.get("produced_artifact_ids", [None])[0]) if len(card.get("produced_artifact_ids", [])) == 1 else None
    family = registry.get("families", {}).get(family_name, {})
    if program:
        arguments = ("wp.complete.program-card/2", "#/$defs/programCardFields", ["--source-root", "--work-root"], [])
    elif card_id == "wp.profiles.brief":
        arguments = ("wp.complete.brief/2", family.get("human_def", ""), ["--source-root", "--projection-root"], [])
    elif card_id == "wp.profiles.handoff":
        arguments = ("wp.complete.handoff/2", family.get("human_def", ""), ["--source-root", "--artifact-root"], [])
    elif card_id == "wp.profiles.program":
        arguments = ("wp.complete.program/2", family.get("human_def", ""), ["--source-root", "--work-root"], [])
    elif card_id in {"wp.experiments.disposable-spike", "wp.bridges.long-document-handoff"}:
        roots = ["--source-root", "--artifact-root"] if family.get("persistence_class") == "boundary_by_contract" else ["--source-root"]
        arguments = ("wp.complete.card/2", family.get("human_def", ""), roots, [])
    else:
        raise CycleError("E_CONTRACT_INVALID", "card has no direct completion route", exit_code=5)
    return _input_contract(
        schema, registry, card, arguments[0], arguments[1], always=arguments[2], conditional=arguments[3]
    )


def _route_help_contract(schema: dict[str, Any]) -> dict[str, Any]:
    fields = schema["$defs"]["routeFields"]
    groups: dict[str, Any] = {"boolean": [], "string_array": [], "integer_min": {}, "enum": {}}
    for name in sorted(fields["required"]):
        definition = fields["properties"][name]
        if definition.get("type") == "boolean":
            groups["boolean"].append(name)
        elif definition.get("type") == "array" and definition.get("items", {}).get("type") == "string":
            groups["string_array"].append(name)
        elif definition.get("type") == "integer" and isinstance(definition.get("minimum"), int):
            groups["integer_min"][name] = definition["minimum"]
        elif isinstance(definition.get("enum"), list):
            groups["enum"][name] = definition["enum"]
        else:
            raise CycleError("E_CONTRACT_INVALID", "route field cannot be projected", exit_code=5)
    if sum(len(value) for value in groups.values()) != len(fields["required"]):
        raise CycleError("E_CONTRACT_INVALID", "route fields are not uniquely projected", exit_code=5)
    return {"contract_id": "wp.route.initial/2", "required_fields": groups, "required_root_args": ["--source-root"]}


def _route_help() -> str:
    output = (
        "usage: card_cycle.py route --input - --source-root PATH [--work-root PATH]\n"
        "initial_input_contract=" + _canonical(_route_help_contract(load_json(SCHEMA_PATH))).decode("utf-8") + "\n"
    )
    if len(output.encode("utf-8")) > ROUTE_HELP_MAX_BYTES:
        raise CycleError("E_CONTRACT_INVALID", "route help exceeds the byte limit", exit_code=5)
    return output


class _RouteHelpAction(argparse.Action):
    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace, values: Any, option_string: str | None = None) -> None:
        parser._print_message(_route_help(), sys.stdout)
        parser.exit()


def _next_card(manifest: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    if route.get("route_action") != "select_card" or route.get("primary_card") is None:
        raise CycleError("E_UNSUPPORTED_VARIANT", "this slice requires a card route", exit_code=4)
    card = _card(manifest, route["primary_card"]["card_id"])
    step = {
        "kind": "card",
        "decision_id": route["selected_decision_id"],
        "card_id": card["card_id"],
        "card_path": card["path"],
        "card_hash": card["sha256"],
    }
    return step


def _program_next_step(manifest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    queue = state["pending_card_instances"]
    if queue:
        head = queue[0]
        matches = [card for card in manifest["cards"] if card.get("decision_id") == head["decision_id"]]
        if len(matches) != 1:
            raise CycleError("E_CONTRACT_INVALID", "Program queue decision has no unique card", exit_code=5)
        card = matches[0]
        step = {
            "kind": "card", "decision_id": head["decision_id"], "card_id": card["card_id"],
            "card_path": card["path"], "card_hash": card["sha256"],
            "card_instance_id": head["card_instance_id"], "subject_ref": head["subject_ref"],
        }
        return step
    statuses = {
        "drafting": "program_ready", "ready": "program_ready", "active": "program_ready",
        "blocked": "program_blocked", "completed": "program_complete", "superseded": "program_superseded",
    }
    return {"kind": "terminal", "status": statuses[state["status"]]}


def _program_scope_receipt(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_id": state["scope_binding"]["binding_id"],
        "profile": "program",
        "allowed_plan_outputs": state["scope_binding"]["allowed_plan_outputs"],
        "delivery_root_binding_hash": _hash_json(state["initial_root_binding"]),
    }


def _program_receipt(
    manifest: dict[str, Any],
    state: dict[str, Any],
    locator: dict[str, Any],
    *,
    completion: dict[str, Any] | None,
    content_locator: dict[str, Any] | None,
    already_completed: bool,
    source_status: str = "fresh",
) -> dict[str, Any]:
    source_identity = {key: state["source_identity"][key] for key in ("kind", "identity_hash")}
    next_step = _program_next_step(manifest, state)
    if source_status == "blocked":
        next_step = {"kind": "terminal", "status": "source_blocked"}
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion" if completion is not None else "route",
        "completion": completion,
        "planning_scope_binding": _program_scope_receipt(state),
        "content_locator": content_locator,
        "owner_locator": locator,
        "already_completed": already_completed,
        "source_fresh": source_status == "fresh",
        "source_rebind_required": source_status == "source_rebind_required",
        "state_version": state["state_version"],
        "state_hash": state["content_hash"],
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _build_program_candidate(
    fields: dict[str, Any],
    manifest: dict[str, Any],
    source_identity: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    node_ids = [node["id"] for node in fields["initial_nodes"]]
    if len(node_ids) != len(set(node_ids)) or any(item["subject_ref"] is not None and item["subject_ref"] not in node_ids for item in fields["initial_queue"]):
        raise CycleError("E_COMMAND_SCHEMA", "initial Program queue has an invalid local node binding", exit_code=4)
    root_info = work_root.stat()
    initial_root_binding = {
        "dev": root_info.st_dev, "ino": root_info.st_ino, "uid": root_info.st_uid,
        "mode": stat.S_IMODE(root_info.st_mode),
    }
    scope_body = {
        "binding_kind": "wp-planning",
        "producer_card_id": "wp.profiles.program",
        "initial_source_identity_hash": source_identity["identity_hash"],
        "allowed_reads": ["**"],
        "allowed_plan_outputs": ["artifacts/**", "projections/**"],
        "effect_ceiling": "local-plan-artifact",
        "approval_requirements": [],
        "publication_ceiling": "none",
    }
    scope_binding = {**scope_body, "binding_id": _hash_json(scope_body)}
    placeholder = "sha256:" + "0" * 64
    initial_specs, _ = normalize_enqueue_requests(fields["initial_queue"], domain="initial", initialization_id=placeholder)
    program_payload_hash = _hash_json(fields)
    init_semantics = {
        "bundle_id": manifest["bundle_id"], "profile": "program", "goal": fields["goal"],
        "non_goals": fields["non_goals"], "source_identity": source_identity,
        "planning_scope_binding_id": scope_binding["binding_id"], "initial_root_binding": initial_root_binding,
        "initial_queue_specs": initial_specs, "program_payload_hash": program_payload_hash,
    }
    initialization_id = _hash_json(init_semantics)
    initial_specs, instances = normalize_enqueue_requests(fields["initial_queue"], domain="initial", initialization_id=initialization_id)
    initial_queue_hash = _hash_json(initial_specs)
    plan_id = "wp-plan:" + initialization_id[7:]
    initial_completion_payload = {
        "initialization_id": initialization_id, "plan_id": plan_id,
        "program_payload_hash": program_payload_hash, "initial_queue_hash": initial_queue_hash,
    }
    initial_completion_id = _hash_json(initial_completion_payload)
    state = {
        "schema_version": "3.0", "bundle_id": manifest["bundle_id"],
        "manifest_hash": _hash_bytes(MANIFEST_PATH.read_bytes()), "plan_id": plan_id, "profile": "program",
        "goal": fields["goal"], "non_goals": fields["non_goals"],
        "status": "active" if instances else "ready",
        "current_frontier": [node["id"] for node in fields["initial_nodes"] if node["status"] in {"ready", "in_progress"}],
        "completion": {"status": "open", "epistemic_status": "needs_repair", "required_evidence": [], "residual_uncertainty": []},
        "scope_binding": scope_binding,
        "initialization": {"initialization_id": initialization_id, "program_payload_hash": program_payload_hash, "initial_queue_hash": initial_queue_hash},
        "initial_completion_id": initial_completion_id,
        "initial_root_binding": initial_root_binding, "established_root_identity": initial_root_binding,
        "source_root_binding": source_identity["root_binding"], "source_identity": source_identity,
        "approvals": [], "facts": [], "decisions": [], "evidence": [], "nodes": fields["initial_nodes"], "edges": [], "risks": [], "gaps": [], "snapshots": [],
        "rollback": {"strategy": "not_applicable", "steps": [], "verifier_refs": []},
        "global_invariants": [
            {"id": f"I-{index:02d}", "statement": statement, "locality": "global", "applicability": "always", "targets": []}
            for index, statement in enumerate(fields["invariants"], 1)
        ],
        "policy_claims": [], "artifacts": [], "pending_card_instances": instances,
        "state_version": 1, "content_hash": placeholder,
        "last_transition": {
            "transition_kind": "init",
            "operation_id": canonical_object_hash({"domain": "wp-init/1", "initialization_id": initialization_id, "completion_id": initial_completion_id}),
            "prior_state_version": 0, "prior_content_hash": None, "scope_binding_id": scope_binding["binding_id"],
            "completion_id": initial_completion_id, "completed_card_instance_id": None,
            "enqueued_card_instance_ids": [item["card_instance_id"] for item in instances], "inline_render_completion": None,
        },
    }
    state["content_hash"] = canonical_state_hash(state)
    return state


def _route_initial(command: dict[str, Any], manifest: dict[str, Any], source_identity: dict[str, str]) -> dict[str, Any]:
    facts = {
        "schema_version": "2.0",
        "route_phase": "entry",
        **command["fields"],
        "pending_decision_ids": [],
        "available_artifact_ids": [],
        "completed_decision_ids": [],
        "just_completed_card_id": None,
        "decision_request": None,
    }
    route = assess(facts)
    if validate_plan_route_result(route):
        raise CycleError("E_CONTRACT_INVALID", "plan route result is invalid", exit_code=5)
    receipt = _base_receipt(manifest, source_identity, _next_card(manifest, route))
    receipt["route_context"] = command["fields"]
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _validate_previous(
    schema: dict[str, Any],
    previous: Any,
    source_identity: dict[str, str],
    *,
    allow_source_drift: bool = False,
) -> dict[str, Any]:
    _validate(schema, "receipt", previous, "E_RECEIPT_INVALID", exit_code=3)
    if previous["receipt_id"] != _receipt_id(previous):
        raise CycleError("E_RECEIPT_INVALID", "previous receipt hash is invalid", exit_code=3)
    if not allow_source_drift and previous["source_identity"] != source_identity:
        raise CycleError("E_SOURCE_REVISION_CHANGED", "source identity changed", exit_code=3)
    return previous


def _enforce_brief_budget(registry: dict[str, Any], fields: dict[str, Any], outcome: dict[str, Any]) -> None:
    family = registry["families"][registry["artifacts"]["plan-brief"]]
    if len(_canonical({"fields": fields, "outcome": outcome})) > family["human_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "human input exceeds its family budget", exit_code=4)


def _read_regular(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise CycleError("E_ORPHAN_CONFLICT", "projection target is unsafe", exit_code=5) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or before.st_nlink not in {1, 2}:
            raise CycleError("E_ORPHAN_CONFLICT", "projection target is unsafe", exit_code=5)
        payload = bytearray()
        while len(payload) <= 32_768:
            chunk = os.read(descriptor, min(65_536, 32_769 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        after = os.fstat(descriptor)
        if len(payload) > 32_768 or _stable_stat(before) != _stable_stat(after):
            raise CycleError("E_ORPHAN_CONFLICT", "projection target is unstable", exit_code=5)
        return bytes(payload), before
    finally:
        os.close(descriptor)


def _fsync_directory(root: Path) -> None:
    descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _publish_immutable(root: Path, filename: str, payload: bytes) -> None:
    final = root / filename
    temporary = root / f"{filename}.tmp"
    final_info = _lstat_optional(final)
    temp_info = _lstat_optional(temporary)

    if final_info is not None:
        final_bytes, final_stat = _read_regular(final)
        if final_bytes != payload or stat.S_IMODE(final_stat.st_mode) != 0o600:
            raise CycleError("E_ORPHAN_CONFLICT", "projection final conflicts", exit_code=5)
        if temp_info is None:
            return
        temp_bytes, temp_stat = _read_regular(temporary)
        if temp_bytes != payload or (final_stat.st_dev, final_stat.st_ino) != (temp_stat.st_dev, temp_stat.st_ino):
            raise CycleError("E_ORPHAN_CONFLICT", "projection temp conflicts", exit_code=5)
        temporary.unlink()
        _fsync_directory(root)
        return

    if temp_info is not None:
        temp_bytes, temp_stat = _read_regular(temporary)
        if temp_bytes != payload or stat.S_IMODE(temp_stat.st_mode) != 0o600 or temp_stat.st_nlink != 1:
            raise CycleError("E_ORPHAN_CONFLICT", "projection temp conflicts", exit_code=5)
    else:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.link(temporary, final, follow_symlinks=False)
    _fsync_directory(root)
    temporary.unlink()
    _fsync_directory(root)


def _complete_brief(
    command: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    projection_root: Path,
    root_binding: dict[str, int],
) -> dict[str, Any]:
    if previous["next_step"].get("card_id") != "wp.profiles.brief" or previous["route_context"] is None:
        raise CycleError("E_RECEIPT_INVALID", "brief completion does not match the active card", exit_code=3)
    _enforce_brief_budget(registry, command["fields"], command["outcome"])
    rendered = render_brief(command["fields"]).encode("utf-8")
    family = registry["families"][registry["artifacts"]["plan-brief"]]
    if len(rendered) > family["payload_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "brief projection exceeds its payload budget", exit_code=4)

    payload_hash = _hash_json(command["fields"])
    content_hash = _hash_bytes(rendered)
    scope_payload = {
        "profile": "brief",
        "allowed_plan_outputs": ["plan-brief"],
        "delivery_root_binding_hash": _hash_json(root_binding),
        "source_identity": source_identity,
    }
    scope_binding = {key: value for key, value in scope_payload.items() if key != "source_identity"}
    scope_binding["binding_id"] = _hash_json(scope_payload)
    completion_payload = {
        "artifact_id": "plan-brief",
        "producer_card_id": previous["next_step"]["card_id"],
        "decision_id": previous["next_step"]["decision_id"],
        "payload_hash": payload_hash,
        "outcome": {"blocker": command["outcome"]["blocker"], "decision_request": None},
        "source_identity": source_identity,
        "scope_binding_id": scope_binding["binding_id"],
    }
    completion = {key: value for key, value in completion_payload.items() if key not in {"source_identity", "scope_binding_id"}}
    completion["completion_id"] = _hash_json(completion_payload)
    locator = {
        "schema_version": "content-locator/1",
        "content_kind": "projection",
        "artifact_id": "plan-brief",
        "content_hash": content_hash,
        "bytes": len(rendered),
    }
    filename = f"plan-brief--{content_hash.removeprefix('sha256:')}.md"
    _publish_immutable(projection_root, filename, rendered)

    receipt = _base_receipt(manifest, source_identity, {"kind": "terminal", "status": "brief_complete"})
    receipt.update({
        "receipt_kind": "completion",
        "completion": completion,
        "planning_scope_binding": scope_binding,
        "content_locator": locator,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _complete_standalone_card(
    command: dict[str, Any],
    schema: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    artifact_root: Path | None,
) -> dict[str, Any]:
    card = _card(manifest, previous["next_step"].get("card_id", ""))
    if card["card_id"] not in {"wp.experiments.disposable-spike", "wp.bridges.long-document-handoff"}:
        raise CycleError("E_RECEIPT_INVALID", "standalone completion does not match the active card", exit_code=3)
    artifact_ids = card["produced_artifact_ids"]
    if len(artifact_ids) != 1:
        raise CycleError("E_CONTRACT_INVALID", "standalone card must produce exactly one artifact", exit_code=5)
    artifact_id = artifact_ids[0]
    family_name = registry["artifacts"].get(artifact_id)
    family = registry["families"].get(family_name)
    if not isinstance(family, dict):
        raise CycleError("E_CONTRACT_INVALID", "standalone artifact family is unavailable", exit_code=5)
    human_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": family["human_def"]}
    if list(Draft202012Validator(human_schema).iter_errors(command["fields"])):
        raise CycleError("E_COMMAND_SCHEMA", "human fields do not match the routed artifact family", exit_code=4)
    if len(_canonical({"fields": command["fields"], "outcome": command["outcome"]})) > family["human_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "human input exceeds its family budget", exit_code=4)
    outcome = {"blocker": command["outcome"]["blocker"], "decision_request": None}
    body = {
        "artifact_id": artifact_id, "producer_card_id": card["card_id"],
        "decision_id": card["decision_id"], "fields": command["fields"], "outcome": outcome,
    }
    payload = _canonical(body) + b"\n"
    content_locator = None
    if family["persistence_class"] == "boundary_by_contract":
        if artifact_root is None:
            raise CycleError("E_ROOT_ROLE", "boundary completion requires an artifact root", exit_code=2)
        content_locator = {
            "schema_version": "content-locator/1", "content_kind": "artifact", "artifact_id": artifact_id,
            "content_hash": _hash_bytes(payload), "bytes": len(payload),
        }
        _publish_immutable(artifact_root, f"{artifact_id}--{content_locator['content_hash'][7:]}.json", payload)
    elif family["persistence_class"] != "semantic_inline":
        raise CycleError("E_CONTRACT_INVALID", "standalone persistence class is not active", exit_code=5)
    completion = {
        "completion_id": _hash_json(body), "artifact_id": artifact_id,
        "producer_card_id": card["card_id"], "decision_id": card["decision_id"],
        "payload_hash": _hash_json(command["fields"]), "outcome": outcome,
    }
    terminal_status = "handoff_complete" if family["persistence_class"] == "boundary_by_contract" else "brief_complete"
    receipt = _base_receipt(manifest, source_identity, {"kind": "terminal", "status": terminal_status})
    receipt.update({"receipt_kind": "completion", "completion": completion, "content_locator": content_locator})
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _complete_handoff(
    command: dict[str, Any],
    manifest: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    artifact_root: Path,
    root_binding: dict[str, int],
) -> dict[str, Any]:
    if previous["next_step"].get("card_id") != "wp.profiles.handoff" or previous["route_context"] is None:
        raise CycleError("E_RECEIPT_INVALID", "handoff completion does not match the active card", exit_code=3)
    fields = command["fields"]
    scope_payload = {
        "profile": "handoff",
        "allowed_plan_outputs": ["plan-handoff"],
        "delivery_root_binding_hash": _hash_json(root_binding),
        "source_identity": source_identity,
    }
    scope_binding = {key: value for key, value in scope_payload.items() if key != "source_identity"}
    scope_binding["binding_id"] = _hash_json(scope_payload)
    completion_payload = {
        "artifact_id": "plan-handoff",
        "producer_card_id": previous["next_step"]["card_id"],
        "decision_id": previous["next_step"]["decision_id"],
        "payload_hash": _hash_json(fields),
        "outcome": {"blocker": command["outcome"]["blocker"], "decision_request": None},
        "source_identity": source_identity,
        "scope_binding_id": scope_binding["binding_id"],
    }
    completion = {key: value for key, value in completion_payload.items() if key not in {"source_identity", "scope_binding_id"}}
    completion["completion_id"] = _hash_json(completion_payload)
    unsigned = {
        "schema_version": "3.0",
        "bundle_id": manifest["bundle_id"],
        "producer": {
            "profile": "handoff",
            "card_id": previous["next_step"]["card_id"],
            "decision_id": previous["next_step"]["decision_id"],
            "completion_id": completion["completion_id"],
            "plan_id": None,
            "state_hash": None,
        },
        "source_identity": source_identity,
        "scope_binding": {
            "binding_id": scope_binding["binding_id"],
            "allowed_reads": ["**"],
            "allowed_writes": [],
            "effect_ceiling": "local-plan-artifact",
            "approval_requirements": [],
            "publication_ceiling": "none",
        },
        "goal": fields["goal"],
        "non_goals": fields["non_goals"],
        "global_invariants": [
            {"ref": f"I-{index:02d}", "statement": statement}
            for index, statement in enumerate(fields["invariants"], 1)
        ],
        "owner_seams": [
            {"owner": owner, "paths": [], "resources": [], "effects": []}
            for owner in fields["owner_seams"]
        ],
        "requirements": {
            "fact_refs": [], "decision_refs": [], "evidence_refs": fields["required_evidence"],
            "approval_refs": [], "policy_refs": [],
        },
        "ordered_slices": [
            {
                "slice_id": f"S-{index:02d}", "node_ref": None, "objective": objective,
                "depends_on": [] if index == 1 else [f"S-{index - 1:02d}"],
                "read_set": ["**"], "write_set": [], "effect_set": [],
                "completion_criterion": "Required evidence is recorded for this slice.",
            }
            for index, objective in enumerate(fields["ordered_slices"], 1)
        ],
        "rollback": {"strategy": "manual_recovery", "steps": [fields["rollback"]], "verifier_refs": []},
        "target_entry": {
            "skill_id": "software-quality-workflows", "route_phase": "entry",
            "required_decision_ids": ["sqw.select.control.scope-authority-and-effects"],
        },
        "unresolved_blockers": [command["outcome"]["blocker"]] if command["outcome"]["blocker"] else [],
    }
    artifact = {"handoff_id": "wp-handoff:" + sha256(_canonical(unsigned)).hexdigest(), **unsigned}
    handoff_schema = load_json(HANDOFF_SCHEMA_PATH)
    errors = list(Draft202012Validator(handoff_schema).iter_errors(artifact))
    if errors:
        raise CycleError("E_CONTRACT_INVALID", "typed handoff builder produced an invalid artifact", exit_code=5)
    payload = _canonical(artifact) + b"\n"
    locator = {
        "schema_version": "content-locator/1", "content_kind": "artifact", "artifact_id": "plan-handoff",
        "content_hash": _hash_bytes(payload), "bytes": len(payload),
    }
    _publish_immutable(artifact_root, f"plan-handoff--{locator['content_hash'][7:]}.json", payload)
    receipt = _base_receipt(manifest, source_identity, {"kind": "terminal", "status": "handoff_complete"})
    receipt.update({
        "receipt_kind": "completion", "completion": completion,
        "planning_scope_binding": scope_binding, "content_locator": locator,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _complete_program_init(
    schema: dict[str, Any],
    command: dict[str, Any],
    manifest: dict[str, Any],
    previous: dict[str, Any],
    source_root: Path,
    source_identity: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    if previous["next_step"].get("card_id") != "wp.profiles.program" or previous["route_context"] is None:
        raise CycleError("E_RECEIPT_INVALID", "Program completion does not match the active profile card", exit_code=3)
    try:
        candidate = _build_program_candidate(command["fields"], manifest, source_identity, work_root)
    except PlanInputError as exc:
        raise CycleError("E_COMMAND_SCHEMA", str(exc), exit_code=4) from exc
    completion_payload = {
        "artifact_id": "plan-program", "producer_card_id": previous["next_step"]["card_id"],
        "decision_id": previous["next_step"]["decision_id"], "payload_hash": _hash_json(command["fields"]),
        "outcome": {"blocker": command["outcome"]["blocker"], "decision_request": None},
        "initial_completion_id": candidate["initial_completion_id"],
    }
    completion = {key: value for key, value in completion_payload.items() if key != "initial_completion_id"}
    completion["completion_id"] = candidate["initial_completion_id"]
    owner_content = _canonical(candidate) + b"\n"
    if len(owner_content) > PROGRAM_STATE_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "Program owner exceeds the byte limit", exit_code=4)
    content_locator = {
        "schema_version": "content-locator/1", "content_kind": "owner", "artifact_id": "plan-program",
        "content_hash": _hash_bytes(owner_content), "bytes": len(owner_content),
    }
    expected_locator = _program_locator(candidate)
    preflight = _program_receipt(
        manifest, candidate, expected_locator, completion=completion, content_locator=content_locator,
        already_completed=False,
    )
    _validate(schema, "receipt", preflight, "E_CONTRACT_INVALID", exit_code=5)
    if len(_canonical(preflight)) + 1 > RECEIPT_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "receipt exceeds the byte limit", exit_code=4)
    try:
        state, locator, replayed = initialize_program_owner(work_root, source_root, candidate)
    except ProgramOwnerConflict as exc:
        raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
    except PlanInputError as exc:
        raise CycleError("E_ROOT_ROLE", str(exc), exit_code=2) from exc
    if state != candidate or locator != expected_locator:
        raise CycleError("E_ORPHAN_CONFLICT", "Program initialization identity drifted", exit_code=5)
    if not replayed:
        return preflight
    return _program_receipt(
        manifest, state, locator, completion=completion, content_locator=content_locator,
        already_completed=True,
    )


def _build_program_handoff_artifact(
    state: dict[str, Any],
    completion_id: str,
    next_step: dict[str, Any],
    artifact_id: str,
    source_identity_override: dict[str, Any] | None = None,
) -> tuple[str, bytes]:
    node_ids = [next_step["subject_ref"]] if next_step.get("subject_ref") is not None else list(state["current_frontier"])
    node_by_id = {node["id"]: node for node in state["nodes"]}
    if not node_ids or any(node_id not in node_by_id for node_id in node_ids):
        raise ProgramOwnerConflict("Program handoff requires a complete current node binding")
    nodes = [node_by_id[node_id] for node_id in node_ids]

    def unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    refs = unique([ref for node in nodes for ref in node["inputs"] + node["verifier"]["required_evidence"]])
    producer_state_hash = (
        state["last_transition"]["prior_content_hash"]
        if state["last_transition"]["completion_id"] == completion_id and state["last_transition"]["transition_kind"] == "card"
        else state["content_hash"]
    )
    bound_source = source_identity_override or state["source_identity"]
    unsigned = {
        "schema_version": "3.0", "bundle_id": state["bundle_id"],
        "producer": {
            "profile": "program", "card_id": next_step["card_id"], "decision_id": next_step["decision_id"],
            "completion_id": completion_id, "plan_id": state["plan_id"], "state_hash": producer_state_hash,
        },
        "source_identity": {key: bound_source[key] for key in ("kind", "identity_hash")},
        "scope_binding": {
            "binding_id": state["scope_binding"]["binding_id"],
            "allowed_reads": state["scope_binding"]["allowed_reads"],
            "allowed_writes": state["scope_binding"]["allowed_plan_outputs"],
            "effect_ceiling": state["scope_binding"]["effect_ceiling"],
            "approval_requirements": state["scope_binding"]["approval_requirements"],
            "publication_ceiling": state["scope_binding"]["publication_ceiling"],
        },
        "goal": state["goal"], "non_goals": state["non_goals"],
        "global_invariants": [{"ref": item["id"], "statement": item["statement"]} for item in state["global_invariants"]],
        "owner_seams": [
            {"owner": node["id"], "paths": unique(node["read_set"] + node["write_set"]), "resources": node["resource_set"], "effects": node["effect_set"]}
            for node in nodes
        ],
        "requirements": {
            "fact_refs": [ref for ref in refs if ref.startswith("F-")],
            "decision_refs": [ref for ref in refs if ref.startswith("D-")],
            "evidence_refs": [ref for ref in refs if ref.startswith("E-")],
            "approval_refs": [ref for ref in refs if ref.startswith("A-")],
            "policy_refs": [item["policy_id"] for item in state["policy_claims"]],
        },
        "ordered_slices": [
            {
                "slice_id": f"S-{index:02d}", "node_ref": node["id"], "objective": node["objective"],
                "depends_on": node["depends_on"], "read_set": node["read_set"], "write_set": node["write_set"],
                "effect_set": node["effect_set"], "completion_criterion": node.get("completion_criterion", node["verifier"]["completion_criterion"]),
            }
            for index, node in enumerate(nodes, 1)
        ],
        "rollback": state["rollback"],
        "target_entry": {
            "skill_id": "software-quality-workflows", "route_phase": "entry",
            "required_decision_ids": ["sqw.select.control.scope-authority-and-effects"],
        },
        "unresolved_blockers": [
            gap["question"] for gap in state["gaps"]
            if gap["status"] != "closed" and set(gap["blocks"]) & set(node_ids)
        ],
    }
    artifact = {"handoff_id": "wp-handoff:" + sha256(_canonical(unsigned)).hexdigest(), **unsigned}
    errors = list(Draft202012Validator(load_json(HANDOFF_SCHEMA_PATH)).iter_errors(artifact))
    if errors:
        raise ProgramOwnerConflict("Program handoff builder produced an invalid typed artifact")
    return artifact_id, _canonical(artifact) + b"\n"


def _route_program_resume(
    command: dict[str, Any],
    manifest: dict[str, Any],
    source_root: Path,
    current_source: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    try:
        state, _, source_status = resume_program_owner(
            work_root, source_root, command["fields"]["owner_locator"], current_source_identity=current_source
        )
    except ProgramOwnerConflict as exc:
        code = "E_SOURCE_REVISION_CHANGED" if any(anchor in str(exc) for anchor in ("source identity drift", "root binding changed")) else "E_ORPHAN_CONFLICT"
        raise CycleError(code, str(exc), exit_code=3 if code == "E_SOURCE_REVISION_CHANGED" else 5) from exc
    return _program_receipt(
        manifest, state, command["fields"]["owner_locator"], completion=None,
        content_locator=None, already_completed=False, source_status=source_status,
    )


def _complete_program_card(
    command: dict[str, Any],
    manifest: dict[str, Any],
    previous: dict[str, Any],
    source_root: Path,
    current_source: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    fields = command["fields"]
    next_step = previous["next_step"]
    if next_step.get("kind") != "card" or next_step.get("card_instance_id") is None:
        raise CycleError("E_RECEIPT_INVALID", "Program completion has no active queue head", exit_code=3)
    if (fields["expected_state_version"], fields["expected_content_hash"]) != (previous["state_version"], previous["state_hash"]):
        raise CycleError("E_RECEIPT_INVALID", "Program expected state does not match the route receipt", exit_code=3)
    if fields["owner_locator"] != previous["owner_locator"]:
        raise CycleError("E_RECEIPT_INVALID", "Program owner locator does not match the route receipt", exit_code=3)
    if any(operation["operation"] == "rebind_source" for operation in fields["operations"]):
        raise CycleError("E_COMMAND_SCHEMA", "rebind_source is CLI-derived", exit_code=4)
    source_rebind = current_source if previous["source_rebind_required"] else None
    completion = {
        "outcome": command["outcome"], "rationale": fields["rationale"],
        "evidence_refs": fields["evidence_refs"], "card_id": next_step["card_id"],
        "decision_id": next_step["decision_id"],
    }
    artifact_id = None
    artifact_payload = None
    artifact_builder = None
    produced_artifact_id = None
    projection_kind = None
    projection_builder = None
    renderer_contract_hash = None
    inline_completion = None
    if next_step["card_id"] == "wp.economy.output-projection":
        if fields["context"] is not None or fields["runtime_projection"] is not None:
            raise CycleError("E_COMMAND_SCHEMA", "output projection does not accept context fields", exit_code=4)
        projection_kind = "program"
        projection_builder = lambda state: render_program(state).encode("utf-8")
        renderer_contract_hash = _renderer_contract_hash(("schemas/plan-state.schema.json", "scripts/render_plan_profile.py"))
    elif next_step["card_id"] == "wp.slicing.context-capsules":
        context = fields["context"]
        runtime_projection = fields["runtime_projection"]
        if context is None or runtime_projection is None or context["node_id"] != next_step["subject_ref"]:
            raise CycleError("E_COMMAND_SCHEMA", "context completion does not bind the queue subject", exit_code=4)
        renderer_contract_hash = _renderer_contract_hash(("schemas/plan-state.schema.json", "scripts/render_context_capsule.py"))
        inline_completion = {
            "node_id": context["node_id"], "consumer_profile": context["consumer_profile"],
            "budget_bytes": context["budget_bytes"], "runtime_projection": runtime_projection,
            "manifest_hash": _hash_bytes(MANIFEST_PATH.read_bytes()), "card_hash": next_step["card_hash"],
            "renderer_contract_hash": renderer_contract_hash,
        }
        projection_kind = "context-capsule"
        projection_builder = lambda state: render_context_capsule(
            state, context["node_id"], context["budget_bytes"], runtime_projection
        )[0].encode("utf-8")
    elif next_step["card_id"] in {"wp.profiles.handoff", "wp.bridges.long-document-handoff"}:
        if fields["context"] is not None or fields["runtime_projection"] is not None:
            raise CycleError("E_COMMAND_SCHEMA", "handoff completion does not accept context fields", exit_code=4)
        if fields["operations"] or fields["enqueue_requests"]:
            raise CycleError("E_COMMAND_SCHEMA", "handoff completion is mechanically derived from current state", exit_code=4)
        handoff_artifact_id = "long-document-handoff" if next_step["card_id"] == "wp.bridges.long-document-handoff" else "plan-handoff"
        produced_artifact_id = handoff_artifact_id
        artifact_builder = lambda state, completion_id: _build_program_handoff_artifact(
            state, completion_id, next_step, handoff_artifact_id, source_rebind
        )
    elif fields["context"] is not None or fields["runtime_projection"] is not None:
        raise CycleError("E_COMMAND_SCHEMA", "non-context Program card received context fields", exit_code=4)
    try:
        state, replayed, output_locator, blocked_after_commit = apply_program_owner_transition(
            work_root,
            source_root,
            fields["owner_locator"],
            expected_state_version=fields["expected_state_version"],
            expected_content_hash=fields["expected_content_hash"],
            scope_binding_id=previous["planning_scope_binding"]["binding_id"],
            completed_card_instance_id=next_step["card_instance_id"],
            completion=completion,
            operations=fields["operations"],
            enqueue_requests=fields["enqueue_requests"],
            current_source_identity=current_source,
            source_rebind=source_rebind,
            artifact_id=artifact_id,
            artifact_payload=artifact_payload,
            artifact_builder=artifact_builder,
            inline_render_completion=inline_completion,
            projection_kind=projection_kind,
            projection_builder=projection_builder,
            renderer_contract_hash=renderer_contract_hash,
        )
    except ProgramStateAdvanced as exc:
        raise CycleError("E_STATE_ADVANCED", str(exc), exit_code=3) from exc
    except ProgramOwnerConflict as exc:
        message = str(exc)
        code = "E_PROJECTION_BUDGET" if "exceeds 8192" in message else "E_STATE_STALE" if "receipt is stale" in message else "E_HANDOFF_INVALID" if "handoff" in message.lower() else "E_SOURCE_REVISION_CHANGED" if "source status" in message else "E_ORPHAN_CONFLICT"
        exit_code = 4 if code in {"E_PROJECTION_BUDGET", "E_HANDOFF_INVALID"} else 3 if code in {"E_STATE_STALE", "E_SOURCE_REVISION_CHANGED"} else 5
        raise CycleError(code, str(exc), exit_code=exit_code) from exc
    except PlanInputError as exc:
        code = "E_STATE_BUDGET" if "budget" in str(exc) else "E_COMMAND_SCHEMA"
        raise CycleError(code, str(exc), exit_code=4) from exc
    except ValueError as exc:
        if "budget" in str(exc):
            raise CycleError("E_PROJECTION_BUDGET", str(exc), exit_code=4) from exc
        raise CycleError("E_CONTRACT_INVALID", "Program renderer rejected canonical state", exit_code=5) from exc
    completion_receipt = {
        "completion_id": canonical_completion_id(completion), "artifact_id": produced_artifact_id or ("context-capsule" if projection_kind == "context-capsule" else "output-projection" if projection_kind else "plan-program"),
        "producer_card_id": next_step["card_id"], "decision_id": next_step["decision_id"],
        "payload_hash": _hash_json(fields),
        "outcome": {"blocker": command["outcome"]["blocker"], "decision_request": None},
    }
    return _program_receipt(
        manifest, state, fields["owner_locator"], completion=completion_receipt,
        content_locator=output_locator, already_completed=replayed,
        source_status="blocked" if blocked_after_commit else "fresh",
    )


def _render_program_projection(
    command: dict[str, Any],
    manifest: dict[str, Any],
    source_root: Path,
    current_source: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    fields = command["fields"]
    kind = fields["projection_kind"]
    if kind == "program":
        renderer_hash = _renderer_contract_hash(("schemas/plan-state.schema.json", "scripts/render_plan_profile.py"))
        builder = lambda state: render_program(state).encode("utf-8")
        completion_id = None
    else:
        renderer_hash = _renderer_contract_hash(("schemas/plan-state.schema.json", "scripts/render_context_capsule.py"))

        def builder(state: dict[str, Any]) -> bytes:
            inline = state["last_transition"]["inline_render_completion"]
            if inline is None:
                raise CycleError("E_CONTEXT_NOT_CURRENT", "current Program state has no context completion", exit_code=3)
            card = _card(manifest, "wp.slicing.context-capsules")
            if (
                inline["manifest_hash"] != _hash_bytes(MANIFEST_PATH.read_bytes())
                or inline["card_hash"] != card["sha256"]
                or inline["renderer_contract_hash"] != renderer_hash
            ):
                raise CycleError("E_CONTEXT_NOT_CURRENT", "context renderer binding is stale", exit_code=3)
            return render_context_capsule(
                state, inline["node_id"], inline["budget_bytes"], inline["runtime_projection"]
            )[0].encode("utf-8")

        completion_id = None
    try:
        state, content_locator, replayed = render_program_owner_projection(
            work_root,
            source_root,
            fields["owner_locator"],
            current_source_identity=current_source,
            projection_kind=kind,
            projection_builder=builder,
            renderer_contract_hash=renderer_hash,
            completion_id=completion_id,
        )
    except CycleError:
        raise
    except ProgramOwnerConflict as exc:
        code = "E_PROJECTION_BUDGET" if "exceeds 8192" in str(exc) else "E_ORPHAN_CONFLICT"
        raise CycleError(code, str(exc), exit_code=4 if code == "E_PROJECTION_BUDGET" else 5) from exc
    return _program_receipt(
        manifest, state, fields["owner_locator"], completion=None,
        content_locator=content_locator, already_completed=replayed,
    )


def _render_handoff_projection(
    command: dict[str, Any],
    manifest: dict[str, Any],
    source_identity: dict[str, str],
    artifact_root: Path,
    projection_root: Path,
) -> dict[str, Any]:
    locator = command["fields"]["content_locator"]
    if locator["content_kind"] != "artifact" or locator["artifact_id"] != "plan-handoff":
        raise CycleError("E_COMMAND_SCHEMA", "handoff render requires a plan-handoff artifact locator", exit_code=4)
    artifact_path = artifact_root / f"plan-handoff--{locator['content_hash'][7:]}.json"
    payload, _ = _read_regular(artifact_path)
    if len(payload) != locator["bytes"] or _hash_bytes(payload) != locator["content_hash"]:
        raise CycleError("E_ORPHAN_CONFLICT", "handoff artifact locator is stale", exit_code=5)
    try:
        artifact = strict_json_bytes(payload, source=str(artifact_path))
    except ValueError as exc:
        raise CycleError("E_ORPHAN_CONFLICT", "handoff artifact is invalid", exit_code=5) from exc
    errors = list(Draft202012Validator(load_json(HANDOFF_SCHEMA_PATH)).iter_errors(artifact))
    if errors:
        raise CycleError("E_HANDOFF_INVALID", "handoff artifact violates its typed contract", exit_code=4)
    if artifact["source_identity"] != source_identity:
        raise CycleError("E_SOURCE_REVISION_CHANGED", "handoff artifact source binding is stale", exit_code=3)
    rendered = render_handoff(artifact).encode("utf-8")
    content_locator = {
        "schema_version": "content-locator/1", "content_kind": "projection", "artifact_id": "plan-handoff",
        "content_hash": _hash_bytes(rendered), "bytes": len(rendered),
    }
    _publish_immutable(projection_root, f"plan-handoff--{content_locator['content_hash'][7:]}.md", rendered)
    receipt = _base_receipt(manifest, source_identity, {"kind": "terminal", "status": "handoff_complete"})
    receipt.update({"receipt_kind": "completion", "content_locator": content_locator, "already_completed": False})
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.input != "-":
        raise CycleError("E_COMMAND_SCHEMA", "--input must be stdin")
    schema, registry, manifest = _load_contracts()
    command = _read_command()
    _validate(schema, "command", command, "E_COMMAND_SCHEMA")
    contract_id = command["contract_id"]
    expected_subcommand = "route" if contract_id.startswith("wp.route.") else "render" if contract_id.startswith("wp.render.") else "complete"
    if args.subcommand != expected_subcommand:
        raise CycleError("E_COMMAND_SCHEMA", "subcommand does not match contract")
    root_roles = {
        "wp.route.initial/2": (None, None, None),
        "wp.route.resume/2": ("work", None, None),
        "wp.complete.brief/2": (None, None, "projection"),
        "wp.complete.card/2": (None, None, None),
        "wp.complete.handoff/2": (None, "artifact", None),
        "wp.complete.program/2": ("work", None, None),
        "wp.complete.program-card/2": ("work", None, None),
        "wp.render.program/2": ("work", None, None),
        "wp.render.handoff/2": (None, "artifact", "projection"),
    }
    if contract_id.startswith("wp.complete."):
        input_contract = command["previous_receipt"]["next_step"].get("input_contract")
        if not isinstance(input_contract, dict) or input_contract.get("completion_contract_id") != contract_id:
            raise CycleError("E_RECEIPT_INVALID", "completion does not match the projected input contract", exit_code=3)
        root_contract = input_contract["required_root_args"]
        projected_roots = set(root_contract["always"])
        for condition in root_contract["conditional"]:
            if command["fields"].get(condition["field"]) in condition["in"]:
                projected_roots.add(condition["arg"])
        unknown_roots = projected_roots - {"--source-root", "--work-root", "--artifact-root", "--projection-root"}
        if unknown_roots:
            raise CycleError("E_CONTRACT_INVALID", "projected input contract has an unknown root role", exit_code=5)
        root_roles[contract_id] = (
            "work" if "--work-root" in projected_roots else None,
            "artifact" if "--artifact-root" in projected_roots else None,
            "projection" if "--projection-root" in projected_roots else None,
        )
    required_work, required_artifact, required_projection = root_roles[contract_id]
    supplied = {"work": args.work_root, "artifact": args.artifact_root, "projection": args.projection_root}
    required = {name for name, marker in (("work", required_work), ("artifact", required_artifact), ("projection", required_projection)) if marker}
    if {name for name, value in supplied.items() if value is not None} != required:
        raise CycleError("E_ROOT_ROLE", "command root roles do not match the contract")

    roots: dict[str, tuple[Path, dict[str, int]]] = {
        name: _validate_delivery_root(Path(value))
        for name, value in supplied.items()
        if value is not None
    }
    source_root = Path(args.source_root)
    source_resolved = source_root.resolve(strict=True)
    if "work" in roots:
        work_resolved = roots["work"][0]
        if work_resolved == source_resolved or work_resolved.is_relative_to(source_resolved):
            raise CycleError("E_ROOT_ROLE", "Program work root must remain outside the source", exit_code=4)
    output_role = {
        "wp.complete.brief/2": "projection",
        "wp.complete.handoff/2": "artifact",
        "wp.render.handoff/2": "projection",
    }.get(contract_id)
    if contract_id == "wp.complete.card/2" and required_artifact:
        output_role = "artifact"
    output_root = roots.get(output_role, (None, None))[0] if output_role is not None else None
    source_publication = bool(
        output_root is not None
        and (output_root == source_resolved or output_root.is_relative_to(source_resolved))
    )
    program_contract = contract_id in {"wp.route.resume/2", "wp.complete.program/2", "wp.complete.program-card/2", "wp.render.program/2"}
    publication_capture: tuple[str, Any, dict[str, Any]] | None = None
    recovery_target: str | None = None
    if source_publication:
        publication_capture = _open_publication_capture(source_root)
        _, _, publication_before = publication_capture
        source_identity = _observation_identity(publication_before)
        output_relative = _relative_to_source(source_resolved, output_root)
        output_prefix = "" if output_relative == "." else output_relative + "/"
        candidate_patterns = {
            "wp.complete.brief/2": ("plan-brief--", ".md"),
            "wp.complete.handoff/2": ("plan-handoff--", ".json"),
            "wp.render.handoff/2": ("plan-handoff--", ".md"),
        }
        if contract_id == "wp.complete.card/2":
            artifact_id = command["previous_receipt"]["next_step"]["input_contract"]["artifact_id"]
            candidate_patterns[contract_id] = (artifact_id + "--", ".json")
        candidate_pattern = candidate_patterns[contract_id]
        base_exclusions: set[str] = set()
        expected_identity = command.get("previous_receipt", {}).get("source_identity") if command.get("previous_receipt") else None
        if contract_id == "wp.render.handoff/2":
            artifact_root = roots["artifact"][0]
            locator = command["fields"]["content_locator"]
            artifact_path = artifact_root / f"plan-handoff--{locator['content_hash'][7:]}.json"
            artifact_payload, _ = _read_regular(artifact_path)
            try:
                artifact_value = strict_json_bytes(artifact_payload, source=str(artifact_path))
                expected_identity = artifact_value["source_identity"]
            except (KeyError, TypeError, ValueError) as exc:
                raise CycleError("E_HANDOFF_INVALID", "handoff artifact source binding is invalid", exit_code=4) from exc
            if artifact_path.is_relative_to(source_resolved):
                base_exclusions.add(artifact_path.relative_to(source_resolved).as_posix())
        if expected_identity is not None and source_identity != expected_identity:
            matches: list[str] = []
            for relative in _observation_paths(publication_before):
                name = relative.removeprefix(output_prefix)
                if (
                    relative.startswith(output_prefix)
                    and "/" not in name
                    and name.startswith(candidate_pattern[0])
                    and name.endswith(candidate_pattern[1])
                    and _identity_without_paths(publication_before, base_exclusions | {relative}) == expected_identity
                ):
                    matches.append(relative)
            if len(matches) != 1:
                if _identity_without_paths(publication_before, base_exclusions) != expected_identity:
                    raise CycleError("E_SOURCE_REVISION_CHANGED", "source identity changed outside the authorized output", exit_code=3)
            else:
                recovery_target = matches[0]
            source_identity = expected_identity
        elif expected_identity is not None:
            source_identity = expected_identity
        full_source_identity = None
    else:
        full_source_identity = _capture_program_source(source_root) if program_contract else None
        source_identity = (
            {key: full_source_identity[key] for key in ("kind", "identity_hash")}
            if full_source_identity is not None
            else _capture_source(source_root)
        )
    if contract_id == "wp.route.initial/2":
        receipt = _route_initial(command, manifest, source_identity)
    elif contract_id == "wp.route.resume/2":
        work, _ = roots["work"]
        assert full_source_identity is not None
        receipt = _route_program_resume(command, manifest, source_root, full_source_identity, work)
    else:
        previous = None
        if command["previous_receipt"] is not None:
            previous = _validate_previous(
                schema,
                command["previous_receipt"],
                source_identity,
                allow_source_drift=contract_id == "wp.complete.program-card/2",
            )
            if previous["bundle_id"] != manifest["bundle_id"]:
                raise CycleError("E_RECEIPT_INVALID", "previous receipt bundle is stale", exit_code=3)
        if contract_id == "wp.complete.brief/2":
            projection, root_binding = roots["projection"]
            assert previous is not None
            receipt = _complete_brief(command, manifest, registry, previous, source_identity, projection, root_binding)
        elif contract_id == "wp.complete.card/2":
            artifact = roots.get("artifact", (None, None))[0]
            assert previous is not None
            receipt = _complete_standalone_card(command, schema, manifest, registry, previous, source_identity, artifact)
        elif contract_id == "wp.complete.handoff/2":
            artifact, root_binding = roots["artifact"]
            assert previous is not None
            receipt = _complete_handoff(command, manifest, previous, source_identity, artifact, root_binding)
        elif contract_id == "wp.complete.program/2":
            work, _ = roots["work"]
            assert previous is not None and full_source_identity is not None
            receipt = _complete_program_init(schema, command, manifest, previous, source_root, full_source_identity, work)
        elif contract_id == "wp.complete.program-card/2":
            work, _ = roots["work"]
            assert previous is not None and full_source_identity is not None
            receipt = _complete_program_card(command, manifest, previous, source_root, full_source_identity, work)
        elif contract_id == "wp.render.program/2":
            work, _ = roots["work"]
            assert full_source_identity is not None
            receipt = _render_program_projection(command, manifest, source_root, full_source_identity, work)
        elif contract_id == "wp.render.handoff/2":
            artifact, _ = roots["artifact"]
            projection, _ = roots["projection"]
            receipt = _render_handoff_projection(command, manifest, source_identity, artifact, projection)
        else:
            raise CycleError("E_UNSUPPORTED_VARIANT", "command contract is not active", exit_code=4)
    if publication_capture is not None:
        publication_kind, publication_session, publication_before = publication_capture
        assert output_root is not None
        target = output_root / _publication_filename(contract_id, receipt["content_locator"])
        relative_target = target.relative_to(source_resolved).as_posix()
        if recovery_target is not None and recovery_target != relative_target:
            raise CycleError("E_ORPHAN_CONFLICT", "recovered output does not match the deterministic locator", exit_code=5)
        publication_after = _publication_fence(publication_kind, publication_session)
        after_identity, transition = _publication_transition(publication_before, publication_after, relative_target)
        receipt["source_identity"] = after_identity
        receipt["source_transition"] = transition
        receipt["receipt_id"] = _receipt_id(receipt)
    _validate(schema, "receipt", receipt, "E_CONTRACT_INVALID")
    if len(_canonical(receipt)) + 1 > RECEIPT_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "receipt exceeds the byte limit", exit_code=4)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for name in ("route", "complete", "render"):
        command = subparsers.add_parser(name, add_help=name != "route")
        if name == "route":
            command.add_argument("-h", "--help", action=_RouteHelpAction, nargs=0)
        command.add_argument("--input", required=True)
        command.add_argument("--source-root", required=True)
        command.add_argument("--work-root")
        command.add_argument("--artifact-root")
        command.add_argument("--projection-root")
    return parser


def _emit_error(error: CycleError) -> int:
    payload = {
        "code": error.code,
        "message": " ".join(str(error).split())[:512] or "card cycle failed",
        "retryable": error.retryable,
    }
    encoded = _canonical(payload)
    if len(encoded) > 1_024:
        payload["message"] = "card cycle failed"
        encoded = _canonical(payload)
    sys.stderr.buffer.write(encoded + b"\n")
    return error.exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = _execute(args)
    except CycleError as exc:
        return _emit_error(exc)
    except (AssertionError, KeyError, OSError, TypeError, ValueError):
        return _emit_error(CycleError("E_CONTRACT_INVALID", "card cycle failed", exit_code=5))
    sys.stdout.buffer.write(_canonical(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
