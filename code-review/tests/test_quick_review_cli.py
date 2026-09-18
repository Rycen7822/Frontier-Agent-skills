"""Short CLI tests: arguments, artifacts, exit codes, and input preservation."""

from __future__ import annotations

from copy import deepcopy
import builtins
import errno
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

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
        code, payload = fixtures.capture_cli(self.repo, output, *args)
        return code, payload, output

    def read_report(self, report_path: Path) -> dict:
        """Read one written report and validate it against the check schema."""
        report = json.loads(report_path.read_text(encoding="utf-8"))
        review_record.validate_document(report, "check_report")
        return report

    def check(self, packet: Path, record_value: dict, name: str):
        record_path = fixtures.write_json(self.root / f"{name}-record.json", record_value)
        report_path = self.root / f"{name}-report.json"
        code, payload = fixtures.check_cli(self.repo, packet, record_path, report_path)
        return code, payload, report_path

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
        code, payload = fixtures.capture_cli(self.repo, existing, "--mode", "workspace", "--path", ".")
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertIsNone(payload["artifact"])
        self.assertEqual("keep\n", marker.read_text(encoding="utf-8"))
        self.assertEqual(["keep.txt"], sorted(path.name for path in existing.iterdir()))

    def test_scope_refuses_output_inside_the_repository(self) -> None:
        inside = self.repo / "packet"
        code, payload = fixtures.capture_cli(self.repo, inside, "--mode", "workspace", "--path", ".")
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
        fixtures.write_file(
            self.repo, "src/owned.py", "def read(record):\n    return record['payload']\n"
        )
        code, payload, packet_dir = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        packet = fixtures.packet_view(packet_dir)
        # The snippet is the second byte line of the file on disk, read without the locator.
        second_line = (self.repo / "src/owned.py").read_bytes().split(b"\n")[1]
        self.assertEqual(b"    return record['payload']", second_line)
        entry = fixtures.evidence(
            packet,
            snippet=second_line.decode("utf-8"),
            start_line=2,
            end_line=2,
            source_name="src/owned.py",
        )
        record = fixtures.hand_record(
            packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
        )
        code, payload, report_path = self.check(packet_dir, record, "round-trip")
        self.assertEqual(0, code, payload)
        self.assertEqual("valid", payload["result"])
        self.assertEqual("all_declared_reviewed", payload["coverage_status"])
        self.assertEqual("captured_inputs_match", payload["freshness"])
        report = self.read_report(report_path)
        anchor = report["anchors"][0]
        self.assertEqual(0, report["exit_code"])
        self.assertEqual(1, report["finding_count"])
        self.assertEqual("resolved", anchor["status"])
        self.assertEqual((2, 2), (anchor["start_line"], anchor["end_line"]))
        self.assertEqual(
            {"total": 2, "reviewed": 2, "partial": 0, "not_reviewed": 0},
            report["item_counts"],
        )

    def test_check_exit_four_for_partial_coverage(self) -> None:
        fixtures.write_file(self.repo, "src/module.py", "value = 3\n")
        code, payload, packet_dir = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        packet = fixtures.packet_view(packet_dir)
        record = fixtures.hand_record(
            packet,
            coverage=[
                {
                    "item_id": packet["scope"]["items"][0]["id"],
                    "status": "not_reviewed",
                    "reason": "Only the entry point was inspected.",
                }
            ],
            verification=[
                {
                    "id": "V-1",
                    "label": "Runtime reproduction",
                    "status": "not_run",
                    "observation": "No runtime was started for this record.",
                }
            ],
        )
        code, payload, report_path = self.check(packet_dir, record, "partial")
        self.assertEqual(4, code)
        self.assertEqual("valid", payload["result"])
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(4, report["exit_code"])
        self.assertEqual("partial", report["coverage_status"])
        self.assertEqual(0, report["finding_count"])
        self.assertEqual([], report["problems"])

    def test_check_reports_a_packet_without_scope_json(self) -> None:
        empty_packet = self.root / "empty-packet"
        empty_packet.mkdir()
        # A structurally valid record for a packet that was never captured.
        record = {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": "sha256:" + "0" * 64,
            "coverage": [],
            "findings": [],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }
        code, payload, report_path = self.check(empty_packet, record, "empty")
        self.assertEqual(2, code)
        report = self.read_report(report_path)
        self.assertEqual("invalid", report["validation"])
        self.assertEqual("E_SCOPE_MISSING", report["problems"][0]["code"])

    def test_check_leaves_packet_and_record_untouched(self) -> None:
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet_dir = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        before = {
            path.name: review_record.sha256_digest(path.read_bytes())
            for path in [
                packet_dir / "scope.json",
                *sorted((packet_dir / "objects").iterdir()),
            ]
        }
        code, payload, report_path = self.check(
            packet_dir, fixtures.hand_record(fixtures.packet_view(packet_dir)), "untouched"
        )
        self.assertEqual(0, code, payload)
        after = {
            path.name: review_record.sha256_digest(path.read_bytes())
            for path in [
                packet_dir / "scope.json",
                *sorted((packet_dir / "objects").iterdir()),
            ]
        }
        self.assertEqual(before, after)
        self.assertTrue(report_path.is_file())

    def test_check_refuses_an_existing_report_and_repo_internal_output(self) -> None:
        code, payload, packet_dir = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        record = fixtures.hand_record(fixtures.packet_view(packet_dir))
        existing = self.root / "existing-report-report.json"
        existing.write_bytes(b"previous\n")
        code, payload, report_path = self.check(packet_dir, record, "existing-report")
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertEqual(b"previous\n", existing.read_bytes())
        self.assertEqual(existing, report_path)
        inside = self.repo / "report.json"
        record_path = fixtures.write_json(self.root / "existing-report-record.json", record)
        code, payload = fixtures.check_cli(self.repo, packet_dir, record_path, inside)
        self.assertEqual(2, code)
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertFalse(inside.exists())

    def _n06_scaffold(self) -> tuple[Path, dict]:
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        return packet, fixtures.hand_record(fixtures.packet_view(packet))

    def test_n06_invalid_inputs_produce_a_bounded_invalid_report(self) -> None:
        packet, record = self._n06_scaffold()
        sentinel = "S" * 9000
        with self.subTest("N06 over-long recorded field"):
            value = deepcopy(record)
            value["limitations"] = [sentinel]
            code, payload, report_path = self.check(packet, value, "n06-long-field")
            self.assertEqual(2, code)
            self.assertEqual("invalid", payload["result"])
            report = self.read_report(report_path)
            self.assertEqual(2, report["exit_code"])
            self.assertEqual("E_SCHEMA", report["problems"][0]["code"])
            self.assertLessEqual(len(report["problems"][0]["message"]), 512)
            self.assertEqual("unavailable", report["coverage_status"])
            self.assertEqual("not_checked", report["freshness"]["status"])
            self.assertIsNone(report["finding_count"])
            self.assertIsNone(report["item_counts"])
            self.assertNotIn(sentinel, json.dumps(report))
            self.assertNotIn(sentinel, json.dumps(payload))
        with self.subTest("N06 unknown over-long field"):
            value = deepcopy(record)
            value["U" * 9000] = 1
            code, payload, report_path = self.check(packet, value, "n06-unknown-field")
            self.assertEqual(2, code)
            report = self.read_report(report_path)
            self.assertEqual("E_SCHEMA", report["problems"][0]["code"])
            self.assertEqual("", report["problems"][0]["pointer"])
            self.assertNotIn("U" * 100, json.dumps(report))
        with self.subTest("N06 pointer beyond the expressible bound"):
            value = deepcopy(record)
            value["limitations"] = [sentinel]
            code, payload, report_path = self.check(packet, value, "n06-pointer-bound")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("E_SCHEMA", report["problems"][0]["code"])
            self.assertEqual("/limitations/0", report["problems"][0]["pointer"])
            self.assertEqual(2, payload["exit_code"])
        with self.subTest("N06 directory as the record"):
            directory = self.root / "n06-directory"
            directory.mkdir()
            report_path = self.root / "n06-directory-report.json"
            code, payload = fixtures.check_cli(self.repo, packet, directory, report_path)
            self.assertEqual(2, code)
            self.assertEqual(str(report_path), payload["artifact"])
            report = self.read_report(report_path)
            self.assertEqual("E_INPUT_TYPE", report["problems"][0]["code"])
        with self.subTest("N06 missing record"):
            report_path = self.root / "n06-missing-report.json"
            code, payload = fixtures.check_cli(self.repo, packet, self.root / "n06-absent.json", report_path)
            self.assertEqual(2, code)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("E_INPUT_MISSING", report["problems"][0]["code"])
        with self.subTest("N06 merged limitations over the report bound"):
            value = deepcopy(record)
            value["limitations"] = ["first", "second", "third"]
            record_path = self.root / "n06-overflow-record.json"
            before = fixtures.write_json(record_path, value).read_bytes()
            with mock.patch.object(review_record, "MAX_ITEMS", 2):
                code, payload, report_path = self.check(packet, value, "n06-overflow")
            self.assertEqual(2, code)
            self.assertEqual("E_REPORT_LIMIT", payload["code"])
            self.assertIsNone(payload["artifact"])
            self.assertFalse(report_path.exists())
            self.assertEqual(before, record_path.read_bytes())
        with self.subTest("N06 write-stage failure"):
            real_fdopen = os.fdopen

            class _PartialWrite:
                """Wrap the real stream, write half the payload, then fail."""

                def __init__(self, handle) -> None:
                    self._handle = handle

                def write(self, data: bytes) -> None:
                    self._handle.write(data[: len(data) // 2])
                    raise OSError(errno.ENOSPC, "No space left on device")

                def __enter__(self):
                    return self

                def __exit__(self, *exc_info):
                    self._handle.__exit__(*exc_info)

            with mock.patch.object(
                os,
                "fdopen",
                lambda descriptor, *args, **kwargs: _PartialWrite(
                    real_fdopen(descriptor, *args, **kwargs)
                ),
            ):
                code, payload, report_path = self.check(packet, record, "n06-write-failure")
            self.assertEqual(2, code)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertIsNone(payload["artifact"])
            self.assertNotIn("valid", json.dumps(payload))
            self.assertTrue(report_path.exists())
            with self.assertRaises(ValueError):
                json.loads(report_path.read_text(encoding="utf-8"))
        with self.subTest("N06 close-stage failure keeps the descriptor count"):
            real_fdopen = os.fdopen

            class _FailingClose:
                """Wrap the real stream and fail while closing it."""

                def __init__(self, handle) -> None:
                    self._handle = handle

                def write(self, data: bytes) -> None:
                    self._handle.write(data)

                def __enter__(self):
                    return self

                def __exit__(self, *exc_info):
                    self._handle.close()
                    raise OSError(errno.EIO, "Input/output error")

            descriptor_dir = "/proc/self/fd"
            before = len(os.listdir(descriptor_dir)) if os.path.isdir(descriptor_dir) else None
            with mock.patch.object(
                os,
                "fdopen",
                lambda descriptor, *args, **kwargs: _FailingClose(
                    real_fdopen(descriptor, *args, **kwargs)
                ),
            ):
                code, payload, report_path = self.check(packet, record, "n06-close-failure")
            self.assertEqual(2, code)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertIsNone(payload["artifact"])
            self.assertNotIn("valid", json.dumps(payload))
            self.assertTrue(report_path.exists())
            if before is not None:
                self.assertEqual(before, len(os.listdir(descriptor_dir)))

    def _f2_scaffold(self):
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src/module.py")
        self.assertEqual(0, code, payload)
        scope_path = packet / "scope.json"
        original = scope_path.read_bytes()
        replaced = json.loads(original.decode("utf-8"))
        replaced["limitations"] = ["the scope file was replaced after it was read"]
        replaced_bytes = (json.dumps(replaced, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.assertNotEqual(original, replaced_bytes)
        return packet, scope_path, original, replaced_bytes, fixtures.hand_record(
            fixtures.packet_view(packet)
        )

    def test_f2_scope_digest_binds_the_bytes_that_were_read(self) -> None:
        packet, scope_path, original, replaced_bytes, record = self._f2_scaffold()
        real_open = builtins.open
        reads = {"scope": 0}

        class _SwappingHandle:
            """Delegate to the real file object and replace the file after its first read."""

            def __init__(self, handle) -> None:
                self._handle = handle

            def read(self, *args):
                data = self._handle.read(*args)
                scope_path.write_bytes(replaced_bytes)
                return data

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return self._handle.__exit__(*exc_info)

            def __getattr__(self, name):
                return getattr(self._handle, name)

        def swapping_open(file, *args, **kwargs):
            handle = real_open(file, *args, **kwargs)
            if not os.fspath(file).endswith("scope.json"):
                return handle
            reads["scope"] += 1
            return _SwappingHandle(handle) if reads["scope"] == 1 else handle

        def check(record_value, name):
            with mock.patch.object(builtins, "open", swapping_open):
                return self.check(packet, record_value, f"f2-{name}")

        with self.subTest("F2 a record bound to the replaced bytes is rejected"):
            replaced_record = deepcopy(record)
            replaced_record["scope_sha256"] = review_record.sha256_digest(replaced_bytes)
            code, payload, report_path = check(replaced_record, "replaced")
            self.assertEqual(2, code, payload)
            self.assertEqual(1, reads["scope"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("invalid", report["validation"])
            codes = [problem["code"] for problem in report["problems"]]
            self.assertIn("E_SCOPE_DIGEST", codes)
        with self.subTest("F2 a record bound to the bytes that were read still validates"):
            scope_path.write_bytes(original)
            reads["scope"] = 0
            bound_record = deepcopy(record)
            bound_record["scope_sha256"] = review_record.sha256_digest(original)
            code, payload, report_path = check(bound_record, "bound")
            self.assertEqual(0, code, payload)
            self.assertEqual(1, reads["scope"])
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("valid", report["validation"])

    def test_f3_json_text_encoding_errors_are_typed(self) -> None:
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src/module.py")
        self.assertEqual(0, code, payload)
        record = fixtures.hand_record(fixtures.packet_view(packet))

        with self.subTest("F3 an unpaired surrogate is a bounded encoding error"):
            broken = deepcopy(record)
            broken["limitations"] = ["lone surrogate: \ud800"]
            raw = (json.dumps(broken, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            self.assertIn(b"\\ud800", raw)
            record_path = self.root / "f3-surrogate-record.json"
            record_path.write_bytes(raw)
            report_path = self.root / "f3-surrogate-report.json"
            code, payload = fixtures.check_cli(self.repo, packet, record_path, report_path)
            self.assertEqual(2, code, payload)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("invalid", report["validation"])
            problems = [problem for problem in report["problems"] if problem["code"] == "E_JSON_ENCODING"]
            self.assertEqual(1, len(problems))
            self.assertLessEqual(len(problems[0]["message"]), 512)
            self.assertEqual(raw, record_path.read_bytes())
        with self.subTest("F3 valid non-ASCII text and escaped literals still validate"):
            accepted = deepcopy(record)
            accepted["limitations"] = ["\u4e2d\u6587\u4e0e emoji \U0001f600", "literal \\ud800"]
            code, payload, report_path = self.check(packet, accepted, "f3-accepted")
            self.assertEqual(0, code, payload)
            self.assertEqual("valid", json.loads(report_path.read_text(encoding="utf-8"))["validation"])


if __name__ == "__main__":
    unittest.main()
