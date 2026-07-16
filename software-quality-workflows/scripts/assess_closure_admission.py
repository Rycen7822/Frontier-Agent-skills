#!/usr/bin/env python3
"""Assess autonomous-closure eligibility without creating workflow state."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, load_json


FACT_FIELDS = {
    "autonomous_closure_requested",
    "intent_status",
    "machine_observable_outcome",
    "requirements_stable_enough",
    "known_requirement_conflict",
    "scope_freezable",
    "authority_freezable",
    "reproducible_environment",
    "verifier_qualification_feasible",
    "bounded_side_effects",
    "resume_required",
    "expensive_proof_reusable",
    "local_repair_likely",
    "strategy_family_count",
    "search_value",
    "framework_tax",
}

SAFETY_FACTS = (
    "machine_observable_outcome",
    "requirements_stable_enough",
    "scope_freezable",
    "authority_freezable",
    "reproducible_environment",
    "verifier_qualification_feasible",
    "bounded_side_effects",
)
BOOLEAN_FACTS = set(SAFETY_FACTS) | {
    "autonomous_closure_requested",
    "resume_required",
    "expensive_proof_reusable",
    "local_repair_likely",
    "known_requirement_conflict",
}


class AdmissionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _result(
    facts: dict[str, Any],
    decision: str,
    *,
    reasons: list[str],
    next_action: str,
    terminal_status: str | None = None,
    missing: list[str] | None = None,
    mode: str = "M2_SPARSE",
) -> dict[str, Any]:
    canonical = json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "1.0",
        "admission_id": "admission-" + sha256(canonical).hexdigest()[:20],
        "decision": decision,
        "terminal_status": terminal_status,
        "reason_codes": list(dict.fromkeys(reasons)),
        "missing_conditions": list(dict.fromkeys(missing or [])),
        "next_action": next_action,
        "recommended_execution_mode": mode,
    }


def _validated(raw_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_facts, dict):
        raise AdmissionError("ADMISSION_INPUT_INVALID", "closure admission facts must be an object")
    if not raw_facts:
        raise AdmissionError("ADMISSION_INPUT_INCOMPLETE", "closure admission facts must not be empty")
    unknown = sorted(set(raw_facts) - FACT_FIELDS)
    if unknown:
        raise AdmissionError("ADMISSION_INPUT_UNKNOWN_FIELD", f"unknown closure admission facts: {unknown}")
    missing = sorted(FACT_FIELDS - set(raw_facts))
    if missing:
        raise AdmissionError("ADMISSION_INPUT_INCOMPLETE", f"missing closure admission facts: {missing}")
    facts = dict(raw_facts)
    for key in BOOLEAN_FACTS:
        value = facts[key]
        if key in SAFETY_FACTS:
            if value is not None and not isinstance(value, bool):
                raise AdmissionError("ADMISSION_INPUT_INVALID", f"{key} must be boolean or null")
        elif not isinstance(value, bool):
            raise AdmissionError("ADMISSION_INPUT_INVALID", f"{key} must be boolean")
    if facts["intent_status"] not in {"defined", "low_risk_defaults_available", "materially_underdefined"}:
        raise AdmissionError("ADMISSION_INPUT_INVALID", f"invalid intent_status: {facts['intent_status']!r}")
    count = facts["strategy_family_count"]
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 64:
        raise AdmissionError("ADMISSION_INPUT_INVALID", "strategy_family_count must be an integer from 1 through 64")
    if facts["search_value"] not in {"none", "low", "medium", "high"}:
        raise AdmissionError("ADMISSION_INPUT_INVALID", f"invalid search_value: {facts['search_value']!r}")
    if facts["framework_tax"] not in {"low", "medium", "high"}:
        raise AdmissionError("ADMISSION_INPUT_INVALID", f"invalid framework_tax: {facts['framework_tax']!r}")
    return facts


def assess_admission(raw_facts: dict[str, Any]) -> dict[str, Any]:
    facts = _validated(raw_facts)

    if facts["known_requirement_conflict"]:
        return _result(
            facts,
            "TERMINAL",
            reasons=["KNOWN_REQUIREMENT_CONFLICT"],
            next_action="EMIT_TERMINAL",
            terminal_status="SPEC_UNSAT",
            mode="M0_DIRECT",
        )

    if facts["intent_status"] == "materially_underdefined":
        return _result(
            facts,
            "TERMINAL",
            reasons=["MATERIAL_INTENT_AMBIGUITY"],
            next_action="EMIT_TERMINAL",
            terminal_status="SPEC_UNDERDETERMINED",
            missing=["intent_status"],
            mode="M0_DIRECT",
        )

    missing_spec = [
        key for key in ("machine_observable_outcome", "requirements_stable_enough")
        if facts[key] is not True
    ]
    if missing_spec:
        return _result(
            facts,
            "TERMINAL",
            reasons=["OBSERVABLE_SPEC_MISSING"],
            next_action="EMIT_TERMINAL",
            terminal_status="SPEC_UNDERDETERMINED",
            missing=missing_spec,
            mode="M0_DIRECT",
        )

    if facts["bounded_side_effects"] is not True:
        return _result(
            facts,
            "TERMINAL",
            reasons=["SIDE_EFFECT_BOUNDARY_UNAVAILABLE"],
            next_action="EMIT_TERMINAL",
            terminal_status="SIDE_EFFECT_UNBOUNDED",
            missing=["bounded_side_effects"],
            mode="M0_DIRECT",
        )

    missing_authority = [
        key for key in ("scope_freezable", "authority_freezable")
        if facts[key] is not True
    ]
    if missing_authority:
        return _result(
            facts,
            "TERMINAL",
            reasons=["AUTHORITY_OR_SCOPE_NOT_FREEZABLE"],
            next_action="EMIT_TERMINAL",
            terminal_status="AUTHORITY_BLOCKED",
            missing=missing_authority,
            mode="M0_DIRECT",
        )

    if facts["reproducible_environment"] is not True:
        return _result(
            facts,
            "TERMINAL",
            reasons=["ENVIRONMENT_NOT_REPRODUCIBLE"],
            next_action="EMIT_TERMINAL",
            terminal_status="ENVIRONMENT_UNAVAILABLE",
            missing=["reproducible_environment"],
            mode="M0_DIRECT",
        )

    if facts["verifier_qualification_feasible"] is False:
        return _result(
            facts,
            "TERMINAL",
            reasons=["VERIFIER_QUALIFICATION_DISPROVEN"],
            next_action="EMIT_TERMINAL",
            terminal_status="VERIFIER_UNQUALIFIABLE",
            missing=["verifier_qualification_feasible"],
            mode="M0_DIRECT",
        )
    if facts["verifier_qualification_feasible"] is None:
        return _result(
            facts,
            "DIRECT_SELECTED",
            reasons=["VERIFIER_FEASIBILITY_UNCONFIRMED"],
            next_action="ROUTE_STANDARD",
            missing=["verifier_qualification_feasible"],
            mode="M0_DIRECT",
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
            facts,
            "DIRECT_SELECTED",
            reasons=["NO_CLOSURE_VALUE_BOUNDARY"],
            next_action="ROUTE_STANDARD",
            mode="M0_DIRECT",
        )

    tax = {"low": 1, "medium": 2, "high": 3}[facts["framework_tax"]]
    if facts["autonomous_closure_requested"]:
        tax = max(1, tax - 1)
    if value < tax:
        return _result(
            facts,
            "DIRECT_SELECTED",
            reasons=[reason.upper() for reason in benefit_reasons] + ["FRAMEWORK_TAX_EXCEEDS_VALUE"],
            next_action="ROUTE_STANDARD",
            mode="M0_DIRECT",
        )

    reasons = [reason.upper() for reason in benefit_reasons]
    if facts["intent_status"] == "low_risk_defaults_available":
        reasons.append("LOW_RISK_DEFAULTS_AVAILABLE")
    if facts["autonomous_closure_requested"]:
        reasons.append("CLOSURE_REQUESTED")
    reasons.extend(
        [
            "BOUNDED_LOCAL_SIDE_EFFECTS",
            "MACHINE_OBSERVABLE_OUTCOME",
            "VERIFIER_QUALIFICATION_FEASIBLE",
        ]
    )
    return _result(
        facts,
        "CLOSURE_ELIGIBLE",
        reasons=reasons,
        next_action="COMPILE_CLOSURE_CONTRACT",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", type=Path)
    args = parser.parse_args(argv)
    try:
        result = assess_admission(load_json(args.facts))
    except AdmissionError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc)}}, ensure_ascii=False, indent=2))
        return 2
    except (OSError, InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "ADMISSION_INPUT_INVALID", "message": str(exc)}}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
