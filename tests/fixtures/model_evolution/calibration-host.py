#!/usr/bin/env python3
"""Deterministic semantic fake for model-calibration lifecycle tests."""

from hashlib import sha256
import json
from pathlib import Path
import sys


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _artifact(name: str, value: object) -> dict[str, str]:
    payload = _canonical(value)
    Path(name).write_bytes(payload)
    return {
        "path": f"workspace/{name}",
        "sha256": "sha256:" + sha256(payload).hexdigest(),
        "encoding": "utf-8",
    }


def _judgment(item: dict[str, object]) -> tuple[bool, str]:
    evidence = str(item["grader_view"].get("candidate_evidence", "")).lower()
    if any(marker in evidence for marker in (
        "not captured", "no readable", "no process trace", "cannot establish",
    )):
        return False, "high"
    if any(marker in evidence for marker in (
        "placeholder", "contradicts", "performed ad hoc", "unrelated workflow",
        "are absent", "is missing", "only part", "completion and cleanup",
        "=not_run",
    )):
        return False, "none"
    return True, "none"


def main() -> int:
    request = json.loads(sys.stdin.read())
    payload = request["payload"]
    batch = payload["blinded_input"]
    items = []
    for item in batch["items"]:
        passed, uncertainty = _judgment(item)
        items.append({
            "item_id": item["item_id"],
            "checks": [
                {
                    "id": check["id"],
                    "pass": passed,
                    "notes": "semantic calibration fixture",
                    "uncertainty": uncertainty,
                }
                for check in item["checks"]
            ],
        })
    grade = _artifact("model-grade.json", {
        "batch_id": batch["batch_id"],
        "items": items,
    })
    result = {
        "record_type": "skill-evaluator-host-result/1",
        "terminal": True,
        "terminal_status": "completed",
        "envelope": request["envelope"],
        "request_hash": request["request_hash"],
        "treatment_error": None,
        "refusal": False,
        "timeout": False,
        "protocol_error": None,
        "principals": [],
        "handoffs": [],
        "actions": [],
        "artifacts": [grade],
        "state": [],
        "cleanup": {"status": "clean"},
        "usage": {
            "pricing_identity": "fixture-pricing",
            "host_safety_review": {
                "capture_status": "missing",
                "host_safety_review_count": 0,
                "host_safety_review_latency_ms": 0,
            },
            "records": [{
                "principal_id": "fixture-grader",
                "turn_id": None,
                "phase": "model_grade",
                "call_id": "fixture-grade",
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "queue_ms": 0,
                "runtime_ms": 1,
                "tool_calls": 0,
                "retries": 0,
                "rework": 0,
                "network_calls": 0,
                "residue_count": 0,
                "requested_effort": 1,
                "effective_effort": 1,
            }],
        },
        "context": {
            "status": "captured",
            "bytes": 0,
            "tokens": 0,
            "controlled_bytes": 0,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": 0,
            "components": [],
        },
        "assertions": [{
            "claim": "semantic calibration fixture completed",
            "artifact": grade,
            "locally_verifiable": True,
        }],
    }
    print(_canonical(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
