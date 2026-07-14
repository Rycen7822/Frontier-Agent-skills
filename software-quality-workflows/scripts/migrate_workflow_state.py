#!/usr/bin/env python3
"""Perform the one-time deterministic standard workflow-state 1.0 to 1.1 migration."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from _workflow_state import InputError, canonical_hash, load_json


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "references" / "owner-registry.json"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VIRTUAL_PRIMARY_MAP = {
    "direct-change": "change-execution",
    "planned-change": "change-execution",
    "writing-plans": "change-execution",
    "long-document-segmented-writing": "change-execution",
    "github-workflows": "change-execution",
}


class MigrationError(ValueError):
    pass


def _report_hash(value: dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("report_hash", None)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _registry() -> dict[str, dict[str, Any]]:
    try:
        value = load_json(REGISTRY_PATH)
    except (OSError, InputError) as exc:
        raise MigrationError(f"cannot load owner registry: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("owners"), list):
        raise MigrationError("owner registry is malformed")
    return {row["id"]: row for row in value["owners"] if isinstance(row, dict) and isinstance(row.get("id"), str)}


def _preferred_phase(state: dict[str, Any]) -> str:
    if state.get("request_mode") == "diagnose":
        return "DIAGNOSING"
    if state.get("status") in {"closing", "closed"}:
        return "SIGNING_OFF"
    if state.get("status") == "open":
        return "PLANNING"
    return "SEARCHING"


def _owner_phase(row: dict[str, Any], preferred: str) -> str:
    phases = row.get("phases", [])
    if preferred in phases:
        return preferred
    if not phases:
        raise MigrationError(f"owner has no phase: {row.get('id')}")
    return sorted(phases)[0]


def _ordered_dependency_closure(seed: list[str], owners: dict[str, dict[str, Any]]) -> list[str]:
    result: list[str] = []
    pending = list(seed)
    while pending:
        owner_id = pending.pop(0)
        if owner_id in result:
            continue
        if owner_id not in owners:
            raise MigrationError(f"v1 active owner is not representable in registry 2.0: {owner_id}")
        result.append(owner_id)
        for dependency in owners[owner_id].get("requires", []):
            if dependency not in result and dependency not in pending:
                pending.append(dependency)
    return result


def migrate_state(state: dict[str, Any], *, policy_bundle_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if state.get("schema_version") != "1.0":
        raise MigrationError("only workflow-state schema 1.0 can be migrated")
    if not HASH_RE.fullmatch(policy_bundle_hash):
        raise MigrationError("policy_bundle_hash must be sha256:<64 lowercase hex>")
    if any(field in state for field in ("execution_policy", "policy_bundle_hash", "closure_run")):
        raise MigrationError("v1 input contains v1.1-only fields")
    active = state.get("active_owners")
    if not isinstance(active, dict):
        raise MigrationError("v1 active_owners object is missing")
    old_primary = active.get("primary")
    if not isinstance(old_primary, str):
        raise MigrationError("v1 primary owner is missing")

    owners = _registry()
    primary = VIRTUAL_PRIMARY_MAP.get(old_primary, old_primary)
    primary_row = owners.get(primary)
    if primary_row is None or primary_row.get("authority") != "normative_owner":
        raise MigrationError(f"v1 primary owner cannot become a registry 2.0 primary: {old_primary}")

    seed = [primary]
    for field in ("domain", "evidence"):
        values = active.get(field, [])
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise MigrationError(f"v1 active_owners.{field} must be a string array")
        for owner_id in values:
            mapped = VIRTUAL_PRIMARY_MAP.get(owner_id, owner_id)
            if mapped not in seed:
                seed.append(mapped)
    expanded = _ordered_dependency_closure(seed, owners)

    normative = [owner_id for owner_id in expanded if owner_id != primary and owners[owner_id].get("authority") == "normative_owner"]
    companions = [owner_id for owner_id in expanded if owners[owner_id].get("authority") == "companion"]
    if len(normative) > 8 or len(companions) > 6 or len(expanded) > 12:
        raise MigrationError("migrated active owner stack exceeds workflow-state 1.1 reference limits")
    active_set = set(expanded)
    for owner_id in expanded:
        conflicts = active_set.intersection(owners[owner_id].get("conflicts_with", []))
        if conflicts:
            raise MigrationError(f"migrated active owner stack conflicts: {owner_id}, {sorted(conflicts)}")

    reasons_by_path: dict[str, str] = {}
    loaded_v1 = active.get("loaded_references", [])
    if not isinstance(loaded_v1, list):
        raise MigrationError("v1 loaded_references must be an array")
    for item in loaded_v1:
        if not isinstance(item, dict):
            raise MigrationError("v1 loaded reference must be an object")
        path, reason = item.get("path"), item.get("reason_code")
        if isinstance(path, str) and isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]+", reason):
            reasons_by_path[path] = reason

    preferred_phase = _preferred_phase(state)
    loaded = []
    for owner_id in expanded:
        row = owners[owner_id]
        loaded.append(
            {
                "owner_id": owner_id,
                "path": row["path"],
                "reason_code": reasons_by_path.get(row["path"], "migration_dependency_required" if owner_id != primary else "migration_primary_normalized"),
                "phase": _owner_phase(row, preferred_phase),
            }
        )

    migrated = deepcopy(state)
    migrated["schema_version"] = "1.1"
    migrated["execution_policy"] = "standard"
    migrated["policy_bundle_hash"] = policy_bundle_hash
    migrated.pop("closure_run", None)
    migrated["active_owners"] = {
        "primary": primary,
        "normative": normative,
        "companions": companions,
        "loaded_references": loaded,
    }
    migrated.pop("state_hash", None)

    report: dict[str, Any] = {
        "schema_version": "workflow-state-migration-report/1.0",
        "source_schema_version": "1.0",
        "target_schema_version": "1.1",
        "workflow_id": migrated.get("workflow_id"),
        "source_state_hash": canonical_hash(state),
        "new_state_hash": canonical_hash(migrated),
        "changes": [
            "execution_policy=standard",
            "policy_bundle_hash added from caller binding",
            "virtual primary normalized to registry 2.0 owner",
            "active owner authority buckets and dependency closure rebuilt",
            "loaded owner/path/reason/phase bindings rebuilt",
        ],
        "unresolved": [],
    }
    report["report_hash"] = _report_hash(report)
    return migrated, report


def _temporary_payload(path: Path, value: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return temporary


def write_migration(
    source_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    *,
    policy_bundle_hash: str,
) -> dict[str, Any]:
    source, output, report_output = Path(source_path), Path(output_path), Path(report_path)
    resolved = {source.resolve(), output.resolve(), report_output.resolve()}
    if len(resolved) != 3:
        raise MigrationError("source, output, and report paths must be distinct")
    if output.exists() or report_output.exists():
        raise MigrationError("refusing to overwrite migration output or report")
    try:
        value = load_json(source)
    except (OSError, InputError) as exc:
        raise MigrationError(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationError("workflow state must be a JSON object")
    migrated, report = migrate_state(value, policy_bundle_hash=policy_bundle_hash)
    state_temp = _temporary_payload(output, migrated)
    report_temp = _temporary_payload(report_output, report)
    state_linked = False
    report_linked = False
    try:
        os.link(state_temp, output)
        state_linked = True
        try:
            os.link(report_temp, report_output)
            report_linked = True
        except FileExistsError as exc:
            raise MigrationError("refusing to overwrite migration report") from exc
    except FileExistsError as exc:
        raise MigrationError("refusing to overwrite migration output") from exc
    finally:
        state_temp.unlink(missing_ok=True)
        report_temp.unlink(missing_ok=True)
        if state_linked and not report_linked:
            output.unlink(missing_ok=True)
    return {
        "ok": True,
        "output": str(output),
        "report": str(report_output),
        "new_state_hash": report["new_state_hash"],
        "report_hash": report["report_hash"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--policy-bundle-hash", required=True)
    args = parser.parse_args(argv)
    try:
        result = write_migration(args.source, args.output, args.report, policy_bundle_hash=args.policy_bundle_hash)
    except (MigrationError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "workflow.migration", "message": str(exc)}}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
