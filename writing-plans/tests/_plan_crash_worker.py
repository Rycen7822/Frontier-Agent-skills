#!/usr/bin/env python3
"""Test-owned dispatcher for real Writing Plans SIGKILL checkpoints."""

from __future__ import annotations

from pathlib import Path
import sys

from test_plan_state import _program_apply_worker, _program_init_worker


def main() -> int:
    if len(sys.argv) == 6 and sys.argv[1] == "--program-init-worker":
        _program_init_worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]))
        return 0
    if len(sys.argv) == 6 and sys.argv[1] == "--program-apply-worker":
        _program_apply_worker(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], Path(sys.argv[5]))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
