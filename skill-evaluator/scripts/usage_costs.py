"""Usage attribution. Input already includes cache reads; output may include reasoning."""

from __future__ import annotations

from typing import Any
import math

FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "queue_ms",
    "runtime_ms",
    "tool_calls",
    "retries",
)


def summarize_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for field in FIELDS:
        values = [record.get(field) for record in records]
        result[field] = None if any(value is None for value in values) else sum(values)
    total, cached = result["input_tokens"], result["cache_read_tokens"]
    if total is not None and cached is not None and cached > total:
        raise ValueError("cache reads exceed captured input tokens")
    result["uncached_input_tokens"] = (
        None if total is None or cached is None else total - cached
    )
    # A usage row can aggregate many API requests. Missing billing is not zero.
    result.update(
        captured_records=len(records), provider_requests=None, monetary_cost=None
    )
    return result


def validate_principal_identities(usage, task, judge, *, host=None, expected_role=None):
    identities = usage.get("principal_identities")
    if not isinstance(identities, list):
        raise ValueError("usage lacks principal identities")
    bound = {}
    for identity in identities:
        principal = identity["principal_id"]
        role = "task" if principal in task else "judge" if principal in judge else None
        if (
            principal in bound
            or role is None
            or identity["role"] != role
            or (expected_role and role != expected_role)
        ):
            raise ValueError("usage principal role is invalid or duplicated")
        if host is not None:
            config = host["identity"].get("execution" if role == "task" else "grading")
            if (
                not config
                or identity["model"] != config["model"]
                or identity["pricing_identity"] != config["pricing_id"]
            ):
                raise ValueError(
                    "usage model or pricing identity differs from bound role"
                )
        bound[principal] = identity
    if {r["principal_id"] for r in usage["records"]} != set(bound):
        raise ValueError("usage records and principal identities do not join exactly")
    return bound


def captured_usage(result, entry, host, *, role, grader_id=None):
    """Validate actual Host roles before attributing captured counters."""
    usage = result.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("records"), list):
        raise ValueError("Host usage is missing")
    principals = {p["principal_id"] for p in result.get("principals", [])}
    allowed = principals if role == "task" else {f"grader-{grader_id}"}
    if len(principals) != len(result.get("principals", [])):
        raise ValueError("duplicate task principal")
    config = host["identity"].get(
        "execution" if role == "task" else "grading", host["identity"]["execution"]
    )
    if host.get("schema_version") == 3:
        validate_principal_identities(
            usage,
            allowed if role == "task" else set(),
            allowed if role == "judge" else set(),
            host=host,
            expected_role=role,
        )
    elif usage.get("pricing_identity") != config["pricing_id"]:
        raise ValueError("Host usage price identity differs from role")
    turns = {turn["turn_id"] for turn in entry["execute_case_payload"]["turns"]}
    seen = set()
    for record in usage["records"]:
        identity = (
            record.get("principal_id"),
            record.get("turn_id"),
            record.get("phase"),
            record.get("call_id"),
        )
        if (
            identity in seen
            or identity[0] not in allowed
            or not identity[2]
            or not identity[3]
            or (identity[1] is not None and identity[1] not in turns)
        ):
            raise ValueError("usage record has an unbound or duplicate call")
        seen.add(identity)
        for field in FIELDS:
            value = record.get(field)
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value) or value < 0
            ):
                raise ValueError("usage counters must be finite and nonnegative")
    summary = summarize_usage(usage["records"])
    if not usage["records"]:
        summary.update({field: None for field in (*FIELDS, "uncached_input_tokens")})
    return {"role": role, **summary, "pricing_identities": [config["pricing_id"]]}


def aggregate_captured(sources, *, unknown_roles=()):
    """Aggregate only this invocation's task and judge sources; reuse costs zero."""
    unique = {source["digest"]: source["usage"] for source in sources}
    result = {}
    fields = (*FIELDS, "uncached_input_tokens", "captured_records")
    for role in ("task", "judge", "overall"):
        values = [
            value
            for value in unique.values()
            if role == "overall" or value["role"] == role
        ]
        unknown = bool(unknown_roles) if role == "overall" else role in unknown_roles
        result[role] = {}
        for field in fields:
            items = [value[field] for value in values]
            result[role][field] = (
                None if unknown or any(v is None for v in items) else sum(items)
            )
        result[role].update(
            provider_requests=None if values or unknown else 0,
            monetary_cost=None if values or unknown else 0,
            pricing_identities=sorted(
                {price for value in values for price in value["pricing_identities"]}
            ),
        )
    result.update(calibration_and_apparatus=None, outer_agent=None)
    return result
