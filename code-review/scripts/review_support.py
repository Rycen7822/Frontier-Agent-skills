#!/usr/bin/env python3
"""Capture review scope packets and check machine-readable review records.

This is the only public entry point of the review helper. Scope capture,
validation, freshness, and reporting stay in the two internal modules.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from _review_git import (
    ScopeRequest,
    capture_scope,
    compare_scope,
    repository_root,
    require_new_output,
)
from _review_record import (
    SCOPE_FILE,
    ReviewError,
    encode_document,
    finish_report,
    load_json,
    validate_document,
    validate_record,
)

EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_PARTIAL = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review_support.py",
        description="Capture a review scope packet or check a review record.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scope = subparsers.add_parser("scope", help="capture the requested scope into a packet")
    scope.add_argument("--repo", required=True, help="target repository root")
    scope.add_argument(
        "--mode", required=True, choices=("commit", "range", "workspace", "snapshot")
    )
    scope.add_argument(
        "--path",
        dest="paths",
        action="append",
        required=True,
        help="repository-relative literal path; repeat for more paths",
    )
    scope.add_argument(
        "--context-path",
        dest="context_paths",
        action="append",
        default=[],
        help="repository-relative file captured as extra source evidence",
    )
    scope.add_argument("--base")
    scope.add_argument("--head")
    scope.add_argument("--commit")
    scope.add_argument("--revision")
    scope.add_argument("--output", required=True, help="new packet directory")

    check = subparsers.add_parser("check", help="check a record against its packet")
    check.add_argument("--repo", required=True, help="target repository root")
    check.add_argument("--packet", required=True, help="existing packet directory")
    check.add_argument("--record", required=True, help="review record JSON file")
    check.add_argument("--output", required=True, help="new check report file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "scope":
        return _run_scope(args)
    return _run_check(args)


def _run_scope(args: argparse.Namespace) -> int:
    request = ScopeRequest(
        mode=args.mode,
        paths=tuple(args.paths),
        context_paths=tuple(args.context_paths),
        base=args.base,
        head=args.head,
        commit=args.commit,
        revision=args.revision,
    )
    try:
        result = capture_scope(Path(args.repo), request, Path(args.output))
    except ReviewError as error:
        return _fail(error)
    exit_code = EXIT_PARTIAL if result["partial"] else EXIT_OK
    _emit(
        {
            "result": "ok",
            "command": "scope",
            "artifact": result["packet"],
            "exit_code": exit_code,
            "mode": result["mode"],
            "items": result["items"],
            "sources": result["sources"],
            "scope_sha256": result["scope_sha256"],
            "limitations": result["limitations"],
        }
    )
    return exit_code


def _run_check(args: argparse.Namespace) -> int:
    packet = Path(args.packet)
    try:
        root = repository_root(Path(args.repo))
        target = require_new_output(root, Path(args.output), "report output")
    except ReviewError as error:
        return _fail(error)
    validation, freshness = _check_inputs(root, packet, Path(args.record))
    try:
        report = finish_report(validation, freshness)
        validate_document(report, "check_report")
        data = encode_document(report, "E_REPORT_LIMIT")
    except ReviewError as error:
        return _fail(error)
    try:
        _write_new_file(target, data)
    except ReviewError as error:
        return _fail(error)
    _emit(
        {
            "result": report["validation"],
            "command": "check",
            "artifact": str(target),
            "exit_code": report["exit_code"],
            "validation": report["validation"],
            "coverage_status": report["coverage_status"],
            "freshness": report["freshness"]["status"],
        }
    )
    return report["exit_code"]


def _check_inputs(
    root: Path, packet: Path, record_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the record, then compare freshness, keeping every failure typed."""
    freshness: dict[str, Any] = {"status": "not_checked", "changed_paths": []}
    try:
        scope = _load_scope(packet)
        record = load_json(record_path)
        validation = validate_record(packet, scope, record)
    except ReviewError as error:
        return {"validation": "invalid", "problems": [error.problem()]}, freshness
    try:
        freshness = compare_scope(root, scope)
    except ReviewError as error:
        return {"validation": "invalid", "problems": [error.problem()]}, freshness
    return validation, freshness


def _load_scope(packet: Path) -> dict[str, Any]:
    scope_path = packet / SCOPE_FILE
    if not scope_path.is_file():
        raise ReviewError("E_SCOPE_MISSING", f"{packet} does not contain {SCOPE_FILE}")
    return load_json(scope_path)


def _write_new_file(path: Path, data: bytes) -> None:
    """Create one new file exclusively; a failed write never yields an artifact."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ReviewError("E_OUTPUT", f"{path} already exists") from exc
    except OSError as exc:
        raise ReviewError("E_OUTPUT", f"cannot create {path}: {exc.strerror}") from exc
    try:
        _write_all(descriptor, data)
    except OSError as exc:
        raise ReviewError("E_OUTPUT", f"cannot write {path}: {exc.strerror}") from exc


def _write_all(descriptor: int, data: bytes) -> None:
    """Write the whole payload to a descriptor this call owns."""
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _fail(error: ReviewError) -> int:
    _emit(
        {
            "result": "error",
            "artifact": None,
            "exit_code": EXIT_INVALID_INPUT,
            "code": error.code,
            "message": error.message,
            "pointer": error.pointer,
        }
    )
    return EXIT_INVALID_INPUT


if __name__ == "__main__":
    sys.exit(main())
