#!/usr/bin/env python3
"""Validate minimal context-clean reviewer-pair calibration evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from evidence_io import canonical_json_bytes
from reviewer_prompt_contract import PromptContractError, validate_reviewer_prompt


PAIR_SCHEMA = "context-clean-subagent-reviewer-pair/3.0"
PACKET_SCHEMA = "context-clean-subagent-reviewer-packet/2.0"
MAPPING_SCHEMA = "context-clean-subagent-reviewer-mapping/2.0"
RECEIPT_SCHEMA = "context-clean-subagent-reviewer-receipt/2.0"
PROMPT_SCHEMA = "context-clean-subagent-reviewer-prompt/5.0"
RATINGS_SCHEMA = "context-clean-subagent-reviewer-ratings/3.0"
ARTIFACT_FIELDS = {"path", "digest", "schema_version"}
CONFIGURATION_FIELDS = {
    "model",
    "reasoning_effort",
    "service_tier",
    "fork_turns",
}
FORBIDDEN_PACKET_KEYS = {
    "gold_label",
    "gold_severity",
    "expected_overall",
    "expected_checks",
    "judge_output",
    "other_reviewer_output",
    "plan",
    "source_path",
    "filesystem_locator",
}
SAFE_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)


class ReviewerPairError(ValueError):
    """A typed calibration contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise ReviewerPairError(code, message)


def _closed(
    value: Any,
    fields: set[str],
    *,
    code: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code, f"{label} must contain exactly {sorted(fields)}")
    return value


def _safe_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character in SAFE_ID_CHARS for character in value)
    )


def _digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _validate_configuration(value: Any) -> dict[str, str]:
    _closed(
        value,
        CONFIGURATION_FIELDS,
        code="calibration.reviewer_pair",
        label="requested configuration",
    )
    text_fields = ("model", "reasoning_effort", "service_tier")
    if any(
        not isinstance(value[field], str)
        or not 1 <= len(value[field]) <= 128
        or not value[field].isprintable()
        for field in text_fields
    ) or value["fork_turns"] != "none":
        _fail(
            "calibration.reviewer_pair",
            "requested configuration is invalid or not context-clean",
        )
    return {field: value[field] for field in sorted(CONFIGURATION_FIELDS)}


