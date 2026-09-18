"""Git and workspace capture for the review helper.

Every Git invocation goes through :func:`run_git`, and captured facts keep the
commit, index, worktree, and untracked layers separate. The module captures
sources and compares them later; it never judges a defect.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import errno
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
from typing import Any, Iterable

from _review_record import (
    CAPTURED_AVAILABILITY, LAYER_ORDER, MAX_FILE_BYTES, MAX_ITEMS, MAX_PACKET_BYTES,
    ReviewError, SCOPE_FILE, SCOPE_SCHEMA_VERSION, TEXT_AVAILABILITY, count_lines,
    dedupe_texts, encode_document, normalize_path, sha256_digest, validate_scope,
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
# Inherited redirection is dropped so the observation cannot be pointed elsewhere.
CLEARED_ENVIRONMENT = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT",
    "GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_NAMESPACE", "GIT_PREFIX",
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


def validate_request(request: ScopeRequest) -> ScopeRequest:
    """Reject argument violations and return the canonical request."""
    mode_arguments = {
        "commit": (("commit",), ("base", "head", "revision")),
        "range": (("base", "head"), ("commit", "revision")),
        "workspace": ((), ("base", "head", "commit", "revision")),
        "snapshot": (("revision",), ("base", "head", "commit")),
    }
    if request.mode not in mode_arguments:
        raise ReviewError("E_ARGS", f"unknown scope mode {request.mode!r}")
    if not request.paths:
        raise ReviewError("E_ARGS", "at least one path is required")
    required, forbidden = mode_arguments[request.mode]
    for name in required:
        if getattr(request, name) is None:
            raise ReviewError("E_ARGS", f"mode {request.mode} requires --{name}")
    for name in forbidden:
        if getattr(request, name) is not None:
            raise ReviewError("E_ARGS", f"mode {request.mode} does not accept --{name}")
    paths = _canonical_paths(request.paths, "path")
    context_paths = _canonical_paths(request.context_paths, "context path")
    if "." in context_paths:
        raise ReviewError("E_PATH_INVALID", "a context path must name a file, not '.'")
    for name in ("base", "head", "commit", "revision"):
        value = getattr(request, name)
        if value is not None:
            _validate_revision(value, name)
    return replace(request, paths=paths, context_paths=context_paths)


def _canonical_paths(paths: Iterable[str], label: str) -> tuple[str, ...]:
    """Validate, de-duplicate, and sort literal paths by UTF-8 bytes."""
    canonical: set[str] = set()
    for path in paths:
        if any(character in path for character in GLOB_CHARACTERS):
            raise ReviewError("E_PATH_INVALID", f"the {label} {path!r} looks like a glob")
        canonical.add(normalize_path(path, label))
    return tuple(sorted(canonical, key=lambda value: value.encode("utf-8")))


def _validate_revision(revision: str, label: str) -> None:
    """Reject revisions the record schema cannot carry, before any Git call."""
    if not revision.strip():
        raise ReviewError("E_REVISION", f"--{label} is empty or only whitespace")
    if len(revision) > MAX_REVISION_CHARACTERS:
        raise ReviewError(
            "E_REVISION",
            f"--{label} holds {len(revision)} characters, over {MAX_REVISION_CHARACTERS}",
        )


def _decode_git_path(raw: bytes) -> str:
    """Decode one Git file name strictly; a non-UTF-8 name is a typed error."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError("E_PATH_ENCODING", "a repository path is not valid UTF-8") from exc


def _git_path_line(raw: bytes) -> str:
    """Decode one Git path output line after removing its protocol LF only."""
    return _decode_git_path(raw[:-1] if raw.endswith(b"\n") else raw)


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
        "git", "-C", str(repo), "-c", "core.fsmonitor=false",
        "-c", "diff.renames=false", "--literal-pathspecs", *argv,
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
                "E_GIT_TIMEOUT", f"git {argv[0]} did not finish in {GIT_TIMEOUT_SECONDS}s"
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
        raise ReviewError("E_GIT_OUTPUT_LIMIT", f"git {argv[0]} passed {limit} bytes")
    return stdout


