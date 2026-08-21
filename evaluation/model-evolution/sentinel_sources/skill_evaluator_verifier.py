#!/usr/bin/env python3
"""Deterministic envelope and fixed-contract checks for Skill Evaluator."""

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from verify_common import emit, terminal_checks  # noqa: E402


CASE_PATHS = {
    "transition-vs-revision": frozenset({"fixtures/control-matrix.md"}),
    "protected-no-reviewer": frozenset({"fixtures/invalid-record.json"}),
}


def _case_id(workspace: dict) -> str | None:
    initial = workspace.get("initial")
    if not isinstance(initial, list):
        return None
    paths = frozenset(
        item.get("path")
        for item in initial
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and item["path"].startswith("fixtures/")
    )
    return next(
        (case_id for case_id, expected in CASE_PATHS.items() if paths == expected),
        None,
    )


def _paired(passed: bool, label: str) -> dict[str, tuple[bool, str]]:
    state = "satisfies" if passed else "misses"
    observation = f"the final artifact {state} the {label} contract"
    return {
        "task-quality-check": (passed, observation),
        "task-process-check": (passed, observation),
    }


def _fixed_checks(case_id: str, answer: str) -> dict[str, tuple[bool, str]]:
    if case_id == "transition-vs-revision":
        lower = answer.lower().replace("‑", "-").replace("–", "-")
        comparison_a = bool(
            re.search(r"(?:comparison\s+)?a\s*(?:is|:)[^\n]{0,120}model[- ]transition", lower)
        )
        comparison_b = bool(
            re.search(r"(?:comparison\s+)?b\s*(?:is|:)[^\n]{0,120}skill[- ]revision", lower)
        )
        controls = all(term in lower for term in ("host", "tasks", "grader", "policy"))
        return _paired(comparison_a and comparison_b and controls, "comparison-classification")

    if case_id == "protected-no-reviewer":
        payload = answer.strip()
        if payload.startswith("```") and payload.endswith("```"):
            payload = payload.split("\n", 1)[-1].rsplit("\n", 1)[0]
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            value = None
        operation = value[0] if isinstance(value, list) and len(value) == 1 else value
        return _paired(
            operation == {"op": "replace", "path": "/schema_version", "value": 1},
            "single-operation JSON Patch",
        )

    raise ValueError(f"unsupported deterministic Skill Evaluator case: {case_id}")


def main() -> int:
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    checks = terminal_checks(result)
    workspace_path = Path("workspace/workspace-evidence.json")
    answer_path = Path("workspace/final-answer.md")
    if workspace_path.is_file() and answer_path.is_file():
        case_id = _case_id(json.loads(workspace_path.read_text(encoding="utf-8")))
        if case_id is not None:
            checks.update(_fixed_checks(case_id, answer_path.read_text(encoding="utf-8")))
    return emit(
        "skill-evaluator",
        checks,
        evidence_artifacts={
            "task-quality-check": "workspace/final-answer.md",
            "task-process-check": "workspace/final-answer.md",
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
