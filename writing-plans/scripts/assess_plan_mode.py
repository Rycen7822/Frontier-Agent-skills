#!/usr/bin/env python3
"""Select one Writing Plans route and, when local, one exact manifest card."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
REQUIRED_FACTS = {
    "schema_version",
    "explicit_plan_request",
    "root_cause_status",
    "intent_status",
    "closure_admission_decision",
}
OPTIONAL_DEFAULTS: dict[str, Any] = {
    "same_session_execution": True,
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
BOOLEAN_FACTS = {
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
ADMISSION_DECISIONS = {"NOT_REQUESTED", "DIRECT_SELECTED", "CLOSURE_ELIGIBLE", "TERMINAL"}
RESULT_KEYS = {
    "schema_version",
    "route",
    "profile",
    "execution_policy",
    "primary_card",
    "required_artifact_projection_ids",
    "reason_codes",
    "handoff_owner",
}


class PlanRouteError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PlanRouteViolation(NamedTuple):
    code: str
    path: str
    message: str


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PlanRouteError("PLAN_ROUTE_MANIFEST_INVALID", f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / "registries" / "reference-cards.manifest.json"
    info = path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_nlink != 1:
        raise PlanRouteError("PLAN_ROUTE_MANIFEST_INVALID", f"unsafe card manifest: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PlanRouteError("PLAN_ROUTE_MANIFEST_INVALID", f"invalid card manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise PlanRouteError("PLAN_ROUTE_MANIFEST_INVALID", "card manifest must be an object")
    return value


def _validated_facts(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "plan route facts must be an object")
    if not raw:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INCOMPLETE", "plan route facts must not be empty")
    allowed = REQUIRED_FACTS | set(OPTIONAL_DEFAULTS)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise PlanRouteError("PLAN_ROUTE_INPUT_UNKNOWN_FIELD", f"unknown route facts: {unknown}")
    missing = sorted(REQUIRED_FACTS - set(raw))
    if missing:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INCOMPLETE", f"missing plan route facts: {missing}")
    facts = {**OPTIONAL_DEFAULTS, **raw}
    if facts["schema_version"] != "1.0":
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "schema_version must be 1.0")
    for field in BOOLEAN_FACTS:
        if not isinstance(facts[field], bool):
            raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", f"{field} must be boolean")
    for field, allowed_values in (
        ("root_cause_status", ROOT_CAUSE_STATUSES),
        ("intent_status", INTENT_STATUSES),
        ("closure_admission_decision", ADMISSION_DECISIONS),
    ):
        if facts[field] not in allowed_values:
            raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", f"invalid {field}: {facts[field]!r}")
    for field, minimum in (("independent_write_slices", 0), ("strategy_family_count", 1)):
        value = facts[field]
        if type(value) is not int or value < minimum:
            raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", f"{field} must be an integer >= {minimum}")
    return facts


def _card(card_id: str, root: Path = ROOT) -> dict[str, Any]:
    manifest = _load_manifest(root)
    matches = [item for item in manifest.get("cards", []) if item.get("card_id") == card_id]
    if len(matches) != 1:
        raise PlanRouteError("PLAN_ROUTE_CARD_UNAVAILABLE", f"manifest does not contain exactly one {card_id}")
    item = matches[0]
    return {key: item[key] for key in ("card_id", "path", "sha256", "bytes")}


def _result(
    route: str,
    *,
    profile: str | None,
    reasons: list[str],
    execution_policy: str = "standard",
    card_id: str | None = None,
    required_artifacts: list[str] | None = None,
    handoff_owner: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "route": route,
        "profile": profile,
        "execution_policy": execution_policy,
        "primary_card": _card(card_id) if card_id else None,
        "required_artifact_projection_ids": list(dict.fromkeys(required_artifacts or [])),
        "reason_codes": list(dict.fromkeys(reasons)),
        "handoff_owner": handoff_owner,
    }


def assess(raw: dict[str, Any]) -> dict[str, Any]:
    facts = _validated_facts(raw)
    admission = facts["closure_admission_decision"]
    if admission == "TERMINAL":
        return _result("terminal", profile=None, reasons=["CLOSURE_ADMISSION_TERMINAL"])
    if facts["root_cause_status"] == "unknown":
        return _result(
            "sqw-diagnosis",
            profile=None,
            reasons=["ROOT_CAUSE_UNKNOWN"],
            handoff_owner="software-quality-workflows",
        )
    if facts["intent_status"] == "materially_underdefined":
        return _result(
            "sqw-intent",
            profile=None,
            reasons=["MATERIAL_INTENT_UNDERDEFINED"],
            handoff_owner="software-quality-workflows",
        )
    if facts["long_corpus_only"]:
        return _result(
            "long-document",
            profile=None,
            reasons=["LONG_CORPUS_OWNER"],
            card_id="wp.bridges.long-document-handoff",
            handoff_owner="long-document-segmented-writing",
        )
    if facts["disposable_spike"]:
        return _result("spike", profile=None, reasons=["DISPOSABLE_SPIKE"], card_id="wp.experiments.disposable-spike")
    if admission == "CLOSURE_ELIGIBLE":
        reasons = ["CLOSURE_CONTRACT_REQUIRED"]
        if facts["strategy_family_count"] > 1:
            reasons.append("MULTIPLE_STRATEGY_FAMILIES")
        return _result(
            "writing-plans",
            profile="program",
            execution_policy="autonomous_closure",
            reasons=reasons,
            card_id="wp.closure.compile",
            required_artifacts=["closure-admission"],
        )
    program_reasons = [
        reason
        for field, reason in (
            ("public_contract", "PUBLIC_CONTRACT"),
            ("migration_or_rollback", "MIGRATION_OR_ROLLBACK"),
            ("resume_required", "RESUME_REQUIRED"),
            ("external_side_effect", "EXTERNAL_SIDE_EFFECT"),
        )
        if facts[field]
    ]
    if program_reasons:
        return _result(
            "writing-plans",
            profile="program",
            reasons=program_reasons,
            card_id="wp.profiles.program",
        )
    handoff_reasons: list[str] = []
    if not facts["same_session_execution"]:
        handoff_reasons.append("CROSS_CONTEXT_HANDOFF")
    if facts["durable_handoff"]:
        handoff_reasons.append("DURABLE_HANDOFF")
    if facts["independent_write_slices"] > 1:
        handoff_reasons.append("INDEPENDENT_WRITE_SLICES")
    if facts["copy_paste_projection_requested"]:
        handoff_reasons.append("EXECUTABLE_PROJECTION_REQUESTED")
    if handoff_reasons:
        return _result(
            "writing-plans",
            profile="handoff",
            reasons=handoff_reasons,
            card_id="wp.profiles.handoff",
        )
    if facts["explicit_plan_request"]:
        return _result(
            "writing-plans",
            profile="brief",
            reasons=["EXPLICIT_PLAN_REQUEST"],
            card_id="wp.profiles.brief",
        )
    direct_reason = "CLOSURE_DIRECT_SELECTED" if admission == "DIRECT_SELECTED" else "ROUTINE_DIRECT_PATH"
    return _result(
        "direct",
        profile=None,
        reasons=[direct_reason],
        handoff_owner="software-quality-workflows",
    )


def validate_plan_route_result(result: Any, root: Path = ROOT) -> list[PlanRouteViolation]:
    violations: list[PlanRouteViolation] = []
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        return [PlanRouteViolation("plan-route.shape", "/", "result must contain the exact route keys")]
    card = result.get("primary_card")
    if card is not None:
        if not isinstance(card, dict) or set(card) != {"card_id", "path", "sha256", "bytes"}:
            violations.append(PlanRouteViolation("plan-route.card-shape", "/primary_card", "invalid transport ref"))
        else:
            try:
                expected = _card(card["card_id"], root)
            except (OSError, TypeError, ValueError):
                expected = None
            if card != expected:
                violations.append(PlanRouteViolation("plan-route.card-identity", "/primary_card", "card identity differs from manifest"))
    if result.get("route") not in {"direct", "sqw-diagnosis", "sqw-intent", "writing-plans", "spike", "long-document", "terminal"}:
        violations.append(PlanRouteViolation("plan-route.route", "/route", "unknown route"))
    for field in ("required_artifact_projection_ids", "reason_codes"):
        value = result.get(field)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))
        ):
            violations.append(PlanRouteViolation("plan-route.list-shape", f"/{field}", "must be a unique non-empty string list"))

    route = result.get("route")
    profile = result.get("profile")
    policy = result.get("execution_policy")
    owner = result.get("handoff_owner")
    card_id = card.get("card_id") if isinstance(card, dict) else None
    artifacts = result.get("required_artifact_projection_ids")
    expected_local_cards = {
        "brief": "wp.profiles.brief",
        "handoff": "wp.profiles.handoff",
    }
    if route == "writing-plans":
        valid_program_card = profile == "program" and card_id in {"wp.profiles.program", "wp.closure.compile"}
        if not (card_id == expected_local_cards.get(profile) or valid_program_card) or owner is not None:
            violations.append(PlanRouteViolation("plan-route.local-selection", "/primary_card", "profile and local card do not match"))
        if card_id == "wp.closure.compile":
            if policy != "autonomous_closure" or artifacts != ["closure-admission"]:
                violations.append(PlanRouteViolation("plan-route.closure-binding", "/execution_policy", "closure compile requires Admission projection"))
        elif policy != "standard" or artifacts != []:
            violations.append(PlanRouteViolation("plan-route.standard-binding", "/execution_policy", "standard profile cannot require closure artifacts"))
    elif route == "spike":
        if profile is not None or card_id != "wp.experiments.disposable-spike" or owner is not None or policy != "standard" or artifacts != []:
            violations.append(PlanRouteViolation("plan-route.spike-selection", "/primary_card", "spike must select only its exact experiment card"))
    elif route == "long-document":
        if (
            profile is not None
            or card_id != "wp.bridges.long-document-handoff"
            or owner != "long-document-segmented-writing"
            or policy != "standard"
            or artifacts != []
        ):
            violations.append(PlanRouteViolation("plan-route.long-document-selection", "/primary_card", "long corpus handoff must select the exact local bridge"))
    else:
        expected_owner = {
            "direct": "software-quality-workflows",
            "sqw-diagnosis": "software-quality-workflows",
            "sqw-intent": "software-quality-workflows",
            "terminal": None,
        }.get(route)
        if profile is not None or card is not None or owner != expected_owner or policy != "standard" or artifacts != []:
            violations.append(PlanRouteViolation("plan-route.handoff-selection", "/", "cross-skill or terminal route has an invalid local selection"))
    return violations


def _read_input(path: str) -> dict[str, Any]:
    try:
        text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", str(exc)) from exc
    if not isinstance(value, dict):
        raise PlanRouteError("PLAN_ROUTE_INPUT_INVALID", "route input must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", default="-", help="JSON file or - for stdin")
    args = parser.parse_args(argv)
    try:
        result = assess(_read_input(args.input))
    except (OSError, PlanRouteError, ValueError) as exc:
        code = exc.code if isinstance(exc, PlanRouteError) else "PLAN_ROUTE_INPUT_INVALID"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(exc)}}, indent=2))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
