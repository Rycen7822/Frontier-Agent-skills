#!/usr/bin/env python3
"""Select one Writing Plans decision card or return a typed boundary result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, NamedTuple

from _writing_reference_cards import load_json, strict_json_bytes


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"
DECISION_MAP = ROOT / "registries" / "decision-card-map.json"
RESULT_KEYS = {
    "schema_version", "route_action", "route_owner", "selected_decision_id",
    "primary_card", "required_artifact_ids", "reason_codes",
}
REQUIRED_FACT_KEYS = {
    "schema_version", "route_phase", "explicit_plan_request", "root_cause_status", "intent_status",
    "pending_decision_ids", "available_artifact_ids", "completed_decision_ids",
    "just_completed_card_id", "decision_request",
}
OPTIONAL_DEFAULTS = {
    "copy_paste_projection_requested": False,
    "disposable_spike": False,
    "durable_handoff": False,
    "external_side_effect": False,
    "independent_write_slices": 0,
    "long_corpus_only": False,
    "migration_or_rollback": False,
    "public_contract": False,
    "resume_required": False,
    "same_session_execution": True,
    "strategy_family_count": 1,
}
MAPPING_KEYS = {
    "decision_id", "card_id", "priority", "required_artifact_ids", "produced_artifact_ids",
    "positive_fixture_id", "near_miss_fixture_id",
}


class PlanRouteError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PlanRouteViolation(NamedTuple):
    code: str
    pointer: str
    message: str


def _string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", f"{field} must be an array of non-empty strings")
    return list(value)


def _validated_facts(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "plan route facts must be an object")
    if not raw:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INCOMPLETE", "plan route facts must not be empty")
    allowed = REQUIRED_FACT_KEYS | set(OPTIONAL_DEFAULTS)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise PlanRouteError("PLAN_ROUTE_INPUT_UNKNOWN_FIELD", f"unknown route facts: {unknown}")
    missing = sorted(REQUIRED_FACT_KEYS - set(raw))
    if missing:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INCOMPLETE", f"missing route facts: {missing}")
    facts = {**OPTIONAL_DEFAULTS, **raw}
    if facts["schema_version"] != "2.0":
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "schema_version must be 2.0")
    if facts["route_phase"] not in {"entry", "program_queue"}:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "route_phase must be entry or program_queue")
    for field in (
        "explicit_plan_request", "copy_paste_projection_requested", "disposable_spike", "durable_handoff",
        "external_side_effect", "long_corpus_only", "migration_or_rollback", "public_contract",
        "resume_required", "same_session_execution",
    ):
        if not isinstance(facts[field], bool):
            raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", f"{field} must be boolean")
    if facts["root_cause_status"] not in {"known", "unknown", "not_applicable"}:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "root_cause_status is invalid")
    if facts["intent_status"] not in {"defined", "materially_underdefined"}:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "intent_status is invalid")
    for field, minimum in (("independent_write_slices", 0), ("strategy_family_count", 1)):
        if isinstance(facts[field], bool) or not isinstance(facts[field], int) or facts[field] < minimum:
            raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", f"{field} must be an integer >= {minimum}")
    for field in ("pending_decision_ids", "available_artifact_ids", "completed_decision_ids"):
        facts[field] = _string_list(facts[field], field=field)
    if facts["just_completed_card_id"] is not None and not (
        isinstance(facts["just_completed_card_id"], str) and facts["just_completed_card_id"]
    ):
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "just_completed_card_id must be null or a non-empty string")
    return facts


def _decision_rows(root: Path = ROOT) -> list[dict[str, Any]]:
    path = root / "registries" / "decision-card-map.json"
    if not path.is_file() or path.is_symlink():
        raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", "decision-card map is missing or unsafe")
    value = load_json(path)
    if not isinstance(value, dict) or set(value) != {"schema_version", "skill_id", "skill_version", "decisions"}:
        raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", "decision-card map shape is invalid")
    if (value["schema_version"], value["skill_id"], value["skill_version"]) != (
        "decision-card-map/1.0", "writing-plans", "7.0.0",
    ) or not isinstance(value["decisions"], list):
        raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", "decision-card map identity is invalid")
    rows = value["decisions"]
    for row in rows:
        if not isinstance(row, dict) or set(row) != MAPPING_KEYS:
            raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", "decision-card mapping shape is invalid")
        if not isinstance(row["priority"], int) or isinstance(row["priority"], bool) or row["priority"] < 1:
            raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", "decision priority is invalid")
        for field in ("decision_id", "card_id", "positive_fixture_id", "near_miss_fixture_id"):
            if not isinstance(row[field], str) or not row[field]:
                raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", f"{field} is invalid")
        for field in ("required_artifact_ids", "produced_artifact_ids"):
            values = _string_list(row[field], field=field)
            if len(values) != len(set(values)):
                raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", f"{field} contains duplicates")
    for field in ("decision_id", "card_id", "priority", "positive_fixture_id", "near_miss_fixture_id"):
        values = [row[field] for row in rows]
        if len(values) != len(set(values)):
            raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", f"duplicate {field}")
    return rows


def _card(card_id: str, root: Path = ROOT) -> dict[str, Any]:
    manifest = load_json(root / "registries" / "reference-cards.manifest.json")
    matches = [card for card in manifest.get("cards", []) if card.get("card_id") == card_id]
    if len(matches) != 1:
        raise PlanRouteError("PLAN_ROUTE_CARD_UNAVAILABLE", f"manifest does not contain exactly one {card_id}")
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
    return _result("blocked", owner="writing-plans", reasons=[code])


def _select(decision_id: str, reason: str, rows: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    row = next((item for item in rows if item["decision_id"] == decision_id), None)
    if row is None:
        raise PlanRouteError("PLAN_ROUTE_MAP_INVALID", f"entry decision is unmapped: {decision_id}")
    return _result("select_card", owner="writing-plans", reasons=[reason], decision=row, root=root)


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
    return _result("select_card", owner="writing-plans", reasons=["PENDING_DECISION_SELECTED"], decision=selected, root=root)


def assess(raw: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    facts = _validated_facts(raw)
    rows = _decision_rows(root)
    if facts["route_phase"] == "program_queue":
        return _queue_result(facts, rows, root) or _result(
            "terminal", owner=None, reasons=["PROGRAM_QUEUE_EMPTY"]
        )
    if facts["root_cause_status"] == "unknown":
        return _result("handoff", owner="software-quality-workflows", reasons=["ROOT_CAUSE_UNKNOWN"])
    if facts["intent_status"] == "materially_underdefined":
        return _result("handoff", owner="software-quality-workflows", reasons=["MATERIAL_INTENT_UNDERDEFINED"])
    if facts["long_corpus_only"]:
        return _select("wp.select.bridges.long-document-handoff", "LONG_CORPUS_OWNER", rows, root)
    if facts["disposable_spike"]:
        return _select("wp.select.experiments.disposable-spike", "DISPOSABLE_SPIKE", rows, root)
    if any(facts[field] for field in ("public_contract", "migration_or_rollback", "resume_required", "external_side_effect")):
        return _select("wp.select.profiles.program", "PROGRAM_PLAN_REQUIRED", rows, root)
    if (
        not facts["same_session_execution"]
        or facts["durable_handoff"]
        or facts["independent_write_slices"] > 1
        or facts["copy_paste_projection_requested"]
    ):
        return _select("wp.select.profiles.handoff", "DURABLE_HANDOFF_REQUIRED", rows, root)
    if facts["explicit_plan_request"]:
        return _select("wp.select.profiles.brief", "EXPLICIT_PLAN_REQUEST", rows, root)
    queued = _queue_result(facts, rows, root)
    if queued is not None:
        return queued
    return _result("handoff", owner="software-quality-workflows", reasons=["ROUTINE_DIRECT_PATH"])


def validate_plan_route_result(result: Any, root: Path = ROOT) -> list[PlanRouteViolation]:
    issues: list[PlanRouteViolation] = []
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        return [PlanRouteViolation("plan-route.shape", "/", "result keys are not exact")]
    action = result.get("route_action")
    decision_id = result.get("selected_decision_id")
    card = result.get("primary_card")
    if action == "select_card":
        if not isinstance(decision_id, str) or not isinstance(card, dict):
            issues.append(PlanRouteViolation("plan-route.selection", "/", "selection requires one decision and card"))
        else:
            try:
                row = next(item for item in _decision_rows(root) if item["decision_id"] == decision_id)
                if card != _card(row["card_id"], root):
                    issues.append(PlanRouteViolation("plan-route.card", "/primary_card", "selected card identity is stale"))
            except (PlanRouteError, StopIteration):
                issues.append(PlanRouteViolation("plan-route.decision", "/selected_decision_id", "decision is not mapped"))
    elif decision_id is not None or card is not None:
        issues.append(PlanRouteViolation("plan-route.boundary", "/", "boundary result cannot select a card"))
    if not isinstance(result.get("reason_codes"), list) or not result["reason_codes"]:
        issues.append(PlanRouteViolation("plan-route.reason", "/reason_codes", "at least one reason is required"))
    return issues


def _read_input(path: str) -> dict[str, Any]:
    try:
        value = strict_json_bytes(Path(path).read_bytes(), source=path)
    except (OSError, ValueError) as exc:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "route input must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facts")
    args = parser.parse_args(argv)
    try:
        result = assess(_read_input(args.facts))
    except (OSError, ValueError, PlanRouteError) as exc:
        code = exc.code if isinstance(exc, PlanRouteError) else "PLAN_ROUTE_INPUT_INVALID"
        print(json.dumps({"ok": False, "error": code, "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
