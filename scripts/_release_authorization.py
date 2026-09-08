#!/usr/bin/env python3
"""Qualification-bound release authorization projection and validation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from _evaluation_documents import (
    ContractError,
    canonical_bytes,
    content_hash,
    parse_utc,
    validate_document,
)


AUTHORIZATION_SCHEMA_VERSION = "release-authorization/3"
QUALIFICATION_SCHEMA_VERSION = "model-qualification/3"
RELEASABLE_DECISIONS = {"qualified", "qualified_with_limits"}


GATE_IDS = (
    "apparatus",
    "identity_comparability",
    "manual_authority",
    "critical_function",
    "safety_protected",
    "routing",
    "operational_cost",
    "loop_pathology",
    "incremental_value",
    "revision",
    "statistical_support",
    "release_identity",
)


def validate_qualification(value: Any) -> dict[str, Any]:
    """Validate qualification structure, gate order, and decision."""
    qualification = validate_document(value, "qualification")
    if [gate["gate_id"] for gate in qualification["gates"]] != list(GATE_IDS):
        raise ContractError("qualification gates are not in canonical order")
    limited_gates = [
        gate["gate_id"]
        for gate in qualification["gates"]
        if gate["status"] == "limited_native_absorption"
    ]
    if limited_gates not in ([], ["incremental_value"]):
        raise ContractError("native absorption is valid only on incremental value")
    if any(
        issue["code"] != "native-capability-absorption"
        for issue in qualification["limits"]
    ):
        raise ContractError("qualification contains a non-native limit")
    limited_skills = [
        skill_id
        for skill_id, result in qualification["skills"].items()
        if result["task_behavior"] == "limited_native_absorption"
    ]
    sqw_implicit = qualification["identity"]["skills"]["software-quality-workflows"][
        "allow_implicit_invocation"
    ]
    if limited_gates:
        if (
            limited_skills != ["software-quality-workflows"]
            or sqw_implicit is not False
            or len(qualification["limits"]) != 1
            or qualification["limits"][0]["scope"] != "software-quality-workflows"
        ):
            raise ContractError("native absorption requires explicit-only SQW evidence")
    elif limited_skills or qualification["limits"]:
        raise ContractError("native absorption limit is not bound to its gate")
    if (
        derive_decision(
            qualification["gates"],
            qualification["limits"],
            qualification["blockers"],
        )
        != qualification["decision"]
    ):
        raise ContractError("qualification decision differs from ordered gates")
    return qualification


def derive_decision(
    gates: list[dict[str, Any]],
    limits: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> str:
    statuses = {gate["status"] for gate in gates}
    if blockers or statuses & {"blocked", "unobserved"}:
        return "blocked"
    if limits or "limited_native_absorption" in statuses:
        return "qualified_with_limits"
    return "qualified"


def release_projection(
    qualification: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project the exact qualification identity accepted by release tooling."""
    qualification = validate_qualification(qualification)
    decision = qualification["decision"]
    if decision not in RELEASABLE_DECISIONS:
        raise ContractError("release requires a qualified model qualification")

    identity = qualification["identity"]
    if identity["target_observed_host"] is None:
        raise ContractError("release qualification requires an observed target Host")

    observed_as_of = parse_utc(qualification["validity"]["observed_as_of"])
    valid_until = parse_utc(qualification["validity"]["valid_until"])
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ContractError("release validation time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if not observed_as_of <= current < valid_until:
        raise ContractError("model qualification is not currently valid")

    return {
        "qualification": {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "qualification_id": qualification["qualification_id"],
            "digest": content_hash(canonical_bytes(qualification)),
            "decision": decision,
        },
        "bundle_id": identity["bundle_id"],
        "bundle_version": identity["bundle_version"],
        "source_revision": identity["source_revision"],
        "source_tree_hash": identity["source_tree_hash"],
        "plugin_tree_hash": identity["plugin_tree_hash"],
        "skills": deepcopy(identity["skills"]),
        "target_observed_host": deepcopy(identity["target_observed_host"]),
        "claim": deepcopy(qualification["claim"]),
        "validity": {
            "observed_as_of": qualification["validity"]["observed_as_of"],
            "valid_until": qualification["validity"]["valid_until"],
        },
        "limits": [
            {"code": item["code"], "scope": item["scope"]}
            for item in qualification["limits"]
        ],
    }


def create_authorization(
    qualification: dict[str, Any],
    *,
    static_gate: dict[str, Any],
    authority_id: str,
    signature_attestation: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create an authorization from one currently valid qualification."""
    authority_id = authority_id.strip()
    signature_attestation = signature_attestation.strip()
    if not authority_id or not signature_attestation:
        raise ContractError(
            "release authority id and signature attestation are required"
        )
    return {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        **release_projection(qualification, now=now),
        "static_gate": deepcopy(static_gate),
        "remote_writes": False,
        "authority": {
            "authority_id": authority_id,
            "role": "release_owner",
            "decision": "approve",
            "signature_attestation": signature_attestation,
        },
    }


def validate_authorization_binding(
    authorization: dict[str, Any],
    qualification: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reject any authorization that differs from its qualification."""
    expected = release_projection(qualification, now=now)
    projected = {key: authorization.get(key) for key in expected}
    if projected != expected:
        raise ContractError("release authorization differs from its qualification")
    if authorization.get("remote_writes") is not False:
        raise ContractError("release authorization must keep remote writes disabled")
    return authorization
