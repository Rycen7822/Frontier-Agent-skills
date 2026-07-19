#!/usr/bin/env python3
"""Select one Software Quality Workflows decision card or a typed boundary result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, NamedTuple

from _workflow_reference_cards import load_json, strict_json_bytes


ROOT = Path(__file__).resolve().parents[1]
RESULT_KEYS = {
    "schema_version", "route_action", "route_owner", "selected_decision_id",
    "primary_card", "required_artifact_ids", "reason_codes",
}
FACT_KEYS = {
    "schema_version", "route_phase", "request_mode", "intent_status", "root_cause_status", "implicated_surfaces",
    "unknown_implicated_facts", "surface_assessment", "persistence_need", "delegation_need",
    "external_side_effect", "pending_decision_ids", "available_artifact_ids", "completed_decision_ids",
    "just_completed_card_id", "decision_request",
}
MAPPING_KEYS = {
    "decision_id", "card_id", "priority", "required_artifact_ids", "produced_artifact_ids",
    "positive_fixture_id", "near_miss_fixture_id",
}
SURFACE_FAMILIES = [
    "public_contract", "data_state", "security_privacy", "runtime_platform", "dependency_supply_chain",
    "browser_ui", "performance_resource", "plugin_installed_surface", "migration_release", "workspace_vcs",
    "external_side_effect", "test_fixture_benchmark", "observability_operations", "concurrency_shared_state",
]


class RouteError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Violation(NamedTuple):
    code: str
    pointer: str
    message: str


def _string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RouteError("ROUTE_INPUT_INVALID", f"{field} must be an array of non-empty strings")
    return list(value)


def _validate_surface_assessment(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "taxonomy_version", "coverage", "assessed_families", "evidence_refs",
    }:
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "surface_assessment must contain the exact coverage keys")
    if value["taxonomy_version"] != "sqw-route-surfaces/1" or value["coverage"] != "complete":
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "surface assessment identity or coverage is incomplete")
    if value["assessed_families"] != SURFACE_FAMILIES:
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "surface assessment must cover every family in canonical order")
    evidence = _string_list(value["evidence_refs"], field="surface_assessment.evidence_refs")
    if not evidence or len(evidence) != len(set(evidence)):
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "surface assessment needs unique evidence refs")
    return dict(value)


def _validated_facts(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RouteError("ROUTE_INPUT_INVALID", "route facts must be an object")
    if not raw:
        raise RouteError("ROUTE_INPUT_INCOMPLETE", "route facts must not be empty")
    unknown = sorted(set(raw) - FACT_KEYS)
    if unknown:
        raise RouteError("ROUTE_INPUT_UNKNOWN_FIELD", f"unknown route facts: {unknown}")
    missing = sorted(FACT_KEYS - set(raw))
    if missing:
        raise RouteError("ROUTE_INPUT_INCOMPLETE", f"missing route facts: {missing}")
    facts = dict(raw)
    if facts["schema_version"] != "2.0":
        raise RouteError("ROUTE_INPUT_INVALID", "schema_version must be 2.0")
    if facts["route_phase"] not in {"entry", "active_queue"}:
        raise RouteError("ROUTE_INPUT_INVALID", "route_phase must be entry or active_queue")
    enums = {
        "request_mode": {"change", "report", "review", "recovery", "plan"},
        "intent_status": {"adequate", "materially_underdefined"},
        "root_cause_status": {"known", "unknown", "not_applicable"},
        "persistence_need": {"none", "trace", "durable"},
        "delegation_need": {"none", "read", "write"},
        "external_side_effect": {"none", "authorized", "unauthorized", "irreversible"},
    }
    for field, allowed in enums.items():
        if facts[field] not in allowed:
            raise RouteError("ROUTE_INPUT_INVALID", f"invalid {field}: {facts[field]!r}")
    for field in (
        "implicated_surfaces", "unknown_implicated_facts", "pending_decision_ids",
        "available_artifact_ids", "completed_decision_ids",
    ):
        facts[field] = _string_list(facts[field], field=field)
    unsupported = sorted(set(facts["implicated_surfaces"]) - set(SURFACE_FAMILIES))
    if unsupported:
        raise RouteError("ROUTE_INPUT_INVALID", f"unknown implicated surfaces: {unsupported}")
    if any(item not in facts["implicated_surfaces"] for item in facts["unknown_implicated_facts"]):
        raise RouteError("ROUTE_FACTS_INVALID", "unknown facts lack an implicated surface")
    facts["surface_assessment"] = _validate_surface_assessment(facts["surface_assessment"])
    if facts["external_side_effect"] != "none" and "external_side_effect" not in facts["implicated_surfaces"]:
        raise RouteError("ROUTE_FACTS_INCOMPLETE", "external side effect status lacks an implicated surface")
    if facts["just_completed_card_id"] is not None and not (
        isinstance(facts["just_completed_card_id"], str) and facts["just_completed_card_id"]
    ):
        raise RouteError("ROUTE_INPUT_INVALID", "just_completed_card_id must be null or a non-empty string")
    return facts


def _decision_rows(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / "registries" / "decision-card-map.json"
    if not path.is_file() or path.is_symlink():
        raise RouteError("ROUTE_MAP_INVALID", "decision-card map is missing or unsafe")
    value = load_json(path)
    if not isinstance(value, dict) or set(value) != {"schema_version", "skill_id", "skill_version", "decisions"}:
        raise RouteError("ROUTE_MAP_INVALID", "decision-card map shape is invalid")
    if (value["schema_version"], value["skill_id"], value["skill_version"]) != (
        "decision-card-map/1.0", "software-quality-workflows", "6.0.0",
    ) or not isinstance(value["decisions"], list):
        raise RouteError("ROUTE_MAP_INVALID", "decision-card map identity is invalid")
    rows = value["decisions"]
    for row in rows:
        if not isinstance(row, dict) or set(row) != MAPPING_KEYS:
            raise RouteError("ROUTE_MAP_INVALID", "decision-card mapping shape is invalid")
        if not isinstance(row["priority"], int) or isinstance(row["priority"], bool) or row["priority"] < 1:
            raise RouteError("ROUTE_MAP_INVALID", "decision priority is invalid")
        for field in ("decision_id", "card_id", "positive_fixture_id", "near_miss_fixture_id"):
            if not isinstance(row[field], str) or not row[field]:
                raise RouteError("ROUTE_MAP_INVALID", f"{field} is invalid")
        for field in ("required_artifact_ids", "produced_artifact_ids"):
            values = _string_list(row[field], field=field)
            if len(values) != len(set(values)):
                raise RouteError("ROUTE_MAP_INVALID", f"{field} contains duplicates")
    for field in ("decision_id", "card_id", "priority", "positive_fixture_id", "near_miss_fixture_id"):
        values = [row[field] for row in rows]
        if len(values) != len(set(values)):
            raise RouteError("ROUTE_MAP_INVALID", f"duplicate {field}")
    return rows


def _card(card_id: str, root: Path = ROOT) -> dict[str, Any]:
    manifest = load_json(root / "registries" / "reference-cards.manifest.json")
    matches = [card for card in manifest.get("cards", []) if card.get("card_id") == card_id]
    if len(matches) != 1:
        raise RouteError("ROUTE_CARD_UNAVAILABLE", f"manifest does not contain exactly one {card_id}")
    card = matches[0]
    return {field: card[field] for field in ("card_id", "path", "sha256", "bytes")}


def _result(
    action: str,
    *,
    owner: str | None,
    reasons: list[str],
    decision: dict[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "route_action": action,
        "route_owner": owner,
        "selected_decision_id": decision["decision_id"] if decision else None,
        "primary_card": _card(decision["card_id"], root) if decision else None,
        "required_artifact_ids": list(decision["required_artifact_ids"]) if decision else [],
        "reason_codes": list(dict.fromkeys(reasons)),
    }


def _blocked(code: str) -> dict[str, Any]:
    return _result("blocked", owner="software-quality-workflows", reasons=[code])


def _select(decision_id: str, reason: str, rows: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    row = next((item for item in rows if item["decision_id"] == decision_id), None)
    if row is None:
        raise RouteError("ROUTE_MAP_INVALID", f"entry decision is unmapped: {decision_id}")
    return _result("select_card", owner="software-quality-workflows", reasons=[reason], decision=row, root=root)


def _queue_result(facts: dict[str, Any], rows: list[dict[str, Any]], root: Path) -> dict[str, Any] | None:
    pending = list(facts["pending_decision_ids"])
    completed = list(facts["completed_decision_ids"])
    if len(pending) != len(set(pending)) or len(completed) != len(set(completed)):
        return _blocked("DECISION_DUPLICATE")
    by_decision = {row["decision_id"]: row for row in rows}
    by_card = {row["card_id"]: row for row in rows}
    request = facts["decision_request"]
    if request is not None:
        if not isinstance(request, dict) or set(request) != {
            "decision_id", "produced_by_card_id", "produced_artifact_id",
        } or not all(isinstance(value, str) and value for value in request.values()):
            return _blocked("DECISION_REQUEST_INVALID")
        producer = by_card.get(request["produced_by_card_id"])
        if (
            producer is None
            or facts["just_completed_card_id"] != request["produced_by_card_id"]
            or producer["decision_id"] not in completed
            or request["produced_artifact_id"] not in producer["produced_artifact_ids"]
            or request["produced_artifact_id"] not in facts["available_artifact_ids"]
        ):
            return _blocked("DECISION_PRODUCER_INVALID")
        pending.append(request["decision_id"])
    if not pending:
        return None
    if len(pending) != len(set(pending)):
        return _blocked("DECISION_DUPLICATE")
    if any(decision_id not in by_decision for decision_id in pending):
        return _blocked("DECISION_UNKNOWN")
    if any(decision_id in completed for decision_id in pending):
        return _blocked("DECISION_COMPLETED")
    available = set(facts["available_artifact_ids"])
    eligible = [
        by_decision[decision_id]
        for decision_id in pending
        if set(by_decision[decision_id]["required_artifact_ids"]) <= available
    ]
    if not eligible:
        return _blocked("DECISION_ARTIFACT_UNMET")
    selected = min(eligible, key=lambda row: (row["priority"], row["decision_id"]))
    return _result(
        "select_card", owner="software-quality-workflows", reasons=["PENDING_DECISION_SELECTED"],
        decision=selected, root=root,
    )


def assess(raw_facts: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    facts = _validated_facts(raw_facts)
    rows = _decision_rows(root)
    if facts["route_phase"] == "active_queue":
        return _queue_result(facts, rows, root) or _result(
            "terminal", owner=None, reasons=["ACTIVE_QUEUE_EMPTY"]
        )
    if facts["external_side_effect"] in {"unauthorized", "irreversible"}:
        reason = (
            "EXTERNAL_SIDE_EFFECT_UNAUTHORIZED"
            if facts["external_side_effect"] == "unauthorized"
            else "IRREVERSIBLE_AUTHORITY_REQUIRED"
        )
        return _result("terminal", owner=None, reasons=[reason])
    if facts["request_mode"] == "recovery":
        return _select("sqw.select.entry.recovery", "REPOSITORY_RECOVERY_REQUESTED", rows, root)
    if facts["root_cause_status"] == "unknown":
        return _select("sqw.select.entry.diagnose-failure", "ROOT_CAUSE_UNKNOWN", rows, root)
    if facts["intent_status"] == "materially_underdefined":
        return _select("sqw.select.entry.intent-discovery", "MATERIAL_INTENT_UNDERDEFINED", rows, root)
    if facts["request_mode"] == "report":
        return _select("sqw.select.entry.read-only-audit", "READ_ONLY_REQUEST", rows, root)
    if facts["request_mode"] == "review":
        return _select("sqw.select.entry.read-only-audit", "REVIEW_ENTRY_REQUIRED", rows, root)
    if facts["request_mode"] == "plan":
        return _result("handoff", owner="writing-plans", reasons=["PLAN_ROUTE_REQUIRED"])
    queued = _queue_result(facts, rows, root)
    if queued is not None:
        return queued
    return _select("sqw.select.entry.direct-change", "ROUTINE_LOCAL_CHANGE", rows, root)


def validate_route_result(result: Any, root: Path = ROOT) -> list[Violation]:
    issues: list[Violation] = []
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        return [Violation("route.shape", "/", "result keys are not exact")]
    action = result.get("route_action")
    decision_id = result.get("selected_decision_id")
    card = result.get("primary_card")
    if action == "select_card":
        if not isinstance(decision_id, str) or not isinstance(card, dict):
            issues.append(Violation("route.selection", "/", "selection requires one decision and card"))
        else:
            try:
                row = next(item for item in _decision_rows(root) if item["decision_id"] == decision_id)
                if card != _card(row["card_id"], root):
                    issues.append(Violation("route.card", "/primary_card", "selected card identity is stale"))
            except (RouteError, StopIteration):
                issues.append(Violation("route.decision", "/selected_decision_id", "decision is not mapped"))
    elif decision_id is not None or card is not None:
        issues.append(Violation("route.boundary", "/", "boundary result cannot select a card"))
    if not isinstance(result.get("reason_codes"), list) or not result["reason_codes"]:
        issues.append(Violation("route.reason", "/reason_codes", "at least one reason is required"))
    return issues


def _read_input(path: str) -> dict[str, Any]:
    try:
        value = strict_json_bytes(Path(path).read_bytes(), source=path)
    except (OSError, ValueError) as exc:
        raise RouteError("ROUTE_INPUT_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise RouteError("ROUTE_INPUT_INVALID", "route input must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts")
    args = parser.parse_args(argv)
    try:
        result = assess(_read_input(args.facts))
    except (OSError, ValueError, RouteError) as exc:
        code = exc.code if isinstance(exc, RouteError) else "ROUTE_INPUT_INVALID"
        print(json.dumps({"ok": False, "error": code, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