def _repo_root(repo: Path) -> tuple[Path, bool]:
    """Return the canonical capture root and whether the repository is bare."""
    if not Path(repo).exists():
        raise ReviewError("E_REPO", f"{repo} does not exist")
    top = run_git(Path(repo), ["rev-parse", "--show-toplevel"], allow_failure=True)
    if top is not None and _git_path_line(top):
        return Path(_git_path_line(top)), False
    git_dir = run_git(Path(repo), ["rev-parse", "--absolute-git-dir"], allow_failure=True)
    if git_dir is None or not _git_path_line(git_dir):
        raise ReviewError("E_REPO", f"{repo} is not a Git repository")
    return Path(_git_path_line(git_dir)), True


def _object_format(root: Path) -> str:
    value = run_git(root, ["rev-parse", "--show-object-format"])
    assert value is not None
    decoded = value.decode("ascii").strip()
    if decoded not in ("sha1", "sha256"):
        raise ReviewError("E_REPO", f"unsupported object format {decoded!r}")
    return decoded


def _check_offline_sources(root: Path) -> None:
    """Fail before object access when repository objects may live on a remote."""
    partial = run_git(root, ["config", "--get", "extensions.partialClone"], allow_failure=True)
    if partial and partial.strip():
        raise ReviewError("E_PARTIAL_CLONE", "the repository declares extensions.partialClone")
    markers = run_git(root, ["config", "--get-regexp", r"^remote\..*\.promisor$"], allow_failure=True)
    for line in (markers or b"").decode("utf-8", "replace").splitlines():
        fields = line.split(None, 1)
        if len(fields) == 2 and fields[1].strip().lower() == "true":
            raise ReviewError("E_PARTIAL_CLONE", f"{fields[0]} is a promisor remote")
    objects_dir = run_git(root, ["rev-parse", "--path-format=absolute", "--git-path", "objects"])
    assert objects_dir is not None
    pack_dir = Path(_git_path_line(objects_dir)) / "pack"
    if pack_dir.is_dir() and any(name.name.endswith(".promisor") for name in pack_dir.iterdir()):
        raise ReviewError("E_PARTIAL_CLONE", "the object database holds a promisor pack")


def repository_root(repo: Path) -> Path:
    """Resolve a possibly nested ``--repo`` argument to the canonical root."""
    root, _bare = _repo_root(repo)
    return root


def _resolve_oid(root: Path, revision: str | None, label: str) -> str:
    if not revision:
        raise ReviewError("E_REVISION", f"--{label} is required for this mode")
    argument = f"{revision}^{{commit}}"
    resolved = run_git(root, ["rev-parse", "--verify", "--end-of-options", argument], allow_failure=True)
    if resolved is None or not resolved.strip():
        raise ReviewError("E_REVISION", f"cannot resolve --{label} to a commit")
    return resolved.decode("ascii").strip()


def _head_oid_or_none(root: Path) -> str | None:
    argument = "HEAD^{commit}"
    value = run_git(root, ["rev-parse", "--verify", "--end-of-options", argument], allow_failure=True)
    if value is not None and value.strip():
        return value.decode("ascii").strip()
    if run_git(root, ["symbolic-ref", "--quiet", "HEAD"], allow_failure=True) is None:
        raise ReviewError("E_REPO", "HEAD resolves to neither a commit nor a branch")
    return None


