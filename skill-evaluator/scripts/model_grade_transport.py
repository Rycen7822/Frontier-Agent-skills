"""Build and validate the blinded execution model-grader transport."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
import re
from typing import Any, Callable


BLINDED_FIELDS = {
    "case_id", "repeat", "requirements", "captured_output",
    "artifacts", "observations",
}
UNCERTAINTY = {"none", "low", "medium", "high"}
CONTEXT_FIELDS = {
    "controlled_bytes": "controlled_bytes",
    "controlled_core_bytes": "controlled_core_bytes",
    "total_bytes": "bytes",
    "unique_reference_bytes": "unique_reference_bytes",
}
PATH_FIELDS = (
    "allowed_change_paths",
    "changed_paths",
    "expected_change_paths",
    "protected_paths",
)


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


def _task_evidence(entry: dict[str, Any]) -> dict[str, str]:
    """Return the user request bound into the frozen execution payload."""
    payload = entry.get("execute_case_payload")
    turns = payload.get("turns") if isinstance(payload, dict) else None
    if not isinstance(turns, list):
        raise ValueError("model grader execution turns are invalid")
    messages = []
    for turn in turns:
        item = turn.get("input") if isinstance(turn, dict) else None
        if not isinstance(item, dict) or item.get("kind") != "user_message":
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("model grader user request is invalid")
        messages.append(content)
    if not messages:
        raise ValueError("model grader user request is missing")
    return {"request_text": "\n\n".join(messages)}


def _deterministic_claims(result: dict[str, Any]) -> list[str]:
    """Return locally verified claims bound to declared result artifacts."""
    artifacts = result.get("artifacts")
    assertions = result.get("assertions")
    if not isinstance(artifacts, list) or not isinstance(assertions, list):
        raise ValueError("model grader deterministic evidence is invalid")
    claims = []
    for assertion in assertions:
        if (
            not isinstance(assertion, dict)
            or assertion.get("locally_verifiable") is not True
        ):
            continue
        claim = assertion.get("claim")
        if (
            not isinstance(claim, str)
            or not claim
            or assertion.get("artifact") not in artifacts
        ):
            raise ValueError("model grader deterministic claim is invalid")
        claims.append(claim)
    if not claims:
        raise ValueError("model grader deterministic claims are missing")
    return sorted(set(claims))


def _context_evidence(result: dict[str, Any]) -> dict[str, int]:
    """Return bounded context totals without exposing captured content."""
    context = result.get("context")
    if not isinstance(context, dict):
        raise ValueError("model grader context evidence is invalid")
    summary = {}
    for output_name, source_name in CONTEXT_FIELDS.items():
        value = context.get(source_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("model grader context total is invalid")
        summary[output_name] = value
    components = context.get("components")
    if not isinstance(components, list):
        raise ValueError("model grader context components are invalid")
    counts = {"body": 0, "reference": 0}
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("model grader context component is invalid")
        kind = component.get("kind")
        if kind in counts:
            occurrence = component.get("occurrence", 1)
            if (
                isinstance(occurrence, bool)
                or not isinstance(occurrence, int)
                or occurrence < 1
            ):
                raise ValueError("model grader context occurrence is invalid")
            counts[kind] += occurrence
    summary["body_load_count"] = counts["body"]
    summary["reference_load_count"] = counts["reference"]
    return dict(sorted(summary.items()))


def _grader_observation(
    entry: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build the typed evidence visible to the model grader."""
    return {
        "context_evidence": _context_evidence(result),
        "deterministic_claims": _deterministic_claims(result),
        "task_evidence": _task_evidence(entry),
    }


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
        "observations": [_grader_observation(entry, result)],
    }


def _relative_evidence_paths(assessment: dict[str, Any]) -> list[str]:
    """Validate and collect fixture-relative paths from host evidence."""
    paths = set()
    for field in PATH_FIELDS:
        values = assessment.get(field, [])
        if not isinstance(values, list):
            raise ValueError(f"model grader {field} is invalid")
        for value in values:
            if (
                not isinstance(value, str)
                or not value
                or value.startswith("/")
                or "\\" in value
                or re.match(r"^[A-Za-z]:[\\/]", value)
                or any(part in {"", ".", ".."} for part in value.split("/"))
            ):
                raise ValueError(f"model grader {field} path is invalid")
            paths.add(value)
    return sorted(paths, key=len, reverse=True)


def _redact_workspace_paths(
    final_answer: str,
    assessment: dict[str, Any],
) -> str:
    """Replace bound absolute paths with their relative evidence paths."""
    if not isinstance(final_answer, str):
        raise ValueError("model grader final answer is invalid")
    redacted = final_answer
    for path in _relative_evidence_paths(assessment):
        angle_path = re.compile(
            rf"<[^>\n]*/{re.escape(path)}(?P<line>:\d+)?>",
        )
        redacted = angle_path.sub(
            lambda match: f"<{path}{match.group('line') or ''}>",
            redacted,
        )
        plain_path = re.compile(
            rf"(?<![:A-Za-z0-9])(?:[A-Za-z]:[\\/]|/)"
            rf"[^\s`'\"<>()]*{re.escape(path)}(?P<line>:\d+)?",
        )
        redacted = plain_path.sub(
            lambda match: f"{path}{match.group('line') or ''}",
            redacted,
        )
    if re.search(
        r"(?<![:A-Za-z0-9])(?:[A-Za-z]:[\\/]|/)"
        r"(?:home|private|tmp|opt|Users|workspace|workspaces)[\\/]",
        redacted,
    ):
        raise ValueError("model grader final answer exposes an absolute path")
    return redacted


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
    observations = blinded["observations"]
    if (
        not isinstance(observations, list)
        or len(observations) != 1
        or not isinstance(observations[0], dict)
        or set(observations[0]) != {
            "context_evidence",
            "deterministic_claims",
            "task_evidence",
        }
    ):
        raise ValueError("model grader typed evidence is invalid")
    return {
        "item_id": entry_id,
        "checks": [{"id": item["check_id"]} for item in requirements],
        "grader_view": {
            "captured_output": blinded["captured_output"],
            **copy.deepcopy(observations[0]),
            "host_assessment": assessment,
            "final_answer": _redact_workspace_paths(
                evidence["final-answer"],
                assessment,
            ),
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
