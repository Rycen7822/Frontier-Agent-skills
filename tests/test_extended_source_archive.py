from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import zipfile

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
ARCHIVER_PATH = ROOT / "scripts" / "build_source_archive.py"
EXPECTED_SKILLS = {
    "long-document-segmented-writing", "skill-evaluator",
    "software-quality-workflows", "writing-plans",
}


def load_archiver():
    spec = importlib.util.spec_from_file_location("extended_source_archiver", ARCHIVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load source archiver")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExtendedSourceArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.archiver = load_archiver()

    def assert_valid_evidence(self, evidence: dict) -> None:
        schema = json.loads((ROOT / "packaging" / "schemas" / "source-archive-evidence.schema.json").read_text())
        Draft202012Validator(schema).validate(evidence)
        unhashed = deepcopy(evidence)
        observed = unhashed.pop("evidence_hash")
        expected = "sha256:" + sha256(json.dumps(
            unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        self.assertEqual(expected, observed)

    def test_bundle_archive_is_reproducible_clean_and_schema_valid(self) -> None:
        self.assertTrue({".worktrees", "reference"} <= self.archiver.IGNORED_TOP_LEVEL)
        archives = []
        evidences = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for ordinal in range(2):
                output = root / f"bundle-{ordinal}.zip"
                evidence_path = root / f"bundle-{ordinal}.json"
                evidence = self.archiver.build_archive(ROOT, output, evidence_path, "bundle")
                self.assert_valid_evidence(evidence)
                archives.append(output.read_bytes())
                evidences.append(evidence)
                with zipfile.ZipFile(output) as archive:
                    names = archive.namelist()
                self.assertTrue(all(name.startswith("frontier-engineering-bundle/") for name in names))
                self.assertFalse(any("__pycache__" in name or "/.work/" in name for name in names))
            self.assertEqual(archives[0], archives[1])
            self.assertEqual(evidences[0], evidences[1])

    def test_skills_only_contains_exactly_four_skill_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "skills.zip"
            evidence = self.archiver.build_archive(ROOT, output, root / "skills.json", "skills_only")
            self.assert_valid_evidence(evidence)
            with zipfile.ZipFile(output) as archive:
                roots = {Path(name).parts[0] for name in archive.namelist()}
            self.assertEqual(EXPECTED_SKILLS, roots)

    def test_no_overwrite_symlink_and_source_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "bundle.zip"
            evidence = root / "bundle.json"
            self.archiver.build_archive(ROOT, output, evidence, "bundle")
            with self.assertRaisesRegex(ValueError, "no-overwrite"):
                self.archiver.build_archive(ROOT, output, root / "other.json", "bundle")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / "source"
            shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns(
                ".git", ".work", ".worktrees", "reference", "CODEX_STATE.md",
                "__pycache__", ".pytest_cache", "dist",
            ))
            target = copied / "writing-plans" / "tests" / "test_quick_skill_contract.py"
            target.unlink()
            target.symlink_to(copied / "README.md")
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.archiver.build_archive(copied, root / "symlink.zip", root / "symlink.json", "bundle")

            target.unlink()
            shutil.copy2(ROOT / "writing-plans" / "tests" / "test_quick_skill_contract.py", target)
            original_copy = self.archiver.shutil.copy2
            changed = False

            def drifting_copy(source: Path, destination: Path, *args: object, **kwargs: object) -> Path:
                nonlocal changed
                result = original_copy(source, destination, *args, **kwargs)
                if not changed:
                    changed = True
                    mutation = copied / "README.md"
                    mutation.write_text(mutation.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
                return result

            with mock.patch.object(self.archiver.shutil, "copy2", side_effect=drifting_copy):
                with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
                    self.archiver.build_archive(copied, root / "drift.zip", root / "drift.json", "bundle")
            self.assertFalse((root / "drift.zip").exists())
            self.assertFalse((root / "drift.json").exists())


if __name__ == "__main__":
    unittest.main()
