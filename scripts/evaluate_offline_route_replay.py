#!/usr/bin/env python3
"""Execute outcome-linked route sequences and emit a deterministic diagnostic."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "262090d40051afd6a5fc5d1f8be1606bb62f97c4"
BUNDLE_PATH = ROOT / "frontier-engineering.bundle.json"
BUNDLE_BUILDER_PATH = ROOT / "bundle" / "build_bundle_manifest.py"
OUTPUT = ROOT / "evaluation" / "offline-route-replay.json"
SKILLS = {
    "writing-plans": {
        "version": "5.0.0",
        "router": "scripts/assess_plan_mode.py",
        "decision_map": "registries/decision-card-map.json",
        "card_manifest": "registries/reference-cards.manifest.json",
        "decision_cases": "tests/fixtures/decision-route-cases-v5.json",
        "sequences": "tests/fixtures/plan-route-sequences.json",
    },
    "software-quality-workflows": {
        "version": "6.0.0",
        "router": "scripts/route_workflow.py",
        "decision_map": "registries/decision-card-map.json",
        "card_manifest": "registries/reference-cards.manifest.json",
        "decision_cases": "tests/fixtures/decision-route-cases-v6.json",
        "sequences": "tests/fixtures/workflow-route-sequences.json",
    },
}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _content_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"content identity input is missing or symlinked: {path}")
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _build_current_bundle() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("offline_replay_bundle_builder", BUNDLE_BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise ValueError("generated bundle builder is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = module.build_manifest()
    if not isinstance(manifest, dict):
        raise ValueError("generated bundle builder returned a non-object")
    return manifest


def _load_current_bundle() -> dict[str, Any]:
    checked = _load_json(BUNDLE_PATH)
    if checked != _build_current_bundle():
        raise ValueError("generated bundle manifest is missing or stale")
    return checked


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _distribution(values: list[int]) -> dict[str, int | float]:
    if not values:
        return {"minimum": 0, "median": 0, "p95": 0, "maximum": 0}
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "maximum": max(values),
    }


def _baseline_archive_hash() -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "archive", BASELINE_REVISION, "writing-plans", "software-quality-workflows"],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError("frozen v4/v3 baseline revision is unavailable")
    return "sha256:" + sha256(completed.stdout).hexdigest()


def _safe_path(skill_root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"unsafe replay input path: {relative}")
    path = skill_root / relative_path
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(skill_root.resolve()):
        raise ValueError(f"missing or unsafe replay input: {relative}")
    return path


def _load_router(skill_id: str, script: Path) -> Any:
    module_name = "offline_replay_" + skill_id.replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ValueError(f"route module is unavailable: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    if not callable(getattr(module, "assess", None)):
        raise ValueError(f"route module lacks assess(): {script}")
    return module.assess


def _load_skill_inputs(skill_id: str) -> dict[str, Any]:
    config = SKILLS[skill_id]
    skill_root = ROOT / skill_id
    paths = {key: _safe_path(skill_root, relative) for key, relative in config.items() if key != "version"}
    decision_map = _load_json(paths["decision_map"])
    manifest = _load_json(paths["card_manifest"])
    decision_cases = _load_json(paths["decision_cases"])
    sequences = _load_json(paths["sequences"])
    if sequences.get("decision_case_fixture") != config["decision_cases"]:
        raise ValueError(f"{skill_id} sequence fixture does not bind the canonical decision cases")
    if sequences.get("skill_id") != skill_id or sequences.get("schema_version") != "outcome-linked-route-sequences/1.0":
        raise ValueError(f"{skill_id} sequence fixture identity is invalid")
    if decision_map.get("skill_id") != skill_id or decision_map.get("skill_version") != config["version"]:
        raise ValueError(f"{skill_id} decision map identity is invalid")
    if manifest.get("skill_id") != skill_id or manifest.get("skill_version") != config["version"]:
        raise ValueError(f"{skill_id} card manifest identity is invalid")
    return {
        "skill_id": skill_id,
        "skill_root": skill_root,
        "router": _load_router(skill_id, paths["router"]),
        "decision_map": decision_map,
        "manifest": manifest,
        "decision_cases": decision_cases,
        "sequences": sequences,
        "bindings": {
            "skill_version": config["version"],
            "router_hash": _content_hash(paths["router"]),
            "decision_map_hash": _content_hash(paths["decision_map"]),
            "card_manifest_hash": _content_hash(paths["card_manifest"]),
            "decision_case_fixture_hash": _content_hash(paths["decision_cases"]),
            "sequence_fixture_hash": _content_hash(paths["sequences"]),
        },
    }


def _route(inputs: dict[str, Any], overlay: Any) -> dict[str, Any]:
    defaults = inputs["decision_cases"].get("defaults")
    if not isinstance(defaults, dict) or not isinstance(overlay, dict):
        raise ValueError(f"{inputs['skill_id']} replay facts are invalid")
    result = inputs["router"]({**defaults, **overlay}, root=inputs["skill_root"])
    if not isinstance(result, dict):
        raise ValueError(f"{inputs['skill_id']} route emitted a non-object")
    return result


def _card_snapshot(result: dict[str, Any]) -> tuple[str | None, int, int]:
    card = result.get("primary_card")
    if card is None:
        return None, 0, 0
    if not isinstance(card, dict) or not isinstance(card.get("card_id"), str):
        raise ValueError("route emitted a malformed primary card")
    size = card.get("bytes")
    if not isinstance(size, int) or size < 0:
        raise ValueError("route emitted invalid active card bytes")
    return card["card_id"], 1, size


def _selection_rows(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in inputs["decision_cases"].get("positive_cases", []):
        result = _route(inputs, case.get("facts"))
        card_id, active_count, active_bytes = _card_snapshot(result)
        expected_decision = case.get("decision_id")
        expected_card = case.get("expected_card_id")
        rows.append({
            "case_id": case.get("id"),
            "skill_id": inputs["skill_id"],
            "expected_decision_id": expected_decision,
            "actual_decision_id": result.get("selected_decision_id"),
            "expected_card_id": expected_card,
            "actual_card_id": card_id,
            "decision_exact": result.get("selected_decision_id") == expected_decision,
            "card_exact": card_id == expected_card,
            "active_card_count": active_count,
            "active_bytes": active_bytes,
        })
    return rows


def _protected_rows(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_decision = {row["decision_id"]: row for row in inputs["decision_map"].get("decisions", [])}
    for case in inputs["decision_cases"].get("near_miss_cases", []):
        result = _route(inputs, case.get("facts"))
        card_id, active_count, active_bytes = _card_snapshot(result)
        expected_decision = case.get("expected_decision_id")
        expected_card = by_decision.get(expected_decision, {}).get("card_id")
        rows.append({
            "case_id": case.get("id"), "skill_id": inputs["skill_id"], "kind": "near_miss",
            "expected_decision_id": expected_decision, "expected_card_id": expected_card,
            "excluded_card_id": case.get("excluded_card_id"),
            "actual_decision_id": result.get("selected_decision_id"), "actual_card_id": card_id,
            "expected_reason": None, "actual_reason": None,
            "protected_pass": (
                result.get("selected_decision_id") == expected_decision
                and card_id == expected_card and card_id != case.get("excluded_card_id")
            ),
            "active_card_count": active_count, "active_bytes": active_bytes,
        })
    for case in inputs["decision_cases"].get("negative_cases", []):
        result = _route(inputs, case.get("facts"))
        card_id, active_count, active_bytes = _card_snapshot(result)
        reasons = result.get("reason_codes")
        actual_reason = reasons[0] if isinstance(reasons, list) and reasons else None
        rows.append({
            "case_id": case.get("id"), "skill_id": inputs["skill_id"], "kind": "negative",
            "expected_decision_id": None, "expected_card_id": None, "excluded_card_id": None,
            "actual_decision_id": result.get("selected_decision_id"), "actual_card_id": card_id,
            "expected_reason": case.get("expected_reason"), "actual_reason": actual_reason,
            "protected_pass": (
                result.get("route_action") == "blocked" and result.get("selected_decision_id") is None
                and card_id is None and actual_reason == case.get("expected_reason")
            ),
            "active_card_count": active_count, "active_bytes": active_bytes,
        })
    return rows


def _entry_rows(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in inputs["sequences"].get("entry_cases", []):
        result = _route(inputs, case.get("facts"))
        card_id, active_count, active_bytes = _card_snapshot(result)
        expected = case.get("expected", {})
        exact = (
            result.get("route_action"), result.get("route_owner"), result.get("selected_decision_id"), card_id
        ) == (
            expected.get("route_action"), expected.get("route_owner"),
            expected.get("selected_decision_id"), expected.get("card_id"),
        )
        rows.append({
            "case_id": case.get("id"), "skill_id": inputs["skill_id"],
            "expected_action": expected.get("route_action"), "actual_action": result.get("route_action"),
            "expected_owner": expected.get("route_owner"), "actual_owner": result.get("route_owner"),
            "expected_decision_id": expected.get("selected_decision_id"),
            "actual_decision_id": result.get("selected_decision_id"),
            "expected_card_id": expected.get("card_id"), "actual_card_id": card_id,
            "entry_exact": exact, "active_card_count": active_count, "active_bytes": active_bytes,
        })
    return rows


def _sequence_rows(inputs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[int]]:
    rows: list[dict[str, Any]] = []
    all_step_bytes: list[int] = []
    entries = {case.get("id"): case for case in inputs["sequences"].get("entry_cases", [])}
    mappings = {row["decision_id"]: row for row in inputs["decision_map"].get("decisions", [])}
    for sequence in inputs["sequences"].get("workflow_sequences", []):
        completed: list[str] = []
        artifacts: list[str] = []
        selected_cards: list[str] = []
        step_bytes: list[int] = []
        step_exact = True
        unnecessary_loads = 0
        previous: dict[str, Any] | None = None
        for index, step in enumerate(sequence.get("steps", [])):
            if index == 0:
                entry = entries.get(sequence.get("entry_case_id"))
                if not isinstance(entry, dict):
                    raise ValueError(f"sequence entry is unknown: {sequence.get('id')}")
                facts = entry.get("facts")
            else:
                if previous is None or step.get("requested_by_step") != index - 1:
                    raise ValueError(f"sequence outcome link is invalid: {sequence.get('id')}:{index}")
                if step.get("request_artifact_id") != previous.get("produced_artifact_id"):
                    raise ValueError(f"sequence outcome artifact is invalid: {sequence.get('id')}:{index}")
                facts = {
                    "completed_decision_ids": list(completed),
                    "available_artifact_ids": list(artifacts),
                    "just_completed_card_id": previous.get("card_id"),
                    "decision_request": {
                        "decision_id": step.get("decision_id"),
                        "produced_by_card_id": previous.get("card_id"),
                        "produced_artifact_id": step.get("request_artifact_id"),
                    },
                }
            result = _route(inputs, facts)
            card_id, _, active_bytes = _card_snapshot(result)
            mapping = mappings.get(step.get("decision_id"), {})
            produced = step.get("produced_artifact_id")
            exact = (
                result.get("selected_decision_id") == step.get("decision_id")
                and card_id == step.get("card_id")
                and produced in mapping.get("produced_artifact_ids", [])
            )
            step_exact = step_exact and exact
            if card_id is not None and card_id != step.get("card_id"):
                unnecessary_loads += 1
            if exact:
                completed.append(step["decision_id"])
                artifacts.append(produced)
                selected_cards.append(card_id)
            step_bytes.append(active_bytes)
            all_step_bytes.append(active_bytes)
            previous = step
        terminal = sequence.get("terminal_outcome", {})
        expected_terminal_owner = "software-quality-workflows" if inputs["skill_id"] == "writing-plans" else None
        terminal_complete = (
            step_exact and terminal.get("status") == "completed"
            and terminal.get("owner") == expected_terminal_owner
            and terminal.get("required_decision_ids", []) == completed
            and terminal.get("required_artifact_ids", []) == artifacts
            and len(completed) == len(set(completed))
            and len(artifacts) == len(set(artifacts))
        )
        rows.append({
            "sequence_id": sequence.get("id"), "skill_id": inputs["skill_id"],
            "step_count": len(sequence.get("steps", [])), "selected_card_ids": selected_cards,
            "active_bytes_per_step": step_bytes, "total_active_bytes": sum(step_bytes),
            "unnecessary_card_loads": unnecessary_loads,
            "terminal_status": terminal.get("status"), "terminal_owner": terminal.get("owner"),
            "terminal_complete": terminal_complete,
        })
    return rows, all_step_bytes


def build_report() -> dict[str, Any]:
    bundle = _load_current_bundle()
    bundle_manifest_hash = _content_hash(BUNDLE_PATH)
    inputs = [_load_skill_inputs(skill_id) for skill_id in SKILLS]
    selection_rows = [row for item in inputs for row in _selection_rows(item)]
    protected_rows = [row for item in inputs for row in _protected_rows(item)]
    entry_rows = [row for item in inputs for row in _entry_rows(item)]
    sequence_rows: list[dict[str, Any]] = []
    sequence_step_bytes: list[int] = []
    for item in inputs:
        rows, step_bytes = _sequence_rows(item)
        sequence_rows.extend(rows)
        sequence_step_bytes.extend(step_bytes)

    expected_cards = {
        row["card_id"]
        for item in inputs
        for row in item["decision_map"].get("decisions", [])
    }
    covered_cards = {row["actual_card_id"] for row in selection_rows if row["card_exact"]}
    decision_true_positives = sum(row["decision_exact"] for row in selection_rows)
    actual_decisions = sum(row["actual_decision_id"] is not None for row in selection_rows)
    protected_passes = sum(row["protected_pass"] for row in protected_rows)
    entry_passes = sum(row["entry_exact"] for row in entry_rows)
    terminal_passes = sum(row["terminal_complete"] for row in sequence_rows)
    unnecessary = (
        sum(row["active_card_count"] for row in selection_rows if row["actual_card_id"] != row["expected_card_id"])
        + sum(row["active_card_count"] for row in protected_rows if row["actual_card_id"] != row["expected_card_id"])
        + sum(row["active_card_count"] for row in entry_rows if row["actual_card_id"] != row["expected_card_id"])
        + sum(row["unnecessary_card_loads"] for row in sequence_rows)
    )
    all_step_bytes = (
        [row["active_bytes"] for row in selection_rows]
        + [row["active_bytes"] for row in protected_rows]
        + [row["active_bytes"] for row in entry_rows]
        + sequence_step_bytes
    )
    metrics = {
        "active_card_count": len(expected_cards),
        "active_card_coverage_count": len(covered_cards),
        "entry_accuracy": entry_passes / len(entry_rows) if entry_rows else 0.0,
        "decision_precision": decision_true_positives / actual_decisions if actual_decisions else 0.0,
        "decision_recall": decision_true_positives / len(selection_rows) if selection_rows else 0.0,
        "terminal_path_completion": terminal_passes / len(sequence_rows) if sequence_rows else 0.0,
        "unnecessary_card_loads": unnecessary,
        "per_step_active_bytes": _distribution(all_step_bytes),
        "sequence_total_active_bytes": _distribution([row["total_active_bytes"] for row in sequence_rows]),
        "protected_negative_count": len(protected_rows),
        "protected_negative_pass_rate": protected_passes / len(protected_rows) if protected_rows else 0.0,
        "near_miss_unloaded_count": sum(
            row["kind"] == "near_miss" and row["actual_card_id"] != row["excluded_card_id"]
            for row in protected_rows
        ),
        "negative_unloaded_count": sum(
            row["kind"] == "negative" and row["active_card_count"] == 0 for row in protected_rows
        ),
    }
    near_miss_count = sum(row["kind"] == "near_miss" for row in protected_rows)
    negative_count = sum(row["kind"] == "negative" for row in protected_rows)
    gates = {
        "active_card_coverage": metrics["active_card_count"] == metrics["active_card_coverage_count"] == 62,
        "entry_accuracy": metrics["entry_accuracy"] == 1.0,
        "decision_precision": metrics["decision_precision"] == 1.0,
        "decision_recall": metrics["decision_recall"] == 1.0,
        "terminal_path_completion": metrics["terminal_path_completion"] == 1.0,
        "protected_negative_pass_rate": metrics["protected_negative_pass_rate"] == 1.0,
        "unnecessary_card_loads": metrics["unnecessary_card_loads"] == 0,
        "per_step_active_bytes": metrics["per_step_active_bytes"]["maximum"] <= 8192,
        "near_miss_selectors_unloaded": metrics["near_miss_unloaded_count"] == near_miss_count,
        "negative_selectors_unloaded": metrics["negative_unloaded_count"] == negative_count,
    }
    report: dict[str, Any] = {
        "schema_version": "offline-route-replay/2.0",
        "diagnostic_classification": "deterministic_diagnostic",
        "baseline": {
            "identity": "frontier-engineering/4.0.0+3.0.0",
            "source_archive_hash": _baseline_archive_hash(),
            "skill_versions": {"software-quality-workflows": "4.0.0", "writing-plans": "3.0.0"},
        },
        "vnext": {
            "identity": bundle["bundle_id"],
            "bundle_build_id": bundle["release_build_id"],
            "bundle_manifest_hash": bundle_manifest_hash,
            "skill_versions": {
                skill_id: item["version"]
                for skill_id, item in bundle["skills"].items()
            },
        },
        "input_bindings": {item["skill_id"]: item["bindings"] for item in inputs},
        "case_count": len(selection_rows) + len(protected_rows) + len(entry_rows) + len(sequence_rows),
        "selection_rows": sorted(selection_rows, key=lambda item: (item["skill_id"], item["case_id"])),
        "protected_rows": sorted(protected_rows, key=lambda item: (item["skill_id"], item["case_id"])),
        "entry_rows": sorted(entry_rows, key=lambda item: (item["skill_id"], item["case_id"])),
        "sequence_rows": sorted(sequence_rows, key=lambda item: (item["skill_id"], item["sequence_id"])),
        "metrics": metrics,
        "gates": gates,
        "decision": "deterministic_sequence_ready" if all(gates.values()) else "deterministic_sequence_blocked",
        "limitations": [
            "sequence total active bytes are a diagnostic distribution, not an external context budget",
            "natural model routing and outcome quality require real Sol max runs",
            "deterministic route replay does not satisfy L2 usefulness or publication gates",
        ],
    }
    report["report_hash"] = _canonical_hash(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        report = build_report()
        rendered = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if args.check:
            if args.output.is_symlink() or not args.output.is_file() or args.output.read_bytes() != rendered:
                raise ValueError("offline route replay report is missing or stale")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_bytes(rendered)
            temporary.replace(args.output)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, "decision": report["decision"], "report_hash": report["report_hash"]}))
    return 0 if report["decision"] == "deterministic_sequence_ready" else 2


if __name__ == "__main__":
    sys.exit(main())
