#!/usr/bin/env python3
"""Validate context-clean reviewer-pair evidence for grader calibration."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from evidence_io import canonical_sha256, verify_self_hash


PAIR_FIELDS = {
    "schema_version", "pair_id", "campaign_id", "packet", "output_schema",
    "sealed_mapping", "reviewer_receipts",
    "both_spawns_acknowledged_before_first_result_consumed", "pair_hash",
}
RECEIPT_FIELDS = {
    "schema_version", "receipt_id", "campaign_id", "request_id",
    "reviewer_id", "principal_id", "agent_id", "task_name",
    "requested_configuration", "reservation_hash", "prompt_hash",
    "packet_hash", "output_schema_hash", "spawn_request_hash",
    "spawn_ack_hash", "terminal_result_hash", "raw_response_hash",
    "parsed_ratings_hash", "terminal_status", "receipt_hash",
}
ARTIFACT_BINDING_FIELDS = {"path", "sha256"}
REQUESTED_CONFIGURATION = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "max",
    "service_tier": "priority",
    "fork_turns": "none",
}
FORBIDDEN_PACKET_KEYS = {
    "gold_label", "gold_severity", "expected_overall", "expected_checks",
    "judge_output", "other_reviewer_output", "plan", "source_path",
    "filesystem_locator",
}
SAFE_ID_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-",
)
SHA256_PREFIX = "sha256:"


class ReviewerPairError(ValueError):
    """A typed calibration contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str) -> None:
    raise ReviewerPairError(code, message)


def _safe_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and value[0].isalnum()
        and all(character in SAFE_ID_CHARS for character in value)
    )


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith(SHA256_PREFIX)
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _contains_forbidden_packet_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in FORBIDDEN_PACKET_KEYS
            or _contains_forbidden_packet_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_packet_key(item) for item in value)
    return False


def _closed_object(
    value: Any,
    fields: set[str],
    *,
    code: str,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code, f"{label} must contain exactly {sorted(fields)}")
    return value


def _open_directory_nofollow(path: Path) -> int:
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
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
    """Open one regular file beneath root without following any component."""
    absolute_root = Path(os.path.abspath(root))
    absolute_path = Path(os.path.abspath(path))
    try:
        relative = absolute_path.relative_to(absolute_root)
    except ValueError:
        _fail("calibration.artifact_path", f"{label} is outside output root")
    if not relative.parts:
        _fail("calibration.artifact_path", f"{label} must identify a file")
    try:
        directory = _open_directory_nofollow(absolute_root)
    except OSError as exc:
        _fail(
            "calibration.artifact_path",
            f"cannot open {label} root without symlink components: {exc}",
        )
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
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                _fail(
                    "calibration.artifact_path",
                    f"{label} is not a regular file",
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
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
            "sha256": SHA256_PREFIX + hashlib.sha256(raw).hexdigest(),
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
    code: str,
    label: str,
) -> tuple[dict[str, Any], bytes, Path]:
    binding = _closed_object(
        binding,
        ARTIFACT_BINDING_FIELDS,
        code=code,
        label=f"{label} binding",
    )
    if not isinstance(binding["path"], str) or not _sha256(binding["sha256"]):
        _fail(code, f"{label} binding fields are invalid")
    relative = PurePosixPath(binding["path"])
    if (
        binding["path"].startswith("/")
        or "\\" in binding["path"]
        or any(part == ".." for part in relative.parts)
        or relative.as_posix() in {"", "."}
    ):
        _fail(code, f"{label} binding path is not a contained POSIX path")
    path = output_root / binding["path"]
    observed_binding, raw, absolute = read_nofollow_regular(
        path, output_root, label=label,
    )
    if observed_binding != binding:
        _fail(code, f"{label} binding does not match reopened bytes")
    return _load_json(raw, code=code, label=label), raw, absolute


