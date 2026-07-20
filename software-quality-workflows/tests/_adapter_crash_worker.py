#!/usr/bin/env python3
"""Test-owned dispatcher for real SQW adapter SIGKILL checkpoints."""

from __future__ import annotations

from pathlib import Path
import sys

from test_workflow_runtime import (
    _bootstrap_worker,
    _complete_materialized_worker,
    _complete_worker,
    _event_worker,
    _render_worker,
    _resume_outcome_worker,
    _resume_worker,
)


def main() -> int:
    if len(sys.argv) == 6 and sys.argv[1] == "--bootstrap-worker":
        _bootstrap_worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]))
        return 0
    if len(sys.argv) == 6 and sys.argv[1] == "--resume-outcome-worker":
        _resume_outcome_worker(Path(sys.argv[2]), sys.argv[3], sys.argv[4], Path(sys.argv[5]))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "--resume-worker":
        _resume_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "--complete-worker":
        _complete_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "--complete-materialized-worker":
        _complete_materialized_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
        return 0
    if len(sys.argv) == 5 and sys.argv[1] == "--render-worker":
        _render_worker(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
        return 0
    if len(sys.argv) == 7 and sys.argv[1] == "--event-worker":
        _event_worker(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]), sys.argv[5], Path(sys.argv[6]))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
