#!/usr/bin/env python3
"""Canonical evidence bytes, hashes, contained paths, and atomic writes."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import sys
from typing import Any, Mapping


SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def normalize_relative_path(reference: Any, label: str) -> str:
    if not isinstance(reference, str) or not reference or "\\" in reference:
        raise ValueError(f"{label} must be a non-empty POSIX relative path")
    if reference.startswith("/"):
        raise ValueError(f"{label} path escapes its declared root")
    relative = PurePosixPath(reference)
    if any(part == ".." for part in relative.parts):
        raise ValueError(f"{label} path escapes its declared root")
    normalized = relative.as_posix()
    if normalized in {"", "."}:
        raise ValueError(f"{label} must identify a path")
    return normalized


def resolve_contained_path(
    root: Path,
    reference: Any,
    label: str,
    *,
    kind: str | None = None,
) -> tuple[str, Path]:
    normalized = normalize_relative_path(reference, label)
    resolved_root = root.resolve()
    resolved = (resolved_root / normalized).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{label} path escapes its declared root")
    if kind is not None and not resolved.exists():
        raise FileNotFoundError(f"{label} {kind} is missing: {normalized}")
    if kind == "file" and not resolved.is_file():
        raise ValueError(f"{label} is not a regular file: {normalized}")
    if kind == "directory" and not resolved.is_dir():
        raise ValueError(f"{label} is not a directory: {normalized}")
    if kind not in {None, "file", "directory"}:
        raise ValueError(f"unknown contained path kind: {kind}")
    return normalized, resolved


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}") from None
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid UTF-8 in {path}: {exc}") from None
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from None


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes, *, replace: bool = False) -> None:
    if path.is_symlink():
        raise ValueError(f"output path must not be a symlink: {path}")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError(f"output parent must be a regular directory: {parent}")
    if path.exists() and not replace:
        raise FileExistsError(f"refusing to overwrite existing output: {path}")

    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() and not replace:
            raise FileExistsError(f"refusing to overwrite existing output: {path}")
        os.replace(temporary, path)
        _fsync_directory(parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any, *, replace: bool = False) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value), replace=replace)


def artifact_record(path: Path, root: Path, *, encoding: str) -> dict[str, str]:
    if encoding not in {"utf-8", "binary"}:
        raise ValueError("artifact encoding must be utf-8 or binary")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError("artifact path escapes its declared root")
    if not resolved.is_file():
        raise ValueError(f"artifact is not a regular file: {path}")
    if encoding == "utf-8":
        try:
            resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"artifact is not valid UTF-8: {path}: {exc}") from None
    relative = resolved.relative_to(resolved_root).as_posix()
    return {"path": relative, "digest": file_sha256(resolved), "encoding": encoding}


def _json_pointer_target(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer must be empty or begin with /")
    current = value
    for raw_token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", raw_token):
            raise ValueError("JSON Pointer contains invalid escape")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                raise ValueError("JSON Pointer target does not exist")
            current = current[token]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ValueError("JSON Pointer array index is invalid")
            index = int(token)
            if index >= len(current):
                raise ValueError("JSON Pointer target does not exist")
            current = current[index]
        else:
            raise ValueError("JSON Pointer traverses a scalar")
    return current


def validate_locator(
    locator: Any,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    if not isinstance(locator, dict):
        raise ValueError("locator must be an object")
    kind = locator.get("kind")
    expected_fields = {
        "text_lines": {"kind", "artifact", "start_line", "end_line"},
        "json_pointer": {"kind", "artifact", "json_pointer"},
        "byte_range": {"kind", "artifact", "start_byte", "end_byte_exclusive"},
    }
    if kind not in expected_fields or set(locator) != expected_fields[kind]:
        raise ValueError("locator must match exactly one supported locator shape")
    artifact = normalize_relative_path(locator.get("artifact"), "locator artifact")
    if artifact not in artifacts:
        raise ValueError(f"locator artifact is not verified: {artifact}")
    record = artifacts[artifact]
    resolved = record.get("resolved")
    if not isinstance(resolved, Path) or not resolved.is_file():
        raise ValueError(f"locator artifact is not a regular file: {artifact}")

    if kind == "text_lines":
        if record.get("encoding") != "utf-8":
            raise ValueError("text locator requires a UTF-8 artifact")
        start = locator["start_line"]
        end = locator["end_line"]
        lines = record.get("lines")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
            or not isinstance(lines, list)
            or end > len(lines)
            or not any(line for line in lines[start - 1 : end])
        ):
            raise ValueError("text locator range is empty or out of bounds")
        return

    if kind == "json_pointer":
        if record.get("encoding") != "utf-8":
            raise ValueError("JSON Pointer locator requires a UTF-8 artifact")
        pointer = locator["json_pointer"]
        if not isinstance(pointer, str):
            raise ValueError("json_pointer must be a string")
        try:
            value = json.loads(record.get("text", ""))
        except json.JSONDecodeError as exc:
            raise ValueError(f"locator artifact is not valid JSON: {exc.msg}") from None
        _json_pointer_target(value, pointer)
        return

    start = locator["start_byte"]
    end = locator["end_byte_exclusive"]
    size = resolved.stat().st_size
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end <= start
        or end > size
    ):
        raise ValueError("byte locator range is empty or out of bounds")


def resolve_host_command(
    host: dict[str, Any],
    contract_root: Path,
) -> tuple[list[str], dict[str, str]]:
    command = host["command"]
    executable = Path(command["resolved_executable"])
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or executable.is_symlink()
    ):
        raise ValueError("host resolved executable must be an absolute regular file")
    if file_sha256(executable) != command["executable_digest"]:
        raise ValueError("host executable digest mismatch")
    declared = command["argv"]
    declared_executable = Path(declared[0])
    if declared_executable.is_absolute():
        declared_resolution = declared_executable.resolve()
    elif len(declared_executable.parts) == 1:
        declared_resolution = (executable.parent / declared[0]).resolve()
    else:
        raise ValueError("host argv[0] must be absolute or an executable name")
    if declared_resolution != executable.resolve():
        raise ValueError("host argv[0] does not resolve to the bound executable")

    argv = [str(executable.resolve())]
    for argument in declared[1:]:
        candidate = contract_root / argument
        argv.append(str(candidate.resolve()) if candidate.is_file() else argument)
    repository_scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(repository_scripts) not in sys.path:
        sys.path.insert(0, str(repository_scripts))
    from _codex_eval_delivery import DeliveryError, project_command_environment

    try:
        environment = project_command_environment(command, dict(os.environ))
    except DeliveryError as exc:
        raise ValueError(str(exc)) from exc
    return argv, environment
