"""Validate and expand the compact context-clean reviewer prompt packet."""

from __future__ import annotations

from typing import Any

from evidence_io import canonical_json_bytes
from grader_semantics import semantic_payload


COMPACT_PACKET_SCHEMA = "context-clean-subagent-reviewer-message-packet/2.0"
FULL_PACKET_SCHEMA = "context-clean-subagent-reviewer-packet/2.0"
PROMPT_SCHEMA = "context-clean-subagent-reviewer-prompt/5.0"
MATRIX_RESPONSE_SCHEMA = "context-clean-subagent-reviewer-matrix/2.0"
TUPLE_FIELDS = ["opaque_example_id", "view_index", "check_index"]
REVIEWER_INSTRUCTION = (
    'Return exactly {"matrix":[...]} with no other keys or text. Each '
    "[opaque_example_id, view_index, check_index] selects views[view_index] "
    "and checks[check_index]. Rate pass only when authoritative visible "
    "evidence satisfies the pass condition. Rate fail when authoritative "
    "evidence violates the condition or omits required evidence; an ordinary "
    "missing fact fails. When the view explicitly has evidence_state="
    "conflicting_candidate_snapshots, authoritative_snapshot=null, and two "
    "conflicting candidate snapshots, rate every example for that view "
    "abstain and do not assess its candidate snapshots check by check. "
    "Otherwise do not rate abstain. Arrange response_contract.rows strings "
    "with response_contract.columns P/F/A symbols; flattening those strings "
    "row-major must exactly follow packet.examples. Do not infer hidden gold "
    "or unstated facts. Do not return reviewer or opaque example identifiers, "
    "explanations, Markdown, or any other keys."
)


class PromptContractError(ValueError):
    """The compact prompt packet cannot represent its semantic payload."""


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise PromptContractError(f"{label} is not a closed object")
    return value


def _safe_id(value: Any) -> bool:
    allowed = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    )
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character in allowed for character in value)
    )


def expand_prompt_packet(
    compact: dict[str, Any],
    *,
    campaign_id: str,
) -> dict[str, Any]:
    """Expand one compact packet into the authoritative semantic shape."""
    _closed(
        compact,
        {
            "schema_version",
            "campaign_id",
            "tuple_fields",
            "views",
            "checks",
            "examples",
        },
        "compact reviewer packet",
    )
    views = compact["views"]
    checks = compact["checks"]
    examples = compact["examples"]
    if (
        compact["schema_version"] != COMPACT_PACKET_SCHEMA
        or compact["campaign_id"] != campaign_id
        or compact["tuple_fields"] != TUPLE_FIELDS
        or not isinstance(views, list)
        or not views
        or not isinstance(checks, list)
        or not checks
        or not isinstance(examples, list)
        or not examples
        or len({canonical_json_bytes(view) for view in views}) != len(views)
        or len({canonical_json_bytes(check) for check in checks}) != len(checks)
    ):
        raise PromptContractError("compact reviewer packet identity is invalid")
    if any(not isinstance(view, dict) or not view for view in views):
        raise PromptContractError("compact reviewer view is invalid")
    for check in checks:
        _closed(check, {"check_id", "pass_condition"}, "reviewer check")
        if (
            not _safe_id(check["check_id"])
            or not isinstance(check["pass_condition"], str)
            or not check["pass_condition"].strip()
        ):
            raise PromptContractError("compact reviewer check is invalid")

    packet_examples: list[dict[str, Any]] = []
    opaque_ids: set[str] = set()
    seen_views: set[int] = set()
    seen_checks: set[int] = set()
    for example in examples:
        if not isinstance(example, list) or len(example) != 3:
            raise PromptContractError("compact reviewer example is not a triple")
        opaque_id, view_index, check_index = example
        if (
            not _safe_id(opaque_id)
            or opaque_id in opaque_ids
            or type(view_index) is not int
            or type(check_index) is not int
            or not 0 <= view_index < len(views)
            or not 0 <= check_index < len(checks)
        ):
            raise PromptContractError("compact reviewer example is invalid")
        if view_index not in seen_views:
            if view_index != len(seen_views):
                raise PromptContractError("reviewer view order is not canonical")
            seen_views.add(view_index)
        if check_index not in seen_checks:
            if check_index != len(seen_checks):
                raise PromptContractError("reviewer check order is not canonical")
            seen_checks.add(check_index)
        opaque_ids.add(opaque_id)
        check = checks[check_index]
        packet_examples.append({
            "opaque_example_id": opaque_id,
            "payload": semantic_payload(
                views[view_index],
                check["check_id"],
                check["pass_condition"],
            ),
        })
    if len(seen_views) != len(views) or len(seen_checks) != len(checks):
        raise PromptContractError("reviewer dictionaries contain unused values")
    return {
        "schema_version": FULL_PACKET_SCHEMA,
        "campaign_id": campaign_id,
        "examples": packet_examples,
    }


def matrix_response_contract(
    compact: dict[str, Any],
    output_schema_version: str,
) -> dict[str, Any]:
    """Describe the ordered value-only response expected from the reviewer."""
    columns = len(compact["checks"])
    rows, remainder = divmod(len(compact["examples"]), columns)
    if rows < 1 or columns < 1 or remainder:
        raise PromptContractError("reviewer packet is not a row-major matrix")
    return {
        "schema_version": MATRIX_RESPONSE_SCHEMA,
        "rows": rows,
        "columns": columns,
        "symbols": {
            "P": {"label": "pass", "severity": 0},
            "F": {"label": "fail", "severity": 1},
            "A": {"label": "abstain", "severity": 0},
        },
        "example_order": "packet.examples row-major",
        "output_schema_version": output_schema_version,
    }


def validate_reviewer_prompt(
    prompt: dict[str, Any],
    *,
    campaign_id: str,
    reviewer_id: str,
    output_schema_version: str,
) -> dict[str, Any]:
    """Validate one closed prompt and return its expanded semantic packet."""
    _closed(
        prompt,
        {
            "schema_version",
            "reviewer_id",
            "instruction",
            "packet",
            "response_contract",
        },
        "reviewer prompt",
    )
    expanded = expand_prompt_packet(prompt["packet"], campaign_id=campaign_id)
    if (
        prompt["schema_version"] != PROMPT_SCHEMA
        or prompt["reviewer_id"] != reviewer_id
        or prompt["instruction"] != REVIEWER_INSTRUCTION
        or prompt["response_contract"]
        != matrix_response_contract(prompt["packet"], output_schema_version)
    ):
        raise PromptContractError("reviewer prompt exposes or changes context")
    return expanded
