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

from _review_git import ScopeRequest, capture_scope, compare_scope
from _review_record import (
    ReviewError,
    finish_report,
    load_json,
    validate_document,
    validate_record,
)

SCOPE_FILE = "scope.json"
EXIT_OK = 0
EXIT_INVALID_INPUT = 2


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
    _emit(
        {
            "result": "ok",
            "command": "scope",
            "artifact": result["packet"],
            "exit_code": EXIT_OK,
            "mode": result["mode"],
            "items": result["items"],
            "sources": result["sources"],
            "scope_sha256": result["scope_sha256"],
            "limitations": result["limitations"],
        }
    )
    return EXIT_OK


def _run_check(args: argparse.Namespace) -> int:
    repo = Path(args.repo)
    packet = Path(args.packet)
    output = Path(args.output)
    try:
        _require_new_output(repo, output)
    except ReviewError as error:
        return _fail(error)
    freshness: dict[str, Any] = {"status": "not_checked", "changed_paths": []}
    try:
        scope = _load_scope(packet)
        record = load_json(Path(args.record))
        validation = validate_record(packet, scope, record)
        freshness = compare_scope(repo, scope, packet)
    except ReviewError as error:
        validation = {"validation": "invalid", "problems": [error.problem()]}
    report = finish_report(validation, freshness)
    validate_document(report, "check_report")
    try:
        _write_new_file(output, report)
    except ReviewError as error:
        return _fail(error)
    _emit(
        {
            "result": report["validation"],
            "command": "check",
            "artifact": str(output),
            "exit_code": report["exit_code"],
            "validation": report["validation"],
            "coverage_status": report["coverage_status"],
            "freshness": report["freshness"]["status"],
        }
    )
    return report["exit_code"]


def _load_scope(packet: Path) -> dict[str, Any]:
    scope_path = packet / SCOPE_FILE
    if not scope_path.is_file():
        raise ReviewError("E_SCOPE_MISSING", f"{packet} does not contain {SCOPE_FILE}")
    return load_json(scope_path)


def _require_new_output(repo: Path, output: Path) -> None:
    target = Path(os.path.abspath(output))
    if target.is_relative_to(Path(os.path.realpath(repo))):
        raise ReviewError("E_OUTPUT", "the report output is inside the repository")
    for parent in [target, *target.parents]:
        if parent.is_symlink():
            raise ReviewError("E_OUTPUT", f"the output path uses the symlink {parent}")
    if os.path.lexists(target):
        raise ReviewError("E_OUTPUT", f"{target} already exists")


def _write_new_file(path: Path, value: Any) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ReviewError("E_OUTPUT", f"{path} already exists") from exc
    except OSError as exc:
        raise ReviewError("E_OUTPUT", f"cannot create {path}: {exc.strerror}") from exc
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
