"""C1-C2: the CLI turns bad input into bounded results and never overwrites output."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
for path in (str(TESTS_DIR), str(TESTS_DIR.parent / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

import _review_fixtures as fixtures  # noqa: E402
import _review_record as review_record  # noqa: E402
from _review_fixtures import digest, hand_record, packet_view  # noqa: E402


class QuickReviewCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = fixtures.init_repo(self.root)
        fixtures.commit(self.repo, {"src/module.py": "value = 1\n"})
        fixtures.write(self.repo, "src/module.py", "value = 2\n")

    def output(self, name: str) -> Path:
        return self.root / name

    def assert_invalid_report(self, report: Path) -> dict:
        written = json.loads(report.read_text(encoding="utf-8"))
        review_record.validate_document(written, "check_report")
        self.assertEqual(("invalid", "unavailable", "not_checked", 2, []),
                         (written["validation"], written["coverage_status"],
                          written["freshness"]["status"], written["exit_code"], written["anchors"]))
        self.assertEqual((None, None, None),
                         (written["finding_count"],
                          written["concern_count"],
                          written["item_counts"]))
        self.assertTrue(written["problems"])
        return written

    def test_c1_invalid_input_reaches_the_consumer(self) -> None:
        packet = self.output("c1-packet")
        code, payload, _ = fixtures.scope_cli(
            self.repo, packet, "--mode", "workspace", "--path", "src/module.py")
        self.assertEqual(0, code, payload)
        view = packet_view(packet)

        def broken_check(name: str, *, raw: bytes | None = None, record: dict | None = None):
            path = self.output(f"c1-{name}-record.json")
            path.write_bytes(raw) if raw is not None else fixtures.write_json(path, record)
            report = self.output(f"c1-{name}-report.json")
            return fixtures.check_cli(self.repo, packet, path, report)

        with self.subTest("missing required argument"):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    fixtures.run_cli(["scope", "--repo", str(self.repo)])
            self.assertEqual(2, caught.exception.code)
        cases = {"duplicate JSON key": (
                b'{"schema_version": "a", "schema_version": "fas-review-record/1"}',
                "E_JSON_DUPLICATE_KEY"),
            "invalid text encoding": (b'{"schema_version": "\xff\xfe"}', "E_JSON_ENCODING"),
            "lone surrogate escape": (b'{"schema_version": "\\ud800"}', "E_JSON_ENCODING")}
        for label, (raw, expected) in cases.items():
            with self.subTest(label):
                code, payload, report = broken_check(label.replace(" ", "-"), raw=raw)
                self.assertEqual(2, code, payload)
                self.assertEqual("invalid", payload["validation"])
                written = self.assert_invalid_report(report)
                self.assertEqual(expected, written["problems"][0]["code"])
                self.assertNotIn("Traceback", report.read_text(encoding="utf-8"))
        with self.subTest("one oversized field"):
            sentinel = "S" * 9000
            record = {**hand_record(view), "limitations": [sentinel]}
            code, payload, report = broken_check("oversized", record=record)
            self.assertEqual(2, code, payload)
            text = report.read_text(encoding="utf-8")
            self.assertNotIn(sentinel, text)
            written = json.loads(text)
            self.assertEqual("E_SCHEMA", written["problems"][0]["code"])
            self.assertLessEqual(
                len(written["problems"][0]["message"]), review_record.PROBLEM_MESSAGE_LIMIT)
            self.assertEqual(written, self.assert_invalid_report(report))

    def test_c2_output_and_path_boundaries(self) -> None:
        packet = self.output("c2-packet")
        code, payload, _ = fixtures.scope_cli(
            self.repo, packet, "--mode", "workspace", "--path", "src/module.py")
        self.assertEqual(0, code, payload)
        # The summary must describe the bytes that were actually written.
        self.assertEqual(payload["scope_sha256"], digest((packet / "scope.json").read_bytes()))
        with self.subTest("an existing packet is not overwritten"):
            before = (packet / "scope.json").read_bytes()
            code, payload, _ = fixtures.scope_cli(
                self.repo, packet, "--mode", "workspace", "--path", "src/module.py")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertEqual(before, (packet / "scope.json").read_bytes())
        record = fixtures.write_json(self.output("c2-record.json"), hand_record(packet_view(packet))
        )
        report = self.output("c2-report.json")
        code, payload, _ = fixtures.check_cli(self.repo, packet, record, report)
        self.assertEqual(0, code, payload)
        with self.subTest("an existing report is not overwritten"):
            before = report.read_bytes()
            code, payload, _ = fixtures.check_cli(self.repo, packet, record, report)
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertEqual(before, report.read_bytes())
        with self.subTest("a nested repository argument still refuses an internal output"):
            inside = self.repo / "src" / "report.json"
            code, payload, _ = fixtures.check_cli(self.repo / "src", packet, record, inside)
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertFalse(inside.exists())
            outside = self.output("c2-nested-report.json")
            code, payload, _ = fixtures.check_cli(self.repo / "src", packet, record, outside)
            self.assertEqual(0, code, payload)
            self.assertTrue(outside.is_file())
        for raw_path in ("../escape.py", "src/../src/module.py", ".git/config"):
            with self.subTest(f"rejected literal path {raw_path}"):
                code, payload, _ = fixtures.scope_cli(
                    self.repo, self.output(f"c2-{raw_path.replace('/', '-')}"),
                    "--mode", "workspace", "--path", raw_path)
                self.assertEqual(2, code, payload)
                self.assertEqual("E_PATH_INVALID", payload["code"])


if __name__ == "__main__":
    unittest.main()
