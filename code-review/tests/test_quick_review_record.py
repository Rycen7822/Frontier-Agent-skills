"""R1-R7: record semantics, references, captured objects, and location states."""

from __future__ import annotations

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
from _review_fixtures import (  # noqa: E402
    concern, coverage, coverage_entry, evidence, finding, hand_record, item,
    report_for, symlink_source, text_source, validate, verification)

REPORT_KEYS = {"schema_version", "validation", "coverage_status", "freshness", "finding_count",
    "concern_count", "item_counts", "anchors", "problems", "limitations", "exit_code"}


class QuickReviewRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def packet(self, name, sources, items, **extra):
        return fixtures.hand_packet(self.root, sources, items, name=name, **extra)

    def module_packet(self, name, payload=b"value = 1\n", **extra):
        return self.packet(name, [text_source("main", "src/module.py", payload)],
            [item("worktree", "A", "src/module.py", after="main")], **extra)

    def located(self, name, evidence_fields, payload=b"value = 1\n"):
        """One packet whose single finding carries the given evidence fields."""
        view = self.module_packet(name, payload)
        entry = evidence(view, path="src/module.py", **evidence_fields)
        return view, hand_record(view, findings=[finding(view, [entry])])

    def two_item_packet(self, name):
        return self.packet(
            name,
            [text_source("main", "a.py", b"a = 1\n"), text_source("other", "b.py", b"b = 1\n")],
            [item("worktree", "A", "a.py", after="main"),
             item("worktree", "A", "b.py", after="other")],
        )

    def test_r1_a_valid_record_is_valid_and_never_a_verdict(self) -> None:
        with self.subTest("plain record without findings"):
            view = self.module_packet("r1-plain")
            report = report_for(view, hand_record(view))
            self.assertEqual("valid", report["validation"])
            self.assertEqual("all_declared_reviewed", report["coverage_status"])
            self.assertEqual((0, 0), (report["exit_code"], report["finding_count"]))
            self.assertEqual(REPORT_KEYS, set(report))
        with self.subTest("critical finding stays structurally valid"):
            view = self.module_packet("r1-critical")
            entry = evidence(view, path="src/module.py", snippet="value = 1",
                             start_line=1, end_line=1)
            report = report_for(
                view, hand_record(view, findings=[finding(view, [entry], severity="critical")]))
            self.assertEqual("valid", report["validation"])
            self.assertEqual(1, report["finding_count"])
            self.assertEqual(("resolved", 0), (report["anchors"][0]["status"], report["exit_code"]))
        with self.subTest("empty scope holds no findings"):
            view = self.packet("r1-empty", [], [])
            report = report_for(view, hand_record(view))
            self.assertEqual("nothing_in_scope", report["coverage_status"])
            self.assertEqual((0, 0), (report["item_counts"]["total"], report["exit_code"]))

    def test_r2_coverage_and_reference_errors(self) -> None:
        unknown_evidence = {"source_id": "S-000009", "start_line": None,
                            "end_line": None, "snippet": "a"}
        cases = [
            ("missing coverage", lambda view: {"coverage": coverage(view)[:1]},
             "E_COVERAGE_MISSING"),
            ("duplicate coverage",
             lambda view: {"coverage": [*coverage(view), coverage(view)[0]]},
             "E_COVERAGE_DUPLICATE"),
            ("unknown coverage item",
             lambda view: {"coverage": [coverage_entry("I-000009", "reviewed")]},
             "E_COVERAGE_UNKNOWN"),
            ("unknown item in a finding",
             lambda view: {"findings": [finding(
                 view, [evidence(view, path="a.py", snippet="a = 1")],
                 item_ids=["I-000009"])]},
             "E_REFERENCE_UNKNOWN"),
            ("unknown source in evidence",
             lambda view: {"findings": [finding(view, [unknown_evidence])]}, "E_REFERENCE_UNKNOWN"),
            ("duplicate finding id",
             lambda view: {
                 "findings": [finding(view, [evidence(view, path="a.py", snippet="a = 1")]),
                              finding(view, [evidence(view, path="b.py", snippet="b = 1")])],
             },
             "E_DUPLICATE_ID"),
            ("duplicate concern id",
             lambda view: {"concerns": [concern(view), concern(view)]}, "E_DUPLICATE_ID"),
        ]
        for index, (label, changes, code) in enumerate(cases):
            with self.subTest(label):
                view = self.two_item_packet(f"r2-{index}")
                with self.assertRaises(review_record.ReviewError) as caught:
                    validate(view, {**hand_record(view), **changes(view)})
                self.assertEqual(code, caught.exception.code)

    def test_r3_input_and_object_binding(self) -> None:
        def r3_packet(name):
            return self.packet(name, [text_source("main", "src/module.py", b"value = 1\n"),
                 text_source("side", "src/other.py", b"other = 1\n")],
                [item("worktree", "A", "src/module.py", after="main")])

        def blob_path(view, source) -> Path:
            return view["packet"] / "objects" / (source["sha256"][7:] + ".blob")

        with self.subTest("record digest must match the scope bytes"):
            view = r3_packet("r3-digest")
            with self.assertRaises(review_record.ReviewError) as caught:
                validate(view, {**hand_record(view), "scope_sha256": "sha256:" + "0" * 64})
            self.assertEqual("E_SCOPE_DIGEST", caught.exception.code)
        with self.subTest("a referenced object is verified"):
            view = r3_packet("r3-object")
            blob_path(view, view["scope"]["sources"][0]).write_bytes(b"value = 2\n")
            with self.assertRaises(review_record.ReviewError) as caught:
                validate(view, hand_record(view))
            self.assertEqual("E_SOURCE_OBJECT", caught.exception.code)
        with self.subTest("an object no finding references is verified too"):
            view = r3_packet("r3-unreferenced")
            unreferenced = view["scope"]["sources"][1]
            referenced = [entry["after"] for entry in view["scope"]["items"]]
            self.assertNotIn(unreferenced["id"], referenced)
            blob_path(view, unreferenced).write_bytes(b"tampered\n")
            with self.assertRaises(review_record.ReviewError) as caught:
                validate(view, hand_record(view))
            self.assertEqual("E_SOURCE_OBJECT", caught.exception.code)

    def test_r4_anchor_location_status(self) -> None:
        payload = b"one\ntwo\nthree\ntwo\n"
        cases = [("exact coordinates", {"snippet": "three", "start_line": 3, "end_line": 3},
             "resolved", (3, 3), (None, None)),
            ("unique hit without coordinates", {"snippet": "three"}, "resolved", (3, 3),
             (None, None)),
            ("repeated text without coordinates", {"snippet": "two"}, "ambiguous",
             (None, None), (None, None)),
            ("wrong coordinates relocate", {"snippet": "three", "start_line": 1, "end_line": 1},
             "needs_relocation", (1, 1), (3, 3)),
            ("range beyond the source", {"snippet": "three", "start_line": 9, "end_line": 10},
             "E_LOCATION_RANGE", (None, None), (None, None))]
        for index, (label, fields, expected, span, candidate) in enumerate(cases):
            with self.subTest(label):
                view, record = self.located(f"r4-{index}", fields, payload)
                if expected.startswith("E_"):
                    with self.assertRaises(review_record.ReviewError) as caught:
                        validate(view, record)
                    self.assertEqual(expected, caught.exception.code)
                    continue
                anchor = validate(view, record)["anchors"][0]
                self.assertEqual(expected, anchor["status"])
                self.assertEqual(span, (anchor["start_line"], anchor["end_line"]))
                self.assertEqual(candidate, (anchor["candidate_start"], anchor["candidate_end"]))

    def test_r5_raw_line_semantics(self) -> None:
        cases = [("CRLF source and snippet", b"alpha\r\nbeta\r\n", "beta\r\n", "resolved", (2, 2)),
            ("sign column stays part of the line", b"-old\n+new\n", "+new", "resolved", (2, 2)),
            ("indented block", b"if x:\n    run()\n", "    run()", "resolved", (2, 2)),
            ("empty source", b"", "anything", "unlocated", (None, None)),
            ("final line without a break", b"tail", "tail", "resolved", (1, 1))]
        for index, (label, payload, snippet, expected, span) in enumerate(cases):
            with self.subTest(label):
                view, record = self.located(f"r5-{index}", {"snippet": snippet}, payload)
                anchor = validate(view, record)["anchors"][0]
                self.assertEqual(expected, anchor["status"])
                self.assertEqual(span, (anchor["start_line"], anchor["end_line"]))

    def test_r6_shared_digest_keeps_each_source_availability(self) -> None:
        payload = b"target"
        cases = [("text source sorts first", "a-text.py", "z-link"),
                 ("symlink source sorts first", "z-text.py", "a-link")]
        for index, (label, text_path, link_path) in enumerate(cases):
            with self.subTest(label):
                pairs = sorted([("text", text_path), ("link", link_path)], key=lambda pair: pair[1])
                sources = [text_source("text", path, payload) if name == "text"
                           else symlink_source("link", path, payload) for name, path in pairs]
                view = self.packet(f"r6-{index}", sources,
                                   [item("worktree", "A", path, after=name)
                                    for name, path in pairs])
                by_path = {entry["path"]: entry["id"] for entry in view["scope"]["items"]}
                record = hand_record(view,
                    coverage_entries=[coverage_entry(by_path[text_path], "reviewed"),
                                      coverage_entry(by_path[link_path], "not_reviewed",
                                                     "the link target is out of scope")],
                    findings=[finding(view, [evidence(view, path=text_path, snippet="target"),
                                             evidence(view, path=link_path, snippet="target")])])
                report = report_for(view, record)
                self.assertEqual("valid", report["validation"])
                self.assertEqual(("partial", 4, []),
                                 (report["coverage_status"], report["exit_code"],
                                  report["problems"]))
                self.assertEqual([("resolved", 1, 1), ("unsupported_source", None, None)],
                    [(a["status"], a["start_line"], a["end_line"]) for a in report["anchors"]])

    def test_r7_partial_results_and_merged_limitations(self) -> None:
        def report_of(name, **record_fields):
            view = self.module_packet(name)
            return report_for(view, hand_record(view, **record_fields))

        with self.subTest("partial coverage"):
            view = self.module_packet("r7-partial")
            report = report_for(view, hand_record(view, coverage_entries=coverage(view, "partial")))
            self.assertEqual(("partial", 4), (report["coverage_status"], report["exit_code"]))
            self.assertEqual(1, report["item_counts"]["partial"])
        with self.subTest("open concern"):
            view = self.module_packet("r7-concern")
            report = report_for(view, hand_record(view, concerns=[concern(view)]))
            self.assertEqual((1, 4), (report["concern_count"], report["exit_code"]))
        with self.subTest("failed verification"):
            report = report_of("r7-failed", verification_entries=[verification(status="failed")])
            self.assertEqual(4, report["exit_code"])
        with self.subTest("not_run verification is not a failed run"):
            report = report_of("r7-not-run", verification_entries=[verification(status="not_run")])
            self.assertEqual(0, report["exit_code"])
        with self.subTest("scope and record limitations merge in order"):
            view = self.module_packet("r7-limits", limitations=["scope note", "shared note"])
            record = hand_record(view, limitations=["record note", "shared note"])
            self.assertEqual(["scope note", "shared note", "record note"],
                             report_for(view, record)["limitations"])
