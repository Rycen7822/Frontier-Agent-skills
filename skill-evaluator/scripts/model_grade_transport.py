"""Build and validate the blinded execution model-grader transport."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
from typing import Any, Callable


BLINDED_FIELDS = {
    "case_id", "repeat", "requirements", "captured_output",
    "artifacts", "observations",
}
UNCERTAINTY = {"none", "low", "medium", "high"}


def batch_identity(
    evaluation_id: str,
    case_id: str,
    grader_id: str,
) -> str:
    """Return the shared batch identity for one case and model grader."""
    values = (evaluation_id, case_id, grader_id)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("model grader batch identity fields are invalid")
    payload = json.dumps(
        {
            "case_id": case_id,
            "evaluation_id": evaluation_id,
            "grader_id": grader_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "mgb-" + sha256(payload).hexdigest()[:24]


def execution_result(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the sole task-execution result from a terminal receipt."""
    results = [
        result for result in receipt["host_protocol"]["results"]
        if result["envelope"]["request_kind"] == "execute_case"
    ]
    if len(results) != 1:
        raise ValueError("model grader batch member lacks one execution")
    return results[0]


def blinded_execution(
    entry: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Project an execution result onto the declared blinded fields."""
    return {
        "case_id": entry["case_id"],
        "repeat": entry["repeat"],
        "requirements": copy.deepcopy(
            entry["execute_case_payload"]["case"]["requirements"],
        ),
        "captured_output": {
            field: copy.deepcopy(result[field])
            for field in (
                "terminal_status", "treatment_error", "refusal", "timeout",
            )
        },
        "artifacts": copy.deepcopy(result["artifacts"]),
        "observations": [],
    }


def execution_item(
    blinded: dict[str, Any],
    *,
    grader_id: str,
    entry_id: str,
    read_artifact: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """Project one execution receipt into a blinded batch item."""
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
        "item_id": entry_id,
        "checks": [{"id": item["check_id"]} for item in requirements],
        "grader_view": {
            "captured_output": blinded["captured_output"],
            "host_assessment": assessment,
            "final_answer": evidence["final-answer"],
        },
    }


def execution_batch(
    items: list[dict[str, Any]],
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Bind multiple blinded execution items to one provider request."""
    item_ids = [
        item.get("item_id") for item in items if isinstance(item, dict)
    ]
    if (
        not isinstance(batch_id, str)
        or not batch_id
        or not items
        or len(item_ids) != len(items)
        or any(
            set(item) != {"item_id", "checks", "grader_view"}
            for item in items
        )
        or any(not isinstance(item_id, str) or not item_id for item_id in item_ids)
        or len(item_ids) != len(set(item_ids))
    ):
        raise ValueError("model grader batch items are invalid")
    return {"batch_id": batch_id, "items": items}


def normalize_judgment(
    output: Any,
    *,
    batch: dict[str, Any],
    requirements: list[dict[str, Any]],
    item_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate a batch judgment and normalize one bound item."""
    items = output.get("items") if isinstance(output, dict) else None
    expected_items = {
        item["item_id"]: [check["id"] for check in item["checks"]]
        for item in batch["items"]
    }
    observed_items = {
        item.get("item_id"): item
        for item in items or []
        if isinstance(item, dict)
    }
    if (
        not isinstance(output, dict) or not expected_items
        or set(output) != {"batch_id", "items"}
        or output["batch_id"] != batch["batch_id"]
        or not isinstance(items, list)
        or len(items) != len(expected_items)
        or set(observed_items) != set(expected_items)
        or any(set(item) != {"item_id", "checks"} for item in items)
    ):
        raise ValueError("model grader judgment differs from the bound batch")
    for observed_id, expected in expected_items.items():
        checks = observed_items[observed_id].get("checks")
        observed = [
            check.get("id") for check in checks if isinstance(check, dict)
        ] if isinstance(checks, list) else []
        if (
            observed != expected
            or len(observed) != len(set(observed))
            or any(
                set(check) != {"id", "pass", "notes", "uncertainty"}
                or not isinstance(check["pass"], bool)
                or not isinstance(check["notes"], str)
                or check["uncertainty"] not in UNCERTAINTY
                for check in checks or []
            )
        ):
            raise ValueError("model grader judgment differs from the bound batch")
    item = observed_items.get(item_id)
    if item is None:
        raise ValueError("model grader item is outside the bound batch")
    checks = item["checks"]
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
    item_position = items.index(item)
    pointers = {
        check["id"]: f"/items/{item_position}/checks/{index}/pass"
        for index, check in enumerate(checks)
    }
    return normalized, pointers