def resolve_request(repo: Path, request: ScopeRequest) -> dict[str, Any]:
    """Freeze the comparison endpoints of one request into commit OIDs."""
    request = validate_request(request)
    root, bare = _repo_root(repo)
    _check_offline_sources(root)
    state: dict[str, Any] = {
        "mode": request.mode,
        "root": str(root),
        "bare": bare,
        "request": {field: list(value) if isinstance(value, tuple) else value
                    for field, value in asdict(request).items() if field != "mode"},
        "resolved": {"object_format": _object_format(root), "base_oid": None,
                     "head_oid": None, "comparison_base_oid": None},
        "root_commit": False,
        "parents": [],
        "worktree_snapshot": False,
    }
    resolved = state["resolved"]
    if request.mode == "commit":
        head = _resolve_oid(root, request.commit, "commit")
        parents = run_git(root, ["rev-list", "--parents", "-n", "1", head])
        assert parents is not None
        fields = parents.split()
        resolved["head_oid"] = head
        state["parents"] = [field.decode("ascii") for field in fields[1:]]
        state["root_commit"] = len(fields) == 1
    elif request.mode == "range":
        base = _resolve_oid(root, request.base, "base")
        head = _resolve_oid(root, request.head, "head")
        resolved["base_oid"], resolved["head_oid"] = base, head
        merge_bases = run_git(root, ["merge-base", "--all", base, head], allow_failure=True)
        candidates = (merge_bases or b"").split()
        if not candidates:
            raise ReviewError("E_NO_MERGE_BASE", "the two endpoints share no merge base")
        if len(candidates) > 1:
            raise ReviewError("E_AMBIGUOUS_MERGE_BASE",
                              f"the endpoints have {len(candidates)} merge bases")
        resolved["comparison_base_oid"] = candidates[0].decode("ascii")
    elif request.mode == "workspace" or request.revision == WORKTREE_REVISION:
        if bare:
            raise ReviewError("E_REPO", "this scope needs a work tree")
        state["worktree_snapshot"] = request.mode == "snapshot"
        resolved["head_oid"] = _head_oid_or_none(root)
    else:
        resolved["head_oid"] = _resolve_oid(root, request.revision, "revision")
    state["observation"] = (
        "immutable_commits"
        if request.mode in ("commit", "range")
        or (request.mode == "snapshot" and not state["worktree_snapshot"])
        else "bounded_double_observation"
    )
    return state


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
        fields = header[1:].split(b" ") if header.startswith(b":") else []
        if len(fields) != 5:
            raise ReviewError("E_GIT_RAW", f"malformed raw record in the {layer} layer")
        old_mode, new_mode, old_oid, new_oid, status = fields
        if status not in (b"A", b"M", b"D", b"T", b"U"):
            raise ReviewError("E_GIT_RAW", f"unsupported raw status in the {layer} layer")
        if index + 1 >= len(tokens):
            raise ReviewError("E_GIT_RAW", f"raw record without a path in the {layer} layer")
        path = _decode_git_path(tokens[index + 1])
        index += 2
        entries.append({
            "status": status.decode("ascii"), "path": path,
            "old_mode": old_mode.decode("ascii"), "new_mode": new_mode.decode("ascii"),
            "old_oid": old_oid.decode("ascii"), "new_oid": new_oid.decode("ascii"),
        })
    return entries


def _git_side(origin: str, revision: str | None, mode: str, oid: str) -> dict[str, Any]:
    return {"origin": origin, "revision": revision, "git_oid": oid, "git_mode": mode}


def _disk_side(mode: str | None) -> dict[str, Any]:
    return {"origin": "worktree", "revision": None, "git_oid": None, "git_mode": mode}


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
    else:
        status = "A" if before is None else "D" if after is None else "T" if letter == "T" else "M"
    return {"layer": layer, "status": status, "path": path, "before": before, "after": after}


def _diff_items(
    root: Path,
    layer: str,
    argv: list[str],
    before: tuple[str, str | None] | None,
    after: tuple[str, str | None] | None,
) -> list[dict[str, Any]]:
    """Convert raw diff records into items.

    A ``worktree`` after side is read from disk and carries no Git object.
    """
    raw = run_git(root, argv)
    assert raw is not None
    items: list[dict[str, Any]] = []
    for record in parse_raw_diff(raw, layer):
        before_side = (
            _git_side(before[0], before[1], record["old_mode"], record["old_oid"])
            if before is not None and record["old_mode"] != "000000"
            else None
        )
        if after is None or record["new_mode"] == "000000":
            after_side = None
        elif after[0] == "worktree":
            after_side = _disk_side(None)
        else:
            after_side = _git_side(after[0], after[1], record["new_mode"], record["new_oid"])
        entry = _item(layer, record["path"], before_side, after_side, record["status"])
        if entry is not None:
            items.append(entry)
    return items


def _ls_files_stage(root: Path, paths: Iterable[str]) -> dict[str, tuple[str, str]]:
    raw = run_git(root, ["ls-files", "--stage", "-z", "--", *paths])
    assert raw is not None
    entries: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, _, path = record.partition(b"\t")
        fields = meta.split(b" ")
        if len(fields) != 3 or not path:
            raise ReviewError("E_GIT_RAW", "malformed ls-files stage record")
        mode, oid, stage = fields
        decoded_path = _decode_git_path(path)
        if stage != b"0":
            raise ReviewError("E_UNMERGED", f"{decoded_path} has unmerged index stages")
        entries[decoded_path] = (mode.decode("ascii"), oid.decode("ascii"))
    return entries


