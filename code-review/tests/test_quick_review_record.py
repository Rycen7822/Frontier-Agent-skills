"""R01-R19: record structure, relations, captured objects, and location status."""

from __future__ import annotations

from copy import deepcopy
import errno
import json
from pathlib import Path
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

import _review_record as review_record  # noqa: E402
import _review_fixtures as fixtures  # noqa: E402

OID_A = "a" * 40
OID_B = "b" * 40


class QuickReviewRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        # ``check`` resolves --repo to its canonical root before it inspects inputs.
        fixtures.init_repo(self.root)

    def validate(self, packet, record):
        return review_record.validate_record(
            packet["packet"], packet["scope"], record, scope_bytes=packet["scope_bytes"]
        )

    def check_report(self, validation: dict) -> dict:
        """Build the check report for a captured-inputs-match freshness result."""
        return review_record.finish_report(
            validation, {"status": "captured_inputs_match", "changed_paths": []}
        )

    def assertCode(self, code, callable_, *args, **kwargs):
        with self.assertRaises(review_record.ReviewError) as caught:
            callable_(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_r01_valid_record_without_findings_is_valid_not_a_verdict(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"value = 1\n")
        record = fixtures.hand_record(packet)
        validation = self.validate(packet, record)
        self.assertEqual("valid", validation["validation"])
        self.assertEqual("all_declared_reviewed", validation["coverage_status"])
        report = self.check_report(validation)
        review_record.validate_document(report, "check_report")
        self.assertEqual(0, report["exit_code"])
        for forbidden in ("pass", "ready", "publication_ceiling", "review_is_current"):
            self.assertNotIn(forbidden, report)
        self.assertEqual(
            "all_declared_reviewed", report["coverage_status"]
        )

    def test_r02_valid_critical_finding_stays_structurally_valid(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"return load(object_id)\n")
        record = fixtures.hand_record(
            packet,
            findings=[
                fixtures.finding(
                    packet,
                    severity="critical",
                    evidence_entries=[
                        fixtures.evidence(
                            packet,
                            snippet="return load(object_id)",
                            start_line=1,
                            end_line=1,
                        )
                    ],
                )
            ],
        )
        validation = self.validate(packet, record)
        self.assertEqual("valid", validation["validation"])
        report = self.check_report(validation)
        self.assertEqual(1, report["finding_count"])
        self.assertEqual(0, report["exit_code"])
        serialized = json.dumps(report)
        for forbidden in ("publish", "publication", "approval"):
            self.assertNotIn(forbidden, serialized)

    def test_r03_coverage_gaps_duplicates_and_unknown_ids_are_invalid(self) -> None:
        packet = fixtures.hand_packet(
            self.root,
            sources=[
                {
                    "name": "one",
                    "path": "src/one.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": b"one = 1\n",
                },
                {
                    "name": "two",
                    "path": "src/two.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": b"two = 2\n",
                },
            ],
            items=[
                {"layer": "worktree", "status": "A", "path": "src/one.py", "after": "one"},
                {"layer": "worktree", "status": "A", "path": "src/two.py", "after": "two"},
            ],
        )
        first, second = (item["id"] for item in packet["scope"]["items"])
        cases = {
            "empty": ([], "E_COVERAGE_MISSING"),
            "missing": ([{"item_id": first, "status": "reviewed", "reason": None}], "E_COVERAGE_MISSING"),
            "duplicate": (
                [
                    {"item_id": first, "status": "reviewed", "reason": None},
                    {"item_id": first, "status": "reviewed", "reason": None},
                    {"item_id": second, "status": "reviewed", "reason": None},
                ],
                "E_COVERAGE_DUPLICATE",
            ),
            "unknown": (
                [
                    {"item_id": first, "status": "reviewed", "reason": None},
                    {"item_id": second, "status": "reviewed", "reason": None},
                    {"item_id": "I-000009", "status": "reviewed", "reason": None},
                ],
                "E_COVERAGE_UNKNOWN",
            ),
        }
        for label, (coverage, code) in cases.items():
            with self.subTest(f"R03 {label}"):
                record = fixtures.hand_record(packet, coverage=coverage)
                self.assertCode(code, self.validate, packet, record)

    def test_r04_duplicate_identifiers_are_invalid(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        item_id = packet["scope"]["items"][0]["id"]
        snippet = fixtures.evidence(packet, snippet="x = 1", start_line=1, end_line=1)
        duplicate_findings = [
            fixtures.finding(packet, finding_id="F-1", evidence_entries=[snippet]),
            fixtures.finding(packet, finding_id="F-1", evidence_entries=[snippet]),
        ]
        with self.subTest("R04 finding"):
            record = fixtures.hand_record(packet, findings=duplicate_findings)
            self.assertCode("E_DUPLICATE_ID", self.validate, packet, record)
        concern = {
            "id": "C-1",
            "summary": "Unresolved ownership question.",
            "item_ids": [item_id],
            "missing_evidence": "No caller list was captured.",
            "impact_if_true": "A second caller may bypass the check.",
        }
        with self.subTest("R04 concern"):
            record = fixtures.hand_record(packet, concerns=[concern, deepcopy(concern)])
            self.assertCode("E_DUPLICATE_ID", self.validate, packet, record)
        verification = {
            "id": "V-1",
            "label": "Runtime reproduction",
            "status": "not_run",
            "observation": "Only source inspection was performed.",
        }
        with self.subTest("R04 verification"):
            record = fixtures.hand_record(
                packet, verification=[verification, deepcopy(verification)]
            )
            self.assertCode("E_DUPLICATE_ID", self.validate, packet, record)

    def test_r05_unknown_source_digest_mismatch_and_corrupt_bytes(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        snippet = fixtures.evidence(packet, snippet="x = 1", start_line=1, end_line=1)
        with self.subTest("R05 unknown source"):
            broken = deepcopy(snippet)
            broken["source_id"] = "S-000042"
            record = fixtures.hand_record(
                packet, findings=[fixtures.finding(packet, evidence_entries=[broken])]
            )
            error = self.assertCode("E_REFERENCE_UNKNOWN", self.validate, packet, record)
            self.assertEqual("/findings/0/evidence/0/source_id", error.pointer)
        with self.subTest("R05 scope digest"):
            record = fixtures.hand_record(packet)
            record["scope_sha256"] = "sha256:" + "0" * 64
            error = self.assertCode("E_SCOPE_DIGEST", self.validate, packet, record)
            self.assertEqual("/scope_sha256", error.pointer)
        with self.subTest("R05 corrupt bytes"):
            blob = next((packet["packet"] / "objects").glob("*.blob"))
            blob.write_bytes(b"tampered\n")
            record = fixtures.hand_record(packet)
            self.assertCode("E_SOURCE_OBJECT", self.validate, packet, record)
        with self.subTest("R05 pointer on schema error"):
            record = fixtures.hand_record(packet)
            record["coverage"][0]["status"] = "looked_at"
            error = self.assertCode("E_SCHEMA", self.validate, packet, record)
            self.assertEqual("/coverage/0/status", error.pointer)

    def test_r06_partial_coverage_requires_a_reason(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        item_id = packet["scope"]["items"][0]["id"]
        with self.subTest("R06 without reason"):
            record = fixtures.hand_record(
                packet, coverage=[{"item_id": item_id, "status": "partial", "reason": None}]
            )
            self.assertCode("E_SCHEMA", self.validate, packet, record)
        with self.subTest("R06 with reason"):
            record = fixtures.hand_record(
                packet,
                coverage=[
                    {
                        "item_id": item_id,
                        "status": "partial",
                        "reason": "Only the public entry point was opened.",
                    }
                ],
            )
            validation = self.validate(packet, record)
            self.assertEqual("partial", validation["coverage_status"])
            report = self.check_report(validation)
            self.assertEqual(4, report["exit_code"])

    def test_r07_non_text_source_cannot_be_declared_reviewed(self) -> None:
        with self.subTest("R07 binary"):
            packet = fixtures.hand_packet(
                self.root,
                packet_name="binary-packet",
                sources=[
                    {
                        "name": "blob",
                        "path": "assets/logo.bin",
                        "origin": "worktree",
                        "availability": "binary",
                        "payload": b"\x00\x01\x02",
                    }
                ],
                items=[
                    {
                        "layer": "worktree",
                        "status": "A",
                        "path": "assets/logo.bin",
                        "after": "blob",
                    }
                ],
            )
            record = fixtures.hand_record(packet)
            self.assertCode("E_COVERAGE_UNSUPPORTED", self.validate, packet, record)
        with self.subTest("R07 oversize"):
            packet = fixtures.hand_packet(
                self.root,
                packet_name="oversize-packet",
                sources=[
                    {
                        "name": "big",
                        "path": "data/big.bin",
                        "origin": "worktree",
                        "availability": "too_large",
                        "size_bytes": 9 * 1024 * 1024,
                    }
                ],
                items=[
                    {"layer": "worktree", "status": "A", "path": "data/big.bin", "after": "big"}
                ],
            )
            record = fixtures.hand_record(packet)
            self.assertCode("E_COVERAGE_UNSUPPORTED", self.validate, packet, record)

    def test_r07b_shared_digest_keeps_each_source_availability(self) -> None:
        cases = {
            "text source sorts first": ("a-text.py", "z-link"),
            "symlink source sorts first": ("z-text.py", "a-link"),
        }
        for label, (text_path, link_path) in cases.items():
            with self.subTest(label):
                packet = fixtures.hand_packet(
                    self.root,
                    packet_name=f"mixed-{label.split()[0]}",
                    sources=[
                        {
                            "name": "text",
                            "path": text_path,
                            "origin": "worktree",
                            "git_mode": "100644",
                            "availability": "text",
                            "payload": b"target",
                        },
                        {
                            "name": "link",
                            "path": link_path,
                            "origin": "worktree",
                            "git_mode": "120000",
                            "availability": "symlink",
                            "payload": b"target",
                        },
                    ],
                    items=[
                        {
                            "layer": "worktree",
                            "status": "A",
                            "path": text_path,
                            "after": "text",
                        },
                        {
                            "layer": "worktree",
                            "status": "A",
                            "path": link_path,
                            "after": "link",
                        },
                    ],
                )
                digests = {source["sha256"] for source in packet["scope"]["sources"]}
                self.assertEqual(1, len(digests), packet["scope"]["sources"])
                # The fixture orders sources by path, so this is the group order under test.
                self.assertEqual(
                    ["text" if path == text_path else "symlink" for path in sorted(cases[label])],
                    [source["availability"] for source in packet["scope"]["sources"]],
                )
                record = fixtures.hand_record(
                    packet,
                    coverage=[
                        {
                            "item_id": packet["item_ids"][text_path],
                            "status": "reviewed",
                            "reason": None,
                        },
                        {
                            "item_id": packet["item_ids"][link_path],
                            "status": "not_reviewed",
                            "reason": "A symlink target is outside this scope.",
                        },
                    ],
                    findings=[
                        fixtures.finding(
                            packet,
                            evidence_entries=[
                                fixtures.evidence(packet, snippet="target", source_name="text"),
                                fixtures.evidence(packet, snippet="target", source_name="link"),
                            ],
                        )
                    ],
                )
                with mock.patch.object(
                    review_record, "read_source", side_effect=review_record.read_source
                ) as read:
                    validation = self.validate(packet, record)
                self.assertEqual(["valid", "partial"], [validation["validation"], validation["coverage_status"]])
                self.assertEqual([], validation["problems"])
                self.assertEqual(
                    [digests.pop()], [call.args[1]["sha256"] for call in read.call_args_list]
                )
                text_anchor, link_anchor = validation["anchors"]
                self.assertEqual(
                    [packet["source_ids"]["text"], "resolved", 1, 1],
                    [
                        text_anchor["source_id"],
                        text_anchor["status"],
                        text_anchor["start_line"],
                        text_anchor["end_line"],
                    ],
                )
                self.assertEqual(
                    [packet["source_ids"]["link"], "unsupported_source"],
                    [link_anchor["source_id"], link_anchor["status"]],
                )
                report = self.check_report(validation)
                self.assertEqual(4, report["exit_code"])
                self.assertEqual(
                    ["not_reviewed"],
                    [
                        entry["status"]
                        for entry in record["coverage"]
                        if entry["item_id"] == packet["item_ids"][link_path]
                    ],
                )

    def test_r08_empty_scope_reports_nothing_in_scope(self) -> None:
        packet = fixtures.hand_packet(self.root, sources=[], items=[])
        with self.subTest("R08 empty"):
            record = fixtures.hand_record(packet)
            validation = self.validate(packet, record)
            self.assertEqual("nothing_in_scope", validation["coverage_status"])
            report = self.check_report(validation)
            review_record.validate_document(report, "check_report")
            self.assertEqual(0, report["exit_code"])
            self.assertEqual(0, report["finding_count"])
        with self.subTest("R08 rejected finding"):
            record = fixtures.hand_record(
                packet,
                findings=[
                    {
                        "id": "F-1",
                        "severity": "low",
                        "summary": "Something looks off.",
                        "relation": "not_determined",
                        "trigger": "Any call.",
                        "impact": "Unknown.",
                        "item_ids": ["I-000001"],
                        "evidence": [
                            {
                                "source_id": "S-000001",
                                "start_line": None,
                                "end_line": None,
                                "snippet": None,
                            }
                        ],
                        "fix": None,
                    }
                ],
            )
            self.assertCode("E_EMPTY_SCOPE_FINDINGS", self.validate, packet, record)

    def test_r09_line_number_shapes_are_rejected(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\ny = 2\n")

        def with_lines(start, end):
            entry = fixtures.evidence(packet, snippet="x = 1", start_line=start, end_line=end)
            return fixtures.hand_record(
                packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
            )

        cases = {
            "boolean": (True, True, "E_SCHEMA"),
            "negative": (-1, 1, "E_SCHEMA"),
            "single side null": (1, None, "E_SCHEMA"),
            "beyond eof": (3, 4, "E_LOCATION_RANGE"),
            "inverted": (2, 1, "E_LOCATION_RANGE"),
        }
        for label, (start, end, code) in cases.items():
            with self.subTest(f"R09 {label}"):
                self.assertCode(code, self.validate, packet, with_lines(start, end))

    def test_r10_explicit_coordinates_win_over_repeats(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"alpha\nbeta\nalpha\n")
        entry = fixtures.evidence(packet, snippet="alpha", start_line=3, end_line=3)
        record = fixtures.hand_record(
            packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
        )
        validation = self.validate(packet, record)
        anchor = validation["anchors"][0]
        self.assertEqual("resolved", anchor["status"])
        self.assertEqual((3, 3), (anchor["start_line"], anchor["end_line"]))
        self.assertIsNone(anchor["candidate_start"])

    def test_r11_anchor_status_without_coordinates(self) -> None:
        cases = {
            "unique": (b"alpha\nbeta\n", "beta", "resolved", (2, 2)),
            "repeated": (b"alpha\nalpha\n", "alpha", "ambiguous", None),
            "absent": (b"alpha\nbeta\n", "gamma", "unlocated", None),
        }
        for label, (payload, snippet, status, coordinates) in cases.items():
            with self.subTest(f"R11 {label}"):
                packet = fixtures.anchor_packet(
                    self.root, payload, packet_name=f"packet-{label}"
                )
                entry = fixtures.evidence(packet, snippet=snippet)
                record = fixtures.hand_record(
                    packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
                )
                validation = self.validate(packet, record)
                anchor = validation["anchors"][0]
                self.assertEqual(status, anchor["status"])
                if coordinates is None:
                    self.assertIsNone(anchor["start_line"])
                else:
                    self.assertEqual(coordinates, (anchor["start_line"], anchor["end_line"]))

    def test_r11b_one_source_split_per_blob_and_per_source_metadata(self) -> None:
        payload = b"alpha\nbeta\ngamma\n"
        packet = fixtures.anchor_packet(self.root, payload)
        entries = [
            fixtures.evidence(packet, snippet=line, start_line=number, end_line=number)
            for number, line in enumerate(("alpha", "beta", "gamma"), start=1)
        ]
        record = fixtures.hand_record(
            packet, findings=[fixtures.finding(packet, evidence_entries=entries)]
        )
        with mock.patch.object(
            review_record, "split_lines", side_effect=review_record.split_lines
        ) as split:
            validation = self.validate(packet, record)
        self.assertEqual(
            ["resolved"] * 3, [anchor["status"] for anchor in validation["anchors"]]
        )
        # One source split for the shared blob, one snippet split per anchor.
        self.assertEqual(4, split.call_count)
        self.assertEqual(1, sum(1 for call in split.call_args_list if call.args[0] == payload))
        with self.subTest("R11b a second source with the same digest keeps its own metadata"):
            shared = fixtures.hand_packet(
                self.root,
                sources=[
                    {
                        "name": "old",
                        "path": "src/module.py",
                        "origin": "git",
                        "revision": "a" * 40,
                        "git_oid": "b" * 40,
                        "availability": "text",
                        "payload": payload,
                    },
                    {
                        "name": "new",
                        "path": "src/module.py",
                        "origin": "worktree",
                        "availability": "text",
                        "payload": payload,
                    },
                ],
                items=[
                    {
                        "layer": "worktree",
                        "status": "M",
                        "path": "src/module.py",
                        "before": "old",
                        "after": "new",
                    }
                ],
                packet_name="packet-shared-digest",
            )
            self.assertEqual(
                1, len({source["sha256"] for source in shared["scope"]["sources"]})
            )
            both = fixtures.hand_record(
                shared,
                findings=[
                    fixtures.finding(
                        shared,
                        evidence_entries=[
                            fixtures.evidence(shared, snippet="beta", source_name="old"),
                            fixtures.evidence(shared, snippet="beta", source_name="new"),
                        ],
                    )
                ],
            )
            anchors = self.validate(shared, both)["anchors"]
            self.assertEqual(
                [shared["source_ids"]["old"], shared["source_ids"]["new"]],
                [anchor["source_id"] for anchor in anchors],
            )
            self.assertEqual(["resolved", "resolved"], [anchor["status"] for anchor in anchors])
            shared["scope"]["sources"][1]["size_bytes"] += 1
            with self.assertRaises(review_record.ReviewError) as caught:
                self.validate(shared, both)
            self.assertEqual("E_SOURCE_OBJECT", caught.exception.code)

    def test_r12_wrong_coordinates_relocate_without_rewriting_the_record(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"first\nsecond\nthird\n")
        entry = fixtures.evidence(packet, snippet="second", start_line=1, end_line=1)
        record = fixtures.hand_record(
            packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
        )
        record_path = fixtures.write_json(self.root / "review-record.json", record)
        before = record_path.read_bytes()
        validation = self.validate(packet, record)
        anchor = validation["anchors"][0]
        self.assertEqual("needs_relocation", anchor["status"])
        self.assertEqual((1, 1), (anchor["start_line"], anchor["end_line"]))
        self.assertEqual((2, 2), (anchor["candidate_start"], anchor["candidate_end"]))
        self.assertEqual(before, record_path.read_bytes())
        self.assertEqual(record, json.loads(before))

    def test_r13_line_splitting_keeps_source_semantics(self) -> None:
        payload = b"+x\n-y\n    indented\n   \nlast\r\n"
        packet = fixtures.anchor_packet(self.root, payload)
        cases = {
            "diff markers": ("+x\n-y", 1, 2),
            "indentation": ("    indented", 3, 3),
            "whitespace-only line": ("   ", 4, 4),
            "crlf": ("last", 5, 5),
            "trailing terminator": ("-y\n", 2, 2),
        }
        for label, (snippet, start, end) in cases.items():
            with self.subTest(f"R13 {label}"):
                entry = fixtures.evidence(
                    packet, snippet=snippet, start_line=start, end_line=end
                )
                record = fixtures.hand_record(
                    packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
                )
                validation = self.validate(packet, record)
                anchor = validation["anchors"][0]
                self.assertEqual("resolved", anchor["status"])
                self.assertEqual((start, end), (anchor["start_line"], anchor["end_line"]))
        with self.subTest("R13 lone trailing CR"):
            lone = fixtures.anchor_packet(
                self.root, b"value\r", packet_name="packet-lone-cr"
            )
            entry = fixtures.evidence(lone, snippet="value")
            record = fixtures.hand_record(
                lone, findings=[fixtures.finding(lone, evidence_entries=[entry])]
            )
            validation = self.validate(lone, record)
            self.assertEqual("unlocated", validation["anchors"][0]["status"])
        with self.subTest("R13 para separator"):
            separator = fixtures.anchor_packet(
                self.root,
                "alpha\u2028beta\n".encode("utf-8"),
                packet_name="packet-u2028",
            )
            entry = fixtures.evidence(
                separator,
                snippet="alpha\u2028beta",
                start_line=1,
                end_line=1,
            )
            record = fixtures.hand_record(
                separator, findings=[fixtures.finding(separator, evidence_entries=[entry])]
            )
            validation = self.validate(separator, record)
            self.assertEqual("resolved", validation["anchors"][0]["status"])

    def test_r14_deleted_side_evidence_keeps_the_old_revision(self) -> None:
        packet = fixtures.hand_packet(
            self.root,
            mode="commit",
            request={
                "paths": ["src/module.py"],
                "context_paths": [],
                "base": None,
                "head": None,
                "commit": OID_B,
                "revision": None,
            },
            resolved={
                "object_format": "sha1",
                "base_oid": None,
                "head_oid": OID_B,
                "comparison_base_oid": None,
            },
            sources=[
                {
                    "name": "old",
                    "path": "src/module.py",
                    "origin": "git",
                    "revision": OID_A,
                    "git_oid": OID_A,
                    "git_mode": "100644",
                    "availability": "text",
                    "payload": b"def guard():\n    return strict\n",
                }
            ],
            items=[
                {"layer": "commit", "status": "D", "path": "src/module.py", "before": "old"}
            ],
        )
        entry = fixtures.evidence(
            packet,
            snippet="    return strict",
            start_line=2,
            end_line=2,
            source_name="old",
        )
        record = fixtures.hand_record(
            packet, findings=[fixtures.finding(packet, evidence_entries=[entry])]
        )
        validation = self.validate(packet, record)
        anchor = validation["anchors"][0]
        self.assertEqual("resolved", anchor["status"])
        self.assertEqual(OID_A, anchor["revision"])
        self.assertEqual("git", anchor["origin"])
        self.assertEqual(2, anchor["start_line"])
        self.assertIsNone(packet["scope"]["items"][0]["after"])

    def test_r15_strict_json_input_rejection(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        record = fixtures.hand_record(packet)
        valid_bytes = json.dumps(record).encode("utf-8")
        cases = {
            "duplicate key": (b'{"schema_version": "fas-review-record/1", "schema_version": "x"}', "E_JSON_DUPLICATE_KEY"),
            "nan": (b'{"schema_version": NaN}', "E_JSON_CONSTANT"),
            "infinity": (b'{"schema_version": Infinity}', "E_JSON_CONSTANT"),
            "invalid utf-8": (b'{"schema_version": "\xff\xfe"}', "E_JSON_ENCODING"),
            "byte-order mark": (b"\xef\xbb\xbf" + valid_bytes, "E_JSON_ENCODING"),
            "non object root": (b"[1, 2]", "E_JSON_ROOT"),
            "syntax": (b'{"schema_version":}', "E_JSON_SYNTAX"),
        }
        for label, (raw, code) in cases.items():
            with self.subTest(f"R15 {label}"):
                path = self.root / f"{label.replace(' ', '-')}.json"
                path.write_bytes(raw)
                self.assertCode(code, review_record.load_json, path)
        with self.subTest("R15 extra field"):
            broken = deepcopy(record)
            broken["reviewed_paths"] = ["src/module.py"]
            self.assertCode(
                "E_SCHEMA", review_record.validate_document, broken, "record"
            )
        with self.subTest("R15 unknown version"):
            broken = deepcopy(record)
            broken["schema_version"] = "fas-review-record/0"
            self.assertCode(
                "E_SCHEMA", review_record.validate_document, broken, "record"
            )

    def test_r16_context_finding_survives_partial_coverage(self) -> None:
        packet = fixtures.hand_packet(
            self.root,
            sources=[
                {
                    "name": "changed",
                    "path": "src/module.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": b"changed = True\n",
                },
                {
                    "name": "context",
                    "path": "config/runtime.json",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": b'{"limit": 32}\n',
                },
            ],
            items=[
                {
                    "layer": "worktree",
                    "status": "A",
                    "path": "src/module.py",
                    "after": "changed",
                }
            ],
        )
        item_id = packet["scope"]["items"][0]["id"]
        entry = {
            "source_id": packet["source_ids"]["context"],
            "start_line": 1,
            "end_line": 1,
            "snippet": '{"limit": 32}',
        }
        record = fixtures.hand_record(
            packet,
            coverage=[
                {
                    "item_id": item_id,
                    "status": "not_reviewed",
                    "reason": "Only the consumer configuration was inspected.",
                }
            ],
            findings=[fixtures.finding(packet, evidence_entries=[entry])],
        )
        validation = self.validate(packet, record)
        self.assertEqual("partial", validation["coverage_status"])
        self.assertEqual(1, validation["finding_count"])
        self.assertEqual("resolved", validation["anchors"][0]["status"])
        report = self.check_report(validation)
        self.assertEqual(4, report["exit_code"])

    def test_r17_concerns_and_failed_verification_force_exit_four(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        item_id = packet["scope"]["items"][0]["id"]
        base = fixtures.hand_record(packet)
        with self.subTest("R17 concern"):
            record = fixtures.hand_record(
                packet,
                concerns=[
                    {
                        "id": "C-1",
                        "summary": "A second caller may bypass the guard.",
                        "item_ids": [item_id],
                        "missing_evidence": "Caller inventory was not captured.",
                        "impact_if_true": "The guard is not an enforced boundary.",
                    }
                ],
            )
            validation = self.validate(packet, record)
            self.assertEqual(1, validation["concern_count"])
            self.assertEqual(4, self.check_report(validation)["exit_code"])
        with self.subTest("R17 failed verification"):
            record = fixtures.hand_record(
                packet,
                verification=[
                    {
                        "id": "V-1",
                        "label": "Runtime reproduction",
                        "status": "failed",
                        "observation": "The reproduction raised TypeError.",
                    }
                ],
            )
            validation = self.validate(packet, record)
            self.assertEqual(4, self.check_report(validation)["exit_code"])
        with self.subTest("R17 not_run verification"):
            record = fixtures.hand_record(
                packet,
                verification=[
                    {
                        "id": "V-1",
                        "label": "Runtime reproduction",
                        "status": "not_run",
                        "observation": "Only source inspection was performed.",
                    }
                ],
            )
            validation = self.validate(packet, record)
            self.assertEqual(0, self.check_report(validation)["exit_code"])
        with self.subTest("R17 base"):
            validation = self.validate(packet, base)
            self.assertEqual(0, self.check_report(validation)["exit_code"])

    def test_r18_existing_report_output_is_not_overwritten(self) -> None:
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        record = fixtures.hand_record(packet)
        record_path = fixtures.write_json(self.root / "record.json", record)
        packet_path = packet["packet"]
        scope_bytes = (packet_path / "scope.json").read_bytes()
        report_path = self.root / "report.json"
        report_path.write_bytes(b"existing report\n")
        code, payload = fixtures.check_cli(self.root / "repo", packet_path, record_path, report_path)
        self.assertEqual(2, code)
        self.assertEqual(2, payload["exit_code"])
        self.assertIsNone(payload["artifact"])
        self.assertEqual("E_OUTPUT", payload["code"])
        self.assertEqual(b"existing report\n", report_path.read_bytes())
        self.assertEqual(scope_bytes, (packet_path / "scope.json").read_bytes())
        self.assertEqual(record, json.loads(record_path.read_bytes()))

    def test_r19_invalid_input_reports_null_statistics(self) -> None:
        with self.subTest("R19 direct"):
            report = review_record.finish_report(
                {
                    "validation": "invalid",
                    "problems": [
                        {
                            "code": "E_JSON_SYNTAX",
                            "pointer": "",
                            "message": "record.json:1:1: Expecting value",
                        }
                    ],
                },
                {"status": "not_checked", "changed_paths": []},
            )
            review_record.validate_document(report, "check_report")
            self.assertEqual("invalid", report["validation"])
            self.assertEqual("unavailable", report["coverage_status"])
            self.assertEqual("not_checked", report["freshness"]["status"])
            self.assertIsNone(report["finding_count"])
            self.assertIsNone(report["concern_count"])
            self.assertIsNone(report["item_counts"])
            self.assertEqual([], report["anchors"])
            self.assertEqual(2, report["exit_code"])
        with self.subTest("R19 cli"):
            packet = fixtures.anchor_packet(self.root, b"x = 1\n")
            record_path = self.root / "broken-record.json"
            record_path.write_bytes(b'{"schema_version": NaN}')
            report_path = self.root / "invalid-report.json"
            code, payload = fixtures.check_cli(self.root / "repo", packet["packet"], record_path, report_path)
            self.assertEqual(2, code)
            self.assertEqual("invalid", payload["result"])
            report = json.loads(report_path.read_bytes())
            review_record.validate_document(report, "check_report")
            self.assertIsNone(report["finding_count"])
            self.assertIsNone(report["item_counts"])

    def test_n06b_input_io_failures_are_typed(self) -> None:
        path = self.root / "n06b-input.json"
        fixtures.write_json(path, {"schema_version": "fas-review-record/1"})
        cases = {
            PermissionError(errno.EACCES, "Permission denied"): "E_INPUT_IO",
            IsADirectoryError(errno.EISDIR, "Is a directory"): "E_INPUT_TYPE",
            FileNotFoundError(errno.ENOENT, "No such file"): "E_INPUT_MISSING",
            OSError(errno.EIO, "Input/output error"): "E_INPUT_IO",
        }
        for failure, expected in cases.items():
            with self.subTest(f"N06b {type(failure).__name__}"):
                with mock.patch("builtins.open", side_effect=failure):
                    with self.assertRaises(review_record.ReviewError) as caught:
                        review_record.load_json(path)
                self.assertEqual(expected, caught.exception.code)
        packet = fixtures.anchor_packet(self.root, b"x = 1\n")
        source = packet["scope"]["sources"][0]
        with self.subTest("N06b source reads keep their own classification"):
            with mock.patch("builtins.open", side_effect=PermissionError(errno.EACCES, "denied")):
                with self.assertRaises(review_record.ReviewError) as caught:
                    review_record.read_source(packet["packet"], source)
            self.assertEqual("E_SOURCE_OBJECT", caught.exception.code)
            blob = packet["packet"] / "objects" / f"{source['sha256'][7:]}.blob"
            blob.unlink()
            with self.assertRaises(review_record.ReviewError) as missing:
                review_record.read_source(packet["packet"], source)
            self.assertEqual("E_SOURCE_OBJECT", missing.exception.code)
        with self.subTest("N06b a directory is not read as JSON"):
            directory = self.root / "n06b-directory"
            directory.mkdir()
            with self.assertRaises(review_record.ReviewError) as caught:
                review_record.load_json(directory)
            self.assertEqual("E_INPUT_TYPE", caught.exception.code)

    def test_n09_scope_and_record_limitations_are_merged(self) -> None:
        packet = fixtures.hand_packet(
            self.root,
            sources=[
                {
                    "name": "main",
                    "path": "src/module.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": b"value = 1\n",
                }
            ],
            items=[
                {
                    "layer": "worktree",
                    "status": "A",
                    "path": "src/module.py",
                    "after": "main",
                }
            ],
            limitations=["scope note", "shared note"],
        )
        record = fixtures.hand_record(
            packet, limitations=["shared note", "record note", "scope note"]
        )
        before = deepcopy(record)
        validation = self.validate(packet, record)
        self.assertEqual(
            ["scope note", "shared note", "record note"], validation["limitations"]
        )
        self.assertEqual(before, record)
        report = self.check_report(validation)
        review_record.validate_document(report, "check_report")
        self.assertEqual(
            ["scope note", "shared note", "record note"], report["limitations"]
        )
        self.assertEqual(0, report["exit_code"])
        with self.subTest("N09 empty limitations stay valid"):
            empty = fixtures.hand_record(packet)
            self.assertEqual(
                ["scope note", "shared note"], self.validate(packet, empty)["limitations"]
            )
        with self.subTest("N09 the merged array keeps its bound"):
            overflow = fixtures.hand_record(packet, limitations=["a", "b"])
            with mock.patch.object(review_record, "MAX_ITEMS", 2):
                validation = self.validate(packet, overflow)
                self.assertEqual(4, len(validation["limitations"]))
                with self.assertRaises(review_record.ReviewError) as caught:
                    self.check_report(validation)
            self.assertEqual("E_REPORT_LIMIT", caught.exception.code)
            self.assertEqual(
                ["scope note", "shared note"],
                json.loads((packet["packet"] / "scope.json").read_bytes())["limitations"],
            )
            self.assertEqual(["a", "b"], overflow["limitations"])

    def test_n10_coverage_uses_one_source_index(self) -> None:
        class CountingSources(list):
            def __init__(self, values):
                super().__init__(values)
                self.iterations = 0

            def __iter__(self):
                self.iterations += 1
                return super().__iter__()

        for size in (20, 60):
            with self.subTest(f"N10 index built once for {size} items"):
                packet = fixtures.hand_packet(
                    self.root,
                    sources=[
                        {
                            "name": f"s{index}",
                            "path": f"src/f{index:03d}.py",
                            "origin": "worktree",
                            "availability": "text",
                            "payload": f"value = {index}\n".encode("utf-8"),
                        }
                        for index in range(size)
                    ],
                    items=[
                        {
                            "layer": "worktree",
                            "status": "A",
                            "path": f"src/f{index:03d}.py",
                            "after": f"s{index}",
                        }
                        for index in range(size)
                    ],
                    packet_name=f"n10-{size}",
                )
                scope = dict(packet["scope"])
                counting = CountingSources(scope["sources"])
                scope["sources"] = counting
                record = fixtures.hand_record(packet)
                status, counts = review_record._validate_coverage(scope, record)
                self.assertEqual("all_declared_reviewed", status)
                self.assertEqual(size, counts["total"])
                self.assertEqual(1, counting.iterations)

    def test_n11_each_digest_is_read_once_per_check(self) -> None:
        shared = b"value = 1\n"
        packet = fixtures.hand_packet(
            self.root,
            sources=[
                {
                    "name": "a",
                    "path": "src/a.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": shared,
                },
                {
                    "name": "b",
                    "path": "src/b.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": shared,
                },
                {
                    "name": "c",
                    "path": "src/c.py",
                    "origin": "worktree",
                    "availability": "text",
                    "payload": b"other = 2\n",
                },
            ],
            items=[
                {"layer": "worktree", "status": "A", "path": "src/a.py", "after": "a"},
                {"layer": "worktree", "status": "A", "path": "src/b.py", "after": "b"},
                {"layer": "worktree", "status": "A", "path": "src/c.py", "after": "c"},
            ],
        )
        record = fixtures.hand_record(
            packet,
            findings=[
                fixtures.finding(
                    packet,
                    evidence_entries=[
                        fixtures.evidence(packet, snippet="value = 1", source_name="a"),
                        fixtures.evidence(packet, snippet="value = 1", source_name="b"),
                        fixtures.evidence(packet, snippet="other = 2", source_name="c"),
                        fixtures.evidence(packet, snippet="value = 1", source_name="a"),
                    ],
                )
            ],
        )
        with mock.patch.object(
            review_record, "read_source", side_effect=review_record.read_source
        ) as read:
            validation = self.validate(packet, record)
            self.assertEqual(2, len(read.call_args_list))
            self.assertEqual(4, len(validation["anchors"]))
            self.assertEqual(
                ["resolved"] * 4, [anchor["status"] for anchor in validation["anchors"]]
            )
            self.assertEqual(
                [0, 1, 2, 3], [anchor["evidence_index"] for anchor in validation["anchors"]]
            )
            with self.subTest("N11 no cross-call caching"):
                self.validate(packet, record)
                self.assertEqual(4, len(read.call_args_list))
        with self.subTest("N11 an unreferenced corrupt object is still rejected"):
            broken = fixtures.hand_packet(
                self.root,
                sources=[
                    {
                        "name": "kept",
                        "path": "src/kept.py",
                        "origin": "worktree",
                        "availability": "text",
                        "payload": b"kept = 1\n",
                    },
                    {
                        "name": "broken",
                        "path": "src/broken.py",
                        "origin": "worktree",
                        "availability": "text",
                        "payload": b"broken = 1\n",
                    },
                ],
                items=[
                    {
                        "layer": "worktree",
                        "status": "A",
                        "path": "src/kept.py",
                        "after": "kept",
                    },
                    {
                        "layer": "worktree",
                        "status": "A",
                        "path": "src/broken.py",
                        "after": "broken",
                    },
                ],
                packet_name="n11-broken",
            )
            broken_source = next(
                source
                for source in broken["scope"]["sources"]
                if source["path"] == "src/broken.py"
            )
            blob = broken["packet"] / "objects" / f"{broken_source['sha256'][7:]}.blob"
            blob.write_bytes(b"tampered = 1\n")
            broken_record = fixtures.hand_record(
                broken,
                findings=[
                    fixtures.finding(
                        broken,
                        evidence_entries=[
                            fixtures.evidence(broken, snippet="kept = 1", source_name="kept")
                        ],
                    )
                ],
            )
            with self.assertRaises(review_record.ReviewError) as caught:
                self.validate(broken, broken_record)
            self.assertEqual("E_SOURCE_OBJECT", caught.exception.code)

    def test_n12_location_stops_after_two_matches(self) -> None:
        repeated = b"dup = 1\n" * 5
        packet = fixtures.anchor_packet(self.root, repeated)
        record = fixtures.hand_record(
            packet,
            findings=[
                fixtures.finding(
                    packet,
                    evidence_entries=[fixtures.evidence(packet, snippet="dup = 1")],
                )
            ],
        )
        validation = self.validate(packet, record)
        self.assertEqual("ambiguous", validation["anchors"][0]["status"])
        lines = review_record.split_lines(repeated)
        self.assertEqual(2, len(review_record._find_matches(lines, [b"dup = 1"])))
        with self.subTest("N12 a given coordinate wins over repeats"):
            located = fixtures.hand_record(
                packet,
                findings=[
                    fixtures.finding(
                        packet,
                        evidence_entries=[
                            fixtures.evidence(packet, snippet="dup = 1", start_line=4, end_line=4)
                        ],
                    )
                ],
            )
            anchor = self.validate(packet, located)["anchors"][0]
            self.assertEqual("resolved", anchor["status"])
            self.assertEqual(4, anchor["start_line"])
        with self.subTest("N12 counting keeps the byte semantics"):
            payloads = [
                b"",
                b"\n",
                b"\n\n",
                b"single",
                b"single\n",
                b"a\r\nb\r\n",
                b"a\r\nb",
                b"a\rb\n",
                b"-1\n  indented\n\nvalue = 1\rmid\n\xe2\x80\xa8text\n",
                b"\xff\xfe bytes\n",
            ]
            for raw in payloads:
                self.assertEqual(len(review_record.split_lines(raw)), review_record.count_lines(raw))


if __name__ == "__main__":
    unittest.main()