def expected_ratings_schema() -> dict[str, Any]:
    """Return the exact reviewer output schema independently owned by product."""
    safe_id = {
        "type": "string",
        "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.invalid/context-clean-subagent-reviewer-ratings-v1.schema.json",
        "type": "object",
        "required": ["schema_version", "reviewer_id", "ratings"],
        "properties": {
            "schema_version": {
                "const": "context-clean-subagent-reviewer-ratings/1.0",
            },
            "reviewer_id": safe_id,
            "ratings": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["opaque_example_id", "label", "severity"],
                    "properties": {
                        "opaque_example_id": safe_id,
                        "label": {"enum": ["pass", "fail", "abstain"]},
                        "severity": {"type": "number"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


def _validate_packet(
    packet: dict[str, Any],
    *,
    campaign_id: str,
    expected_checks: dict[str, str],
) -> list[dict[str, Any]]:
    fields = {"schema_version", "campaign_id", "examples", "packet_hash"}
    _closed_object(
        packet, fields, code="calibration.reviewer_packet", label="packet",
    )
    if (
        packet["schema_version"] != "context-clean-subagent-reviewer-packet/1.0"
        or packet["campaign_id"] != campaign_id
        or not verify_self_hash(packet, "packet_hash")
        or not isinstance(packet["examples"], list)
        or not packet["examples"]
    ):
        _fail("calibration.reviewer_packet", "packet identity or self-hash is invalid")
    seen: set[str] = set()
    for example in packet["examples"]:
        _closed_object(
            example,
            {"opaque_example_id", "payload", "payload_hash"},
            code="calibration.reviewer_packet",
            label="packet example",
        )
        opaque_id = example["opaque_example_id"]
        payload = _closed_object(
            example["payload"],
            {"view", "check"},
            code="calibration.reviewer_packet",
            label="packet payload",
        )
        check = _closed_object(
            payload["check"],
            {"check_id", "pass_condition"},
            code="calibration.reviewer_packet",
            label="packet check",
        )
        if (
            not _safe_id(opaque_id)
            or opaque_id in seen
            or not isinstance(payload["view"], dict)
            or not payload["view"]
            or not _safe_id(check["check_id"])
            or not isinstance(check["pass_condition"], str)
            or not check["pass_condition"].strip()
            or expected_checks.get(check["check_id"])
            != check["pass_condition"]
            or _contains_forbidden_packet_key(payload)
            or example["payload_hash"] != canonical_sha256(payload)
        ):
            _fail("calibration.reviewer_packet", "packet examples are invalid or duplicated")
        seen.add(opaque_id)
    return packet["examples"]


def _validate_mapping(
    mapping: dict[str, Any],
    *,
    campaign_id: str,
    packet_binding: dict[str, str],
    schema_binding: dict[str, str],
    packet_examples: list[dict[str, Any]],
    labels: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    fields = {
        "schema_version", "campaign_id", "packet_hash", "output_schema_hash",
        "examples", "mapping_hash",
    }
    _closed_object(
        mapping, fields, code="calibration.reviewer_mapping", label="sealed mapping",
    )
    if (
        mapping["schema_version"] != "context-clean-subagent-reviewer-mapping/1.0"
        or mapping["campaign_id"] != campaign_id
        or mapping["packet_hash"] != packet_binding["sha256"]
        or mapping["output_schema_hash"] != schema_binding["sha256"]
        or not verify_self_hash(mapping, "mapping_hash")
        or not isinstance(mapping["examples"], list)
    ):
        _fail("calibration.reviewer_mapping", "sealed mapping identity or hash is invalid")
    expected_opaque = [item["opaque_example_id"] for item in packet_examples]
    observed_opaque: list[str] = []
    by_opaque: dict[str, dict[str, Any]] = {}
    real_ids: set[str] = set()
    for item in mapping["examples"]:
        _closed_object(
            item,
            {
                "opaque_example_id", "example_id", "check_id",
                "dimension", "payload_hash",
            },
            code="calibration.reviewer_mapping",
            label="sealed mapping example",
        )
        opaque_id = item["opaque_example_id"]
        real_id = item["example_id"]
        label = labels.get(real_id)
        if (
            not _safe_id(opaque_id)
            or not _safe_id(real_id)
            or opaque_id in by_opaque
            or real_id in real_ids
            or label is None
            or item["check_id"] != label["check_id"]
            or item["dimension"] != label["dimension"]
            or item["payload_hash"] != label["payload_hash"]
        ):
            _fail("calibration.reviewer_mapping", "sealed mapping does not join labels exactly")
        observed_opaque.append(opaque_id)
        real_ids.add(real_id)
        by_opaque[opaque_id] = item
    if observed_opaque != expected_opaque or set(real_ids) != set(labels):
        _fail("calibration.reviewer_mapping", "sealed mapping coverage or ordering differs")
    for packet_example in packet_examples:
        mapped = by_opaque[packet_example["opaque_example_id"]]
        if (
            mapped["payload_hash"] != packet_example["payload_hash"]
            or mapped["check_id"]
            != packet_example["payload"]["check"]["check_id"]
        ):
            _fail("calibration.reviewer_mapping", "packet and mapping payload/check binding differs")
    return by_opaque


def _read_sibling_json(
    receipt_path: Path,
    name: str,
    expected_hash: str,
    *,
    output_root: Path,
    code: str,
) -> tuple[dict[str, Any], bytes]:
    binding, raw, _ = read_nofollow_regular(
        receipt_path.parent / name,
        output_root,
        label=f"{receipt_path.parent.name}/{name}",
    )
    if binding["sha256"] != expected_hash:
        _fail(code, f"{name} bytes do not match the receipt")
    return _load_json(raw, code=code, label=name), raw


def _validate_receipt(
    receipt: dict[str, Any],
    receipt_path: Path,
    *,
    output_root: Path,
    campaign_id: str,
    packet: dict[str, Any],
    packet_binding: dict[str, str],
    output_schema: dict[str, Any],
    schema_binding: dict[str, str],
    reviewer_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    _closed_object(
        receipt, RECEIPT_FIELDS,
        code="calibration.reviewer_receipt",
        label="reviewer receipt",
    )
    id_fields = (
        "receipt_id", "request_id", "reviewer_id", "principal_id",
        "agent_id", "task_name",
    )
    if (
        receipt["schema_version"]
        != "context-clean-subagent-reviewer-receipt/1.0"
        or receipt["campaign_id"] != campaign_id
        or not all(_safe_id(receipt[field]) for field in id_fields)
        or receipt["requested_configuration"] != REQUESTED_CONFIGURATION
        or receipt["terminal_status"] != "complete"
        or not verify_self_hash(receipt, "receipt_hash")
    ):
        _fail("calibration.reviewer_receipt", "reviewer receipt identity or self-hash is invalid")
    hash_fields = {
        field for field in RECEIPT_FIELDS if field.endswith("_hash")
    }
    if not all(_sha256(receipt[field]) for field in hash_fields):
        _fail("calibration.reviewer_receipt", "reviewer receipt contains an invalid hash")
    if (
        receipt["packet_hash"] != packet_binding["sha256"]
        or receipt["output_schema_hash"] != schema_binding["sha256"]
    ):
        _fail("calibration.reviewer_receipt", "receipt packet/schema binding differs")

    reservation, _ = _read_sibling_json(
        receipt_path, "reservation.json", receipt["reservation_hash"],
        output_root=output_root, code="calibration.reviewer_reservation",
    )
    _closed_object(
        reservation,
        {
            "schema_version", "campaign_id", "request_id", "family",
            "request_kind", "entry_hash",
        },
        code="calibration.reviewer_reservation",
        label="reviewer reservation",
    )
    if (
        reservation["schema_version"] != "frontier-provider-reservation/2.0"
        or reservation["campaign_id"] != campaign_id
        or reservation["request_id"] != receipt["request_id"]
        or reservation["family"] != "reviewer_calibration"
        or reservation["request_kind"] != "context_isolated_review"
        or not _sha256(reservation["entry_hash"])
    ):
        _fail("calibration.reviewer_reservation", "reservation does not bind the reviewer request")

    prompt, _ = _read_sibling_json(
        receipt_path, "prompt.json", receipt["prompt_hash"],
        output_root=output_root, code="calibration.reviewer_prompt",
    )
    _closed_object(
        prompt,
        {"schema_version", "reviewer_id", "instruction", "packet", "output_schema"},
        code="calibration.reviewer_prompt",
        label="reviewer prompt",
    )
    if (
        prompt["schema_version"] != "context-clean-subagent-reviewer-prompt/1.0"
        or prompt["reviewer_id"] != receipt["reviewer_id"]
        or prompt["instruction"] != "Return typed JSON only."
        or prompt["packet"] != packet
        or prompt["output_schema"] != output_schema
    ):
        _fail("calibration.reviewer_prompt", "reviewer prompt exposes or changes context")

    spawn_request, _ = _read_sibling_json(
        receipt_path, "spawn-request.json", receipt["spawn_request_hash"],
        output_root=output_root, code="calibration.reviewer_spawn_request",
    )
    _closed_object(
        spawn_request,
        {
            "schema_version", "request_id", "reviewer_id", "task_name",
            "model", "reasoning_effort", "service_tier", "fork_turns",
            "message_hash",
        },
        code="calibration.reviewer_spawn_request",
        label="spawn request",
    )
    expected_request = {
        "request_id": receipt["request_id"],
        "reviewer_id": receipt["reviewer_id"],
        "task_name": receipt["task_name"],
        **REQUESTED_CONFIGURATION,
        "message_hash": receipt["prompt_hash"],
    }
    if (
        spawn_request["schema_version"] != "context-clean-subagent-spawn-request/1.0"
        or {
            field: spawn_request[field] for field in expected_request
        } != expected_request
    ):
        _fail("calibration.reviewer_spawn_request", "spawn request configuration differs")

    spawn_ack, _ = _read_sibling_json(
        receipt_path, "spawn-ack.json", receipt["spawn_ack_hash"],
        output_root=output_root, code="calibration.reviewer_spawn_ack",
    )
    _closed_object(
        spawn_ack,
        {
            "schema_version", "request_id", "agent_id", "task_name",
            "ack_sequence",
        },
        code="calibration.reviewer_spawn_ack",
        label="spawn ack",
    )
    if (
        spawn_ack["schema_version"] != "context-clean-subagent-spawn-ack/1.0"
        or spawn_ack["request_id"] != receipt["request_id"]
        or spawn_ack["agent_id"] != receipt["agent_id"]
        or spawn_ack["task_name"] != receipt["task_name"]
        or not isinstance(spawn_ack["ack_sequence"], int)
        or isinstance(spawn_ack["ack_sequence"], bool)
        or spawn_ack["ack_sequence"] < 1
    ):
        _fail("calibration.reviewer_spawn_ack", "spawn ack does not bind the request")

    raw_response, raw_response_bytes = _read_sibling_json(
        receipt_path, "raw-response.json", receipt["raw_response_hash"],
        output_root=output_root, code="calibration.reviewer_output",
    )
    _closed_object(
        raw_response,
        {"schema_version", "reviewer_id", "ratings"},
        code="calibration.reviewer_output",
        label="reviewer output",
    )
    if (
        raw_response["schema_version"]
        != "context-clean-subagent-reviewer-ratings/1.0"
        or raw_response["reviewer_id"] != receipt["reviewer_id"]
        or not isinstance(raw_response["ratings"], list)
        or not raw_response["ratings"]
    ):
        _fail("calibration.reviewer_output", "reviewer output identity or ratings are invalid")
    for rating in raw_response["ratings"]:
        _closed_object(
            rating,
            {"opaque_example_id", "label", "severity"},
            code="calibration.reviewer_output",
            label="reviewer output rating",
        )
        if (
            not _safe_id(rating["opaque_example_id"])
            or rating["label"] not in {"pass", "fail", "abstain"}
            or not isinstance(rating["severity"], (int, float))
            or isinstance(rating["severity"], bool)
            or not math.isfinite(float(rating["severity"]))
        ):
            _fail("calibration.reviewer_output", "reviewer output rating is invalid")
    projected_rows = [
        {
            "opaque_example_id": row["example_id"],
            "label": row["label"],
            "severity": row["severity"],
        }
        for row in reviewer_rows
    ]
    if raw_response["ratings"] != projected_rows:
        _fail("calibration.reviewer_output", "reviewer output differs from raw rating rows")
    if receipt["parsed_ratings_hash"] != canonical_sha256(projected_rows):
        _fail("calibration.reviewer_output", "parsed ratings hash differs")

    terminal, _ = _read_sibling_json(
        receipt_path, "terminal-result.json", receipt["terminal_result_hash"],
        output_root=output_root, code="calibration.reviewer_terminal",
    )
    _closed_object(
        terminal,
        {
            "schema_version", "request_id", "agent_id", "status",
            "result_consumed_sequence", "observable_extra_turns",
            "observable_followups", "observable_tool_events",
            "raw_response_hash",
        },
        code="calibration.reviewer_terminal",
        label="terminal result",
    )
    if (
        terminal["schema_version"] != "context-clean-subagent-terminal-result/1.0"
        or terminal["request_id"] != receipt["request_id"]
        or terminal["agent_id"] != receipt["agent_id"]
        or terminal["status"] != "complete"
        or terminal["raw_response_hash"]
        != SHA256_PREFIX + hashlib.sha256(raw_response_bytes).hexdigest()
        or not isinstance(terminal["result_consumed_sequence"], int)
        or isinstance(terminal["result_consumed_sequence"], bool)
        or terminal["result_consumed_sequence"] < 1
        or not isinstance(terminal["observable_extra_turns"], int)
        or isinstance(terminal["observable_extra_turns"], bool)
        or terminal["observable_extra_turns"] != 0
        or not isinstance(terminal["observable_followups"], int)
        or isinstance(terminal["observable_followups"], bool)
        or terminal["observable_followups"] != 0
        or terminal["observable_tool_events"] != []
    ):
        _fail("calibration.reviewer_terminal", "terminal result is incomplete or has extra observations")
    return {
        "receipt": receipt,
        "ack_sequence": spawn_ack["ack_sequence"],
        "result_consumed_sequence": terminal["result_consumed_sequence"],
    }


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
        pair_path, output_root, label="reviewer pair",
    )
    pair = _load_json(
        pair_raw, code="calibration.reviewer_pair", label="reviewer pair",
    )
    _closed_object(
        pair, PAIR_FIELDS, code="calibration.reviewer_pair", label="reviewer pair",
    )
    if (
        pair["schema_version"] != "context-clean-subagent-reviewer-pair/1.0"
        or not _safe_id(pair["pair_id"])
        or not _safe_id(pair["campaign_id"])
        or pair["both_spawns_acknowledged_before_first_result_consumed"] is not True
        or not verify_self_hash(pair, "pair_hash")
        or not isinstance(pair["reviewer_receipts"], list)
        or len(pair["reviewer_receipts"]) != 2
    ):
        _fail("calibration.reviewer_pair", "reviewer pair identity or self-hash is invalid")

    packet, _, _ = _read_binding(
        pair["packet"],
        output_root=output_root,
        code="calibration.reviewer_packet",
        label="reviewer packet",
    )
    output_schema, _, _ = _read_binding(
        pair["output_schema"],
        output_root=output_root,
        code="calibration.reviewer_schema",
        label="reviewer output schema",
    )
    mapping, _, _ = _read_binding(
        pair["sealed_mapping"],
        output_root=output_root,
        code="calibration.reviewer_mapping",
        label="sealed reviewer mapping",
    )
    if output_schema != expected_ratings_schema():
        _fail("calibration.reviewer_schema", "reviewer output schema differs from product contract")
    packet_examples = _validate_packet(
        packet,
        campaign_id=pair["campaign_id"],
        expected_checks=expected_checks,
    )
    labels = {row["example_id"]: row for row in label_rows}
    mapping_by_opaque = _validate_mapping(
        mapping,
        campaign_id=pair["campaign_id"],
        packet_binding=pair["packet"],
        schema_binding=pair["output_schema"],
        packet_examples=packet_examples,
        labels=labels,
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
            or row.get("execution_identity") is not None
            or row.get("independence_facts") is not None
            or row.get("grader_id") != judge_grader_id
        ):
            _fail("calibration.reviewer_rows", "reviewer row carries invalid identity fields")
        rows_by_reviewer.setdefault(reviewer_id, []).append(row)
    if len(rows_by_reviewer) != 2:
        _fail("calibration.reviewer_count", "reviewer pair requires exactly two reviewers")

    receipt_bindings = pair["reviewer_receipts"]
    if not all(isinstance(item, dict) for item in receipt_bindings):
        _fail("calibration.reviewer_receipt", "receipt bindings must be objects")
    receipt_paths = [item.get("path") for item in receipt_bindings]
    if (
        not all(isinstance(path, str) for path in receipt_paths)
        or receipt_paths != sorted(receipt_paths)
        or len(set(receipt_paths)) != 2
    ):
        _fail("calibration.reviewer_receipt", "receipt bindings must be path-sorted")
    receipt_results: list[dict[str, Any]] = []
    for binding in receipt_bindings:
        receipt, _, receipt_path = _read_binding(
            binding,
            output_root=output_root,
            code="calibration.reviewer_receipt",
            label="reviewer receipt",
        )
        reviewer_id = receipt.get("reviewer_id")
        rows = rows_by_reviewer.get(reviewer_id)
        if rows is None:
            _fail("calibration.reviewer_receipt", "receipt reviewer has no raw rows")
        receipt_results.append(
            _validate_receipt(
                receipt,
                receipt_path,
                output_root=output_root,
                campaign_id=pair["campaign_id"],
                packet=packet,
                packet_binding=pair["packet"],
                output_schema=output_schema,
                schema_binding=pair["output_schema"],
                reviewer_rows=rows,
            )
        )

    receipts = [result["receipt"] for result in receipt_results]
    unique_fields = (
        "request_id", "reviewer_id", "principal_id", "agent_id", "task_name",
    )
    if any(len({receipt[field] for receipt in receipts}) != 2 for field in unique_fields):
        _fail("calibration.reviewer_identity", "reviewer receipt identities must be distinct")
    reviewer_ids = {receipt["reviewer_id"] for receipt in receipts}
    principal_ids = {receipt["principal_id"] for receipt in receipts}
    if (
        reviewer_ids != set(rows_by_reviewer)
        or not reviewer_ids.isdisjoint(judge_reviewer_ids)
        or not principal_ids.isdisjoint(judge_principal_ids)
    ):
        _fail("calibration.reviewer_identity", "reviewer identity collides with the judge")
    for receipt in receipts:
        reviewer = rows_by_reviewer[receipt["reviewer_id"]][0]["reviewer"]
        if reviewer["principal_id"] != receipt["principal_id"]:
            _fail("calibration.reviewer_identity", "raw reviewer principal differs from receipt")

    opaque_ids = [item["opaque_example_id"] for item in packet_examples]
    mapped_rows: list[dict[str, Any]] = []
    for reviewer_id in sorted(rows_by_reviewer):
        rows = rows_by_reviewer[reviewer_id]
        if [row["example_id"] for row in rows] != opaque_ids:
            _fail("calibration.reviewer_coverage", "reviewer opaque coverage or ordering differs")
        for row in rows:
            mapped = mapping_by_opaque.get(row["example_id"])
            if (
                mapped is None
                or row["check_id"] != mapped["check_id"]
                or row["dimension"] != mapped["dimension"]
            ):
                _fail("calibration.reviewer_mapping", "reviewer row does not join sealed mapping")
            mapped_rows.append({**row, "example_id": mapped["example_id"]})

    latest_ack = max(result["ack_sequence"] for result in receipt_results)
    first_consumption = min(
        result["result_consumed_sequence"] for result in receipt_results
    )
    if latest_ack >= first_consumption:
        _fail("calibration.reviewer_barrier", "a result was consumed before both spawn acknowledgements")
    return {
        "binding": pair_binding,
        "mapped_rows": mapped_rows,
        "reviewer_ids": sorted(reviewer_ids),
        "principal_ids": sorted(principal_ids),
    }