def _others(root: Path, paths: Iterable[str]) -> list[str]:
    argv = ["ls-files", "--others", "--exclude-standard", "-z", "--", *paths]
    raw = run_git(root, argv)
    assert raw is not None
    return [_decode_git_path(record) for record in raw.split(b"\0") if record]


def _ls_tree(
    root: Path, oid: str, paths: Iterable[str]
) -> list[tuple[str, str, str, str]]:
    raw = run_git(root, ["ls-tree", "-r", "-z", oid, "--", *paths])
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
        entries.append((mode, kind, object_id, _decode_git_path(path)))
    return entries


def _reject_unmerged(root: Path, paths: Iterable[str]) -> None:
    raw = run_git(root, ["ls-files", "--unmerged", "-z", "--", *paths])
    assert raw is not None
    if not raw.strip(b"\0"):
        return
    unmerged = [
        _decode_git_path(record.split(b"\t", 1)[-1])
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
            *DIFF_FLAGS, head_oid, "--", *paths,
        ]
    else:
        argv = ["diff", *DIFF_FLAGS, base_oid, head_oid, "--", *paths]
    return _diff_items(root, layer, argv, ("git", base_oid), ("git", head_oid))


def _index_items(root: Path, head_oid: str | None, paths: list[str]) -> list[dict[str, Any]]:
    """Items for the frozen HEAD to index comparison, real staged blobs included."""
    argv = ["diff", "--cached", *DIFF_FLAGS]
    if head_oid is not None:
        argv.append(head_oid)
    argv.extend(["--", *paths])
    return _diff_items(root, "index", argv, ("git", head_oid), ("index", None))


