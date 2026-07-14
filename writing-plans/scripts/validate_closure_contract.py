#!/usr/bin/env python3
"""Validate a Closure Contract schema and its cross-field freeze semantics."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from _closure_contract import ContractInputError, canonical_contract_hash, canonical_object_hash, id_index, iter_strings, load_contract
from _plan_state import PlanInputError, Violation, patterns_may_overlap, pointer, validate_against_schema


TERMINAL_STATUSES = (
    "CLOSED",
    "SPEC_UNDERDETERMINED",
    "SPEC_UNSAT",
    "AUTHORITY_BLOCKED",
    "ENVIRONMENT_UNAVAILABLE",
    "BASELINE_UNSTABLE",
    "VERIFIER_UNQUALIFIED",
    "NON_CONVERGED",
    "BUDGET_EXHAUSTED",
    "WORKFLOW_INVALID",
    "ABORTED_BY_SOURCE_DRIFT",
)
AUTHORITY_RANK = {"read_only": 0, "local_ephemeral": 1, "local_reversible": 2, "draft_pr": 3}
SELECTION_ORDER = (
    "hard_constraint_violations",
    "regressions",
    "soft_objectives_by_priority",
    "risk",
    "complexity",
    "diff_size",
    "evaluation_cost",
)
ANCHOR_PREFIXES = ("user:", "repo:", "path:", "policy:", "artifact:", "source:")


def _objects(contract: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = contract.get(field)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _refs(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _violation(code: str, path: str, message: str, object_id: str | None = None) -> Violation:
    return Violation(code, path, message, object_id)


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _unsafe_relative_pattern(value: str) -> bool:
    return value.startswith(("/", "\\")) or "\\" in value or "\x00" in value or ".." in value.split("/")


def _check_anchors(violations: list[Violation], anchors: Iterable[str], path: str, object_id: str | None = None) -> None:
    for anchor in anchors:
        if not anchor.startswith(ANCHOR_PREFIXES):
            violations.append(_violation("contract.anchor-invalid", path, f"anchor lacks an authoritative scheme: {anchor!r}", object_id))


def _check_refs(
    violations: list[Violation],
    refs: Iterable[str],
    *,
    expected_collection: str,
    index: dict[str, tuple[str, int]],
    path: str,
    object_id: str | None,
) -> None:
    for ref in refs:
        resolved = index.get(ref)
        if resolved is None or resolved[0] != expected_collection:
            violations.append(_violation("contract.ref-unresolved", path, f"{ref} does not resolve to {expected_collection}", object_id))


def validate_contract(
    contract: dict[str, Any],
    schema: dict[str, Any],
    *,
    for_freeze: bool = False,
    expected_scope_hash: str | None = None,
    authority_ceiling: str | None = None,
    expected_base_revision: str | None = None,
    expected_policy_bundle_hash: str | None = None,
    expected_authority_hash: str | None = None,
) -> list[Violation]:
    violations = [
        Violation("contract.schema", item.path, item.message, item.object_id)
        for item in validate_against_schema(contract, schema)
    ]
    index, duplicates = id_index(contract)
    for identifier in sorted(duplicates):
        violations.append(_violation("contract.id-duplicate", "/", f"duplicate stable ID: {identifier}", identifier))

    source = contract.get("source") if isinstance(contract.get("source"), dict) else {}
    scope = contract.get("scope") if isinstance(contract.get("scope"), dict) else {}
    created_time = _aware_datetime(contract.get("created_at"))
    if created_time is None:
        violations.append(_violation("contract.time-invalid", "/created_at", "created_at must be timezone-aware"))
    if _aware_datetime(source.get("observed_at")) is None:
        violations.append(_violation("contract.time-invalid", "/source/observed_at", "source observed_at must be timezone-aware"))
    source_scope_hash = source.get("scope_hash")
    scope_hash = scope.get("scope_hash")
    if expected_base_revision is not None and source.get("base_revision") != expected_base_revision:
        violations.append(_violation("contract.source-mismatch", "/source/base_revision", "contract does not match the admitted source revision"))
    if expected_policy_bundle_hash is not None and source.get("policy_bundle_hash") != expected_policy_bundle_hash:
        violations.append(_violation("contract.policy-mismatch", "/source/policy_bundle_hash", "contract does not match the admitted policy bundle"))
    if isinstance(source_scope_hash, str) and isinstance(scope_hash, str) and source_scope_hash != scope_hash:
        violations.append(_violation("contract.scope-mismatch", "/scope/scope_hash", "source and scope hashes differ"))
    if expected_scope_hash is not None and (source_scope_hash != expected_scope_hash or scope_hash != expected_scope_hash):
        violations.append(_violation("contract.scope-mismatch", "/scope/scope_hash", "contract does not match the admitted scope hash"))

    authority = contract.get("authority") if isinstance(contract.get("authority"), dict) else {}
    actual_ceiling = authority.get("autonomy_ceiling")
    if expected_authority_hash is not None and canonical_object_hash(authority) != expected_authority_hash:
        violations.append(_violation("contract.authority-mismatch", "/authority", "contract authority object differs from the admitted manifest"))
    if authority_ceiling in AUTHORITY_RANK and actual_ceiling in AUTHORITY_RANK and AUTHORITY_RANK[actual_ceiling] > AUTHORITY_RANK[authority_ceiling]:
        violations.append(_violation("contract.authority-mismatch", "/authority/autonomy_ceiling", "contract exceeds the admitted autonomy ceiling"))
    if actual_ceiling in AUTHORITY_RANK:
        for effect in _refs(authority.get("allowed_side_effects")):
            if effect in AUTHORITY_RANK and AUTHORITY_RANK[effect] > AUTHORITY_RANK[actual_ceiling]:
                violations.append(_violation("contract.authority-mismatch", "/authority/allowed_side_effects", f"side effect {effect} exceeds autonomy ceiling"))
    forbidden_actions = set(_refs(authority.get("forbidden_actions")))
    preauthorized_actions = set(_refs(authority.get("preauthorized_external_actions")))
    for action in sorted(forbidden_actions & preauthorized_actions):
        violations.append(_violation("contract.authority-conflict", "/authority", f"action {action!r} is both forbidden and preauthorized"))

    request = contract.get("request") if isinstance(contract.get("request"), dict) else {}
    _check_anchors(violations, _refs(request.get("source_anchors")), "/request/source_anchors")
    if for_freeze and not _refs(request.get("source_anchors")):
        violations.append(_violation("contract.request-source-missing", "/request/source_anchors", "freeze requires at least one authoritative request anchor"))
    if for_freeze and not _refs(scope.get("allowed_read_paths")):
        violations.append(_violation("contract.read-scope-missing", "/scope/allowed_read_paths", "freeze requires an explicit read scope"))
    if for_freeze and not _refs(scope.get("allowed_write_paths")):
        violations.append(_violation("contract.write-scope-missing", "/scope/allowed_write_paths", "change closure requires an explicit candidate write scope"))
    if for_freeze and not _objects(contract, "protected_surfaces"):
        violations.append(_violation("contract.protected-surface-missing", "/protected_surfaces", "freeze requires protected controller/contract surfaces"))

    hard_constraints = _objects(contract, "hard_constraints")
    if for_freeze and not hard_constraints:
        violations.append(_violation("contract.hard-required", "/hard_constraints", "a frozen Closure Contract requires at least one hard constraint"))
    for position, constraint in enumerate(hard_constraints):
        object_id = constraint.get("id") if isinstance(constraint.get("id"), str) else None
        base = f"/hard_constraints/{position}"
        sources = _refs(constraint.get("source_anchors"))
        verifier_refs = _refs(constraint.get("oracle_requirement_refs"))
        if not sources:
            violations.append(_violation("contract.hard-source-missing", base + "/source_anchors", "hard constraint lacks an authoritative source anchor", object_id))
        if not verifier_refs:
            violations.append(_violation("contract.hard-verifier-missing", base + "/oracle_requirement_refs", "hard constraint lacks a verifier requirement", object_id))
        _check_anchors(violations, sources, base + "/source_anchors", object_id)
        if for_freeze and constraint.get("blocking") is not True:
            violations.append(_violation("contract.hard-nonblocking", base + "/blocking", "hard constraints must remain blocking", object_id))
        if for_freeze and constraint.get("protected_from_candidate") is not True:
            violations.append(_violation("contract.hard-unprotected", base + "/protected_from_candidate", "hard constraints must be protected from candidate mutation", object_id))
        if not _refs(constraint.get("applies_to_corners")):
            violations.append(_violation("contract.hard-corner-missing", base + "/applies_to_corners", "hard constraint lacks a selected corner", object_id))
        if for_freeze and constraint.get("manual_or_external_judgment_required") is True:
            violations.append(_violation("contract.hard-manual-terminal", base, "manual/external judgment cannot be silently frozen for unattended closure", object_id))
        _check_refs(violations, _refs(constraint.get("applies_to_corners")), expected_collection="corners", index=index, path=base + "/applies_to_corners", object_id=object_id)
        _check_refs(violations, verifier_refs, expected_collection="verifier_requirements", index=index, path=base + "/oracle_requirement_refs", object_id=object_id)

    for position, assumption in enumerate(_objects(contract, "assumptions")):
        object_id = assumption.get("id") if isinstance(assumption.get("id"), str) else None
        if assumption.get("classification") == "defaulted" and assumption.get("decision") == "accepted" and (
            assumption.get("materiality") != "low" or assumption.get("reversibility") != "local"
        ):
            violations.append(_violation("contract.default-unsafe", f"/assumptions/{position}", "only low-materiality local defaults may be accepted unattended", object_id))
        challenge = assumption.get("challenge_oracle")
        if isinstance(challenge, str):
            _check_refs(violations, [challenge], expected_collection="verifier_requirements", index=index, path=f"/assumptions/{position}/challenge_oracle", object_id=object_id)

    for position, objective in enumerate(_objects(contract, "soft_objectives")):
        object_id = objective.get("id") if isinstance(objective.get("id"), str) else None
        base = f"/soft_objectives/{position}"
        conflicts = _refs(objective.get("conflicts_with_hard_constraint_refs"))
        if conflicts:
            violations.append(_violation("contract.objective-hard-conflict", base + "/conflicts_with_hard_constraint_refs", "soft objective declares a hard-constraint conflict", object_id))
        _check_refs(violations, _refs(objective.get("oracle_requirement_refs")), expected_collection="verifier_requirements", index=index, path=base + "/oracle_requirement_refs", object_id=object_id)
        _check_refs(violations, conflicts, expected_collection="hard_constraints", index=index, path=base + "/conflicts_with_hard_constraint_refs", object_id=object_id)

    for position, corner in enumerate(_objects(contract, "corners")):
        object_id = corner.get("id") if isinstance(corner.get("id"), str) else None
        _check_refs(violations, _refs(corner.get("verifier_requirement_refs")), expected_collection="verifier_requirements", index=index, path=f"/corners/{position}/verifier_requirement_refs", object_id=object_id)

    for position, requirement in enumerate(_objects(contract, "verifier_requirements")):
        if not _refs(requirement.get("allowed_oracle_classes")):
            violations.append(_violation("contract.verifier-oracle-missing", f"/verifier_requirements/{position}/allowed_oracle_classes", "verifier requirement lacks an allowed oracle class", requirement.get("id")))
        repeat = requirement.get("repeat_policy") if isinstance(requirement.get("repeat_policy"), dict) else {}
        runs, flakes = repeat.get("runs"), repeat.get("allowed_flakes")
        if isinstance(runs, int) and isinstance(flakes, int) and flakes >= runs:
            violations.append(_violation("contract.repeat-policy", f"/verifier_requirements/{position}/repeat_policy", "allowed flakes must be fewer than runs", requirement.get("id")))

    allowed_writes = _refs(scope.get("allowed_write_paths"))
    for field in ("allowed_read_paths", "allowed_write_paths", "forbidden_paths"):
        for path_value in _refs(scope.get(field)):
            if _unsafe_relative_pattern(path_value):
                violations.append(_violation("contract.path-unsafe", f"/scope/{field}", f"scope path must be repository-relative: {path_value!r}"))
    protected_paths = _refs(scope.get("forbidden_paths")) + [surface.get("path") for surface in _objects(contract, "protected_surfaces") if isinstance(surface.get("path"), str)]
    for position, surface in enumerate(_objects(contract, "protected_surfaces")):
        path_value = surface.get("path")
        if isinstance(path_value, str) and _unsafe_relative_pattern(path_value):
            violations.append(_violation("contract.path-unsafe", f"/protected_surfaces/{position}/path", f"protected path must be repository-relative: {path_value!r}", surface.get("id")))
        _check_anchors(violations, _refs(surface.get("source_anchors")), f"/protected_surfaces/{position}/source_anchors", surface.get("id"))
    for write_path in allowed_writes:
        for protected_path in protected_paths:
            if patterns_may_overlap(write_path, protected_path):
                violations.append(_violation("contract.protected-write-overlap", "/scope/allowed_write_paths", f"candidate write {write_path!r} overlaps protected surface {protected_path!r}"))

    publication = contract.get("publication_policy") if isinstance(contract.get("publication_policy"), dict) else {}
    publication_ceiling = publication.get("ceiling")
    preauthorized = preauthorized_actions
    exceeds = publication_ceiling == "local_patch" and AUTHORITY_RANK.get(actual_ceiling, -1) < AUTHORITY_RANK["local_reversible"]
    exceeds = exceeds or publication_ceiling == "draft_pr" and (AUTHORITY_RANK.get(actual_ceiling, -1) < AUTHORITY_RANK["draft_pr"] or "draft_pr" not in preauthorized)
    if exceeds:
        violations.append(_violation("contract.publication-authority", "/publication_policy/ceiling", "publication ceiling exceeds explicit authority"))

    for position, ambiguity in enumerate(_objects(contract, "ambiguities")):
        if for_freeze and ambiguity.get("status") != "resolved":
            violations.append(_violation("contract.ambiguity-unresolved", f"/ambiguities/{position}", "material ambiguity blocks contract freeze", ambiguity.get("id")))

    terminal_policy = contract.get("terminal_policy") if isinstance(contract.get("terminal_policy"), dict) else {}
    if terminal_policy.get("allowed_statuses") != list(TERMINAL_STATUSES):
        violations.append(_violation("contract.terminal-status", "/terminal_policy/allowed_statuses", "terminal status vocabulary must be the fixed ordered set"))
    for string_path, value in iter_strings(contract):
        if value.startswith("plan:"):
            violations.append(_violation("contract.reverse-plan-ref", pointer(string_path), "Closure Contract cannot reference a plan artifact"))
        if value.startswith("candidate:") or value.startswith("CAND-"):
            violations.append(_violation("contract.candidate-ref", pointer(string_path), "Closure Contract cannot bind a future candidate identity"))

    search = contract.get("search_policy") if isinstance(contract.get("search_policy"), dict) else {}
    if search.get("selection_order") != list(SELECTION_ORDER):
        violations.append(_violation("contract.selection-order", "/search_policy/selection_order", "selection order must remain lexicographic and fixed"))

    status = contract.get("status")
    if status == "draft":
        if contract.get("content_hash") is not None or contract.get("frozen_at") is not None:
            violations.append(_violation("contract.draft-derived-field", "/", "draft content_hash and frozen_at must be null"))
    elif status in {"frozen", "superseded"}:
        frozen_time = _aware_datetime(contract.get("frozen_at"))
        if frozen_time is None:
            violations.append(_violation("contract.frozen-time-missing", "/frozen_at", "frozen or superseded contract requires a timezone-aware frozen_at"))
        if frozen_time is not None and created_time is not None and frozen_time < created_time:
            violations.append(_violation("contract.time-order", "/frozen_at", "frozen_at cannot precede created_at"))
        if contract.get("content_hash") != canonical_contract_hash(contract):
            violations.append(_violation("contract.hash-mismatch", "/content_hash", "content hash does not match canonical frozen semantics"))
    if for_freeze and status != "draft":
        violations.append(_violation("contract.freeze-status", "/status", "freeze input must be a draft"))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--for-freeze", action="store_true")
    parser.add_argument("--expected-scope-hash")
    parser.add_argument("--authority-ceiling", choices=sorted(AUTHORITY_RANK))
    parser.add_argument("--expected-base-revision")
    parser.add_argument("--expected-policy-bundle-hash")
    parser.add_argument("--expected-authority-hash")
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.contract)
        schema = load_contract(args.schema)
        violations = validate_contract(
            contract,
            schema,
            for_freeze=args.for_freeze,
            expected_scope_hash=args.expected_scope_hash,
            authority_ceiling=args.authority_ceiling,
            expected_base_revision=args.expected_base_revision,
            expected_policy_bundle_hash=args.expected_policy_bundle_hash,
            expected_authority_hash=args.expected_authority_hash,
        )
    except (ContractInputError, PlanInputError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "contract.input", "message": str(exc)}}, indent=2))
        return 2
    print(json.dumps({"ok": not violations, "violations": [item.as_dict() for item in violations]}, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
