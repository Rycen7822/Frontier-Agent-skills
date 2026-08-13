#!/usr/bin/env python3
"""Qualification-bound release authorization projection and validation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from _model_evolution_contract import (
    ContractError,
    canonical_bytes,
    content_hash,
    parse_utc,
)
from _model_evolution_qualification import validate_qualification


AUTHORIZATION_SCHEMA_VERSION = "release-authorization/3"
QUALIFICATION_SCHEMA_VERSION = "model-qualification/3"
RELEASABLE_DECISIONS = {"qualified", "qualified_with_limits"}


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
