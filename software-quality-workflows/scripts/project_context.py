#!/usr/bin/env python3
"""Render a bounded, sensitivity-aware workflow frontier projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from _closure import eligible_events
from _workflow_state import InputError, canonical_hash, contains_secret_like, load_json, redact_secret_like


def _artifact_summary(item: dict[str, Any]) -> str:
    artifact_id = item.get("id", "artifact")
    if item.get("sensitive") or contains_secret_like(item):
        return f"- {artifact_id}: [SENSITIVE_POINTER] {item.get('artifact_ref', 'controlled-pointer')} ({item.get('freshness', 'unknown')})"
    return f"- {artifact_id}: {item.get('claim', '')} ({item.get('freshness', 'unknown')}; {item.get('artifact_ref', 'no-pointer')})"


def project_context(state: dict[str, Any], *, budget_chars: int = 6000) -> tuple[str, dict[str, Any]]:
    if budget_chars < 500:
        raise ValueError("budget_chars must be at least 500")
    nodes = {item["id"]: item for item in state.get("nodes", [])}
    artifacts = {item["id"]: item for item in state.get("artifacts", [])}
    verifiers = {item["id"]: item for item in state.get("verifiers", [])}
    approvals = {item["id"]: item for item in state.get("authority", {}).get("approvals", [])}
    frontier = [ref for ref in state.get("frontier", []) if ref in nodes]

    mandatory: list[str] = [
        "# Workflow frontier",
        "",
        f"workflow: {state.get('workflow_id')} / {state.get('mode')} / {state.get('request_mode')} / {state.get('status')}",
        f"state_version: {state.get('state_version')}",
        f"state_hash: {canonical_hash(state)}",
        f"source: {state.get('source', {}).get('observed_revision')} / scope {state.get('source', {}).get('scope_hash')}",
        f"authority: {state.get('authority', {}).get('risk_ceiling')}; external_writes={state.get('authority', {}).get('external_writes')}; destructive={state.get('authority', {}).get('destructive_actions')}",
        f"protected_paths: {', '.join(state.get('scope', {}).get('protected_paths', [])) or 'none'}",
        "",
    ]
    included: set[str] = set()
    closure_anchor_refs: list[str] = []
    run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else None
    if state.get("execution_policy") == "autonomous_closure" and run is not None:
        def binding_line(label: str, field: str) -> str:
            binding = run.get(field)
            if not isinstance(binding, dict):
                return f"{label}: not-bound"
            artifact_ref = binding.get("artifact_ref", "not-bound")
            if isinstance(artifact_ref, str):
                closure_anchor_refs.append(artifact_ref)
            suffix = f" epoch={binding.get('epoch')}" if "epoch" in binding else ""
            return f"{label}: {artifact_ref} {binding.get('content_hash', 'no-hash')}{suffix}"

        for field in ("active_candidate_refs", "active_counterexample_refs"):
            closure_anchor_refs.extend(item for item in run.get(field, []) if isinstance(item, str))
        for field in ("incumbent_candidate_ref", "terminal_certificate_ref"):
            if isinstance(run.get(field), str):
                closure_anchor_refs.append(run[field])
        budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
        mandatory.extend([
            "## Autonomous closure",
            f"phase: {run.get('phase')}",
            "transition authority: controller",
            f"eligible controller events: {', '.join(sorted(eligible_events(state))) or 'none'}",
            binding_line("contract", "contract_ref"),
            binding_line("baseline", "baseline_ref"),
            binding_line("verifier", "verifier_bundle_ref"),
            f"budget: iterations {budget.get('iterations_used')}/{budget.get('iterations_limit')}; evaluations {budget.get('candidate_evaluations_used')}/{budget.get('candidate_evaluations_limit')}; reviews {budget.get('review_rounds_used')}/{budget.get('review_rounds_limit')}",
            f"active candidates: {', '.join(run.get('active_candidate_refs', [])[:16]) or 'none'}",
            f"active counterexamples: {', '.join(run.get('active_counterexample_refs', [])[:16]) or 'none'}",
            f"incumbent: {run.get('incumbent_candidate_ref', 'none')}",
            "",
        ])
    mandatory.append("## Global invariants")

    active = state.get("active_owners") if isinstance(state.get("active_owners"), dict) else {}
    loaded_refs: list[str] = []
    unload_refs: list[str] = []
    current_phase = run.get("phase") if run is not None else None
    for item in active.get("loaded_references", []) if isinstance(active.get("loaded_references"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        if current_phase is None or item.get("phase") == current_phase:
            loaded_refs.append(item["path"])
        else:
            unload_refs.append(item["path"])
    for invariant in state.get("global_invariants", []):
        included.add(invariant["id"])
        statement = "[SENSITIVE_POINTER]" if invariant.get("sensitive") or contains_secret_like(invariant) else invariant.get("statement", "")
        mandatory.append(f"- {invariant['id']} ({invariant.get('status')}): {statement}")

    mandatory.extend(["", "## Loaded references"])
    mandatory.extend(f"- {path}" for path in loaded_refs[:12])
    if not loaded_refs:
        mandatory.append("- none")

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
        mandatory.extend(
            [
                f"### {node_id}",
                f"Objective: {objective}",
                f"Inputs: {', '.join(node.get('input_refs', [])) or 'none'}",
                f"Allowed reads: {reads}",
                f"Allowed writes: {writes}",
                f"Resources: {resources}",
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

    text = mandatory_text
    omitted: list[str] = []
    if optional:
        heading = "\n## Recent relevant failure and optional evidence\n"
        if len(text) + len(heading) <= budget_chars:
            text += heading
        else:
            omitted.extend(ref for ref, _ in optional)
            optional = []
    for ref, block in optional:
        candidate = text + block + "\n"
        if len(candidate) <= budget_chars:
            text = candidate
            included.add(ref)
        else:
            omitted.append(ref)

    for node_id in nodes:
        if node_id not in frontier and node_id not in omitted:
            omitted.append(node_id)
    text = redact_secret_like(text)
    mandatory_exceeded = len(mandatory_text) > budget_chars
    if len(text) > budget_chars:
        marker = "\n[context truncated at hard character budget]\n"
        retained: list[str] = []
        used = 0
        for line in text.splitlines(keepends=True):
            if used + len(line) + len(marker) > budget_chars:
                break
            retained.append(line)
            used += len(line)
        text = "".join(retained).rstrip() + marker
        if len(text) > budget_chars:
            text = text[:budget_chars]
    metadata = {
        "workflow_id": state.get("workflow_id"),
        "state_version": state.get("state_version"),
        "state_hash": canonical_hash(state),
        "budget_chars": budget_chars,
        "actual_chars": len(text),
        "budget_exceeded": mandatory_exceeded,
        "included_refs": sorted(included),
        "omitted_refs": sorted(set(omitted)),
        "requires_on_demand_read": bool(omitted),
        "omission_reason": "budget_or_non_frontier_state" if omitted else None,
        "loaded_refs": sorted(set(loaded_refs)),
        "unload_refs": sorted(set(unload_refs)),
        "closure_anchor_refs": sorted(set(closure_anchor_refs)),
    }
    return text, metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--budget-chars", type=int, default=6000)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args(argv)
    try:
        state = load_json(args.state)
        text, metadata = project_context(state, budget_chars=args.budget_chars)
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
