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
SPEC = importlib.util.spec_from_file_location("build_source_archive", ARCHIVER_PATH)
assert SPEC is not None and SPEC.loader is not None
archiver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archiver)


class SourceArchiveTests(unittest.TestCase):
    def _validate_evidence(self, evidence: dict[str, object]) -> None:
        schema = json.loads(
            (ROOT / "packaging" / "schemas" / "source-archive-evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        self.assertEqual([], list(Draft202012Validator(schema).iter_errors(evidence)))
        self.assertEqual("source-archive-evidence/2.0", evidence["schema_version"])
        unhashed = deepcopy(evidence)
        observed_hash = unhashed.pop("evidence_hash")
        self.assertEqual(
            observed_hash,
            "sha256:"
            + sha256(
                json.dumps(unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

    def test_bundle_archive_is_deterministic_clean_and_schema_valid(self) -> None:
        observed = []
        archives = []
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            for index in range(2):
                output = parent / f"bundle-{index}.zip"
                evidence_path = parent / f"bundle-{index}.evidence.json"
                evidence = archiver.build_archive(ROOT, output, evidence_path, "bundle")
                self._validate_evidence(evidence)
                self.assertEqual(evidence, json.loads(evidence_path.read_text(encoding="utf-8")))
                observed.append(evidence)
                archives.append(output.read_bytes())
                with zipfile.ZipFile(output) as archive:
                    names = archive.namelist()
                    self.assertEqual(evidence["archive_file_count"], len(names))
                    self.assertTrue(all(name.startswith("frontier-engineering-bundle/") for name in names))
                    self.assertFalse(any("__pycache__" in name or "/dist/" in name or "/.closure/" in name for name in names))
                    self.assertFalse(
                        any(
                            part in {".git", ".work", "tmp"} or part == "CODEX_STATE.md"
                            for name in names
                            for part in Path(name).parts
                        )
                    )
                    self.assertIn(
                        "frontier-engineering-bundle/bundle-manifest.json",
                        names,
                    )
                    self.assertIn(
                        "frontier-engineering-bundle/frontier-engineering.bundle.json",
                        names,
                    )
                    self.assertIn(
                        "frontier-engineering-bundle/bundle/frontier-engineering-bundle.schema.json",
                        names,
                    )
            self.assertEqual(observed[0], observed[1])
            self.assertEqual(archives[0], archives[1])

    def test_known_repository_metadata_is_ignored_but_unknown_top_level_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            copied = parent / "bundle"
            shutil.copytree(
                ROOT,
                copied,
                ignore=shutil.ignore_patterns(
                    ".git", ".work", "CODEX_STATE.md", "__pycache__", ".pytest_cache", "dist"
                ),
            )
            (copied / ".work").mkdir()
            (copied / ".work" / "local-note.md").write_text(
                "/" + "home" + "/developer/private\n", encoding="utf-8"
            )
            (copied / "CODEX_STATE.md").write_text("local state\n", encoding="utf-8")
            (copied / "tmp").mkdir()
            (copied / "tmp" / "scratch.json").write_text("{}\n", encoding="utf-8")

            archiver.build_archive(copied, parent / "clean.zip", parent / "clean.json", "bundle")

            (copied / "unexpected-source.txt").write_text("must not be silently omitted\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unclassified top-level source path"):
                archiver.build_archive(copied, parent / "bad.zip", parent / "bad.json", "bundle")

    def test_skills_only_archive_contains_exactly_the_two_skill_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "skills.zip"
            evidence_path = parent / "skills.evidence.json"
            evidence = archiver.build_archive(ROOT, output, evidence_path, "skills_only")
            self._validate_evidence(evidence)
            self.assertIsNone(evidence["root_prefix"])
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
            roots = {Path(name).parts[0] for name in names}
            self.assertEqual({"writing-plans", "software-quality-workflows"}, roots)
            self.assertNotIn("README.md", names)
            self.assertIn("writing-plans/SKILL.md", names)
            self.assertIn("software-quality-workflows/SKILL.md", names)

    def test_no_overwrite_symlink_and_source_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            output = parent / "bundle.zip"
            evidence = parent / "evidence.json"
            archiver.build_archive(ROOT, output, evidence, "bundle")
            with self.assertRaisesRegex(ValueError, "no-overwrite"):
                archiver.build_archive(ROOT, output, parent / "other-evidence.json", "bundle")

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            copied = parent / "bundle"
            shutil.copytree(
                ROOT,
                copied,
                ignore=shutil.ignore_patterns(
                    ".git", ".work", "CODEX_STATE.md", "__pycache__", ".pytest_cache", "dist"
                ),
            )
            target = copied / "writing-plans" / "references" / "profiles" / "brief.md"
            target.unlink()
            target.symlink_to(copied / "README.md")
            with self.assertRaisesRegex(ValueError, "symlink"):
                archiver.build_archive(copied, parent / "symlink.zip", parent / "symlink.json", "bundle")

            target.unlink()
            shutil.copy2(ROOT / "writing-plans" / "references" / "profiles" / "brief.md", target)
            original_copy = archiver.shutil.copy2
            changed = False

            def drifting_copy(source: Path, destination: Path, *args: object, **kwargs: object) -> Path:
                nonlocal changed
                result = original_copy(source, destination, *args, **kwargs)
                if not changed:
                    changed = True
                    mutation = copied / "README.md"
                    mutation.write_text(mutation.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
                return result

            with mock.patch.object(archiver.shutil, "copy2", side_effect=drifting_copy):
                with self.assertRaisesRegex(ValueError, "SOURCE_DRIFT"):
                    archiver.build_archive(copied, parent / "drift.zip", parent / "drift.json", "bundle")
            self.assertFalse((parent / "drift.zip").exists())
            self.assertFalse((parent / "drift.json").exists())


if __name__ == "__main__":
    unittest.main()
