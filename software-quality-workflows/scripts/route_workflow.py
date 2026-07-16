#!/usr/bin/env python3
"""Route validated SQW facts to one exact card or one typed boundary action."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_reference_cards import load_json


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
SURFACE_TAXONOMY_VERSION = "sqw-route-surfaces/1"
SURFACE_FAMILIES = (
    "public_contract",
    "data_state",
    "security_privacy",
    "runtime_platform",
    "dependency_supply_chain",
    "browser_ui",
    "performance_resource",
    "plugin_installed_surface",
    "migration_release",
    "workspace_vcs",
    "external_side_effect",
    "test_fixture_benchmark",
    "observability_operations",
    "concurrency_shared_state",
)
REQUIRED_FACTS = {
    "schema_version",
    "request_mode",
    "intent_status",
    "root_cause_status",
    "implicated_surfaces",
    "unknown_implicated_facts",
    "surface_assessment",
    "persistence_need",
    "delegation_need",
    "external_side_effect",
    "explicit_autonomous_closure",
}
OPTIONAL_DEFAULTS = {
    "admission_decision": "NOT_ASSESSED",
    "admission_ref": None,
}
RESULT_KEYS = {
    "schema_version",
    "route_action",
    "workflow_mode",
    "execution_policy",
    "selection_stage",
    "selected_decision_id",
    "primary_owner_id",
    "primary_card",
    "fact_projection",
    "required_artifact_projection_ids",
    "reason_codes",
    "admission_ref",
}
ENTRY_SELECTIONS = {
    "direct": ("STANDARD_CHANGE_ENTRY", "form-change-contract", "change-execution", "sqw.entry.direct-change"),
    "diagnosis": ("DIAGNOSIS_ENTRY", "establish-root-cause", "systematic-debugging", "sqw.entry.diagnose-failure"),
    "intent": ("INTENT_DISCOVERY_ENTRY", "resolve-material-intent", "intent-and-design-discovery", "sqw.entry.intent-discovery"),
    "audit": ("READ_ONLY_AUDIT_ENTRY", "perform-read-only-audit", "read-only-architecture-audits", "sqw.entry.read-only-audit"),
    "review": ("REVIEW_TIER_ENTRY", "select-review-tier", "requesting-code-review", "sqw.review.tier-selection"),
    "recovery": ("RECOVERY_ENTRY", "recover-repository-state", "merge-conflict-resolution", "sqw.entry.recovery"),
}


class RouteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str


def _string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RouteError("ROUTE_FACTS_INVALID", f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise RouteError("ROUTE_FACTS_INVALID", f"{field} must not contain duplicates")
    return value


def _validate_surface_assessment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "surface_assessment must be an object")
    expected_keys = {"taxonomy_version", "coverage", "assessed_families", "evidence_refs"}
    if set(value) != expected_keys:
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "surface_assessment must contain the exact coverage keys")
    families = _string_list(value["assessed_families"], field="surface_assessment.assessed_families")
    evidence = _string_list(value["evidence_refs"], field="surface_assessment.evidence_refs")
    if (
        value["taxonomy_version"] != SURFACE_TAXONOMY_VERSION
        or value["coverage"] != "complete"
        or families != list(SURFACE_FAMILIES)
        or not evidence
    ):
        raise RouteError(
            "ROUTE_FACTS_INCOMPLETE",
            "surface assessment taxonomy, ordered coverage, or evidence is incomplete",
        )
    return value


def _validated_facts(raw_facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_facts, dict):
        raise RouteError("ROUTE_INPUT_INVALID", "route facts must be an object")
    if not raw_facts:
        raise RouteError("ROUTE_INPUT_INCOMPLETE", "route facts must not be empty")
    allowed = REQUIRED_FACTS | set(OPTIONAL_DEFAULTS)
    unknown = sorted(set(raw_facts) - allowed)
    if unknown:
        raise RouteError("ROUTE_INPUT_UNKNOWN_FIELD", f"unknown route facts: {unknown}")
    missing = sorted(REQUIRED_FACTS - set(raw_facts))
    if missing:
        raise RouteError("ROUTE_INPUT_INCOMPLETE", f"missing route facts: {missing}")
    facts = {**OPTIONAL_DEFAULTS, **raw_facts}
    if facts["schema_version"] != "1.0":
        raise RouteError("ROUTE_INPUT_INVALID", "schema_version must be 1.0")
    if facts["request_mode"] not in {"change", "report", "review", "recovery", "plan"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid request_mode: {facts['request_mode']!r}")
    if facts["intent_status"] not in {"adequate", "materially_underdefined"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid intent_status: {facts['intent_status']!r}")
    if facts["root_cause_status"] not in {"known", "unknown", "not_applicable"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid root_cause_status: {facts['root_cause_status']!r}")
    if facts["persistence_need"] not in {"none", "trace", "durable"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid persistence_need: {facts['persistence_need']!r}")
    if facts["delegation_need"] not in {"none", "read", "write"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid delegation_need: {facts['delegation_need']!r}")
    if facts["external_side_effect"] not in {"none", "authorized", "unauthorized", "irreversible"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid external_side_effect: {facts['external_side_effect']!r}")
    if not isinstance(facts["explicit_autonomous_closure"], bool):
        raise RouteError("ROUTE_INPUT_INVALID", "explicit_autonomous_closure must be boolean")
    if facts["admission_decision"] not in {"NOT_ASSESSED", "DIRECT_SELECTED", "CLOSURE_ELIGIBLE", "TERMINAL"}:
        raise RouteError("ROUTE_INPUT_INVALID", f"invalid admission_decision: {facts['admission_decision']!r}")
    if facts["admission_ref"] is not None and (not isinstance(facts["admission_ref"], str) or not facts["admission_ref"]):
        raise RouteError("ROUTE_INPUT_INVALID", "admission_ref must be null or a non-empty string")
    if (facts["admission_decision"] == "NOT_ASSESSED") != (facts["admission_ref"] is None):
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "Admission decision and artifact reference must be bound together")

    _validate_surface_assessment(facts["surface_assessment"])
    implicated = _string_list(facts["implicated_surfaces"], field="implicated_surfaces")
    unknown_implicated = _string_list(facts["unknown_implicated_facts"], field="unknown_implicated_facts")
    unsupported = sorted(set(implicated) - set(SURFACE_FAMILIES))
    if unsupported:
        raise RouteError("ROUTE_INPUT_INVALID", f"unknown implicated surfaces: {unsupported}")
    detached_unknowns = [item for item in unknown_implicated if item.split(".", 1)[0] not in implicated]
    if detached_unknowns:
        raise RouteError("ROUTE_FACTS_INVALID", f"unknown facts lack an implicated surface: {detached_unknowns}")
    if unknown_implicated:
        raise RouteError("IMPLICATED_FACT_UNKNOWN", f"implicated facts remain unknown: {unknown_implicated}")
    if facts["external_side_effect"] != "none" and "external_side_effect" not in implicated:
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "external side effect status lacks an implicated surface")
    return facts


def _card(card_id: str, root: Path = ROOT) -> dict[str, Any]:
    manifest = load_json(root / "registries" / "reference-cards.manifest.json")
    matches = [item for item in manifest.get("cards", []) if item.get("card_id") == card_id]
    if len(matches) != 1:
        raise RouteError("ROUTE_CARD_UNAVAILABLE", f"manifest does not contain exactly one {card_id}")
    item = matches[0]
    return {key: item[key] for key in ("card_id", "path", "sha256", "bytes")}


def _fact_projection(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_mode": facts["request_mode"],
        "root_cause_status": facts["root_cause_status"],
        "implicated_surfaces": facts["implicated_surfaces"],
    }


def _workflow_mode(facts: dict[str, Any]) -> str:
    if facts["persistence_need"] == "durable" or facts["delegation_need"] != "none":
        return "M2_SPARSE"
    if facts["persistence_need"] == "trace":
        return "M1_TRACE"
    if facts["external_side_effect"] == "authorized":
        return "M2_SPARSE"
    return "M0_DIRECT"


def _result(
    facts: dict[str, Any],
    *,
    route_action: str,
    workflow_mode: str | None,
    execution_policy: str | None,
    selection_stage: str,
    selected_decision_id: str,
    primary_owner_id: str | None,
    card_id: str | None,
    reasons: list[str],
    required_artifacts: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "route_action": route_action,
        "workflow_mode": workflow_mode,
        "execution_policy": execution_policy,
        "selection_stage": selection_stage,
        "selected_decision_id": selected_decision_id,
        "primary_owner_id": primary_owner_id,
        "primary_card": _card(card_id) if card_id else None,
        "fact_projection": _fact_projection(facts),
        "required_artifact_projection_ids": list(dict.fromkeys(required_artifacts or [])),
        "reason_codes": list(dict.fromkeys(reasons)),
        "admission_ref": facts["admission_ref"],
    }


def _entry_result(facts: dict[str, Any], selection: str, reason: str) -> dict[str, Any]:
    stage, decision_id, owner_id, card_id = ENTRY_SELECTIONS[selection]
    return _result(
        facts,
        route_action="EXECUTE",
        workflow_mode=_workflow_mode(facts),
        execution_policy="standard",
        selection_stage=stage,
        selected_decision_id=decision_id,
        primary_owner_id=owner_id,
        card_id=card_id,
        reasons=[reason],
    )


def assess(raw_facts: dict[str, Any]) -> dict[str, Any]:
    facts = _validated_facts(raw_facts)
    admission = facts["admission_decision"]
    if facts["external_side_effect"] in {"unauthorized", "irreversible"}:
        reason = "EXTERNAL_SIDE_EFFECT_UNAUTHORIZED" if facts["external_side_effect"] == "unauthorized" else "IRREVERSIBLE_AUTHORITY_REQUIRED"
        return _result(
            facts,
            route_action="EMIT_TERMINAL",
            workflow_mode=None,
            execution_policy=None,
            selection_stage="SAFETY_TERMINAL",
            selected_decision_id="reject-unsafe-side-effect",
            primary_owner_id=None,
            card_id=None,
            reasons=[reason],
        )
    if admission == "TERMINAL":
        return _result(
            facts,
            route_action="EMIT_TERMINAL",
            workflow_mode=None,
            execution_policy=None,
            selection_stage="ADMISSION_TERMINAL",
            selected_decision_id="emit-admission-terminal",
            primary_owner_id=None,
            card_id=None,
            reasons=["CLOSURE_ADMISSION_TERMINAL"],
            required_artifacts=["closure-admission"],
        )
    if facts["request_mode"] == "recovery":
        return _entry_result(facts, "recovery", "REPOSITORY_RECOVERY_REQUESTED")
    if facts["root_cause_status"] == "unknown":
        return _entry_result(facts, "diagnosis", "ROOT_CAUSE_UNKNOWN")
    if facts["intent_status"] == "materially_underdefined":
        return _entry_result(facts, "intent", "MATERIAL_INTENT_UNDERDEFINED")
    if facts["request_mode"] == "report":
        return _entry_result(facts, "audit", "READ_ONLY_REQUEST")
    if facts["request_mode"] == "review":
        return _entry_result(facts, "review", "REVIEW_REQUESTED")
    if admission == "CLOSURE_ELIGIBLE":
        return _result(
            facts,
            route_action="EXECUTE",
            workflow_mode=None,
            execution_policy="autonomous_closure",
            selection_stage="CLOSURE_COMPILE_HANDOFF",
            selected_decision_id="compile-closure-contract",
            primary_owner_id="writing-plans",
            card_id=None,
            reasons=["CLOSURE_CONTRACT_REQUIRED"],
            required_artifacts=["closure-admission"],
        )
    if facts["explicit_autonomous_closure"] and admission == "NOT_ASSESSED":
        return _result(
            facts,
            route_action="ASSESS_CLOSURE",
            workflow_mode=None,
            execution_policy=None,
            selection_stage="CLOSURE_ADMISSION",
            selected_decision_id="assess-closure",
            primary_owner_id=None,
            card_id=None,
            reasons=["AUTONOMOUS_CLOSURE_REQUESTED"],
        )
    if facts["request_mode"] == "plan":
        return _result(
            facts,
            route_action="EXECUTE",
            workflow_mode=None,
            execution_policy="standard",
            selection_stage="PLAN_ROUTE_HANDOFF",
            selected_decision_id="select-plan-profile",
            primary_owner_id="writing-plans",
            card_id=None,
            reasons=["PLAN_ROUTE_REQUIRED"],
            required_artifacts=["plan-route-facts"],
        )
    direct_reason = "CLOSURE_DIRECT_SELECTED" if admission == "DIRECT_SELECTED" else "ROUTINE_LOCAL_CHANGE"
    return _entry_result(facts, "direct", direct_reason)


def validate_route_result(result: Any, root: Path = ROOT) -> list[Violation]:
    violations: list[Violation] = []
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        return [Violation("route.shape", "/", "result must contain the exact route keys")]
    if result.get("route_action") not in {"EXECUTE", "ASSESS_CLOSURE", "EMIT_TERMINAL"}:
        violations.append(Violation("route.action", "/route_action", "unknown route action"))
    if result.get("workflow_mode") not in {None, "M0_DIRECT", "M1_TRACE", "M2_SPARSE", "M3_FULL"}:
        violations.append(Violation("route.workflow-mode", "/workflow_mode", "invalid workflow mode"))
    if result.get("execution_policy") not in {None, "standard", "autonomous_closure"}:
        violations.append(Violation("route.execution-policy", "/execution_policy", "invalid execution policy"))
    card = result.get("primary_card")
    if card is not None:
        if not isinstance(card, dict) or set(card) != {"card_id", "path", "sha256", "bytes"}:
            violations.append(Violation("route.card-shape", "/primary_card", "invalid card transport ref"))
        else:
            try:
                expected = _card(card["card_id"], root)
            except (OSError, TypeError, ValueError):
                expected = None
            if card != expected:
                violations.append(Violation("route.card-identity", "/primary_card", "card identity differs from manifest"))
    if result.get("route_action") in {"ASSESS_CLOSURE", "EMIT_TERMINAL"} and card is not None:
        violations.append(Violation("route.card-forbidden", "/primary_card", "boundary action cannot select a card"))
    if not isinstance(result.get("fact_projection"), dict) or set(result["fact_projection"]) != {"request_mode", "root_cause_status", "implicated_surfaces"}:
        violations.append(Violation("route.fact-projection", "/fact_projection", "invalid bounded fact projection"))
    for field in ("required_artifact_projection_ids", "reason_codes"):
        value = result.get(field)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))
        ):
            violations.append(Violation("route.list-shape", f"/{field}", "must be a unique non-empty string list"))

    action = result.get("route_action")
    mode = result.get("workflow_mode")
    policy = result.get("execution_policy")
    owner = result.get("primary_owner_id")
    stage = result.get("selection_stage")
    artifacts = result.get("required_artifact_projection_ids")
    admission_ref = result.get("admission_ref")
    if action == "ASSESS_CLOSURE":
        if any(value is not None for value in (mode, policy, owner, card, admission_ref)) or artifacts != [] or stage != "CLOSURE_ADMISSION":
            violations.append(Violation("route.closure-assessment", "/", "closure assessment must be pre-workflow and card-free"))
    elif action == "EMIT_TERMINAL":
        if any(value is not None for value in (mode, policy, owner, card)):
            violations.append(Violation("route.terminal-shape", "/", "terminal action cannot create workflow selection"))
        if admission_ref is None and artifacts not in ([], None):
            violations.append(Violation("route.terminal-binding", "/admission_ref", "unbound terminal cannot project Admission"))
        if admission_ref is not None and artifacts != ["closure-admission"]:
            violations.append(Violation("route.terminal-binding", "/required_artifact_projection_ids", "Admission terminal must project its artifact"))
    elif action == "EXECUTE":
        if card is not None:
            if mode is None or policy != "standard" or not isinstance(owner, str) or not owner or artifacts != []:
                violations.append(Violation("route.card-execution", "/", "local card execution requires standard policy, mode, owner, and no boundary artifact"))
        elif stage == "PLAN_ROUTE_HANDOFF":
            if mode is not None or policy != "standard" or owner != "writing-plans" or artifacts != ["plan-route-facts"] or admission_ref is not None:
                violations.append(Violation("route.plan-handoff", "/", "plan handoff binding is invalid"))
        elif stage == "CLOSURE_COMPILE_HANDOFF":
            if mode is not None or policy != "autonomous_closure" or owner != "writing-plans" or artifacts != ["closure-admission"] or admission_ref is None:
                violations.append(Violation("route.closure-handoff", "/", "closure compile handoff binding is invalid"))
        else:
            violations.append(Violation("route.card-missing", "/primary_card", "EXECUTE requires a local card or registered handoff stage"))
    return violations


def _read_input(path: str) -> dict[str, Any]:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise RouteError("ROUTE_INPUT_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise RouteError("ROUTE_INPUT_INVALID", "route input must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts", type=str)
    args = parser.parse_args(argv)
    try:
        result = assess(_read_input(args.facts))
    except (OSError, RouteError, ValueError) as exc:
        code = exc.code if isinstance(exc, RouteError) else "ROUTE_INPUT_INVALID"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(exc)}}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
