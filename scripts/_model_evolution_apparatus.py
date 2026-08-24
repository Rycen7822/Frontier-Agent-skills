#!/usr/bin/env python3
"""Versioned outcome-free transport retry and budget contract."""

from __future__ import annotations

from copy import deepcopy
from math import sqrt
from pathlib import Path, PurePosixPath
import re
from statistics import NormalDist
from typing import Any

from _model_evolution_contract import (
    ContractError,
    SAFE_ID,
    SKILL_IDS,
    content_hash,
    load_json,
    load_jsonl,
    validate_document,
)


POLICY_ROLES = ("target_current", "target_prior", "target_holdout")
INCOMPLETE_COMMAND = re.compile(
    r"^Codex stream has incomplete items: stdout record [1-9][0-9]* "
    r"\(item\.started/command_execution\)$"
)


def _count(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} is invalid")
    return value


def derive_retry_budget(
    *,
    valid_statistical_samples: int,
    observed_failures: int,
    observed_transport_attempts: int,
    confidence_level: float,
    campaign_exhaustion_tail: float,
    calibration_attempts: int,
    probe_attempt_ceiling: int,
) -> dict[str, Any]:
    """Derive retry limits from the bounded pilot and full campaign scale."""
    samples = _count(valid_statistical_samples, "valid statistical samples", minimum=1)
    failures = _count(observed_failures, "observed failures")
    trials = _count(observed_transport_attempts, "observed attempts", minimum=1)
    calibration = _count(calibration_attempts, "calibration attempts")
    probes = _count(probe_attempt_ceiling, "probe attempt ceiling")
    if failures > trials:
        raise ContractError("observed failures exceed attempts")
    if not 0.5 < confidence_level < 1.0:
        raise ContractError("confidence level is invalid")
    if not 0.0 < campaign_exhaustion_tail < 0.5:
        raise ContractError("campaign exhaustion tail is invalid")

    rate = failures / trials
    z = NormalDist().inv_cdf(confidence_level)
    denominator = 1.0 + z * z / trials
    center = (rate + z * z / (2.0 * trials)) / denominator
    radius = z * sqrt(
        rate * (1.0 - rate) / trials + z * z / (4.0 * trials * trials)
    ) / denominator
    upper = center + radius

    max_attempts = 1
    while samples * upper**max_attempts > campaign_exhaustion_tail:
        max_attempts += 1

    # P(F <= r before `samples` successes) under the conservative failure bound.
    probability = (1.0 - upper) ** samples
    cumulative = probability
    reserve = 0
    target = 1.0 - campaign_exhaustion_tail
    while cumulative < target:
        probability *= (samples + reserve) * upper / (reserve + 1)
        reserve += 1
        cumulative += probability

    execute = samples + reserve
    model_grade = execute + calibration
    provider = execute + model_grade + probes
    return {
        "observed_rate": rate,
        "wilson_upper_bound": upper,
        "max_attempts_per_entry": max_attempts,
        "campaign_apparatus_reserve": reserve,
        "campaign_reserve_cdf": cumulative,
        "per_entry_exhaustion_union_bound": samples * upper**max_attempts,
        "execute_request_ceiling": execute,
        "model_grade_request_ceiling": model_grade,
        "provider_request_ceiling": provider,
    }


def validate_apparatus_retry_policy(value: Any) -> dict[str, Any]:
    """Validate schema plus the policy's recomputable statistical derivation."""
    policy = validate_document(value, "apparatus_retry_policy")
    if policy["scope"]["roles"] != list(POLICY_ROLES):
        raise ContractError("apparatus retry policy roles differ")
    if policy["scope"]["skills"] != list(SKILL_IDS):
        raise ContractError("apparatus retry policy skills differ")
    if policy["scope"]["treatments"] != "all_registered_treatments":
        raise ContractError("apparatus retry policy treatment scope differs")
    expected_predicate = {
        "terminal_status": "protocol_error",
        "protocol_error_kind": "malformed_record",
        "message_contract": "incomplete_item.started_command_execution",
        "usage_records": "empty",
        "complete_result": False,
        "timeout": False,
        "refusal": False,
        "treatment_error": None,
    }
    if policy["recoverable_failure"] != expected_predicate:
        raise ContractError("recoverable apparatus predicate differs")

    observation = policy["observation"]
    design = policy["design"]
    budget = policy["request_budget"]
    derived = derive_retry_budget(
        valid_statistical_samples=design["valid_statistical_samples"],
        observed_failures=observation["matching_failures"],
        observed_transport_attempts=observation["transport_attempts"],
        confidence_level=design["confidence_level"],
        campaign_exhaustion_tail=design["campaign_exhaustion_tail"],
        calibration_attempts=budget["calibration_attempt_ceiling"],
        probe_attempt_ceiling=budget["probe_attempt_ceiling"],
    )
    exact = {
        "max_attempts": derived["max_attempts_per_entry"],
        "retryable_apparatus_classes": ["official_transient"],
        "backoff_seconds": 0,
    }
    if policy["runner_attempt_policy"] != exact:
        raise ContractError("runner attempt policy differs from derivation")
    expected_budget = {
        "valid_statistical_samples": design["valid_statistical_samples"],
        "apparatus_attempt_reserve": derived["campaign_apparatus_reserve"],
        "execute_request_ceiling": derived["execute_request_ceiling"],
        "calibration_request_count": budget["calibration_request_count"],
        "calibration_attempt_ceiling": budget["calibration_attempt_ceiling"],
        "model_grade_request_ceiling": derived["model_grade_request_ceiling"],
        "probe_request_count": budget["probe_request_count"],
        "probe_attempt_ceiling": budget["probe_attempt_ceiling"],
        "provider_request_ceiling": derived["provider_request_ceiling"],
        "reviewer_ceiling": 0,
    }
    if budget != expected_budget:
        raise ContractError("apparatus request budget differs from derivation")
    for field in (
        "observed_rate",
        "wilson_upper_bound",
        "campaign_reserve_cdf",
        "per_entry_exhaustion_union_bound",
    ):
        if abs(policy["derivation"][field] - derived[field]) > 1e-15:
            raise ContractError(f"apparatus derivation differs at {field}")
    return policy