def _contains_forbidden_packet_value(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in FORBIDDEN_PACKET_KEYS
            or _contains_forbidden_packet_value(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_packet_value(item) for item in value)
    if isinstance(value, str):
        return any(
            prefix in value
            for prefix in (
                "/home/",
                "/mnt/",
                "/tmp/",
                "/workspace/",
                "/workspaces/",
                "/private/",
                "/Users/",
            )
        )
    return False


def _open_directory_nofollow(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            _fail("calibration.artifact_path", f"not a directory: {path}")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_nofollow_regular(
    path: Path,
    root: Path,
    *,
    label: str,
) -> tuple[dict[str, str], bytes, Path]:
    """Read one regular file beneath root without following path components."""
    absolute_root = Path(os.path.abspath(root))
    absolute_path = Path(os.path.abspath(path))
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError:
        _fail("calibration.artifact_path", f"{label} is outside output root")
    if not relative.parts:
        _fail("calibration.artifact_path", f"{label} must identify a file")
    directory = _open_directory_nofollow(absolute_root)
    try:
        for part in relative.parts[:-1]:
            next_directory = os.open(
                part,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=directory,
            )
            os.close(directory)
            directory = next_directory
        descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                _fail(
                    "calibration.artifact_path",
                    f"{label} is not a regular file",
                )
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
    except OSError as exc:
        _fail(
            "calibration.artifact_path",
            f"cannot open {label} without symlink components: {exc}",
        )
    finally:
        os.close(directory)
    return (
        {
            "path": relative.as_posix(),
            "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        },
        raw,
        absolute_path,
    )


def _load_json(raw: bytes, *, code: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(code, f"{label} is not valid UTF-8 JSON: {exc}")
    if not isinstance(value, dict):
        _fail(code, f"{label} must be a JSON object")
    return value


def _read_binding(
    binding: Any,
    *,
    output_root: Path,
    expected_schema: str,
    code: str,
    label: str,
) -> tuple[dict[str, Any], Path]:
    binding = _closed(
        binding,
        ARTIFACT_FIELDS,
        code=code,
        label=f"{label} binding",
    )
    if (
        not isinstance(binding["path"], str)
        or not _digest(binding["digest"])
        or binding["schema_version"] != expected_schema
    ):
        _fail(code, f"{label} binding fields are invalid")
    relative = PurePosixPath(binding["path"])
    if (
        binding["path"].startswith("/")
        or "\\" in binding["path"]
        or any(part == ".." for part in relative.parts)
        or relative.as_posix() in {"", "."}
    ):
        _fail(code, f"{label} binding path is not contained")
    observed, raw, absolute = read_nofollow_regular(
        output_root / binding["path"], output_root, label=label
    )
    if observed != {"path": binding["path"], "digest": binding["digest"]}:
        _fail(code, f"{label} binding does not match reopened bytes")
    document = _load_json(raw, code=code, label=label)
    if document.get("schema_version") != expected_schema:
        _fail(code, f"{label} schema version differs")
    return document, absolute


def _validate_packet(
    packet: dict[str, Any],
    *,
    campaign_id: str,
    expected_checks: dict[str, str],
) -> list[dict[str, Any]]:
    _closed(
        packet,
        {"schema_version", "campaign_id", "examples"},
        code="calibration.reviewer_packet",
        label="reviewer packet",
    )
    examples = packet["examples"]
    if (
        packet["schema_version"] != PACKET_SCHEMA
        or packet["campaign_id"] != campaign_id
        or not isinstance(examples, list)
        or not examples
    ):
        _fail("calibration.reviewer_packet", "reviewer packet is invalid")
    opaque_ids: set[str] = set()
    for example in examples:
        _closed(
            example,
            {"opaque_example_id", "payload"},
            code="calibration.reviewer_packet",
            label="reviewer packet example",
        )
        payload = example["payload"]
        if not isinstance(payload, dict) or set(payload) != {"view", "check"}:
            _fail("calibration.reviewer_packet", "semantic payload is invalid")
        check = payload["check"]
        if not isinstance(check, dict) or set(check) != {
            "check_id",
            "pass_condition",
        }:
            _fail("calibration.reviewer_packet", "semantic check is invalid")
        opaque_id = example["opaque_example_id"]
        try:
            canonical_json_bytes(payload)
        except (TypeError, ValueError):
            _fail("calibration.reviewer_packet", "semantic payload is not JSON")
        if (
            not _safe_id(opaque_id)
            or opaque_id in opaque_ids
            or check.get("check_id") not in expected_checks
            or check.get("pass_condition")
            != expected_checks.get(check.get("check_id"))
            or not isinstance(payload["view"], dict)
            or not payload["view"]
            or _contains_forbidden_packet_value(payload)
        ):
            _fail("calibration.reviewer_packet", "reviewer packet leaks or drifts")
        opaque_ids.add(opaque_id)
    return examples


def _validate_mapping(
    mapping: dict[str, Any],
    *,
    campaign_id: str,
    packet_examples: list[dict[str, Any]],
    labels: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    _closed(
        mapping,
        {"schema_version", "campaign_id", "examples"},
        code="calibration.reviewer_mapping",
        label="sealed reviewer mapping",
    )
    items = mapping["examples"]
    if (
        mapping["schema_version"] != MAPPING_SCHEMA
        or mapping["campaign_id"] != campaign_id
        or not isinstance(items, list)
        or len(items) != len(packet_examples)
    ):
        _fail("calibration.reviewer_mapping", "sealed mapping is invalid")
    expected_opaque = [item["opaque_example_id"] for item in packet_examples]
    if [item.get("opaque_example_id") for item in items] != expected_opaque:
        _fail("calibration.reviewer_mapping", "sealed mapping order differs")
    by_opaque: dict[str, dict[str, Any]] = {}
    for packet_example, item in zip(packet_examples, items, strict=True):
        _closed(
            item,
            {"opaque_example_id", "example_id", "check_id", "dimension"},
            code="calibration.reviewer_mapping",
            label="sealed mapping row",
        )
        label = labels.get((item["example_id"], item["check_id"]))
        if (
            label is None
            or item["dimension"] != label["dimension"]
            or packet_example["payload"] != label["payload"]
        ):
            _fail("calibration.reviewer_mapping", "mapping semantic join differs")
        by_opaque[item["opaque_example_id"]] = item
    return by_opaque


def _validate_receipt(
    binding: dict[str, Any],
    *,
    output_root: Path,
    campaign_id: str,
    requested_configuration: dict[str, str],
    packet: dict[str, Any],
    reviewer_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    receipt, _ = _read_binding(
        binding,
        output_root=output_root,
        expected_schema=RECEIPT_SCHEMA,
        code="calibration.reviewer_receipt",
        label="reviewer receipt",
    )
    _closed(
        receipt,
        {
            "schema_version",
            "receipt_id",
            "campaign_id",
            "request_id",
            "reviewer_id",
            "principal_id",
            "agent_id",
            "task_name",
            "requested_configuration",
            "prompt",
            "raw_response",
            "terminal_status",
            "ack_sequence",
            "result_consumed_sequence",
            "observable_extra_turns",
            "observable_followups",
            "observable_tool_events",
        },
        code="calibration.reviewer_receipt",
        label="reviewer receipt",
    )
    id_fields = (
        "receipt_id",
        "request_id",
        "reviewer_id",
        "principal_id",
        "agent_id",
        "task_name",
    )
    if (
        receipt["campaign_id"] != campaign_id
        or not all(_safe_id(receipt[field]) for field in id_fields)
        or _validate_configuration(receipt["requested_configuration"])
        != requested_configuration
        or receipt["terminal_status"] != "complete"
        or type(receipt["ack_sequence"]) is not int
        or type(receipt["result_consumed_sequence"]) is not int
        or receipt["ack_sequence"] >= receipt["result_consumed_sequence"]
        or receipt["observable_extra_turns"] != 0
        or receipt["observable_followups"] != 0
        or receipt["observable_tool_events"] != []
    ):
        _fail("calibration.reviewer_receipt", "reviewer lifecycle is invalid")
    prompt, _ = _read_binding(
        receipt["prompt"],
        output_root=output_root,
        expected_schema=PROMPT_SCHEMA,
        code="calibration.reviewer_prompt",
        label="reviewer prompt",
    )
    try:
        expanded = validate_reviewer_prompt(
            prompt,
            campaign_id=campaign_id,
            reviewer_id=receipt["reviewer_id"],
            output_schema_version=RATINGS_SCHEMA,
        )
    except PromptContractError as exc:
        _fail("calibration.reviewer_prompt", str(exc))
    if expanded != packet:
        _fail("calibration.reviewer_prompt", "reviewer prompt packet differs")
    response, _ = _read_binding(
        receipt["raw_response"],
        output_root=output_root,
        expected_schema=RATINGS_SCHEMA,
        code="calibration.reviewer_output",
        label="reviewer raw response",
    )
    _closed(
        response,
        {"schema_version", "ratings"},
        code="calibration.reviewer_output",
        label="reviewer raw response",
    )
    ratings = response["ratings"]
    if not isinstance(ratings, list) or len(ratings) != len(reviewer_rows):
        _fail("calibration.reviewer_output", "reviewer output coverage differs")
    for rating, row in zip(ratings, reviewer_rows, strict=True):
        _closed(
            rating,
            {"label", "severity"},
            code="calibration.reviewer_output",
            label="reviewer judgment",
        )
        severity = rating["severity"]
        if (
            rating["label"] not in {"pass", "fail", "abstain"}
            or not isinstance(severity, (int, float))
            or isinstance(severity, bool)
            or not math.isfinite(float(severity))
            or rating != {"label": row["label"], "severity": row["severity"]}
        ):
            _fail("calibration.reviewer_output", "reviewer judgment differs")
    return receipt


def validate_reviewer_pair(
    pair_path: Path,
    *,
    output_root: Path,
    reviewer_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
    judge_reviewer_ids: set[str],
    judge_principal_ids: set[str],
    judge_grader_id: str,
    expected_checks: dict[str, str],
) -> dict[str, Any]:
    """Validate and map exactly two context-clean reviewer streams."""
    pair_binding, pair_raw, _ = read_nofollow_regular(
        pair_path, output_root, label="reviewer pair"
    )
    pair = _load_json(
        pair_raw, code="calibration.reviewer_pair", label="reviewer pair"
    )
    _closed(
        pair,
        {
            "schema_version",
            "pair_id",
            "campaign_id",
            "packet",
            "sealed_mapping",
            "requested_configuration",
            "reviewer_receipts",
            "both_spawns_acknowledged_before_first_result_consumed",
        },
        code="calibration.reviewer_pair",
        label="reviewer pair",
    )
    if (
        pair["schema_version"] != PAIR_SCHEMA
        or not _safe_id(pair["pair_id"])
        or not _safe_id(pair["campaign_id"])
        or pair["both_spawns_acknowledged_before_first_result_consumed"] is not True
        or not isinstance(pair["reviewer_receipts"], list)
        or len(pair["reviewer_receipts"]) != 2
    ):
        _fail("calibration.reviewer_pair", "reviewer pair identity is invalid")
    requested = _validate_configuration(pair["requested_configuration"])
    packet, _ = _read_binding(
        pair["packet"],
        output_root=output_root,
        expected_schema=PACKET_SCHEMA,
        code="calibration.reviewer_packet",
        label="reviewer packet",
    )
    packet_examples = _validate_packet(
        packet,
        campaign_id=pair["campaign_id"],
        expected_checks=expected_checks,
    )
    mapping, _ = _read_binding(
        pair["sealed_mapping"],
        output_root=output_root,
        expected_schema=MAPPING_SCHEMA,
        code="calibration.reviewer_mapping",
        label="sealed reviewer mapping",
    )
    mapping_by_opaque = _validate_mapping(
        mapping,
        campaign_id=pair["campaign_id"],
        packet_examples=packet_examples,
        labels={(row["example_id"], row["check_id"]): row for row in label_rows},
    )

    rows_by_reviewer: dict[str, list[dict[str, Any]]] = {}
    for row in reviewer_rows:
        reviewer = row.get("reviewer", {})
        reviewer_id = reviewer.get("reviewer_id")
        if (
            reviewer.get("role") != "context_clean_subagent_reviewer"
            or not _safe_id(reviewer_id)
            or reviewer.get("blinded") is not True
            or row.get("grader_identity") is not None
            or row.get("execution_profile") is not None
            or row.get("independence_facts") is not None
            or row.get("grader_id") != judge_grader_id
        ):
            _fail("calibration.reviewer_rows", "reviewer row identity is invalid")
        rows_by_reviewer.setdefault(reviewer_id, []).append(row)
    if len(rows_by_reviewer) != 2:
        _fail("calibration.reviewer_count", "exactly two reviewers are required")
    opaque_ids = [item["opaque_example_id"] for item in packet_examples]
    mapped_rows: list[dict[str, Any]] = []
    for reviewer_id in sorted(rows_by_reviewer):
        rows = rows_by_reviewer[reviewer_id]
        if [row["example_id"] for row in rows] != opaque_ids:
            _fail("calibration.reviewer_coverage", "reviewer ordering differs")
        for row in rows:
            mapped = mapping_by_opaque.get(row["example_id"])
            if (
                mapped is None
                or row["check_id"] != mapped["check_id"]
                or row["dimension"] != mapped["dimension"]
            ):
                _fail("calibration.reviewer_mapping", "reviewer mapping differs")
            mapped_rows.append({**row, "example_id": mapped["example_id"]})

    receipt_bindings = pair["reviewer_receipts"]
    paths = [item.get("path") for item in receipt_bindings if isinstance(item, dict)]
    if len(paths) != 2 or paths != sorted(paths) or len(set(paths)) != 2:
        _fail("calibration.reviewer_receipt", "receipt bindings are not ordered")
    receipts = []
    for binding in receipt_bindings:
        path_hint = binding.get("path") if isinstance(binding, dict) else None
        reviewer_id = Path(path_hint).parent.name if isinstance(path_hint, str) else ""
        rows = rows_by_reviewer.get(reviewer_id)
        if rows is None:
            _fail("calibration.reviewer_receipt", "receipt reviewer has no rows")
        receipts.append(
            _validate_receipt(
                binding,
                output_root=output_root,
                campaign_id=pair["campaign_id"],
                requested_configuration=requested,
                packet=packet,
                reviewer_rows=rows,
            )
        )
    unique_fields = (
        "request_id",
        "reviewer_id",
        "principal_id",
        "agent_id",
        "task_name",
    )
    if any(len({receipt[field] for receipt in receipts}) != 2 for field in unique_fields):
        _fail("calibration.reviewer_identity", "reviewer identities collide")
    reviewer_ids = {receipt["reviewer_id"] for receipt in receipts}
    principal_ids = {receipt["principal_id"] for receipt in receipts}
    if (
        reviewer_ids != set(rows_by_reviewer)
        or not reviewer_ids.isdisjoint(judge_reviewer_ids)
        or not principal_ids.isdisjoint(judge_principal_ids)
    ):
        _fail("calibration.reviewer_identity", "reviewer identity collides")
    for receipt in receipts:
        reviewer = rows_by_reviewer[receipt["reviewer_id"]][0]["reviewer"]
        if reviewer["principal_id"] != receipt["principal_id"]:
            _fail("calibration.reviewer_identity", "reviewer principal differs")
    if max(item["ack_sequence"] for item in receipts) >= min(
        item["result_consumed_sequence"] for item in receipts
    ):
        _fail("calibration.reviewer_barrier", "result consumed before both acks")
    return {
        "binding": {
            **pair_binding,
            "schema_version": PAIR_SCHEMA,
        },
        "mapped_rows": mapped_rows,
        "reviewer_ids": sorted(reviewer_ids),
        "principal_ids": sorted(principal_ids),
    }
