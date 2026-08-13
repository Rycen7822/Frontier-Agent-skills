#!/usr/bin/env python3
"""Build or verify the bounded four-Skill model-evolution sentinel corpus."""

from __future__ import annotations

import argparse
import json
import sys

sys.dont_write_bytecode = True

from _model_evolution_sentinel_builder import (  # noqa: E402
    check,
    write,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        paths = write()
        print(json.dumps({"ok": True, "files": len(paths)}, sort_keys=True))
    else:
        check()
        print(json.dumps({"ok": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
