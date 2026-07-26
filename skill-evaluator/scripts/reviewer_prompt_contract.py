"""Validate and expand the compact context-clean reviewer prompt packet."""

from __future__ import annotations

from typing import Any

from evidence_io import canonical_sha256


COMPACT_PACKET_SCHEMA = (
    "context-clean-subagent-reviewer-message-packet/1.0"
)
FULL_PACKET_SCHEMA = "context-clean-subagent-reviewer-packet/1.0"
TUPLE_FIELDS = ["opaque_example_id", "view_index", "check_index"]


class PromptContractError(ValueError):
    """The compact prompt packet cannot represent its bound full packet."""


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
    """Expand one canonical compact packet into the authoritative shape."""
    _closed(
        compact,
        {
            "schema_version",
            "campaign_id",
            "tuple_fields",
            "views",
            "checks",
            "examples",
            "source_packet_hash",
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
        or len({canonical_sha256(view) for view in views}) != len(views)
        or len({canonical_sha256(check) for check in checks}) != len(checks)
    ):
        raise PromptContractError("compact reviewer packet identity is invalid")
    for view in views:
        if not isinstance(view, dict) or not view:
            raise PromptContractError("compact reviewer view is invalid")
    for check in checks:
        _closed(
            check,
            {"check_id", "pass_condition"},
            "compact reviewer check",
        )
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
            raise PromptContractError(
                "compact reviewer example is not a triple"
            )
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
                raise PromptContractError(
                    "compact reviewer view order is not canonical"
                )
            seen_views.add(view_index)
        if check_index not in seen_checks:
            if check_index != len(seen_checks):
                raise PromptContractError(
                    "compact reviewer check order is not canonical"
                )
            seen_checks.add(check_index)
        opaque_ids.add(opaque_id)
        payload = {
            "view": views[view_index],
            "check": checks[check_index],
        }
        packet_examples.append({
            "opaque_example_id": opaque_id,
            "payload": payload,
            "payload_hash": canonical_sha256(payload),
        })
    if len(seen_views) != len(views) or len(seen_checks) != len(checks):
        raise PromptContractError(
            "compact reviewer dictionaries contain unused values"
        )

    packet = {
        "schema_version": FULL_PACKET_SCHEMA,
        "campaign_id": campaign_id,
        "examples": packet_examples,
        "packet_hash": "",
    }
    packet["packet_hash"] = canonical_sha256({
        key: value for key, value in packet.items() if key != "packet_hash"
    })
    if packet["packet_hash"] != compact["source_packet_hash"]:
        raise PromptContractError(
            "compact reviewer source packet hash differs"
        )
    return packet
