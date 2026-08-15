#!/usr/bin/env python3
"""Deterministic envelope and fully mechanical case checks for Writing Plans."""

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from verify_common import emit, terminal_checks  # noqa: E402


SOURCE_BOUND_PATHS = (
    "fixtures/src/config.py",
    "fixtures/src/client.py",
    "fixtures/tests/test_client.py",
)


def _source_bound_case(workspace: dict) -> bool:
    initial = workspace.get("initial")
    if not isinstance(initial, list):
        return False
    paths = {
        item.get("path")
        for item in initial
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    return {path for path in paths if path.startswith("fixtures/")} == set(
        SOURCE_BOUND_PATHS,
    )


def _source_bound_checks(answer: str) -> dict[str, tuple[bool, str]]:
    config_literal = answer.find("request_timeout_ms = 30000")
    config_start = answer.rfind(SOURCE_BOUND_PATHS[0], 0, config_literal)
    client_literal = answer.find(
        "from .config import request_timeout_ms", config_literal,
    )
    client_start = answer.rfind(SOURCE_BOUND_PATHS[1], 0, client_literal)
    test_start = answer.find(SOURCE_BOUND_PATHS[2], client_literal)
    ordered = (
        min(
            config_literal, config_start, client_literal, client_start, test_start,
        ) >= 0
        and config_start < client_start < test_start
    )
    config = answer[config_start:client_start] if ordered else ""
    client = answer[client_start:test_start] if ordered else ""
    test = answer[test_start:] if ordered else ""
    quality = bool(
        ordered
        and "timeout_ms = 30000" in config
        and "request_timeout_ms = 30000" in config
        and "return timeout_ms" not in config
        and "return request_timeout_ms" not in config
        and "from .config import timeout_ms" in client
        and "from .config import request_timeout_ms" in client
        and "return timeout_ms" in client
        and "return request_timeout_ms" in client
        and "request_timeout_ms = 30000" not in client
        and (
            "request() == 30000" in test
            or "request()` still returns `30000" in test
        )
        and any(
            marker in (client + test).lower()
            for marker in (
                "do not edit",
                "make no edit",
                "leave `fixtures/tests/test_client.py` unchanged",
                "preserve its existing behavior",
            )
        )
    )

    lower = answer.lower()
    root_bound = any(
        marker in lower
        for marker in (
            "starting cwd: `<workspace>`",
            "from `<workspace>`",
            "run commands from `<workspace>`",
        )
    )
    fixtures_bound = any(
        marker in lower
        for marker in (
            "starting cwd: `<workspace>/fixtures`",
            "from `<workspace>/fixtures`",
            "run commands from `<workspace>/fixtures`",
        )
    )
    pytest_lines = [
        line for line in answer.splitlines() if "python -m pytest" in line
    ]
    root_pytest = any(
        "PYTHONPATH=fixtures" in line
        and "-p no:cacheprovider" in line
        and "fixtures/tests/test_client.py" in line
        for line in pytest_lines
    )
    fixtures_pytest = any(
        "PYTHONPATH=" not in line
        and "-p no:cacheprovider" in line
        and "fixtures/tests/test_client.py" not in line
        and "tests/test_client.py" in line
        for line in pytest_lines
    )
    old_absent = re.search(
        r"assert\s+['\"]timeout_ms['\"]\s+not\s+in\s+identifiers", answer,
    )
    new_present = re.search(
        r"assert\s+['\"]request_timeout_ms['\"]\s+in\s+identifiers", answer,
    )
    identifier_aware = bool(
        old_absent
        and new_present
        and (
            ("ast.parse" in answer and "ast.walk" in answer)
            or (
                "tokenize." in answer
                and ("tokenize.NAME" in answer or ".isidentifier()" in answer)
            )
        )
    )
    residual_start = lower.find("identifier-aware")
    pytest_start = min(
        (
            answer.find(line, residual_start)
            for line in pytest_lines
            if answer.find(line, residual_start) >= 0
        ),
        default=-1,
    )
    residual = (
        answer[residual_start:pytest_start]
        if residual_start >= 0 and pytest_start > residual_start
        else ""
    )
    root_paths = all(
        f'"{path}"' in residual or f"'{path}'" in residual
        for path in SOURCE_BOUND_PATHS
    )
    fixture_paths = all(
        f'"{path}"' in residual or f"'{path}'" in residual
        for path in ("src/config.py", "src/client.py", "tests/test_client.py")
    )
    process = len(pytest_lines) == 1 and identifier_aware and (
        (root_bound and root_pytest and root_paths)
        or (fixtures_bound and fixtures_pytest and fixture_paths)
    )
    return {
        "task-quality-check": (
            quality,
            "ordered config, consumer, and test bindings preserve the exact rename behavior"
            if quality
            else "the exact source-bound rename ownership or behavior is incomplete",
        ),
        "task-process-check": (
            process,
            "cwd-bound no-cache pytest and identifier-aware residual checks are executable"
            if process
            else "the cwd, no-cache pytest, or identifier-aware residual check is incomplete",
        ),
    }


def main() -> int:
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    checks = terminal_checks(result)
    workspace_path = Path("workspace/workspace-evidence.json")
    answer_path = Path("workspace/final-answer.md")
    if workspace_path.is_file() and answer_path.is_file():
        workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
        if _source_bound_case(workspace):
            checks.update(_source_bound_checks(answer_path.read_text(encoding="utf-8")))
    return emit(
        "writing-plans",
        checks,
        evidence_artifacts={
            "task-quality-check": "workspace/final-answer.md",
            "task-process-check": "workspace/final-answer.md",
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
