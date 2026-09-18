"""G01-G23: real Git fixtures for scope capture, layering, limits, and freshness."""

from __future__ import annotations

import errno
import hashlib
import json
import os
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

import _review_fixtures as fixtures  # noqa: E402
import _review_git as review_git  # noqa: E402
import _review_record as review_record  # noqa: E402


class _FaultyScopeStream:
    """A scope-field stream that fails mid-write or on close."""

    def __init__(self, stream, *, prefix: int | None, close_failure: bool) -> None:
        self._stream = stream
        self._prefix = prefix
        self._close_failure = close_failure

    def write(self, data: bytes) -> int:
        if self._prefix is None:
            return self._stream.write(data)
        self._stream.write(data[: self._prefix])
        self._stream.flush()
        raise OSError(errno.ENOSPC, "No space left on device")

    def __enter__(self) -> "_FaultyScopeStream":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self._stream.close()
        if self._close_failure:
            raise OSError(errno.ENOSPC, "No space left on device")
        return False


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
        code, payload = fixtures.capture_cli(self.repo, output, *args)
        return code, payload, output

    def read_scope(self, packet: Path) -> dict:
        return json.loads((packet / "scope.json").read_text(encoding="utf-8"))

    def items_by_path(self, scope: dict) -> dict[tuple[str, str], dict]:
        return {(item["layer"], item["path"]): item for item in scope["items"]}

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
            code, payload = fixtures.capture_cli(
                self.repo, self.packet_dir(), "--mode", "range", "--base", "main", "--head", "orphan",
                "--path", ".",
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
            code, payload = fixtures.capture_cli(
                self.repo, self.packet_dir(), "--mode", "range", "--base", m1, "--head", m2, "--path",
                ".",
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
            self.assertEqual(4, code, payload)
            self.assertEqual(4, payload["exit_code"])
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
        code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", ".")
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
        large = self.repo / "large.bin"
        with large.open("wb") as stream:
            stream.truncate(8 * 1024 * 1024 + 1)
        code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
        self.assertEqual(4, code, payload)
        self.assertEqual(4, payload["exit_code"])
        scope = self.read_scope(packet)
        sources = {source["path"]: source for source in scope["sources"]}
        self.assertEqual("binary", sources["binary.bin"]["availability"])
        self.assertEqual(b"\x00\x01\x02", self.blob_bytes(packet, sources["binary.bin"]))
        self.assertEqual("binary", sources["bad-utf8.txt"]["availability"])
        self.assertEqual("too_large", sources["large.bin"]["availability"])
        self.assertIsNone(sources["large.bin"]["sha256"])
        self.assertEqual(8 * 1024 * 1024 + 1, sources["large.bin"]["size_bytes"])
        self.assertEqual(8 * 1024 * 1024, review_record.MAX_FILE_BYTES)
        self.assertEqual(128 * 1024 * 1024, review_record.MAX_PACKET_BYTES)

    def test_g17b_packet_budget_exhaustion(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        for index in range(4):
            fixtures.write_file(self.repo, f"bulk/{index:02d}.bin", bytes([65 + index]) * 12)
        with mock.patch.object(review_git, "MAX_PACKET_BYTES", 24):
            code, payload, packet = self.scope("--mode", "workspace", "--path", "bulk")
        self.assertEqual(4, code, payload)
        scope = self.read_scope(packet)
        sources = {source["path"]: source for source in scope["sources"]}
        statuses = [source["availability"] for source in scope["sources"]]
        self.assertEqual(2, statuses.count("text"))
        self.assertEqual(2, statuses.count("budget_exhausted"))
        self.assertEqual("text", sources["bulk/00.bin"]["availability"])
        self.assertEqual("text", sources["bulk/01.bin"]["availability"])
        self.assertEqual("budget_exhausted", sources["bulk/02.bin"]["availability"])
        self.assertIsNone(sources["bulk/02.bin"]["sha256"])
        self.assertEqual(12, sources["bulk/02.bin"]["size_bytes"])
        self.assertTrue(
            any("byte budget was exhausted" in text for text in scope["limitations"])
        )
        total = sum(path.stat().st_size for path in (packet / "objects").glob("*.blob"))
        self.assertEqual(24, total)

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
            self.assertEqual(4, code, payload)
            self.assertEqual(4, payload["exit_code"])
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
            code, payload = fixtures.capture_cli(self.repo, inside, "--mode", "workspace", "--path", ".")
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

        output = self.packet_dir()
        with mock.patch.object(review_git, "_read_disk", changing_read):
            code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", ".")
        self.assertEqual(2, code)
        self.assertEqual("E_SOURCE_CHANGED_DURING_CAPTURE", payload["code"])
        self.assertFalse((output / "scope.json").exists())

    def test_g20_freshness_for_changed_relevant_and_unrelated_inputs(self) -> None:
        fixtures.commit_files(self.repo, {"src/module.py": "value = 1\n", "docs/readme.md": "docs\n"})
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src")
        self.assertEqual(0, code, payload)
        record = fixtures.hand_record(fixtures.packet_view(packet))
        record_path = self.root / "record.json"
        fixtures.write_json(record_path, record)
        baseline = self.root / "report-baseline.json"
        code, payload = fixtures.check_cli(self.repo, packet, record_path, baseline)
        self.assertEqual(0, code, payload)
        self.assertEqual("captured_inputs_match", payload["freshness"])
        with self.subTest("G20 relevant change"):
            fixtures.write_file(self.repo, "src/module.py", "value = 3\n")
            report = self.root / "report-changed.json"
            code, payload = fixtures.check_cli(self.repo, packet, record_path, report)
            self.assertEqual(4, code)
            self.assertEqual("changed", payload["freshness"])
            self.assertIn("src/module.py", json.loads(report.read_text())["freshness"]["changed_paths"])
        with self.subTest("G20 new relevant item"):
            fixtures.write_file(self.repo, "src/added.py", "added = 1\n")
            report = self.root / "report-added.json"
            code, payload = fixtures.check_cli(self.repo, packet, record_path, report)
            self.assertEqual(4, code)
            self.assertEqual("changed", payload["freshness"])
        with self.subTest("G20 unrelated change"):
            fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
            (self.repo / "src" / "added.py").unlink()
            fixtures.write_file(self.repo, "docs/readme.md", "updated docs\n")
            report = self.root / "report-unrelated.json"
            code, payload = fixtures.check_cli(self.repo, packet, record_path, report)
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
        record = fixtures.hand_record(fixtures.packet_view(packet))
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
        code, payload = fixtures.check_cli(self.repo, packet, record_path, report)
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
            code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", ".")
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
            code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", ".")
            self.assertEqual(2, code)
            self.assertEqual("E_PARTIAL_CLONE", payload["code"])
            self.assertFalse(output.exists())

    def test_n01_context_sources_take_part_in_freshness(self) -> None:
        fixtures.commit_files(
            self.repo,
            {
                "src/module.py": "value = 1\n",
                "config/runtime.json": '{"limit": 32}\n',
                "docs/readme.md": "docs\n",
            },
        )
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
        record_path = self.root / "n01-workspace-record.json"
        fixtures.write_json(record_path, fixtures.hand_record(fixtures.packet_view(packet)))

        def check(name: str):
            return fixtures.check_cli(self.repo, packet, record_path, self.root / f"n01-{name}.json")

        code, payload = check("baseline")
        self.assertEqual(0, code, payload)
        self.assertEqual("captured_inputs_match", payload["freshness"])
        with self.subTest("N01 context bytes changed"):
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 64}\n')
            code, payload = check("bytes")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
            written = json.loads((self.root / "n01-bytes.json").read_text())
            self.assertIn("config/runtime.json", written["freshness"]["changed_paths"])
        with self.subTest("N01 restore after an unrelated change stays a match"):
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 32}\n')
            fixtures.write_file(self.repo, "docs/readme.md", "updated docs\n")
            code, payload = check("unrelated")
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", payload["freshness"])
        with self.subTest("N01 context mode changed"):
            os.chmod(self.repo / "config/runtime.json", 0o755)
            self.addCleanup(os.chmod, self.repo / "config/runtime.json", 0o644)
            code, payload = check("mode")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
        with self.subTest("N01 context deleted"):
            (self.repo / "config/runtime.json").unlink()
            code, payload = check("deleted")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 32}\n')
            os.chmod(self.repo / "config/runtime.json", 0o644)
        with self.subTest("N01 context index-only change"):
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 64}\n')
            fixtures.git(self.repo, "add", "config/runtime.json")
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 32}\n')
            code, payload = check("index-only")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
            written = json.loads((self.root / "n01-index-only.json").read_text())
            self.assertIn("config/runtime.json", written["freshness"]["changed_paths"])
            fixtures.git(self.repo, "reset", "-q", "config/runtime.json")
        self._assert_n01_worktree_snapshot()
        self._assert_n01_frozen_commit_survives_a_ref_move()

    def _assert_n01_worktree_snapshot(self) -> None:
        code, payload, packet = self.scope(
            "--mode",
            "snapshot",
            "--revision",
            "WORKTREE",
            "--path",
            "src/module.py",
            "--context-path",
            "config/runtime.json",
        )
        self.assertEqual(0, code, payload)
        scope = self.read_scope(packet)
        self.assertEqual(1, len(scope["items"]))
        record_path = self.root / "n01-snapshot-record.json"
        fixtures.write_json(record_path, fixtures.hand_record(fixtures.packet_view(packet)))
        with self.subTest("N01 snapshot context bytes changed"):
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 128}\n')
            code, payload = fixtures.check_cli(self.repo, packet, record_path, self.root / "n01-snapshot-bytes.json")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
        with self.subTest("N01 snapshot context deleted"):
            (self.repo / "config/runtime.json").unlink()
            code, payload = fixtures.check_cli(self.repo, packet, record_path, self.root / "n01-snapshot-deleted.json")
            self.assertEqual(4, code, payload)
            self.assertEqual("changed", payload["freshness"])
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 32}\n')
        with self.subTest("N01 snapshot unchanged context matches"):
            code, payload = fixtures.check_cli(self.repo, packet, record_path, self.root / "n01-snapshot-match.json")
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", payload["freshness"])

    def _assert_n01_frozen_commit_survives_a_ref_move(self) -> None:
        fixtures.commit_files(self.repo, {"config/runtime.json": '{"limit": 32}\n'})
        head = fixtures.head_oid(self.repo)
        code, payload, packet = self.scope(
            "--mode",
            "commit",
            "--commit",
            head,
            "--path",
            "src/module.py",
            "--context-path",
            "config/runtime.json",
        )
        self.assertEqual(0, code, payload)
        record_path = self.root / "n01-commit-record.json"
        fixtures.write_json(record_path, fixtures.hand_record(fixtures.packet_view(packet)))
        moved = fixtures.commit_files(self.repo, {"config/runtime.json": '{"limit": 512}\n'})
        with self.subTest("N01 frozen commit ignores a moved branch"):
            code, payload = fixtures.check_cli(self.repo, packet, record_path, self.root / "n01-commit-moved.json")
            self.assertEqual(0, code, payload)
            self.assertEqual("captured_inputs_match", payload["freshness"])
            self.assertNotEqual(head, moved)

    def test_n02_context_change_during_capture_is_reported(self) -> None:
        fixtures.commit_files(
            self.repo,
            {"src/module.py": "value = 1\n", "config/runtime.json": '{"limit": 32}\n'},
        )
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        original = review_git._read_disk
        state = {"injected": 0}

        def changing_read(root: Path, relative: str):
            result = original(root, relative)
            if relative == "config/runtime.json" and state["injected"] == 0:
                state["injected"] += 1
                (Path(root) / relative).write_bytes(b'{"limit": 99}\n')
            return result

        output = self.packet_dir()
        with mock.patch.object(review_git, "_read_disk", changing_read):
            code, payload = fixtures.capture_cli(
                self.repo, output, "--mode", "workspace", "--path", "src/module.py", "--context-path",
                "config/runtime.json",
            )
        self.assertEqual(2, code, payload)
        self.assertEqual("E_SOURCE_CHANGED_DURING_CAPTURE", payload["code"])
        self.assertEqual(1, state["injected"])
        self.assertEqual(b'{"limit": 99}\n', (self.repo / "config/runtime.json").read_bytes())
        self.assertFalse((output / "scope.json").exists())

    def test_n03_only_a_missing_path_may_be_skipped(self) -> None:
        fixtures.commit_files(self.repo, {"dir/a.py": "a = 1\n"})
        (self.repo / "dir").rename(self.repo / "dir-real")
        os.symlink("dir-real", self.repo / "dir")
        with self.subTest("N03 symlinked parent fails explicitly"):
            output = self.packet_dir()
            code, payload = fixtures.capture_cli(
                self.repo, output, "--mode", "snapshot", "--revision", "WORKTREE", "--path", "dir/a.py",
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PARENT_SYMLINK", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("N03 deleted tracked path stays absent"):
            (self.repo / "dir").unlink()
            code, payload, packet = self.scope(
                "--mode", "snapshot", "--revision", "WORKTREE", "--path", "dir/a.py"
            )
            self.assertEqual(0, code, payload)
            self.assertEqual([], self.read_scope(packet)["items"])
        with self.subTest("N03 final symlink is recorded as itself"):
            fixtures.write_file(self.repo, "target.py", "t = 1\n")
            os.symlink("target.py", self.repo / "link.py")
            code, payload, packet = self.scope("--mode", "workspace", "--path", "link.py")
            self.assertEqual(4, code, payload)
            scope = self.read_scope(packet)
            source = next(item for item in scope["sources"] if item["path"] == "link.py")
            self.assertEqual("symlink", source["availability"])
            self.assertEqual(b"target.py", self.blob_bytes(packet, source))
        with self.subTest("N03 permission failures are explicit"):
            real_open = os.open

            def denied(path, flags, *args, **kwargs):
                if path == "denied":
                    raise PermissionError(errno.EACCES, "Permission denied")
                return real_open(path, flags, *args, **kwargs)

            with mock.patch.object(review_git.os, "open", denied):
                with self.assertRaises(review_record.ReviewError) as caught:
                    review_git._disk_present(self.repo, "denied/a.py")
                self.assertEqual("E_IO", caught.exception.code)
                with self.assertRaises(review_record.ReviewError) as typed:
                    review_git._disk_file_present(self.repo, "denied/a.py")
                self.assertEqual("E_IO", typed.exception.code)
            self.assertFalse(review_git._disk_present(self.repo, "absent/a.py"))
            self.assertFalse(review_git._disk_file_present(self.repo, "absent/a.py"))

    def test_n04_packet_budget_counts_new_deduped_bytes(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        duplicate = b"duplicate!!\n"
        self.assertEqual(12, len(duplicate))
        fixtures.write_file(self.repo, "dup/one.txt", duplicate)
        fixtures.write_file(self.repo, "dup/two.txt", duplicate)
        original = review_git.MAX_PACKET_BYTES
        review_git.MAX_PACKET_BYTES = 16
        self.addCleanup(setattr, review_git, "MAX_PACKET_BYTES", original)
        with self.subTest("N04 duplicate bytes are not charged twice"):
            code, payload, packet = self.scope("--mode", "workspace", "--path", "dup")
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            sources = {source["path"]: source for source in scope["sources"]}
            self.assertEqual(
                {"text"}, {source["availability"] for source in sources.values()}
            )
            self.assertEqual(1, len(list((packet / "objects").glob("*.blob"))))
            self.assertEqual(sources["dup/one.txt"]["sha256"], sources["dup/two.txt"]["sha256"])
            for source in sources.values():
                self.assertEqual(12, source["size_bytes"])
                self.assertEqual(1, source["line_count"])
        with self.subTest("N04 a unique object exactly on the budget is kept"):
            fixtures.write_file(self.repo, "exact.txt", b"E" * 16)
            code, payload, packet = self.scope("--mode", "workspace", "--path", "exact.txt")
            self.assertEqual(0, code, payload)
            source = self.read_scope(packet)["sources"][0]
            self.assertEqual("text", source["availability"])
        with self.subTest("N04 a new unique object over the budget is not captured"):
            fixtures.write_file(self.repo, "unique.txt", b"U" * 12)
            code, payload, packet = self.scope(
                "--mode", "workspace", "--path", "dup/one.txt", "--path", "unique.txt"
            )
            self.assertEqual(4, code, payload)
            sources = {source["path"]: source for source in self.read_scope(packet)["sources"]}
            self.assertEqual("text", sources["dup/one.txt"]["availability"])
            self.assertEqual("budget_exhausted", sources["unique.txt"]["availability"])
            self.assertIsNone(sources["unique.txt"]["sha256"])
            self.assertEqual(12, sources["unique.txt"]["size_bytes"])
            blobs = list((packet / "objects").glob("*.blob"))
            self.assertEqual(1, len(blobs))
            self.assertEqual(12, blobs[0].stat().st_size)

    def test_n05_capture_seals_only_a_valid_scope(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n", "b.py": "b = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 2\n")
        fixtures.write_file(self.repo, "b.py", "b = 2\n")
        with self.subTest("N05 over-long revision"):
            long_ref = "HEAD" + "^0" * 70
            self.assertEqual(144, len(long_ref))
            output = self.packet_dir()
            code, payload = fixtures.capture_cli(
                self.repo, output, "--mode", "snapshot", "--revision", long_ref, "--path", ".",
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_REVISION", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("N05 revision that is only whitespace"):
            output = self.packet_dir()
            code, payload = fixtures.capture_cli(
                self.repo, output, "--mode", "snapshot", "--revision", "   ", "--path", ".",
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_REVISION", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("N05 NUL in a path"):
            output = self.packet_dir()
            code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", "a\x00b")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PATH_INVALID", payload["code"])
            self.assertFalse(output.exists())
        with self.subTest("N05 encoded scope size limit"):
            with mock.patch.object(review_record, "MAX_JSON_BYTES", 512):
                output = self.packet_dir()
                code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", ".")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_JSON_TOO_LARGE", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("N05 items and sources limits"):
            with (
                mock.patch.object(review_git, "MAX_ITEMS", 1),
                mock.patch.object(review_record, "MAX_ITEMS", 1),
            ):
                output = self.packet_dir()
                code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", ".")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_ITEMS_LIMIT", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("N05 a crafted scope with too many sources is rejected"):
            with mock.patch.object(review_record, "MAX_ITEMS", 1):
                crafted = fixtures.hand_packet(
                    self.root,
                    sources=[
                        {
                            "name": f"s{index}",
                            "path": f"f{index}.py",
                            "origin": "worktree",
                            "availability": "text",
                            "payload": b"x = 1\n",
                        }
                        for index in range(4)
                    ],
                    items=[
                        {"layer": "worktree", "status": "A", "path": "f0.py", "after": "s0"}
                    ],
                    packet_name="n05-crafted",
                )
                with self.assertRaises(review_record.ReviewError) as caught:
                    review_record.validate_scope(crafted["scope"])
            self.assertEqual("E_SOURCES_LIMIT", caught.exception.code)
        with self.subTest("N05 a successful scope passes the same validation"):
            code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            review_record.validate_scope(scope)
            review_record.validate_document(scope, "scope")

    def test_n07_output_boundary_uses_the_real_repository_root(self) -> None:
        fixtures.commit_files(self.repo, {"src/module.py": "value = 1\n"})
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        code, payload, packet = self.scope("--mode", "workspace", "--path", "src/module.py")
        self.assertEqual(0, code, payload)
        record_path = self.root / "n07-record.json"
        fixtures.write_json(record_path, fixtures.hand_record(fixtures.packet_view(packet)))
        subdirectory = self.repo / "src"
        baseline_head = fixtures.head_oid(self.repo)
        baseline_status = fixtures.git(self.repo, "status", "--porcelain").stdout
        with self.subTest("N07 check from a subdirectory cannot write inside the repository"):
            inside = self.repo / "report-inside.json"
            code, payload = fixtures.check_cli(subdirectory, packet, record_path, inside)
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertFalse(inside.exists())
        with self.subTest("N07 scope from a subdirectory cannot write inside the repository"):
            output = self.repo / "packet-inside"
            code, payload = fixtures.capture_cli(subdirectory, output, "--mode", "workspace", "--path", "src/module.py")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_OUTPUT", payload["code"])
            self.assertFalse(output.exists())
        with self.subTest("N07 check from a subdirectory still writes outside"):
            outside = self.root / "report-outside.json"
            code, payload = fixtures.check_cli(subdirectory, packet, record_path, outside)
            self.assertEqual(0, code, payload)
            self.assertTrue(outside.is_file())
        with self.subTest("N07 the repository is untouched"):
            self.assertEqual(baseline_head, fixtures.head_oid(self.repo))
            self.assertEqual(
                baseline_status, fixtures.git(self.repo, "status", "--porcelain").stdout
            )

    def test_n08_scope_exit_contract_follows_source_availability(self) -> None:
        fixtures.commit_files(self.repo, {"text/a.py": "a = 1\n"})
        fixtures.write_file(self.repo, ".gitignore", "ignored.txt\n")
        fixtures.write_file(self.repo, "ignored.txt", "ignored = 1\n")
        with self.subTest("N08 all-text scope is zero"):
            fixtures.write_file(self.repo, "text/a.py", "a = 2\n")
            code, payload, packet = self.scope("--mode", "workspace", "--path", "text")
            self.assertEqual(0, code, payload)
            self.assertEqual(0, payload["exit_code"])
            scope = self.read_scope(packet)
            self.assertTrue(scope["sources"])
            self.assertEqual({"text"}, {source["availability"] for source in scope["sources"]})
        with self.subTest("N08 ignored-untracked reminder alone stays zero"):
            code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
            self.assertEqual(0, code, payload)
            self.assertEqual(0, payload["exit_code"])
            scope = self.read_scope(packet)
            self.assertTrue(scope["limitations"])
            self.assertNotIn("ignored.txt", {source["path"] for source in scope["sources"]})
            self.assertEqual(
                {"text"}, {source["availability"] for source in scope["sources"]}
            )
        with self.subTest("N08 binary source is partial"):
            fixtures.write_file(self.repo, "nontext/b.bin", b"\x00\x01\x02")
            code, payload, packet = self.scope("--mode", "workspace", "--path", "nontext")
            self.assertEqual(4, code, payload)
            self.assertEqual(4, payload["exit_code"])
            scope = self.read_scope(packet)
            self.assertEqual(
                {"binary"}, {source["availability"] for source in scope["sources"]}
            )
        with self.subTest("N08 too-large source is partial"):
            large = self.repo / "large/large.bin"
            large.parent.mkdir(parents=True)
            with large.open("wb") as stream:
                stream.truncate(8 * 1024 * 1024 + 1)
            code, payload, packet = self.scope("--mode", "workspace", "--path", "large")
            self.assertEqual(4, code, payload)
            self.assertEqual(4, payload["exit_code"])
            source = self.read_scope(packet)["sources"][0]
            self.assertEqual("too_large", source["availability"])
            self.assertEqual(8 * 1024 * 1024 + 1, source["size_bytes"])
            self.assertEqual(
                16 * 1024 * 1024, review_record.MAX_JSON_BYTES
            )
            self.assertEqual(8 * 1024 * 1024, review_record.MAX_FILE_BYTES)
            self.assertEqual(128 * 1024 * 1024, review_record.MAX_PACKET_BYTES)
        with self.subTest("N08 submodule source is partial"):
            head = fixtures.head_oid(self.repo)
            fixtures.git(
                self.repo, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor/sub"
            )
            code, payload, packet = self.scope("--mode", "workspace", "--path", "vendor/sub")
            self.assertEqual(4, code, payload)
            self.assertEqual(4, payload["exit_code"])
            source = self.read_scope(packet)["sources"][0]
            self.assertEqual("submodule", source["availability"])
        with self.subTest("N08 hard errors stay two and seal nothing"):
            output = self.packet_dir()
            code, payload = fixtures.capture_cli(
                self.repo, output, "--mode", "commit", "--commit", "does-not-exist", "--path", ".",
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_REVISION", payload["code"])
            self.assertFalse((output / "scope.json").exists())

    def test_f1_equivalent_context_spellings_share_one_source_set(self) -> None:
        head = fixtures.commit_files(
            self.repo,
            {"src/module.py": "value = 1\n", "config/runtime.json": '{"limit": 32}\n'},
        )
        fixtures.write_file(self.repo, "src/module.py", "value = 2\n")
        fixtures.write_file(self.repo, "cfg/runtime.py", "limit = 32\n")
        packets = {}
        for label, spelling in (
            ("plain", "config/runtime.json"),
            ("dotted", "./config/runtime.json"),
        ):
            with self.subTest(f"F1 {label} snapshot spelling"):
                code, payload, packet = self.scope(
                    "--mode",
                    "snapshot",
                    "--revision",
                    "HEAD",
                    "--path",
                    "src/module.py",
                    "--context-path",
                    spelling,
                )
                self.assertEqual(0, code, payload)
                packets[label] = packet
                scope = self.read_scope(packet)
                self.assertEqual(["config/runtime.json"], scope["request"]["context_paths"])
                context = [
                    source
                    for source in scope["sources"]
                    if source["path"] == "config/runtime.json"
                ]
                self.assertEqual({"git"}, {source["origin"] for source in context})
                self.assertEqual([head], [source["revision"] for source in context])
        self.assertEqual(
            (packets["plain"] / "scope.json").read_bytes(),
            (packets["dotted"] / "scope.json").read_bytes(),
        )
        with self.subTest("F1 a parent component is rejected before normalization"):
            output = self.packet_dir("f1-parent")
            code, payload = fixtures.capture_cli(
                self.repo, output, "--mode", "workspace", "--path", "config/../config/runtime.json",
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PATH_INVALID", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("F1 redundant separators and dot segments normalize"):
            code, payload, packet = self.scope(
                "--mode",
                "workspace",
                "--path",
                "cfg//./runtime.py",
                "--context-path",
                "./config/runtime.json",
            )
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            self.assertEqual(["cfg/runtime.py"], scope["request"]["paths"])
            self.assertEqual(["cfg/runtime.py"], [item["path"] for item in scope["items"]])
            self.assertEqual(["config/runtime.json"], scope["request"]["context_paths"])
        with self.subTest("F1 equivalent context parameters collapse into one source set"):
            code, payload, packet = self.scope(
                "--mode",
                "workspace",
                "--path",
                "src/module.py",
                "--context-path",
                "./config/runtime.json",
                "--context-path",
                "config/runtime.json",
            )
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            self.assertEqual(["config/runtime.json"], scope["request"]["context_paths"])
            context = [
                source
                for source in scope["sources"]
                if source["path"] == "config/runtime.json"
            ]
            self.assertEqual({"git", "index", "worktree"}, {source["origin"] for source in context})
        with self.subTest("F1 an index-only context change is reported"):
            code, payload, packet = self.scope(
                "--mode",
                "workspace",
                "--path",
                "src/module.py",
                "--context-path",
                "./config/runtime.json",
            )
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            record = fixtures.write_json(
                self.root / "f1-index-record.json", fixtures.hand_record(fixtures.packet_view(packet))
            )
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 64}\n')
            fixtures.git(self.repo, "add", "config/runtime.json")
            fixtures.write_file(self.repo, "config/runtime.json", '{"limit": 32}\n')
            report = self.root / "f1-index-report.json"
            code, payload = fixtures.check_cli(self.repo, packet, record, report)
            self.assertEqual(4, code, payload)
            written = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("changed", written["freshness"]["status"])
            self.assertIn("config/runtime.json", written["freshness"]["changed_paths"])
        with self.subTest("F1 glob characters in real file names stay literal"):
            fixtures.commit_files(self.repo, {"star*.py": "star = 1\n"})
            fixtures.write_file(self.repo, "star*.py", "star = 2\n")
            code, payload, packet = self.scope("--mode", "workspace", "--path", ".")
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            self.assertIn("star*.py", [item["path"] for item in scope["items"]])
            record = fixtures.write_json(
                self.root / "f1-glob-record.json", fixtures.hand_record(fixtures.packet_view(packet))
            )
            code, payload = fixtures.check_cli(self.repo, packet, record, self.root / "f1-glob-report.json")
            self.assertEqual(0, code, payload)
            output = self.packet_dir("f1-glob-request")
            code, payload = fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", "star*.py")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PATH_INVALID", payload["code"])
        with self.subTest("F1 a context source that appears later is reported"):
            fixtures.write_file(self.repo, "notes/extra.py", "extra = 1\n")
            code, payload, packet = self.scope(
                "--mode",
                "workspace",
                "--path",
                "src/module.py",
                "--context-path",
                "notes/extra.py",
            )
            self.assertEqual(0, code, payload)
            scope = self.read_scope(packet)
            self.assertEqual(
                {"worktree"},
                {
                    source["origin"]
                    for source in scope["sources"]
                    if source["path"] == "notes/extra.py"
                },
            )
            record = fixtures.write_json(
                self.root / "f1-origin-record.json", fixtures.hand_record(fixtures.packet_view(packet))
            )
            fixtures.git(self.repo, "add", "notes/extra.py")
            report = self.root / "f1-origin-report.json"
            code, payload = fixtures.check_cli(self.repo, packet, record, report)
            self.assertEqual(4, code, payload)
            written = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual("changed", written["freshness"]["status"])
            self.assertIn("notes/extra.py", written["freshness"]["changed_paths"])

    def test_f3_non_utf8_git_paths_are_typed_errors(self) -> None:
        bad_name = os.fsdecode(b"bad-\xff.py")
        with self.subTest("F3 a tracked snapshot path"):
            repo = fixtures.init_repo(self.root / "encoding-tracked")
            fixtures.commit_files(repo, {"ok.py": "ok = 1\n"})
            (repo / bad_name).write_bytes(b"broken = 1\n")
            fixtures.git(repo, "add", "-A")
            fixtures.git(repo, "commit", "-q", "-m", "non utf-8 name")
            output = self.packet_dir("f3-tracked")
            code, payload = fixtures.capture_cli(
                repo, output, "--mode", "snapshot", "--revision", "HEAD", "--path", ".",
            )
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PATH_ENCODING", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("F3 a staged path"):
            repo = fixtures.init_repo(self.root / "encoding-staged")
            fixtures.commit_files(repo, {"ok.py": "ok = 1\n"})
            (repo / bad_name).write_bytes(b"broken = 1\n")
            fixtures.git(repo, "add", "-A")
            with self.assertRaises(review_record.ReviewError) as staged:
                review_git._ls_files_stage(repo, ["."])
            self.assertEqual("E_PATH_ENCODING", staged.exception.code)
            output = self.packet_dir("f3-staged")
            code, payload = fixtures.capture_cli(repo, output, "--mode", "workspace", "--path", ".")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PATH_ENCODING", payload["code"])
            self.assertFalse((output / "scope.json").exists())
        with self.subTest("F3 an untracked path"):
            repo = fixtures.init_repo(self.root / "encoding-untracked")
            fixtures.commit_files(repo, {"ok.py": "ok = 1\n"})
            (repo / bad_name).write_bytes(b"broken = 1\n")
            output = self.packet_dir("f3-untracked")
            code, payload = fixtures.capture_cli(repo, output, "--mode", "workspace", "--path", ".")
            self.assertEqual(2, code, payload)
            self.assertEqual("E_PATH_ENCODING", payload["code"])
            self.assertFalse((output / "scope.json").exists())

    def test_f4_repository_root_keeps_only_protocol_terminator(self) -> None:
        cases = (
            ("plain", "repo-plain"),
            ("trailing space", "repo-trailing "),
            ("trailing newline", "repo-newline\n"),
        )
        for label, name in cases:
            with self.subTest(f"F4 {label}"):
                repo = fixtures.init_repo(self.root, name=name)
                fixtures.write_file(repo, "only.py", "value = 1\n")
                fixtures.git(repo, "add", "-A")
                fixtures.git(repo, "commit", "-q", "-m", "fixture")
                stem = label.replace(" ", "-")
                packet = self.packet_dir(f"f4-{stem}")
                code, payload = fixtures.capture_cli(
                    repo, packet, "--mode", "snapshot", "--revision", "HEAD", "--path", ".",
                )
                self.assertEqual(0, code, payload)
                scope = self.read_scope(packet)
                self.assertEqual(["only.py"], [item["path"] for item in scope["items"]])
                record = fixtures.write_json(
                    self.root / f"f4-{stem}-record.json", fixtures.hand_record(fixtures.packet_view(packet))
                )
                report = self.root / f"f4-{stem}-report.json"
                code, payload = fixtures.check_cli(repo, packet, record, report)
                self.assertEqual(0, code, payload)
                written = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual("captured_inputs_match", written["freshness"]["status"])

    def test_f5_scope_marker_is_published_atomically(self) -> None:
        fixtures.commit_files(self.repo, {"a.py": "a = 1\n"})
        fixtures.write_file(self.repo, "a.py", "a = 2\n")

        def faulty_capture(output: Path, prefix: int | None, close_failure: bool):
            real_fdopen = os.fdopen
            real_mkstemp = review_git.tempfile.mkstemp
            state: dict[str, int] = {}

            def tracking_mkstemp(*args, **kwargs):
                descriptor, name = real_mkstemp(*args, **kwargs)
                if Path(name).parent == output:
                    state["descriptor"] = descriptor
                return descriptor, name

            def injected_fdopen(descriptor, *args, **kwargs):
                stream = real_fdopen(descriptor, *args, **kwargs)
                if descriptor != state.get("descriptor"):
                    return stream
                return _FaultyScopeStream(stream, prefix=prefix, close_failure=close_failure)

            with mock.patch.object(review_git.tempfile, "mkstemp", tracking_mkstemp):
                with mock.patch.object(review_git.os, "fdopen", injected_fdopen):
                    return fixtures.capture_cli(self.repo, output, "--mode", "workspace", "--path", "a.py")

        with self.subTest("F5 a capture publishes exactly one completion marker"):
            code, payload, packet = self.scope("--mode", "workspace", "--path", "a.py")
            self.assertEqual(0, code, payload)
            self.assertTrue((packet / "scope.json").is_file())
            self.assertEqual([], sorted(path.name for path in packet.glob(".scope-*")))
        for label, prefix, close_failure in (
            ("F5 a partial write leaves no completion marker", 10, False),
            ("F5 a failing close leaves no completion marker", None, True),
        ):
            with self.subTest(label):
                output = self.packet_dir("f5-faulty")
                code, payload = faulty_capture(output, prefix, close_failure)
                self.assertEqual(2, code, payload)
                self.assertEqual("E_OUTPUT", payload["code"])
                self.assertFalse((output / "scope.json").exists())
                self.assertEqual([], sorted(path.name for path in output.glob(".scope-*")))
        with self.subTest("F5 an existing completion marker is never overwritten"):
            source = fixtures.hand_packet(
                self.root,
                sources=[
                    {
                        "name": "one",
                        "path": "a.py",
                        "origin": "worktree",
                        "availability": "text",
                        "payload": b"a = 2\n",
                    }
                ],
                items=[
                    {
                        "layer": "worktree",
                        "status": "A",
                        "path": "a.py",
                        "before": None,
                        "after": "one",
                    }
                ],
                packet_name="f5-source",
            )
            target = self.packet_dir("f5-target")
            target.mkdir()
            marker = target / "scope.json"
            marker.write_bytes(b'{"kept": true}\n')
            with self.assertRaises(review_record.ReviewError) as caught:
                review_git._seal_scope(
                    target, source["scope"], self.repo, {"observation": "immutable_commits"}
                )
            self.assertEqual("E_OUTPUT", caught.exception.code)
            self.assertEqual(b'{"kept": true}\n', marker.read_bytes())
            self.assertEqual([], sorted(path.name for path in target.glob(".scope-*")))

    def _raw_diff_paths(self, raw: bytes) -> list[bytes]:
        tokens = raw.split(b"\0")
        return [tokens[index + 1] for index, token in enumerate(tokens) if token.startswith(b":")]


if __name__ == "__main__":
    unittest.main()
