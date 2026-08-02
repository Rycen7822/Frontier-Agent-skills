"""Canonical model-grader payload identity shared by every transport."""

from __future__ import annotations

import copy
import math
from typing import Any

from evidence_io import canonical_json_bytes, canonical_sha256


def _is_json_value(value: Any) -> bool:
    if value is None or type(value) in {bool, int, str}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_is_json_value(item) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _is_json_value(item)
            for key, item in value.items()
        )
    return False


def semantic_payload(
    view: dict[str, Any],
    check_id: str,
    pass_condition: str,
) -> dict[str, Any]:
    """Return one closed, JSON-native grader payload without normalization."""
    if (
        type(view) is not dict
        or not _is_json_value(view)
        or type(check_id) is not str
        or not check_id.strip()
        or type(pass_condition) is not str
        or not pass_condition.strip()
    ):
        raise ValueError("grader semantic payload fields are invalid")
    payload = {
        "view": copy.deepcopy(view),
        "check": {
            "check_id": check_id,
            "pass_condition": pass_condition,
        },
    }
    canonical_json_bytes(payload)
    return payload


def semantic_payload_hash(payload: dict[str, Any]) -> str:
    """Validate and hash one exact semantic payload."""
    if type(payload) is not dict or set(payload) != {"view", "check"}:
        raise ValueError("grader semantic payload must be a closed object")
    check = payload.get("check")
    if type(check) is not dict or set(check) != {"check_id", "pass_condition"}:
        raise ValueError("grader semantic check must be a closed object")
    validated = semantic_payload(
        payload.get("view"),
        check.get("check_id"),
        check.get("pass_condition"),
    )
    if validated != payload:
        raise ValueError("grader semantic payload is not JSON-native")
    return canonical_sha256(payload)
