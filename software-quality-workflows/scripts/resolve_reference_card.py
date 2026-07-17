#!/usr/bin/env python3
"""Resolve one SQW route through the canonical decision selector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_reference_cards import strict_json_bytes
from route_workflow import ROOT, RouteError, assess


def resolve(raw: Any, *, root: Path = ROOT) -> dict[str, Any]:
    """Return the exact route result; selection logic remains owned by assess()."""
    return assess(raw, root=root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", default="-")
    args = parser.parse_args(argv)
    try:
        data = sys.stdin.buffer.read(2 * 1024 * 1024 + 1) if args.request == "-" else Path(args.request).read_bytes()
        result = resolve(strict_json_bytes(data, source=args.request))
    except (OSError, ValueError, RouteError) as exc:
        code = exc.code if isinstance(exc, RouteError) else "ROUTE_INPUT_INVALID"
        result = {
            "schema_version": "2.0",
            "route_action": "blocked",
            "route_owner": "software-quality-workflows",
            "selected_decision_id": None,
            "primary_card": None,
            "required_artifact_ids": [],
            "reason_codes": [code],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result["route_action"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
