#!/usr/bin/env python3
"""Deterministic terminal-envelope verifier for the confirmatory SE suite."""

import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

from verify_common import emit, terminal_checks  # noqa: E402


def main() -> int:
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    return emit("skill-evaluator", terminal_checks(result))


if __name__ == "__main__":
    raise SystemExit(main())
