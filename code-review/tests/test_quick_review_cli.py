"""Short CLI tests: arguments, artifacts, exit codes, and input preservation."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _review_fixtures as fixtures  # noqa: E402
import _review_record as review_record  # noqa: E402
import review_support  # noqa: E402


class QuickReviewCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = fixtures.init_repo(self.root)
        self.fixtures_commit = fixtures.commit_files(self.repo, {"src/module.py": "value = 1\n"})

    def scope(self, *args: str):
        output = self.root / f"packet-{len(list(self.root.glob('packet-*')))}"
        code, payload = fixtures.run_cli(
            ["scope", "--repo", str(self.repo), *args, "--output", str(output)]
        )
        return code, payload, output

    def test_help_and_argument_errors_use_argparse_exit_codes(self) -> None:
        with self.assertRaises(SystemExit) as top:
            review_support.main(["--help"])
        self.assertEqual(0, top.exception.code)
        with self.assertRaises(SystemExit) as sub:
            review_support.main(["scope", "--help"])
        self.assertEqual(0, sub.exception.code)
        with self.assertRaises(SystemExit) as missing:
            review_support.main(["scope", "--repo", str(self.repo)])
        self.assertEqual(2, missing.exception.code)
        with self.assertRaises(SystemExit) as unknown:
            review_support.main(["review", "--repo", str(self.repo)])
        self.assertEqual(2, unknown.exception.code)

    def test_scope_requires_the_fixed_mode_matrix(self) -> None:
        cases = {
            "commit without commit": ("--mode", "commit", "--path", "."),
            "commit with base": ("--mode", "commit", "--commit", "HEAD", "--base", "HEAD", "--path", "."),
            "range without head": ("--mode", "range", "--base", "HEAD", "--path", "."),
            "workspace with revision": ("--mode", "workspace", "--revision", "HEAD", "--path", "."),
            "snapshot without revision": ("--mode", "snapshot", "--path", "."),
            "snapshot with commit": ("--mode", "snapshot", "--revision", "HEAD", "--commit", "HEAD", "--path", "."),
        }
        for label, args in cases.items():
            with self.subTest(label):
                code, payload, output = self.scope(*args)
                self.assertEqual(2, code)
                self.assertEqual("E_ARGS", payload["code"])
                self.assertIsNone(payload["artifact"])
                self.assertFalse(output.exists())

    def test_scope_rejects_literal_path_violations(self) -> None:
        cases = {
            "absolute": ("/etc/passwd", "E_PATH_INVALID"),
            "parent": ("src/../etc", "E_PATH_INVALID"),
            "metadata": (".git/config", "E_PATH_INVALID"),
            "glob": ("src/*.py", "E_PATH_INVALID"),
            "empty": ("", "E_PATH_INVALID"),
            "surrogate": ("src/\udcff.py", "E_PATH_ENCODING"),
        }
        for label, (path, code) in cases.items():
            with self.subTest(label):
                code_seen, payload, output = self.scope("--mode", "workspace", "--path", path)
                self.assertEqual(2, code_seen)
                self.assertEqual(code, payload["code"])
                self.assertFalse(output.exists())

    def test_scope_success_writes_a_private_packet_and_json_summary(self) -> None:
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, output = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        self.assertEqual("ok", payload["result"])
        self.assertEqual(0, payload["exit_code"])
        self.assertEqual("scope", payload["command"])
        self.assertEqual("workspace", payload["mode"])
        self.assertEqual(1, payload["items"])
        self.assertEqual(2, payload["sources"])
        self.assertEqual(str(output), payload["artifact"])
        scope_bytes = (output / "scope.json").read_bytes()
        self.assertEqual(
            review_record.sha256_digest(scope_bytes), payload["scope_sha256"]
        )
        scope = json.loads(scope_bytes)
        self.assertEqual("fas-review-scope/1", scope["schema_version"])
        self.assertEqual(["src"], scope["request"]["paths"])
        self.assertEqual(0o700, stat.S_IMODE(output.stat().st_mode))
        self.assertTrue((output / "objects").is_dir())
        self.assertNotIn(str(self.root), scope_bytes.decode("utf-8"))
        self.assertNotIn(str(self.repo), scope_bytes.decode("utf-8"))

    def test_scope_never_overwrites_an_existing_output(self) -> None:
        existing = self.root / "packet-existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep\n", encoding="utf-8")
        code, payload = fixtures.run_cli(
            [
                "scope",
                "--repo",
                str(self.repo),
                "--mode",
                "workspace",
                "--path",
                ".",
                "--output",
                str(existing),
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertIsNone(payload["artifact"])
        self.assertEqual("keep\n", marker.read_text(encoding="utf-8"))
        self.assertEqual(["keep.txt"], sorted(path.name for path in existing.iterdir()))

    def test_scope_refuses_output_inside_the_repository(self) -> None:
        inside = self.repo / "packet"
        code, payload = fixtures.run_cli(
            [
                "scope",
                "--repo",
                str(self.repo),
                "--mode",
                "workspace",
                "--path",
                ".",
                "--output",
                str(inside),
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertFalse(inside.exists())

    def test_scope_reports_a_missing_context_path(self) -> None:
        code, payload, output = self.scope(
            "--mode", "workspace", "--path", ".", "--context-path", "config/missing.json"
        )
        self.assertEqual(2, code)
        self.assertEqual("E_CONTEXT_MISSING", payload["code"])
        # A failed capture may leave the partial directory for diagnosis, but never scope.json.
        self.assertFalse((output / "scope.json").exists())

    def test_scope_rejects_a_directory_context_path(self) -> None:
        code, payload, output = self.scope(
            "--mode", "workspace", "--path", ".", "--context-path", "src"
        )
        self.assertEqual(2, code)
        self.assertEqual("E_CONTEXT_MISSING", payload["code"])

    def test_check_round_trip_on_a_real_packet(self) -> None:
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        fixtures.write_file(self.repo, "src/owned.py", "def read(record):\n    return record['payload']\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        scope = json.loads((packet / "scope.json").read_text(encoding="utf-8"))
        sources = {source["path"]: source for source in scope["sources"]}
        owned_item = next(item for item in scope["items"] if item["path"] == "src/owned.py")
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": payload["scope_sha256"],
            "coverage": [
                {"item_id": item["id"], "status": "reviewed", "reason": None}
                for item in scope["items"]
            ],
            "findings": [
                {
                    "id": "F-1",
                    "severity": "high",
                    "summary": "The ownership check is gone.",
                    "relation": "introduced",
                    "trigger": "A caller reads another account's record.",
                    "impact": "Private payloads are returned.",
                    "item_ids": [owned_item["id"]],
                    "evidence": [
                        {
                            "source_id": sources["src/owned.py"]["id"],
                            "start_line": 2,
                            "end_line": 2,
                            "snippet": "    return record['payload']",
                        }
                    ],
                    "fix": "Restore the ownership check.",
                }
            ],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }
        record_path = fixtures.write_json(self.root / "record.json", record)
        report_path = self.root / "report.json"
        code, payload = fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(report_path),
            ]
        )
        self.assertEqual(0, code, payload)
        self.assertEqual("valid", payload["result"])
        self.assertEqual("all_declared_reviewed", payload["coverage_status"])
        self.assertEqual("captured_inputs_match", payload["freshness"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        review_record.validate_document(report, "check_report")
        self.assertEqual(0, report["exit_code"])
        self.assertEqual(1, report["finding_count"])
        self.assertEqual("resolved", report["anchors"][0]["status"])
        self.assertEqual(
            {"total": 2, "reviewed": 2, "partial": 0, "not_reviewed": 0},
            report["item_counts"],
        )

    def test_check_exit_four_for_partial_coverage(self) -> None:
        fixtures.write_file(self.repo, "src/module.py", "value = 3\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        scope = json.loads((packet / "scope.json").read_text(encoding="utf-8"))
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": payload["scope_sha256"],
            "coverage": [
                {
                    "item_id": scope["items"][0]["id"],
                    "status": "not_reviewed",
                    "reason": "Only the entry point was inspected.",
                }
            ],
            "findings": [],
            "concerns": [],
            "verification": [
                {
                    "id": "V-1",
                    "label": "Runtime reproduction",
                    "status": "not_run",
                    "observation": "No runtime was started for this record.",
                }
            ],
            "limitations": [],
        }
        record_path = fixtures.write_json(self.root / "partial-record.json", record)
        report_path = self.root / "partial-report.json"
        code, payload = fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(report_path),
            ]
        )
        self.assertEqual(4, code)
        self.assertEqual("valid", payload["result"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual("partial", report["coverage_status"])
        self.assertEqual(0, report["finding_count"])

    def test_check_reports_a_packet_without_scope_json(self) -> None:
        empty_packet = self.root / "empty-packet"
        empty_packet.mkdir()
        record_path = fixtures.write_json(
            self.root / "empty-record.json",
            {
                "schema_version": "fas-review-record/1",
                "scope_ref": "scope.json",
                "scope_sha256": "sha256:" + "0" * 64,
                "coverage": [],
                "findings": [],
                "concerns": [],
                "verification": [],
                "limitations": [],
            },
        )
        report_path = self.root / "empty-report.json"
        code, payload = fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(empty_packet),
                "--record",
                str(record_path),
                "--output",
                str(report_path),
            ]
        )
        self.assertEqual(2, code)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        review_record.validate_document(report, "check_report")
        self.assertEqual("invalid", report["validation"])
        self.assertEqual("E_SCOPE_MISSING", report["problems"][0]["code"])

    def test_check_leaves_packet_and_record_untouched(self) -> None:
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        scope = json.loads((packet / "scope.json").read_text(encoding="utf-8"))
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": payload["scope_sha256"],
            "coverage": [
                {"item_id": item["id"], "status": "reviewed", "reason": None}
                for item in scope["items"]
            ],
            "findings": [],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }
        record_path = fixtures.write_json(self.root / "untouched-record.json", record)
        before = {
            path.name: review_record.sha256_digest(path.read_bytes())
            for path in [packet / "scope.json", record_path, *sorted((packet / "objects").iterdir())]
        }
        report_path = self.root / "untouched-report.json"
        code, payload = fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(report_path),
            ]
        )
        self.assertEqual(0, code, payload)
        after = {
            path.name: review_record.sha256_digest(path.read_bytes())
            for path in [packet / "scope.json", record_path, *sorted((packet / "objects").iterdir())]
        }
        self.assertEqual(before, after)

    def test_check_refuses_an_existing_report_and_repo_internal_output(self) -> None:
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        scope = json.loads((packet / "scope.json").read_text(encoding="utf-8"))
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": payload["scope_sha256"],
            "coverage": [
                {"item_id": item["id"], "status": "reviewed", "reason": None}
                for item in scope["items"]
            ],
            "findings": [],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }
        record_path = fixtures.write_json(self.root / "existing-report-record.json", record)
        existing = self.root / "existing-report.json"
        existing.write_bytes(b"previous\n")
        code, payload = fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(existing),
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertEqual(b"previous\n", existing.read_bytes())
        inside = self.repo / "report.json"
        code, payload = fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record_path),
                "--output",
                str(inside),
            ]
        )
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertFalse(inside.exists())


if __name__ == "__main__":
    unittest.main()
