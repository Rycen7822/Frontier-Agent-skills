"""Canonical controller artifacts, hashes, paths, and atomic writes."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any


class StateError(RuntimeError):
    """Controller state is missing, inconsistent, or unauthorized."""


HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + sha256(canonical_bytes(value)).hexdigest()


def raw_hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    return raw_hash(assert_nofollow(path, kind="file").read_bytes())


def require_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or HASH_PATTERN.fullmatch(value) is None:
        raise StateError(f"{field} must be a canonical SHA256")
    return value


def require_nonempty(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or value != value.strip()
    ):
        raise StateError(f"{field} must be a canonical non-empty string")
    return value


def strict_json_loads(raw: bytes | str, source: Path | str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        text = raw.decode("utf-8", errors="strict") if isinstance(raw, bytes) else raw
        return json.loads(
            text,
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise StateError(f"invalid JSON state: {source}: {exc}") from None


def json_object(raw: bytes | str, source: Path | str) -> dict[str, Any]:
    value = strict_json_loads(raw, source)
    if not isinstance(value, dict):
        raise StateError(f"JSON state is not an object: {source}")
    return value


def _path_parts(path: Path) -> list[Path]:
    absolute = path.absolute()
    parts: list[Path] = []
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        parts.append(current)
    return parts


def assert_nofollow(
    path: Path,
    *,
    allow_absent_leaf: bool = False,
    kind: str | None = None,
) -> Path:
    """Reject symlinks in every component and optionally permit an absent leaf."""
    absolute = path.absolute()
    parts = _path_parts(absolute)
    for position, component in enumerate(parts):
        leaf = position == len(parts) - 1
        try:
            status = component.lstat()
        except FileNotFoundError:
            if leaf and allow_absent_leaf:
                return absolute
            raise StateError(f"path component is absent: {component}") from None
        if component.is_symlink():
            raise StateError(f"symlink path component is forbidden: {component}")
        if not leaf and not component.is_dir():
            raise StateError(f"intermediate component is not a directory: {component}")
        if leaf and kind == "file" and (
            not component.is_file() or status.st_nlink != 1
        ):
            raise StateError(f"expected single-link regular file: {component}")
        if leaf and kind == "directory" and not component.is_dir():
            raise StateError(f"expected directory: {component}")
    return absolute


def atomic_write(
    path: Path,
    payload: bytes,
    mode: int = 0o600,
    *,
    replace: bool = True,
) -> None:
    target = assert_nofollow(path, allow_absent_leaf=True)
    parent = assert_nofollow(target.parent, kind="directory")
    target_mode = mode
    if target.exists():
        status = assert_nofollow(target, kind="file").stat(
            follow_symlinks=False,
        )
        if replace:
            target_mode = stat.S_IMODE(status.st_mode)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=parent,
    )
    temp_path = Path(temp_name)
    try:
        os.fchmod(descriptor, target_mode)
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp_path, target)
        else:
            try:
                os.link(temp_path, target, follow_symlinks=False)
            except FileExistsError:
                raise StateError(
                    f"no-overwrite destination appeared: {target}"
                ) from None
            staged_status = temp_path.stat(follow_symlinks=False)
            target_status = target.stat(follow_symlinks=False)
            if (
                staged_status.st_dev,
                staged_status.st_ino,
            ) != (
                target_status.st_dev,
                target_status.st_ino,
            ):
                raise StateError(f"published file ownership differs: {target}")
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        if target.read_bytes() != payload:
            raise StateError(f"post-write verification failed: {target}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, canonical_bytes(value) + b"\n")


def write_or_verify_json(path: Path, value: dict[str, Any]) -> None:
    payload = canonical_bytes(value) + b"\n"
    target = assert_nofollow(path, allow_absent_leaf=True)
    if target.exists():
        if assert_nofollow(target, kind="file").read_bytes() != payload:
            raise StateError(f"artifact changed during resume: {target}")
        return
    atomic_write(target, payload, replace=False)


def load_json(path: Path) -> dict[str, Any]:
    target = assert_nofollow(path, kind="file")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise StateError(f"invalid JSON state: {target}: {exc}") from None
    value = strict_json_loads(raw, target)
    if not isinstance(value, dict):
        raise StateError(f"JSON state is not an object: {target}")
    if raw != canonical_bytes(value) + b"\n":
        raise StateError(f"JSON state bytes are not canonical: {target}")
    return value


def self_hashed(value: dict[str, Any], field: str) -> dict[str, Any]:
    payload = dict(value)
    payload[field] = canonical_hash(
        {key: item for key, item in payload.items() if key != field},
    )
    return payload


def verify_self_hash(value: dict[str, Any], field: str) -> None:
    if value.get(field) != canonical_hash(
        {key: item for key, item in value.items() if key != field},
    ):
        raise StateError(f"{field} verification failed")


def artifact_binding(path: Path, root: Path) -> dict[str, str]:
    target = assert_nofollow(path, kind="file")
    base = assert_nofollow(root, kind="directory")
    try:
        relative = target.relative_to(base)
    except ValueError:
        raise StateError(f"artifact is outside its root: {target}") from None
    return {"path": relative.as_posix(), "sha256": file_hash(target)}


def contained_file(root: Path, relative: str, label: str) -> Path:
    base = assert_nofollow(root, kind="directory")
    child = Path(relative)
    if child.is_absolute() or ".." in child.parts:
        raise StateError(f"{label} path is outside its root")
    try:
        return assert_nofollow(base / child, kind="file")
    except (OSError, StateError) as exc:
        raise StateError(f"{label} is unavailable: {exc}") from None


def verified_artifact(
    root: Path,
    binding: dict[str, Any],
    label: str,
    *,
    prefix: str = "",
) -> Path:
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise StateError(f"{label} binding is invalid")
    relative = (Path(prefix) / binding["path"]).as_posix()
    path = contained_file(root, relative, label)
    if file_hash(path) != binding.get("sha256"):
        raise StateError(f"{label} hash differs")
    return path


def regular_files(root: Path) -> list[Path]:
    base = assert_nofollow(root, kind="directory")
    files = []
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            raise StateError(f"artifact tree contains a symlink: {path}")
        if path.is_file():
            files.append(assert_nofollow(path, kind="file"))
    return files


def portable_inventory(
    root: Path,
    paths: list[Path],
) -> list[dict[str, Any]]:
    base = assert_nofollow(root, kind="directory")
    inventory = []
    for path in paths:
        target = assert_nofollow(path, kind="file")
        try:
            relative = target.relative_to(base)
        except ValueError:
            raise StateError(f"artifact is outside its root: {target}") from None
        inventory.append({
            "path": relative.as_posix(),
            "content_hash": file_hash(target),
            "size": target.stat().st_size,
            "mode": "0755" if target.stat().st_mode & stat.S_IXUSR else "0644",
        })
    return inventory


def portable_tree_inventory(root: Path) -> list[dict[str, Any]]:
    base = assert_nofollow(root, kind="directory")
    return portable_inventory(base, regular_files(base))


def tree_hash(root: Path) -> str:
    return canonical_hash(portable_tree_inventory(root))


def bundle_source_hash(root: Path, expected_skills: set[str]) -> str:
    base = assert_nofollow(root, kind="directory")
    manifest_path = contained_file(
        base,
        "bundle-manifest.json",
        "bundle manifest",
    )
    manifest = json_object(manifest_path.read_bytes(), manifest_path)
    skills = manifest.get("skills")
    if (
        not isinstance(skills, list)
        or {
            item.get("id") for item in skills if isinstance(item, dict)
        }
        != expected_skills
        or any(
            not isinstance(item, dict)
            or item.get("path") != item.get("id")
            for item in skills
        )
    ):
        raise StateError("bundle source manifest differs")
    paths = [manifest_path]
    for item in skills:
        paths.extend(regular_files(base / item["path"]))
    return canonical_hash(portable_inventory(base, sorted(paths)))


def git_read(repo: Path, *arguments: str) -> str:
    if not arguments or arguments[0] not in {
        "status",
        "verify-commit",
        "rev-parse",
        "branch",
    }:
        raise StateError("git proof command is not read-only")
    root = assert_nofollow(repo, kind="directory")
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        raise StateError(
            f"git {arguments[0]} failed: {completed.stderr.strip()[:1000]}"
        )
    return completed.stdout.strip()


def signed_clean_revision(repo: Path) -> dict[str, str]:
    if git_read(repo, "status", "--porcelain=v2", "--untracked-files=all"):
        raise StateError("candidate source worktree must be clean")
    git_read(repo, "verify-commit", "HEAD")
    return {
        "candidate_revision": git_read(repo, "rev-parse", "HEAD"),
        "git_tree": git_read(repo, "rev-parse", "HEAD^{tree}"),
        "branch": git_read(repo, "branch", "--show-current"),
    }


def verify_unique_files(roots: list[Path]) -> None:
    observed: set[tuple[int, int]] = set()
    for root in roots:
        base = assert_nofollow(root, kind="directory")
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                raise StateError("artifact graph contains a symlink")
            if not path.is_file():
                continue
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                metadata = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            identity = (metadata.st_dev, metadata.st_ino)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or identity in observed
            ):
                raise StateError("artifact graph is hardlinked or reuses an inode")
            observed.add(identity)
