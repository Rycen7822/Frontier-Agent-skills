#!/usr/bin/env python3
"""Validate and deterministically assemble explicit Markdown section files."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import NoReturn


FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+|$)")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-+*]|\d+[.)])[ \t]+\S")
BLOCKQUOTE = re.compile(r"^ {0,3}>[ \t]?\S")
THEMATIC_BREAK = re.compile(r"^ {0,3}(?:\*[ \t]*){3,}$|^ {0,3}(?:-[ \t]*){3,}$|^ {0,3}(?:_[ \t]*){3,}$")
TABLE_DELIMITER = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*)\|?\s*$")


class ContractError(Exception):
    def __init__(self, code: str, path: Path | str, line: int = 1, *, exit_code: int = 2) -> None:
        super().__init__(code)
        self.code = code
        self.path = str(path)
        self.line = line
        self.exit_code = exit_code


class ContractParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ContractError("E_ARGUMENT", "<args>")


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ContractError("E_SYMLINK", path)
        if not cursor.exists():
            break


def _read_regular(path: Path) -> bytes:
    _reject_symlink_components(path)
    try:
        info = path.stat()
    except OSError as exc:
        raise ContractError("E_INPUT_IO", path, exit_code=3) from exc
    if not stat.S_ISREG(info.st_mode):
        raise ContractError("E_NOT_REGULAR", path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ContractError("E_INPUT_IO", path, exit_code=3) from exc
    if not raw or not raw.strip():
        raise ContractError("E_EMPTY", path)
    if b"\r" in raw:
        line = raw[: raw.index(b"\r")].count(b"\n") + 1
        raise ContractError("E_CRLF", path, line)
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        raise ContractError("E_UTF8", path, line) from exc
    return raw


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return TABLE_DELIMITER.fullmatch(line) is not None or "|" in stripped


def _validate_source_style(path: Path, raw: bytes) -> None:
    lines = raw.decode("utf-8").splitlines()
    fence_char: str | None = None
    fence_width = 0
    fence_line = 1
    previous = "boundary"
    for number, line in enumerate(lines, start=1):
        if fence_char is not None:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence_char)}{{{fence_width},}}[ \t]*", line):
                fence_char = None
                previous = "boundary"
            continue
        opening = FENCE_OPEN.match(line)
        if opening:
            fence = opening.group(1)
            fence_char = fence[0]
            fence_width = len(fence)
            fence_line = number
            previous = "boundary"
            continue
        if not line.strip() or HEADING.match(line) or _is_table_line(line) or THEMATIC_BREAK.fullmatch(line):
            previous = "boundary"
            continue
        if LIST_ITEM.match(line):
            previous = "list"
            continue
        if BLOCKQUOTE.match(line):
            if previous == "blockquote":
                raise ContractError("E_HARD_WRAP_BLOCKQUOTE", path, number)
            previous = "blockquote"
            continue
        if previous == "plain":
            raise ContractError("E_HARD_WRAP_PROSE", path, number)
        if previous == "list":
            raise ContractError("E_HARD_WRAP_LIST", path, number)
        previous = "plain"
    if fence_char is not None:
        raise ContractError("E_UNCLOSED_FENCE", path, fence_line)


def _read_sources(paths: list[Path]) -> list[tuple[Path, bytes]]:
    if not paths:
        raise ContractError("E_ARGUMENT", "<args>")
    sources: list[tuple[Path, bytes]] = []
    identities: list[tuple[int, int]] = []
    for path in paths:
        raw = _read_regular(path)
        info = path.stat()
        identity = (info.st_dev, info.st_ino)
        if identity in identities:
            raise ContractError("E_DUPLICATE", path)
        identities.append(identity)
        _validate_source_style(path, raw)
        sources.append((path, raw))
    return sources


def _trim_section_boundary(raw: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    while lines and not lines[-1].rstrip(b"\r\n").strip(b" \t"):
        lines.pop()
    body = b"".join(lines)
    return body.rstrip(b"\n")


def _candidate(sources: list[tuple[Path, bytes]]) -> bytes:
    bodies = [_trim_section_boundary(raw) for _, raw in sources]
    if any(not body for body in bodies):
        raise ContractError("E_EMPTY", sources[bodies.index(b"")][0])
    return b"\n\n".join(bodies) + b"\n"


def _status(status: str, raw: bytes) -> str:
    return json.dumps(
        {"status": status, "bytes": len(raw), "sha256": "sha256:" + sha256(raw).hexdigest()},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _style_status(sources: list[tuple[Path, bytes]]) -> str:
    digest = sha256()
    digest.update(b"source-style-v1\0")
    total = 0
    for _, raw in sources:
        total += len(raw)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return json.dumps(
        {"status": "source_style_valid", "bytes": total, "sha256": "sha256:" + digest.hexdigest()},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _check_output(output: Path, candidate: bytes) -> None:
    _reject_symlink_components(output)
    if not output.exists():
        raise ContractError("E_OUTPUT_MISSING", output, exit_code=1)
    try:
        if not output.is_file():
            raise ContractError("E_OUTPUT_TYPE", output)
        current = output.read_bytes()
    except ContractError:
        raise
    except OSError as exc:
        raise ContractError("E_OUTPUT_IO", output, exit_code=3) from exc
    if current != candidate:
        raise ContractError("E_OUTPUT_MISMATCH", output, exit_code=1)


def _write_atomic(output: Path, candidate: bytes) -> str:
    _reject_symlink_components(output)
    parent = output.parent
    if not parent.is_dir():
        raise ContractError("E_OUTPUT_PARENT", parent, exit_code=3)
    if output.exists():
        if output.is_symlink() or not output.is_file():
            raise ContractError("E_OUTPUT_TYPE", output)
        try:
            if output.read_bytes() == candidate:
                return "unchanged"
        except OSError as exc:
            raise ContractError("E_OUTPUT_IO", output, exit_code=3) from exc
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{output.name}.", dir=parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(candidate)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        temporary = None
        directory_descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ContractError("E_ATOMIC_WRITE", output, exit_code=3) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return "written"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = ContractParser(description=__doc__, add_help=True)
    parser.add_argument("--section", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--check-source-style", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    style_mode = bool(args.check_source_style)
    assembly_mode = bool(args.section or args.output or args.check)
    if style_mode == assembly_mode:
        raise ContractError("E_ARGUMENT", "<args>")
    if assembly_mode and (not args.section or args.output is None):
        raise ContractError("E_ARGUMENT", "<args>")
    return args


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse(argv)
        if args.check_source_style:
            print(_style_status(_read_sources(args.check_source_style)))
            return 0
        sources = _read_sources(args.section)
        candidate = _candidate(sources)
        if args.check:
            _check_output(args.output, candidate)
            print(_status("valid", candidate))
            return 0
        status = _write_atomic(args.output, candidate)
        print(_status(status, candidate))
        return 0
    except ContractError as exc:
        print(f"{exc.code} {exc.path}:{exc.line}", file=sys.stderr)
        return exc.exit_code
    except OSError:
        print("E_IO <runtime>:1", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
