#!/usr/bin/env python3
"""Validate SQW registry 2.0 authority, graph, paths, and active coverage."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, Violation, load_json, pointer, validate_against_schema


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "references" / "owner-registry.json"
DEFAULT_SCHEMA = ROOT / "schemas" / "owner-registry.schema.json"


def _requires_cycle(edges: dict[str, set[str]]) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in visiting:
            start = stack.index(node)
            return stack[start:] + [node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for target in sorted(edges.get(node, set())):
            cycle = visit(target)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(edges):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def validate_registry(data: Any, schema: dict[str, Any], root: Path = ROOT) -> list[Violation]:
    violations = validate_against_schema(data, schema, code="registry.schema")
    if not isinstance(data, dict):
        return violations
    for index, owner in enumerate(data.get("owners", [])):
        if not isinstance(owner, dict):
            continue
        if owner.get("authority") == "companion" and "owns" in owner:
            violations.append(Violation("registry.companion-owns", pointer(("owners", index, "owns")), "companion cannot own normative policy", owner.get("id")))
        if owner.get("authority") == "normative_owner" and "contributes" in owner:
            violations.append(Violation("registry.normative-contributes", pointer(("owners", index, "contributes")), "normative owner cannot use companion contribution claims", owner.get("id")))
    if any(item.code == "registry.schema" for item in violations):
        return violations

    root = root.resolve()
    owners = data.get("owners", [])
    by_id: dict[str, dict[str, Any]] = {}
    seen_paths: dict[str, int] = {}
    policies: dict[str, list[str]] = defaultdict(list)
    registered: set[str] = set()

    for index, owner in enumerate(owners):
        owner_id = owner["id"]
        path_value = owner["path"]
        if owner_id in by_id:
            violations.append(Violation("registry.owner-duplicate", pointer(("owners", index, "id")), "owner ID is duplicated", owner_id))
        else:
            by_id[owner_id] = owner
        if path_value in seen_paths:
            violations.append(Violation("registry.path-duplicate", pointer(("owners", index, "path")), f"path duplicates index {seen_paths[path_value]}", owner_id))
        else:
            seen_paths[path_value] = index
            registered.add(path_value)

        candidate = root / path_value
        try:
            candidate.relative_to(root)
        except ValueError:
            violations.append(Violation("registry.path-escape", pointer(("owners", index, "path")), "reference path escapes skill root", owner_id))
        if candidate.is_symlink():
            violations.append(Violation("registry.path-symlink", pointer(("owners", index, "path")), "registered reference cannot be a symlink", owner_id))
        elif not candidate.is_file():
            violations.append(Violation("registry.path-missing", pointer(("owners", index, "path")), f"registered reference does not exist: {path_value}", owner_id))
        if candidate.stem != owner_id:
            violations.append(Violation("registry.id-path-mismatch", pointer(("owners", index, "path")), "owner ID must equal the flat reference stem", owner_id))

        if owner["authority"] == "normative_owner":
            if "contributes" in owner:
                violations.append(Violation("registry.normative-contributes", pointer(("owners", index, "contributes")), "normative owner cannot use companion contribution claims", owner_id))
            for policy in owner.get("owns", []):
                policies[policy].append(owner_id)
        else:
            if "owns" in owner:
                violations.append(Violation("registry.companion-owns", pointer(("owners", index, "owns")), "companion cannot own normative policy", owner_id))

    for policy, policy_owners in policies.items():
        if len(policy_owners) > 1:
            violations.append(Violation("registry.policy-duplicate", "/owners", f"policy {policy!r} has multiple owners: {policy_owners}"))

    requires_graph: dict[str, set[str]] = {owner_id: set() for owner_id in by_id}
    for index, owner in enumerate(owners):
        owner_id = owner["id"]
        for field in ("requires", "may_load", "conflicts_with"):
            for edge_index, target in enumerate(owner.get(field, [])):
                target_owner = by_id.get(target)
                if target_owner is None:
                    violations.append(Violation("registry.edge-unknown", pointer(("owners", index, field, edge_index)), f"unknown owner edge target: {target}", owner_id))
                    continue
                if field == "requires":
                    requires_graph[owner_id].add(target)
                    if target_owner["authority"] != "normative_owner":
                        violations.append(Violation("registry.requires-companion", pointer(("owners", index, field, edge_index)), "requires may target only a normative owner", owner_id))
                    if not set(owner.get("phases", [])) & set(target_owner.get("phases", [])):
                        violations.append(Violation("registry.phase-incompatible", pointer(("owners", index, field, edge_index)), f"required owner {target} is not active in any consumer phase", owner_id))
                    if owner.get("role") == "lifecycle" and target_owner.get("role") == "lifecycle":
                        violations.append(Violation("registry.lifecycle-requires-lifecycle", pointer(("owners", index, field, edge_index)), "lifecycle owners cannot unconditionally require another lifecycle owner", owner_id))
                if field == "conflicts_with" and owner_id not in target_owner.get("conflicts_with", []):
                    violations.append(Violation("registry.conflict-asymmetric", pointer(("owners", index, field, edge_index)), f"conflict edge is not symmetric with {target}", owner_id))

    cycle = _requires_cycle(requires_graph)
    if cycle:
        violations.append(Violation("registry.requires-cycle", "/owners", "requires graph contains a cycle: " + " -> ".join(cycle)))

    actual = {path.relative_to(root).as_posix() for path in (root / "references").glob("*.md") if not path.is_symlink()}
    for path in sorted(actual - registered):
        violations.append(Violation("registry.reference-orphan", "/owners", f"active Markdown reference is not registered: {path}"))
    for path in sorted(registered - actual):
        if (root / path).exists():
            violations.append(Violation("registry.reference-nonflat", "/owners", f"registry path is not an active flat Markdown reference: {path}"))

    local_ids = set(by_id)
    seen_external: set[str] = set()
    for index, external in enumerate(data.get("external_owners", [])):
        external_id = external["id"]
        if external_id in local_ids or external_id in seen_external:
            violations.append(Violation("registry.external-duplicate", pointer(("external_owners", index, "id")), "external owner ID collides with another owner", external_id))
        seen_external.add(external_id)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        data, schema = load_json(args.registry), load_json(args.schema)
        violations = validate_registry(data, schema, args.root)
    except (OSError, InputError) as exc:
        violations = [Violation("registry.schema", "", str(exc))]
    print(json.dumps({"ok": not violations, "violations": [item.as_dict() for item in violations]}, ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
