"""Check passive skill assets, not model behavior or simplification quality."""

from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "code-simplifier"
LINK = re.compile(r"\]\(([^)]+)\)")
ORIGINAL_LICENSE_BLOBS = {
    "LICENSE": "d645695673349e3947e8e5ae42332d0ac3164cd7",
    "NOTICE": "e26b467d444fa7e3993c0c70a36b4d01f356cf2f",
    "licenses/SOURCE.txt": "04779c617c852725164b68ce1a11c4a369fb75bd",
    "licenses/pstack-MIT.txt": "6b5400237fdf6545be0b8fae370d6f2fcff8fb25",
}


class CodeSimplifierAssets(unittest.TestCase):
    def local_targets(self, document: Path) -> list[Path]:
        targets = []
        for match in LINK.finditer(document.read_text(encoding="utf-8")):
            raw = match.group(1).strip().strip("<>")
            url = urlsplit(raw)
            if url.scheme or url.netloc or not url.path:
                continue
            relative = Path(unquote(url.path))
            self.assertFalse(relative.is_absolute(), raw)
            self.assertNotIn("..", relative.parts, raw)
            target = document.parent / relative
            self.assertTrue(target.is_file(), f"{document.name}: {raw}")
            current = target
            while current != SKILL:
                self.assertFalse(current.is_symlink(), str(current))
                self.assertNotEqual(current, current.parent, raw)
                current = current.parent
            self.assertTrue(target.resolve().is_relative_to(SKILL.resolve()), raw)
            targets.append(target)
        return targets

    def test_skill_metadata_is_loadable(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match)
        frontmatter = yaml.safe_load(match.group(1))
        self.assertEqual(frontmatter["name"], "code-simplifier")
        self.assertIsInstance(frontmatter["description"], str)
        self.assertTrue(frontmatter["description"].strip())
        self.assertEqual(frontmatter["license"], "Apache-2.0")
        self.assertRegex(frontmatter["metadata"]["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(frontmatter["metadata"]["hosts"], ["codex", "hermes-agent"])

    def test_existing_invocation_policy_is_preserved(self) -> None:
        agents = yaml.safe_load((SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(agents), {"interface", "policy"})
        self.assertEqual(set(agents["policy"]), {"allow_implicit_invocation"})
        self.assertIs(agents["policy"]["allow_implicit_invocation"], True)
        self.assertIn("$code-simplifier", agents["interface"]["default_prompt"])
        self.assertEqual(agents["interface"]["display_name"], "Code Simplifier")

    def test_markdown_links_resolve_inside_skill(self) -> None:
        for document in SKILL.rglob("*.md"):
            with self.subTest(document=document.relative_to(SKILL).as_posix()):
                self.local_targets(document)

    def test_on_demand_references_are_reachable(self) -> None:
        pending = [SKILL / "SKILL.md"]
        visited = set()
        while pending:
            document = pending.pop()
            if document in visited:
                continue
            visited.add(document)
            pending.extend(p for p in self.local_targets(document) if p.suffix == ".md")
        references = set((SKILL / "references").glob("*.md"))
        self.assertTrue(references)
        self.assertTrue(references <= visited, f"unreachable references: {references - visited}")

    def test_upstream_license_assets_are_byte_identical(self) -> None:
        for relative, expected in ORIGINAL_LICENSE_BLOBS.items():
            with self.subTest(asset=relative):
                data = (SKILL / relative).read_bytes()
                digest = sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
                self.assertEqual(digest, expected)

    def test_module_contains_only_passive_text_assets(self) -> None:
        self.assertFalse(SKILL.is_symlink())
        for path in SKILL.rglob("*"):
            with self.subTest(path=path.relative_to(SKILL).as_posix()):
                self.assertFalse(path.is_symlink())
                if path.is_dir():
                    continue
                self.assertTrue(path.is_file())
                self.assertTrue(path.name in {"LICENSE", "NOTICE"} or path.suffix in {".md", ".yaml", ".txt"})
                self.assertFalse(path.stat().st_mode & 0o111)

    def test_text_assets_have_portable_encoding(self) -> None:
        for path in SKILL.rglob("*"):
            if not path.is_file():
                continue
            with self.subTest(path=path.relative_to(SKILL).as_posix()):
                data = path.read_bytes()
                data.decode("utf-8", errors="strict")
                self.assertTrue(data.endswith(b"\n"))
                self.assertNotIn(b"\r", data)
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\x00", data)


if __name__ == "__main__":
    unittest.main()
