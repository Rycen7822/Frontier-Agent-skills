"""G1-G8: real Git capture for the four scopes, freshness, and capture limits."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
for path in (str(TESTS_DIR), str(TESTS_DIR.parent / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

import _review_fixtures as fixtures  # noqa: E402
import _review_git as review_git  # noqa: E402
import _review_record as review_record  # noqa: E402
from _review_fixtures import (  # noqa: E402
    commit, digest, git, hand_record, items_of, objects_of, packet_view, payload_of,
    scope_of, sources_of, write, write_json)


class ExtendedReviewScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = fixtures.init_repo(self.root)

    def output(self, name: str) -> Path:
        return self.root / name

    def capture(self, name: str, *extra: str, mode: str = "workspace", repo: Path | None = None):
        return fixtures.scope_cli(repo or self.repo, self.output(name), "--mode", mode, *extra)

    def record_for(self, packet: Path, name: str = "record.json") -> Path:
        return write_json(self.output(name), hand_record(packet_view(packet)))

    def test_g1_commit_scope_layers_and_root_commit(self) -> None:
        first = commit(self.repo, {"src/app.py": "value = 1\n",
                "tests/test_app.py": "def test_app():\n    assert True\n",
                "docs/notes.md": "# notes\n", "package.json": '{"name": "demo"}\n',
                "generated/schema.json": '{"generated": true}\n'})
        second = commit(self.repo, {"src/app.py": "value = 2\n", "docs/notes.md": None,
                "config/runtime.yaml": "limit: 32\n"})
        with self.subTest("the root commit has no synthetic base"):
            code, payload, packet = self.capture(
                "g1-root", "--commit", first, "--path", ".", mode="commit"
            )
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            self.assertIsNone(scope["resolved"]["base_oid"])
            self.assertEqual(first, scope["resolved"]["head_oid"])
            items = items_of(scope)
            self.assertEqual(5, len(items))
            self.assertEqual({"A"}, {item["status"] for item in items.values()})
            self.assertLessEqual({("commit", "docs/notes.md"), ("commit", "tests/test_app.py"),
                 ("commit", "generated/schema.json")}, set(items))
        with self.subTest("a later commit compares against its first parent"):
            code, payload, packet = self.capture(
                "g1-head", "--commit", second, "--path", ".", mode="commit"
            )
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            items = items_of(scope)
            sources = sources_of(scope)
            # Commit mode always records head_oid alone; the parent stays the diff base.
            self.assertIsNone(scope["resolved"]["base_oid"])
            self.assertIsNone(scope["resolved"]["comparison_base_oid"])
            self.assertEqual(second, scope["resolved"]["head_oid"])
            self.assertEqual("M", items[("commit", "src/app.py")]["status"])
            self.assertEqual("D", items[("commit", "docs/notes.md")]["status"])
            self.assertEqual("A", items[("commit", "config/runtime.yaml")]["status"])
            self.assertEqual(b"# notes\n",
                payload_of(packet, sources[items[("commit", "docs/notes.md")]["before"]]))
            self.assertEqual(b"value = 2\n",
                payload_of(packet, sources[items[("commit", "src/app.py")]["after"]]))

    def test_g2_range_uses_the_merge_base_and_freezes_sources(self) -> None:
        base = commit(self.repo, {"src/app.py": "value = 1\n"})
        git(self.repo, "checkout", "-q", "-b", "topic")
        topic = commit(self.repo, {"src/app.py": "value = 2\n", "src/topic.py": "topic = 1\n"})
        git(self.repo, "checkout", "-q", "main")
        commit(self.repo, {"src/main.py": "main = 1\n"})
        with self.subTest("the merge base is the left endpoint, not the branch tip"):
            code, payload, packet = self.capture(
                "g2", "--base", "main", "--head", "topic", "--path", ".", mode="range"
            )
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            self.assertEqual(base, scope["resolved"]["comparison_base_oid"])
            self.assertEqual(topic, scope["resolved"]["head_oid"])
            self.assertEqual({"src/app.py", "src/topic.py"}, {path for _, path in items_of(scope)},)
        with self.subTest("a moved ref does not change captured sources"):
            captured = (packet / "scope.json").read_bytes()
            record = self.record_for(packet, "g2-record.json")
            git(self.repo, "checkout", "-q", "topic")
            moved = commit(self.repo, {"src/topic.py": "topic = 2\n"})
            self.assertNotEqual(topic, moved)
            code, payload, _ = fixtures.check_cli(
                self.repo, packet, record, self.output("g2-report.json"))
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", payload["freshness"])
            self.assertEqual(captured, (packet / "scope.json").read_bytes())
        with self.subTest("two merge bases are rejected"):
            criss = fixtures.init_repo(self.root, name="criss-cross")
            commit(criss, {"f.py": "base\n"})
            git(criss, "checkout", "-q", "-b", "left")
            left_tip = commit(criss, {"left.py": "left\n"})
            git(criss, "checkout", "-q", "-b", "right", "main")
            commit(criss, {"right.py": "right\n"})
            git(criss, "checkout", "-q", "left")
            git(criss, "merge", "-q", "--no-edit", "--no-ff", "right")
            git(criss, "checkout", "-q", "right")
            git(criss, "merge", "-q", "--no-edit", "--no-ff", left_tip)
            code, payload, output = self.capture(
                "g2-criss", "--base", "left", "--head", "right", "--path", ".",
                mode="range", repo=criss
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_AMBIGUOUS_MERGE_BASE", payload["code"])
            self.assertFalse(output.exists())

    def test_g3_workspace_layers_stay_separate(self) -> None:
        commit(self.repo, {"src/module.py": "value = 1\n"})
        with self.subTest("staged and then modified again"):
            write(self.repo, "src/module.py", "value = 2\n")
            git(self.repo, "add", "src/module.py")
            write(self.repo, "src/module.py", "value = 3\n")
            code, payload, packet = self.capture("g3-layers", "--path", "src/module.py")
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            items = items_of(scope)
            sources = sources_of(scope)
            index_source = sources[items[("index", "src/module.py")]["after"]]
            worktree_source = sources[items[("worktree", "src/module.py")]["after"]]
            self.assertNotEqual(index_source["id"], worktree_source["id"])
            self.assertEqual(("index", "worktree"),
                             (index_source["origin"], worktree_source["origin"]))
            self.assertEqual(b"value = 2\n", payload_of(packet, index_source))
            self.assertEqual(b"value = 3\n", payload_of(packet, worktree_source))
        with self.subTest("a staged deletion plus an untracked rebuild"):
            commit(self.repo, {"src/gone.py": "gone = 1\n"})
            git(self.repo, "rm", "-q", "-f", "src/gone.py")
            write(self.repo, "src/gone.py", "rebuilt = 1\n")
            code, payload, packet = self.capture("g3-rebuild", "--path", "src/gone.py")
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            items = items_of(scope)
            sources = sources_of(scope)
            self.assertEqual("D", items[("index", "src/gone.py")]["status"])
            self.assertEqual("A", items[("untracked", "src/gone.py")]["status"])
            self.assertEqual(b"rebuilt = 1\n",
                payload_of(packet, sources[items[("untracked", "src/gone.py")]["after"]]))
        with self.subTest("an unborn HEAD still captures staged and untracked files"):
            fresh = fixtures.init_repo(self.root, name="unborn")
            write(fresh, "staged.py", "staged = 1\n")
            git(fresh, "add", "staged.py")
            write(fresh, "loose.py", "loose = 1\n")
            code, payload, packet = self.capture("g3-unborn", "--path", ".", repo=fresh)
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            self.assertIsNone(scope["resolved"]["head_oid"])
            items = items_of(scope)
            sources = sources_of(scope)
            self.assertEqual("A", items[("index", "staged.py")]["status"])
            self.assertEqual("A", items[("untracked", "loose.py")]["status"])
            self.assertEqual(b"loose = 1\n",
                payload_of(packet, sources[items[("untracked", "loose.py")]["after"]]))

    def test_g4_snapshot_commit_and_worktree_sources(self) -> None:
        first = commit(self.repo, {"src/module.py": "value = 1\n"})
        write(self.repo, "src/module.py", "value = 2\n")
        with self.subTest("a commit snapshot reads the frozen commit"):
            code, payload, packet = self.capture(
                "g4-commit", "--revision", first, "--path", "src/module.py", mode="snapshot"
            )
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            self.assertEqual("immutable_commits", scope["observation"])
            item = items_of(scope)[("snapshot", "src/module.py")]
            source = sources_of(scope)[item["after"]]
            self.assertIsNone(item["before"])
            self.assertEqual("P", item["status"])
            self.assertEqual(("git", first), (source["origin"], source["revision"]))
            self.assertEqual(b"value = 1\n", payload_of(packet, source))
        with self.subTest("a WORKTREE snapshot reads the working tree"):
            code, payload, packet = self.capture(
                "g4-worktree", "--revision", "WORKTREE", "--path", "src/module.py", mode="snapshot"
            )
            self.assertEqual(0, code, payload)
            scope = scope_of(packet)
            self.assertEqual("bounded_double_observation", scope["observation"])
            item = items_of(scope)[("snapshot", "src/module.py")]
            source = sources_of(scope)[item["after"]]
            self.assertEqual("worktree", source["origin"])
            self.assertEqual(b"value = 2\n", payload_of(packet, source))

    def test_g5_context_and_freshness(self) -> None:
        commit(self.repo,
            {"src/module.py": "value = 1\n", "config.py": "LIMIT = 1\n",
             "docs/readme.md": "docs\n"},
        )
        write(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.capture(
            "g5", "--path", "src", "--context-path", "./config.py")
        self.assertEqual(0, code, payload)
        scope = scope_of(packet)
        self.assertEqual(["config.py"], scope["request"]["context_paths"])
        self.assertEqual({"src/module.py"}, {item["path"] for item in scope["items"]})
        self.assertIn("config.py", {source["path"] for source in scope["sources"]})
        record = self.record_for(packet, "g5-record.json")

        def check(name: str, repo: Path | None = None):
            report = self.output(name)
            got = fixtures.check_cli(repo or self.repo, packet, record, report)
            return got[0], got[1], json.loads(report.read_text(encoding="utf-8"))

        with self.subTest("the captured inputs still match"):
            code, payload, written = check("g5-match.json")
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", written["freshness"]["status"])
        with self.subTest("changed context bytes"):
            write(self.repo, "config.py", "LIMIT = 2\n")
            code, payload, written = check("g5-context.json")
            self.assertEqual(4, code, payload)
            self.assertEqual(["config.py"], written["freshness"]["changed_paths"])
            write(self.repo, "config.py", "LIMIT = 1\n")
        with self.subTest("an index-only change"):
            write(self.repo, "config.py", "LIMIT = 3\n")
            git(self.repo, "add", "config.py")
            write(self.repo, "config.py", "LIMIT = 1\n")
            code, payload, written = check("g5-index.json")
            self.assertEqual(4, code, payload)
            self.assertIn("config.py", written["freshness"]["changed_paths"])
            git(self.repo, "restore", "--staged", "config.py")
        with self.subTest("a new relevant entry"):
            write(self.repo, "src/added.py", "added = 1\n")
            code, payload, written = check("g5-added.json")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", written["freshness"]["status"])
            (self.repo / "src" / "added.py").unlink()
        with self.subTest("an unrelated change stays a match"):
            write(self.repo, "docs/readme.md", "updated docs\n")
            code, payload, written = check("g5-unrelated.json")
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", written["freshness"]["status"])

    def test_g6_capture_limits_and_dedupe_budget(self) -> None:
        with self.subTest("binary and oversized objects stay partial"):
            commit(self.repo, {"bin.dat": b"\x00\x01binary\n"})
            write(self.repo, "bin.dat", b"\x00\x02binary\n")
            oversized = b"x" * (review_record.MAX_FILE_BYTES + 1)
            write(self.repo, "big.txt", oversized)
            code, payload, packet = self.capture("g6-limits", "--path", ".")
            self.assertEqual(4, code, payload)
            self.assertEqual(4, payload["exit_code"])
            scope = scope_of(packet)
            sources = {source["path"]: source for source in scope["sources"]}
            binary_sources = [source for source in scope["sources"] if source["path"] == "bin.dat"]
            self.assertEqual(2, len(binary_sources))
            self.assertEqual({"binary"}, {source["availability"] for source in binary_sources})
            self.assertEqual(b"\x00\x02binary\n", payload_of(packet, sources["bin.dat"]),)
            self.assertEqual("too_large", sources["big.txt"]["availability"])
            self.assertIsNone(sources["big.txt"]["sha256"])
            self.assertEqual(len(oversized), sources["big.txt"]["size_bytes"])
            captured = objects_of(packet)
            self.assertEqual({source["sha256"][7:] + ".blob" for source in binary_sources},
                set(captured))
            self.assertTrue(all(len(raw) < review_record.MAX_FILE_BYTES
                                for raw in captured.values()))
            self.assertTrue(any("big.txt" in note for note in payload["limitations"]))
        with self.subTest("the budget counts deduplicated new bytes"):
            repo = fixtures.init_repo(self.root, name="budget")
            write(repo, "a.txt", b"A" * 30)
            write(repo, "b.txt", b"A" * 30)
            write(repo, "c.txt", b"C" * 20)
            with mock.patch.object(review_git, "MAX_PACKET_BYTES", 40):
                code, payload, packet = self.capture("g6-budget", "--path", ".", repo=repo)
            self.assertEqual(4, code, payload)
            scope = scope_of(packet)
            sources = {source["path"]: source for source in scope["sources"]}
            self.assertEqual(sources["a.txt"]["sha256"], sources["b.txt"]["sha256"])
            self.assertEqual("budget_exhausted", sources["c.txt"]["availability"])
            self.assertIsNone(sources["c.txt"]["sha256"])
            self.assertEqual({sources["a.txt"]["sha256"]},
                             {digest(raw) for raw in objects_of(packet).values()})
            self.assertTrue(
                any("budget" in note for note in payload["limitations"]), payload["limitations"])

    def test_g7_read_only_rejections(self) -> None:
        def fingerprint(repo: Path) -> dict:
            return {"staged": git(repo, "ls-files", "--stage", "-z").stdout,
                "status": git(repo, "status", "--porcelain=v1").stdout,
                "config": git(repo, "config", "--list").stdout}

        with self.subTest("an unmerged index"):
            repo = fixtures.init_repo(self.root, name="unmerged")
            commit(repo, {"shared.py": "value = 1\n"})
            git(repo, "checkout", "-q", "-b", "side")
            commit(repo, {"shared.py": "side = 1\n"})
            git(repo, "checkout", "-q", "main")
            commit(repo, {"shared.py": "main = 1\n"})
            merge = git(repo, "merge", "side", check=False)
            self.assertNotEqual(0, merge.returncode)
            before = fingerprint(repo)
            output = self.output("g7-unmerged")
            code, payload, _ = self.capture("g7-unmerged", "--path", ".", repo=repo)
            self.assertEqual(2, code, payload)
            self.assertEqual("E_UNMERGED", payload["code"])
            self.assertFalse((output / "scope.json").exists())
            self.assertEqual(before, fingerprint(repo))
        with self.subTest("a promisor remote marker"):
            repo = fixtures.init_repo(self.root, name="promisor")
            commit(repo, {"a.py": "a = 1\n"})
            git(repo, "config", "remote.origin.promisor", "true")
            output = self.output("g7-promisor")
            code, payload, _ = self.capture("g7-promisor", "--path", ".", repo=repo)
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PARTIAL_CLONE", payload["code"])
            self.assertFalse(output.exists())
            marker = git(repo, "config", "remote.origin.promisor").stdout.decode().strip()
            self.assertEqual("true", marker)
        with self.subTest("a symlinked parent component"):
            repo = fixtures.init_repo(self.root, name="symlink-parent")
            commit(repo, {"pkg/mod.py": "x = 1\n"})
            outside = self.root / "outside-pkg"
            (repo / "pkg").rename(outside)
            os.symlink(str(outside), repo / "pkg")
            before = fingerprint(repo)
            with self.assertRaises(review_git.ReviewError) as caught:
                review_git._read_disk(repo, "pkg/mod.py")
            self.assertEqual("E_PARENT_SYMLINK", caught.exception.code)
            self.assertEqual(before, fingerprint(repo))

    def test_g8_unstable_capture_and_publish(self) -> None:
        commit(self.repo, {"src/module.py": "value = 1\n", "config.py": "LIMIT = 1\n"})
        write(self.repo, "src/module.py", "value = 2\n")
        with self.subTest("a context change during capture is reported"):
            original = review_git._read_disk

            def changing(root: Path, relative: str) -> dict:
                detail = original(root, relative)
                if relative == "config.py":
                    write(root, "config.py", "LIMIT = 2\n")
                return detail

            output = self.output("g8-changing")
            with mock.patch.object(review_git, "_read_disk", changing):
                code, payload, _ = fixtures.scope_cli(self.repo, output, "--mode", "workspace",
                    "--path", "src/module.py", "--context-path", "config.py")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_SOURCE_CHANGED_DURING_CAPTURE", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("a failing publish leaves no scope.json"):
            write(self.repo, "config.py", "LIMIT = 1\n")
            output = self.output("g8-publish")

            def failing_link(source: str, target: str) -> None:
                raise OSError(errno.ENOSPC, "no space left on device")

            with mock.patch.object(os, "link", failing_link):
                code, payload, _ = self.capture("g8-publish", "--path", "src/module.py")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertFalse((output / "scope.json").exists())
            # The packet directory may hold captured objects, never the completion marker.
            self.assertEqual(["objects"], sorted(path.name for path in output.iterdir()))
