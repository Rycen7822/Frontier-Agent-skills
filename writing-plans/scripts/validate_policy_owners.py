#!/usr/bin/env python3
"""Validate the non-loading Writing Plans policy ownership graph."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

from _writing_reference_cards import BUNDLE_ID, SKILL_ID, TARGET_SKILL_VERSION, load_json


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registries" / "policy-owners.json"
MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"
POLICY_ID = re.compile(r"^wp(?:\.[a-z0-9][a-z0-9-]*)+$")


def validate(registry: Any, manifest: Any) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    required_keys = {"bundle_id", "policies", "schema_version", "skill_id", "skill_version"}
    if not isinstance(registry, dict) or set(registry) != required_keys:
        return [{"code": "policy.registry-shape", "path": "", "message": "registry has unexpected keys"}]
    expected_identity = {"bundle_id": BUNDLE_ID, "schema_version": "1.0", "skill_id": SKILL_ID, "skill_version": TARGET_SKILL_VERSION}
    for field, expected in expected_identity.items():
        if registry.get(field) != expected:
            issues.append({"code": "policy.identity", "path": f"/{field}", "message": f"expected {expected}"})
    cards = {item.get("card_id") for item in manifest.get("cards", []) if isinstance(item, dict)} if isinstance(manifest, dict) else set()
    policies = registry.get("policies")
    if not isinstance(policies, list) or not policies:
        return issues + [{"code": "policy.list", "path": "/policies", "message": "policies must be non-empty"}]
    by_id: dict[str, dict[str, Any]] = {}
    for index, policy in enumerate(policies):
        path = f"/policies/{index}"
        if not isinstance(policy, dict) or set(policy) != {"depends_on", "owner_id", "owner_type", "policy_id"}:
            issues.append({"code": "policy.shape", "path": path, "message": "policy keys differ"})
            continue
        policy_id = policy.get("policy_id")
        if not isinstance(policy_id, str) or not POLICY_ID.fullmatch(policy_id) or policy_id in by_id:
            issues.append({"code": "policy.id", "path": path, "message": "policy ID is invalid or duplicate"})
            continue
        by_id[policy_id] = policy
        owner_type, owner_id = policy.get("owner_type"), policy.get("owner_id")
        if owner_type == "card":
            if owner_id not in cards:
                issues.append({"code": "policy.owner-missing", "path": path, "message": "card owner is missing"})
        elif owner_type == "machine":
            if not isinstance(owner_id, str) or owner_id.startswith("/") or ".." in Path(owner_id).parts or not (ROOT / owner_id).is_file():
                issues.append({"code": "policy.owner-missing", "path": path, "message": "machine owner is unsafe or missing"})
        else:
            issues.append({"code": "policy.owner-type", "path": path, "message": "owner type is invalid"})
        depends = policy.get("depends_on")
        if not isinstance(depends, list) or any(not isinstance(item, str) for item in depends) or len(depends) != len(set(depends)):
            issues.append({"code": "policy.depends", "path": path, "message": "depends_on is invalid"})
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(policy_id: str) -> None:
        if policy_id in visiting:
            issues.append({"code": "policy.cycle", "path": policy_id, "message": "policy graph contains a cycle"})
            return
        if policy_id in visited:
            return
        visiting.add(policy_id)
        for target in by_id[policy_id].get("depends_on", []):
            if target not in by_id:
                issues.append({"code": "policy.dependency-missing", "path": policy_id, "message": f"unknown dependency: {target}"})
            else:
                visit(target)
        visiting.remove(policy_id)
        visited.add(policy_id)

    for policy_id in sorted(by_id):
        visit(policy_id)
    return issues


def main() -> int:
    try:
        issues = validate(load_json(REGISTRY), load_json(MANIFEST))
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    return 0 if not issues else 2


if __name__ == "__main__":
    sys.exit(main())
