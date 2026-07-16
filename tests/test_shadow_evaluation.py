from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_shadow.py"
SPEC = importlib.util.spec_from_file_location("evaluate_shadow", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
evaluator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluator)


FAMILIES = [
    "deterministic_bugfix",
    "unknown_reproducible_bug",
    "behavior_preserving_refactor",
    "public_api_migration",
    "dependency_runtime_upgrade",
    "performance_with_parity",
    "security_boundary",
    "browser_installed_runtime",
    "flaky_concurrency_fault",
    "ci_build_release_evidence",
    "multi_module_feature",
    "underdetermined_product",
    "subjective_no_oracle",
    "external_authority_blocked",
    "verifier_hacking_trap",
    "source_drift_dirty_work",
    "slow_external_job",
    "upfront_plan_anchoring",
]
ABLATIONS = [
    "no_policy_graph",
    "no_card_navigation",
    "no_exact_transport_ref",
    "no_context_lease",
    "no_artifact_boundary_reroute",
    "no_controller_context_separation",
    "mutable_verifier",
    "no_local_invalidation",
    "no_one_card_limit",
]


def labels() -> dict:
    return {
        "intent_determinacy": "determinate",
        "machine_observability": "high",
        "verifier_separability": "separable",
        "failure_locality": "local",
        "side_effect_risk": "bounded",
        "public_contract_surface": "none",
        "state_coupling": "low",
        "verification_cost": "low",
        "strategy_ambiguity": "single_family",
        "resume_value": "low",
        "parallelism_value": "low",
    }


def complete_corpus(*, historical: int = 50) -> dict:
    strata = (["simple"] * 50) + (["medium"] * 50) + (["long"] * 30) + (["should_not_close"] * 20)
    cases = []
    for index, stratum in enumerate(strata, 1):
        case_labels = labels()
        should_close = stratum != "should_not_close"
        if not should_close:
            case_labels["intent_determinacy"] = "underdetermined"
            case_labels["machine_observability"] = "none"
            case_labels["verifier_separability"] = "not_separable"
        cases.append({
            "eval_case_id": f"EVAL-{index:04d}",
            "title": f"paired shadow case {index}",
            "family": FAMILIES[(index - 1) % len(FAMILIES)],
            "stratum": stratum,
            "provenance": "historical" if index <= historical else "synthetic",
            "request_ref": f"restricted:history/request/EVAL-{index:04d}" if index <= historical else f"fixture:request/EVAL-{index:04d}",
            "repository_ref": f"restricted:history/repo/EVAL-{index:04d}" if index <= historical else f"fixture:repo/EVAL-{index:04d}",
            "repository_revision": f"rev-{index:04d}",
            "labels": case_labels,
            "should_close": should_close,
            "portfolio_eligible": False,
            "hidden_oracle_ref": f"restricted:oracle/EVAL-{index:04d}",
            "conditions": ["C0", "C1", "C2", "C3", "C4"],
        })
    return {
        "schema_version": "p5-eval-corpus/1.0",
        "corpus_id": "CORPUS-TEST-001",
        "cohort_id": "COHORT-TEST-001",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
        "bundle_hash": "sha256:" + "1" * 64,
        "controller_hash": "sha256:" + "2" * 64,
        "activation_level": "shadow",
        "multi_candidate_enabled": False,
        "target_counts": {"simple": 50, "medium": 50, "long": 30, "should_not_close": 20},
        "cases": cases,
    }


