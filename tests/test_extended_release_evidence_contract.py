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
    "software-quality-workflows": "implicit",
    "writing-plans": "explicit_only",
}
ACTIVATION_BOOL = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": True,
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
            "bundle_id": "frontier-engineering/5.0.0",
        })
        static = {
            "bundle_id": "frontier-engineering/5.0.0",
            "bundle_version": "5.0.0",
            "skill_activation": ACTIVATION_BOOL,
        }
        static["report_hash"] = self_hash(static)
        write_json(source / "evaluation" / "static-contract-diagnostic.json", static)

        identity = {
            "candidate_revision": REVISION,
            "candidate_source_tree_hash": SOURCE_HASH,
            "candidate_plugin_tree_hash": PLUGIN_HASH,
        }
        sqw = {**identity, "evidence_status": "complete", "usefulness_status": "supported"}
        sqw["report_hash"] = self_hash(sqw)
        wp = {**identity, "evidence_status": "complete", "usefulness_status": "supported"}
        wp["report_hash"] = self_hash(wp)
        sqw_bytes = write_json(run / "l2" / "sqw" / "report.json", sqw)
        wp_bytes = write_json(run / "l2" / "writing-plans" / "report.json", wp)
        aggregate = {
            **identity,
            "aggregate_status": "passed",
            "sqw_report_content_hash": digest(sqw_bytes),
            "writing_plans_report_content_hash": digest(wp_bytes),
        }
        aggregate_bytes = write_json(run / "l2" / "aggregate-report.json", aggregate)
        longitudinal = {**identity, "longitudinal_status": "passed"}
        longitudinal_bytes = write_json(run / "longitudinal" / "report.json", longitudinal)
        activation = {
            "schema_version": "activation-decision/1.0",
            "bundle_id": "frontier-engineering/5.0.0",
            "candidate_revision": REVISION,
            "source_tree_hash": SOURCE_HASH,
            "candidate_plugin_tree_hash": PLUGIN_HASH,
            "sqw_l2_report_hash": digest(sqw_bytes),
            "writing_plans_l2_report_hash": digest(wp_bytes),
            "aggregate_l2_report_hash": digest(aggregate_bytes),
            "longitudinal_report_hash": digest(longitudinal_bytes),
            "approved_skill_activation": dict(ACTIVATION),
            "remote_writes": False,
            "decision": "approve",
            "blocking_observations": [],
        }
        activation_bytes = write_json(run / "activation-decision.json", activation)
        evidence = {
            "schema_version": "release-evidence/3.0",
            "bundle_id": "frontier-engineering/5.0.0",
            "bundle_version": "5.0.0",
            "source_tree_hash": SOURCE_HASH,
            "plugin_tree_hash": PLUGIN_HASH,
            "source_revision": REVISION,
            "source_revision_signed": True,
            "source_clean": True,
            "deterministic_report_hash": static["report_hash"],
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

    def validate(self, source: Path, evidence_path: Path) -> dict:
        with mock.patch.object(self.builder, "_git_release_source_ok", return_value=True):
            return self.builder.validate_release_evidence(
                evidence_path,
                source_root=source,
                manifest={"bundle_version": "5.0.0"},
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
            sqw_path = evidence_path.parent / "l2" / "sqw" / "report.json"
            sqw = json.loads(sqw_path.read_text(encoding="utf-8"))
            sqw["new_unbound_claim"] = True
            sqw["report_hash"] = self_hash(sqw)
            write_json(sqw_path, sqw)
            with self.assertRaisesRegex(ValueError, "aggregate L2 status or arm content hash"):
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


if __name__ == "__main__":
    unittest.main()
