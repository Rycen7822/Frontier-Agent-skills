#!/usr/bin/env python3
"""Deterministic envelope and literal-contract checks for Writing Plans."""

import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from verify_common import emit, terminal_checks  # noqa: E402


CASE_PATHS = {
    "protected-description": frozenset({"fixtures/agents/openai.yaml"}),
    "explicit-handoff": frozenset({"fixtures/release-status.md"}),
    "resume-preflight": frozenset({"fixtures/resume-state.md", "fixtures/docs/config.md"}),
}
DESCRIPTION = (
    "description: Use after software decisions and diagnosis are settled to write "
    "source-bound software implementation Handoffs and durable multi-session Programs."
)
DESCRIPTION_VALUE = DESCRIPTION.removeprefix("description: ")


def _case_id(workspace: dict) -> str | None:
    initial = workspace.get("initial")
    if not isinstance(initial, list):
        return None
    paths = {
        item.get("path")
        for item in initial
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    fixture_paths = frozenset(path for path in paths if path.startswith("fixtures/"))
    return next(
        (case_id for case_id, expected in CASE_PATHS.items() if fixture_paths == expected),
        None,
    )


def _paired_checks(passed: bool, label: str) -> dict[str, tuple[bool, str]]:
    observation = (
        f"the final plan satisfies the exact {label} contract"
        if passed
        else f"the exact {label} contract is incomplete or contradictory"
    )
    return {
        "task-quality-check": (passed, observation),
        "task-process-check": (passed, observation),
    }


def _fixed_case_checks(case_id: str, answer: str) -> dict[str, tuple[bool, str]]:
    lower = answer.lower()
    if case_id == "protected-description":
        required = (
            "fixtures/agents/openai.yaml",
            "8.2.0",
            "8.2.1",
        )
        joined_literals = re.sub(r"([\"'])\s*\n\s*\1", "", answer)
        description_proof = DESCRIPTION in joined_literals or (
            'line.startswith("description:")' in answer
            and "descriptions ==" in answer
            and DESCRIPTION_VALUE in answer
        )
        exact_proof = (
            ("python" in lower and "assert" in answer and ".read_text(" in answer)
            or ("sed -n '1p'" in answer and "sed -n '2p'" in answer)
        )
        return _paired_checks(
            all(term in answer for term in required)
            and "version" in lower
            and description_proof
            and exact_proof,
            "version-and-description",
        )

    if case_id == "explicit-handoff":
        required = (
            "signed implementation commit",
            "pythondontwritebytecode=1 python -m unittest tests.test_release",
            "release engineering",
            "immutable",
            "artifact",
        )
        passing = "passing" in lower or "marked pass" in lower
        remaining_state = (
            "pending" in lower
            or "remains" in lower
            or ("verification only" in lower and "no source-changing work" in lower)
        )
        authority = "publish" in lower or "publication" in lower
        verification = "verification" in lower or bool(re.search(r"\bverify\b", lower))
        return _paired_checks(
            all(term in lower for term in required)
            and passing
            and remaining_state
            and authority
            and verification,
            "release-handoff",
        )

    if case_id == "resume-preflight":
        required = (
            "abc123",
            "completed",
            "pending",
            "fixtures/docs/config.md",
            "integration check",
            "attestation",
            "combined preflight",
        )
        rows = all(re.search(rf"\b{row}\b", lower) for row in ("state", "resume", "slice", "proof"))
        next_action = "replac" in lower or "edit" in lower
        return _paired_checks(
            all(term in lower for term in required) and rows and next_action,
            "resume documentation handoff",
        )

    raise ValueError(f"unsupported deterministic Writing Plans case: {case_id}")


def main() -> int:
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    checks = terminal_checks(result)
    workspace_path = Path("workspace/workspace-evidence.json")
    answer_path = Path("workspace/final-answer.md")
    if workspace_path.is_file() and answer_path.is_file():
        workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
        case_id = _case_id(workspace)
        if case_id is not None:
            checks.update(
                _fixed_case_checks(case_id, answer_path.read_text(encoding="utf-8")),
            )
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