def materialized_attempt_policy(policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the common runner policy without mutating the bound document."""
    if policy is None:
        return None
    return deepcopy(validate_apparatus_retry_policy(policy)["runner_attempt_policy"])


def validate_outcome_free_incomplete_command(
    value: Any, *, entry_ordinal: int, attempt: int
) -> dict[str, Any]:
    """Accept only the exact D18 outcome-free malformed Host terminal."""
    if not isinstance(value, dict):
        raise ContractError("Host result must be an object")
    envelope = value.get("envelope")
    protocol_error = value.get("protocol_error")
    usage = value.get("usage")
    context = value.get("context")
    cleanup = value.get("cleanup")
    if (
        value.get("record_type") != "skill-evaluator-host-result/2"
        or value.get("terminal") is not True
        or value.get("terminal_status") != "protocol_error"
        or not isinstance(envelope, dict)
        or envelope.get("entry_ordinal") != entry_ordinal
        or envelope.get("attempt") != attempt
        or envelope.get("request_kind") != "execute_case"
        or not isinstance(protocol_error, dict)
        or protocol_error.get("kind") != "malformed_record"
        or not isinstance(protocol_error.get("message"), str)
        or INCOMPLETE_COMMAND.fullmatch(protocol_error["message"]) is None
        or not isinstance(usage, dict)
        or usage.get("records") != []
        or not isinstance(context, dict)
        or context.get("bytes") != 0
        or not isinstance(cleanup, dict)
        or cleanup.get("status") != "clean"
        or value.get("timeout") is not False
        or value.get("refusal") is not False
        or value.get("treatment_error") is not None
        or any(
            value.get(field) != []
            for field in (
                "actions",
                "artifacts",
                "assertions",
                "handoffs",
                "principals",
                "state",
            )
        )
    ):
        raise ContractError("Host result is not an outcome-free incomplete command")
    entry_id = envelope.get("entry_id")
    request_id = envelope.get("request_id")
    if (
        not isinstance(entry_id, str)
        or SAFE_ID.fullmatch(entry_id) is None
        or not isinstance(request_id, str)
        or SAFE_ID.fullmatch(request_id) is None
    ):
        raise ContractError("Host result request identity is invalid")
    return value


def project_transport_sequence(
    events: list[dict[str, Any]], *, max_attempts: int, apparatus_reserve: int
) -> dict[str, Any]:
    """Project a prefix of valid samples and exact outcome-free failures."""
    max_attempts = _count(max_attempts, "max attempts", minimum=1)
    apparatus_reserve = _count(apparatus_reserve, "apparatus reserve")
    expected_ordinal = 0
    expected_attempt = 1
    requests: set[str] = set()
    failures = 0
    terminal_reason = None
    for event in events:
        if terminal_reason is not None:
            raise ContractError("transport events continue after a terminal limit")
        ordinal = _count(event.get("entry_ordinal"), "entry ordinal")
        attempt = _count(event.get("attempt"), "attempt", minimum=1)
        request_id = event.get("request_id")
        if ordinal != expected_ordinal or attempt != expected_attempt:
            raise ContractError("transport events are not an execution-order prefix")
        if not isinstance(request_id, str) or SAFE_ID.fullmatch(request_id) is None:
            raise ContractError("transport request identity is invalid")
        if request_id in requests:
            raise ContractError("transport request identity is duplicated")
        requests.add(request_id)
        if event.get("valid") is True:
            expected_ordinal += 1
            expected_attempt = 1
            continue
        if event.get("valid") is not False:
            raise ContractError("transport event validity is invalid")
        validate_outcome_free_incomplete_command(
            event.get("host_result"), entry_ordinal=ordinal, attempt=attempt
        )
        failures += 1
        if failures >= apparatus_reserve:
            terminal_reason = "campaign_apparatus_reserve_exhausted"
        elif attempt >= max_attempts:
            terminal_reason = "entry_attempt_ceiling_exhausted"
        else:
            expected_attempt += 1
    return {
        "valid_statistical_samples": expected_ordinal,
        "apparatus_attempts": failures,
        "request_identities": len(requests),
        "next_entry_ordinal": expected_ordinal,
        "next_attempt": None if terminal_reason else expected_attempt,
        "terminal_reason": terminal_reason,
    }


def audit_plan_transport(
    plan_path: Path, index_path: Path, policy: dict[str, Any]
) -> dict[str, Any]:
    """Verify indexed receipts as one natural-order transport prefix."""
    policy = validate_apparatus_retry_policy(policy)
    plan = load_json(plan_path, label="execution plan")
    if not isinstance(plan, dict):
        raise ContractError("execution plan must be an object")
    execute_entries = [
        entry
        for entry in plan.get("entries", [])
        if entry.get("disposition") == "execute"
    ]
    expected_attempt_policy = policy["runner_attempt_policy"]
    if any(
        entry.get("attempt_policy") != expected_attempt_policy
        for entry in execute_entries
    ):
        raise ContractError("plan attempt policy differs from campaign policy")
    if not index_path.exists():
        rows: list[Any] = []
    else:
        indexed = load_jsonl(index_path, label="run index")
        header, *rows = indexed
        if (
            not isinstance(header, dict)
            or header.get("record_type") != "index_header"
            or header.get("plan_id") != plan.get("plan_id")
            or header.get("plan_digest") != content_hash(plan_path.read_bytes())
        ):
            raise ContractError("run index header differs from plan")
    artifacts_root = plan_path.parent / plan["artifacts"]["root"]
    entry_position = 0
    next_attempt = 1
    requests: set[str] = set()
    failures = 0
    terminal_reason = None
    for row in rows:
        if terminal_reason is not None:
            raise ContractError("run index continues after a terminal limit")
        if entry_position >= len(execute_entries) or not isinstance(row, dict):
            raise ContractError("run index exceeds the execute plan")
        entry = execute_entries[entry_position]
        if row.get("entry_id") != entry.get("entry_id"):
            raise ContractError("run index is not an execution-order prefix")
        relative = PurePosixPath(str(row.get("artifact_dir", "")))
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            raise ContractError("run artifact path is unsafe")
        attempt_root = artifacts_root.joinpath(*relative.parts)
        receipt_path = attempt_root / "receipt.json"
        receipt_ref = row.get("receipt")
        if (
            not isinstance(receipt_ref, dict)
            or receipt_ref.get("path") != f"{relative.as_posix()}/receipt.json"
            or receipt_ref.get("digest") != content_hash(receipt_path.read_bytes())
        ):
            raise ContractError("indexed receipt binding differs")
        receipt = load_json(receipt_path, label="attempt receipt")
        run = receipt.get("run") if isinstance(receipt, dict) else None
        ordinal = entry.get("entry_ordinal")
        if (
            not isinstance(run, dict)
            or run.get("entry_id") != entry.get("entry_id")
            or run.get("entry_ordinal") != ordinal
            or run.get("attempt") != next_attempt
            or run.get("request_id") in requests
        ):
            raise ContractError("attempt receipt identity or order differs")
        request_id = run.get("request_id")
        if not isinstance(request_id, str) or SAFE_ID.fullmatch(request_id) is None:
            raise ContractError("attempt request identity is invalid")
        requests.add(request_id)
        if run.get("valid") is True:
            entry_position += 1
            next_attempt = 1
            continue
        if (
            run.get("valid") is not False
            or run.get("error") != "official_transient"
            or run.get("terminal") != "interrupted"
            or run.get("completion_origin") != "resume_seal"
            or receipt.get("usage", {}).get("records") != []
        ):
            raise ContractError("invalid receipt is outside the retry contract")
        terminal_rows = load_jsonl(
            attempt_root / "host-stdout.jsonl", label="Host result"
        )
        if len(terminal_rows) != 1:
            raise ContractError("Host result must contain one terminal record")
        validate_outcome_free_incomplete_command(
            terminal_rows[0], entry_ordinal=ordinal, attempt=next_attempt
        )
        failures += 1
        if failures >= policy["request_budget"]["apparatus_attempt_reserve"]:
            terminal_reason = "campaign_apparatus_reserve_exhausted"
        elif next_attempt >= policy["runner_attempt_policy"]["max_attempts"]:
            terminal_reason = "entry_attempt_ceiling_exhausted"
        else:
            next_attempt += 1
    return {
        "completed_entries": entry_position,
        "indexed_attempts": len(rows),
        "apparatus_attempts": failures,
        "request_identities": len(requests),
        "next_entry_id": (
            execute_entries[entry_position]["entry_id"]
            if entry_position < len(execute_entries)
            else None
        ),
        "next_entry_ordinal": (
            execute_entries[entry_position]["entry_ordinal"]
            if entry_position < len(execute_entries)
            else None
        ),
        "next_attempt": None if terminal_reason else next_attempt,
        "terminal_reason": terminal_reason,
    }
