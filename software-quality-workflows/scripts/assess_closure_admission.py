#!/usr/bin/env python3
"""Assess autonomous-closure eligibility without creating workflow state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, load_json


FACT_DEFAULTS: dict[str, Any] = {
    "autonomous_closure_requested": False,
    "intent_status": "defined",
    "machine_observable_outcome": None,
    "requirements_stable_enough": None,
    "known_requirement_conflict": False,
    "scope_freezable": None,
    "authority_freezable": None,
    "reproducible_environment": None,
    "verifier_separable": None,
    "bounded_side_effects": None,
    "resume_required": False,
    "expensive_proof_reusable": False,
    "local_repair_likely": False,
    "strategy_family_count": 1,
    "search_value": "none",
    "framework_tax": "low",
}

SAFETY_FACTS = (
    "machine_observable_outcome",
    "requirements_stable_enough",
    "scope_freezable",
    "authority_freezable",
    "reproducible_environment",
    "verifier_separable",
    "bounded_side_effects",
)
BOOLEAN_FACTS = set(SAFETY_FACTS) | {
    "autonomous_closure_requested",
    "resume_required",
    "expensive_proof_reusable",
    "local_repair_likely",
    "known_requirement_conflict",
}


def _result(
    status: str,
    *,
    reasons: list[str],
    missing: list[str] | None = None,
    actions: list[str] | None = None,
    mode: str = "M2_SPARSE",
    owner: str = "autonomous-closure",
) -> dict[str, Any]:
    return {
        "status": status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "missing_conditions": list(dict.fromkeys(missing or [])),
        "required_pre_freeze_actions": list(dict.fromkeys(actions or [])),
        "recommended_mode": mode,
        "required_primary_owner": owner,
    }


def _validated(raw_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_facts, dict):
        raise ValueError("closure admission facts must be an object")
    unknown = sorted(set(raw_facts) - set(FACT_DEFAULTS))
    if unknown:
        raise ValueError(f"unknown closure admission facts: {unknown}")
    facts = {**FACT_DEFAULTS, **raw_facts}
    for key in BOOLEAN_FACTS:
        value = facts[key]
        if key in SAFETY_FACTS:
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{key} must be boolean or null")
        elif not isinstance(value, bool):
            raise ValueError(f"{key} must be boolean")
    if facts["intent_status"] not in {"defined", "low_risk_defaults_available", "materially_underdefined"}:
        raise ValueError(f"invalid intent_status: {facts['intent_status']!r}")
    count = facts["strategy_family_count"]
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 64:
        raise ValueError("strategy_family_count must be an integer from 1 through 64")
    if facts["search_value"] not in {"none", "low", "medium", "high"}:
        raise ValueError(f"invalid search_value: {facts['search_value']!r}")
    if facts["framework_tax"] not in {"low", "medium", "high"}:
        raise ValueError(f"invalid framework_tax: {facts['framework_tax']!r}")
    return facts


def assess_admission(raw_facts: dict[str, Any]) -> dict[str, Any]:
    facts = _validated(raw_facts)

    if facts["known_requirement_conflict"]:
        return _result(
            "spec_unsat",
            reasons=["known_requirement_conflict"],
            missing=[],
            actions=["emit_spec_unsat_certificate"],
        )

    if facts["intent_status"] == "materially_underdefined":
        return _result(
            "spec_underdetermined",
            reasons=["material_intent_ambiguity"],
            missing=["intent_status"],
            actions=["emit_spec_underdetermined_certificate"],
        )

    missing_spec = [
        key for key in ("machine_observable_outcome", "requirements_stable_enough")
        if facts[key] is not True
    ]
    if missing_spec:
        return _result(
            "spec_underdetermined",
            reasons=["observable_spec_missing"],
            missing=missing_spec,
            actions=["resolve_observable_spec"],
        )

    missing_authority = [
        key for key in ("scope_freezable", "authority_freezable", "bounded_side_effects")
        if facts[key] is not True
    ]
    if missing_authority:
        return _result(
            "authority_blocked",
            reasons=["authority_or_scope_not_freezable"],
            missing=missing_authority,
            actions=["emit_authority_blocked_certificate"],
        )

    if facts["reproducible_environment"] is not True:
        return _result(
            "environment_unavailable",
            reasons=["environment_not_reproducible"],
            missing=["reproducible_environment"],
            actions=["restore_or_bind_environment"],
        )

    if facts["verifier_separable"] is not True:
        return _result(
            "verifier_unqualified_candidate",
            reasons=["verifier_not_separable"],
            missing=["verifier_separable"],
            actions=["qualify_verifier"],
        )

    benefit_reasons: list[str] = []
    value = 0
    if facts["resume_required"]:
        benefit_reasons.append("resume_required")
        value = max(value, 3)
    if facts["expensive_proof_reusable"]:
        benefit_reasons.append("expensive_proof_reusable")
        value = max(value, 3)
    if facts["local_repair_likely"]:
        benefit_reasons.append("local_repair_likely")
        value = max(value, 2)
    if facts["strategy_family_count"] >= 2 and facts["search_value"] in {"medium", "high"}:
        benefit_reasons.append("strategy_comparison_valuable")
        value = max(value, {"none": 1, "low": 1, "medium": 2, "high": 3}[facts["search_value"]])

    if not benefit_reasons:
        return _result(
            "direct_preferred",
            reasons=["no_closure_value_boundary"],
            mode="M0_DIRECT",
            owner="change-execution",
        )

    tax = {"low": 1, "medium": 2, "high": 3}[facts["framework_tax"]]
    if facts["autonomous_closure_requested"]:
        tax = max(1, tax - 1)
    if value < tax:
        return _result(
            "direct_preferred",
            reasons=benefit_reasons + ["framework_tax_exceeds_value"],
            mode="M0_DIRECT",
            owner="change-execution",
        )

    reasons = benefit_reasons
    if facts["intent_status"] == "low_risk_defaults_available":
        reasons.append("low_risk_defaults_available")
    if facts["autonomous_closure_requested"]:
        reasons.append("closure_requested")
    return _result("closure_eligible", reasons=reasons)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess_admission(load_json(args.facts))
    except (OSError, InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