def run_record(case: dict, condition: str) -> dict:
    index = int(case["eval_case_id"].split("-")[-1])
    should_close = case["should_close"]
    closure_selected = condition == "C4" or (condition == "C3" and should_close)
    hard_closed = should_close and (condition == "C3" or index % 5 != 0)
    input_tokens = {"C0": 1000, "C1": 1020, "C2": 1040, "C3": 1300, "C4": 1700}[condition]
    wall_time = {"C0": 10.0, "C1": 10.2, "C2": 10.4, "C3": 13.0, "C4": 18.0}[condition]
    terminal_needed = not should_close
    return {
        "schema_version": "p5-eval-run/1.0",
        "run_id": f"RUN-{case['eval_case_id']}-{condition}",
        "eval_case_id": case["eval_case_id"],
        "condition": condition,
        "cohort_id": "COHORT-TEST-001",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "max",
        "bundle_hash": "sha256:" + "1" * 64,
        "controller_hash": "sha256:" + "2" * 64,
        "condition_hash": "sha256:" + {"C0": "4", "C1": "5", "C2": "6", "C3": "7", "C4": "8"}[condition] * 64,
        "repository_revision": case["repository_revision"],
        "fixed_variables_hash": "sha256:" + "3" * 64,
        "route_result_ref": f"artifact:route/{case['eval_case_id']}-{condition}",
        "contract_ref": f"artifact:contract/{case['eval_case_id']}" if closure_selected else None,
        "terminal_ref": f"artifact:terminal/{case['eval_case_id']}" if terminal_needed else None,
        "metrics_ref": f"artifact:metrics/{case['eval_case_id']}-{condition}",
        "hidden_oracle_ref": case["hidden_oracle_ref"],
        "human_labels_ref": f"restricted:labels/{case['eval_case_id']}",
        "closure_selected": closure_selected,
        "remote_writes": False,
        "publication_ceiling": "local_patch" if condition in {"C3", "C4"} else "none",
        "outcome": {
            "hard_constraint_closure": hard_closed if should_close else None,
            "hidden_defect_escape": False,
            "intent_fidelity": 1.0,
            "scope_violation_count": 0,
            "protected_surface_violation_count": 0,
            "authority_violation_count": 0,
            "public_contract_violation_count": 0,
            "verifier_escape": False,
            "severe_defect_escape": not hard_closed if should_close else False,
            "terminal_correct": True if terminal_needed else None,
            "certificate_sufficient": True if terminal_needed else None,
        },
        "framework_tax": {
            "input_tokens": input_tokens,
            "output_reasoning_tokens": input_tokens // 2,
            "model_calls": 1,
            "subagent_calls": 0,
            "raw_tool_calls": 4,
            "verifier_calls": 1,
            "critical_path_depth": 1,
            "wall_time_seconds": wall_time,
            "compute_cost": 1.0,
            "context_capsule_bytes": 2048,
            "full_reference_bytes": 4096,
            "controller_overhead_seconds": 0.2,
        },
        "autonomy": {
            "midrun_user_questions": 0,
            "safe_default_count": 0,
            "incorrect_safe_default_count": 0,
            "blocked_action_violations": 0,
            "unattended_terminal": True,
            "crash_resume_succeeded": None,
            "manual_controller_repair": False,
        },
    }


def complete_runs(corpus: dict) -> list[dict]:
    return [run_record(case, condition) for case in corpus["cases"] for condition in case["conditions"]]


def passing_controls(corpus: dict) -> dict:
    policies = [
        policy
        for skill in ("software-quality-workflows", "writing-plans")
        for policy in json.loads(
            (ROOT / skill / "registries" / "policy-owners.json").read_text(encoding="utf-8")
        )["policies"]
    ]
    references = []
    for policy in policies:
        machine_owned = policy["owner_type"] == "machine"
        references.append({
            "policy_id": policy["policy_id"],
            "owner_type": policy["owner_type"],
            "owner_id": policy["owner_id"],
            "decision_case_status": "passed",
            "precision_case_status": "not_applicable" if machine_owned else "passed",
            "exclusion_case_status": "not_applicable" if machine_owned else "passed",
            "ablation_status": "passed",
            "evidence_refs": [f"artifact:policy-eval/{policy['policy_id']}"],
        })
    return {
        "schema_version": "p5-control-evidence/1.0",
        "cohort_id": corpus["cohort_id"],
        "bundle_hash": corpus["bundle_hash"],
        "controller_hash": corpus["controller_hash"],
        "ablations": [
            {"id": item, "status": "passed", "evidence_refs": [f"artifact:ablation/{item}"]}
            for item in ABLATIONS
        ],
        "reference_evaluations": references,
    }


