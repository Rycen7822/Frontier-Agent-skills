from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
SUPPORT_MAP = Path("references/package-support-map.md")
SUPPORT_ROOTS = ("references", "registries", "schemas", "scripts", "templates", "operator", "tests")
ENTRY_RE = re.compile(
    r"^- \[`(?P<path>[^`]+)` · `sha256:(?P<sha>[0-9a-f]{64})`\]\((?P<target>[^)]+)\)$"
)


class PackageSupportMapTests(unittest.TestCase):
    def _run_builder(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(root / "scripts" / "build_reference_manifest.py"), *arguments],
            cwd=root,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )

    def _generated_copy(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="sqw-support-map-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "skill"
        shutil.copytree(
            ROOT,
            root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        completed = self._run_builder(root)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertTrue((root / SUPPORT_MAP).is_file(), "builder did not generate the support map")
        return root

    @staticmethod
    def _inventory(root: Path) -> dict[str, str]:
        inventory: dict[str, str] = {}
        for top_level in SUPPORT_ROOTS:
            support_root = root / top_level
            if not support_root.exists():
                continue
            for path in sorted(support_root.rglob("*")):
                relative = path.relative_to(root)
                if path.is_symlink() or "__pycache__" in relative.parts:
                    continue
                if path.is_file() and relative != SUPPORT_MAP and path.suffix not in {".pyc", ".pyo"}:
                    inventory[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return inventory

    def _assert_map_exact(self, root: Path) -> None:
        map_path = root / SUPPORT_MAP
        observed: dict[str, str] = {}
        for line in map_path.read_text(encoding="utf-8").splitlines():
            match = ENTRY_RE.fullmatch(line)
            if match is None:
                continue
            label_path = match.group("path")
            target = (map_path.parent / unquote(match.group("target"))).resolve()
            self.assertTrue(target.is_relative_to(root.resolve()), line)
            self.assertTrue(target.is_file(), line)
            self.assertEqual(label_path, target.relative_to(root.resolve()).as_posix())
            observed[label_path] = match.group("sha")
        self.assertEqual(self._inventory(root), observed)
        self.assertNotIn(SUPPORT_MAP.as_posix(), observed)

    def test_generated_map_is_current_exact_linked_and_not_preloaded(self) -> None:
        completed = self._run_builder(ROOT, "--check")
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertTrue((ROOT / SUPPORT_MAP).is_file())
        skill_entry = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("](references/package-support-map.md)", skill_entry)
        self.assertIn("do not preload", skill_entry.lower())
        self._assert_map_exact(ROOT)

    def test_entrypoint_pair_stays_within_the_frozen_budget(self) -> None:
        writing_entry = ROOT.parent / "writing-plans" / "SKILL.md"
        self.assertLessEqual(
            writing_entry.stat().st_size + (ROOT / "SKILL.md").stat().st_size,
            12500,
        )

    def test_inventory_and_link_drift_fail_closed(self) -> None:
        def first_operator_file(root: Path) -> Path:
            return next(path for path in sorted((root / "operator").rglob("*")) if path.is_file())

        for case in ("missing-file", "new-file", "hash-drift", "missing-link", "escaping-link"):
            with self.subTest(case=case):
                root = self._generated_copy()
                if case == "missing-file":
                    first_operator_file(root).unlink()
                elif case == "new-file":
                    (root / "operator" / "task3-new-support.txt").write_text("new\n", encoding="utf-8")
                elif case == "hash-drift":
                    target = first_operator_file(root)
                    target.write_bytes(target.read_bytes() + b"\n")
                else:
                    map_path = root / SUPPORT_MAP
                    replacement = "missing-task3.md" if case == "missing-link" else "../../outside-task3.md"
                    lines = map_path.read_text(encoding="utf-8").splitlines()
                    entry_index = next(index for index, line in enumerate(lines) if ENTRY_RE.fullmatch(line))
                    lines[entry_index] = re.sub(r"\([^)]+\)$", f"({replacement})", lines[entry_index])
                    map_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                completed = self._run_builder(root, "--check")
                self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
                self.assertIn("SUPPORT_MAP_STALE", completed.stdout)


if __name__ == "__main__":
    unittest.main()
