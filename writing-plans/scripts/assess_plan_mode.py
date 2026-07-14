#!/usr/bin/env python3
"""Select the lightest writing-plans route/profile from observable facts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

DEFAULTS: dict[str, Any] = {
    "explicit_plan_request": False,
    "same_session_execution": True,
    "root_cause_status": "not_applicable",
    "intent_status": "defined",
    "autonomous_closure_admission": "not_requested",
    "durable_handoff": False,
    "public_contract": False,
    "migration_or_rollback": False,
    "resume_required": False,
    "external_side_effect": False,
    "independent_write_slices": 0,
    "strategy_family_count": 1,
    "long_corpus_only": False,
    "copy_paste_projection_requested": False,
    "disposable_spike": False,
}

BOOLEAN_OR_NULL_FACTS = {
    "explicit_plan_request",
    "same_session_execution",
    "durable_handoff",
    "public_contract",
    "migration_or_rollback",
    "resume_required",
    "external_side_effect",
    "long_corpus_only",
    "copy_paste_projection_requested",
    "disposable_spike",
}
ROOT_CAUSE_STATUSES = {"known", "unknown", "not_applicable"}
INTENT_STATUSES = {"defined", "materially_underdefined", "low_risk_defaults_available"}
ADMISSION_STATUSES = {"not_requested", "eligible", "ineligible", "terminal"}


def _result(
    route: str,
    profile: str | None,
    reasons: list[str],
    *,
    execution_policy: str = "standard",
    primary_reference: str | None = None,
    required: list[str] | None = None,
    optional: list[str] | None = None,
    must_not_load: list[str] | None = None,
    required_artifacts: list[str] | None = None,
    handoff_owner: str | None = None,
    terminal_status: str | None = None,
    projection: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "route": route,
        "profile": profile,
        "execution_policy": execution_policy,
        "primary_reference": primary_reference,
        "required_references": required or [],
        "optional_references": optional or [],
        "must_not_load": must_not_load or [],
        "reason_codes": reasons,
        "required_artifacts": required_artifacts or [],
        "handoff_owner": handoff_owner,
        "terminal_status": terminal_status,
        "forbidden_assumptions": [
            "root-cause rediscovery is part of implementation",
            "VCS publication or external execution is authorized",
            "autonomous closure may pause for a mid-run user answer",
        ],
    }
    if projection:
        result["projection"] = projection
    return result


def _validated_facts(raw: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown route facts: {unknown}")
    facts = {**DEFAULTS, **raw}
    for field in BOOLEAN_OR_NULL_FACTS:
        value = facts[field]
        if value is not None and not isinstance(value, bool):
            raise ValueError(f"{field} must be true, false, or null")
    for field, allowed in (
        ("root_cause_status", ROOT_CAUSE_STATUSES),
        ("intent_status", INTENT_STATUSES),
        ("autonomous_closure_admission", ADMISSION_STATUSES),
    ):
        if facts[field] not in allowed:
            raise ValueError(f"invalid {field}: {facts[field]!r}")
    for field, minimum in (("independent_write_slices", 0), ("strategy_family_count", 1)):
        value = facts[field]
        if type(value) is not int or value < minimum:
            raise ValueError(f"{field} must be an integer >= {minimum}")
    return facts


def _program_references(facts: dict[str, Any], *, closure: bool) -> list[str]:
    references = [
        "references/plan-profiles.md",
        "references/plan-state-contract.md",
        "references/implementation-slicing-and-context-capsules.md",
    ]
    if closure:
        references.append("references/closure-contract.md")
    if facts["migration_or_rollback"] is True:
        references.append("references/deprecation-migration-plans.md")
    if facts["public_contract"] is True:
        references.append("references/architecture-decision-records.md")
    if closure and facts["strategy_family_count"] > 1:
        references.append("references/design-audit-compression-ledger.md")
    return references


def _budget_reasons(references: list[str]) -> list[str]:
    return [f"reference_budget_exception:{reference}" for reference in references[5:]]


def assess(raw: dict[str, Any]) -> dict[str, Any]:
    facts = _validated_facts(raw)
    no_closure = ["references/closure-contract.md", "references/design-audit-compression-ledger.md"]
    if facts["long_corpus_only"] is True:
        return _result(
            "long-document",
            None,
            ["long_corpus_owner"],
            must_not_load=no_closure,
            handoff_owner="long-document-segmented-writing",
        )
    if facts["root_cause_status"] == "unknown":
        diagnosis = "software-quality-workflows/references/systematic-debugging.md"
        return _result(
            "sqw-diagnosis",
            None,
            ["root_cause_unknown"],
            primary_reference=diagnosis,
            required=[diagnosis],
            must_not_load=no_closure,
            handoff_owner="software-quality-workflows",
        )
    if facts["disposable_spike"] is True:
        return _result(
            "spike",
            None,
            ["disposable_spike"],
            primary_reference="references/spike.md",
            required=["references/spike.md"],
            must_not_load=["references/closure-contract.md"],
            required_artifacts=["spike_verdict"],
        )
    if facts["intent_status"] == "materially_underdefined":
        intent = "software-quality-workflows/references/intent-and-design-discovery.md"
        return _result(
            "sqw-intent",
            None,
            ["material_intent_underdefined"],
            primary_reference=intent,
            required=[intent],
            must_not_load=["references/closure-contract.md"],
            handoff_owner="software-quality-workflows",
        )
    admission = facts["autonomous_closure_admission"]
    if admission == "terminal":
        return _result(
            "terminal",
            None,
            ["closure_admission_terminal"],
            must_not_load=no_closure,
            terminal_status="admission_terminal",
        )
    unknown_boolean_facts = sorted(field for field in BOOLEAN_OR_NULL_FACTS if facts[field] is None)
    if unknown_boolean_facts:
        return _result(
            "terminal",
            None,
            ["route_fact_unknown"],
            must_not_load=no_closure,
            terminal_status="insufficient_route_facts",
        )
    if admission == "ineligible":
        safe_direct = facts["same_session_execution"] is True and all(
            facts[field] is False
            for field in ("explicit_plan_request", "durable_handoff", "public_contract", "migration_or_rollback", "resume_required", "external_side_effect", "copy_paste_projection_requested")
        ) and facts["independent_write_slices"] <= 1
        if safe_direct:
            return _result("direct", None, ["closure_ineligible_direct_fallback"], must_not_load=no_closure)
        return _result(
            "terminal",
            None,
            ["closure_ineligible"],
            must_not_load=no_closure,
            terminal_status="closure_ineligible",
        )
    if admission == "eligible":
        required = _program_references(facts, closure=True)
        reasons = ["closure_eligible"]
        if facts["intent_status"] == "low_risk_defaults_available":
            reasons.append("low_risk_defaults")
        if facts["strategy_family_count"] > 1:
            reasons.append("multiple_strategy_families")
        for field in ("public_contract", "migration_or_rollback", "external_side_effect", "resume_required"):
            if facts[field] is True:
                reasons.append(field)
        reasons.extend(_budget_reasons(required))
        return _result(
            "writing-plans",
            "program",
            reasons,
            execution_policy="autonomous_closure",
            primary_reference="references/closure-contract.md",
            required=required,
            required_artifacts=["closure_contract", "program_plan"],
            handoff_owner="software-quality-workflows",
        )
    program_reasons = [
        field
        for field in ("public_contract", "migration_or_rollback", "external_side_effect", "resume_required")
        if facts[field] is True
    ]
    if program_reasons:
        required = _program_references(facts, closure=False)
        return _result(
            "writing-plans",
            "program",
            program_reasons + _budget_reasons(required),
            primary_reference="references/plan-profiles.md",
            required=required,
            required_artifacts=["program_plan"],
            handoff_owner="software-quality-workflows",
        )

    handoff_reasons: list[str] = []
    if facts["same_session_execution"] is False:
        handoff_reasons.append("cross_context_handoff")
    if facts["durable_handoff"] is True:
        handoff_reasons.append("durable_handoff")
    if facts["independent_write_slices"] > 1:
        handoff_reasons.append("independent_write_slices")
    if facts["copy_paste_projection_requested"] is True:
        handoff_reasons.append("novice_projection_requested")
    if handoff_reasons:
        return _result(
            "writing-plans",
            "handoff",
            handoff_reasons,
            primary_reference="references/plan-profiles.md",
            required=["references/plan-profiles.md", "references/implementation-slicing-and-context-capsules.md"],
            required_artifacts=["plan_handoff"],
            handoff_owner="software-quality-workflows",
            projection="novice_executable" if facts["copy_paste_projection_requested"] is True else None,
        )
    if facts["explicit_plan_request"] is True:
        return _result(
            "writing-plans",
            "brief",
            ["explicit_plan_request"],
            primary_reference="references/plan-profiles.md",
            required=["references/plan-profiles.md"],
            required_artifacts=["brief_plan"],
            handoff_owner="software-quality-workflows",
        )
    return _result("direct", None, ["routine_direct_path"], must_not_load=no_closure)


def _read_input(path: str) -> dict[str, Any]:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("route input must be a JSON object")
    unknown = sorted(set(value) - set(DEFAULTS))
    if unknown:
        raise ValueError(f"unknown route facts: {unknown}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="JSON file or - for stdin")
    args = parser.parse_args(argv)
    try:
        result = assess(_read_input(args.input))
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
