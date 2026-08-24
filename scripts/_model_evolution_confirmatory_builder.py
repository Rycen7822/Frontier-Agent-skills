#!/usr/bin/env python3
"""Build the versioned, provider-free SE confirmatory corpus."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
from statistics import NormalDist
from typing import Any

sys.dont_write_bytecode = True

import _model_evolution_sentinel_builder as legacy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path("evaluation/model-evolution")
OUTPUT_ROOT = MODEL_ROOT / "confirmatory-v1"
SOURCE_ROOT = REPOSITORY_ROOT / MODEL_ROOT / "confirmatory_sources"
DEFINITION = runpy.run_path(str(SOURCE_ROOT / "skill_evaluator_v1.py"))["DEFINITION"]
OLD_CASE_IDS = {
    "skill-evaluator-level-owner-selection",
    "skill-evaluator-deterministic-first",
    "skill-evaluator-analyzer-exit-contract",
    "skill-evaluator-cli-schema-diagnosis",
    "skill-evaluator-transition-vs-revision",
    "skill-evaluator-protected-no-reviewer",
}


def _lineage() -> dict[str, Any]:
    return {
        "schema_version": "se-confirmatory-case-lineage/1",
        "case_count": len(DEFINITION["case_lineage"]),
        "strata": 6,
        "cases_per_stratum": 8,
        "cases": DEFINITION["case_lineage"],
    }


def _power() -> dict[str, Any]:
    normal = NormalDist()
    rows = []
    for effect in (0.15, 0.222, 0.30):
        for standard_deviation in (0.40, 0.503, 0.65):
            z = effect * (48 ** 0.5) / standard_deviation - 1.6448536269514722
            rows.append({
                "effect": effect,
                "standard_deviation": standard_deviation,
                "distinct_cases": 48,
                "approximate_power": round(normal.cdf(z), 6),
            })
    return {
        "schema_version": "se-confirmatory-power-sensitivity/1",
        "alpha_one_sided": 0.05,
        "registered_distinct_cases": 48,
        "method": "normal-approximation-design-sensitivity",
        "rows": rows,
        "claim": "design_rationale_only_not_pass_guarantee",
        "optional_stopping": False,
    }


def _policy() -> dict[str, Any]:
    old = json.loads(
        (REPOSITORY_ROOT / MODEL_ROOT / "bundle-revision-policy.json").read_text()
    )
    old["schema_version"] = "frontier-bundle-revision-policy/2"
    old["authority_id"] = "frontier-bundle-8-confirmatory-v1"
    old["registered_at"] = "2026-08-24T00:00:00Z"
    old["skills"]["skill-evaluator"]["minimum_distinct_cases"] = 48
    old["estimator"] = {
        "id": "paired-difference-of-differences",
        "version": "1.0.0",
        "resampling_unit": "case",
        "confidence_level": 0.95,
        "bootstrap_iterations": 10000,
        "decision_lower_percentile": 0.05,
        "diagnostic_upper_percentile": 0.95,
        "seed_derivation": "sha256-domain-separated-length-prefixed-policy-bytes-v1",
    }
    return old


def _manual_protocol(packet_schema: bytes) -> dict[str, Any]:
    return {
        "schema_version": "manual-authority-protocol/1",
        "authority_owner": "release-owner",
        "custodian_id": "confirmatory-manual-custodian",
        "packet_schema": _campaign_binding(
            (OUTPUT_ROOT / "manual-authority-packet-v1.schema.json").as_posix(),
            packet_schema,
        ),
        "protocol": "post-holdout-independent-signoff",
        "decision_values": ["approve", "hold", "reject"],
        "signing_conditions": [
            "four_revision_reports_closed",
            "sealed_holdout_closed",
            "packet_identity_verified",
        ],
        "decision": None,
        "signed_attestation": None,
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _artifact_schema(path: str, payload: bytes) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        value = json.loads(payload)
        return str(value.get("schema_version", "json/1"))
    if suffix == ".jsonl":
        first = next(line for line in payload.splitlines() if line.strip())
        value = json.loads(first)
        return f"jsonl/{value.get('schema_version', 1)}"
    if suffix in {".md", ".txt", ".log"}:
        payload.decode("utf-8")
        return "text/utf-8"
    return "bytes/1"


def _campaign_binding(path: str, payload: bytes) -> dict[str, str]:
    return {
        "root": "campaign",
        "path": path,
        "schema_version": _artifact_schema(path, payload),
    }


def _relocate_binding(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"root", "path"}:
        prefix = "evaluation/model-evolution/sentinels/"
        if value["root"] != "repository" or not value["path"].startswith(prefix):
            raise ValueError("legacy sentinel binding is outside its generated root")
        suffix = value["path"][len(prefix):]
        return _campaign_binding(
            (OUTPUT_ROOT / "sentinels" / suffix).as_posix(),
            (REPOSITORY_ROOT / value["path"]).read_bytes(),
        )
    if isinstance(value, dict):
        return {key: _relocate_binding(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_relocate_binding(item) for item in value]
    return value


def materialize(repository_root: Path) -> list[Path]:
    output = repository_root / OUTPUT_ROOT
    target = output / "sentinels/skill-evaluator"
    base_spec = json.loads(
        (REPOSITORY_ROOT / "skill-evaluator/templates/eval-spec.example.json").read_text()
    )
    base_scenario = json.loads(
        (REPOSITORY_ROOT / "skill-evaluator/templates/scenarios.example.jsonl")
        .read_text().splitlines()[0]
    )
    fixture_payloads = {
        path: content.encode() for path, content in DEFINITION["fixtures"].items()
    }
    fixture_bindings = {
        path: {"path": path, "sha256": legacy._sha256(payload)}
        for path, payload in fixture_payloads.items()
    }
    manifest = legacy._json_bytes({
        "schema_version": 1,
        "artifacts": [
            {
                "path": Path(path).relative_to("fixtures").as_posix(),
                "digest": legacy._sha256(payload),
                "encoding": "utf-8",
            }
            for path, payload in sorted(fixture_payloads.items())
        ],
    })
    scenarios = [
        legacy._scenario(
            base_scenario,
            skill_id="skill-evaluator",
            case=case,
            fixture_hash=legacy._sha256(manifest),
            fixture_bindings=fixture_bindings,
            process_required=True,
        )
        for case in DEFINITION["cases"]
    ]
    scenario_bytes = legacy._jsonl_bytes(scenarios)
    prompt = legacy._grader_prompt(
        "skill-evaluator", DEFINITION["claims"], DEFINITION["grader_rules"]
    )
    calibration = legacy._calibration_gold("skill-evaluator", DEFINITION["claims"])
    verifier = (SOURCE_ROOT / "skill_evaluator_v1_verifier.py").read_bytes()
    output_schema = (
        REPOSITORY_ROOT / "skill-evaluator/templates/grader-output.schema.json"
    ).read_bytes()
    initial = {
        **{target / path: payload for path, payload in fixture_payloads.items()},
        target / "fixtures/manifest.json": manifest,
        target / "verify.py": verifier,
        target / "verify_common.py": legacy.COMMON_VERIFIER_BYTES,
        target / "grader-prompt.md": prompt,
        target / "grader-output.schema.json": output_schema,
        target / "host-manifest.template.json": legacy._host_manifest(),
        target / "scenarios.public.jsonl": scenario_bytes,
        target / "calibration-gold.jsonl": calibration,
    }
    for skill_id in (
        "long-document-segmented-writing",
        "software-quality-workflows",
        "writing-plans",
    ):
        source = REPOSITORY_ROOT / MODEL_ROOT / "sentinels" / skill_id
        destination = output / "sentinels" / skill_id
        for path in source.rglob("*"):
            if path.is_file() and not path.is_symlink():
                initial[destination / path.relative_to(source)] = path.read_bytes()
    spec_path = target / "eval-spec.template.json"
    proof_path = target / "suite-quality-proof.json"
    quality_path = target / "suite-quality.json"
    lineage_path = output / "skill-evaluator-case-lineage-v1.json"
    power_path = output / "skill-evaluator-power-sensitivity-v1.json"
    policy_path = output / "bundle-revision-policy-v2.json"
    authority_path = output / "manual-authority-protocol-v1.json"
    manual_schema_path = output / "manual-authority-packet-v1.schema.json"
    index_path = output / "sentinel-index-v3.json"
    legacy._prune_generated_files(
        output,
        {
            *initial,
            spec_path,
            proof_path,
            quality_path,
            lineage_path,
            power_path,
            policy_path,
            authority_path,
            manual_schema_path,
            index_path,
        },
    )
    for path, payload in initial.items():
        _write(path, payload)
    spec = legacy._spec(
        base_spec,
        skill_id="skill-evaluator",
        config=DEFINITION,
        scenarios=scenarios,
    )
    spec["evaluation_id"] = "frontier-skill-evaluator-confirmatory-v1"
    spec["analysis"]["bootstrap_iterations"] = 10000
    spec["suite"]["order_seed"] = 804801
    proof = legacy._quality_proof(spec, scenarios, prompt_digest=legacy._sha256(prompt))
    _write(spec_path, legacy._json_bytes(spec))
    _write(proof_path, legacy._json_bytes(proof))
    quality_path.unlink(missing_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(REPOSITORY_ROOT / "skill-evaluator/scripts/validate_eval_suite.py"),
            "suite-quality",
            "--spec",
            str(spec_path),
            "--proof",
            str(proof_path),
            "--output",
            str(quality_path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    spec["suite"]["quality"] = {
        "path": "suite-quality.json",
        "digest": legacy._sha256(quality_path.read_bytes()),
        "schema_version": "suite-quality/2",
    }
    _write(spec_path, legacy._json_bytes(spec))
    manual_schema = (
        REPOSITORY_ROOT
        / "evaluation/model-evolution/schemas/manual-authority-packet-v1.schema.json"
    ).read_bytes()
    _write(manual_schema_path, manual_schema)
    for path, value in (
        (lineage_path, _lineage()),
        (power_path, _power()),
        (policy_path, _policy()),
        (authority_path, _manual_protocol(manual_schema)),
    ):
        _write(path, legacy._json_bytes(value))

    old_index = json.loads(
        (REPOSITORY_ROOT / MODEL_ROOT / "sentinel-index-v2.json").read_text()
    )
    skills = {
        skill_id: _relocate_binding(copy.deepcopy(record))
        for skill_id, record in old_index["skills"].items()
    }
    relative = OUTPUT_ROOT / "sentinels/skill-evaluator"
    skills["skill-evaluator"] = {
        "critical_bucket_id": "skill-evaluator-confirmatory-critical",
        "spec_template": _campaign_binding((relative / "eval-spec.template.json").as_posix(), spec_path.read_bytes()),
        "public_scenarios": _campaign_binding((relative / "scenarios.public.jsonl").as_posix(), scenario_bytes),
        "calibration_gold": _campaign_binding((relative / "calibration-gold.jsonl").as_posix(), calibration),
        "calibration_request_ceiling": len(calibration.splitlines()),
        "fixture_roots": [
            _campaign_binding((relative / "fixtures/manifest.json").as_posix(), manifest),
            *[
                _campaign_binding((relative / path).as_posix(), fixture_payloads[path])
                for path in sorted(fixture_payloads)
            ],
        ],
        "verifier_roots": [
            _campaign_binding((relative / "verify.py").as_posix(), verifier),
            _campaign_binding((relative / "verify_common.py").as_posix(), legacy.COMMON_VERIFIER_BYTES),
        ],
        "required_coverage_tags": list(DEFINITION_STRATA),
        "protected_case_ids": [
            f"skill-evaluator-{case['id']}"
            for case in DEFINITION["cases"] if case["protected"]
        ],
        "external_holdout_contract_id": "skill-evaluator-confirmatory-external-holdout-v1",
        "holdout_case_ceiling": 2,
    }
    catalog_paths = sorted({
        *initial,
        spec_path,
        proof_path,
        quality_path,
        lineage_path,
        power_path,
        policy_path,
        authority_path,
        manual_schema_path,
    })
    index = {
        "schema_version": "model-evolution-sentinel-index/3",
        "sentinel_id": "frontier-four-skill-confirmatory-v1",
        "revision_policy": _campaign_binding((OUTPUT_ROOT / policy_path.name).as_posix(), policy_path.read_bytes()),
        "manual_authority_protocol": _campaign_binding((OUTPUT_ROOT / authority_path.name).as_posix(), authority_path.read_bytes()),
        "case_lineage": _campaign_binding((OUTPUT_ROOT / lineage_path.name).as_posix(), lineage_path.read_bytes()),
        "power_sensitivity": _campaign_binding((OUTPUT_ROOT / power_path.name).as_posix(), power_path.read_bytes()),
        "catalog_files": [
            _campaign_binding(
                path.relative_to(repository_root).as_posix(), path.read_bytes()
            )
            for path in catalog_paths
        ],
        "skills": skills,
    }
    _write(index_path, legacy._json_bytes(index))
    return sorted({*initial, spec_path, proof_path, quality_path, lineage_path, power_path, policy_path, authority_path, manual_schema_path, index_path})


DEFINITION_STRATA = tuple(
    dict.fromkeys(item["stratum"] for item in DEFINITION["case_lineage"])
)


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="frontier-confirmatory-check-") as temporary:
        expected_root = Path(temporary)
        expected_paths = materialize(expected_root)
        expected = {
            path.relative_to(expected_root): path.read_bytes() for path in expected_paths
        }
        failures = [
            relative.as_posix()
            for relative, payload in expected.items()
            if not (REPOSITORY_ROOT / relative).is_file()
            or (REPOSITORY_ROOT / relative).read_bytes() != payload
        ]
        if failures:
            raise RuntimeError("confirmatory generated files differ: " + ", ".join(failures[:8]))


def main(argv: list[str] | None = None) -> int:
    check_mode = argv == ["--check"]
    if argv not in ([], None, ["--check"]):
        raise SystemExit("usage: _model_evolution_confirmatory_builder.py [--check]")
    check() if check_mode else materialize(REPOSITORY_ROOT)
    print("confirmatory corpus check passed" if check_mode else "confirmatory corpus generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