class ShadowEvaluationTests(unittest.TestCase):
    def test_p5_schemas_are_strict_draft_2020_12_and_accept_canonical_examples(self) -> None:
        corpus = complete_corpus()
        run = run_record(corpus["cases"][0], "C3")
        controls = passing_controls(corpus)
        report = evaluator.evaluate_shadow(corpus, complete_runs(corpus), controls)
        examples = {
            "p5-eval-corpus.schema.json": corpus,
            "p5-eval-run.schema.json": run,
            "p5-control-evidence.schema.json": controls,
            "p5-eval-report.schema.json": report,
        }
        for filename, example in examples.items():
            with self.subTest(schema=filename):
                schema = json.loads((ROOT / "evaluation" / "schemas" / filename).read_text(encoding="utf-8"))
                Draft202012Validator.check_schema(schema)
                self.assertEqual([], list(Draft202012Validator(schema).iter_errors(example)))
                unknown = {**example, "unexpected": True}
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(unknown)))

    def test_seed_corpus_is_valid_but_cannot_promote_without_live_pairs(self) -> None:
        corpus = json.loads((ROOT / "evaluation" / "corpus" / "p5-shadow-corpus.json").read_text(encoding="utf-8"))
        controls = json.loads((ROOT / "evaluation" / "p5-control-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual([], evaluator.validate_corpus(corpus))
        self.assertEqual([], evaluator.validate_control_evidence(controls, corpus=corpus))
        self.assertEqual(set(FAMILIES), {case["family"] for case in corpus["cases"]})
        self.assertFalse(any(case["provenance"] == "historical" for case in corpus["cases"]))
        self.assertTrue(all(item["status"] == "not_run" for item in controls["ablations"]))
        report = evaluator.evaluate_shadow(corpus, [], controls)
        self.assertEqual("remain_shadow", report["decision"])
        self.assertIn("minimum_paired_samples", report["failed_gates"])
        self.assertEqual("shadow", report["activation_ceiling"])
        checked_in_report = json.loads((ROOT / "evaluation" / "p5-shadow-report.json").read_text(encoding="utf-8"))
        for schema_name, artifact in (
            ("p5-eval-corpus.schema.json", corpus),
            ("p5-control-evidence.schema.json", controls),
            ("p5-eval-report.schema.json", checked_in_report),
        ):
            schema = json.loads((ROOT / "evaluation" / "schemas" / schema_name).read_text(encoding="utf-8"))
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(artifact)))

    def test_seed_corpus_rebuild_is_byte_deterministic(self) -> None:
        source = ROOT / "evaluation" / "corpus" / "p5-shadow-corpus.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "corpus.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_shadow_seed_corpus.py"), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            self.assertEqual(source.read_bytes(), output.read_bytes())

    def test_pending_control_evidence_rebuild_is_byte_deterministic(self) -> None:
        corpus = ROOT / "evaluation" / "corpus" / "p5-shadow-corpus.json"
        source = ROOT / "evaluation" / "p5-control-evidence.json"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "controls.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_shadow_control_evidence.py"),
                    "--corpus", str(corpus),
                    "--output", str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
            self.assertEqual(source.read_bytes(), output.read_bytes())

    def test_complete_safe_paired_cohort_can_reach_canary_eligibility(self) -> None:
        corpus = complete_corpus()
        runs = complete_runs(corpus)
        self.assertEqual([], evaluator.validate_corpus(corpus))
        self.assertTrue(all(not evaluator.validate_run(run) for run in runs))
        report = evaluator.evaluate_shadow(corpus, runs, passing_controls(corpus))
        self.assertEqual("eligible_for_p6_canary", report["decision"])
        self.assertEqual([], report["failed_gates"])
        self.assertTrue(report["gates"]["closure_benefit"])
        self.assertTrue(report["gates"]["adaptive_beats_always_on"])

    def test_missing_ablation_and_reference_evidence_cannot_promote(self) -> None:
        corpus = complete_corpus()
        report = evaluator.evaluate_shadow(corpus, complete_runs(corpus))
        self.assertEqual("remain_shadow", report["decision"])
        self.assertFalse(report["gates"]["ablation_coverage"])
        self.assertFalse(report["gates"]["reference_evaluation_coverage"])

    def test_any_scope_escape_forces_shadow_even_when_other_metrics_pass(self) -> None:
        corpus = complete_corpus()
        runs = complete_runs(corpus)
        escaped = next(run for run in runs if run["condition"] == "C3")
        escaped["outcome"]["protected_surface_violation_count"] = 1
        report = evaluator.evaluate_shadow(corpus, runs, passing_controls(corpus))
        self.assertEqual("remain_shadow", report["decision"])
        self.assertFalse(report["gates"]["zero_scope_authority_protected_escapes"])

    def test_insufficient_historical_share_and_missing_pairs_fail_closed(self) -> None:
        corpus = complete_corpus(historical=49)
        runs = complete_runs(corpus)[:-1]
        report = evaluator.evaluate_shadow(corpus, runs, passing_controls(corpus))
        self.assertEqual("remain_shadow", report["decision"])
        self.assertIn("historical_share", report["failed_gates"])
        self.assertIn("condition_pairing", report["failed_gates"])

    def test_fixed_variables_and_condition_identity_cannot_drift_within_pairs(self) -> None:
        corpus = complete_corpus()
        runs = complete_runs(corpus)
        next(run for run in runs if run["eval_case_id"] == "EVAL-0001" and run["condition"] == "C3")["fixed_variables_hash"] = "sha256:" + "9" * 64
        next(run for run in runs if run["eval_case_id"] == "EVAL-0002" and run["condition"] == "C2")["condition_hash"] = "sha256:" + "a" * 64
        report = evaluator.evaluate_shadow(corpus, runs, passing_controls(corpus))
        self.assertEqual("remain_shadow", report["decision"])
        self.assertFalse(report["gates"]["fixed_variable_pairing"])
        self.assertFalse(report["gates"]["condition_identity"])

    def test_c5_is_rejected_without_case_and_corpus_portfolio_authority(self) -> None:
        corpus = complete_corpus()
        run = run_record(corpus["cases"][0], "C3")
        run["condition"] = "C5"
        run["run_id"] = "RUN-EVAL-0001-C5"
        errors = evaluator.validate_run(run, corpus=corpus)
        self.assertTrue(any("E_PORTFOLIO_DISABLED" in error for error in errors))

    def test_malformed_run_is_bounded_input_failure_not_an_aggregator_crash(self) -> None:
        corpus = complete_corpus()
        runs = complete_runs(corpus)
        malformed = next(run for run in runs if run["condition"] == "C2")
        del malformed["framework_tax"]
        report = evaluator.evaluate_shadow(corpus, runs, passing_controls(corpus))
        self.assertEqual("remain_shadow", report["decision"])
        self.assertFalse(report["gates"]["input_validity"])
        self.assertTrue(any("E_SCHEMA_INVALID" in item for item in report["validation_errors"]))

    def test_report_write_is_canonical_and_no_overwrite(self) -> None:
        corpus = complete_corpus()
        report = evaluator.evaluate_shadow(corpus, complete_runs(corpus), passing_controls(corpus))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            evaluator.write_report(report, path)
            first = path.read_bytes()
            self.assertEqual(report, json.loads(first))
            with self.assertRaises(FileExistsError):
                evaluator.write_report(report, path)

    def test_input_loader_rejects_duplicate_keys_nonfinite_values_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.jsonl"
            duplicate.write_text('{"run_id":"one","run_id":"two"}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate key"):
                evaluator._load_jsonl(duplicate)
            nonfinite = root / "nonfinite.json"
            nonfinite.write_text('{"value":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                evaluator._load_json(nonfinite)
            linked = root / "linked.json"
            linked.symlink_to(nonfinite)
            with self.assertRaises((OSError, ValueError)):
                evaluator._load_json(linked)


if __name__ == "__main__":
    unittest.main()
