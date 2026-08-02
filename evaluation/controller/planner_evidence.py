"""Verify planner-run evidence and expose transfer-ready deliverables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import (
    contained_file,
    json_object,
    load_json,
    verified_artifact,
    verify_self_hash,
)


def _planner_contract(
    planner_root: Path,
    case_ids: set[str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, tuple[str, str]]]:
    plan_path = contained_file(
        planner_root,
        "execution-plan-v1.json",
        "planner plan",
    )
    plan = json_object(plan_path.read_bytes(), plan_path)
    verify_self_hash(plan, "plan_hash")
    spec_path = contained_file(
        planner_root,
        "eval-spec-v5.json",
        "planner spec",
    )
    spec = load_json(spec_path)
    profiles = {
        item["treatment_id"]: (item["causal_role"], item["profile"])
        for item in spec["treatments"]
    }
    if len(profiles) != len(spec["treatments"]):
        raise ValueError("planner treatment identity is ambiguous")
    selected = [
        item
        for item in plan["entries"]
        if (
            item["disposition"] == "execute"
            and item["case_id"] in case_ids
            and profiles[item["treatment_id"]][0] in {"baseline", "candidate"}
        )
    ]
    entries = {item["entry_id"]: item for item in selected}
    if len(entries) != len(selected):
        raise ValueError("planner entry identity is ambiguous")
    return plan, entries, profiles


def _planner_index(
    planner_root: Path,
    entries: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    index_path = contained_file(
        planner_root,
        "artifacts/index.jsonl",
        "planner run index",
    )
    rows = {}
    for position, line in enumerate(
        index_path.read_bytes().splitlines(),
        start=1,
    ):
        row = json_object(line, f"{index_path}:{position}")
        entry_id = row.get("entry_id")
        if entry_id not in entries:
            continue
        if entry_id in rows:
            raise ValueError("planner transfer source was retried")
        rows[entry_id] = row
    if set(rows) != set(entries):
        raise ValueError("planner transfer source inventory is incomplete")
    return rows


def _planner_deliverable(
    planner_root: Path,
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    row: dict[str, Any],
    profiles: dict[str, tuple[str, str]],
) -> tuple[tuple[str, int, str], dict[str, Any]]:
    artifacts_root = planner_root / "artifacts"
    receipt_path = verified_artifact(
        artifacts_root,
        row["receipt"],
        "planner receipt",
    )
    receipt = json_object(receipt_path.read_bytes(), receipt_path)
    verify_self_hash(receipt, "receipt_hash")
    run = receipt["run"]
    expected = {
        "valid": True,
        "terminal": "completed",
        "entry_id": entry["entry_id"],
        "case_id": entry["case_id"],
        "repeat": entry["repeat"],
        "treatment_id": entry["treatment_id"],
        "plan_hash": plan["plan_hash"],
    }
    if any(run.get(key) != value for key, value in expected.items()):
        raise ValueError("planner receipt identity is invalid")
    manifest_references = [
        item
        for item in receipt["artifacts"]
        if item["path"] == "fixture-final-manifest.json"
    ]
    if len(manifest_references) != 1:
        raise ValueError("planner final manifest binding is ambiguous")
    manifest_path = verified_artifact(
        artifacts_root,
        manifest_references[0],
        "planner manifest",
        prefix=row["artifact_dir"],
    )
    manifest = json_object(manifest_path.read_bytes(), manifest_path)
    artifact_path = f"fixtures/{entry['case_id']}/PLAN.md"
    references = [
        item for item in manifest["files"] if item["path"] == artifact_path
    ]
    if len(references) != 1:
        raise ValueError("planner final manifest lacks one canonical PLAN.md")
    deliverable_path = verified_artifact(
        artifacts_root,
        references[0],
        "planner deliverable",
        prefix=f"{row['artifact_dir']}/workspace",
    )
    content = deliverable_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError("planner deliverable is empty")
    role, profile = profiles[entry["treatment_id"]]
    return (entry["case_id"], entry["repeat"], role), {
        "source_case_id": entry["case_id"],
        "planner_repeat": entry["repeat"],
        "planner_treatment_id": entry["treatment_id"],
        "planner_profile": profile,
        "planner_entry_id": entry["entry_id"],
        "planner_receipt_hash": row["receipt"]["sha256"],
        "planner_plan_hash": plan["plan_hash"],
        "deliverable_sha256": references[0]["sha256"],
        "deliverable_content": content,
    }


def verified_planner_deliverables(
    planner_root: Path,
    *,
    case_ids: set[str],
    repeats: int,
) -> dict[tuple[str, int, str], dict[str, Any]]:
    plan, entries, profiles = _planner_contract(planner_root, case_ids)
    rows = _planner_index(planner_root, entries)
    deliverables = {}
    for entry_id, entry in entries.items():
        key, value = _planner_deliverable(
            planner_root,
            plan=plan,
            entry=entry,
            row=rows[entry_id],
            profiles=profiles,
        )
        if key in deliverables:
            raise ValueError("planner deliverable identity is ambiguous")
        deliverables[key] = value
    expected = {
        (case_id, repeat, role)
        for case_id in case_ids
        for repeat in range(1, repeats + 1)
        for role in ("baseline", "candidate")
    }
    if set(deliverables) != expected:
        raise ValueError("planner baseline/candidate matrix is incomplete")
    return deliverables
