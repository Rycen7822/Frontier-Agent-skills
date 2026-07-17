#!/usr/bin/env python3
"""Render a bounded, sensitivity-aware workflow frontier projection."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from _workflow_state import InputError, canonical_hash, contains_secret_like, load_json, redact_secret_like


ROOT = Path(__file__).resolve().parents[1]
CARD_MANIFEST = ROOT / "registries" / "reference-cards.manifest.json"


def _artifact_summary(item: dict[str, Any]) -> str:
    artifact_id = item.get("id", "artifact")
    if item.get("sensitive") or contains_secret_like(item):
        return f"- {artifact_id}: [SENSITIVE_POINTER] {item.get('artifact_ref', 'controlled-pointer')} ({item.get('freshness', 'unknown')})"
    return f"- {artifact_id}: {item.get('claim', '')} ({item.get('freshness', 'unknown')}; {item.get('artifact_ref', 'no-pointer')})"


def project_context(
    state: dict[str, Any],
    *,
    budget_bytes: int = 8192,
    card_refs: list[dict[str, Any]],
    artifact_projections: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if type(budget_bytes) is not int or budget_bytes < 500:
        raise ValueError("budget_bytes must be an integer of at least 500")
    effective_budget = min(budget_bytes, 8192)
    if not isinstance(card_refs, list) or not 1 <= len(card_refs) <= 3:
        raise ValueError("card_refs must contain one to three exact card identities")
    manifest = load_json(CARD_MANIFEST)
    if state.get("bundle_id") != manifest.get("bundle_id"):
        raise ValueError("workflow bundle does not match the live card manifest")
    card_index = {item.get("card_id"): item.get("sha256") for item in manifest.get("cards", []) if isinstance(item, dict)}
    seen_cards: set[str] = set()
    for ref in card_refs:
        if not isinstance(ref, dict) or set(ref) != {"card_id", "card_hash"}:
            raise ValueError("card_refs must contain exact card_id/card_hash objects")
        if not isinstance(ref["card_id"], str) or ref["card_id"] in seen_cards or card_index.get(ref["card_id"]) != ref.get("card_hash"):
            raise ValueError("card_refs contain a stale, duplicate, or unknown identity")
        seen_cards.add(ref["card_id"])
    if not isinstance(artifact_projections, dict) or any(not isinstance(key, str) or not key or not isinstance(value, dict) for key, value in artifact_projections.items()):
        raise ValueError("artifact_projections must map projection IDs to objects")
    nodes = {item["id"]: item for item in state.get("nodes", [])}
    artifacts = {item["id"]: item for item in state.get("artifacts", [])}
    verifiers = {item["id"]: item for item in state.get("verifiers", [])}
    approvals = {item["id"]: item for item in state.get("authority", {}).get("approvals", [])}
    frontier = [ref for ref in state.get("frontier", []) if ref in nodes]
    state_hash = canonical_hash(state)
    projection_payload = {
        "state_hash": state_hash,
        "card_refs": card_refs,
        "artifact_projections": artifact_projections,
    }
    projection_hash = "sha256:" + sha256(json.dumps(projection_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    mandatory: list[str] = [
        "# Workflow frontier",
        "",
        f"workflow: {state.get('workflow_id')} / {state.get('mode')} / {state.get('request_mode')} / {state.get('status')}",
        f"state_version: {state.get('state_version')}",
        f"state_hash: {state_hash}",
        f"projection_hash: {projection_hash}",
        "cards: " + ", ".join(f"{item['card_id']}@{item['card_hash']}" for item in card_refs),
        "artifact projections: " + (", ".join(sorted(artifact_projections)) or "none"),
        f"source: {state.get('source', {}).get('observed_revision')} / scope {state.get('source', {}).get('scope_hash')}",
        f"authority: {state.get('authority', {}).get('risk_ceiling')}; external_writes={state.get('authority', {}).get('external_writes')}; destructive={state.get('authority', {}).get('destructive_actions')}",
        f"protected_paths: {', '.join(state.get('scope', {}).get('protected_paths', [])) or 'none'}",
        "",
    ]
    for projection_id in sorted(artifact_projections):
        value = redact_secret_like(json.dumps(artifact_projections[projection_id], ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        mandatory.append(f"projection {projection_id}: {value}")
    if artifact_projections:
        mandatory.append("")
    included: set[str] = set()
    mandatory.append("## Global invariants")

    for invariant in state.get("global_invariants", []):
        locality = invariant.get("locality")
        targets = set(invariant.get("targets", []))
        frontier_resources = {resource for node_id in frontier for resource in nodes[node_id].get("resource_set", [])}
        applies = locality == "global" or locality == "node_set" and bool(targets & set(frontier)) or locality == "resource_set" and bool(targets & frontier_resources)
        if not applies:
            continue
        included.add(invariant["id"])
        statement = "[SENSITIVE_POINTER]" if invariant.get("sensitive") or contains_secret_like(invariant) else invariant.get("statement", "")
        mandatory.append(f"- {invariant['id']} ({invariant.get('status')}): {statement}")

    mandatory.extend(["", "## Current frontier"])
    relevant_artifacts: list[str] = []
    for node_id in frontier:
        node = nodes[node_id]
        included.add(node_id)
        node_sensitive = bool(node.get("sensitive")) or contains_secret_like(node)
        objective = "[SENSITIVE_POINTER]" if node_sensitive else node.get("objective", "")
        reads = "[SENSITIVE_POINTER]" if node_sensitive else (", ".join(node.get("read_set", [])) or "none")
        writes = "[SENSITIVE_POINTER]" if node_sensitive else (", ".join(node.get("write_set", [])) or "none")
        resources = "[SENSITIVE_POINTER]" if node_sensitive else (", ".join(node.get("resource_set", [])) or "none")
        effects = "[SENSITIVE_POINTER]" if node_sensitive else (", ".join(node.get("effect_set", [])) or "none")
        mandatory.extend(
            [
                f"### {node_id}",
                f"Objective: {objective}",
                f"Inputs: {', '.join(node.get('input_refs', [])) or 'none'}",
                f"Allowed reads: {reads}",
                f"Allowed writes: {writes}",
                f"Resources: {resources}",
                f"Effects: {effects}",
                f"Side effect: {node.get('side_effect')}",
                f"Retry: {node.get('attempt_policy', {}).get('attempts_used')}/{node.get('attempt_policy', {}).get('max_attempts')} {node.get('attempt_policy', {}).get('idempotency')}",
            ]
        )
        approval_text = [f"{ref}={approvals.get(ref, {}).get('status', 'missing')}" for ref in node.get("required_approvals", [])]
        mandatory.append(f"Approvals: {', '.join(approval_text) or 'none'}")
        for verifier_ref in node.get("verifier_refs", []):
            verifier = verifiers.get(verifier_ref, {})
            claim = "[SENSITIVE_POINTER]" if node_sensitive else verifier.get("claim", "")
            mandatory.append(f"Verifier {verifier_ref}: {verifier.get('status', 'missing')} — {claim}")
        for ref in node.get("input_refs", []):
            if ref in artifacts and ref not in relevant_artifacts:
                relevant_artifacts.append(ref)

    mandatory.extend(["", "## Blocking evidence pointers"])
    if relevant_artifacts:
        for ref in relevant_artifacts:
            mandatory.append(_artifact_summary(artifacts[ref]))
            included.add(ref)
    else:
        mandatory.append("- none")
    mandatory_text = redact_secret_like("\n".join(mandatory).rstrip() + "\n")

    optional: list[tuple[str, str]] = []
    for failure in reversed(state.get("recent_failures", [])):
        summary = "[SENSITIVE_POINTER]" if failure.get("sensitive") or contains_secret_like(failure) else failure.get("summary", "")
        optional.append((failure["id"], f"- {failure['id']} ({failure.get('classification')}): {summary}; {failure.get('artifact_ref')}"))
    for artifact in state.get("artifacts", []):
        if artifact["id"] not in included:
            optional.append((artifact["id"], _artifact_summary(artifact)))

    mandatory_bytes = len(mandatory_text.encode("utf-8"))
    if mandatory_bytes > effective_budget:
        raise ValueError(f"mandatory context exceeds budget: {mandatory_bytes} > {effective_budget} bytes")
    text = mandatory_text
    omitted: list[str] = []
    if optional:
        heading = "\n## Recent relevant failure and optional evidence\n"
        if len((text + heading).encode("utf-8")) <= effective_budget:
            text += heading
        else:
            omitted.extend(ref for ref, _ in optional)
            optional = []
    for ref, block in optional:
        candidate = text + block + "\n"
        if len(candidate.encode("utf-8")) <= effective_budget:
            text = candidate
            included.add(ref)
        else:
            omitted.append(ref)

    for node_id in nodes:
        if node_id not in frontier and node_id not in omitted:
            omitted.append(node_id)
    text = redact_secret_like(text)
    metadata = {
        "workflow_id": state.get("workflow_id"),
        "state_version": state.get("state_version"),
        "state_hash": state_hash,
        "projection_hash": projection_hash,
        "card_refs": card_refs,
        "artifact_projection_ids": sorted(artifact_projections),
        "budget_bytes": effective_budget,
        "actual_bytes": len(text.encode("utf-8")),
        "mandatory_bytes": mandatory_bytes,
        "mandatory_truncation_count": 0,
        "included_refs": sorted(included),
        "omitted_refs": sorted(set(omitted)),
        "requires_on_demand_read": bool(omitted),
        "omission_reason": "budget_or_non_frontier_state" if omitted else None,
    }
    return text, metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--budget-bytes", type=int, default=8192)
    parser.add_argument("--card-ref", action="append", required=True, metavar="CARD_ID=SHA256")
    parser.add_argument("--artifact-projection", action="append", default=[], metavar="PROJECTION_ID=JSON_PATH")
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        card_refs = []
        for raw in args.card_ref:
            card_id, separator, card_hash = raw.partition("=")
            if not separator:
                raise ValueError("card refs must use CARD_ID=SHA256")
            card_refs.append({"card_id": card_id, "card_hash": card_hash})
        projections: dict[str, dict[str, Any]] = {}
        for raw in args.artifact_projection:
            projection_id, separator, path = raw.partition("=")
            if not separator or projection_id in projections:
                raise ValueError("artifact projections must use unique PROJECTION_ID=JSON_PATH")
            value = load_json(path)
            if not isinstance(value, dict):
                raise ValueError("artifact projection JSON must be an object")
            projections[projection_id] = value
        text, metadata = project_context(state, budget_bytes=args.budget_bytes, card_refs=card_refs, artifact_projections=projections)
    except (InputError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2
    print(text, end="")
    if args.metadata:
        args.metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(metadata, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
