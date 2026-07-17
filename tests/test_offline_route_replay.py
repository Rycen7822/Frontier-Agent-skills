from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from unittest import mock

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_offline_route_replay.py"
SPEC = importlib.util.spec_from_file_location("evaluate_offline_route_replay", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


class OfflineRouteReplayTests(unittest.TestCase):
    """C1/C5 regressions for a content-bound, HEAD-invariant sequence report."""

    @staticmethod
    def _rendered(report: dict[str, object]) -> bytes:
        return (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

    def test_checked_report_is_reproducible_strict_and_deterministic_only(self) -> None:
        generated = replay.build_report()
        checked = json.loads((ROOT / "evaluation" / "offline-route-replay.json").read_text(encoding="utf-8"))
        self.assertEqual(generated, checked)
        schema = json.loads(
            (ROOT / "evaluation" / "schemas" / "offline-route-replay.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(checked)))
        self.assertEqual("offline-route-replay/2.0", checked["schema_version"])
        self.assertEqual("deterministic_diagnostic", checked["diagnostic_classification"])
        self.assertEqual("deterministic_sequence_ready", checked["decision"])
        self.assertTrue(all(checked["gates"].values()))
        self.assertEqual((62, 62), (
            checked["metrics"]["active_card_coverage_count"], checked["metrics"]["active_card_count"],
        ))
        self.assertIn("natural model routing and outcome quality require real Sol max runs", checked["limitations"])
        self.assertIn(
            "sequence total active bytes are a diagnostic distribution, not an external context budget",
            checked["limitations"],
        )

    def test_git_head_is_not_part_of_tracked_payload(self) -> None:
        original_run = subprocess.run

        def build_with_head(revision: str) -> bytes:
            def controlled_run(args: object, *positional: object, **keywords: object) -> subprocess.CompletedProcess[str]:
                if isinstance(args, list) and args[-2:] == ["rev-parse", "HEAD"]:
                    return subprocess.CompletedProcess(args, 0, stdout=revision + "\n", stderr="")
                return original_run(args, *positional, **keywords)

            with mock.patch.object(replay.subprocess, "run", side_effect=controlled_run):
                return self._rendered(replay.build_report())

        self.assertEqual(build_with_head("1" * 40), build_with_head("2" * 40))

    def test_report_binds_content_identities_and_self_excluding_hash(self) -> None:
        report = replay.build_report()
        bundle_path = ROOT / "frontier-engineering.bundle.json"
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

        self.assertEqual(
            {"identity", "source_archive_hash", "skill_versions"},
            set(report["baseline"]),
        )
        self.assertEqual(
            {"identity", "bundle_build_id", "bundle_manifest_hash", "skill_versions"},
            set(report["vnext"]),
        )
        self.assertEqual({"writing-plans", "software-quality-workflows"}, set(report["input_bindings"]))
        self.assertEqual(
            {
                "skill_version", "router_hash", "decision_map_hash", "card_manifest_hash",
                "decision_case_fixture_hash", "sequence_fixture_hash",
            },
            set(report["input_bindings"]["writing-plans"]),
        )
        self.assertEqual(
            "sha256:09d1ac63e98b2849c648c608baf9d0a4b4e332683d47b263543991be1f2b0166",
            report["baseline"]["source_archive_hash"],
        )
        self.assertEqual(bundle["release_build_id"], report["vnext"]["bundle_build_id"])
        self.assertEqual("sha256:" + sha256(bundle_path.read_bytes()).hexdigest(), report["vnext"]["bundle_manifest_hash"])

        payload = copy.deepcopy(report)
        observed_hash = payload.pop("report_hash")
        self.assertEqual(replay._canonical_hash(payload), observed_hash)

        schema = json.loads(
            (ROOT / "evaluation" / "schemas" / "offline-route-replay.schema.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("revision", json.dumps(schema, sort_keys=True))

    def test_decision_map_and_card_identity_changes_invalidate_checked_replay(self) -> None:
        original = replay.build_report()
        original_hash = replay._content_hash
        targets = (
            ROOT / "writing-plans" / "registries" / "decision-card-map.json",
            ROOT / "software-quality-workflows" / "registries" / "reference-cards.manifest.json",
        )
        for target in targets:
            with self.subTest(target=target.relative_to(ROOT)):
                def changed_hash(path: Path) -> str:
                    return "sha256:" + "0" * 64 if path == target else original_hash(path)

                with tempfile.TemporaryDirectory() as directory_name:
                    checked_report = Path(directory_name) / "offline-route-replay.json"
                    checked_report.write_bytes(self._rendered(original))
                    with mock.patch.object(replay, "_content_hash", side_effect=changed_hash):
                        changed = replay.build_report()
                        self.assertNotEqual(original["report_hash"], changed["report_hash"])
                        output = io.StringIO()
                        with redirect_stdout(output):
                            self.assertEqual(2, replay.main(["--check", "--output", str(checked_report)]))
                        self.assertIn("missing or stale", output.getvalue())

    def test_bound_source_and_manifest_change_report_and_fail_check(self) -> None:
        original = replay.build_report()
        bundle = json.loads((ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8"))
        changed_bundle = copy.deepcopy(bundle)
        changed_bundle["skills"]["writing-plans"]["root_hash"] = "sha256:" + "0" * 64
        changed_bundle["release_build_id"] = "build-" + "0" * 24
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            changed_bundle_path = directory / "frontier-engineering.bundle.json"
            changed_bundle_path.write_text(json.dumps(changed_bundle, sort_keys=True) + "\n", encoding="utf-8")
            checked_report = directory / "offline-route-replay.json"
            checked_report.write_bytes(self._rendered(original))

            with (
                mock.patch.object(replay, "BUNDLE_PATH", changed_bundle_path),
                mock.patch.object(replay, "_build_current_bundle", return_value=changed_bundle),
            ):
                changed_report = replay.build_report()
                self.assertNotEqual(original["report_hash"], changed_report["report_hash"])
                self.assertNotEqual(original["vnext"]["bundle_build_id"], changed_report["vnext"]["bundle_build_id"])
                self.assertNotEqual(
                    original["vnext"]["bundle_manifest_hash"],
                    changed_report["vnext"]["bundle_manifest_hash"],
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(2, replay.main(["--check", "--output", str(checked_report)]))
                self.assertIn("missing or stale", output.getvalue())

    def test_stale_bundle_is_rejected_when_bound_source_identity_changes(self) -> None:
        checked_bundle = json.loads((ROOT / "frontier-engineering.bundle.json").read_text(encoding="utf-8"))
        changed = copy.deepcopy(checked_bundle)
        changed["skills"]["writing-plans"]["root_hash"] = "sha256:" + "0" * 64
        with mock.patch.object(replay, "_build_current_bundle", return_value=changed):
            with self.assertRaisesRegex(ValueError, "missing or stale"):
                replay.build_report()

    def test_replay_binds_the_exact_atomic_version_pair(self) -> None:
        report = json.loads((ROOT / "evaluation" / "offline-route-replay.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"software-quality-workflows": "4.0.0", "writing-plans": "3.0.0"},
            report["baseline"]["skill_versions"],
        )
        self.assertEqual(
            {"software-quality-workflows": "6.0.0", "writing-plans": "5.0.0"},
            report["vnext"]["skill_versions"],
        )
        self.assertEqual(62, len(report["selection_rows"]))
        self.assertEqual(62, len({row["case_id"] for row in report["selection_rows"]}))
        self.assertTrue(all(row["active_card_count"] <= 1 for row in report["selection_rows"]))
        self.assertEqual(report["case_count"], sum(len(report[key]) for key in (
            "selection_rows", "protected_rows", "entry_rows", "sequence_rows",
        )))


if __name__ == "__main__":
    unittest.main()
