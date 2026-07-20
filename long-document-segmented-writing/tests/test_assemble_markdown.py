from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "assemble_markdown.py"


class AssembleMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value: str | bytes) -> Path:
        path = self.root / name
        path.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)
        return path

    def run_cli(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *(str(value) for value in arguments)],
            text=True,
            capture_output=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def assert_error(self, result: subprocess.CompletedProcess[str], code: int, marker: str) -> None:
        self.assertEqual(code, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertTrue(result.stderr.startswith(marker + " "), result.stderr)
        self.assertEqual(1, len(result.stderr.splitlines()))

    def test_source_style_hash_binds_order_and_boundaries(self) -> None:
        first = self.write("a.md", "Alpha.\n")
        second = self.write("b.md", "βeta.\n")
        result = self.run_cli("--check-source-style", first, "--check-source-style", second)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        raw_first, raw_second = first.read_bytes(), second.read_bytes()
        digest = sha256(b"source-style-v1\0" + len(raw_first).to_bytes(8, "big") + raw_first + len(raw_second).to_bytes(8, "big") + raw_second)
        self.assertEqual(["status", "bytes", "sha256"], list(payload))
        self.assertEqual("source_style_valid", payload["status"])
        self.assertEqual(len(raw_first) + len(raw_second), payload["bytes"])
        self.assertEqual("sha256:" + digest.hexdigest(), payload["sha256"])
        reversed_result = self.run_cli("--check-source-style", second, "--check-source-style", first)
        self.assertNotEqual(payload["sha256"], json.loads(reversed_result.stdout)["sha256"])

    def test_plain_prose_hard_wrap_is_rejected(self) -> None:
        source = self.write("plain.md", "This sentence was\nwrapped arbitrarily.\n")
        self.assert_error(self.run_cli("--check-source-style", source), 2, "E_HARD_WRAP_PROSE")

    def test_list_continuation_hard_wrap_is_rejected(self) -> None:
        source = self.write("list.md", "- This list item was\ncontinued arbitrarily.\n")
        self.assert_error(self.run_cli("--check-source-style", source), 2, "E_HARD_WRAP_LIST")

    def test_blockquote_hard_wrap_is_rejected(self) -> None:
        source = self.write("quote.md", "> This quotation was\n> continued arbitrarily.\n")
        self.assert_error(self.run_cli("--check-source-style", source), 2, "E_HARD_WRAP_BLOCKQUOTE")

    def test_markdown_structures_and_unicode_are_valid(self) -> None:
        source = self.write(
            "valid.md",
            "# 标题\n\n一个完整的段落。\n\n- 第一项。\n- 第二项。\n\n| 名称 | 值 |\n|---|---|\n| α | β |\n\n```python\nvalue = 'a'\nvalue += 'b'\n```\n",
        )
        result = self.run_cli("--check-source-style", source)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_table_without_outer_pipes_is_valid(self) -> None:
        source = self.write("table.md", "Name | Value\n--- | ---\nalpha | beta\ngamma | delta\n")
        result = self.run_cli("--check-source-style", source)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_crlf_empty_non_utf8_and_unclosed_fence_are_rejected(self) -> None:
        cases = [
            ("crlf.md", b"Text.\r\n", "E_CRLF"),
            ("empty.md", b"\n\n", "E_EMPTY"),
            ("utf8.md", b"\xff", "E_UTF8"),
            ("fence.md", b"```text\nvalue\n", "E_UNCLOSED_FENCE"),
        ]
        for name, content, marker in cases:
            with self.subTest(marker=marker):
                self.assert_error(self.run_cli("--check-source-style", self.write(name, content)), 2, marker)

    def test_symlink_and_duplicate_inputs_are_rejected(self) -> None:
        source = self.write("source.md", "Text.\n")
        link = self.root / "link.md"
        link.symlink_to(source)
        self.assert_error(self.run_cli("--check-source-style", link), 2, "E_SYMLINK")
        output = self.root / "output.md"
        self.assert_error(self.run_cli("--section", source, "--section", source, "--output", output), 2, "E_DUPLICATE")

    def test_assembly_preserves_content_and_canonicalizes_boundaries(self) -> None:
        first = self.write("00.md", "# One\n\nText with trailing spaces.  \n\n\n")
        second = self.write("01.md", "# Two\n\nβ.\n")
        output = self.root / "final.md"
        result = self.run_cli("--section", first, "--section", second, "--output", output)
        self.assertEqual(0, result.returncode, result.stderr)
        expected = "# One\n\nText with trailing spaces.  \n\n# Two\n\nβ.\n".encode()
        self.assertEqual(expected, output.read_bytes())
        payload = json.loads(result.stdout)
        self.assertEqual("written", payload["status"])
        self.assertEqual(len(expected), payload["bytes"])
        self.assertEqual("sha256:" + sha256(expected).hexdigest(), payload["sha256"])

    def test_identical_replay_is_zero_write_and_check_is_read_only(self) -> None:
        source = self.write("section.md", "# Heading\n\nText.\n")
        output = self.root / "final.md"
        first = self.run_cli("--section", source, "--output", output)
        self.assertEqual(0, first.returncode, first.stderr)
        before = output.stat()
        second = self.run_cli("--section", source, "--output", output)
        after = output.stat()
        self.assertEqual("unchanged", json.loads(second.stdout)["status"])
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        checked = self.run_cli("--section", source, "--output", output, "--check")
        final = output.stat()
        self.assertEqual("valid", json.loads(checked.stdout)["status"])
        self.assertEqual((after.st_ino, after.st_mtime_ns), (final.st_ino, final.st_mtime_ns))

    def test_check_mismatch_and_missing_output_return_one(self) -> None:
        source = self.write("section.md", "Text.\n")
        output = self.write("final.md", "Different.\n")
        self.assert_error(self.run_cli("--section", source, "--output", output, "--check"), 1, "E_OUTPUT_MISMATCH")
        output.unlink()
        self.assert_error(self.run_cli("--section", source, "--output", output, "--check"), 1, "E_OUTPUT_MISSING")

    def test_invalid_mode_combinations_are_rejected(self) -> None:
        source = self.write("section.md", "Text.\n")
        output = self.root / "final.md"
        for arguments in [(), ("--section", source), ("--check-source-style", source, "--output", output)]:
            with self.subTest(arguments=arguments):
                self.assert_error(self.run_cli(*arguments), 2, "E_ARGUMENT")

    def test_output_directory_has_no_sidecars(self) -> None:
        source = self.write("section.md", "Text.\n")
        output_dir = self.root / "output"
        output_dir.mkdir()
        output = output_dir / "final.md"
        result = self.run_cli("--section", source, "--output", output)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["final.md"], sorted(path.name for path in output_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
