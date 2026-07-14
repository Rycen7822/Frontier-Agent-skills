#!/usr/bin/env python3
"""Canonical source and plugin inventory hashing for local bundle tooling."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterable


FORBIDDEN_PARTS = {"__pycache__", ".pytest_cache", ".closure", ".workflow", "dist"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def _content_hash(path: Path) -> tuple[str, int, str]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"inventory member is not a regular file: {path}")
        digest = sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        mode = "0755" if info.st_mode & stat.S_IXUSR else "0644"
        return "sha256:" + digest.hexdigest(), size, mode
    finally:
        os.close(descriptor)


def inventory(root: Path, paths: Iterable[Path]) -> list[dict[str, Any]]:
    resolved_root = root.resolve(strict=True)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(paths):
        try:
            relative_path = path.relative_to(root)
            relative = relative_path.as_posix()
        except ValueError as exc:
            raise ValueError(f"inventory path escapes root: {path}") from exc
        if relative in seen:
            continue
        seen.add(relative)
        if any(part in FORBIDDEN_PARTS for part in Path(relative).parts) or path.suffix in FORBIDDEN_SUFFIXES:
            raise ValueError(f"forbidden generated path in inventory: {relative}")
        current = resolved_root
        for index, part in enumerate(relative_path.parts):
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise ValueError(f"symlink or path substitution is forbidden in inventory: {relative}")
            if index < len(relative_path.parts) - 1 and not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"non-directory path component in inventory: {relative}")
        content_hash, size, mode = _content_hash(current)
        records.append({"path": relative, "content_hash": content_hash, "size": size, "mode": mode})
    return records


def bundle_inventory(source_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    paths: list[Path] = [source_root / "bundle-manifest.json"]
    skills = manifest.get("skills")
    if not isinstance(skills, list):
        raise ValueError("manifest skills must be an array")
    for item in skills:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("manifest skill entry is invalid")
        skill = source_root / item["path"]
        if skill.is_symlink() or not skill.is_dir() or not skill.resolve(strict=True).is_relative_to(source_root.resolve(strict=True)):
            raise ValueError(f"skill path is missing, symlinked, or escapes source root: {item.get('path')}")
        paths.extend(path for path in skill.rglob("*") if path.is_file() or path.is_symlink())
    return inventory(source_root, paths)


def tree_hash(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()
