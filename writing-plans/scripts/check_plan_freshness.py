#!/usr/bin/env python3
"""Check source, scope, evidence, snapshot, and capsule freshness for plan state."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any

from _plan_state import PlanInputError, VERIFIER_REF_SCHEMES, canonical_state_hash, capsule_source_hash, file_hash, load_json, validate_against_schema

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "plan-state.schema.json"


def _now(value: str | None) -> datetime:
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _git(repository: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(["git", "-C", str(repository), *args], capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def _resolve_repository(state_path: Path, state: dict[str, Any], override: Path | None) -> Path:
    if override:
        return override.resolve()
    configured = Path(state["source"]["repository"])
    return configured.resolve() if configured.is_absolute() else (Path.cwd() / configured).resolve()


def _local_artifact(ref: str, repository: Path) -> Path | None:
    if ref.startswith("file:"):
        raw = ref[5:]
    elif ":" in ref.split("/", 1)[0]:
        return None
    else:
        raw = ref
    path = Path(raw)
    return path if path.is_absolute() else repository / path


def _symbol_exists(path: Path, symbol: str) -> bool:
    terminal = re.split(r"[.:#]+", symbol)[-1]
    if not terminal:
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(terminal)}(?![A-Za-z0-9_])", text) is not None


def _verifier_ref_issue(command_ref: Any, repository: Path) -> str | None:
    if not isinstance(command_ref, str):
        return "command verifier has no reference"
    scheme, separator, target = command_ref.partition(":")
    target = target.strip()
    if separator != ":" or scheme not in VERIFIER_REF_SCHEMES or not target:
        return "command verifier reference is not a supported namespace:target"
    if scheme in {"path", "script", "schema"}:
        raw_path = target.split("#", 1)[0]
        path = Path(raw_path)
        resolved = path if path.is_absolute() else repository / path
        return None if resolved.is_file() else f"verifier target is not a file: {resolved}"
    if scheme in {"pytest", "test"}:
        raw_path = target.split("::", 1)[0]
        if "/" not in raw_path and not raw_path.endswith(".py"):
            return None  # A non-empty project-defined logical target remains structurally resolvable.
        path = Path(raw_path)
        resolved = path if path.is_absolute() else repository / path
        return None if resolved.is_file() else f"test target is not a file: {resolved}"
    try:
        executable = shlex.split(target)[0]
    except (ValueError, IndexError):
        return "command verifier target cannot be parsed"
    if "/" in executable:
        path = Path(executable)
        resolved = path if path.is_absolute() else repository / path
        return None if resolved.is_file() else f"command path is not a file: {resolved}"
    return None if shutil.which(executable) else f"command executable is unavailable: {executable}"


def propagate_affected(
    state: dict[str, Any],
    changed_refs: set[str],
    *,
    changed_fields: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Compute semantic plan impact without mutating canonical state."""
    changed_fields = changed_fields or {}
    adjacency: dict[str, set[str]] = {}
    explicit_pairs: set[tuple[str, str]] = set()

    def connect(source: str, target: str) -> None:
        if source and target and ":" not in source:
            adjacency.setdefault(source, set()).add(target)

    semantic_kinds = {"control", "data", "evidence", "invariant", "effect", "resource", "approval"}
    for edge in state.get("edges", []):
        if edge.get("kind") not in semantic_kinds:
            continue
        source, target = edge.get("from"), edge.get("to")
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        explicit_pairs.add((source, target))
        fields = changed_fields.get(source, set())
        sensitivity = set(edge.get("sensitivity", {}).get("fields", []))
        if source in changed_fields and sensitivity and fields.isdisjoint(sensitivity):
            continue
        connect(source, target)

    for collection in ("facts", "decisions"):
        for item in state.get(collection, []):
            for evidence_ref in item.get("evidence_refs", []):
                connect(evidence_ref, item["id"])
    for node in state.get("nodes", []):
        for dependency in node.get("depends_on", []):
            connect(dependency, node["id"])
        for input_ref in node.get("inputs", []):
            if (input_ref, node["id"]) not in explicit_pairs:
                connect(input_ref, node["id"])
        for output_ref in node.get("outputs", []):
            connect(node["id"], output_ref)

    affected = set(changed_refs)
    queue = list(changed_refs)
    while queue:
        current = queue.pop(0)
        for target in sorted(adjacency.get(current, set())):
            if target not in affected:
                affected.add(target)
                queue.append(target)

    all_ids = {"source", "scope", "plan"}
    for collection in ("global_invariants", "facts", "decisions", "evidence", "nodes", "edges", "risks", "gaps", "approvals", "snapshots"):
        all_ids.update(item.get("id") for item in state.get(collection, []) if item.get("id"))
    all_ids.update(item.get("policy_id") for item in state.get("policy_claims", []) if item.get("policy_id"))
    escalation_reasons: list[str] = []
    if affected & {"source", "scope", "plan"}:
        escalation_reasons.append("source_scope_or_plan_identity_changed")
    invariant_by_id = {item.get("id"): item for item in state.get("global_invariants", []) if isinstance(item, dict)}
    if any(ref.startswith("I-") and invariant_by_id.get(ref, {}).get("locality") == "global" for ref in affected):
        escalation_reasons.append("global_invariant_changed")
    return {
        "affected_ids": sorted(affected),
        "preserved_ids": sorted(all_ids - affected),
        "repair_type": "global_or_parent_replan" if escalation_reasons else "local",
        "escalation_reasons": escalation_reasons,
    }


