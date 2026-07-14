#!/usr/bin/env python3
"""Perform the one-time deterministic writing plan-state 1.0 to 1.1 migration."""

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

from _plan_state import PlanInputError, canonical_state_hash, load_json


HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class MigrationError(ValueError):
    pass


def _canonical_hash(value: dict[str, Any], excluded: str) -> str:
    clean = dict(value)
    clean.pop(excluded, None)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _decision_provenance(decision: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> str | None:
    refs = decision.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        return None
    resolved = [evidence.get(ref) for ref in refs if isinstance(ref, str)]
    if len(resolved) != len(refs) or any(item is None for item in resolved):
        return None
    artifacts = [item.get("artifact_ref") for item in resolved if isinstance(item, dict)]
    if len(artifacts) == len(resolved) and all(isinstance(ref, str) and ref.startswith("source:") for ref in artifacts):
        return "repository"
    if len(artifacts) == len(resolved) and all(isinstance(ref, str) and ref.startswith("artifact:design-audit/") for ref in artifacts):
        return "design_audit"
    return None


def migrate_plan_state(state: dict[str, Any], *, policy_bundle_hash: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if state.get("schema_version") != "1.0":
        raise MigrationError("only plan-state schema 1.0 can be migrated")
    if not HASH_RE.fullmatch(policy_bundle_hash):
        raise MigrationError("policy_bundle_hash must be sha256:<64 lowercase hex>")
    if "execution_policy" in state or "closure_contract_ref" in state:
        raise MigrationError("v1 input contains v1.1-only fields")
    migrated = deepcopy(state)
    migrated["schema_version"] = "1.1"
    migrated["execution_policy"] = "standard"
    source = migrated.get("source")
    if not isinstance(source, dict):
        raise MigrationError("v1 source object is missing")
    source["policy_bundle_hash"] = policy_bundle_hash
    for node in migrated.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node["constraint_refs"] = []
        node["corner_refs"] = []
        node["verifier_requirement_refs"] = []

    evidence = {
        item.get("id"): item
        for item in migrated.get("evidence", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    has_migration_boundary = any(
        isinstance(node, dict) and node.get("kind") in {"migration", "release"}
        for node in migrated.get("nodes", [])
    )
    unresolved: list[dict[str, str]] = []
    for decision in migrated.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        decision_id = decision.get("id") if isinstance(decision.get("id"), str) else "<unknown>"
        provenance = _decision_provenance(decision, evidence)
        if provenance is None:
            decision.pop("provenance", None)
            unresolved.append({"decision_id": decision_id, "field": "provenance", "reason": "no explicit repository or design-audit source"})
        else:
            decision["provenance"] = provenance
        decision["materiality"] = "medium"
        decision["reversibility"] = "migration_required" if has_migration_boundary or decision.get("change_action") in {"delete", "replace"} else "local"
        decision["contract_effect"] = "none"

    migrated["content_hash"] = canonical_state_hash(migrated)
    report: dict[str, Any] = {
        "schema_version": "plan-state-migration-report/1.0",
        "source_schema_version": "1.0",
        "target_schema_version": "1.1",
        "plan_id": migrated.get("plan_id"),
        "source_state_hash": canonical_state_hash(state),
        "state_hash": migrated["content_hash"],
        "changes": [
            "execution_policy=standard",
            "source.policy_bundle_hash added from caller binding",
            "node contract reference arrays added empty",
            "decision provenance/materiality/reversibility/contract_effect migrated",
        ],
        "unresolved": unresolved,
    }
    report["report_hash"] = _canonical_hash(report, "report_hash")
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
    except (OSError, PlanInputError) as exc:
        raise MigrationError(str(exc)) from exc
    if not isinstance(value, dict):
        raise MigrationError("plan state must be a JSON object")
    migrated, report = migrate_plan_state(value, policy_bundle_hash=policy_bundle_hash)
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
    return {"ok": True, "output": str(output), "report": str(report_output), "state_hash": migrated["content_hash"], "report_hash": report["report_hash"], "unresolved": report["unresolved"]}


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
        print(json.dumps({"ok": False, "error": {"code": "plan.migration", "message": str(exc)}}, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
