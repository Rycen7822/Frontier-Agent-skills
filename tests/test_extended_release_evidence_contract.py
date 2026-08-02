from __future__ import annotations

import io
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_codex_plugin.py"
SOURCE_HASH = "sha256:" + "1" * 64
PLUGIN_HASH = "sha256:" + "2" * 64
CONTROLLER_HASH = "sha256:" + "3" * 64
EVALUATOR_HASH = "sha256:" + "4" * 64
REQUEST_MANIFEST_HASH = "sha256:" + "5" * 64
REVISION = "a" * 40
ACTIVATION = {
    "long-document-segmented-writing": "implicit",
    "skill-evaluator": "explicit_only",
    "software-quality-workflows": "explicit_only",
    "writing-plans": "explicit_only",
}
ACTIVATION_BOOL = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": False,
    "writing-plans": False,
}


def load_builder():
    spec = importlib.util.spec_from_file_location("release_contract_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load plugin builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def self_hash(value: dict) -> str:
    clean = dict(value)
    clean.pop("report_hash", None)
    return digest(json.dumps(
        clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8"))


def write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    return encoded


def gate_contract(gate_id: str) -> dict:
    return {
        "gate_id": gate_id,
        "metric_id": f"{gate_id}-metric",
        "evidence_artifact_kind": "report_local",
        "selector": "scalar",
        "operator": "eq",
        "threshold": {
            "kind": "scalar",
            "scalar": 0,
            "numerator": None,
            "denominator": None,
            "comparator_metric_id": None,
        },
        "critical": True,
    }


def gate_result(contract: dict) -> dict:
    return {
        "gate_id": contract["gate_id"],
        "metric_id": contract["metric_id"],
        "evidence_artifact_kind": contract["evidence_artifact_kind"],
        "observed": 0,
        "passed": True,
    }


class ExtendedReleaseEvidenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = load_builder()
        revision = mock.patch.object(
            self.builder, "_source_revision", return_value=REVISION,
        )
        revision.start()
        self.addCleanup(revision.stop)

    def test_release_budget_matches_controller_frozen_matrix(self) -> None:
        sys.path.insert(0, str(ROOT))
        try:
            from evaluation.controller import specs
        finally:
            sys.path.remove(str(ROOT))

        budget = self.builder.EXPECTED_FORMAL_BUDGET
        self.assertEqual(
            (
                budget["scored_call_hard_cap"],
                budget["grader_calibration_call_hard_cap"],
                budget["reviewer_calibration_call_hard_cap"],
                budget["scheduled_provider_calls"],
            ),
            specs.PHASE_BUDGETS["formal"],
        )
        self.assertEqual(
            sum(
                usage["provider_calls"]
                for usage in self.builder.EXPECTED_FORMAL_ARM_USAGE.values()
            ),
            budget["scored_call_hard_cap"],
        )

    def make_contract(self, root: Path) -> tuple[Path, Path, dict]:
        source = root / "source"
        run = root / "run"
        (source / "packaging" / "schemas").mkdir(parents=True)
        (source / "evaluation").mkdir()
        for name in (
            "release-evidence.schema.json",
            "p3-decision-contract-v4.schema.json",
            "p3-arm-report-v3.schema.json",
            "frontier-longitudinal-report-v1.schema.json",
        ):
            (source / "packaging" / "schemas" / name).write_bytes(
                (ROOT / "packaging" / "schemas" / name).read_bytes()
            )
        write_json(source / "frontier-engineering.bundle.json", {
            "bundle_id": "frontier-engineering/6.0.0",
            "skills": {
                "skill-evaluator": {
                    "root_hash": EVALUATOR_HASH,
                },
            },
        })
        static = {
            "bundle_id": "frontier-engineering/6.0.0",
            "version": "6.0.0",
            "skill_activation": ACTIVATION_BOOL,
        }
        static["report_hash"] = self_hash(static)
        write_json(source / "evaluation" / "static-contract-diagnostic.json", static)

        candidate_identity = {
            "candidate_revision": REVISION,
            "candidate_source_tree_hash": SOURCE_HASH,
            "candidate_plugin_tree_hash": PLUGIN_HASH,
        }
        identity = {
            **candidate_identity,
            "controller_content_hash": CONTROLLER_HASH,
            "evaluator_source_hash": EVALUATOR_HASH,
        }
        evaluated_skill_ids = [
            "software-quality-workflows",
            "writing-plans",
        ]
        gate_contracts = {
            "software-quality-workflows": gate_contract("sqw-formal-fixture"),
            "writing-plans": gate_contract("wp-formal-fixture"),
        }
        decision_contract = {
            "schema_version": "p3-decision-contract/4.0",
            **identity,
            "request_manifest_content_hash": REQUEST_MANIFEST_HASH,
            "evaluated_skill_ids": evaluated_skill_ids,
            "budget_contract": {
                "schema_version": "provider-budget-contract/1.0",
                "scheduled_provider_calls": 214,
                "scored_call_hard_cap": 206,
                "grader_calibration_call_hard_cap": 4,
                "reviewer_calibration_call_hard_cap": 4,
                "provider_call_hard_cap": 214,
            },
            "gate_contract": {
                "schema_version": "gate-contract/1.0",
                **{
                    study: [contract]
                    for study, contract in gate_contracts.items()
                },
            },
        }
        decision_contract["decision_contract_hash"] = self_hash(decision_contract)
        decision_bytes = write_json(
            run / "l2" / "p3-decision-contract.json",
            decision_contract,
        )
        decision_hash = digest(decision_bytes)

        def arm(
            study: str,
            *,
            provider_calls: int,
            observed: int,
            graded: int,
        ) -> dict:
            contract = gate_contracts[study]
            report = {
                "schema_version": "p3-arm-report/3.0",
                "study": study,
                **identity,
                "decision_contract_content_hash": decision_hash,
                "native_artifact_content_hashes": {
                    "analysis_summary": "sha256:" + "5" * 64,
                    "failure_index": "sha256:" + "6" * 64,
                    "run_index": "sha256:" + "7" * 64,
                },
                "manual_receipt_content_hash": None,
                "evidence_status": "complete",
                "usefulness_status": "supported",
                "metrics": {
                    contract["metric_id"]: {"scalar": 0},
                },
                "gate_results": [gate_result(contract)],
                "usage_closure": {
                    "scheduled": provider_calls,
                    "observed": observed,
                    "graded": graded,
                    "missing": 0,
                    "duplicate": 0,
                    "retries": 0,
                    "provider_calls": provider_calls,
                },
            }
            if study == "writing-plans":
                report["metrics"]["prior_reference_migration_claim"] = {
                    "status": "supported",
                    "minimum_reference_cases": 4,
                    "observed_reference_cases": 4,
                    "mixed_prior_cases": 0,
                    "reduction_selector": "lower",
                    "minimum_reduction": 0.5,
                    "observed_reduction": 0.5,
                }
            report["report_hash"] = self_hash(report)
            return report

        sqw = arm(
            "software-quality-workflows",
            provider_calls=108,
            observed=108,
            graded=12,
        )
        wp = arm(
            "writing-plans",
            provider_calls=98,
            observed=98,
            graded=10,
        )
        sqw_bytes = write_json(
            run / "l2" / "software-quality-workflows" / "report.json",
            sqw,
        )
        wp_bytes = write_json(run / "l2" / "writing-plans" / "report.json", wp)
        arm_hashes = {
            "software-quality-workflows": digest(sqw_bytes),
            "writing-plans": digest(wp_bytes),
        }
        aggregate = {
            "schema_version": "p3-aggregate-report/2.0",
            **candidate_identity,
            "decision_contract_content_hash": decision_hash,
            "evaluated_skill_ids": evaluated_skill_ids,
            "arm_report_content_hashes": arm_hashes,
            "aggregate_status": "passed",
            "scored_model_calls": 206,
            "grader_calibration_calls": 4,
            "reviewer_calibration_calls": 4,
            "apparatus_model_calls": 8,
            "total_provider_calls": 214,
            "retries": 0,
            "gates": [],
        }
        aggregate["report_hash"] = self_hash(aggregate)
        aggregate_bytes = write_json(run / "l2" / "aggregate-report.json", aggregate)
        longitudinal = {
            "schema_version": "frontier-longitudinal-report/1.0",
            **identity,
            "decision_contract_content_hash": decision_hash,
            "campaign_contract_content_hash": "sha256:" + "8" * 64,
            "selected_receipt_set_hash": "sha256:" + "9" * 64,
            "step_result_content_hashes": {
                f"step-{number:02d}": "sha256:" + "a" * 64
                for number in range(1, 13)
            },
            "metrics": {"permanent_test_loc_delta": 0},
            "gate_results": [{
                "gate_id": "p4-fixture",
                "metric_id": "permanent-test-loc-delta",
                "evidence_artifact_kind": "report_local",
                "observed": 0,
                "passed": True,
            }],
            "evidence_status": "complete",
            "usefulness_status": "supported",
            "longitudinal_status": "passed",
        }
        longitudinal["report_hash"] = self_hash(longitudinal)
        longitudinal_bytes = write_json(run / "longitudinal" / "report.json", longitudinal)
        activation = {
            "schema_version": "activation-decision/2.0",
            "bundle_id": "frontier-engineering/6.0.0",
            "candidate_revision": REVISION,
            "source_tree_hash": SOURCE_HASH,
            "candidate_plugin_tree_hash": PLUGIN_HASH,
            "p3_decision_contract_hash": decision_hash,
            "scored_arm_report_hashes": arm_hashes,
            "aggregate_l2_report_hash": digest(aggregate_bytes),
            "longitudinal_report_hash": digest(longitudinal_bytes),
            "approved_skill_activation": dict(ACTIVATION),
            "remote_writes": False,
            "decision": "approve",
            "blocking_observations": [],
        }
        activation_bytes = write_json(run / "activation-decision.json", activation)
        evidence = {
            "schema_version": "release-evidence/4.0",
            "bundle_id": "frontier-engineering/6.0.0",
            "bundle_version": "6.0.0",
            "source_tree_hash": SOURCE_HASH,
            "plugin_tree_hash": PLUGIN_HASH,
            "source_revision": REVISION,
            "source_revision_signed": True,
            "source_clean": True,
            "deterministic_report_hash": static["report_hash"],
            "p3_decision_contract_hash": decision_hash,
            "evaluated_skill_ids": evaluated_skill_ids,
            "arm_report_content_hashes": arm_hashes,
            "l2_scored_report_hash": digest(aggregate_bytes),
            "longitudinal_report_hash": digest(longitudinal_bytes),
            "activation_decision_hash": digest(activation_bytes),
            "approved_skill_activation": dict(ACTIVATION),
            "remote_writes": False,
            "release_gate": "passed",
        }
        evidence_path = run / "release-evidence.json"
        write_json(evidence_path, evidence)
        return source, evidence_path, evidence

    def validate(self, source: Path, evidence_path: Path, *, git_ok: bool = True) -> dict:
        with mock.patch.object(self.builder, "_git_release_source_ok", return_value=git_ok):
            return self.builder.validate_release_evidence(
                evidence_path,
                source_root=source,
                manifest={"bundle_version": "6.0.0"},
                source_tree_hash=SOURCE_HASH,
                plugin_tree_hash=PLUGIN_HASH,
            )

    def rebind_aggregate_usage(
        self,
        evidence_path: Path,
        updates: dict[str, int],
    ) -> None:
        aggregate_path = evidence_path.parent / "l2" / "aggregate-report.json"
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregate.update(updates)
        aggregate["report_hash"] = self_hash(aggregate)
        aggregate_hash = digest(write_json(aggregate_path, aggregate))

        activation_path = evidence_path.parent / "activation-decision.json"
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        activation["aggregate_l2_report_hash"] = aggregate_hash
        activation_hash = digest(write_json(activation_path, activation))

        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["l2_scored_report_hash"] = aggregate_hash
        evidence["activation_decision_hash"] = activation_hash
        write_json(evidence_path, evidence)

    def rebind_arm(
        self,
        evidence_path: Path,
        skill_id: str,
        arm: dict,
    ) -> None:
        l2_root = evidence_path.parent / "l2"
        arm["report_hash"] = self_hash(arm)
        arm_hash = digest(
            write_json(l2_root / skill_id / "report.json", arm)
        )
        aggregate_path = l2_root / "aggregate-report.json"
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregate["arm_report_content_hashes"][skill_id] = arm_hash
        aggregate["report_hash"] = self_hash(aggregate)
        aggregate_hash = digest(write_json(aggregate_path, aggregate))
        activation_path = evidence_path.parent / "activation-decision.json"
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
        activation["scored_arm_report_hashes"][skill_id] = arm_hash
        activation["aggregate_l2_report_hash"] = aggregate_hash
        activation_hash = digest(write_json(activation_path, activation))
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["arm_report_content_hashes"][skill_id] = arm_hash
        evidence["l2_scored_report_hash"] = aggregate_hash
        evidence["activation_decision_hash"] = activation_hash
        write_json(evidence_path, evidence)

    def load_arm(self, evidence_path: Path, skill_id: str) -> dict:
        arm_path = evidence_path.parent / "l2" / skill_id / "report.json"
        return json.loads(arm_path.read_text(encoding="utf-8"))

    def rebind_formal_budget(
        self,
        evidence_path: Path,
        *,
        budget: dict[str, int],
        usage: dict[str, int],
    ) -> None:
        root = evidence_path.parent
        l2_root = root / "l2"
        decision_path = l2_root / "p3-decision-contract.json"
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        decision["budget_contract"].update(budget)
        decision.pop("decision_contract_hash")
        decision["decision_contract_hash"] = self_hash(decision)
        decision_hash = digest(write_json(decision_path, decision))

        arm_hashes = {}
        for skill_id in (
            "software-quality-workflows",
            "writing-plans",
        ):
            arm_path = l2_root / skill_id / "report.json"
            arm = json.loads(arm_path.read_text(encoding="utf-8"))
            arm["decision_contract_content_hash"] = decision_hash
            arm["report_hash"] = self_hash(arm)
            arm_hashes[skill_id] = digest(write_json(arm_path, arm))

        aggregate_path = l2_root / "aggregate-report.json"
        aggregate = json.loads(aggregate_path.read_text(encoding="utf-8"))
        aggregate["decision_contract_content_hash"] = decision_hash
        aggregate["arm_report_content_hashes"] = arm_hashes
        aggregate.update(usage)
        aggregate["report_hash"] = self_hash(aggregate)
        aggregate_hash = digest(write_json(aggregate_path, aggregate))

        longitudinal_path = root / "longitudinal" / "report.json"
        longitudinal = json.loads(
            longitudinal_path.read_text(encoding="utf-8")
        )
        longitudinal["decision_contract_content_hash"] = decision_hash
        longitudinal["report_hash"] = self_hash(longitudinal)
        longitudinal_hash = digest(
            write_json(longitudinal_path, longitudinal)
        )

        activation_path = root / "activation-decision.json"
        activation = json.loads(
            activation_path.read_text(encoding="utf-8")
        )
        activation.update({
            "p3_decision_contract_hash": decision_hash,
            "scored_arm_report_hashes": arm_hashes,
            "aggregate_l2_report_hash": aggregate_hash,
            "longitudinal_report_hash": longitudinal_hash,
        })
        activation_hash = digest(write_json(activation_path, activation))

        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence.update({
            "p3_decision_contract_hash": decision_hash,
            "arm_report_content_hashes": arm_hashes,
            "l2_scored_report_hash": aggregate_hash,
            "longitudinal_report_hash": longitudinal_hash,
            "activation_decision_hash": activation_hash,
        })
        write_json(evidence_path, evidence)

    def test_valid_contract_binds_all_reports_and_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, evidence = self.make_contract(Path(directory))
            self.assertEqual(evidence, self.validate(source, evidence_path))

    def test_combined_and_family_budget_fields_are_rejected(self) -> None:
        obsolete_fields = {
            "calibration_call_hard_cap": 12,
            "family_scored_call_hard_cap": 296,
            "family_calibration_call_hard_cap": 12,
            "family_provider_call_hard_cap": 308,
        }
        for field, value in obsolete_fields.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                source, evidence_path, _ = self.make_contract(Path(directory))
                decision_path = (
                    evidence_path.parent / "l2" / "p3-decision-contract.json"
                )
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
                decision["budget_contract"][field] = value
                decision["decision_contract_hash"] = self_hash(decision)
                write_json(decision_path, decision)
                with self.assertRaisesRegex(ValueError, "P3 decision contract"):
                    self.validate(source, evidence_path)
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            decision_path = (
                evidence_path.parent / "l2" / "p3-decision-contract.json"
            )
            decision = json.loads(decision_path.read_text(encoding="utf-8"))
            decision.pop("request_manifest_content_hash")
            decision["decision_contract_hash"] = self_hash(decision)
            write_json(decision_path, decision)
            with self.assertRaisesRegex(ValueError, "P3 decision contract"):
                self.validate(source, evidence_path)

    def test_split_budget_partitions_and_sums_fail_closed(self) -> None:
        invalid_usage = {
            "grader_cap": {
                "grader_calibration_calls": 9,
                "reviewer_calibration_calls": 3,
            },
            "reviewer_cap": {
                "grader_calibration_calls": 7,
                "reviewer_calibration_calls": 5,
            },
            "apparatus_sum": {"apparatus_model_calls": 11},
            "total_sum": {"total_provider_calls": 307},
        }
        for case, updates in invalid_usage.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                source, evidence_path, _ = self.make_contract(Path(directory))
                self.rebind_aggregate_usage(evidence_path, updates)
                with self.assertRaisesRegex(
                    ValueError,
                    "aggregate L2 provider usage",
                ):
                    self.validate(source, evidence_path)
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            self.rebind_formal_budget(
                evidence_path,
                budget={
                    "scheduled_provider_calls": 296,
                    "grader_calibration_call_hard_cap": 0,
                    "reviewer_calibration_call_hard_cap": 0,
                    "provider_call_hard_cap": 296,
                },
                usage={
                    "grader_calibration_calls": 0,
                    "reviewer_calibration_calls": 0,
                    "apparatus_model_calls": 0,
                    "total_provider_calls": 296,
                },
            )
            with self.assertRaisesRegex(
                ValueError,
                "aggregate L2 provider usage",
            ):
                self.validate(source, evidence_path)

    def test_validation_mode_is_silent_read_only_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_root = root / "frontier-engineering-plugin"
            build_evidence = root / "plugin-build-evidence.json"
            self.builder.build(ROOT, plugin_root, None, build_evidence)
            before = {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            }
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch("sys.stdout", stdout),
                mock.patch("sys.stderr", stderr),
            ):
                return_code = self.builder.main([
                    "--source-root", str(ROOT),
                    "--validate-plugin-root", str(plugin_root),
                    "--build-evidence", str(build_evidence),
                ])
            self.assertEqual(0, return_code)
            self.assertEqual("", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())
            self.assertEqual(before, {
                path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob("*")
                if path.is_file()
            })

            skill = plugin_root / "skills" / "writing-plans" / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8") + "\nmutation\n",
                encoding="utf-8",
            )
            with (
                mock.patch("sys.stdout", io.StringIO()) as failed_stdout,
                mock.patch("sys.stderr", io.StringIO()) as failed_stderr,
            ):
                return_code = self.builder.main([
                    "--source-root", str(ROOT),
                    "--validate-plugin-root", str(plugin_root),
                    "--build-evidence", str(build_evidence),
                ])
            self.assertEqual(2, return_code)
            self.assertEqual("", failed_stdout.getvalue())
            self.assertEqual("", failed_stderr.getvalue())

    def test_release_build_emits_one_canonical_marketplace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marketplace_root = root / "marketplace"
            plugin_root = (
                marketplace_root / "plugins" / "frontier-engineering-plugin"
            )
            build_evidence_path = root / "plugin-build-evidence.json"
            release_evidence_path = root / "release-evidence.json"
            release_evidence_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(
                self.builder,
                "validate_release_evidence",
                return_value={},
            ):
                evidence = self.builder.build(
                    ROOT,
                    plugin_root,
                    release_evidence_path,
                    build_evidence_path,
                    marketplace_root,
                )
                validated = self.builder.validate_plugin_build(
                    plugin_root,
                    build_evidence_path,
                    source_root=ROOT,
                    release_evidence=release_evidence_path,
                )
            marketplace = json.loads((
                marketplace_root / ".agents" / "plugins" / "marketplace.json"
            ).read_text(encoding="utf-8"))
            self.assertEqual(self.builder.CANONICAL_MARKETPLACE, marketplace)
            self.assertEqual("release", evidence["output_class"])
            self.assertEqual(evidence, validated)
            self.assertFalse((root / "plugin-build-staging").exists())
            self.assertFalse((root / "marketplace-build-staging").exists())
            with self.assertRaisesRegex(
                ValueError,
                "release validation requires release evidence",
            ):
                self.builder.validate_plugin_build(
                    plugin_root,
                    build_evidence_path,
                    source_root=ROOT,
                    release_evidence=None,
                )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marketplace_root = root / "marketplace"
            plugin_root = (
                marketplace_root / "plugins" / "frontier-engineering-plugin"
            )
            build_evidence_path = root / "plugin-build-evidence.json"
            release_evidence_path = root / "release-evidence.json"
            release_evidence_path.write_text("{}\n", encoding="utf-8")
            rename_no_replace = self.builder._rename_no_replace
            destination_created = False

            def destination_appears(
                source: Path,
                destination: Path,
            ) -> None:
                nonlocal destination_created
                if destination == marketplace_root and not destination_created:
                    destination_created = True
                    destination.mkdir()
                    (destination / "foreign.txt").write_text(
                        "foreign\n",
                        encoding="utf-8",
                    )
                rename_no_replace(source, destination)

            with (
                mock.patch.object(
                    self.builder,
                    "validate_release_evidence",
                    return_value={},
                ),
                mock.patch.object(
                    self.builder,
                    "_rename_no_replace",
                    side_effect=destination_appears,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "no-overwrite destination appeared",
                ),
            ):
                self.builder.build(
                    ROOT,
                    plugin_root,
                    release_evidence_path,
                    build_evidence_path,
                    marketplace_root,
                )
            self.assertEqual(
                "foreign\n",
                (marketplace_root / "foreign.txt").read_text(
                    encoding="utf-8"
                ),
            )
            self.assertFalse(build_evidence_path.exists())
            self.assertFalse((root / "plugin-build-staging").exists())
            self.assertFalse((root / "marketplace-build-staging").exists())

        def release_paths(root: Path) -> tuple[Path, Path, Path]:
            marketplace = root / "marketplace"
            plugin = (
                marketplace / "plugins" / "frontier-engineering-plugin"
            )
            release = root / "release-evidence.json"
            release.write_text("{}\n", encoding="utf-8")
            return marketplace, plugin, release

        for mutation in ("manifest", "plugin"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marketplace_root, plugin_root, release_evidence_path = (
                    release_paths(root)
                )
                build_evidence_path = root / "plugin-build-evidence.json"
                real_match = self.builder._marketplace_publication_matches
                mutated = False

                def mutate_after_publish(*args, **kwargs) -> bool:
                    nonlocal mutated
                    if not mutated:
                        mutated = True
                        if mutation == "manifest":
                            (
                                marketplace_root
                                / ".agents/plugins/marketplace.json"
                            ).write_text("foreign\n", encoding="utf-8")
                        else:
                            self.builder.shutil.rmtree(plugin_root)
                            plugin_root.mkdir()
                            (plugin_root / "foreign.txt").write_text(
                                "foreign\n",
                                encoding="utf-8",
                            )
                    return real_match(*args, **kwargs)

                with (
                    mock.patch.object(
                        self.builder,
                        "validate_release_evidence",
                        return_value={},
                    ),
                    mock.patch.object(
                        self.builder,
                        "_marketplace_publication_matches",
                        side_effect=mutate_after_publish,
                    ),
                    self.assertRaisesRegex(
                        ValueError,
                        "changed during publication",
                    ),
                ):
                    self.builder.build(
                        ROOT,
                        plugin_root,
                        release_evidence_path,
                        build_evidence_path,
                        marketplace_root,
                    )
                self.assertFalse(build_evidence_path.exists())
                if mutation == "manifest":
                    self.assertEqual(
                        "foreign\n",
                        (
                            marketplace_root
                            / ".agents/plugins/marketplace.json"
                        ).read_text(encoding="utf-8"),
                    )
                else:
                    self.assertEqual(
                        "foreign\n",
                        (plugin_root / "foreign.txt").read_text(
                            encoding="utf-8"
                        ),
                    )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marketplace_root, plugin_root, release_evidence_path = (
                release_paths(root)
            )
            build_evidence_path = root / "plugin-build-evidence.json"
            real_link = self.builder.os.link

            def link_then_raise(*args, **kwargs) -> None:
                real_link(*args, **kwargs)
                raise RuntimeError("injected post-link failure")

            with (
                mock.patch.object(
                    self.builder,
                    "validate_release_evidence",
                    return_value={},
                ),
                mock.patch.object(
                    self.builder.os,
                    "link",
                    side_effect=link_then_raise,
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "post-link failure",
                ),
            ):
                self.builder.build(
                    ROOT,
                    plugin_root,
                    release_evidence_path,
                    build_evidence_path,
                    marketplace_root,
                )
            self.assertFalse(marketplace_root.exists())
            self.assertFalse(build_evidence_path.exists())
            self.assertFalse((root / "plugin-build-staging").exists())
            self.assertFalse((root / "marketplace-build-staging").exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marketplace_root, plugin_root, release_evidence_path = (
                release_paths(root)
            )
            build_evidence_path = root / "plugin-build-evidence.json"
            real_link = self.builder.os.link

            def link_then_mutate(*args, **kwargs) -> None:
                real_link(*args, **kwargs)
                (
                    marketplace_root
                    / ".agents/plugins/marketplace.json"
                ).write_text("foreign\n", encoding="utf-8")

            with (
                mock.patch.object(
                    self.builder,
                    "validate_release_evidence",
                    return_value={},
                ),
                mock.patch.object(
                    self.builder.os,
                    "link",
                    side_effect=link_then_mutate,
                ),
                self.assertRaisesRegex(
                    ValueError,
                    "changed after evidence publication",
                ),
            ):
                self.builder.build(
                    ROOT,
                    plugin_root,
                    release_evidence_path,
                    build_evidence_path,
                    marketplace_root,
                )
            self.assertEqual(
                "foreign\n",
                (
                    marketplace_root
                    / ".agents/plugins/marketplace.json"
                ).read_text(encoding="utf-8"),
            )
            self.assertFalse(build_evidence_path.exists())

    def test_static_report_rejects_bundle_version_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            static_path = source / "evaluation" / "static-contract-diagnostic.json"
            static = json.loads(static_path.read_text(encoding="utf-8"))
            static["bundle_version"] = static.pop("version")
            static["report_hash"] = self_hash(static)
            write_json(static_path, static)
            with self.assertRaisesRegex(ValueError, "static contract diagnostic"):
                self.validate(source, evidence_path)

    def test_tampered_arm_report_fails_even_with_a_recomputed_self_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            sqw_path = (
                evidence_path.parent / "l2"
                / "software-quality-workflows" / "report.json"
            )
            sqw = json.loads(sqw_path.read_text(encoding="utf-8"))
            sqw["new_unbound_claim"] = True
            sqw["report_hash"] = self_hash(sqw)
            write_json(sqw_path, sqw)
            with self.assertRaisesRegex(ValueError, "P3 arm report is invalid"):
                self.validate(source, evidence_path)

    def test_arm_v2_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            arm_path = (
                evidence_path.parent / "l2"
                / "software-quality-workflows" / "report.json"
            )
            arm = json.loads(arm_path.read_text(encoding="utf-8"))
            arm["schema_version"] = "p3-arm-report/2.0"
            arm["report_hash"] = self_hash(arm)
            write_json(arm_path, arm)
            with self.assertRaisesRegex(ValueError, "P3 arm report is invalid"):
                self.validate(source, evidence_path)

    def test_arm_semantics_tamper_is_rejected_after_hash_rebinding(self) -> None:
        for field in ("gate_projection", "usage_closure"):
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory() as directory,
            ):
                source, evidence_path, _ = self.make_contract(Path(directory))
                arm_path = (
                    evidence_path.parent / "l2"
                    / "software-quality-workflows" / "report.json"
                )
                arm = json.loads(arm_path.read_text(encoding="utf-8"))
                if field == "gate_projection":
                    arm["gate_results"][0]["metric_id"] = "unbound-metric"
                else:
                    arm["usage_closure"]["graded"] -= 1
                self.rebind_arm(
                    evidence_path,
                    "software-quality-workflows",
                    arm,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "P3 arm report is invalid or unbound",
                ):
                    self.validate(source, evidence_path)

    def test_prior_migration_claim_tamper_is_rejected_after_hash_rebinding(self) -> None:
        for field, value in (
            ("status", "not_supported"),
            ("observed_reduction", 0.49),
            ("minimum_reference_cases", None),
        ):
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory() as directory,
            ):
                source, evidence_path, _ = self.make_contract(Path(directory))
                arm = self.load_arm(evidence_path, "writing-plans")
                claim = arm["metrics"]["prior_reference_migration_claim"]
                if value is None:
                    claim.pop(field)
                else:
                    claim[field] = value
                self.rebind_arm(evidence_path, "writing-plans", arm)
                with self.assertRaisesRegex(ValueError, "prior migration claim"):
                    self.validate(source, evidence_path)

    def test_truthful_non_supported_claim_states_do_not_block_release(self) -> None:
        for status, cases, mixed, reduction in (
            ("unavailable", 0, 0, None),
            ("unavailable", 4, 1, None),
            ("not_supported", 4, 0, 0.49),
        ):
            with (
                self.subTest(status=status, cases=cases, mixed=mixed),
                tempfile.TemporaryDirectory() as directory,
            ):
                source, evidence_path, _ = self.make_contract(Path(directory))
                arm = self.load_arm(evidence_path, "writing-plans")
                claim = arm["metrics"]["prior_reference_migration_claim"]
                claim.update({
                    "status": status,
                    "observed_reference_cases": cases,
                    "mixed_prior_cases": mixed,
                    "observed_reduction": reduction,
                })
                self.rebind_arm(evidence_path, "writing-plans", arm)
                self.validate(source, evidence_path)

    def test_missing_arm_candidate_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            arm_path = (
                evidence_path.parent / "l2"
                / "software-quality-workflows" / "report.json"
            )
            arm = json.loads(arm_path.read_text(encoding="utf-8"))
            arm.pop("candidate_revision")
            arm["report_hash"] = self_hash(arm)
            write_json(arm_path, arm)
            with self.assertRaisesRegex(ValueError, "P3 arm report is invalid"):
                self.validate(source, evidence_path)

    def test_decision_contract_raw_bytes_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            contract = evidence_path.parent / "l2" / "p3-decision-contract.json"
            contract.write_bytes(contract.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "arm report is invalid or unbound"):
                self.validate(source, evidence_path)

    def test_arm_keys_equal_frozen_evaluated_skill_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, evidence = self.make_contract(Path(directory))
            evidence["arm_report_content_hashes"].pop("writing-plans")
            write_json(evidence_path, evidence)
            with self.assertRaisesRegex(ValueError, "release evidence is invalid"):
                self.validate(source, evidence_path)

    def test_wrong_activation_map_and_symlinked_input_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, evidence = self.make_contract(Path(directory))
            evidence["approved_skill_activation"]["writing-plans"] = "implicit"
            write_json(evidence_path, evidence)
            with self.assertRaisesRegex(ValueError, "release evidence is invalid"):
                self.validate(source, evidence_path)

        for relative in (
            "unexpected.json",
            "l2/software-quality-workflows/unexpected.json",
            "longitudinal/unexpected.json",
        ):
            with (
                self.subTest(extra=relative),
                tempfile.TemporaryDirectory() as directory,
            ):
                source, evidence_path, _ = self.make_contract(Path(directory))
                extra = evidence_path.parent / relative
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_text("{}\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "inventory"):
                    self.validate(source, evidence_path)

        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            arm_root = (
                evidence_path.parent / "l2" / "software-quality-workflows"
            )
            backup = arm_root.with_name("software-quality-workflows-real")
            arm_root.rename(backup)
            arm_root.symlink_to(backup, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.validate(source, evidence_path)

    def test_missing_or_malformed_bound_inputs_fail_closed(self) -> None:
        missing = (
            "source/evaluation/static-contract-diagnostic.json",
            "run/l2/aggregate-report.json",
            "run/longitudinal/report.json",
            "run/activation-decision.json",
        )
        for relative in missing:
            with self.subTest(missing=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, evidence_path, _ = self.make_contract(root)
                (root / relative).unlink()
                with self.assertRaises((OSError, ValueError)):
                    self.validate(source, evidence_path)

        malformed = (
            "source/evaluation/static-contract-diagnostic.json",
            "run/l2/software-quality-workflows/report.json",
            "run/longitudinal/report.json",
            "run/activation-decision.json",
        )
        for relative in malformed:
            with self.subTest(malformed=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, evidence_path, _ = self.make_contract(root)
                (root / relative).write_text("{", encoding="utf-8")
                with self.assertRaises(json.JSONDecodeError):
                    self.validate(source, evidence_path)

    def test_static_l2_longitudinal_and_decision_hashes_are_recomputed(self) -> None:
        fields = (
            "deterministic_report_hash", "l2_scored_report_hash",
            "longitudinal_report_hash", "activation_decision_hash",
        )
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                source, evidence_path, evidence = self.make_contract(Path(directory))
                evidence[field] = "sha256:" + "f" * 64
                write_json(evidence_path, evidence)
                with self.assertRaisesRegex(ValueError, "static contract|external content hash"):
                    self.validate(source, evidence_path)

    def test_unsigned_dirty_or_unverifiable_source_is_rejected(self) -> None:
        for field in ("source_revision_signed", "source_clean"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                source, evidence_path, evidence = self.make_contract(Path(directory))
                evidence[field] = False
                write_json(evidence_path, evidence)
                with self.assertRaisesRegex(ValueError, "release evidence is invalid"):
                    self.validate(source, evidence_path)

        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            with self.assertRaisesRegex(ValueError, "clean signed source revision"):
                self.validate(source, evidence_path, git_ok=False)


if __name__ == "__main__":
    unittest.main()
