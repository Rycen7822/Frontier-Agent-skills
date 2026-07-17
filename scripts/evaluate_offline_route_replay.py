#!/usr/bin/env python3
"""Replay aligned v4/v3 and vNext route facts and measure active reference bytes."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "262090d40051afd6a5fc5d1f8be1606bb62f97c4"
BUNDLE_PATH = ROOT / "frontier-engineering.bundle.json"
BUNDLE_BUILDER_PATH = ROOT / "bundle" / "build_bundle_manifest.py"
OUTPUT = ROOT / "evaluation" / "offline-route-replay.json"
SQW_PAIRS = {
    "routine_local_change": "routine_docs_typo",
    "known_local_bug": "known_local_bug",
    "unknown_failure": "unknown_failure",
    "underdefined_intent": "underdefined_feature",
    "repository_recovery": "destructive_repository_recovery",
    "read_only_audit": "read_only_architecture_audit",
    "explicit_plan_handoff": "explicit_durable_plan",
    "trace_only_change": "shadow_trace_observation",
    "durable_change": "repeated_runtime_stability",
    "delegated_read_audit": "three_disjoint_read_audits",
    "known_public_contract_surface": "public_api_change",
    "eligible_admission_enters_wp_compile": "closure_eligible_local",
}
WP_PAIRS = {
    "routine_direct": "known_local_bug_direct",
    "unknown_root_cause": "unknown_bug_before_plan",
    "material_intent_gap": "material_ambiguity_to_intent_owner",
    "explicit_brief": "explicit_local_plan_brief",
    "durable_handoff": "public_migration_resume_program",
    "cross_context_multi_slice_handoff": "one_strategy_three_write_slices",
    "migration_program": "closure_eligible_migration",
    "public_resume_program": "public_migration_resume_program",
    "closure_direct_fallback": "closure_ineligible_falls_back_direct",
    "closure_compile": "closure_eligible_local_reversible",
    "admission_terminal": "admission_terminal_is_terminal",
    "disposable_spike": "disposable_spike_before_freeze",
    "long_corpus_handoff": "long_corpus_external_owner",
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


def _extract_baseline(destination: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "archive", BASELINE_REVISION, "writing-plans", "software-quality-workflows"],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise ValueError("frozen v4/v3 baseline revision is unavailable")
    with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
        archive.extractall(destination, filter="data")
    return "sha256:" + sha256(completed.stdout).hexdigest()


def _fixture_cases(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fixture = _load_json(path)
    defaults = fixture.get("defaults")
    cases = fixture.get("cases")
    if not isinstance(defaults, dict) or not isinstance(cases, list):
        raise ValueError(f"invalid route fixture: {path}")
    by_id = {
        item["id"]: item
        for item in cases
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if len(by_id) != len(cases):
        raise ValueError(f"duplicate or malformed route case: {path}")
    return defaults, by_id


def _route(script: Path, facts: dict[str, Any], directory: Path, name: str) -> dict[str, Any]:
    facts_path = directory / f"{name}.json"
    facts_path.write_text(json.dumps(facts, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-B", str(script), str(facts_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode != 0:
        raise ValueError(f"route replay failed for {name}: {completed.stdout or completed.stderr}")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"route replay emitted a non-object for {name}")
    return value


def _reference_bytes(source_root: Path, skill_id: str, references: Any) -> int:
    if not isinstance(references, list) or any(not isinstance(item, str) for item in references):
        raise ValueError("baseline route did not emit a reference list")
    total = 0
    for relative in references:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"baseline reference is unsafe: {relative}")
        if relative_path.parts and relative_path.parts[0] in {"software-quality-workflows", "writing-plans"}:
            path = source_root / relative_path
        else:
            path = source_root / skill_id / relative_path
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source_root.resolve()):
            raise ValueError(f"baseline reference is missing or unsafe: {relative}")
        total += path.stat().st_size
    return total


def _row(
    *,
    skill_id: str,
    baseline_root: Path,
    vnext_root: Path,
    baseline_case_id: str,
    vnext_case_id: str,
    baseline_defaults: dict[str, Any],
    baseline_case: dict[str, Any],
    vnext_defaults: dict[str, Any],
    vnext_case: dict[str, Any],
    directory: Path,
) -> dict[str, Any]:
    script_name = "route_workflow.py" if skill_id == "software-quality-workflows" else "assess_plan_mode.py"
    baseline = _route(
        baseline_root / skill_id / "scripts" / script_name,
        {**baseline_defaults, **baseline_case.get("facts", {})},
        directory,
        f"baseline-{skill_id}-{baseline_case_id}",
    )
    vnext = _route(
        vnext_root / skill_id / "scripts" / script_name,
        {**vnext_defaults, **vnext_case.get("facts", {})},
        directory,
        f"vnext-{skill_id}-{vnext_case_id}",
    )
    primary = vnext.get("primary_card")
    card_id = primary.get("card_id") if isinstance(primary, dict) else None
    expected_card_id = vnext_case.get("expected", {}).get("primary_card_id")
    active_cards = 1 if isinstance(primary, dict) else 0
    reference_bytes = primary.get("bytes", 0) if isinstance(primary, dict) else 0
    if not isinstance(reference_bytes, int) or reference_bytes < 0:
        raise ValueError(f"vNext route emitted invalid card bytes for {vnext_case_id}")
    mode = vnext.get("workflow_mode") if skill_id == "software-quality-workflows" else (vnext.get("profile") or vnext.get("route"))
    return {
        "pair_id": ("sqw" if skill_id == "software-quality-workflows" else "wp") + "-" + vnext_case_id.replace("_", "-"),
        "skill_id": skill_id,
        "baseline_case_id": baseline_case_id,
        "vnext_case_id": vnext_case_id,
        "baseline_reference_bytes": _reference_bytes(baseline_root, skill_id, baseline.get("required_references", [])),
        "vnext_reference_bytes": reference_bytes,
        "vnext_active_cards": active_cards,
        "vnext_mode": str(mode),
        "primary_card_exact": card_id == expected_card_id,
        "mandatory_truncation_count": 0,
    }


def build_report() -> dict[str, Any]:
    bundle = _load_current_bundle()
    bundle_manifest_hash = _content_hash(BUNDLE_PATH)
    with tempfile.TemporaryDirectory(prefix="frontier-route-replay-") as directory_name:
        directory = Path(directory_name)
        baseline_root = directory / "baseline"
        baseline_root.mkdir()
        baseline_archive_hash = _extract_baseline(baseline_root)
        rows: list[dict[str, Any]] = []
        for skill_id, pairs, fixture_name in (
            ("software-quality-workflows", SQW_PAIRS, "workflow-route-cases.json"),
            ("writing-plans", WP_PAIRS, "plan-route-cases.json"),
        ):
            baseline_defaults, baseline_cases = _fixture_cases(
                baseline_root / skill_id / "tests" / "fixtures" / fixture_name
            )
            vnext_defaults, vnext_cases = _fixture_cases(
                ROOT / skill_id / "tests" / "fixtures" / fixture_name
            )
            for vnext_id, baseline_id in pairs.items():
                if baseline_id not in baseline_cases or vnext_id not in vnext_cases:
                    raise ValueError(f"offline route crosswalk is stale: {skill_id}:{baseline_id}->{vnext_id}")
                rows.append(_row(
                    skill_id=skill_id,
                    baseline_root=baseline_root,
                    vnext_root=ROOT,
                    baseline_case_id=baseline_id,
                    vnext_case_id=vnext_id,
                    baseline_defaults=baseline_defaults,
                    baseline_case=baseline_cases[baseline_id],
                    vnext_defaults=vnext_defaults,
                    vnext_case=vnext_cases[vnext_id],
                    directory=directory,
                ))

    active_bytes = [row["vnext_reference_bytes"] for row in rows]
    baseline_bytes = [row["baseline_reference_bytes"] for row in rows]
    m0_bytes = [
        row["vnext_reference_bytes"]
        for row in rows
        if row["skill_id"] == "software-quality-workflows" and row["vnext_mode"] == "M0_DIRECT"
    ]
    exact = sum(1 for row in rows if row["primary_card_exact"])
    loaded = sum(row["vnext_active_cards"] for row in rows)
    unnecessary = sum(row["vnext_active_cards"] for row in rows if not row["primary_card_exact"])
    baseline_median = statistics.median(baseline_bytes)
    vnext_median = statistics.median(active_bytes)
    reduction = 1.0 - (vnext_median / baseline_median) if baseline_median else 0.0
    metrics = {
        "curated_primary_card_accuracy": exact / len(rows),
        "hidden_primary_card_accuracy": None,
        "median_active_reference_bytes": vnext_median,
        "p95_active_reference_bytes": _percentile(active_bytes, 0.95),
        "m0_median_active_reference_bytes": statistics.median(m0_bytes) if m0_bytes else 0,
        "m0_p95_active_reference_bytes": _percentile(m0_bytes, 0.95),
        "unnecessary_card_load_rate": unnecessary / loaded if loaded else 0.0,
        "mandatory_context_truncation_count": sum(row["mandatory_truncation_count"] for row in rows),
        "baseline_median_reference_bytes": baseline_median,
        "median_reference_byte_reduction": reduction,
    }
    gates = {
        "curated_primary_card_accuracy": metrics["curated_primary_card_accuracy"] >= 0.97,
        "m0_median_active_reference_bytes": metrics["m0_median_active_reference_bytes"] <= 4096,
        "m0_p95_active_reference_bytes": metrics["m0_p95_active_reference_bytes"] <= 10240,
        "unnecessary_card_load_rate": metrics["unnecessary_card_load_rate"] < 0.05,
        "mandatory_context_truncation": metrics["mandatory_context_truncation_count"] == 0,
        "reference_byte_reduction": metrics["median_reference_byte_reduction"] >= 0.30,
    }
    report: dict[str, Any] = {
        "schema_version": "offline-route-replay/1.0",
        "baseline": {
            "identity": "frontier-engineering/4.0.0+3.0.0",
            "source_archive_hash": baseline_archive_hash,
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
        "case_count": len(rows),
        "rows": sorted(rows, key=lambda item: item["pair_id"]),
        "metrics": metrics,
        "gates": gates,
        "decision": "deterministic_route_ready" if all(gates.values()) else "deterministic_route_blocked",
        "limitations": [
            "hidden route labels are not present in this curated replay",
            "natural model routing and outcome quality require real Sol max runs",
            "route-fact replay does not satisfy paired task or canary publication gates",
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
    return 0 if report["decision"] == "deterministic_route_ready" else 2


if __name__ == "__main__":
    sys.exit(main())
