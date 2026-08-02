#!/usr/bin/env python3
"""Canonical evidence bytes, hashes, contained paths, and atomic writes."""

from __future__ import annotations

import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping


SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return "sha256:" + sha256(canonical_json_bytes(value)).hexdigest()


def canonical_self_hash(value: dict[str, Any], field: str) -> str:
    if not isinstance(value, dict) or field not in value:
        raise ValueError(f"{field} is required for self-hash verification")
    payload = dict(value)
    payload.pop(field)
    return canonical_sha256(payload)


def verify_self_hash(value: Any, field: str) -> bool:
    if not isinstance(value, dict):
        return False
    claimed = value.get(field)
    return (
        isinstance(claimed, str)
        and SHA256_RE.fullmatch(claimed) is not None
        and claimed == canonical_self_hash(value, field)
    )


def file_sha256(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def stable_sha256_sort_key(value: Any) -> bytes:
    return sha256(canonical_json_bytes(value)).digest()


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


def load_jsonl_objects(path: Path) -> list[tuple[int, dict[str, Any]]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise ValueError(f"file not found: {path}") from None
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid UTF-8 in {path}: {exc}") from None
    records: list[tuple[int, dict[str, Any]]] = []
    for line_no, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid JSONL in {path} line {line_no}: {exc.msg}"
            ) from None
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record in {path} line {line_no} must be an object")
        records.append((line_no, value))
    return records


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


def atomic_write_jsonl(
    path: Path,
    records: Iterable[Any],
    *,
    replace: bool = False,
) -> None:
    payload = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    atomic_write_bytes(path, payload, replace=replace)


def _rename_no_replace(source: Path, destination: Path) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise ValueError("atomic no-replace publication is unavailable") from None
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    ) == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise FileExistsError(
            f"refusing to overwrite existing output root: {destination}",
        )
    raise OSError(error, os.strerror(error), destination)


def atomic_write_directory(
    path: Path,
    files: Mapping[str, bytes],
) -> None:
    if not files:
        raise ValueError("atomic directory output requires at least one file")
    if path.is_symlink() or path.exists():
        raise FileExistsError(f"refusing to overwrite existing output root: {path}")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError(f"output parent must be a regular directory: {parent}")

    normalized_files: dict[str, bytes] = {}
    for name, payload in files.items():
        normalized = normalize_relative_path(name, "atomic directory file")
        if PurePosixPath(normalized).parent != PurePosixPath("."):
            raise ValueError("atomic directory files must be top-level names")
        if not isinstance(payload, bytes):
            raise TypeError("atomic directory payloads must be bytes")
        normalized_files[normalized] = payload
    if len(normalized_files) != len(files):
        raise ValueError("atomic directory file names must be distinct")

    temporary = Path(tempfile.mkdtemp(
        dir=parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    ))
    try:
        for name in sorted(normalized_files):
            atomic_write_bytes(temporary / name, normalized_files[name])
        _rename_no_replace(temporary, path)
        _fsync_directory(parent)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


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
    return {"path": relative, "sha256": file_sha256(resolved), "encoding": encoding}


def verify_artifact_records(
    records: Any,
    root: Path,
    *,
    label: str = "artifact",
) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list):
        raise ValueError(f"{label} artifacts must be an array")
    verified: dict[str, dict[str, Any]] = {}
    resolved_paths: set[Path] = set()
    for index, record in enumerate(records):
        item_label = f"{label} artifacts[{index}]"
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "encoding"}:
            raise ValueError(
                f"{item_label} must contain exactly path, sha256, and encoding"
            )
        normalized, resolved = resolve_contained_path(
            root, record.get("path"), f"{label} artifact", kind="file"
        )
        if normalized in verified:
            raise ValueError(f"{label} duplicate normalized artifact path: {normalized}")
        if record["path"] != normalized:
            raise ValueError(f"{label} artifact path is not canonical: {record['path']}")
        if resolved in resolved_paths:
            raise ValueError(f"{label} duplicate resolved artifact path: {normalized}")
        if record.get("encoding") not in {"utf-8", "binary"}:
            raise ValueError(f"{item_label}.encoding must be utf-8 or binary")
        claimed_hash = record.get("sha256")
        if not isinstance(claimed_hash, str) or SHA256_RE.fullmatch(claimed_hash) is None:
            raise ValueError(f"{item_label}.sha256 must be sha256:<64 lowercase hex>")
        actual_hash = file_sha256(resolved)
        if claimed_hash != actual_hash:
            raise ValueError(
                f"{label} artifact sha256 mismatch for {normalized}: "
                f"expected {claimed_hash}, got {actual_hash}"
            )
        item: dict[str, Any] = {**record, "resolved": resolved}
        if record["encoding"] == "utf-8":
            try:
                item["text"] = resolved.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(
                    f"{label} UTF-8 artifact is not decodable: {normalized}: {exc}"
                ) from None
            item["lines"] = item["text"].splitlines()
        verified[normalized] = item
        resolved_paths.add(resolved)
    return verified


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
