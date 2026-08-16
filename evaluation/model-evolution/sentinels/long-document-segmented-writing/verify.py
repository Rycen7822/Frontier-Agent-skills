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
    lower = answer.lower()
    zero_overreach = all(term in lower for term in (
        "zero retries",
        "zero request retries",
    )) and any(term in lower for term in (
        "broader",
        "broadens",
        "overbroad",
        "drops",
        "omits",
        "qualifier",
        "generalized",
    ))
    retry_conflict = (
        "retried twice" in lower
        and "run-a.md" in lower
        and any(term in lower for term in (
            "conflict",
            "contradict",
            "false",
            "cannot support",
            "not two",
            "mutually inconsistent",
        ))
    )
    release_unsupported = (
        ("release-ready" in lower or "release readiness" in lower)
        and "release.md" in lower
        and "no release decision" in lower
        and any(term in lower for term in (
            "unsupported",
            "not supported",
            "not established",
            "cannot support",
            "conflict",
            "contradict",
            "opposite",
        ))
    )
    source_binding = (
        "run-a.md" in lower
        and "release.md" in lower
        and ("binding" in lower or "citation" in lower)
    )
    passed = zero_overreach and retry_conflict and release_unsupported and source_binding
    observation = (
        "the review identifies both retry defects and the unsupported release binding"
        if passed
        else "the review misses a retry defect, release contradiction, or source binding"
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
