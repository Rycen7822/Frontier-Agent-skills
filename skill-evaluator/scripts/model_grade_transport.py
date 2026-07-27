"""Build and validate the blinded execution model-grader transport."""

from __future__ import annotations

import json
from typing import Any, Callable


BLINDED_FIELDS = {
    "case_id", "repeat", "requirements", "captured_output",
    "artifacts", "observations",
}
UNCERTAINTY = {"none", "low", "medium", "high"}


def execution_batch(
    blinded: dict[str, Any],
    *,
    grader_id: str,
    entry_id: str,
    read_artifact: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """Project one execution receipt into the frozen batch prompt shape."""
    if not isinstance(blinded, dict) or set(blinded) != BLINDED_FIELDS:
        raise ValueError("model blinded projection fields are invalid")
    requirements = [
        item for item in blinded["requirements"]
        if isinstance(item, dict) and item.get("grader_id") == grader_id
    ]
    if not requirements:
        raise ValueError("model grader has no selected requirements")
    evidence = {}
    for label in ("host-observation", "final-answer"):
        matches = [
            item for item in blinded["artifacts"]
            if (
                isinstance(item, dict)
                and item.get("path", "").startswith(f"workspace/{label}-")
                and item.get("encoding") == "utf-8"
            )
        ]
        if len(matches) != 1:
            raise ValueError(f"model grader {label} evidence is invalid")
        evidence[label] = read_artifact(matches[0])
    try:
        assessment = json.loads(evidence["host-observation"])
    except json.JSONDecodeError as exc:
        raise ValueError("model grader host assessment is invalid JSON") from exc
    if not isinstance(assessment, dict):
        raise ValueError("model grader host assessment is not an object")
    return {
        "batch_id": entry_id,
        "items": [{
            "item_id": entry_id,
            "checks": [{"id": item["check_id"]} for item in requirements],
            "grader_view": {
                "captured_output": blinded["captured_output"],
                "host_assessment": assessment,
                "final_answer": evidence["final-answer"],
            },
        }],
    }


def normalize_judgment(
    output: Any,
    *,
    batch: dict[str, Any],
    requirements: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate a one-item judgment and return v1 grader transport + locators."""
    items = output.get("items") if isinstance(output, dict) else None
    item = items[0] if isinstance(items, list) and len(items) == 1 else None
    checks = item.get("checks") if isinstance(item, dict) else None
    expected = [check["id"] for check in batch["items"][0]["checks"]]
    observed = [
        check.get("id") for check in checks if isinstance(check, dict)
    ] if isinstance(checks, list) else []
    if (
        not isinstance(output, dict) or not expected
        or set(output) != {"batch_id", "items"}
        or output["batch_id"] != batch["batch_id"]
        or item is None or set(item) != {"item_id", "checks"}
        or item["item_id"] != batch["items"][0]["item_id"]
        or observed != expected or len(observed) != len(set(observed))
        or any(
            set(check) != {"id", "pass", "notes", "uncertainty"}
            or not isinstance(check["pass"], bool)
            or not isinstance(check["notes"], str)
            or check["uncertainty"] not in UNCERTAINTY
            for check in checks or []
        )
    ):
        raise ValueError("model grader judgment differs from the bound batch")
    required = {
        item["check_id"] for item in requirements if item["required"]
    }
    results = {check["id"]: check["pass"] for check in checks}
    score = (sum(results.values()) * 100 + len(checks) // 2) // len(checks)
    normalized = {
        "overall_pass": all(
            check["pass"] for check in checks if check["id"] in required
        ),
        "score": score,
        "checks": [{
            "check_id": check["id"],
            "pass": check["pass"],
            "evidence": [],
            "notes": check["notes"],
            "uncertainty": check["uncertainty"],
        } for check in checks],
        "missing_evidence": [],
        "grader_failure": False,
        "grader_failure_reason": None,
    }
    pointers = {
        check["id"]: f"/items/0/checks/{index}/pass"
        for index, check in enumerate(checks)
    }
    return normalized, pointers