def _worktree_items(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    """Items for index to worktree plus non-ignored untracked files."""
    items = _diff_items(
        root,
        "worktree",
        ["diff", *DIFF_FLAGS, "--", *paths],
        ("index", None),
        ("worktree", None),
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
        elif _disk_kind(root, path) is not None:
            entry = _item("snapshot", path, None, _disk_side(git_mode), "P")
        else:
            entry = None
        if entry is not None:
            items.append(entry)
    for path in _others(root, paths):
        if _disk_kind(root, path) is None:
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
    if mode in ("commit", "range"):
        if mode == "commit":
            base_oid = None if resolved["root_commit"] else resolved["parents"][0]
        else:
            base_oid = resolved["resolved"]["comparison_base_oid"]
        return _range_items(root, mode, base_oid, head_oid, paths)
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
    return {"availability": availability, "sha256": sha256, "size_bytes": size_bytes,
            "line_count": line_count, "git_mode": git_mode, "payload": payload}


def require_new_output(root: Path, output: Path, label: str) -> Path:
    """Return a fresh output path for a single file outside the real repository root."""
    target = Path(os.path.abspath(output))
    if target.is_relative_to(Path(os.path.realpath(root))):
        raise ReviewError("E_OUTPUT", f"the {label} is inside the repository")
    for parent in [target, *target.parents]:
        if parent.is_symlink():
            raise ReviewError("E_OUTPUT", f"the output path uses the symlink {parent}")
    if os.path.lexists(target):
        raise ReviewError("E_OUTPUT", f"{target} already exists")
    return target


def _output_directory(root: Path, output: Path, label: str) -> Path:
    """Create a new packet directory outside the repository."""
    target = require_new_output(root, output, label)
    try:
        target.mkdir(mode=0o700)
    except OSError as exc:
        raise ReviewError("E_OUTPUT", f"cannot create {target}: {exc.strerror}") from exc
    return target


def _open_directory_chain(root: Path, parts: list[str], relative: str) -> int:
    """Open the parent directory of the final component without following symlinks."""
    try:
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        raise ReviewError("E_REPO", f"cannot open {root}: {exc.strerror}") from exc
    for part in parts:
        try:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError as exc:
            # O_DIRECTORY with O_NOFOLLOW reports a symlinked parent as ENOTDIR,
            # so the component itself decides which class the failure belongs to.
            linked = exc.errno in (errno.ELOOP, errno.EMLINK)
            if not linked and exc.errno == errno.ENOTDIR:
                try:
                    linked = stat.S_ISLNK(os.lstat(part, dir_fd=dir_fd).st_mode)
                except OSError:
                    linked = False
            os.close(dir_fd)
            if linked:
                raise ReviewError("E_PARENT_SYMLINK",
                                  f"{relative} crosses a symlinked parent") from exc
            if exc.errno == errno.ENOENT:
                raise ReviewError("E_PARENT_MISSING", f"a parent of {relative} is gone") from exc
            if exc.errno == errno.ENOTDIR:
                raise ReviewError("E_PARENT_NOT_DIRECTORY",
                                  f"a parent of {relative} is not a directory") from exc
            raise ReviewError("E_IO", f"cannot open {relative}: {exc.strerror}") from exc
        os.close(dir_fd)
        dir_fd = next_fd
    return dir_fd


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
    except OSError as exc:
        os.close(dir_fd)
        if exc.errno == errno.ENOENT:
            return None, None
        raise ReviewError("E_IO", f"cannot stat {relative}: {exc.strerror}") from exc
    return dir_fd, info


def _disk_kind(root: Path, relative: str) -> str | None:
    """One work-tree path as ``file``, ``link``, ``other``, or None when absent."""
    dir_fd, info = _open_path(root, relative)
    if dir_fd is not None:
        os.close(dir_fd)
    if info is None:
        return None
    if stat.S_ISLNK(info.st_mode):
        return "link"
    return "file" if stat.S_ISREG(info.st_mode) else "other"


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
            return _entry_info("too_large", size_bytes=len(target), git_mode="120000")
        return _entry_info("symlink", sha256=sha256_digest(target),
                           size_bytes=len(target), git_mode="120000", payload=target)
    if not stat.S_ISREG(info.st_mode):
        return _entry_info("unreadable", size_bytes=info.st_size)
    mode = "100755" if info.st_mode & 0o111 else "100644"
    if info.st_size > MAX_FILE_BYTES:
        return _entry_info("too_large", size_bytes=info.st_size, git_mode=mode)
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ReviewError("E_PARENT_SYMLINK", f"{relative} was replaced by a symlink") from exc
        raise ReviewError("E_IO", f"cannot open {relative}: {exc.strerror}") from exc
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
    was = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    now = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if was != now or len(payload) != before.st_size:
        raise ReviewError(
            "E_SOURCE_CHANGED_DURING_CAPTURE", f"{relative} changed while being captured"
        )
    return _classify(payload, mode)


def _classify(payload: bytes, mode: str | None) -> dict[str, Any]:
    digest = sha256_digest(payload)
    if mode == "120000":
        return _entry_info("symlink", sha256=digest, size_bytes=len(payload), git_mode=mode,
                           payload=payload)
    if b"\0" in payload:
        availability, line_count = "binary", None
    else:
        try:
            payload.decode("utf-8")
        except UnicodeDecodeError:
            availability, line_count = "binary", None
        else:
            availability, line_count = "text", count_lines(payload)
    return _entry_info(availability, sha256=digest, size_bytes=len(payload),
                       line_count=line_count, git_mode=mode, payload=payload)


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
    """One observed fact; worktree sides carry the bytes currently on disk."""
    if side["origin"] == "worktree":
        mode, size, digest = _probe_disk(repo, path)
        return ("worktree", None, None, mode, size, digest)
    frozen = (side["origin"], side["revision"], side["git_oid"], side["git_mode"])
    return (*frozen, None, None)


def _source_fact(source: dict[str, Any]) -> tuple[Any, ...]:
    """The same fact shape, taken from what one captured source recorded."""
    if source["origin"] == "worktree":
        return ("worktree", None, None, source["git_mode"], source["size_bytes"],
                source["sha256"])
    frozen = (source["origin"], source["revision"], source["git_oid"], source["git_mode"])
    return (*frozen, None, None)


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
    """Project the current repository state onto the same facts, context included."""
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


def _fact_changes(
    recorded: dict[tuple[str, str, str], tuple[Any, ...]],
    observed: dict[tuple[str, str, str], tuple[Any, ...]],
) -> set[str]:
    """Paths whose observed fact differs, including a fact that appeared or went away.

    A recorded worktree digest of ``None`` means the bytes were never captured,
    so only the mode and size an observation can see are compared.
    """
    changed: set[str] = set()
    for key in set(recorded) | set(observed):
        was, now = recorded.get(key), observed.get(key)
        if was is None or now is None or was[:5] != now[:5] or (
            was[5] is not None and was[5] != now[5]
        ):
            changed.add(key[1])
    return changed


def capture_scope(repo: Path, request: ScopeRequest, output: Path) -> dict[str, Any]:
    """Capture the requested scope into a new packet directory."""
    resolved = resolve_request(repo, request)
    packet = _output_directory(Path(resolved["root"]), Path(output), "packet output directory")
    return _capture_into(packet, resolved)


def _capture_into(packet: Path, state: dict[str, Any]) -> dict[str, Any]:
    root = Path(state["root"])
    entries = enumerate_items(root, state)
    if len(entries) > MAX_ITEMS:
        raise ReviewError(
            "E_ITEMS_LIMIT",
            f"the requested range has {len(entries)} items, over the {MAX_ITEMS} limit",
        )
    sides = _requested_sides(root, state, entries)
    keys = sorted(sides)
    (packet / "objects").mkdir(mode=0o700, exist_ok=True)
    bounded = state["observation"] == "bounded_double_observation"
    limitations: list[str] = [IGNORED_UNTRACKED_LIMIT] if bounded else []
    source_records = _capture_sources(root, packet, sides, keys, limitations)
    item_records = _item_records(entries, source_records)
    scope = {
        "schema_version": SCOPE_SCHEMA_VERSION,
        "mode": state["mode"],
        "request": state["request"],
        "resolved": state["resolved"],
        "observation": state["observation"],
        "items": item_records,
        "sources": [source_records[key] for key in keys],
        "limitations": dedupe_texts(limitations),
    }
    scope_bytes = _seal_scope(packet, scope, root, state)
    sources = scope["sources"]
    return {
        "packet": str(packet), "scope_sha256": sha256_digest(scope_bytes),
        "mode": scope["mode"], "items": len(item_records), "sources": len(sources),
        "partial": any(source["availability"] != TEXT_AVAILABILITY for source in sources),
        "limitations": scope["limitations"],
    }


def _requested_sides(
    root: Path,
    state: dict[str, Any],
    entries: list[dict[str, Any]],
) -> dict[tuple[str, str, str, str], tuple[dict[str, Any], str]]:
    """Collect every item side plus every existing version of the context paths."""
    sides: dict[tuple[str, str, str, str], tuple[dict[str, Any], str]] = {}
    for entry in entries:
        for side in (entry["before"], entry["after"]):
            if side is not None:
                sides[_source_key(side, entry["path"])] = (side, entry["path"])
    for path in state["request"]["context_paths"]:
        context_sides = _context_sides(root, state, path)
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
        if side["origin"] == "worktree":
            info = _read_disk(root, path)
            git_mode = info["git_mode"]
        else:
            info = _read_git_object(root, side["git_oid"], side["git_mode"])
            git_mode = side["git_mode"]
        availability, digest = info["availability"], info["sha256"]
        if (availability in CAPTURED_AVAILABILITY and digest not in written
                and used + (info["size_bytes"] or 0) > MAX_PACKET_BYTES):
            availability = "budget_exhausted"
        captured = availability in CAPTURED_AVAILABILITY
        if not captured:
            reason = ("the packet byte budget was exhausted"
                      if availability == "budget_exhausted" else availability)
            limitations.append(f"{path} was not captured ({reason}).")
        source_records[key] = {
            "id": f"S-{index:06d}", "path": path, "origin": side["origin"],
            "revision": side["revision"], "git_oid": side["git_oid"], "git_mode": git_mode,
            "availability": availability, "sha256": digest if captured else None,
            "size_bytes": info["size_bytes"],
            "line_count": info["line_count"] if captured else None,
        }
        if captured and digest not in written:
            assert digest is not None
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
    def order(entry: dict[str, Any]) -> tuple[int, bytes]:
        return (LAYER_ORDER.index(entry["layer"]), entry["path"].encode("utf-8"))

    records: list[dict[str, Any]] = []
    for index, entry in enumerate(sorted(entries, key=order), start=1):
        record: dict[str, Any] = {"id": f"I-{index:06d}", "layer": entry["layer"],
                                  "status": entry["status"], "path": entry["path"]}
        for side_name in ("before", "after"):
            side = entry[side_name]
            record[side_name] = (None if side is None
                                 else source_records[_source_key(side, entry["path"])]["id"])
        records.append(record)
    return records


def _seal_scope(
    packet: Path,
    scope: dict[str, Any],
    root: Path,
    state: dict[str, Any],
) -> bytes:
    """Re-observe the request, validate the whole scope, then publish scope.json.

    The completion marker appears only after every check passed, the encoded
    document is bounded, and the bytes were written to a private temporary file.
    """
    if state["observation"] == "bounded_double_observation":
        recorded = _recorded_facts(
            scope["items"], scope["sources"], scope["request"]["context_paths"]
        )
        changed = _fact_changes(recorded, _observed_facts(root, state))
        if changed:
            raise ReviewError(
                "E_SOURCE_CHANGED_DURING_CAPTURE",
                "the workspace changed during capture: " + ", ".join(sorted(changed)),
            )
    validate_scope(scope)
    scope_bytes = encode_document(scope)
    _publish_scope(packet, scope_bytes)
    return scope_bytes


def _publish_scope(packet: Path, scope_bytes: bytes) -> None:
    """Publish the completion marker atomically; a failed write leaves no scope.json."""
    final = packet / SCOPE_FILE
    handle, temp_name = tempfile.mkstemp(dir=packet, prefix=".scope-", suffix=".tmp")
    try:
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(scope_bytes)
        except OSError as exc:
            raise ReviewError("E_OUTPUT", f"cannot write {SCOPE_FILE}: {exc.strerror}") from exc
        try:
            os.link(temp_name, final)
        except FileExistsError as exc:
            raise ReviewError("E_OUTPUT", f"{final} already exists") from exc
        except OSError as exc:
            raise ReviewError("E_OUTPUT", f"cannot publish {SCOPE_FILE}: {exc.strerror}") from exc
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _tree_side(root: Path, revision: str, path: str) -> dict[str, Any] | None:
    for git_mode, kind, git_oid, candidate in _ls_tree(root, revision, [path]):
        if candidate != path:
            continue
        if kind == "commit":
            return _git_side("git", revision, "160000", git_oid)
        if kind == "blob":
            return _git_side("git", revision, git_mode, git_oid)
    return None


def _context_sides(root: Path, state: dict[str, Any], path: str) -> list[dict[str, Any]]:
    """Capture the versions of one context path that exist in the compared states."""
    oids = state["resolved"]
    mode = state["mode"]
    if mode in ("commit", "range"):
        if mode == "commit":
            revisions = ([] if state["root_commit"] else state["parents"][:1]) + [
                oids["head_oid"]
            ]
        else:
            revisions = (oids["comparison_base_oid"], oids["head_oid"])
        return [side for side in (_tree_side(root, revision, path) for revision in revisions)
                if side is not None]
    if mode == "workspace":
        sides: list[dict[str, Any]] = []
        head = _tree_side(root, oids["head_oid"], path) if oids["head_oid"] else None
        if head is not None:
            sides.append(head)
        staged = _ls_files_stage(root, [path]).get(path)
        if staged is not None:
            sides.append(_git_side("index", None, *staged))
        if _disk_kind(root, path) in ("file", "link"):
            sides.append(_disk_side(None))
        return sides
    if state["worktree_snapshot"]:
        staged = _ls_files_stage(root, [path]).get(path)
        if staged is None:
            return [_disk_side(None)] if _disk_kind(root, path) in ("file", "link") else []
        git_mode, git_oid = staged
        if git_mode == "160000":
            return [_git_side("index", None, git_mode, git_oid)]
        return [_disk_side(git_mode)] if _disk_kind(root, path) in ("file", "link") else []
    side = _tree_side(root, oids["head_oid"], path)
    return [side] if side is not None else []


def compare_scope(root: Path, scope: dict[str, Any]) -> dict[str, Any]:
    """Re-observe captured sources and report freshness for the recorded scope.

    The caller validated the record and resolved the real root, so this pass
    only compares facts.
    """
    incomplete = any(
        source["availability"] not in CAPTURED_AVAILABILITY for source in scope["sources"]
    )
    if scope["observation"] == "immutable_commits":
        return _freshness(False, incomplete)
    # A frozen commit snapshot is immutable as well; only the worktree one is re-observed.
    state = {
        "mode": scope["mode"], "root": str(root), "request": scope["request"],
        "resolved": scope["resolved"], "observation": scope["observation"],
        "root_commit": True, "parents": [],
        "worktree_snapshot": scope["request"]["revision"] == WORKTREE_REVISION,
    }
    recorded = _recorded_facts(scope["items"], scope["sources"], scope["request"]["context_paths"])
    changed = _fact_changes(recorded, _observed_facts(root, state))
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
