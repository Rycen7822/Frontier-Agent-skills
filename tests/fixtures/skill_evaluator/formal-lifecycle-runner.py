#!/usr/bin/env python3
"""Deterministic compiled-plan runner with one controlled process exit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--entry-id", required=True)
    parser.add_argument("--resume", action="store_true")
    arguments = parser.parse_args()
    control_path = Path(os.environ["FORMAL_LIFECYCLE_CONTROL"])
    control = json.loads(control_path.read_text())
    rows = (
        [
            json.loads(line)
            for line in arguments.index.read_text().splitlines()
        ]
        if arguments.index.is_file()
        else []
    )
    closed = len({row["entry_id"] for row in rows})
    if (
        control["stop_after"] < control["total"]
        and closed == control["stop_after"]
        and control["empty_exits"] < 2
    ):
        control["empty_exits"] += 1
        control_path.write_bytes(canonical(control) + b"\n")
        return 3
    if any(row["entry_id"] == arguments.entry_id for row in rows):
        return 0
    plan = json.loads(arguments.plan.read_text())
    entry = next(
        item for item in plan["entries"]
        if item["entry_id"] == arguments.entry_id
    )
    receipt = (
        arguments.index.parent
        / f"entries/{arguments.entry_id}/attempt-0001/receipt.json"
    )
    receipt.parent.mkdir(parents=True)
    value = {
        "run": {
            "entry_id": arguments.entry_id,
            "plan_hash": plan["plan_hash"],
            "attempt": 1,
            "error": None,
            "terminal": "completed",
            "valid": True,
        },
    }
    value["receipt_hash"] = (
        "sha256:" + hashlib.sha256(canonical(value)).hexdigest()
    )
    receipt.write_bytes(canonical(value) + b"\n")
    row = {
        "entry_id": arguments.entry_id,
        "attempt": 1,
        "receipt": {
            "path": receipt.relative_to(arguments.index.parent).as_posix(),
            "sha256": (
                "sha256:"
                + hashlib.sha256(receipt.read_bytes()).hexdigest()
            ),
        },
    }
    arguments.index.parent.mkdir(parents=True, exist_ok=True)
    with arguments.index.open("ab") as output:
        output.write(canonical(row) + b"\n")
    return (
        3
        if entry["entry_ordinal"] == control["stop_after"] == control["total"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
