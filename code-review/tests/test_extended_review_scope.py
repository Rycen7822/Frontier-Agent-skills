"""G01-G23: real Git fixtures for scope capture, layering, limits, and freshness."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
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
import _review_git as review_git  # noqa: E402
import _review_record as review_record  # noqa: E402


class ExtendedReviewScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = fixtures.init_repo(self.root)
        self._counter = 0

    def packet_dir(self, name: str = "packet") -> Path:
        self._counter += 1
        return self.root / f"{name}-{self._counter}"

    def scope(self, *args: str):
        output = self.packet_dir()
        code, payload = fixtures.run_cli(
            ["scope", "--repo", str(self.repo), *args, "--output", str(output)]
        )
        return code, payload, output

    def read_scope(self, packet: Path) -> dict:
        return json.loads((packet / "scope.json").read_text(encoding="utf-8"))

    def items_by_path(self, scope: dict) -> dict[tuple[str, str], dict]:
        return {(item["layer"], item["path"]): item for item in scope["items"]}

    def sources_by_path(self, scope: dict) -> dict[tuple[str, str, str], dict]:
        return {
            (source["origin"], source["path"], source["revision"] or ""): source
            for source in scope["sources"]
        }

    def blob_bytes(self, packet: Path, source: dict) -> bytes:
        return (packet / "objects" / f"{source['sha256'][7:]}.blob").read_bytes()

    def test_g01_single_commit_add_modify_delete(self) -> None:
        first = fixtures.commit_files(self.repo, {"a.py": "a = 1\n", "c.py": "c = 3\n"})
        second = fixtures.commit_files(
            self.repo, {"a.py": "a = 2\n", "b.py": "b = 5\n", "c.py": None}
        )
        code, payload, packet = self.scope("--mode", "commit", "--commit", second, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        items = self.items_by_path(scope)
        self.assertEqual(
            {("commit", "a.py"), ("commit", "b.py"), ("commit", "c.py")}, set(items)
        )
        sources = {source["id"]: source for source in scope["sources"]}
        modified = items[("commit", "a.py")]
        self.assertEqual("M", modified["status"])
        self.assertEqual(b"a = 1\n", self.blob_bytes(packet, sources[modified["before"]]))
        self.assertEqual(b"a = 2\n", self.blob_bytes(packet, sources[modified["after"]]))
        self.assertEqual(first, sources[modified["before"]]["revision"])
        deleted = items[("commit", "c.py")]
        self.assertEqual("D", deleted["status"])
        self.assertIsNone(deleted["after"])
        self.assertEqual(b"c = 3\n", self.blob_bytes(packet, sources[deleted["before"]]))
        self.assertEqual(first, sources[deleted["before"]]["revision"])

    def test_g02_root_commit_has_no_synthetic_empty_tree(self) -> None:
        root_commit = fixtures.commit_files(self.repo, {"a.py": "a = 1\n", "d/x.py": "x\n"})
        before = self._object_files()
        code, payload, packet = self.scope("--mode", "commit", "--commit", root_commit, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual(2, len(scope["items"]))
        for item in scope["items"]:
            self.assertEqual("A", item["status"])
            self.assertIsNone(item["before"])
        for source in scope["sources"]:
            self.assertEqual(root_commit, source["revision"])
        self.assertEqual(before, self._object_files())

    def _object_files(self) -> set[str]:
        objects = self.repo / ".git" / "objects"
        return {
            str(path.relative_to(objects))
            for path in objects.rglob("*")
            if path.is_file()
        }

    def test_g03_merge_commit_uses_first_parent_only(self) -> None:
        base = fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.git(self.repo, "checkout", "-q", "-b", "feature", base)
        feature = fixtures.commit_files(self.repo, {"b.py": "b = 1\n"})
        fixtures.git(self.repo, "checkout", "-q", "main")
        fixtures.git(self.repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
        merge_oid = fixtures.head_oid(self.repo)
        code, payload, packet = self.scope("--mode", "commit", "--commit", merge_oid, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual({("commit", "b.py")}, set(self.items_by_path(scope)))
        raw = fixtures.git(
            self.repo,
            "diff",
            "--raw",
            "-z",
            "--no-abbrev",
            "--no-renames",
            base,
            merge_oid,
        ).stdout
        self.assertEqual([b"b.py"], self._raw_diff_paths(raw))
        self.assertEqual(feature, fixtures.head_oid(self.repo, "feature"))

    def test_g04_range_uses_merge_base(self) -> None:
        base = fixtures.commit_files(self.repo, {"shared.py": "shared = 1\n"})
        fixtures.git(self.repo, "checkout", "-q", "-b", "feature", base)
        feature_tip = fixtures.commit_files(self.repo, {"feature.py": "feature = 1\n"})
        fixtures.git(self.repo, "checkout", "-q", "main")
        base_tip = fixtures.commit_files(self.repo, {"landing.py": "landing = 1\n"})
        code, payload, packet = self.scope(
            "--mode", "range", "--base", base_tip, "--head", feature_tip, "--path", "."
        )
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual(base, scope["resolved"]["comparison_base_oid"])
        self.assertEqual(base_tip, scope["resolved"]["base_oid"])
        self.assertEqual({("range", "feature.py")}, set(self.items_by_path(scope)))

    def test_g05_unrelated_and_ambiguous_merge_bases(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        unrelated = fixtures.init_repo(self.root / "second")
        fixtures.commit_files(unrelated, {"z.py": "z = 1\n"})
        code, payload, _ = self.scope(
            "--mode", "range", "--base", "HEAD", "--head", "HEAD", "--path", "."
        )
        self.assertEqual(0, code)
        with self.subTest("G05 no merge base"):
            fixtures.git(self.repo, "checkout", "-q", "--orphan", "orphan")
            fixtures.git(self.repo, "rm", "-q", "-rf", "--cached", ".")
            fixtures.commit_files(self.repo, {"orphan.py": "orphan = 1\n"})
            code, payload = fixtures.run_cli(
                [
                    "scope",
                    "--repo",
                    str(self.repo),
                    "--mode",
                    "range",
                    "--base",
                    "main",
                    "--head",
                    "orphan",
                    "--path",
                    ".",
                    "--output",
                    str(self.packet_dir()),
                ]
            )
            self.assertEqual(2, code)
            self.assertEqual("E_NO_MERGE_BASE", payload["code"])
            fixtures.git(self.repo, "checkout", "-q", "main")
        with self.subTest("G05 ambiguous merge base"):
            root_commit = fixtures.head_oid(self.repo)
            fixtures.git(self.repo, "checkout", "-q", "-b", "x", root_commit)
            fixtures.commit_files(self.repo, {"x.py": "x = 1\n"})
            fixtures.git(self.repo, "checkout", "-q", "-b", "y", root_commit)
            fixtures.commit_files(self.repo, {"y.py": "y = 1\n"})
            fixtures.git(self.repo, "checkout", "-q", "-b", "m1", "x")
            fixtures.git(self.repo, "merge", "-q", "--no-ff", "-m", "m1", "y")
            m1 = fixtures.head_oid(self.repo)
            fixtures.git(self.repo, "checkout", "-q", "-b", "m2", "y")
            fixtures.git(self.repo, "merge", "-q", "--no-ff", "-m", "m2", "x")
            m2 = fixtures.head_oid(self.repo)
            bases = fixtures.git(self.repo, "merge-base", "--all", m1, m2).stdout.split()
            self.assertEqual(2, len(bases))
            code, payload = fixtures.run_cli(
                [
                    "scope",
                    "--repo",
                    str(self.repo),
                    "--mode",
                    "range",
                    "--base",
                    m1,
                    "--head",
                    m2,
                    "--path",
                    ".",
                    "--output",
                    str(self.packet_dir()),
                ]
            )
            self.assertEqual(2, code)
            self.assertEqual("E_AMBIGUOUS_MERGE_BASE", payload["code"])

    def test_g06_frozen_packet_survives_a_moved_branch(self) -> None:
        first = fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        second = fixtures.commit_files(self.repo, {"a.py": "a = 2\n"})
        code, payload, packet = self.scope("--mode", "commit", "--commit", second, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual(second, scope["resolved"]["head_oid"])
        fixtures.git(self.repo, "reset", "-q", "--hard", first)
        self.assertEqual(first, fixtures.head_oid(self.repo))
        self.assertNotEqual(first, scope["resolved"]["head_oid"])
        sources = {source["id"]: source for source in scope["sources"]}
        after = sources[scope["items"][0]["after"]]
        self.assertEqual(second, after["revision"])
        self.assertEqual(b"a = 2\n", self.blob_bytes(packet, after))

    def test_g07_markdown_tests_schema_and_generated_files_are_kept(self) -> None:
        files = {
            "docs/guide.md": "# guide\n",
            "tests/test_x.py": "def test_x():\n    assert True\n",
            "config/schema.json": '{"a": 1}\n',
            "config/runtime.ini": "[runtime]\n",
            "build/generated.py": "# generated\n",
        }
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        head = fixtures.commit_files(self.repo, files)
        code, payload, packet = self.scope("--mode", "commit", "--commit", head, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual(
            {("commit", path) for path in files}, set(self.items_by_path(scope))
        )
        for item in scope["items"]:
            self.assertEqual("A", item["status"])

    def test_g08_staged_then_modified_creates_two_layers(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 2\n")
        fixtures.git(self.repo, "add", "a.py")
        fixtures.write_file(self.repo, "a.py", "a = 3\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        items = self.items_by_path(scope)
        sources = {source["id"]: source for source in scope["sources"]}
        self.assertEqual({("index", "a.py"), ("worktree", "a.py")}, set(items))
        staged = sources[items[("index", "a.py")]["after"]]
        unstaged = sources[items[("worktree", "a.py")]["after"]]
        self.assertEqual(b"a = 2\n", self.blob_bytes(packet, staged))
        self.assertEqual(b"a = 3\n", self.blob_bytes(packet, unstaged))
        self.assertEqual("100644", staged["git_mode"])
        self.assertEqual("index", staged["origin"])
        self.assertNotEqual(staged["sha256"], unstaged["sha256"])

    def test_g09_staged_delete_with_untracked_rebuild(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.git(self.repo, "rm", "-q", "--cached", "a.py")
        fixtures.write_file(self.repo, "a.py", "a = 1\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        items = self.items_by_path(scope)
        self.assertEqual({("index", "a.py"), ("untracked", "a.py")}, set(items))
        self.assertEqual("D", items[("index", "a.py")]["status"])
        self.assertIsNone(items[("index", "a.py")]["after"])
        self.assertEqual("A", items[("untracked", "a.py")]["status"])
        self.assertIsNone(items[("untracked", "a.py")]["before"])

    def test_g10_unborn_head_with_staged_and_untracked_files(self) -> None:
        fixtures.write_file(self.repo, "staged.py", "staged = 1\n")
        fixtures.git(self.repo, "add", "staged.py")
        fixtures.write_file(self.repo, "untracked.py", "untracked = 1\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertIsNone(scope["resolved"]["head_oid"])
        items = self.items_by_path(scope)
        self.assertEqual({("index", "staged.py"), ("untracked", "untracked.py")}, set(items))
        self.assertEqual("A", items[("index", "staged.py")]["status"])
        self.assertIsNone(items[("index", "staged.py")]["before"])
        for source in scope["sources"]:
            self.assertIsNone(source["revision"])

    def test_g11_rename_is_deletion_plus_addition(self) -> None:
        fixtures.commit_files(self.repo, {"old.py": "value = 1\n"})
        fixtures.git(self.repo, "mv", "old.py", "new.py")
        fixtures.git(self.repo, "commit", "-q", "-m", "rename")
        head = fixtures.head_oid(self.repo)
        code, payload, packet = self.scope("--mode", "commit", "--commit", head, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        items = self.items_by_path(scope)
        self.assertEqual({("commit", "new.py"), ("commit", "old.py")}, set(items))
        self.assertEqual("D", items[("commit", "old.py")]["status"])
        self.assertEqual("A", items[("commit", "new.py")]["status"])
        for item in scope["items"]:
            self.assertNotEqual("R", item["status"])

    def test_g12_mode_change_and_regular_to_symlink(self) -> None:
        fixtures.commit_files(self.repo, {"script.sh": "echo hi\n", "plain.txt": "text\n"})
        os.chmod(self.repo / "script.sh", 0o755)
        fixtures.git(self.repo, "add", "script.sh")
        mode_commit = fixtures.commit_files(self.repo, {})
        code, payload, packet = self.scope(
            "--mode", "commit", "--commit", mode_commit, "--path", "script.sh"
        )
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        item = scope["items"][0]
        sources = {source["id"]: source for source in scope["sources"]}
        self.assertEqual("M", item["status"])
        self.assertEqual("100644", sources[item["before"]]["git_mode"])
        self.assertEqual("100755", sources[item["after"]]["git_mode"])
        with self.subTest("G12 regular to symlink"):
            (self.repo / "plain.txt").unlink()
            os.symlink("script.sh", self.repo / "plain.txt")
            fixtures.git(self.repo, "add", "plain.txt")
            fixtures.git(self.repo, "commit", "-q", "-m", "symlink")
            head = fixtures.head_oid(self.repo)
            code, payload, packet = self.scope(
                "--mode", "commit", "--commit", head, "--path", "plain.txt"
            )
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            item = scope["items"][0]
            sources = {source["id"]: source for source in scope["sources"]}
            self.assertEqual("T", item["status"])
            symlink_source = sources[item["after"]]
            self.assertEqual("120000", symlink_source["git_mode"])
            self.assertEqual("symlink", symlink_source["availability"])
            self.assertEqual(b"script.sh", self.blob_bytes(packet, symlink_source))
            self.assertIsNone(symlink_source["line_count"])

    def test_g13_paths_with_spaces_tabs_newlines_and_non_ascii(self) -> None:
        names = ["plain space.py", "tab\tname.py", "line\nbreak.py", "中文名字.py", "-leading.py"]
        first = fixtures.commit_files(self.repo, {"base.py": "b = 1\n"})
        head = fixtures.commit_files(self.repo, {name: f"value = {index}\n" for index, name in enumerate(names)})
        code, payload, packet = self.scope("--mode", "commit", "--commit", head, "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual({("commit", name) for name in names}, set(self.items_by_path(scope)))
        for item in scope["items"]:
            source = next(s for s in scope["sources"] if s["id"] == item["after"])
            self.assertEqual(item["path"], source["path"])
        listing = fixtures.git(self.repo, "diff", "--raw", "-z", "--no-abbrev", first, head).stdout
        recorded_paths = [
            record.split(b"\0")[1] for record in listing.split(b":") if record and b"\0" in record
        ]
        self.assertEqual(sorted(name.encode("utf-8") for name in names), sorted(recorded_paths))

    def test_g14_unmerged_index_fails_without_touching_the_worktree(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "base\n"})
        fixtures.git(self.repo, "checkout", "-q", "-b", "side")
        fixtures.commit_files(self.repo, {"a.py": "side\n"})
        fixtures.git(self.repo, "checkout", "-q", "main")
        fixtures.commit_files(self.repo, {"a.py": "main\n"})
        fixtures.git(self.repo, "merge", "side", check=False)
        index_bytes = (self.repo / ".git" / "index").read_bytes()
        worktree_bytes = (self.repo / "a.py").read_bytes()
        output = self.packet_dir()
        code, payload = fixtures.run_cli(
            ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(output)]
        )
        self.assertEqual(2, code)
        self.assertEqual("E_UNMERGED", payload["code"])
        self.assertFalse((output / "scope.json").exists())
        self.assertEqual(index_bytes, (self.repo / ".git" / "index").read_bytes())
        self.assertEqual(worktree_bytes, (self.repo / "a.py").read_bytes())

    def test_g15_intent_to_add_is_not_a_staged_implementation(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "pending.py", "pending = 1\n")
        fixtures.git(self.repo, "add", "--intent-to-add", "pending.py")
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        items = self.items_by_path(scope)
        self.assertEqual({("worktree", "pending.py")}, set(items))
        item = items[("worktree", "pending.py")]
        self.assertEqual("A", item["status"])
        self.assertIsNone(item["before"])
        sources = {source["id"]: source for source in scope["sources"]}
        after = sources[item["after"]]
        self.assertEqual(b"pending = 1\n", self.blob_bytes(packet, after))
        self.assertEqual("worktree", after["origin"])

    def test_g16_snapshot_commit_and_worktree_read_their_own_source(self) -> None:
        committed = fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 9\n")
        code, payload, packet = self.scope(
            "--mode", "snapshot", "--revision", "HEAD", "--path", "."
        )
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        item = scope["items"][0]
        sources = {source["id"]: source for source in scope["sources"]}
        self.assertEqual("P", item["status"])
        self.assertIsNone(item["before"])
        self.assertEqual("git", sources[item["after"]]["origin"])
        self.assertEqual(b"a = 1\n", self.blob_bytes(packet, sources[item["after"]]))
        with self.subTest("G16 worktree snapshot"):
            code, payload, packet = self.scope(
                "--mode", "snapshot", "--revision", "WORKTREE", "--path", "."
            )
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            sources = {source["id"]: source for source in scope["sources"]}
            item = scope["items"][0]
            self.assertEqual("worktree", sources[item["after"]]["origin"])
            self.assertEqual(b"a = 9\n", self.blob_bytes(packet, sources[item["after"]]))
            self.assertEqual(committed, scope["resolved"]["head_oid"])
            self.assertEqual("bounded_double_observation", scope["observation"])

    def test_g17_binary_invalid_utf8_and_size_limits(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "binary.bin", b"\x00\x01\x02")
        fixtures.write_file(self.repo, "bad-utf8.txt", b"\xff\xfe\xfd text\n")
        fixtures.write_file(self.repo, "large.bin", b"L" * (8 * 1024 * 1024 + 1))
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        sources = {source["path"]: source for source in scope["sources"]}
        self.assertEqual("binary", sources["binary.bin"]["availability"])
        self.assertEqual(b"\x00\x01\x02", self.blob_bytes(packet, sources["binary.bin"]))
        self.assertEqual("binary", sources["bad-utf8.txt"]["availability"])
        large = sources["large.bin"]
        self.assertEqual("too_large", large["availability"])
        self.assertIsNone(large["sha256"])
        self.assertEqual(8 * 1024 * 1024 + 1, large["size_bytes"])

    def test_g17b_packet_budget_exhaustion(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        chunk = b"P" * (8 * 1024 * 1024 - 1)
        for index in range(17):
            fixtures.write_file(self.repo, f"bulk/{index:02d}.bin", bytes([65 + index]) + chunk)
        code, payload, packet = self.scope("--mode", "workspace", "--path", "bulk")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        statuses = [source["availability"] for source in scope["sources"]]
        self.assertIn("budget_exhausted", statuses)
        self.assertTrue(
            any("byte budget was exhausted" in text for text in scope["limitations"])
        )
        total = sum(
            path.stat().st_size for path in (packet / "objects").glob("*.blob")
        )
        self.assertLessEqual(total, 128 * 1024 * 1024)

    def test_g18_submodule_symlinked_parent_and_output_location(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        head = fixtures.head_oid(self.repo)
        with self.subTest("G18 submodule entry"):
            fixtures.git(
                self.repo,
                "update-index",
                "--add",
                "--cacheinfo",
                f"160000,{head},vendor/sub",
            )
            code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            items = self.items_by_path(scope)
            sources = {source["id"]: source for source in scope["sources"]}
            submodule_item = items[("index", "vendor/sub")]
            submodule = sources[submodule_item["after"]]
            self.assertEqual("submodule", submodule["availability"])
            self.assertEqual("160000", submodule["git_mode"])
            self.assertEqual(head, submodule["git_oid"])
            self.assertIsNone(submodule["sha256"])
        with self.subTest("G18 symlinked parent"):
            (self.repo / "outside").mkdir()
            fixtures.write_file(self.repo, "outside/real.py", "real = 1\n")
            os.symlink("outside", self.repo / "linked")
            with self.assertRaises(review_record.ReviewError) as caught:
                review_git._read_disk(self.repo, "linked/real.py")
            self.assertEqual("E_PARENT_SYMLINK", caught.exception.code)
        with self.subTest("G18 output inside the repository"):
            inside = self.repo / "packet"
            code, payload = fixtures.run_cli(
                ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(inside)]
            )
            self.assertEqual(2, code)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertFalse(inside.exists())

    def test_g19_change_during_capture_is_reported(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 2\n")
        original = review_git._read_disk
        state = {"reads": 0}

        def changing_read(root: Path, relative: str):
            result = original(root, relative)
            state["reads"] += 1
            if state["reads"] == 1 and relative == "a.py":
                (Path(root) / relative).write_bytes(b"a = 3\n")
            return result

        review_git._read_disk = changing_read
        self.addCleanup(setattr, review_git, "_read_disk", original)
        output = self.packet_dir()
        code, payload = fixtures.run_cli(
            ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(output)]
        )
        self.assertEqual(2, code)
        self.assertEqual("E_SOURCE_CHANGED_DURING_CAPTURE", payload["code"])
        self.assertFalse((output / "scope.json").exists())

    def test_g20_freshness_for_changed_relevant_and_unrelated_inputs(self) -> None:
        fixtures.commit_files(self.repo, {"src/module.py": "value = 1\n", "docs/readme.md": "docs\n"})
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        record = self._workspace_record(packet, scope)
        record_path = self.root / "record.json"
        fixtures.write_json(record_path, record)
        baseline = self.root / "report-baseline.json"
        code, payload = self._check(packet, record_path, baseline)
        self.assertEqual(0, code, payload)
        self.assertEqual("captured_inputs_match", payload["freshness"])
        with self.subTest("G20 relevant change"):
            fixtures.write_file(self.repo, "src/module.py", "value = 3\n")
            report = self.root / "report-changed.json"
            code, payload = self._check(packet, record_path, report)
            self.assertEqual(4, code)
            self.assertEqual("changed", payload["freshness"])
            self.assertIn("src/module.py", json.loads(report.read_text())["freshness"]["changed_paths"])
        with self.subTest("G20 new relevant item"):
            fixtures.write_file(self.repo, "src/added.py", "added = 1\n")
            report = self.root / "report-added.json"
            code, payload = self._check(packet, record_path, report)
            self.assertEqual(4, code)
            self.assertEqual("changed", payload["freshness"])
        with self.subTest("G20 unrelated change"):
            fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
            (self.repo / "src" / "added.py").unlink()
            fixtures.write_file(self.repo, "docs/readme.md", "updated docs\n")
            report = self.root / "report-unrelated.json"
            code, payload = self._check(packet, record_path, report)
            self.assertEqual(0, code)
            self.assertEqual("captured_inputs_match", payload["freshness"])

    def test_g21_context_paths_extend_sources_only(self) -> None:
        fixtures.commit_files(self.repo, {"src/module.py": "value = 1\n", "config/runtime.json": '{"limit": 32}\n'})
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.scope(
            "--mode",
            "workspace",
            "--path",
            "src/module.py",
            "--context-path",
            "config/runtime.json",
        )
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual(1, len(scope["items"]))
        context_sources = [
            source for source in scope["sources"] if source["path"] == "config/runtime.json"
        ]
        self.assertEqual(
            {"git", "index", "worktree"},
            {source["origin"] for source in context_sources},
        )
        self.assertEqual(3, len(context_sources))
        context = next(source for source in context_sources if source["origin"] == "worktree")
        self.assertEqual("worktree", context["origin"])
        record = self._workspace_record(packet, scope)
        record["findings"] = [
            {
                "id": "F-1",
                "severity": "medium",
                "summary": "The consumer reads a lower limit than the producer writes.",
                "relation": "not_determined",
                "trigger": "A request reads the runtime limit.",
                "impact": "The consumer rejects valid input.",
                "item_ids": [scope["items"][0]["id"]],
                "evidence": [
                    {
                        "source_id": context["id"],
                        "start_line": 1,
                        "end_line": 1,
                        "snippet": '{"limit": 32}',
                    }
                ],
                "fix": None,
            }
        ]
        record_path = self.root / "context-record.json"
        fixtures.write_json(record_path, record)
        report = self.root / "context-report.json"
        code, payload = self._check(packet, record_path, report)
        self.assertEqual(0, code, payload)
        written = json.loads(report.read_text())
        self.assertEqual(1, written["finding_count"])
        self.assertEqual("resolved", written["anchors"][0]["status"])
        self.assertEqual(1, written["item_counts"]["total"])

    def test_g22_repeated_capture_is_semantically_identical(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n", "b.py": "b = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 2\n")
        code, payload, first = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        code, payload, second = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        first_bytes = (first / "scope.json").read_bytes()
        second_bytes = (second / "scope.json").read_bytes()
        self.assertEqual(
            json.loads(first_bytes), json.loads(second_bytes)
        )
        self.assertEqual(first_bytes, second_bytes)
        first_objects = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (first / "objects").glob("*.blob")
        }
        second_objects = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (second / "objects").glob("*.blob")
        }
        self.assertEqual(first_objects, second_objects)
        self.assertEqual(payload["scope_sha256"], review_record.sha256_digest(second_bytes))

    def test_g23_inherited_git_environment_and_promisor_markers(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 2\n")
        decoy = fixtures.init_repo(self.root / "decoy")
        fixtures.commit_files(decoy, {"decoy.py": "decoy = 1\n"})
        original = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(original)))
        os.environ["GIT_DIR"] = str(decoy / ".git")
        os.environ["GIT_INDEX_FILE"] = str(decoy / ".git" / "index")
        os.environ["GIT_CONFIG_COUNT"] = "1"
        os.environ["GIT_CONFIG_KEY_0"] = "core.hooksPath"
        os.environ["GIT_CONFIG_VALUE_0"] = "/nonexistent"
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        sources = {source["path"]: source for source in scope["sources"]}
        self.assertIn("a.py", sources)
        self.assertNotIn("decoy.py", sources)
        self.assertEqual(b"a = 2\n", self.blob_bytes(packet, sources["a.py"]))
        os.environ.clear()
        os.environ.update(original)
        with self.subTest("G23 promisor configuration"):
            fixtures.git(self.repo, "config", "extensions.partialClone", "origin")
            output = self.packet_dir()
            code, payload = fixtures.run_cli(
                ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(output)]
            )
            self.assertEqual(2, code)
            self.assertEqual("E_PARTIAL_CLONE", payload["code"])
            self.assertFalse(output.exists())
            fixtures.git(self.repo, "config", "--unset", "extensions.partialClone")
        with self.subTest("G23 promisor pack marker"):
            pack_dir = self.repo / ".git" / "objects" / "pack"
            pack_dir.mkdir(parents=True, exist_ok=True)
            marker = pack_dir / "fixture.promisor"
            marker.write_bytes(b"")
            self.addCleanup(lambda: marker.unlink(missing_ok=True))
            output = self.packet_dir()
            code, payload = fixtures.run_cli(
                ["scope", "--repo", str(self.repo), "--mode", "workspace", "--path", ".", "--output", str(output)]
            )
            self.assertEqual(2, code)
            self.assertEqual("E_PARTIAL_CLONE", payload["code"])
            self.assertFalse(output.exists())

    def _raw_diff_paths(self, raw: bytes) -> list[bytes]:
        tokens = raw.split(b"\0")
        return [tokens[index + 1] for index, token in enumerate(tokens) if token.startswith(b":")]

    def _workspace_record(self, packet: Path, scope: dict) -> dict:
        digest = review_record.sha256_digest((packet / "scope.json").read_bytes())
        return {
            "schema_version": "fas-review-record/1",
            "scope_ref": "scope.json",
            "scope_sha256": digest,
            "coverage": [
                {"item_id": item["id"], "status": "reviewed", "reason": None}
                for item in scope["items"]
            ],
            "findings": [],
            "concerns": [],
            "verification": [],
            "limitations": [],
        }

    def _check(self, packet: Path, record: Path, report: Path):
        if report.exists():
            report.unlink()
        return fixtures.run_cli(
            [
                "check",
                "--repo",
                str(self.repo),
                "--packet",
                str(packet),
                "--record",
                str(record),
                "--output",
                str(report),
            ]
        )


if __name__ == "__main__":
    unittest.main()
