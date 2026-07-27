#!/usr/bin/env python3
"""Thin verifier entry point for the tracked deterministic grader owner."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from evaluation.controller import host


def main() -> int:
    try:
        path = Path("result.json")
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                "runner-bound result.json is missing or not regular"
            )
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("runner-bound result.json is not an object")
        output = host.deterministic_grade(
            result,
            host.selected_checks(sys.argv[1:]),
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