def check_freshness(
    state_path: Path,
    *,
    schema_path: Path = DEFAULT_SCHEMA,
    repository_override: Path | None = None,
    current_scope_hash: str | None = None,
    now_value: str | None = None,
    changed_refs: set[str] | None = None,
    changed_fields: dict[str, set[str]] | None = None,
    current_policy_bundle_hash: str | None = None,
    current_bundle_id: str | None = None,
    current_reference_manifest_hash: str | None = None,
    current_policy_hashes: dict[str, str] | None = None,
    current_card_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        state = load_json(state_path)
        schema = load_json(schema_path)
    except (OSError, PlanInputError) as exc:
        return {"status": "stale", "affected_ids": ["plan"], "issues": [{"id": "plan", "kind": "invalid_input", "message": str(exc)}]}
    schema_errors = validate_against_schema(state, schema)
    if schema_errors:
        return {"status": "stale", "affected_ids": ["plan"], "issues": [{"id": "plan", "kind": "invalid_schema", "message": item.message, "path": item.path} for item in schema_errors]}

    repository = _resolve_repository(state_path, state, repository_override)
    observed_now = _now(now_value)
    issues: list[dict[str, str]] = []
    global_stale = False
    policy_root_stale = False
    declared_changed_refs = set(changed_refs or set()) | set((changed_fields or {}).keys())

    def add(object_id: str, kind: str, message: str, *, global_issue: bool = False) -> None:
        nonlocal global_stale
        issues.append({"id": object_id, "kind": kind, "message": message})
        global_stale = global_stale or global_issue

    def add_policy_root(kind: str, message: str) -> None:
        nonlocal policy_root_stale
        policy_root_stale = True
        add("policy", kind, message, global_issue=True)

    source_identity = state.get("source", {})
    if current_bundle_id is not None and source_identity.get("bundle_id") != current_bundle_id:
        add("plan", "bundle_changed", "current bundle identity differs from the plan binding", global_issue=True)
    if current_policy_bundle_hash is not None and state.get("source", {}).get("policy_bundle_hash") != current_policy_bundle_hash:
        add_policy_root("policy_bundle_changed", "current policy bundle differs from the plan binding")
    if current_reference_manifest_hash is not None and source_identity.get("reference_manifest_hash") != current_reference_manifest_hash:
        capsule_ids = [item.get("id") for item in state.get("snapshots", []) if item.get("kind") == "capsule" and item.get("id")]
        for capsule_id in capsule_ids or ["context"]:
            add(capsule_id, "card_manifest_changed", "card manifest drift invalidates context projection only")
    for claim in state.get("policy_claims", []):
        policy_id = claim.get("policy_id")
        if current_policy_hashes and policy_id in current_policy_hashes and claim.get("policy_hash") != current_policy_hashes[policy_id]:
            add(policy_id, "policy_hash_changed", "stable policy ID resolves to a different hash")
    if current_card_hashes:
        for snapshot in state.get("snapshots", []):
            if snapshot.get("kind") != "capsule":
                continue
            if any(current_card_hashes.get(ref.get("card_id"), ref.get("card_hash")) != ref.get("card_hash") for ref in snapshot.get("card_refs", [])):
                add(snapshot.get("id", "context"), "card_hash_changed", "card hash drift invalidates context projection only")
    for changed_ref in sorted(declared_changed_refs):
        add(changed_ref, "declared_changed", "caller declared this plan ref changed", global_issue=changed_ref in {"source", "scope", "plan"} or changed_ref.startswith("I-"))

    base_revision = state["source"]["base_revision"]
    current_revision: str | None = None
    code, output = _git(repository, "rev-parse", "HEAD") if repository.exists() else (1, "")
    if code == 0:
        current_revision = output
        if base_revision == "explicit-unversioned":
            add("source", "versioning_available", "state is marked unversioned but repository has a revision", global_issue=True)
        elif base_revision != current_revision:
            ancestor_code, _ = _git(repository, "merge-base", "--is-ancestor", base_revision, current_revision)
            if ancestor_code != 0:
                add("source", "revision_diverged", f"base {base_revision} is not an ancestor of {current_revision}", global_issue=True)
            else:
                add("source", "revision_advanced", f"repository advanced from {base_revision} to {current_revision}")

    if current_scope_hash and state["source"]["scope_hash"] != current_scope_hash:
        add("scope", "scope_hash_changed", "current scope hash differs from plan", global_issue=True)
    if state.get("content_hash") and state["content_hash"] != canonical_state_hash(state):
        add("plan", "state_hash_changed", "content_hash does not match canonical plan state", global_issue=True)

    for snapshot in state.get("snapshots", []):
        snapshot_id = snapshot["id"]
        path = Path(snapshot["path"])
        resolved = path if path.is_absolute() else repository / path
        if not resolved.exists():
            add(snapshot_id, "path_missing", f"snapshot path does not exist: {resolved}")
            continue
        requires_file = snapshot.get("kind") != "path" or snapshot.get("content_hash") is not None or snapshot.get("line_start") is not None or snapshot.get("line_end") is not None
        if requires_file and not resolved.is_file():
            add(snapshot_id, "snapshot_not_file", f"snapshot kind requires a file: {resolved}")
            continue
        if snapshot.get("line_start") or snapshot.get("line_end"):
            line_count = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
            start = snapshot.get("line_start")
            end = snapshot.get("line_end")
            if (start and start > line_count) or (end and end > line_count) or (start and end and end < start):
                add(snapshot_id, "line_drift", "line-sensitive snapshot no longer resolves to the declared range")
        if snapshot.get("kind") == "symbol":
            symbol = snapshot.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                add(snapshot_id, "symbol_unbound", "symbol snapshot has no identity token")
            elif not _symbol_exists(resolved, symbol):
                add(snapshot_id, "symbol_missing", f"symbol no longer resolves in bound path: {symbol}")
        if snapshot.get("content_hash") and snapshot["content_hash"] != file_hash(resolved):
            add(snapshot_id, "content_changed", "snapshot content hash differs")
        if current_revision and snapshot.get("source_revision") not in {None, current_revision}:
            add(snapshot_id, "snapshot_revision_changed", "snapshot revision differs from current checkout")
        if snapshot.get("kind") == "capsule" and (
            snapshot.get("plan_state_hash") != capsule_source_hash(state)
            or snapshot.get("plan_state_version") != state.get("state_version")
        ):
            add(snapshot_id, "capsule_stale", "capsule was generated from another canonical state hash or version")

    for node in state.get("nodes", []):
        if node.get("status") != "done":
            continue
        verifier = node.get("verifier", {})
        if verifier.get("kind") != "command" and verifier.get("command_ref") is None:
            continue
        resolution_issue = _verifier_ref_issue(verifier.get("command_ref"), repository)
        if resolution_issue:
            add(node["id"], "verifier_unresolved", resolution_issue)

    for evidence in state.get("evidence", []):
        evidence_id = evidence["id"]
        if evidence.get("status") in {"stale", "invalidated"}:
            add(evidence_id, "evidence_status", f"evidence is {evidence['status']}")
        policy = evidence.get("freshness_policy", {})
        if policy.get("kind") == "source_bound" and evidence.get("status") == "observed":
            expected_revision = current_revision or base_revision
            if not evidence.get("source_revision"):
                add(evidence_id, "evidence_revision_unbound", "observed source-bound evidence has no revision")
            elif evidence["source_revision"] != expected_revision:
                add(evidence_id, "evidence_revision_changed", "source-bound evidence revision differs")
        if policy.get("kind") == "external_time_bound" and evidence.get("status") == "observed":
            if not policy.get("max_age_hours") and not policy.get("expected_version"):
                add(evidence_id, "evidence_policy_unbound", "external freshness policy has no time or version bound")
            if policy.get("max_age_hours"):
                if not evidence.get("observed_at"):
                    add(evidence_id, "evidence_time_unbound", "time-bound external evidence has no observed_at")
                else:
                    observed = datetime.fromisoformat(evidence["observed_at"].replace("Z", "+00:00"))
                    age_hours = (observed_now - observed).total_seconds() / 3600
                    if age_hours > float(policy["max_age_hours"]):
                        add(evidence_id, "evidence_expired", f"evidence age {age_hours:.2f}h exceeds {policy['max_age_hours']}h")
        if evidence.get("status") == "observed" and policy.get("expected_version"):
            if not evidence.get("external_version"):
                add(evidence_id, "evidence_version_unbound", "version-bound external evidence has no observed version")
            elif evidence["external_version"] != policy["expected_version"]:
                add(evidence_id, "evidence_version_changed", "external evidence version differs from caller policy")
        artifact_ref = evidence.get("artifact_ref")
        if artifact_ref and (evidence.get("content_hash") or evidence.get("artifact_mtime_ns") is not None):
            local = _local_artifact(artifact_ref, repository)
            if local is not None:
                if not local.exists():
                    add(evidence_id, "artifact_missing", f"artifact does not exist: {local}")
                elif not local.is_file():
                    add(evidence_id, "artifact_not_file", f"content-bound artifact is not a file: {local}")
                else:
                    if evidence.get("content_hash") and evidence["content_hash"] != file_hash(local):
                        add(evidence_id, "artifact_changed", "artifact content hash differs")
                    if evidence.get("artifact_mtime_ns") is not None and evidence["artifact_mtime_ns"] != local.stat().st_mtime_ns:
                        add(evidence_id, "artifact_mtime_changed", "artifact mtime differs from the observed binding")

    directly_stale = sorted({item["id"] for item in issues})
    impact = propagate_affected(state, set(directly_stale), changed_fields=changed_fields)
    if policy_root_stale:
        all_nodes = sorted(node.get("id") for node in state.get("nodes", []) if isinstance(node.get("id"), str))
        impact["affected_ids"] = sorted(set(impact["affected_ids"]) | set(all_nodes))
        impact["preserved_ids"] = sorted(set(impact["preserved_ids"]) - set(all_nodes))
        impact["repair_type"] = "global_or_parent_replan"
        impact["escalation_reasons"] = sorted(set(impact["escalation_reasons"] + ["policy_root_changed"]))
    if not issues:
        status = "fresh"
    elif global_stale:
        status = "stale"
    else:
        status = "partially_stale"
    return {
        "status": status,
        "plan_id": state.get("plan_id"),
        "state_hash": canonical_state_hash(state),
        "repository": str(repository),
        "current_revision": current_revision,
        "directly_stale_ids": directly_stale,
        "affected_ids": impact["affected_ids"],
        "preserved_ids": impact["preserved_ids"],
        "repair_type": "global_or_parent_replan" if global_stale else impact["repair_type"],
        "escalation_reasons": sorted(set(impact["escalation_reasons"] + (["freshness_global_issue"] if global_stale else []))),
        "issues": issues,
    }


def _changed_field(value: str) -> tuple[str, str]:
    ref, separator, field = value.partition("=")
    if not separator or not ref or not field:
        raise argparse.ArgumentTypeError("changed field must use REF=FIELD")
    return ref, field


def _identity_binding(value: str) -> tuple[str, str]:
    identity, separator, digest = value.partition("=")
    if not separator or not identity or not digest.startswith("sha256:"):
        raise argparse.ArgumentTypeError("identity binding must use ID=sha256:HASH")
    return identity, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--scope-hash")
    parser.add_argument("--policy-bundle-hash")
    parser.add_argument("--bundle-id")
    parser.add_argument("--reference-manifest-hash")
    parser.add_argument("--policy-hash", action="append", default=[], type=_identity_binding, metavar="POLICY_ID=HASH")
    parser.add_argument("--card-hash", action="append", default=[], type=_identity_binding, metavar="CARD_ID=HASH")
    parser.add_argument("--now", help="deterministic ISO timestamp for tests")
    parser.add_argument("--changed-ref", action="append", default=[], help="plan ID declared stale; repeatable")
    parser.add_argument("--changed-field", action="append", default=[], type=_changed_field, metavar="REF=FIELD", help="field-sensitive change declaration; repeatable")
    args = parser.parse_args(argv)
    changed_fields: dict[str, set[str]] = {}
    for ref, field in args.changed_field:
        changed_fields.setdefault(ref, set()).add(field)
    result = check_freshness(
        args.state,
        schema_path=args.schema,
        repository_override=args.repository,
        current_scope_hash=args.scope_hash,
        now_value=args.now,
        changed_refs=set(args.changed_ref),
        changed_fields=changed_fields,
        current_policy_bundle_hash=args.policy_bundle_hash,
        current_bundle_id=args.bundle_id,
        current_reference_manifest_hash=args.reference_manifest_hash,
        current_policy_hashes=dict(args.policy_hash),
        current_card_hashes=dict(args.card_hash),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"fresh": 0, "partially_stale": 1, "stale": 2}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
