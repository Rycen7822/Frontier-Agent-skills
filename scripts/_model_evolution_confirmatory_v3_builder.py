#!/usr/bin/env python3
"""Build the source-distinct Skill Evaluator confirmatory-v3 corpus."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True

import _model_evolution_confirmatory_builder as v1


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path("evaluation/model-evolution")
OUTPUT_ROOT = MODEL_ROOT / "confirmatory-v3"
SOURCE_PATH = MODEL_ROOT / "confirmatory_sources/skill_evaluator_v3.json"
V1_ROOT = MODEL_ROOT / "confirmatory-v1"
STRATA = {
    "deterministic-validation",
    "analyzer-exit",
    "cli-schema-owner",
    "comparison-class",
    "authority-boundary",
    "negative-control",
}
CASE_ID = re.compile(r"D23-[A-Z]{2}-[0-9]{2}")
ARM_IDS = {"baseline": "arm-17", "candidate": "arm-42"}
V3_MODEL_CHECKS = (
    {
        "check_id": "quality-check",
        "dimension": "quality",
        "required": True,
        "pass_condition": (
            "The deterministic factual classification passes and the explanation "
            "completely applies the case-specific semantic rubric."
        ),
    },
    {
        "check_id": "process-check",
        "dimension": "process",
        "required": True,
        "pass_condition": (
            "The answer preserves the case-specific protected boundary and names no "
            "unsupported authority or effect."
        ),
    },
)


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalize(item)
            for key, item in sorted(value.items())
            if not any(token in key.lower() for token in ("path", "digest", "marker", "case_id"))
        }
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str):
        return CASE_ID.sub("<CASE>", value)
    return value


def _validate_source(source: dict[str, Any], repository_root: Path) -> list[dict[str, Any]]:
    if (
        set(source) != {"schema", "authoring_boundary", "rubric_policy", "cases"}
        or source.get("schema") != "d23-context-clean-corpus-authoring/1"
        or not isinstance(source.get("cases"), list)
        or len(source["cases"]) != 48
    ):
        raise ValueError("confirmatory-v3 authoring source shape is invalid")
    cases = source["cases"]
    required = {
        "case_id", "stratum", "input_shape", "source", "fact_signature",
        "fixture", "expected_semantics", "protected_boundary",
        "deterministic_oracle", "semantic_rubric", "counterfactual",
        "independence_rationale",
    }
    if len({case.get("case_id") for case in cases}) != 48:
        raise ValueError("confirmatory-v3 case IDs are not unique")
    fact_signatures: set[str] = set()
    semantic_payloads: set[str] = set()
    for case in cases:
        if set(case) != required or CASE_ID.fullmatch(case["case_id"]) is None:
            raise ValueError("confirmatory-v3 case fields are invalid")
        if case["stratum"] not in STRATA or case["input_shape"] not in {"ordinary", "boundary"}:
            raise ValueError("confirmatory-v3 stratum or input shape is invalid")
        source_ref = case["source"]
        source_path = repository_root / source_ref["path"]
        if (
            set(source_ref) != {"path", "anchor"}
            or not source_path.is_file()
            or source_path.is_symlink()
            or not any(
                line.lstrip("#").strip() == source_ref["anchor"]
                for line in source_path.read_text(encoding="utf-8").splitlines()
            )
        ):
            raise ValueError(f"confirmatory-v3 source anchor is invalid for {case['case_id']}")
        peers = case["independence_rationale"].get("distinguished_from")
        if not isinstance(peers, dict) or len(peers) != 7 or case["case_id"] in peers:
            raise ValueError(f"confirmatory-v3 independence rationale is incomplete for {case['case_id']}")
        if case["counterfactual"].get("resulting_disposition") == case["fact_signature"].get("expected_disposition"):
            raise ValueError(f"confirmatory-v3 counterfactual does not change disposition for {case['case_id']}")
        rubric_text = json.dumps(
            {"fixture": case["fixture"], "rubric": case["semantic_rubric"]},
            sort_keys=True,
        ).lower()
        if re.search(r"\b(baseline|candidate|skill_disabled|force_loaded)\b", rubric_text):
            raise ValueError(f"confirmatory-v3 rubric exposes treatment identity for {case['case_id']}")
        fact_signatures.add(json.dumps(_normalize(case["fact_signature"]), sort_keys=True, separators=(",", ":")))
        semantic_payloads.add(json.dumps(_normalize({
            "fixture": case["fixture"],
            "expected_semantics": case["expected_semantics"],
            "protected_boundary": case["protected_boundary"],
        }), sort_keys=True, separators=(",", ":")))
    if len(fact_signatures) != 48 or len(semantic_payloads) != 48:
        raise ValueError("confirmatory-v3 normalized semantic cases are not independent")
    for stratum in STRATA:
        group = [case for case in cases if case["stratum"] == stratum]
        if len(group) != 8 or sum(case["input_shape"] == "ordinary" for case in group) != 4:
            raise ValueError(f"confirmatory-v3 stratum shape differs for {stratum}")
    return cases


def _slug(case_id: str) -> str:
    return "confirmatory-v3-" + case_id.removeprefix("D23-").lower()


def _fixture(case: dict[str, Any]) -> str:
    facts = json.dumps(case["fixture"], sort_keys=True, indent=2)
    criteria = "\n".join(f"- {item}" for item in case["semantic_rubric"]["criteria"])
    return (
        f"# Confirmatory case {case['case_id']}\n\n"
        f"Normative source: {case['source']['path']}#{case['source']['anchor']}\n"
        f"Input shape: {case['input_shape']}\n\n"
        f"## Supplied facts\n\n```json\n{facts}\n```\n\n"
        f"## Protected boundary\n\n{case['protected_boundary']}\n\n"
        f"## Semantic rubric\n\n{criteria}\n\n"
        "## Response contract\n\n"
        "Return one JSON object and no prose wrapper with exactly these fields: "
        "`case_id`, `owner`, `oracle_result`, `disposition`, "
        "`boundary_preserved`, and `rationale`. Derive the owner and oracle result "
        "from the supplied facts and normative contract.\n"
    )


def _definition(source: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    fixtures: dict[str, str] = {}
    definitions: list[dict[str, Any]] = []
    lineage: list[dict[str, Any]] = []
    for case in cases:
        slug = _slug(case["case_id"])
        fixture_path = f"fixtures/{slug}.md"
        fixtures[fixture_path] = _fixture(case)
        definitions.append({
            "id": slug,
            "coverage": case["stratum"],
            "task": (
                f"Read `{fixture_path}` and return the exact JSON response contract. "
                "Use only supplied facts and the controlling Skill Evaluator contract."
            ),
            "protected": case["input_shape"] == "boundary",
            "turns": 1,
            "initial_files": [fixture_path],
            "semantic_oracle": case["expected_semantics"],
        })
        lineage.append({
            "case_id": f"skill-evaluator-{slug}",
            "author_case_id": case["case_id"],
            "stratum": case["stratum"],
            "input_shape": case["input_shape"],
            "normative_requirement": case["expected_semantics"],
            "normative_source": f"{case['source']['path']}#{case['source']['anchor']}",
            "fixture": fixture_path,
            "fact_signature": case["fact_signature"],
            "deterministic_oracle": case["deterministic_oracle"],
            "model_grade_required": True,
            "semantic_rubric": case["semantic_rubric"],
            "protected_boundary": case["protected_boundary"],
            "counterfactual": case["counterfactual"],
            "independence": case["independence_rationale"],
        })
    return {
        "name": "Skill Evaluator",
        "version": "5.0.0",
        "repeats": 3,
        "context_ceiling": 28672,
        "minimum_baseline_failure_cases": 2,
        "regression_origin": "prospective-se-confirmatory-v3",
        "claims": ["level-selection", "deterministic-first", "evidence-qualified-comparison"],
        "grader_rules": [
            "Judge only the case-specific supplied facts, protected boundary, and semantic rubric.",
            "Treat the deterministic owner and oracle result as the factual classification authority.",
            "Judge semantic completeness and boundary-preserving explanation without inferring treatment identity.",
        ],
        "process_evidence": [
            "the controlling owner is explicit",
            "the deterministic oracle result matches the supplied facts",
            "the protected boundary is preserved",
        ],
        "fixtures": fixtures,
        "cases": definitions,
        "case_lineage": lineage,
        "authoring_boundary": source["authoring_boundary"],
        "rubric_policy": source["rubric_policy"],
    }


def _verifier(definition: dict[str, Any]) -> bytes:
    oracles = {
        f"skill-evaluator-{_slug(row['author_case_id'])}": {
            "author_case_id": row["author_case_id"],
            "owner": row["fact_signature"]["controlling_owner"],
            "oracle_result": row["deterministic_oracle"]["expected"],
        }
        for row in definition["case_lineage"]
    }
    encoded = json.dumps(oracles, sort_keys=True, separators=(",", ":"))
    source = f'''#!/usr/bin/env python3
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from verify_common import emit, terminal_checks
ORACLES = json.loads({encoded!r})

def main():
    result = json.loads(Path("result.json").read_text(encoding="utf-8"))
    checks = terminal_checks(result)
    case_id = result.get("envelope", {{}}).get("entry_id", "")
    parts = case_id.split(".")
    scenario = parts[1] if len(parts) > 1 else ""
    expected = ORACLES.get(scenario)
    try:
        answer = json.loads(Path("workspace/final-answer.md").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        answer = None
    valid = bool(
        expected
        and isinstance(answer, dict)
        and set(answer) == {{"case_id", "owner", "oracle_result", "disposition", "boundary_preserved", "rationale"}}
        and answer["case_id"] == expected["author_case_id"]
        and answer["owner"] == expected["owner"]
        and answer["oracle_result"] == expected["oracle_result"]
        and isinstance(answer["disposition"], str) and answer["disposition"].strip()
        and answer["boundary_preserved"] is True
        and isinstance(answer["rationale"], str) and answer["rationale"].strip()
    )
    terminal_ok, _ = checks["artifact-check"]
    checks["artifact-check"] = (
        terminal_ok and valid,
        "completed terminal binds the source-derived factual classification"
        if terminal_ok and valid else "final answer does not satisfy the case-specific factual contract",
    )
    return emit("skill-evaluator", checks, evidence_artifacts={{"artifact-check": "workspace/final-answer.md"}})

if __name__ == "__main__":
    raise SystemExit(main())
'''
    return source.encode()


def _binding(path: Path, payload: bytes) -> dict[str, str]:
    return {
        "root": "campaign",
        "path": path.as_posix(),
        "schema_version": v1._artifact_schema(path.as_posix(), payload),
    }


def _rewrite_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_paths(item) for item in value]
    if isinstance(value, str):
        return value.replace(V1_ROOT.as_posix(), OUTPUT_ROOT.as_posix())
    return value


def _rename_arms(spec: dict[str, Any], scenarios: list[dict[str, Any]]) -> None:
    for treatment in spec["treatments"]:
        old = treatment["treatment_id"]
        new = ARM_IDS[old]
        treatment["treatment_id"] = new
    for estimand in spec["analysis"]["estimands"]:
        estimand["candidate_treatment_id"] = ARM_IDS[estimand["candidate_treatment_id"]]
        estimand["comparator_treatment_id"] = ARM_IDS[estimand["comparator_treatment_id"]]


def _set_v3_model_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    model = next(grader for grader in spec["graders"] if grader["type"] == "model")
    model["checks"] = copy.deepcopy(V3_MODEL_CHECKS)
    return model["checks"]


def _calibration_gold_from_checks(
    skill_id: str,
    claims: list[str],
    checks: list[dict[str, Any]],
) -> bytes:
    rows = []
    classes = (
        ("known_good", "pass", 0),
        ("known_bad", "fail", 2),
        ("boundary", "fail", 1),
        ("abstain", "abstain", 0),
    )
    for check in checks:
        for repetition in (1, 2):
            for ordinal, (class_name, label, severity) in enumerate(classes, 1):
                position = (repetition - 1) * len(classes) + ordinal
                payload = v1.legacy.grader_semantics.semantic_payload(
                    v1.legacy._calibration_view(
                        skill_id,
                        claims,
                        check["check_id"],
                        class_name,
                        repetition,
                    ),
                    check["check_id"],
                    check["pass_condition"],
                )
                rows.append(
                    {
                        "schema_version": 3,
                        "example_id": (
                            f"{skill_id}-{check['check_id']}-cal-{position:02d}"
                        ),
                        "class": class_name,
                        "dimension": check["dimension"],
                        "check_id": check["check_id"],
                        "payload": payload,
                        "payload_digest": v1.legacy.grader_semantics.semantic_payload_hash(
                            payload
                        ),
                        "source_support": "supported",
                        "gold_label": label,
                        "gold_severity": severity,
                        "task": "frontier-engineering",
                        "language": "en",
                        "risk": "standard",
                        "host": "replace-host",
                        "model": "replace-before-scored-run",
                    }
                )
    return v1.legacy._jsonl_bytes(rows)


def materialize(repository_root: Path) -> list[Path]:
    source_bytes = (REPOSITORY_ROOT / SOURCE_PATH).read_bytes()
    source = json.loads(source_bytes)
    cases = _validate_source(source, REPOSITORY_ROOT)
    definition = _definition(source, cases)
    output = repository_root / OUTPUT_ROOT
    target = output / "sentinels/skill-evaluator"
    base_spec = json.loads((REPOSITORY_ROOT / "skill-evaluator/templates/eval-spec.example.json").read_text())
    base_scenario = json.loads((REPOSITORY_ROOT / "skill-evaluator/templates/scenarios.example.jsonl").read_text().splitlines()[0])
    fixture_payloads = {path: content.encode() for path, content in definition["fixtures"].items()}
    fixture_bindings = {path: {"path": path, "sha256": v1.legacy._sha256(payload)} for path, payload in fixture_payloads.items()}
    manifest = v1.legacy._json_bytes({
        "schema_version": 1,
        "artifacts": [
            {"path": Path(path).relative_to("fixtures").as_posix(), "digest": v1.legacy._sha256(payload), "encoding": "utf-8"}
            for path, payload in sorted(fixture_payloads.items())
        ],
    })
    scenarios = [
        v1.legacy._scenario(
            base_scenario,
            skill_id="skill-evaluator",
            case=case,
            fixture_hash=v1.legacy._sha256(manifest),
            fixture_bindings=fixture_bindings,
            process_required=True,
        )
        for case in definition["cases"]
    ]
    scenario_bytes = v1.legacy._jsonl_bytes(scenarios)
    prompt = v1.legacy._grader_prompt("skill-evaluator", definition["claims"], definition["grader_rules"])
    verifier = _verifier(definition)
    output_schema = (REPOSITORY_ROOT / "skill-evaluator/templates/grader-output.schema.json").read_bytes()
    initial: dict[Path, bytes] = {
        **{target / path: payload for path, payload in fixture_payloads.items()},
        target / "fixtures/manifest.json": manifest,
        target / "verify.py": verifier,
        target / "verify_common.py": v1.legacy.COMMON_VERIFIER_BYTES,
        target / "grader-prompt.md": prompt,
        target / "grader-output.schema.json": output_schema,
        target / "host-manifest.template.json": v1.legacy._host_manifest(),
        target / "scenarios.public.jsonl": scenario_bytes,
    }
    for skill_id in ("long-document-segmented-writing", "software-quality-workflows", "writing-plans"):
        source_root = REPOSITORY_ROOT / V1_ROOT / "sentinels" / skill_id
        destination = output / "sentinels" / skill_id
        for path in source_root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                initial[destination / path.relative_to(source_root)] = path.read_bytes()
    spec_path = target / "eval-spec.template.json"
    proof_path = target / "suite-quality-proof.json"
    quality_path = target / "suite-quality.json"
    lineage_path = output / "skill-evaluator-case-lineage-v3.json"
    power_path = output / "skill-evaluator-power-sensitivity-v3.json"
    policy_path = output / "bundle-revision-policy-v3.json"
    authority_path = output / "manual-authority-protocol-v1.json"
    manual_schema_path = output / "manual-authority-packet-v1.schema.json"
    index_path = output / "sentinel-index-v3.json"
    source_copy_path = output / "skill-evaluator-authoring-source-v3.json"
    initial[source_copy_path] = source_bytes
    spec = v1.legacy._spec(base_spec, skill_id="skill-evaluator", config=definition, scenarios=scenarios)
    _rename_arms(spec, scenarios)
    scenario_bytes = v1.legacy._jsonl_bytes(scenarios)
    v1._write(target / "scenarios.public.jsonl", scenario_bytes)
    spec["evaluation_id"] = "frontier-skill-evaluator-confirmatory-v3"
    spec["analysis"]["bootstrap_iterations"] = 10000
    spec["suite"]["order_seed"] = 804803
    deterministic = next(grader for grader in spec["graders"] if grader["type"] == "deterministic")
    deterministic["checks"][0]["pass_condition"] = "The completed Host artifact satisfies the case-specific source-derived factual contract."
    deterministic["verifier"]["input_allowlist"] = ["result.json", "workspace/final-answer.md"]
    model = next(grader for grader in spec["graders"] if grader["type"] == "model")
    model["prompt_id"] = "skill-evaluator-confirmatory-v3-grader-prompt"
    model_checks = _set_v3_model_checks(spec)
    calibration = _calibration_gold_from_checks(
        "skill-evaluator", definition["claims"], model_checks
    )
    initial[target / "scenarios.public.jsonl"] = scenario_bytes
    initial[target / "calibration-gold.jsonl"] = calibration
    for path, payload in initial.items():
        v1._write(path, payload)
    proof = v1.legacy._quality_proof(spec, scenarios, prompt_digest=v1.legacy._sha256(prompt))
    v1._write(spec_path, v1.legacy._json_bytes(spec))
    v1._write(proof_path, v1.legacy._json_bytes(proof))
    quality_path.unlink(missing_ok=True)
    result = subprocess.run([
        sys.executable, "-B", str(REPOSITORY_ROOT / "skill-evaluator/scripts/validate_eval_suite.py"),
        "suite-quality", "--spec", str(spec_path), "--proof", str(proof_path), "--output", str(quality_path),
    ], text=True, capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    spec["suite"]["quality"] = {"path": "suite-quality.json", "digest": v1.legacy._sha256(quality_path.read_bytes()), "schema_version": "suite-quality/2"}
    v1._write(spec_path, v1.legacy._json_bytes(spec))
    manual_schema = (REPOSITORY_ROOT / "evaluation/model-evolution/schemas/manual-authority-packet-v1.schema.json").read_bytes()
    v1._write(manual_schema_path, manual_schema)
    lineage = {
        "schema_version": "se-confirmatory-case-lineage/3",
        "corpus_disposition": "confirmatory_eligible",
        "authoring_source": _binding(
            OUTPUT_ROOT / source_copy_path.name,
            source_bytes,
        ),
        "case_count": 48,
        "strata": 6,
        "cases_per_stratum": 8,
        "normalization": "drop-marker-case-id-path-digest-v1",
        "cases": definition["case_lineage"],
    }
    policy = v1._policy()
    policy["authority_id"] = "frontier-bundle-8-confirmatory-v3"
    policy["registered_at"] = "2026-08-25T00:00:00Z"
    power = v1._power()
    power["schema_version"] = "se-confirmatory-power-sensitivity/3"
    protocol = {
        "schema_version": "manual-authority-protocol/1",
        "authority_owner": "release-owner",
        "custodian_id": "confirmatory-manual-custodian",
        "packet_schema": _binding(OUTPUT_ROOT / manual_schema_path.name, manual_schema),
        "protocol": "post-holdout-independent-signoff",
        "decision_values": ["approve", "hold", "reject"],
        "signing_conditions": ["four_revision_reports_closed", "sealed_holdout_closed", "packet_identity_verified"],
        "decision": None,
        "signed_attestation": None,
    }
    for path, value in ((lineage_path, lineage), (power_path, power), (policy_path, policy), (authority_path, protocol)):
        v1._write(path, v1.legacy._json_bytes(value))
    v1_index = json.loads((REPOSITORY_ROOT / V1_ROOT / "sentinel-index-v3.json").read_text())
    skills = _rewrite_paths(copy.deepcopy(v1_index["skills"]))
    relative = OUTPUT_ROOT / "sentinels/skill-evaluator"
    skills["skill-evaluator"] = {
        "critical_bucket_id": "skill-evaluator-confirmatory-critical-v3",
        "spec_template": _binding(relative / "eval-spec.template.json", spec_path.read_bytes()),
        "public_scenarios": _binding(relative / "scenarios.public.jsonl", scenario_bytes),
        "calibration_gold": _binding(relative / "calibration-gold.jsonl", calibration),
        "calibration_request_ceiling": len(calibration.splitlines()),
        "fixture_roots": [
            _binding(relative / "fixtures/manifest.json", manifest),
            *[_binding(relative / path, fixture_payloads[path]) for path in sorted(fixture_payloads)],
        ],
        "verifier_roots": [
            _binding(relative / "verify.py", verifier),
            _binding(relative / "verify_common.py", v1.legacy.COMMON_VERIFIER_BYTES),
        ],
        "required_coverage_tags": sorted(STRATA),
        "protected_case_ids": [f"skill-evaluator-{case['id']}" for case in definition["cases"] if case["protected"]],
        "external_holdout_contract_id": "skill-evaluator-confirmatory-external-holdout-v1",
        "holdout_case_ceiling": 2,
    }
    catalog_paths = sorted({*initial, spec_path, proof_path, quality_path, lineage_path, power_path, policy_path, authority_path, manual_schema_path})
    index = {
        "schema_version": "model-evolution-sentinel-index/3",
        "sentinel_id": "frontier-four-skill-confirmatory-v3",
        "revision_policy": _binding(OUTPUT_ROOT / policy_path.name, policy_path.read_bytes()),
        "manual_authority_protocol": _binding(OUTPUT_ROOT / authority_path.name, authority_path.read_bytes()),
        "case_lineage": _binding(OUTPUT_ROOT / lineage_path.name, lineage_path.read_bytes()),
        "power_sensitivity": _binding(OUTPUT_ROOT / power_path.name, power_path.read_bytes()),
        "catalog_files": [_binding(path.relative_to(repository_root), path.read_bytes()) for path in catalog_paths],
        "skills": skills,
    }
    v1._write(index_path, v1.legacy._json_bytes(index))
    expected = {*initial, spec_path, proof_path, quality_path, lineage_path, power_path, policy_path, authority_path, manual_schema_path, index_path}
    v1.legacy._prune_generated_files(output, expected)
    return sorted(expected)


def check() -> None:
    with tempfile.TemporaryDirectory(prefix="frontier-confirmatory-v3-check-") as temporary:
        expected_root = Path(temporary)
        expected = {
            path.relative_to(expected_root): path.read_bytes()
            for path in materialize(expected_root)
        }
        failures = [
            path.as_posix()
            for path, payload in expected.items()
            if not (REPOSITORY_ROOT / path).is_file() or (REPOSITORY_ROOT / path).read_bytes() != payload
        ]
        if failures:
            raise RuntimeError("confirmatory-v3 generated files differ: " + ", ".join(failures[:8]))


def main(argv: list[str] | None = None) -> int:
    if argv not in ([], None, ["--check"]):
        raise SystemExit("usage: _model_evolution_confirmatory_v3_builder.py [--check]")
    check() if argv == ["--check"] else materialize(REPOSITORY_ROOT)
    print("confirmatory-v3 corpus check passed" if argv == ["--check"] else "confirmatory-v3 corpus generated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
