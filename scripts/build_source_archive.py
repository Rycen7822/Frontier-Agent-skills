#!/usr/bin/env python3
"""Build deterministic clean bundle or four-skill source ZIP archives."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
from typing import Any, Literal
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES, inventory, tree_hash  # noqa: E402
from _deterministic_zip import (  # noqa: E402
    ZipMember,
    verify_deterministic_zip,
    write_deterministic_zip,
)
from build_codex_plugin import (  # noqa: E402
    _contains_forbidden_reader_marker,
    _strict_json,
    skill_version,
    validate_source,
)


Layout = Literal["bundle", "skills_only"]
EXPECTED_SKILLS = {
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
}
BUNDLE_ROOT_PREFIX = "frontier-engineering-bundle"
BUNDLE_DIRECTORIES = {"bundle", "evaluation", "packaging", "scripts", "tests"}
BUNDLE_FILES = {"README.md", "RELEASE_NOTES.md", "bundle-manifest.json", "frontier-engineering.bundle.json"}
IGNORED_TOP_LEVEL = {
    ".git",
    ".agents",
    ".gitignore",
    ".pytest_cache",
    ".ruff_cache",
    ".work",
    "CODEX_STATE.md",
    "share",
    "__pycache__",
    "dist",
    "tmp",
}
ARCHIVE_IGNORED_PARTS = FORBIDDEN_PARTS | {
    ".git", ".mypy_cache", ".ruff_cache", ".tox", ".venv", "venv", "htmlcov", "tmp"
}
GENERATED_NAMES = {".DS_Store", "coverage.xml", ".coverage"}
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".yaml", ".yml", ".py", ".template", ".toml"}
MAX_FILE_SIZE = 16 * 1024 * 1024
MAX_TOTAL_SIZE = 128 * 1024 * 1024


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _file_hash(path: Path) -> str:
    digest = sha256()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"archive input is not a regular file: {path}")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _is_generated(relative: Path) -> bool:
    return (
        any(part in ARCHIVE_IGNORED_PARTS for part in relative.parts)
        or relative.suffix in FORBIDDEN_SUFFIXES
        or relative.name in GENERATED_NAMES
    )


def _collect_directory(source_root: Path, directory: Path) -> list[Path]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"archive source directory is missing or symlinked: {directory.name}")
    result: list[Path] = []
    for path in directory.rglob("*"):
        relative = path.relative_to(source_root)
        if path.is_symlink():
            raise ValueError(f"symlink is forbidden in source archive: {relative.as_posix()}")
        if _is_generated(relative):
            continue
        if path.is_file():
            result.append(path)
        elif not path.is_dir():
            raise ValueError(f"non-regular source archive member: {relative.as_posix()}")
    return result


def _collect_source_files(source_root: Path, manifest: dict[str, Any], layout: Layout) -> list[Path]:
    skill_paths = {str(item["path"]) for item in manifest["skills"]}
    if skill_paths != EXPECTED_SKILLS:
        raise ValueError("bundle manifest must bind exactly the four canonical skill paths")
    allowed_names = skill_paths | BUNDLE_DIRECTORIES | BUNDLE_FILES
    if layout == "bundle":
        for child in source_root.iterdir():
            if child.name in allowed_names or child.name in IGNORED_TOP_LEVEL:
                continue
            raise ValueError(f"unclassified top-level source path would be omitted: {child.name}")
        files = [source_root / name for name in sorted(BUNDLE_FILES)]
        directories = sorted(skill_paths | BUNDLE_DIRECTORIES)
    else:
        files = []
        directories = sorted(skill_paths)
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"required bundle source file is missing or symlinked: {path.name}")
    result = list(files)
    for name in directories:
        result.extend(_collect_directory(source_root, source_root / name))
    if not result:
        raise ValueError("source archive selection is empty")
    return sorted(result)


def _validate_reader_paths(source_root: Path, records: list[dict[str, Any]]) -> None:
    for record in records:
        path = source_root / record["path"]
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        if _contains_forbidden_reader_marker(text):
            raise ValueError(f"developer absolute path in archive source: {record['path']}")


def _copy_snapshot(source_root: Path, staging_root: Path, records: list[dict[str, Any]]) -> None:
    for record in records:
        source = source_root / record["path"]
        destination = staging_root / record["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
    staged_paths = [staging_root / record["path"] for record in records]
    staged_records = inventory(staging_root, staged_paths)
    if staged_records != records:
        raise ValueError("staged source bytes or modes differ from the frozen source inventory")


def _archive_name(relative: str, layout: Layout) -> str:
    return f"{BUNDLE_ROOT_PREFIX}/{relative}" if layout == "bundle" else relative


def _archive_members(
    staging_root: Path,
    records: list[dict[str, Any]],
    layout: Layout,
) -> list[ZipMember]:
    return [
        (
            _archive_name(str(record["path"]), layout),
            staging_root / str(record["path"]),
            int(str(record["mode"]), 8),
        )
        for record in records
    ]


def _write_zip(path: Path, staging_root: Path, records: list[dict[str, Any]], layout: Layout) -> None:
    write_deterministic_zip(path, _archive_members(staging_root, records, layout))


def _verify_zip(path: Path, staging_root: Path, records: list[dict[str, Any]], layout: Layout) -> None:
    verify_deterministic_zip(path, _archive_members(staging_root, records, layout))


def _temporary_path(parent: Path, prefix: str) -> Path:
    descriptor, raw = tempfile.mkstemp(prefix=prefix, dir=parent)
    os.close(descriptor)
    return Path(raw)


def _unlink_same_inode(path: Path, expected: os.stat_result) -> None:
    try:
        observed = path.lstat()
    except FileNotFoundError:
        return
    if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
        raise RuntimeError(f"published output changed before rollback: {path.name}")
    path.unlink()


def _publish_pair(archive_temp: Path, output: Path, evidence_temp: Path, evidence_output: Path) -> None:
    archive_info = archive_temp.stat()
    published_archive = False

    def rollback_archive() -> None:
        if not published_archive:
            return
        _unlink_same_inode(output, archive_info)

    try:
        os.link(archive_temp, output)
        published_archive = True
        os.link(evidence_temp, evidence_output)
    except FileExistsError as exc:
        rollback_archive()
        raise ValueError("archive or evidence output already exists") from exc
    except OSError:
        rollback_archive()
        raise


def build_archive(
    source_root: Path,
    output: Path,
    evidence_output: Path,
    layout: Layout,
) -> dict[str, Any]:
    if layout not in ("bundle", "skills_only"):
        raise ValueError(f"unsupported source archive layout: {layout}")
    if source_root.is_symlink():
        raise ValueError("source root must not be a symlink")
    source_root = source_root.resolve(strict=True)
    if not source_root.is_dir():
        raise ValueError("source root must be a directory")
    output = output.absolute()
    evidence_output = evidence_output.absolute()
    if output == evidence_output or output.suffix.lower() != ".zip":
        raise ValueError("archive output must be a distinct .zip path")
    for path in (output, evidence_output):
        if path.exists() or path.is_symlink():
            raise ValueError(f"no-overwrite output already exists: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)

    manifest = _strict_json(source_root / "bundle-manifest.json")
    validate_source(source_root, manifest)
    selected = _collect_source_files(source_root, manifest, layout)
    records = inventory(source_root, selected)
    if len(records) != len(selected):
        raise ValueError("source inventory contains duplicate archive paths")
    total_size = sum(int(record["size"]) for record in records)
    if total_size > MAX_TOTAL_SIZE or any(int(record["size"]) > MAX_FILE_SIZE for record in records):
        raise ValueError("source archive exceeds bounded file or total size")
    _validate_reader_paths(source_root, records)

    skill_versions = {
        item["id"]: skill_version(source_root / item["path"])
        for item in manifest["skills"]
    }
    if set(skill_versions) != EXPECTED_SKILLS:
        raise ValueError("source archive skill identities differ from the canonical four-skill set")

    archive_temp = _temporary_path(output.parent, ".source-archive-")
    evidence_temp = _temporary_path(evidence_output.parent, ".source-archive-evidence-")
    try:
        with tempfile.TemporaryDirectory(prefix="source-archive-staging-") as directory:
            staging_root = Path(directory)
            _copy_snapshot(source_root, staging_root, records)
            after_records = inventory(source_root, selected)
            if after_records != records:
                raise ValueError("SOURCE_DRIFT: source changed while building the clean archive")
            _write_zip(archive_temp, staging_root, records, layout)
            _verify_zip(archive_temp, staging_root, records, layout)

        os.chmod(archive_temp, 0o644)
        evidence: dict[str, Any] = {
            "schema_version": "source-archive-evidence/2.0",
            "layout": layout,
            "bundle_version": manifest["bundle_version"],
            "root_prefix": BUNDLE_ROOT_PREFIX if layout == "bundle" else None,
            "skill_versions": skill_versions,
            "source_tree_hash": tree_hash(records),
            "archive_content_hash": _file_hash(archive_temp),
            "source_file_count": len(records),
            "archive_file_count": len(records),
            "source_revision_verified": False,
            "generated_artifacts_excluded": True,
            "files": records,
        }
        evidence["evidence_hash"] = _canonical_hash(evidence)
        with evidence_temp.open("w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(evidence_temp, 0o644)
        archive_info = archive_temp.stat()
        evidence_info = evidence_temp.stat()
        _publish_pair(archive_temp, output, evidence_temp, evidence_output)
        try:
            if _file_hash(output) != evidence["archive_content_hash"]:
                raise RuntimeError("published archive hash differs from evidence")
            if _file_hash(evidence_output) != _file_hash(evidence_temp):
                raise RuntimeError("published evidence bytes differ from the generated evidence")
        except (OSError, RuntimeError, ValueError):
            _unlink_same_inode(evidence_output, evidence_info)
            _unlink_same_inode(output, archive_info)
            raise
        return evidence
    finally:
        archive_temp.unlink(missing_ok=True)
        evidence_temp.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--layout", choices=("bundle", "skills_only"), default="bundle")
    args = parser.parse_args(argv)
    try:
        evidence = build_archive(args.source_root, args.output, args.evidence_output, args.layout)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "layout": evidence["layout"],
                "source_file_count": evidence["source_file_count"],
                "archive_content_hash": evidence["archive_content_hash"],
                "source_revision_verified": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
