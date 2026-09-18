"""Git and workspace capture for the review helper.

Every Git invocation goes through :func:`run_git`, and captured facts keep the
commit, index, worktree, and untracked layers separate. This module captures
sources and compares them later; it never judges a defect.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Iterable

from _review_record import (
    CAPTURED_AVAILABILITY,
    LAYER_ORDER,
    MAX_FILE_BYTES,
    MAX_ITEMS,
    MAX_PACKET_BYTES,
    ReviewError,
    SCOPE_FILE,
    SCOPE_SCHEMA_VERSION,
    TEXT_AVAILABILITY,
    count_lines,
    dedupe_texts,
    encode_document,
    sha256_digest,
    validate_scope,
)

GIT_TIMEOUT_SECONDS = 30
GIT_OUTPUT_LIMIT = 32 * 1024 * 1024
GIT_ERROR_EXCERPT = 400
WORKTREE_REVISION = "WORKTREE"
MAX_REVISION_CHARACTERS = 128
GLOB_CHARACTERS = ("*", "?", "[")
IGNORED_UNTRACKED_LIMIT = (
    "Git-ignored untracked files are outside the enumerated scope; enumeration "
    "is not widened for them."
)
CLEARED_ENVIRONMENT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_NAMESPACE",
    "GIT_PREFIX",
    "GIT_CEILING_DIRECTORIES",
)


@dataclass(frozen=True)
class ScopeRequest:
    """A parsed scope request with no process, cache, or output state."""

    mode: str
    paths: tuple[str, ...]
    context_paths: tuple[str, ...] = ()
    base: str | None = None
    head: str | None = None
    commit: str | None = None
    revision: str | None = None


def validate_request(request: ScopeRequest) -> None:
    """Reject literal-path and mode-matrix violations before any Git call."""
    if request.mode not in ("commit", "range", "workspace", "snapshot"):
        raise ReviewError("E_ARGS", f"unknown scope mode {request.mode!r}")
    if not request.paths:
        raise ReviewError("E_ARGS", "at least one path is required")
    required = {
        "commit": ("commit",),
        "range": ("base", "head"),
        "workspace": (),
        "snapshot": ("revision",),
    }[request.mode]
    forbidden = {
        "commit": ("base", "head", "revision"),
        "range": ("commit", "revision"),
        "workspace": ("base", "head", "commit", "revision"),
        "snapshot": ("base", "head", "commit"),
    }[request.mode]
    for name in required:
        if getattr(request, name) is None:
            raise ReviewError("E_ARGS", f"mode {request.mode} requires --{name}")
    for name in forbidden:
        if getattr(request, name) is not None:
            raise ReviewError(
                "E_ARGS", f"mode {request.mode} does not accept --{name}"
            )
    for path in request.paths:
        _validate_literal_path(path, "path")
    for path in request.context_paths:
        _validate_literal_path(path, "context path")
    for name in ("base", "head", "commit", "revision"):
        value = getattr(request, name)
        if value is not None:
            _validate_revision(value, name)


def _validate_revision(revision: str, label: str) -> None:
    """Reject revisions the record schema cannot carry, before any Git call."""
    if not revision.strip():
        raise ReviewError("E_REVISION", f"--{label} is empty or only whitespace")
    if len(revision) > MAX_REVISION_CHARACTERS:
        raise ReviewError(
            "E_REVISION",
            f"--{label} holds {len(revision)} characters, over the "
            f"{MAX_REVISION_CHARACTERS} limit",
        )


def _validate_literal_path(path: str, label: str) -> None:
    if not path:
        raise ReviewError("E_PATH_INVALID", f"the {label} is empty")
    if "\x00" in path:
        raise ReviewError("E_PATH_INVALID", f"the {label} contains a NUL byte")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in path):
        raise ReviewError("E_PATH_ENCODING", f"the {label} is not decodable UTF-8 text")
    if len(path.encode("utf-8")) > 4096:
        raise ReviewError("E_PATH_INVALID", f"the {label} exceeds 4096 UTF-8 bytes")
    if path.startswith("/"):
        raise ReviewError("E_PATH_INVALID", f"the {label} {path!r} is absolute")
    if any(character in path for character in GLOB_CHARACTERS):
        raise ReviewError("E_PATH_INVALID", f"the {label} {path!r} looks like a glob")
    components = path.split("/")
    if ".." in components:
        raise ReviewError(
            "E_PATH_INVALID", f"the {label} {path!r} contains a parent component"
        )
    if ".git" in components:
        raise ReviewError(
            "E_PATH_INVALID", f"the {label} {path!r} addresses repository metadata"
        )


def _clean_environment() -> dict[str, str]:
    """Drop inherited repository redirection and pin offline, locale, and lock settings."""
    env = dict(os.environ)
    for name in CLEARED_ENVIRONMENT:
        env.pop(name, None)
    for name in [
        key for key in env if key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
    ]:
        env.pop(name, None)
    env["LC_ALL"] = "C"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_NO_LAZY_FETCH"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_git(
    repo: Path,
    argv: list[str],
    *,
    limit: int = GIT_OUTPUT_LIMIT,
    allow_failure: bool = False,
) -> bytes | None:
    """Run one Git command with a fixed read-only configuration.

    Returns stdout, or None when ``allow_failure`` is set and Git exits non-zero.
    """
    if shutil.which("git") is None:
        raise ReviewError("E_DEPENDENCY", "the git executable is not available")
    command = [
        "git",
        "-C",
        str(repo),
        "-c",
        "core.fsmonitor=false",
        "-c",
        "diff.renames=false",
        "--literal-pathspecs",
        *argv,
    ]
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            completed = subprocess.run(
                command,
                env=_clean_environment(),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                timeout=GIT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReviewError(
                "E_GIT_TIMEOUT",
                f"git {argv[0]} did not finish within {GIT_TIMEOUT_SECONDS} seconds",
            ) from exc
        except OSError as exc:
            raise ReviewError("E_DEPENDENCY", f"cannot run git: {exc.strerror}") from exc
        out.seek(0)
        stdout = out.read(limit + 1)
        err.seek(0)
        stderr = err.read(GIT_ERROR_EXCERPT + 1)
    if completed.returncode != 0:
        if allow_failure:
            return None
        excerpt = stderr.decode("utf-8", "replace").strip().splitlines()
        detail = excerpt[0][:GIT_ERROR_EXCERPT] if excerpt else "no stderr output"
        raise ReviewError("E_GIT", f"git {argv[0]} failed: {detail}")
    if len(stdout) > limit:
        raise ReviewError(
            "E_GIT_OUTPUT_LIMIT", f"git {argv[0]} produced more than {limit} bytes"
        )
    return stdout


def _repo_root(repo: Path) -> tuple[Path, bool]:
    """Return the canonical capture root and whether the repository is bare."""
    candidate = Path(repo)
    if not candidate.exists():
        raise ReviewError("E_REPO", f"{candidate} does not exist")
    top = run_git(candidate, ["rev-parse", "--show-toplevel"], allow_failure=True)
    if top is not None and top.strip():
        return Path(top.decode("utf-8").strip()), False
    git_dir = run_git(candidate, ["rev-parse", "--absolute-git-dir"], allow_failure=True)
    if git_dir is None or not git_dir.strip():
        raise ReviewError("E_REPO", f"{candidate} is not a Git repository")
    return Path(git_dir.decode("utf-8").strip()), True


def _object_format(root: Path) -> str:
    value = run_git(root, ["rev-parse", "--show-object-format"])
    assert value is not None
    decoded = value.decode("ascii").strip()
    if decoded not in ("sha1", "sha256"):
        raise ReviewError("E_REPO", f"unsupported object format {decoded!r}")
    return decoded


def _check_offline_sources(root: Path) -> None:
    """Fail before object access when repository objects may live on a remote."""
    partial = run_git(
        root, ["config", "--get", "extensions.partialClone"], allow_failure=True
    )
    if partial and partial.strip():
        raise ReviewError(
            "E_PARTIAL_CLONE", "the repository declares extensions.partialClone"
        )
    promisor = run_git(
        root, ["config", "--get-regexp", r"^remote\..*\.promisor$"], allow_failure=True
    )
    if promisor:
        for line in promisor.decode("utf-8", "replace").splitlines():
            fields = line.split(None, 1)
            if len(fields) == 2 and fields[1].strip().lower() == "true":
                raise ReviewError(
                    "E_PARTIAL_CLONE", f"the repository marks {fields[0]} as a promisor"
                )
    objects_dir = run_git(
        root, ["rev-parse", "--path-format=absolute", "--git-path", "objects"]
    )
    assert objects_dir is not None
    pack_dir = Path(objects_dir.decode("utf-8").strip()) / "pack"
    if pack_dir.is_dir() and any(
        entry.name.endswith(".promisor") for entry in pack_dir.iterdir()
    ):
        raise ReviewError(
            "E_PARTIAL_CLONE", "the object database contains a promisor pack"
        )


def repository_root(repo: Path) -> Path:
    """Resolve a possibly nested ``--repo`` argument to the canonical root."""
    root, _bare = _repo_root(repo)
    return root


def _resolve_oid(root: Path, revision: str | None, label: str) -> str:
    if not revision:
        raise ReviewError("E_REVISION", f"--{label} is required for this mode")
    resolved = run_git(
        root,
        ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
        allow_failure=True,
    )
    if resolved is None or not resolved.strip():
        raise ReviewError("E_REVISION", f"cannot resolve --{label} to a commit")
    return resolved.decode("ascii").strip()


def _head_oid_or_none(root: Path) -> str | None:
    value = run_git(
        root,
        ["rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"],
        allow_failure=True,
    )
    if value is None or not value.strip():
        symbolic = run_git(root, ["symbolic-ref", "--quiet", "HEAD"], allow_failure=True)
        if symbolic is None:
            raise ReviewError("E_REPO", "HEAD resolves to neither a commit nor a branch")
        return None
    return value.decode("ascii").strip()


def resolve_request(repo: Path, request: ScopeRequest) -> dict[str, Any]:
    """Freeze the comparison endpoints of one request into commit OIDs."""
    validate_request(request)
    root, bare = _repo_root(repo)
    _check_offline_sources(root)
    resolved: dict[str, Any] = {
        "object_format": _object_format(root),
        "base_oid": None,
        "head_oid": None,
        "comparison_base_oid": None,
    }
    outcome: dict[str, Any] = {
        "mode": request.mode,
        "root": str(root),
        "bare": bare,
        "root_commit": False,
        "worktree_snapshot": False,
        "parents": [],
    }
    if request.mode == "commit":
        head = _resolve_oid(root, request.commit, "commit")
        parents = run_git(root, ["rev-list", "--parents", "-n", "1", head])
        assert parents is not None
        fields = parents.split()
        resolved["head_oid"] = head
        outcome["parents"] = [field.decode("ascii") for field in fields[1:]]
        outcome["root_commit"] = len(fields) == 1
    elif request.mode == "range":
        base = _resolve_oid(root, request.base, "base")
        head = _resolve_oid(root, request.head, "head")
        resolved["base_oid"] = base
        resolved["head_oid"] = head
        merge_bases = run_git(root, ["merge-base", "--all", base, head], allow_failure=True)
        candidates = (merge_bases or b"").split()
        if not candidates:
            raise ReviewError("E_NO_MERGE_BASE", "the two endpoints share no merge base")
        if len(candidates) > 1:
            raise ReviewError(
                "E_AMBIGUOUS_MERGE_BASE",
                f"the two endpoints have {len(candidates)} merge bases",
            )
        resolved["comparison_base_oid"] = candidates[0].decode("ascii")
    elif request.mode == "workspace":
        if bare:
            raise ReviewError("E_REPO", "workspace capture requires a work tree")
        resolved["head_oid"] = _head_oid_or_none(root)
    else:
        if request.revision == WORKTREE_REVISION:
            if bare:
                raise ReviewError("E_REPO", "a working-tree snapshot requires a work tree")
            outcome["worktree_snapshot"] = True
            resolved["head_oid"] = _head_oid_or_none(root)
        else:
            resolved["head_oid"] = _resolve_oid(root, request.revision, "revision")
    observation = (
        "immutable_commits"
        if request.mode in ("commit", "range")
        or (request.mode == "snapshot" and not outcome["worktree_snapshot"])
        else "bounded_double_observation"
    )
    outcome.update(
        {
            "request": {
                "paths": list(request.paths),
                "context_paths": list(request.context_paths),
                "base": request.base,
                "head": request.head,
                "commit": request.commit,
                "revision": request.revision,
            },
            "resolved": resolved,
            "observation": observation,
        }
    )
    return outcome


def parse_raw_diff(raw: bytes, layer: str) -> list[dict[str, Any]]:
    """Parse ``--raw -z --no-abbrev --no-renames`` output without guessing boundaries."""
    tokens = raw.split(b"\0")
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        header = tokens[index]
        if not header:
            index += 1
            continue
        if not header.startswith(b":"):
            raise ReviewError("E_GIT_RAW", f"unexpected raw record in the {layer} layer")
        fields = header[1:].split(b" ")
        if len(fields) != 5:
            raise ReviewError("E_GIT_RAW", f"malformed raw header in the {layer} layer")
        old_mode, new_mode, old_oid, new_oid, status = fields
        if len(status) != 1 or status not in b"AMDTU":
            raise ReviewError(
                "E_GIT_RAW", f"unsupported raw status {status!r} in the {layer} layer"
            )
        if index + 1 >= len(tokens):
            raise ReviewError("E_GIT_RAW", f"raw record without a path in the {layer} layer")
        path = tokens[index + 1]
        index += 2
        try:
            decoded_path = path.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReviewError("E_PATH_ENCODING", f"a {layer} path is not valid UTF-8") from exc
        entries.append(
            {
                "status": status.decode("ascii"),
                "path": decoded_path,
                "old_mode": old_mode.decode("ascii"),
                "new_mode": new_mode.decode("ascii"),
                "old_oid": old_oid.decode("ascii"),
                "new_oid": new_oid.decode("ascii"),
            }
        )
    return entries


def _mode_present(mode: str) -> bool:
    return mode != "000000"


def _git_side(origin: str, revision: str | None, mode: str, oid: str) -> dict[str, Any]:
    return {
        "origin": origin,
        "revision": revision,
        "git_oid": oid,
        "git_mode": mode,
        "disk": False,
    }


def _disk_side(mode: str | None) -> dict[str, Any]:
    return {
        "origin": "worktree",
        "revision": None,
        "git_oid": None,
        "git_mode": mode,
        "disk": True,
    }


def _item(
    layer: str,
    path: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    letter: str,
) -> dict[str, Any] | None:
    if before is None and after is None:
        return None
    if letter == "P":
        status = "P"
    elif before is None:
        status = "A"
    elif after is None:
        status = "D"
    elif letter == "T":
        status = "T"
    else:
        status = "M"
    return {"layer": layer, "status": status, "path": path, "before": before, "after": after}


def _diff_items(
    root: Path,
    layer: str,
    argv: list[str],
    before: tuple[str, str | None] | None,
    after: tuple[str, str | None] | None,
) -> list[dict[str, Any]]:
    """Convert raw diff records into items.

    ``before`` and ``after`` name the origin and revision of each side; a
    ``worktree`` after side is read from disk and carries no Git object.
    """
    items: list[dict[str, Any]] = []
    for record in _diff_raw(root, argv, layer):
        before_side = (
            _git_side(before[0], before[1], record["old_mode"], record["old_oid"])
            if before is not None and _mode_present(record["old_mode"])
            else None
        )
        if after is None or not _mode_present(record["new_mode"]):
            after_side = None
        elif after[0] == "worktree":
            after_side = _disk_side(None)
        else:
            after_side = _git_side(after[0], after[1], record["new_mode"], record["new_oid"])
        entry = _item(layer, record["path"], before_side, after_side, record["status"])
        if entry is not None:
            items.append(entry)
    return items


def _diff_raw(root: Path, argv: list[str], layer: str) -> list[dict[str, Any]]:
    raw = run_git(root, argv)
    assert raw is not None
    return parse_raw_diff(raw, layer)


def _pathspecs(paths: Iterable[str]) -> list[str]:
    return ["--", *paths]


def _ls_files_stage(root: Path, paths: Iterable[str]) -> dict[str, tuple[str, str]]:
    raw = run_git(root, ["ls-files", "--stage", "-z", *_pathspecs(paths)])
    assert raw is not None
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, path = record.split(b"\t", 1)
        except ValueError as exc:
            raise ReviewError("E_GIT_RAW", "malformed ls-files stage record") from exc
        fields = meta.split(b" ")
        if len(fields) != 3:
            raise ReviewError("E_GIT_RAW", "malformed ls-files stage header")
        mode, oid, stage = fields
        decoded_path = path.decode("utf-8")
        if stage != b"0":
            raise ReviewError("E_UNMERGED", f"{decoded_path} has unmerged index stages")
        entries[decoded_path] = (mode.decode("ascii"), oid.decode("ascii"))
    return entries


def _others(root: Path, paths: Iterable[str]) -> list[str]:
    raw = run_git(
        root, ["ls-files", "--others", "--exclude-standard", "-z", *_pathspecs(paths)]
    )
    assert raw is not None
    return [record.decode("utf-8") for record in raw.split(b"\0") if record]


def _ls_tree(
    root: Path, oid: str, paths: Iterable[str]
) -> list[tuple[str, str, str, str]]:
    raw = run_git(root, ["ls-tree", "-r", "-z", oid, *_pathspecs(paths)])
    assert raw is not None
    entries: list[tuple[str, str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, path = record.split(b"\t", 1)
        except ValueError as exc:
            raise ReviewError("E_GIT_RAW", "malformed ls-tree record") from exc
        fields = meta.split(b" ")
        if len(fields) != 3:
            raise ReviewError("E_GIT_RAW", "malformed ls-tree header")
        mode, kind, object_id = (field.decode("ascii") for field in fields)
        entries.append((mode, kind, object_id, path.decode("utf-8")))
    return entries


def _reject_unmerged(root: Path, paths: Iterable[str]) -> None:
    raw = run_git(root, ["ls-files", "--unmerged", "-z", *_pathspecs(paths)])
    assert raw is not None
    if not raw.strip(b"\0"):
        return
    unmerged = [
        record.split(b"\t", 1)[-1].decode("utf-8", "replace")
        for record in raw.split(b"\0")
        if record
    ]
    raise ReviewError(
        "E_UNMERGED", f"unmerged index entries are present: {', '.join(unmerged[:5])}"
    )


DIFF_FLAGS = (
    "--raw",
    "-z",
    "--no-abbrev",
    "--no-renames",
    "--no-ext-diff",
    "--no-textconv",
    "--ignore-submodules=none",
)


def _range_items(
    root: Path,
    layer: str,
    base_oid: str | None,
    head_oid: str,
    paths: list[str],
) -> list[dict[str, Any]]:
    """Items for one immutable comparison; a missing base means the root commit."""
    if base_oid is None:
        argv = [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "-r",
            *DIFF_FLAGS,
            head_oid,
            *_pathspecs(paths),
        ]
    else:
        argv = ["diff", *DIFF_FLAGS, base_oid, head_oid, *_pathspecs(paths)]
    return _diff_items(root, layer, argv, ("git", base_oid), ("git", head_oid))


def _index_items(root: Path, head_oid: str | None, paths: list[str]) -> list[dict[str, Any]]:
    """Items for the frozen HEAD to index comparison, real staged blobs included."""
    argv = ["diff", "--cached", *DIFF_FLAGS]
    if head_oid is not None:
        argv.append(head_oid)
    argv.extend(_pathspecs(paths))
    return _diff_items(root, "index", argv, ("git", head_oid), ("index", None))


def _worktree_items(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    """Items for index to worktree plus non-ignored untracked files."""
    items = _diff_items(
        root, "worktree", ["diff", *DIFF_FLAGS, *_pathspecs(paths)], ("index", None), ("worktree", None)
    )
    for path in _others(root, paths):
        entry = _item("untracked", path, None, _disk_side(None), "A")
        if entry is not None:
            items.append(entry)
    return items


def _working_tree_snapshot_items(
    root: Path, paths: list[str], staged: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    """Snapshot entries that exist on disk; deleted tracked paths belong to the diff modes."""
    items: list[dict[str, Any]] = []
    for path, (git_mode, git_oid) in staged.items():
        if git_mode == "160000":
            entry = _item(
                "snapshot", path, None, _git_side("index", None, git_mode, git_oid), "P"
            )
        elif _disk_present(root, path):
            entry = _item("snapshot", path, None, _disk_side(git_mode), "P")
        else:
            entry = None
        if entry is not None:
            items.append(entry)
    for path in _others(root, paths):
        if not _disk_present(root, path):
            continue
        entry = _item("snapshot", path, None, _disk_side(None), "P")
        if entry is not None:
            items.append(entry)
    return items


def _committed_snapshot_items(root: Path, oid: str, paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for git_mode, kind, git_oid, path in _ls_tree(root, oid, paths):
        if kind == "commit":
            object_mode = "160000"
        elif kind == "blob":
            object_mode = git_mode
        else:
            continue
        entry = _item(
            "snapshot", path, None, _git_side("git", oid, object_mode, git_oid), "P"
        )
        if entry is not None:
            items.append(entry)
    return items


def enumerate_items(repo: Path, resolved: dict[str, Any]) -> list[dict[str, Any]]:
    """List the requested range as layered items with unresolved source sides."""
    root = Path(resolved["root"])
    paths = resolved["request"]["paths"]
    mode = resolved["mode"]
    head_oid = resolved["resolved"]["head_oid"]
    if mode == "commit":
        base_oid = None if resolved["root_commit"] else resolved["parents"][0]
        return _range_items(root, mode, base_oid, head_oid, paths)
    if mode == "range":
        return _range_items(
            root, mode, resolved["resolved"]["comparison_base_oid"], head_oid, paths
        )
    if mode == "workspace":
        _reject_unmerged(root, paths)
        return _index_items(root, head_oid, paths) + _worktree_items(root, paths)
    if mode == "snapshot":
        if resolved["worktree_snapshot"]:
            return _working_tree_snapshot_items(root, paths, _ls_files_stage(root, paths))
        return _committed_snapshot_items(root, head_oid, paths)
    raise ReviewError("E_ARGS", f"unknown scope mode {mode!r}")


def _entry_info(
    availability: str,
    *,
    sha256: str | None = None,
    size_bytes: int | None = None,
    line_count: int | None = None,
    git_mode: str | None = None,
    payload: bytes | None = None,
) -> dict[str, Any]:
    """Build one source-info record with every field named at the call site."""
    return {
        "availability": availability,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "line_count": line_count,
        "git_mode": git_mode,
        "payload": payload,
    }


def _prepare_output(root: Path, output: Path, label: str) -> Path:
    """Create a new output location outside the repository."""
    target = _output_target(root, output, label)
    if os.path.lexists(target):
        raise ReviewError("E_OUTPUT", f"{target} already exists")
    try:
        target.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ReviewError("E_OUTPUT", f"{target} already exists") from exc
    except OSError as exc:
        raise ReviewError("E_OUTPUT", f"cannot create {target}: {exc.strerror}") from exc
    return target


def require_new_output(root: Path, output: Path, label: str) -> Path:
    """Return a fresh output path for a single file outside the repository."""
    target = _output_target(root, output, label)
    if os.path.lexists(target):
        raise ReviewError("E_OUTPUT", f"{target} already exists")
    return target


def _output_target(root: Path, output: Path, label: str) -> Path:
    """Resolve one output path and refuse targets inside the real repository root."""
    target = Path(os.path.abspath(output))
    repo_abs = Path(os.path.realpath(root))
    if target.is_relative_to(repo_abs):
        raise ReviewError("E_OUTPUT", f"the {label} is inside the repository")
    for parent in [target, *target.parents]:
        if parent.is_symlink():
            raise ReviewError("E_OUTPUT", f"the output path uses the symlink {parent}")
    return target


def _open_directory_chain(root: Path, parts: list[str], relative: str) -> int:
    """Open the parent directory of the final component without following symlinks."""
    try:
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise ReviewError("E_REPO", f"cannot open {root}: {exc.strerror}") from exc
    for part in parts:
        try:
            next_fd = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
            )
        except OSError as exc:
            detail = _chain_error(exc, dir_fd, part, relative)
            os.close(dir_fd)
            raise detail from exc
        os.close(dir_fd)
        dir_fd = next_fd
    return dir_fd


def _chain_error(
    exc: OSError, dir_fd: int, part: str, relative: str
) -> ReviewError:
    """Keep the errno class of one failed parent lookup instead of flattening it.

    ``O_DIRECTORY`` with ``O_NOFOLLOW`` reports a symlinked parent as ENOTDIR on
    Linux, so the component is inspected before the class is decided.
    """
    if exc.errno in (errno.ELOOP, errno.EMLINK):
        return ReviewError(
            "E_PARENT_SYMLINK", f"{relative} crosses a symlinked parent component"
        )
    if exc.errno == errno.ENOENT:
        return ReviewError("E_PARENT_MISSING", f"a parent directory of {relative} is gone")
    if exc.errno == errno.ENOTDIR:
        try:
            info = os.lstat(part, dir_fd=dir_fd)
        except OSError:
            info = None
        if info is not None and stat.S_ISLNK(info.st_mode):
            return ReviewError(
                "E_PARENT_SYMLINK", f"{relative} crosses a symlinked parent component"
            )
        return ReviewError(
            "E_PARENT_NOT_DIRECTORY", f"a parent component of {relative} is not a directory"
        )
    return ReviewError("E_IO", f"{relative} could not be opened: {exc.strerror}")


def _open_path(root: Path, relative: str) -> tuple[int | None, os.stat_result | None]:
    """Open the parent chain and stat the leaf without following symlinks.

    ENOENT anywhere means the path does not exist, so ``(None, None)`` is
    returned; every other failure stays an explicit error. The caller closes
    ``dir_fd`` when it is not None.
    """
    parts = relative.split("/")
    try:
        dir_fd = _open_directory_chain(root, parts[:-1], relative)
    except ReviewError as exc:
        if exc.code == "E_PARENT_MISSING":
            return None, None
        raise
    try:
        info = os.lstat(parts[-1], dir_fd=dir_fd)
    except FileNotFoundError:
        os.close(dir_fd)
        return None, None
    except OSError as exc:
        os.close(dir_fd)
        raise ReviewError("E_IO", f"cannot stat {relative}: {exc.strerror}") from exc
    return dir_fd, info


def _disk_present(root: Path, relative: str) -> bool:
    """True when the work-tree path exists, whatever its type."""
    dir_fd, info = _open_path(root, relative)
    if dir_fd is not None:
        os.close(dir_fd)
    return info is not None


def _disk_file_present(root: Path, relative: str) -> bool:
    """True only when the work-tree path is a regular file or a symlink."""
    dir_fd, info = _open_path(root, relative)
    if dir_fd is not None:
        os.close(dir_fd)
    if info is None:
        return False
    return stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)


def _read_disk(root: Path, relative: str) -> dict[str, Any]:
    """Read one work-tree file without following symlinks at any path component."""
    dir_fd, info = _open_path(root, relative)
    if dir_fd is None:
        raise ReviewError(
            "E_SOURCE_CHANGED_DURING_CAPTURE",
            f"{relative} disappeared while it was being captured",
        )
    try:
        return _read_disk_entry(dir_fd, relative.split("/")[-1], relative, info)
    finally:
        os.close(dir_fd)


def _read_disk_entry(
    dir_fd: int, name: str, relative: str, info: os.stat_result | None
) -> dict[str, Any]:
    if stat.S_ISLNK(info.st_mode):
        target = os.fsencode(os.readlink(name, dir_fd=dir_fd))
        if len(target) > MAX_FILE_BYTES:
            return _entry_info(
                "too_large", size_bytes=len(target), git_mode="120000"
            )
        return _entry_info(
            "symlink",
            sha256=sha256_digest(target),
            size_bytes=len(target),
            git_mode="120000",
            payload=target,
        )
    if not stat.S_ISREG(info.st_mode):
        return _entry_info("unreadable", size_bytes=info.st_size)
    mode = "100755" if info.st_mode & 0o111 else "100644"
    if info.st_size > MAX_FILE_BYTES:
        return _entry_info("too_large", size_bytes=info.st_size, git_mode=mode)
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ReviewError(
                "E_PARENT_SYMLINK", f"{relative} was replaced by a symlink"
            ) from exc
        raise ReviewError(
            "E_IO", f"{relative} could not be opened: {exc.strerror}"
        ) from exc
    try:
        before = os.fstat(file_fd)
        chunks: list[bytes] = []
        remaining = MAX_FILE_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(file_fd)
    finally:
        os.close(file_fd)
    payload = b"".join(chunks)
    if len(payload) > MAX_FILE_BYTES:
        return _entry_info("too_large", size_bytes=len(payload), git_mode=mode)
    fingerprint = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if fingerprint != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ReviewError(
            "E_SOURCE_CHANGED_DURING_CAPTURE",
            f"{relative} changed while it was being captured",
        )
    if len(payload) != before.st_size:
        raise ReviewError(
            "E_SOURCE_CHANGED_DURING_CAPTURE",
            f"{relative} changed size while it was being captured",
        )
    return _classify(payload, mode)


def _classify(payload: bytes, mode: str | None) -> dict[str, Any]:
    digest = sha256_digest(payload)
    if mode == "120000":
        return _entry_info(
            "symlink", sha256=digest, size_bytes=len(payload), git_mode=mode, payload=payload
        )
    if b"\0" in payload:
        availability = "binary"
        line_count = None
    else:
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            availability = "binary"
            line_count = None
        else:
            availability = "text"
            line_count = count_lines(payload)
    return _entry_info(
        availability,
        sha256=digest,
        size_bytes=len(payload),
        line_count=line_count,
        git_mode=mode,
        payload=payload,
    )


def _read_git_object(root: Path, oid: str, mode: str | None) -> dict[str, Any]:
    if mode == "160000":
        return _entry_info("submodule", git_mode=mode)
    size_raw = run_git(root, ["cat-file", "-s", oid], allow_failure=True)
    if size_raw is None:
        return _entry_info("unreadable", git_mode=mode)
    size = int(size_raw.strip())
    if size > MAX_FILE_BYTES:
        return _entry_info("too_large", size_bytes=size, git_mode=mode)
    payload = run_git(root, ["cat-file", "blob", oid], limit=MAX_FILE_BYTES)
    assert payload is not None
    return _classify(payload, mode)


def _probe_disk(root: Path, relative: str) -> tuple[Any, ...]:
    """Re-observe one work-tree path as (mode, size, digest) for freshness checks."""
    dir_fd, info = _open_path(root, relative)
    if dir_fd is None:
        return ("missing", None, None)
    try:
        detail = _read_disk_entry(dir_fd, relative.split("/")[-1], relative, info)
    finally:
        os.close(dir_fd)
    return (detail["git_mode"], detail["size_bytes"], detail["sha256"])


def _source_key(side: dict[str, Any], path: str) -> tuple[str, str, str, str]:
    return (side["origin"], side["revision"] or "", path, side["git_oid"] or "")


def _side_fact(repo: Path, path: str, side: dict[str, Any]) -> tuple[Any, ...]:
    """One observed fact: worktree sides are probed, Git and index sides stay frozen."""
    if side["disk"]:
        return ("worktree", *_probe_disk(repo, path))
    return (side["origin"], side["revision"], side["git_oid"], side["git_mode"])


def _source_fact(source: dict[str, Any]) -> tuple[Any, ...]:
    """The fact one captured source records."""
    if source["origin"] == "worktree":
        return ("worktree", source["git_mode"], source["size_bytes"], source["sha256"])
    return (source["origin"], source["revision"], source["git_oid"], source["git_mode"])


def _recorded_facts(
    items: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    context_paths: Iterable[str],
) -> dict[tuple[str, str, str], tuple[Any, ...]]:
    """Project a sealed scope onto the facts a later observation compares against."""
    by_id = {source["id"]: source for source in sources}
    facts: dict[tuple[str, str, str], tuple[Any, ...]] = {}
    for item in items:
        for side_name in ("before", "after"):
            reference = item[side_name]
            if reference is not None:
                facts[(item["layer"], item["path"], side_name)] = _source_fact(
                    by_id[reference]
                )
    declared = set(context_paths)
    for source in sources:
        if source["path"] in declared:
            facts[("context", source["path"], source["origin"])] = _source_fact(source)
    return facts


def _observed_facts(
    repo: Path, resolved: dict[str, Any]
) -> dict[tuple[str, str, str], tuple[Any, ...]]:
    """Project the current repository state onto the same facts.

    Context paths are re-observed alongside the requested items, and only the
    versions the request actually compares are looked at.
    """
    facts: dict[tuple[str, str, str], tuple[Any, ...]] = {}
    for entry in enumerate_items(repo, resolved):
        for side_name in ("before", "after"):
            side = entry[side_name]
            if side is not None:
                facts[(entry["layer"], entry["path"], side_name)] = _side_fact(
                    repo, entry["path"], side
                )
    for path in resolved["request"]["context_paths"]:
        for side in _context_sides(repo, resolved, path):
            facts[("context", path, side["origin"])] = _side_fact(repo, path, side)
    return facts


def _facts_differ(recorded: tuple[Any, ...] | None, observed: tuple[Any, ...] | None) -> bool:
    if recorded is None or observed is None:
        return True
    if recorded[0] != observed[0]:
        return True
    if recorded[0] == "worktree":
        if recorded[1] != observed[1] or recorded[2] != observed[2]:
            return True
        if recorded[3] is None:
            # Bytes were not captured, so only the observable mode and size compare.
            return False
        return recorded[3] != observed[3]
    return recorded[1:] != observed[1:]


def _fact_changes(
    recorded: dict[tuple[str, str, str], tuple[Any, ...]],
    observed: dict[tuple[str, str, str], tuple[Any, ...]],
) -> set[str]:
    changed: set[str] = set()
    for key in set(recorded) | set(observed):
        if _facts_differ(recorded.get(key), observed.get(key)):
            changed.add(key[1])
    return changed


def capture_scope(repo: Path, request: ScopeRequest, output: Path) -> dict[str, Any]:
    """Capture the requested scope into a new packet directory."""
    validate_request(request)
    resolved = resolve_request(repo, request)
    packet = _prepare_output(Path(resolved["root"]), Path(output), "packet output directory")
    return _capture_into(packet, resolved, request)


def _capture_into(
    packet: Path, resolved: dict[str, Any], request: ScopeRequest
) -> dict[str, Any]:
    root = Path(resolved["root"])
    entries = enumerate_items(root, resolved)
    if len(entries) > MAX_ITEMS:
        raise ReviewError(
            "E_ITEMS_LIMIT",
            f"the requested range has {len(entries)} items, over the {MAX_ITEMS} limit",
        )
    sides = _requested_sides(root, resolved, request, entries)
    keys = sorted(sides)
    (packet / "objects").mkdir(mode=0o700, exist_ok=True)
    limitations: list[str] = []
    if resolved["observation"] == "bounded_double_observation":
        limitations.append(IGNORED_UNTRACKED_LIMIT)
    source_records = _capture_sources(root, packet, sides, keys, limitations)
    item_records = _item_records(entries, source_records)
    scope = {
        "schema_version": SCOPE_SCHEMA_VERSION,
        "mode": resolved["mode"],
        "request": {
            "paths": sorted(set(request.paths), key=lambda value: value.encode("utf-8")),
            "context_paths": sorted(
                set(request.context_paths), key=lambda value: value.encode("utf-8")
            ),
            "base": request.base,
            "head": request.head,
            "commit": request.commit,
            "revision": request.revision,
        },
        "resolved": resolved["resolved"],
        "observation": resolved["observation"],
        "items": item_records,
        "sources": [source_records[key] for key in keys],
        "limitations": dedupe_texts(limitations),
    }
    scope_bytes = _seal_scope(packet, scope, root, resolved, request.context_paths)
    return {
        "packet": str(packet),
        "scope_sha256": sha256_digest(scope_bytes),
        "mode": scope["mode"],
        "items": len(item_records),
        "sources": len(scope["sources"]),
        "partial": any(
            source["availability"] != TEXT_AVAILABILITY for source in scope["sources"]
        ),
        "limitations": scope["limitations"],
    }


def _requested_sides(
    root: Path,
    resolved: dict[str, Any],
    request: ScopeRequest,
    entries: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[dict[str, Any], str]]:
    """Collect every item side plus every existing version of the context paths."""
    sides: dict[tuple[str, str, str, str], tuple[dict[str, Any], str]] = {}
    for entry in entries:
        for side in (entry["before"], entry["after"]):
            if side is not None:
                sides[_source_key(side, entry["path"])] = (side, entry["path"])
    for path in request.context_paths:
        context_sides = _context_sides(root, resolved, path)
        if not context_sides:
            raise ReviewError(
                "E_CONTEXT_MISSING",
                f"the context path {path!r} does not exist in any compared version",
            )
        for side in context_sides:
            sides[_source_key(side, path)] = (side, path)
    return sides


def _capture_sources(
    root: Path,
    packet: Path,
    sides: dict[tuple[str, str, str, str], tuple[dict[str, Any], str]],
    keys: list[tuple[str, str, str, str]],
    limitations: list[str],
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """Read every distinct side once and write the objects the budget allows.

    The budget is charged per new digest, so equal bytes stored under several
    paths or origins cost one object.
    """
    objects = packet / "objects"
    source_records: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    used = 0
    written: set[str] = set()
    for index, key in enumerate(keys, start=1):
        side, path = sides[key]
        if side["disk"]:
            info = _read_disk(root, path)
            git_mode = info["git_mode"]
        else:
            info = _read_git_object(root, side["git_oid"], side["git_mode"])
            git_mode = side["git_mode"]
        availability = info["availability"]
        digest = info["sha256"]
        if availability in CAPTURED_AVAILABILITY:
            incremental = 0 if digest in written else (info["size_bytes"] or 0)
            if used + incremental > MAX_PACKET_BYTES:
                availability = "budget_exhausted"
        captured = availability in CAPTURED_AVAILABILITY
        if not captured:
            if availability == "budget_exhausted":
                limitations.append(
                    f"{path} was not captured because the packet byte budget was exhausted."
                )
            else:
                limitations.append(f"{path} was not captured ({availability}).")
        source_records[key] = {
            "id": f"S-{index:06d}",
            "path": path,
            "origin": side["origin"],
            "revision": side["revision"],
            "git_oid": side["git_oid"],
            "git_mode": git_mode,
            "availability": availability,
            "sha256": digest if captured else None,
            "size_bytes": info["size_bytes"],
            "line_count": info["line_count"] if captured else None,
        }
        if captured:
            assert digest is not None
            if digest in written:
                continue
            try:
                (objects / f"{digest[7:]}.blob").write_bytes(info["payload"] or b"")
            except OSError as exc:
                raise ReviewError(
                    "E_OUTPUT", f"cannot write the captured object: {exc.strerror}"
                ) from exc
            written.add(digest)
            used += info["size_bytes"] or 0
    return source_records


def _item_records(
    entries: list[dict[str, Any]],
    source_records: dict[tuple[str, str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Order the items by layer and path and point them at their source ids."""
    ordered: list[dict[str, Any]] = []
    for entry in sorted(
        entries,
        key=lambda item: (LAYER_ORDER.index(item["layer"]), item["path"].encode("utf-8")),
    ):
        record: dict[str, Any] = {
            "layer": entry["layer"],
            "status": entry["status"],
            "path": entry["path"],
        }
        for side_name in ("before", "after"):
            side = entry[side_name]
            record[side_name] = (
                None
                if side is None
                else source_records[_source_key(side, entry["path"])]["id"]
            )
        ordered.append(record)
    return [
        {"id": f"I-{index:06d}", **record}
        for index, record in enumerate(ordered, start=1)
    ]


