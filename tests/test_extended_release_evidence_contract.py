from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_codex_plugin.py"
SOURCE_HASH = "sha256:" + "1" * 64
PLUGIN_HASH = "sha256:" + "2" * 64
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


class ExtendedReleaseEvidenceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = load_builder()

    def make_contract(self, root: Path) -> tuple[Path, Path, dict]:
        source = root / "source"
        run = root / "run"
        (source / "packaging" / "schemas").mkdir(parents=True)
        (source / "evaluation").mkdir()
        (source / "packaging" / "schemas" / "release-evidence.schema.json").write_bytes(
            (ROOT / "packaging" / "schemas" / "release-evidence.schema.json").read_bytes()
        )
        write_json(source / "frontier-engineering.bundle.json", {
            "bundle_id": "frontier-engineering/6.0.0",
        })
        static = {
            "bundle_id": "frontier-engineering/6.0.0",
            "bundle_version": "6.0.0",
            "skill_activation": ACTIVATION_BOOL,
        }
        static["report_hash"] = self_hash(static)
        write_json(source / "evaluation" / "static-contract-diagnostic.json", static)

        identity = {
            "candidate_revision": REVISION,
            "candidate_source_tree_hash": SOURCE_HASH,
            "candidate_plugin_tree_hash": PLUGIN_HASH,
        }
        evaluated_skill_ids = [
            "software-quality-workflows",
            "writing-plans",
        ]
        decision_contract = {
            **identity,
            "evaluated_skill_ids": evaluated_skill_ids,
        }
        decision_contract["decision_contract_hash"] = self_hash(decision_contract)
        decision_bytes = write_json(
            run / "l2" / "p3-decision-contract.json",
            decision_contract,
        )
        decision_hash = digest(decision_bytes)

        def arm(study: str, analysis_keys: tuple[str, ...]) -> dict:
            report = {
                "schema_version": "p3-arm-report/2.0",
                "study": study,
                **identity,
                "decision_contract_content_hash": decision_hash,
                "spec_content_hash": "sha256:" + "3" * 64,
                "cases_content_hash": "sha256:" + "4" * 64,
                "case_contracts_content_hash": "sha256:" + "5" * 64,
                "fixture_manifest_set_hash": "sha256:" + "6" * 64,
                "grader_set_hash": "sha256:" + "7" * 64,
                "grader_batch_schedule_hash": "sha256:" + "8" * 64,
                "treatment_contract_hash": "sha256:" + "9" * 64,
                "environment_hash": "sha256:" + "a" * 64,
                "receipt_index_content_hash": "sha256:" + "b" * 64,
                "receipt_treatment_index_content_hash": "sha256:" + "c" * 64,
                "analysis_input_content_hashes": {
                    key: "sha256:" + "d" * 64 for key in analysis_keys
                },
                "evidence_status": "complete",
                "usefulness_status": "supported",
                "metrics": {},
                "gates": [],
            }
            report["report_hash"] = self_hash(report)
            return report

        sqw = arm("software-quality-workflows", ("task_analysis",))
        wp = arm(
            "writing-plans",
            ("planner_analysis", "transfer_analysis"),
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
            **identity,
            "decision_contract_content_hash": decision_hash,
            "evaluated_skill_ids": evaluated_skill_ids,
            "arm_report_content_hashes": arm_hashes,
            "aggregate_status": "passed",
            "scored_model_calls": 206,
            "apparatus_model_calls": 4,
            "total_provider_calls": 210,
            "retries": 0,
            "gates": [],
        }
        aggregate["report_hash"] = self_hash(aggregate)
        aggregate_bytes = write_json(run / "l2" / "aggregate-report.json", aggregate)
        longitudinal = {**identity, "longitudinal_status": "passed"}
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

    def test_valid_contract_binds_all_reports_and_candidate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, evidence = self.make_contract(Path(directory))
            self.assertEqual(evidence, self.validate(source, evidence_path))

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
            with self.assertRaisesRegex(ValueError, "P3 arm report is invalid or unbound"):
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
            with self.assertRaisesRegex(ValueError, "schema is invalid"):
                self.validate(source, evidence_path)

    def test_wrong_activation_map_and_symlinked_input_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, evidence = self.make_contract(Path(directory))
            evidence["approved_skill_activation"]["writing-plans"] = "implicit"
            write_json(evidence_path, evidence)
            with self.assertRaisesRegex(ValueError, "schema is invalid"):
                self.validate(source, evidence_path)

        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            report = evidence_path.parent / "longitudinal" / "report.json"
            backup = report.with_name("report-real.json")
            report.rename(backup)
            report.symlink_to(backup)
            with self.assertRaises(OSError):
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
                with self.assertRaises(OSError):
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
                with self.assertRaisesRegex(ValueError, "schema is invalid"):
                    self.validate(source, evidence_path)

        with tempfile.TemporaryDirectory() as directory:
            source, evidence_path, _ = self.make_contract(Path(directory))
            with self.assertRaisesRegex(ValueError, "clean signed source revision"):
                self.validate(source, evidence_path, git_ok=False)


if __name__ == "__main__":
    unittest.main()
