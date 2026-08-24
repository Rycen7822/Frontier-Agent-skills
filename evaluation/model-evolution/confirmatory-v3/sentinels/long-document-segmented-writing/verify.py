#!/usr/bin/env python3
"""Deterministic checks for Long Document Segmented Writing."""

import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from verify_common import emit, terminal_checks  # noqa: E402


WHOLE_DRAFT_PATHS = frozenset({
    "fixtures/draft.md",
    "fixtures/run-a.md",
    "fixtures/release.md",
})
FINDING_FIELDS = ("claim", "source", "status", "source_fact")
EXPECTED_FINDINGS = frozenset({
    (
        "The run had zero retries",
        "run-a.md",
        "overbroad",
        "The run recorded zero request retries.",
    ),
    (
        "The run retried twice",
        "run-a.md",
        "contradicted",
        "The run recorded zero request retries.",
    ),
    (
        "It is release-ready",
        "release.md",
        "unsupported",
        "The available record neither supports nor rules out release readiness.",
    ),
})


def _is_whole_draft_review(workspace: dict) -> bool:
    initial = workspace.get("initial")
    if not isinstance(initial, list):
        return False
    paths = {
        item.get("path")
        for item in initial
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    return frozenset(path for path in paths if path.startswith("fixtures/")) == (
        WHOLE_DRAFT_PATHS
    )


def _whole_draft_checks(answer: str) -> dict[str, tuple[bool, str]]:
    try:
        payload = json.loads(answer)
    except json.JSONDecodeError:
        payload = None
    findings = payload.get("findings") if isinstance(payload, dict) else None
    observed = [
        tuple(item.get(field) for field in FINDING_FIELDS)
        for item in findings or []
        if isinstance(item, dict)
    ]
    passed = (
        isinstance(findings, list)
        and len(findings) == len(EXPECTED_FINDINGS)
        and frozenset(observed) == EXPECTED_FINDINGS
    )
    observation = (
        "the JSON findings bind both retry defects and the unsupported release claim"
        if passed
        else "the JSON findings differ from the three frozen claim/source facts"
    )
    return {
        "task-quality-check": (passed, observation),
        "task-process-check": (passed, observation),
    }


def main() -> int:
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    checks = terminal_checks(result)
    workspace_path = Path("workspace/workspace-evidence.json")
    answer_path = Path("workspace/final-answer.md")
    if workspace_path.is_file() and answer_path.is_file():
        workspace = json.loads(workspace_path.read_text(encoding="utf-8"))
        if _is_whole_draft_review(workspace):
            checks.update(
                _whole_draft_checks(answer_path.read_text(encoding="utf-8")),
            )
    return emit(
        "long-document-segmented-writing",
        checks,
        evidence_artifacts={
            "task-quality-check": "workspace/final-answer.md",
            "task-process-check": "workspace/final-answer.md",
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