def _seal_scope(
    packet: Path,
    scope: dict[str, Any],
    root: Path,
    resolved: dict[str, Any],
    context_paths: tuple[str, ...],
) -> bytes:
    """Re-observe the request, validate the whole scope, then write scope.json.

    The completion marker appears only after every check passed, and the encoded
    document is bounded before it is written.
    """
    if resolved["observation"] == "bounded_double_observation":
        recorded = _recorded_facts(scope["items"], scope["sources"], context_paths)
        observed = _observed_facts(root, resolved)
        changed = _fact_changes(recorded, observed)
        if changed:
            raise ReviewError(
                "E_SOURCE_CHANGED_DURING_CAPTURE",
                "the workspace changed during capture: " + ", ".join(sorted(changed)),
            )
    validate_scope(scope)
    scope_bytes = encode_document(scope)
    try:
        (packet / SCOPE_FILE).write_bytes(scope_bytes)
    except OSError as exc:
        raise ReviewError("E_OUTPUT", f"cannot write {SCOPE_FILE}: {exc.strerror}") from exc
    return scope_bytes


def _tree_side(root: Path, revision: str, path: str) -> dict[str, Any] | None:
    for git_mode, kind, git_oid, candidate in _ls_tree(root, revision, [path]):
        if candidate != path:
            continue
        if kind == "commit":
            return _git_side("git", revision, "160000", git_oid)
        if kind == "blob":
            return _git_side("git", revision, git_mode, git_oid)
    return None


