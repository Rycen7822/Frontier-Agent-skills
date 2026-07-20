#!/usr/bin/env python3
"""Run one bounded SQW route or completion cycle without sibling control files."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import selectors
import stat
import subprocess
import sys
import time
from typing import Any

from jsonschema import Draft202012Validator

from _workflow_reference_cards import load_json, strict_json_bytes
from local_workflow_adapter import AdapterConflict, AdapterSourceDrift, LocalWorkflowAdapter, bootstrap_v3, project_source_snapshot
from project_context import render_owner_context
from route_workflow import assess, validate_route_result


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "card-protocol.schema.json"
REGISTRY_PATH = ROOT / "registries" / "artifact-family-contracts.json"
MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
POLICY_PATH = ROOT / "registries" / "policy-owners.json"
STATE_SCHEMA_PATH = ROOT / "schemas" / "workflow-state.schema.json"
EVENT_SCHEMA_PATH = ROOT / "schemas" / "workflow-event.schema.json"
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
SURFACE_FAMILIES = [
    "public_contract",
    "data_state",
    "security_privacy",
    "runtime_platform",
    "dependency_supply_chain",
    "browser_ui",
    "performance_resource",
    "plugin_installed_surface",
    "migration_release",
    "workspace_vcs",
    "external_side_effect",
    "test_fixture_benchmark",
    "observability_operations",
    "concurrency_shared_state",
]


class CycleError(ValueError):
    def __init__(self, code: str, message: str, *, exit_code: int = 2, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.retryable = retryable


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


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
    for card in manifest.get("cards", []):
        _card_input_contract(schema, registry, card)
    return schema, registry, manifest


def _read_command() -> dict[str, Any]:
    data = sys.stdin.buffer.read(COMMAND_MAX_BYTES + 1)
    if len(data) > COMMAND_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "command exceeds the byte limit", exit_code=4)
    try:
        value = strict_json_bytes(data, source="stdin")
    except ValueError as exc:
        raise CycleError("E_COMMAND_SCHEMA", "command is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CycleError("E_COMMAND_SCHEMA", "command must be one JSON object")
    return value


def _validate_command(schema: dict[str, Any], command: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(command), key=lambda item: list(item.path))
    if errors:
        field = "/".join(str(part) for part in errors[0].absolute_path) or "command"
        raise CycleError("E_COMMAND_SCHEMA", f"command field is invalid: {field}")


def _read_source_file(path: Path) -> tuple[str, int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source file cannot be opened", exit_code=5) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CycleError("E_SOURCE_UNAVAILABLE", "source contains a non-regular entry", exit_code=5)
        if before.st_size > SOURCE_FILE_MAX_BYTES:
            raise CycleError("E_SOURCE_UNAVAILABLE", "source file exceeds the byte limit", exit_code=5)
        chunks: list[bytes] = []
        remaining = SOURCE_FILE_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(payload) > SOURCE_FILE_MAX_BYTES or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise CycleError("E_SOURCE_DRIFT", "source changed during observation", exit_code=3, retryable=True)
        return "sha256:" + sha256(payload).hexdigest(), len(payload), f"{stat.S_IMODE(before.st_mode):04o}"
    finally:
        os.close(descriptor)


def _validated_source_root(source_root: Path) -> tuple[Path, os.stat_result]:
    try:
        info = source_root.lstat()
        resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is unavailable", exit_code=5) from exc
    if source_root.is_symlink() or not stat.S_ISDIR(info.st_mode) or resolved != source_root.absolute():
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is not canonical", exit_code=5)
    return resolved, info


def _repository_marker(source_root: Path) -> bool:
    current = source_root
    while True:
        marker = current / ".git"
        try:
            marker.lstat()
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
    streams = {stdout_descriptor: (process.stdout, stdout_cap), stderr_descriptor: (process.stderr, GIT_SMALL_OUTPUT_MAX)}
    captured: dict[int, bytearray] = {descriptor: bytearray() for descriptor in streams}
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
                if len(captured[descriptor]) > streams[descriptor][1]:
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


def _explicit_source_paths(source_root: Path, selectors_to_capture: tuple[str, ...]) -> list[str]:
    selected: set[str] = set()
    for selector_value in selectors_to_capture:
        if selector_value == "**":
            relative_root = PurePosixPath(".")
        elif selector_value.endswith("/**") and "*" not in selector_value[:-3]:
            relative_root = PurePosixPath(selector_value[:-3])
        elif "*" not in selector_value:
            relative_root = PurePosixPath(selector_value)
        else:
            raise CycleError("E_SOURCE_UNAVAILABLE", "source selector is invalid", exit_code=5)
        raw_root = relative_root.as_posix()
        if (
            relative_root.is_absolute()
            or raw_root == ".."
            or any(part in {"", ".."} for part in relative_root.parts)
            or any(ord(character) < 32 or ord(character) == 127 for character in selector_value)
        ):
            raise CycleError("E_SOURCE_UNAVAILABLE", "source selector is invalid", exit_code=5)
        candidate = source_root if raw_root == "." else source_root / raw_root
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISREG(info.st_mode):
            selected.add(candidate.relative_to(source_root).as_posix())
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise CycleError("E_SOURCE_UNAVAILABLE", "source selector resolves to an unsafe entry", exit_code=5)
        for current, directories, filenames in os.walk(candidate, followlinks=False):
            directories.sort()
            filenames.sort()
            current_path = Path(current)
            for name in directories:
                child_info = (current_path / name).lstat()
                if stat.S_ISLNK(child_info.st_mode) or not stat.S_ISDIR(child_info.st_mode):
                    raise CycleError("E_SOURCE_UNAVAILABLE", "source selector crosses an unsafe directory", exit_code=5)
            for name in filenames:
                selected.add((current_path / name).relative_to(source_root).as_posix())
                if len(selected) > SOURCE_MAX_FILES:
                    raise CycleError("E_SOURCE_UNAVAILABLE", "source selector exceeds its file bound", exit_code=5)
    return sorted(selected)


def _repository_observation(
    source_root: Path,
    root_info: os.stat_result,
    deadline: float,
    selectors_to_capture: tuple[str, ...],
) -> tuple[dict[str, Any], tuple[bytes, bytes, bytes]]:
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
        | set(_explicit_source_paths(source_root, selectors_to_capture))
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
        records.append({"path": relative, "content_hash": content_hash, "bytes": size, "mode": mode})
    observation = {
        "kind": "repository",
        "root_binding": {"dev": root_info.st_dev, "ino": root_info.st_ino},
        "head_commit": revision_parts[0],
        "head_tree": revision_parts[1],
        "records": sorted(records, key=lambda item: item["path"]),
    }
    return observation, (revision_raw, index_raw, status_raw)


def _unversioned_observation(resolved: Path, info: os.stat_result) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    total = 0
    for current, directories, filenames in os.walk(resolved, followlinks=False):
        directories[:] = [name for name in directories if name != ".git"]
        filenames[:] = [name for name in filenames if name != ".git"]
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        for name in directories:
            entry = current_path / name
            entry_info = entry.lstat()
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
    return {
        "kind": "unversioned",
        "root_binding": {"dev": info.st_dev, "ino": info.st_ino},
        "head_commit": None,
        "head_tree": None,
        "records": records,
    }


def _capture_source(
    source_root: Path,
    selectors_to_capture: tuple[str, ...] = (),
) -> tuple[dict[str, str], dict[str, Any]]:
    resolved, info = _validated_source_root(source_root)
    if _repository_marker(resolved):
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
        opening, opening_raw = _repository_observation(resolved, info, deadline, selectors_to_capture)
        closing, closing_raw = _repository_observation(resolved, info, deadline, selectors_to_capture)
        if opening_raw != closing_raw or opening != closing:
            raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    else:
        opening = _unversioned_observation(resolved, info)
        closing = _unversioned_observation(resolved, info)
        if opening != closing:
            raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    return {"kind": opening["kind"], "identity_hash": _hash(opening)}, opening


def _receipt_id(receipt: dict[str, Any]) -> str:
    return _hash({key: value for key, value in receipt.items() if key != "receipt_id"})


def _validate_receipt(schema: dict[str, Any], receipt: Any, source_identity: dict[str, str], *, enforce_source: bool = True) -> dict[str, Any]:
    validator_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/receipt",
    }
    errors = list(Draft202012Validator(validator_schema).iter_errors(receipt))
    if errors or not isinstance(receipt, dict):
        raise CycleError("E_RECEIPT_INVALID", "previous receipt is invalid", exit_code=3)
    if receipt["receipt_id"] != _receipt_id(receipt):
        raise CycleError("E_RECEIPT_INVALID", "previous receipt hash is invalid", exit_code=3)
    if enforce_source and receipt["source_identity"] != source_identity:
        raise CycleError("E_SOURCE_REVISION_CHANGED", "source identity changed", exit_code=3)
    return receipt


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
    if not isinstance(family, dict) or family.get("persistence_class") not in {"semantic_inline", "boundary_by_contract"}:
        raise CycleError("E_CONTRACT_INVALID", "selected artifact family is unavailable", exit_code=5)
    fields = _definition(schema, field_reference)
    required = sorted(fields.get("required", []))
    properties = fields["properties"]
    if any(name not in properties for name in required):
        raise CycleError("E_CONTRACT_INVALID", "human definition required fields are inconsistent", exit_code=5)
    if len(always) != len(set(always)) or set(always) - {"--source-root", "--work-root"}:
        raise CycleError("E_CONTRACT_INVALID", "input contract has an unknown root role", exit_code=5)
    for condition in conditional:
        definition = properties.get(condition.get("field"), {})
        if condition.get("arg") not in {"--work-root"} or not isinstance(definition.get("enum"), list) or not set(condition.get("in", [])) <= set(definition["enum"]):
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
    return {"contract_id": "sqw.route.initial/2", "required_fields": groups, "required_root_args": ["--source-root"]}


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


def _card_input_contract(schema: dict[str, Any], registry: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    if card.get("card_id", "").startswith("sqw.entry."):
        arguments = ("sqw.complete.entry/2", "#/$defs/entryFields", ["--source-root"], [])
    elif card.get("card_id") == "sqw.control.scope-authority-and-effects":
        arguments = (
            "sqw.complete.scope/2", "#/$defs/scopeFields", ["--source-root"],
            [{"arg": "--work-root", "field": "mode", "in": ["M2", "M3"]}],
        )
    else:
        artifact_ids = card.get("produced_artifact_ids", [])
        artifact_id = artifact_ids[0] if len(artifact_ids) == 1 else ""
        family_name = registry.get("artifacts", {}).get(artifact_id)
        field_reference = registry.get("families", {}).get(family_name, {}).get("human_def", "")
        arguments = ("sqw.complete.card/2", field_reference, ["--source-root", "--work-root"], [])
    return _input_contract(
        schema, registry, card, arguments[0], arguments[1], always=arguments[2], conditional=arguments[3]
    )


def _next_step(manifest: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
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


def _route_facts(fields: dict[str, Any], **queue: Any) -> dict[str, Any]:
    is_continuation = bool(
        queue.get("pending")
        or queue.get("available")
        or queue.get("completed")
        or queue.get("just_completed")
        or queue.get("decision_request")
    )
    return {
        "schema_version": "2.0",
        "route_phase": "active_queue" if is_continuation else "entry",
        **fields,
        "surface_assessment": {
            "taxonomy_version": "sqw-route-surfaces/1",
            "coverage": "complete",
            "assessed_families": SURFACE_FAMILIES,
            "evidence_refs": ["sqw-card-cycle/1"],
        },
        "pending_decision_ids": queue.get("pending", []),
        "available_artifact_ids": queue.get("available", []),
        "completed_decision_ids": queue.get("completed", []),
        "just_completed_card_id": queue.get("just_completed"),
        "decision_request": queue.get("decision_request"),
    }


def _select(manifest: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    route = assess(facts)
    if validate_route_result(route):
        raise CycleError("E_CONTRACT_INVALID", "route result is invalid", exit_code=5)
    if route["route_action"] == "terminal":
        return {"kind": "terminal", "decision_id": None, "reason_codes": route["reason_codes"]}
    return _next_step(manifest, route)


def _completion(
    artifact_id: str,
    producer_card_id: str,
    decision_id: str,
    fields: dict[str, Any],
    blocker: str | None,
    next_decision_id: str | None,
) -> dict[str, Any]:
    payload = {
        "artifact_id": artifact_id,
        "producer_card_id": producer_card_id,
        "decision_id": decision_id,
        "fields": fields,
        "outcome": {"blocker": blocker, "decision_request": next_decision_id},
    }
    return {**payload, "content_hash": _hash(payload)}


def _enforce_human_budget(registry: dict[str, Any], artifact_id: str, fields: dict[str, Any], outcome: dict[str, Any]) -> None:
    family_name = registry["artifacts"].get(artifact_id)
    family = registry["families"].get(family_name)
    if family is None:
        raise CycleError("E_CONTRACT_INVALID", "artifact family is unavailable", exit_code=5)
    if len(_canonical({"fields": fields, "outcome": outcome})) > family["human_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "human input exceeds its family budget", exit_code=4)


def _base_receipt(manifest: dict[str, Any], source_identity: dict[str, str], next_step: dict[str, Any]) -> dict[str, Any]:
    if next_step.get("kind") == "card":
        card = _card(manifest, next_step.get("card_id", ""))
        next_step = {**next_step, "input_contract": _card_input_contract(load_json(SCHEMA_PATH), load_json(REGISTRY_PATH), card)}
    return {
        "schema_version": "sqw-card-receipt/2",
        "receipt_kind": "route",
        "receipt_id": "",
        "bundle_id": manifest["bundle_id"],
        "skill_id": "software-quality-workflows",
        "source_identity": source_identity,
        "next_step": next_step,
        "route_context": None,
        "completion": None,
        "scope_binding": None,
        "owner_locator": None,
        "current_lease": None,
        "state_version": None,
        "state_hash": None,
        "source_fresh": True,
        "pending_source_transition": None,
        "already_completed": False,
        "projection_locator": None,
    }


def _route_initial(command: dict[str, Any], manifest: dict[str, Any], source_identity: dict[str, str]) -> dict[str, Any]:
    fields = command["fields"]
    receipt = _base_receipt(manifest, source_identity, _select(manifest, _route_facts(fields)))
    receipt["route_context"] = fields
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _route_resume(
    command: dict[str, Any],
    manifest: dict[str, Any],
    source_identity: dict[str, str],
    source_observation: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    adapter = LocalWorkflowAdapter(work_root, load_json(STATE_SCHEMA_PATH), load_json(EVENT_SCHEMA_PATH))
    expected_cards = {card["card_id"]: (card["path"], card["sha256"]) for card in manifest["cards"]}
    try:
        state, lease, pending_transition, source_fresh, blocked_reason = adapter.resume(
            command["fields"]["owner_locator"],
            source_identity,
            current_source_observation=source_observation,
            expected_bundle_id=manifest["bundle_id"],
            expected_policy_bundle_hash=_hash(load_json(POLICY_PATH)),
            expected_card_manifest_hash=_hash(manifest),
            expected_cards=expected_cards,
        )
    except AdapterSourceDrift as exc:
        raise CycleError("E_SOURCE_REVISION_CHANGED", str(exc), exit_code=5) from exc
    except AdapterConflict as exc:
        raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
    frontier = state["active_frontier"]
    next_step = (
        {"kind": "blocked", "decision_id": None, "reason_code": blocked_reason}
        if blocked_reason is not None
        else frontier or {"kind": "terminal", "decision_id": None, "reason_codes": ["ACTIVE_QUEUE_EMPTY"]}
    )
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "owner_locator": command["fields"]["owner_locator"],
        "current_lease": lease,
        "scope_binding": state["scope_binding"],
        "state_version": state["state_version"],
        "state_hash": state["state_hash"],
        "source_fresh": source_fresh,
        "pending_source_transition": pending_transition,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _producer_request(previous: dict[str, Any], artifact_id: str, requested: str) -> dict[str, str]:
    return {
        "decision_id": requested,
        "produced_by_card_id": previous["next_step"]["card_id"],
        "produced_artifact_id": artifact_id,
    }


def _complete_entry(
    command: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
) -> dict[str, Any]:
    entry_cards = {
        "sqw.entry.diagnose-failure", "sqw.entry.direct-change", "sqw.entry.intent-discovery",
        "sqw.entry.read-only-audit", "sqw.entry.recovery",
    }
    if previous["next_step"]["card_id"] not in entry_cards or previous["route_context"] is None:
        raise CycleError("E_RECEIPT_INVALID", "entry completion does not match the active card", exit_code=3)
    artifact_id = "workflow-intake"
    _enforce_human_budget(registry, artifact_id, command["fields"], command["outcome"])
    request = _producer_request(previous, artifact_id, "sqw.select.control.scope-authority-and-effects")
    next_step = _select(
        manifest,
        _route_facts(
            previous["route_context"],
            available=[artifact_id],
            completed=[previous["next_step"]["decision_id"]],
            just_completed=previous["next_step"]["card_id"],
            decision_request=request,
        ),
    )
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion",
        "route_context": previous["route_context"],
        "completion": _completion(
            artifact_id,
            previous["next_step"]["card_id"],
            previous["next_step"]["decision_id"],
            command["fields"],
            command["outcome"]["blocker"],
            request["decision_id"],
        ),
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _normalize_paths(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        path = PurePosixPath(value)
        if path.is_absolute() or value in {"", "."} or any(part in {"", ".", ".."} for part in path.parts):
            raise CycleError("E_SCOPE_PATH", "scope path is not canonical", exit_code=4)
        if any(ord(character) < 32 for character in value):
            raise CycleError("E_SCOPE_PATH", "scope path contains a control character", exit_code=4)
        normalized.append(path.as_posix())
    return sorted(normalized)


def _complete_scope(
    command: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
) -> dict[str, Any]:
    if previous["next_step"]["card_id"] != "sqw.control.scope-authority-and-effects":
        raise CycleError("E_RECEIPT_INVALID", "scope completion does not match the active card", exit_code=3)
    artifact_id = "control-scope-authority-and-effects"
    fields = dict(command["fields"])
    fields["allowed_reads"] = _normalize_paths(fields["allowed_reads"])
    fields["allowed_writes"] = _normalize_paths(fields["allowed_writes"])
    _enforce_human_budget(registry, artifact_id, fields, command["outcome"])
    context = previous["route_context"]
    if context["root_cause_status"] == "unknown":
        next_decision = "sqw.select.diagnosis.evidence-and-hypothesis"
    elif context["intent_status"] == "materially_underdefined":
        next_decision = "sqw.select.intent.discovery-and-freeze"
    elif context["request_mode"] == "recovery":
        next_decision = "sqw.select.recovery.repository-recovery"
    elif context["request_mode"] == "review":
        next_decision = "sqw.select.review.tier-selection"
    elif context["request_mode"] == "report":
        next_decision = "sqw.select.verify.classification-and-completion"
    else:
        next_decision = "sqw.select.test.behavior-cycle"
    request = _producer_request(previous, artifact_id, next_decision)
    prior_decision = previous["completion"]["decision_id"]
    next_step = _select(
        manifest,
        _route_facts(
            previous["route_context"],
            available=["workflow-intake", artifact_id],
            completed=[prior_decision, previous["next_step"]["decision_id"]],
            just_completed=previous["next_step"]["card_id"],
            decision_request=request,
        ),
    )
    binding_payload = {**fields, "source_identity": source_identity}
    scope_binding = {"binding_id": _hash(binding_payload), **fields}
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion",
        "completion": _completion(
            artifact_id,
            previous["next_step"]["card_id"],
            previous["next_step"]["decision_id"],
            fields,
            command["outcome"]["blocker"],
            request["decision_id"],
        ),
        "scope_binding": scope_binding,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _complete_active(
    command: dict[str, Any],
    schema: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    source_snapshot: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    card = _card(manifest, previous["next_step"]["card_id"])
    artifact_ids = card["produced_artifact_ids"]
    if len(artifact_ids) != 1:
        raise CycleError("E_CONTRACT_INVALID", "active card must produce exactly one artifact", exit_code=5)
    artifact_id = artifact_ids[0]
    family_name = registry["artifacts"][artifact_id]
    family = registry["families"][family_name]
    if family["persistence_class"] not in {"semantic_inline", "boundary_by_contract"}:
        raise CycleError("E_UNSUPPORTED_VARIANT", "artifact persistence class is not active", exit_code=4)
    human_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": family["human_def"]}
    if list(Draft202012Validator(human_schema).iter_errors(command["fields"])):
        raise CycleError("E_COMMAND_SCHEMA", "human fields do not match the routed artifact family")
    _enforce_human_budget(registry, artifact_id, command["fields"], command["outcome"])
    if command["outcome"]["blocker"] is not None:
        raise CycleError("E_UNSUPPORTED_VARIANT", "blocked durable completion requires the blocked route slice", exit_code=4)
    completion = _completion(
        artifact_id,
        previous["next_step"]["card_id"],
        previous["next_step"]["decision_id"],
        command["fields"],
        None,
        command["outcome"]["decision_request"],
    )
    completion["source_transition"] = previous["pending_source_transition"]
    completion["content_hash"] = _hash({key: value for key, value in completion.items() if key != "content_hash"})
    if len(_canonical(completion)) > family["payload_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "completion payload exceeds its family budget", exit_code=4)
    materialized = family["persistence_class"] == "boundary_by_contract"
    artifact_payload = _canonical({key: value for key, value in completion.items() if key != "content_hash"}) + b"\n" if materialized else None
    content_locator = {
        "schema_version": "content-locator/1",
        "content_kind": "artifact",
        "artifact_id": artifact_id,
        "content_hash": completion["content_hash"],
        "bytes": len(artifact_payload),
    } if materialized else None

    def select_next(state: dict[str, Any], current_completion: dict[str, Any]) -> dict[str, Any]:
        decision_by_card = {item["card_id"]: item["decision_id"] for item in manifest["cards"]}
        inline = [entry.get("completion", {}) for entry in state["card_completions"] if entry["storage"] == "inline"]
        materialized_entries = [entry for entry in state["card_completions"] if entry["storage"] == "materialized"]
        available = [item["artifact_id"] for item in inline if isinstance(item.get("artifact_id"), str)]
        available.extend(item["artifact_id"] for item in materialized_entries)
        completed = [item["decision_id"] for item in inline if isinstance(item.get("decision_id"), str)]
        completed.extend(decision_by_card[item["card_id"]] for item in materialized_entries)
        available.append(current_completion["artifact_id"])
        completed.append(current_completion["decision_id"])
        requested = current_completion["outcome"]["decision_request"]
        decision_request = None if requested is None else {
            "decision_id": requested,
            "produced_by_card_id": current_completion["producer_card_id"],
            "produced_artifact_id": current_completion["artifact_id"],
        }
        context = {
            "request_mode": state["request_mode"],
            "intent_status": "adequate",
            "root_cause_status": "known",
            "implicated_surfaces": [],
            "unknown_implicated_facts": [],
            "persistence_need": "durable",
            "delegation_need": "none",
            "external_side_effect": "none",
        }
        return _select(
            manifest,
            _route_facts(
                context,
                available=available,
                completed=completed,
                just_completed=current_completion["producer_card_id"],
                decision_request=decision_request,
            ),
        )

    adapter = LocalWorkflowAdapter(work_root, load_json(STATE_SCHEMA_PATH), load_json(EVENT_SCHEMA_PATH))
    owner_receipt = {
        **previous,
        "next_step": {key: value for key, value in previous["next_step"].items() if key != "input_contract"},
    }
    try:
        state, lease, completion_outcome = adapter.complete_card(
            previous["owner_locator"],
            owner_receipt,
            source_identity,
            completion,
            select_next,
            current_source_snapshot=source_snapshot,
            materialized_payload=artifact_payload,
            content_locator=content_locator,
            expected_bundle_id=manifest["bundle_id"],
            expected_policy_bundle_hash=_hash(load_json(POLICY_PATH)),
            expected_card_manifest_hash=_hash(manifest),
            expected_cards={item["card_id"]: (item["path"], item["sha256"]) for item in manifest["cards"]},
        )
    except AdapterSourceDrift as exc:
        raise CycleError("E_SOURCE_REVISION_CHANGED", str(exc), exit_code=5) from exc
    except AdapterConflict as exc:
        raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
    blocked_reason = completion_outcome.split(":", 1)[1] if completion_outcome.startswith("replayed_blocked:") else None
    next_step = (
        {"kind": "blocked", "decision_id": None, "reason_code": blocked_reason}
        if blocked_reason is not None
        else state["active_frontier"] or {"kind": "terminal", "decision_id": None, "reason_codes": ["ACTIVE_QUEUE_EMPTY"]}
    )
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion",
        "completion": ({
            "artifact_id": completion["artifact_id"],
            "content_hash": completion["content_hash"],
            "producer_card_id": completion["producer_card_id"],
            "decision_id": completion["decision_id"],
            "outcome": completion["outcome"],
            "content_locator": content_locator,
        } if materialized else completion),
        "scope_binding": state["scope_binding"],
        "owner_locator": previous["owner_locator"],
        "current_lease": lease,
        "state_version": state["state_version"],
        "state_hash": state["state_hash"],
        "source_fresh": blocked_reason is None,
        "already_completed": completion_outcome != "committed",
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _render_context(
    command: dict[str, Any],
    manifest: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    work_root: Path,
) -> dict[str, Any]:
    adapter = LocalWorkflowAdapter(work_root, load_json(STATE_SCHEMA_PATH), load_json(EVENT_SCHEMA_PATH))
    try:
        state, metadata, projection_locator, replayed = adapter.render_context(
            previous["owner_locator"],
            source_identity,
            lambda current: render_owner_context(current, budget_bytes=command["fields"]["budget_bytes"]),
            expected_state_version=previous["state_version"],
            expected_state_hash=previous["state_hash"],
            expected_bundle_id=manifest["bundle_id"],
            expected_policy_bundle_hash=_hash(load_json(POLICY_PATH)),
            expected_card_manifest_hash=_hash(manifest),
        )
    except AdapterSourceDrift as exc:
        raise CycleError("E_SOURCE_REVISION_CHANGED", str(exc), exit_code=5) from exc
    except (AdapterConflict, ValueError) as exc:
        raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
    receipt = _base_receipt(
        manifest,
        source_identity,
        {"kind": "terminal", "decision_id": None, "reason_codes": ["CONTEXT_RENDERED"]},
    )
    receipt.update({
        "receipt_kind": "render",
        "scope_binding": state["scope_binding"],
        "owner_locator": previous["owner_locator"],
        "state_version": state["state_version"],
        "state_hash": state["state_hash"],
        "already_completed": replayed,
        "projection_locator": projection_locator,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.input != "-":
        raise CycleError("E_COMMAND_SCHEMA", "--input must be stdin")
    schema, registry, manifest = _load_contracts()
    command = _read_command()
    _validate_command(schema, command)
    is_route = command["contract_id"] in {"sqw.route.initial/2", "sqw.route.resume/2"}
    is_render = command["contract_id"] == "sqw.render.context/2"
    expected_subcommand = "route" if is_route else "render" if is_render else "complete"
    if args.subcommand != expected_subcommand:
        raise CycleError("E_COMMAND_SCHEMA", "subcommand does not match contract")
    durable_scope = command["contract_id"] == "sqw.complete.scope/2" and command["fields"]["mode"] in {"M2", "M3"}
    durable_resume = command["contract_id"] == "sqw.route.resume/2"
    durable_active = command["contract_id"] == "sqw.complete.card/2"
    contract_roots: set[str] = set()
    if command["contract_id"].startswith("sqw.complete."):
        input_contract = command["previous_receipt"]["next_step"].get("input_contract")
        if not isinstance(input_contract, dict) or input_contract.get("completion_contract_id") != command["contract_id"]:
            raise CycleError("E_RECEIPT_INVALID", "completion does not match the projected input contract", exit_code=3)
        root_contract = input_contract["required_root_args"]
        contract_roots.update(root_contract["always"])
        for condition in root_contract["conditional"]:
            if command["fields"].get(condition["field"]) in condition["in"]:
                contract_roots.add(condition["arg"])
    requires_work = durable_resume or is_render or "--work-root" in contract_roots
    if requires_work and args.work_root is None:
        raise CycleError("E_ROOT_ROLE", "durable command requires a work root")
    if not requires_work and args.work_root is not None:
        raise CycleError("E_ROOT_ROLE", "this command does not accept a work root")
    source_selectors: tuple[str, ...] = ()
    if command["contract_id"] == "sqw.complete.scope/2":
        source_selectors = tuple(sorted(set(command["fields"]["allowed_reads"]) | set(command["fields"]["allowed_writes"])))
    elif command.get("previous_receipt") and command["previous_receipt"].get("scope_binding"):
        binding = command["previous_receipt"]["scope_binding"]
        source_selectors = tuple(sorted(set(binding["allowed_reads"]) | set(binding["allowed_writes"])))
    elif durable_resume:
        try:
            established = LocalWorkflowAdapter(
                Path(args.work_root), load_json(STATE_SCHEMA_PATH), load_json(EVENT_SCHEMA_PATH)
            )._read_state()
        except AdapterConflict as exc:
            raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
        binding = established["scope_binding"]
        source_selectors = tuple(sorted(set(binding["allowed_reads"]) | set(binding["allowed_writes"])))
    source_identity, source_observation = _capture_source(Path(args.source_root), source_selectors)
    if command["contract_id"] == "sqw.route.initial/2":
        receipt = _route_initial(command, manifest, source_identity)
    elif durable_resume:
        receipt = _route_resume(command, manifest, source_identity, source_observation, Path(args.work_root))
    else:
        previous = _validate_receipt(schema, command["previous_receipt"], source_identity, enforce_source=not durable_active)
        if previous["bundle_id"] != manifest["bundle_id"]:
            raise CycleError("E_RECEIPT_INVALID", "previous receipt bundle is stale", exit_code=3)
        if is_render:
            receipt = _render_context(command, manifest, previous, source_identity, Path(args.work_root))
        elif command["contract_id"] == "sqw.complete.entry/2":
            receipt = _complete_entry(command, manifest, registry, previous, source_identity)
        elif command["contract_id"] == "sqw.complete.scope/2":
            receipt = _complete_scope(command, manifest, registry, previous, source_identity)
            if durable_scope:
                try:
                    state, locator, lease = bootstrap_v3(
                        Path(args.work_root),
                        Path(args.source_root),
                        bundle_id=manifest["bundle_id"],
                        policy_bundle_hash=_hash(load_json(POLICY_PATH)),
                        card_manifest_hash=_hash(manifest),
                        mode=command["fields"]["mode"],
                        request_mode=previous["route_context"]["request_mode"],
                        entry_completion=previous["completion"],
                        scope_completion=receipt["completion"],
                        scope_binding=receipt["scope_binding"],
                        source_identity=source_identity,
                        source_snapshot=project_source_snapshot(source_observation, source_identity, receipt["scope_binding"]),
                        next_step={key: value for key, value in receipt["next_step"].items() if key != "input_contract"},
                    )
                except AdapterConflict as exc:
                    raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
                receipt["owner_locator"] = locator
                receipt["current_lease"] = lease
                receipt["state_version"] = state["state_version"]
                receipt["state_hash"] = state["state_hash"]
                receipt["receipt_id"] = _receipt_id(receipt)
        elif durable_active:
            source_snapshot = project_source_snapshot(source_observation, source_identity, previous["scope_binding"])
            receipt = _complete_active(command, schema, manifest, registry, previous, source_identity, source_snapshot, Path(args.work_root))
        else:
            raise CycleError("E_UNSUPPORTED_VARIANT", "command contract is not active", exit_code=4)
    receipt_validator = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/receipt",
    }
    if list(Draft202012Validator(receipt_validator).iter_errors(receipt)):
        raise CycleError("E_CONTRACT_INVALID", "generated receipt is invalid", exit_code=5)
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
    return parser


def _emit_error(error: CycleError) -> int:
    message = " ".join(str(error).split())[:512] or "card cycle failed"
    payload = {"code": error.code, "message": message, "retryable": error.retryable}
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
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return _emit_error(CycleError("E_CONTRACT_INVALID", "card cycle failed", exit_code=5))
    sys.stdout.buffer.write(_canonical(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