def _context_sides(root: Path, resolved: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """Capture the versions of one context path that exist in the compared states."""
    oids = resolved["resolved"]
    mode = resolved["mode"]
    sides: list[dict[str, Any]] = []
    if mode == "commit":
        if not resolved["root_commit"] and resolved["parents"]:
            before = _tree_side(root, resolved["parents"][0], path)
            if before is not None:
                sides.append(before)
        after = _tree_side(root, oids["head_oid"], path)
        if after is not None:
            sides.append(after)
        return sides
    if mode == "range":
        for revision in (oids["comparison_base_oid"], oids["head_oid"]):
            side = _tree_side(root, revision, path)
            if side is not None:
                sides.append(side)
        return sides
    if mode == "workspace":
        if oids["head_oid"] is not None:
            side = _tree_side(root, oids["head_oid"], path)
            if side is not None:
                sides.append(side)
        staged = _ls_files_stage(root, [path]).get(path)
        if staged is not None:
            git_mode, git_oid = staged
            sides.append(_git_side("index", None, git_mode, git_oid))
        if _disk_file_present(root, path):
            sides.append(_disk_side(None))
        return sides
    if resolved["worktree_snapshot"]:
        staged = _ls_files_stage(root, [path]).get(path)
        if staged is not None:
            git_mode, git_oid = staged
            if git_mode == "160000":
                sides.append(_git_side("index", None, git_mode, git_oid))
            elif _disk_file_present(root, path):
                sides.append(_disk_side(git_mode))
        elif _disk_file_present(root, path):
            sides.append(_disk_side(None))
        return sides
    side = _tree_side(root, oids["head_oid"], path)
    return [side] if side is not None else []


def compare_scope(repo: Path, scope: dict[str, Any]) -> dict[str, Any]:
    """Re-observe captured sources and report freshness for the recorded scope.

    The caller validates the record first, so this pass only compares facts and
    never re-reads captured objects.
    """
    validate_scope(scope)
    root = repository_root(repo)
    incomplete = any(
        source["availability"] not in CAPTURED_AVAILABILITY for source in scope["sources"]
    )
    if scope["observation"] == "immutable_commits":
        return _freshness(False, incomplete)
    resolved = {
        "mode": scope["mode"],
        "root": str(root),
        "request": scope["request"],
        "resolved": scope["resolved"],
        "observation": scope["observation"],
        "root_commit": False,
        "worktree_snapshot": scope["mode"] == "snapshot",
        "parents": [],
    }
    recorded = _recorded_facts(scope["items"], scope["sources"], scope["request"]["context_paths"])
    observed = _observed_facts(root, resolved)
    changed = _fact_changes(recorded, observed)
    return _freshness(bool(changed), incomplete, changed)


def _freshness(
    changed: bool, incomplete: bool, paths: Iterable[str] = ()
) -> dict[str, Any]:
    if changed:
        status = "changed"
    elif incomplete:
        status = "incomplete"
    else:
        status = "captured_inputs_match"
    return {"status": status, "changed_paths": sorted(set(paths))}
