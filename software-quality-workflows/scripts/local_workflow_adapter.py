#!/usr/bin/env python3
"""Crash-safe M1 trace appends and M2/M3 local workflow state."""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterator

try:
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on Windows hosts
    fcntl = None
try:
    import msvcrt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised on POSIX hosts
    msvcrt = None

from _workflow_state import (
    _decode_json,
    canonical_artifact_hash,
    canonical_hash,
    contains_secret_like,
    load_json,
    load_json_lines,
    patterns_may_overlap,
    validate_against_schema,
    validate_closure_artifact,
    validate_review_result,
)
from reconcile_workflow import reconcile
from validate_workflow_state import validate_event_stream, validate_state, validate_transition


class AdapterConflict(RuntimeError):
    pass


_TASK_ID = re.compile(r"^TASK-[A-Z0-9][A-Z0-9._-]{0,95}$")
_RUN_ID = re.compile(r"^RUN-[A-Z0-9][A-Z0-9._-]{0,95}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_REF = re.compile(r"^artifact:[a-z][a-z0-9-]*/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$")
_TASK_ROLES = {"repo_explorer", "spec_auditor", "solution_planner", "candidate_worker", "test_analyst", "reviewer"}
_REQUIRED_FORBIDDEN_ACTIONS = {"publish", "change_contract", "change_verifier_kernel", "promote", "close"}
_CANDIDATE_OUTPUTS = {"candidate_manifest", "change_summary", "verification_requests"}
_TASK_STOP_CONDITIONS = {"task_completed", "scope_blocked", "environment_blocked"}
_REQUIRED_CODEX_ROOT_FLAGS = {"--ask-for-approval"}
_REQUIRED_CODEX_EXEC_FLAGS = {"--json", "--output-schema", "--output-last-message", "--sandbox", "-C", "resume"}
_WORKTREE_ID = re.compile(r"^(?:CAND|INTEGRATION)-[A-Z0-9][A-Z0-9._-]{0,95}$")
_MAX_GIT_OUTPUT = 64 * 1024 * 1024
_MAX_CHANGED_PATHS = 10000
_MAX_SNAPSHOT_FILE = 16 * 1024 * 1024
_MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
_SKILL_ROOT = Path(__file__).resolve().parents[1]
_CODEX_RESULT_SCHEMA = _SKILL_ROOT / "schemas" / "codex-task-result.schema.json"
_CLOSURE_ARTIFACT_SCHEMA = _SKILL_ROOT / "schemas" / "closure-artifacts.schema.json"
_REVIEW_RESULT_SCHEMA = _SKILL_ROOT / "schemas" / "review-result.schema.json"


def _contract_error(code: str, path: str, message: str) -> str:
    return f"{code}@{path}:{message}"


def _safe_relative(value: Any, *, patterns: bool) -> bool:
    if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value or "\\" in value:
        return False
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    if not patterns and any(character in value for character in "*?[]{}"):
        return False
    return True


def _matches_path(path: str, pattern: str) -> bool:
    normalized = pattern.rstrip("/")
    if normalized.endswith("/**"):
        root = normalized[:-3].rstrip("/")
        if path == root or path.startswith(root + "/"):
            return True
    return fnmatchcase(path, normalized)


def _unique_string_list(value: Any, *, maximum: int = 1000) -> bool:
    return isinstance(value, list) and len(value) <= maximum and len(value) == len(set(value)) and all(isinstance(item, str) and 1 <= len(item) <= 1024 for item in value)


def validate_codex_task_envelope(
    task: dict[str, Any],
    *,
    worktrees_root: Path,
    state: dict[str, Any] | None = None,
) -> list[str]:
    """Validate a bounded Codex task proposal before any process is started."""
    errors: list[str] = []
    required = {
        "task_id", "run_id", "role", "objective", "working_directory", "source_revision", "contract_ref", "plan_ref",
        "policy_bundle_hash", "constraint_refs", "counterexample_refs", "allowed_write_paths", "protected_paths",
        "required_outputs", "forbidden_actions", "stop_conditions", "sandbox_profile", "network_policy", "timeout_seconds",
    }
    optional = {"session_binding"}
    if not isinstance(task, dict):
        return [_contract_error("E_SCHEMA_INVALID", "", "task envelope must be an object")]
    missing = sorted(required - set(task))
    unknown = sorted(set(task) - required - optional)
    errors.extend(_contract_error("E_SCHEMA_INVALID", f"/{key}", "required property is missing") for key in missing)
    errors.extend(_contract_error("E_SCHEMA_INVALID", f"/{key}", "unknown property") for key in unknown)
    if not _TASK_ID.fullmatch(str(task.get("task_id", ""))):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/task_id", "invalid task ID"))
    if not _RUN_ID.fullmatch(str(task.get("run_id", ""))):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/run_id", "invalid run ID"))
    if task.get("role") not in _TASK_ROLES:
        errors.append(_contract_error("E_SCHEMA_INVALID", "/role", "unknown bounded agent role"))
    if not isinstance(task.get("objective"), str) or not 1 <= len(task["objective"]) <= 4096:
        errors.append(_contract_error("E_SCHEMA_INVALID", "/objective", "objective must be a bounded non-empty string"))
    if not isinstance(task.get("source_revision"), str) or not task["source_revision"] or len(task["source_revision"]) > 256:
        errors.append(_contract_error("E_SCHEMA_INVALID", "/source_revision", "invalid source revision"))

    try:
        candidate = Path(task.get("working_directory", "")).resolve(strict=False)
        resolved_worktrees = worktrees_root.resolve(strict=False)
        candidate.relative_to(resolved_worktrees)
        if candidate == resolved_worktrees:
            raise ValueError
        if task.get("role") == "candidate_worker" and (candidate.parent != resolved_worktrees or not _WORKTREE_ID.fullmatch(candidate.name) or not candidate.name.startswith("CAND-")):
            raise ValueError
    except (OSError, TypeError, ValueError):
        errors.append(_contract_error("E_SCOPE_VIOLATION", "/working_directory", "working directory must be the task-bound candidate below the controller-owned worktrees root"))

    for name, with_epoch in (("contract_ref", True), ("plan_ref", False)):
        binding = task.get(name)
        if not isinstance(binding, dict):
            errors.append(_contract_error("E_SCHEMA_INVALID", f"/{name}", "artifact binding must be an object"))
            continue
        expected_keys = {"artifact_ref", "hash", "epoch"} if with_epoch else {"artifact_ref", "hash"}
        if set(binding) != expected_keys or not _ARTIFACT_REF.fullmatch(str(binding.get("artifact_ref", ""))) or not _HASH.fullmatch(str(binding.get("hash", ""))):
            errors.append(_contract_error("E_SCHEMA_INVALID", f"/{name}", "artifact binding keys or hash are invalid"))
        if with_epoch and (not isinstance(binding.get("epoch"), int) or isinstance(binding.get("epoch"), bool) or binding.get("epoch", 0) < 1):
            errors.append(_contract_error("E_EPOCH_MISMATCH", f"/{name}/epoch", "contract epoch must be a positive integer"))
    if not _HASH.fullmatch(str(task.get("policy_bundle_hash", ""))):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/policy_bundle_hash", "invalid policy bundle hash"))

    for name in ("constraint_refs", "counterexample_refs", "allowed_write_paths", "protected_paths", "required_outputs", "forbidden_actions", "stop_conditions"):
        if not _unique_string_list(task.get(name)):
            errors.append(_contract_error("E_SCHEMA_INVALID", f"/{name}", "must be a bounded unique string array"))
    allowed = task.get("allowed_write_paths", []) if isinstance(task.get("allowed_write_paths"), list) else []
    protected = task.get("protected_paths", []) if isinstance(task.get("protected_paths"), list) else []
    if any(not _safe_relative(item, patterns=True) for item in [*allowed, *protected]):
        errors.append(_contract_error("E_SCOPE_VIOLATION", "/allowed_write_paths", "write and protected paths must be safe relative patterns"))
    if any(patterns_may_overlap(left, right) for left in allowed for right in protected):
        errors.append(_contract_error("E_PROTECTED_SURFACE_CHANGED", "/allowed_write_paths", "allowed writes overlap a protected surface"))
    forbidden = set(task.get("forbidden_actions", [])) if isinstance(task.get("forbidden_actions"), list) else set()
    if not _REQUIRED_FORBIDDEN_ACTIONS.issubset(forbidden):
        errors.append(_contract_error("E_UNAUTHORIZED_TRANSITION", "/forbidden_actions", "worker must be forbidden from publish, policy/kernel change, promotion, and closure"))
    outputs = set(task.get("required_outputs", [])) if isinstance(task.get("required_outputs"), list) else set()
    if task.get("role") == "candidate_worker" and not _CANDIDATE_OUTPUTS.issubset(outputs):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/required_outputs", "candidate worker is missing a required structured output"))
    stops = set(task.get("stop_conditions", [])) if isinstance(task.get("stop_conditions"), list) else set()
    if not _TASK_STOP_CONDITIONS.issubset(stops):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/stop_conditions", "task is missing a mandatory typed stop condition"))
    if contains_secret_like(task.get("objective", "")):
        errors.append(_contract_error("E_SCOPE_VIOLATION", "/objective", "task objective contains credential-shaped data"))

    read_only_roles = {"repo_explorer", "spec_auditor", "solution_planner", "reviewer"}
    allowed_profiles = {"read-only"} if task.get("role") in read_only_roles else {"read-only", "workspace-write"}
    if task.get("role") == "candidate_worker":
        allowed_profiles = {"workspace-write"}
    if task.get("sandbox_profile") not in allowed_profiles:
        errors.append(_contract_error("E_SCOPE_VIOLATION", "/sandbox_profile", "sandbox profile is broader than the bounded role permits"))
    network = task.get("network_policy")
    if not isinstance(network, dict) or set(network) != {"enabled", "allowed_domains"} or not isinstance(network.get("enabled"), bool) or not _unique_string_list(network.get("allowed_domains"), maximum=64):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/network_policy", "network policy must explicitly bind enabled and unique allowed domains"))
    elif network["enabled"] != bool(network["allowed_domains"]):
        errors.append(_contract_error("E_SCOPE_VIOLATION", "/network_policy", "enabled network requires a non-empty domain allowlist and disabled network requires none"))
    elif any(not _DOMAIN.fullmatch(domain) for domain in network["allowed_domains"]):
        errors.append(_contract_error("E_SCOPE_VIOLATION", "/network_policy/allowed_domains", "network allowlist entries must be exact DNS names"))
    timeout = task.get("timeout_seconds")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86400:
        errors.append(_contract_error("E_SCHEMA_INVALID", "/timeout_seconds", "timeout must be between 1 and 86400 seconds"))

    if state is not None:
        run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
        expected = {
            "/source_revision": (task.get("source_revision"), state.get("source", {}).get("observed_revision")),
            "/policy_bundle_hash": (task.get("policy_bundle_hash"), state.get("policy_bundle_hash")),
            "/contract_ref/hash": (task.get("contract_ref", {}).get("hash"), run.get("contract_ref", {}).get("content_hash")),
            "/contract_ref/epoch": (task.get("contract_ref", {}).get("epoch"), run.get("contract_ref", {}).get("epoch")),
            "/plan_ref/hash": (task.get("plan_ref", {}).get("hash"), state.get("plan_ref", {}).get("content_hash")),
        }
        for path, (observed, frozen) in expected.items():
            if observed != frozen:
                errors.append(_contract_error("E_ARTIFACT_STALE", path, "task binding differs from frozen workflow state"))
    return sorted(set(errors))


def validate_codex_task_result(result: dict[str, Any], schema: dict[str, Any], *, task: dict[str, Any]) -> list[str]:
    errors = [
        _contract_error(item.code, item.path, item.message)
        for item in validate_against_schema(result, schema, code="E_SCHEMA_INVALID")
    ]
    if not isinstance(result, dict):
        return sorted(set(errors))
    if result.get("task_id") != task.get("task_id"):
        errors.append(_contract_error("E_ARTIFACT_STALE", "/task_id", "result belongs to another task"))
    allowed = task.get("allowed_write_paths", []) if isinstance(task.get("allowed_write_paths"), list) else []
    protected = task.get("protected_paths", []) if isinstance(task.get("protected_paths"), list) else []
    for index, path in enumerate(result.get("changed_paths", []) if isinstance(result.get("changed_paths"), list) else []):
        pointer = f"/changed_paths/{index}"
        if not _safe_relative(path, patterns=False):
            errors.append(_contract_error("E_SCOPE_VIOLATION", pointer, "changed path is not a safe relative concrete path"))
            continue
        if any(_matches_path(path, pattern) for pattern in protected):
            errors.append(_contract_error("E_PROTECTED_SURFACE_CHANGED", pointer, "changed path is protected"))
        elif not any(_matches_path(path, pattern) for pattern in allowed):
            errors.append(_contract_error("E_SCOPE_VIOLATION", pointer, "changed path is outside allowed writes"))
    for field in ("claims", "blocker"):
        if contains_secret_like(result.get(field)):
            errors.append(_contract_error("E_SCOPE_VIOLATION", f"/{field}", "result contains credential-shaped data"))
    if result.get("status") == "completed" and task.get("role") == "candidate_worker":
        worktree_id = Path(str(task.get("working_directory", ""))).name
        candidate_id = "C-" + worktree_id.removeprefix("CAND-")
        if result.get("candidate_ref") != f"artifact:candidate/{candidate_id}":
            errors.append(_contract_error("E_ARTIFACT_STALE", "/candidate_ref", "candidate result identity differs from task identity"))
    return sorted(set(errors))


def validate_codex_resume(session: dict[str, Any], task: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "task_id": task.get("task_id"),
        "source_revision": task.get("source_revision"),
        "contract_hash": task.get("contract_ref", {}).get("hash"),
        "contract_epoch": task.get("contract_ref", {}).get("epoch"),
        "plan_hash": task.get("plan_ref", {}).get("hash"),
        "policy_bundle_hash": task.get("policy_bundle_hash"),
    }
    if not isinstance(session, dict) or not isinstance(session.get("session_id"), str) or not session.get("session_id"):
        errors.append(_contract_error("E_SCHEMA_INVALID", "/session_id", "resume requires a recorded session ID"))
    for key, value in expected.items():
        if session.get(key) != value:
            errors.append(_contract_error("E_ARTIFACT_STALE", f"/{key}", "session binding differs from current task"))
    return sorted(set(errors))


def probe_codex_capabilities(
    executable: str = "codex",
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    commands = [[executable, "--help"], [executable, "exec", "--help"]]
    outputs: list[str] = []
    returncodes: list[int] = []
    try:
        for command in commands:
            result = runner(command, capture_output=True, text=True, check=False, timeout=15)
            outputs.append(f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}")
            returncodes.append(getattr(result, "returncode", 1))
    except (OSError, subprocess.SubprocessError) as exc:
        missing = sorted(_REQUIRED_CODEX_ROOT_FLAGS | _REQUIRED_CODEX_EXEC_FLAGS)
        return {"qualified": False, "commands": commands, "missing": missing, "error": str(exc)}
    missing = sorted(
        {flag for flag in _REQUIRED_CODEX_ROOT_FLAGS if flag not in outputs[0]}
        | {flag for flag in _REQUIRED_CODEX_EXEC_FLAGS if flag not in outputs[1]}
    )
    return {
        "qualified": all(code == 0 for code in returncodes) and not missing,
        "commands": commands,
        "missing": missing,
        "returncodes": returncodes,
    }


def _run_git(repository: Path, arguments: list[str], *, timeout: int = 60, input_data: bytes | None = None) -> bytes:
    command = [
        "git",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "core.fsmonitor=false",
        "-c", "core.pager=cat",
        "-c", "color.ui=false",
        "-C", str(repository),
        *arguments,
    ]
    environment = os.environ.copy()
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    try:
        result = subprocess.run(
            command,
            input=input_data,
            stdin=subprocess.DEVNULL if input_data is None else None,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AdapterConflict(f"git command unavailable or timed out: {' '.join(arguments[:3])}: {exc}") from exc
    if len(result.stdout) + len(result.stderr) > _MAX_GIT_OUTPUT:
        raise AdapterConflict("git command output exceeds the bounded adapter limit")
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace")[:2048].strip()
        raise AdapterConflict(f"git command failed ({result.returncode}): {' '.join(arguments[:3])}: {detail}")
    return result.stdout


def _git_paths(payload: bytes) -> list[str]:
    raw_paths = [item for item in payload.split(b"\0") if item]
    if len(raw_paths) > _MAX_CHANGED_PATHS:
        raise AdapterConflict(f"candidate changes exceed {_MAX_CHANGED_PATHS} paths")
    try:
        paths = [item.decode("utf-8", errors="strict") for item in raw_paths]
    except UnicodeDecodeError as exc:
        raise AdapterConflict("candidate contains a path that is not valid UTF-8") from exc
    if any(not _safe_relative(path, patterns=False) for path in paths):
        raise AdapterConflict("git reported an unsafe candidate path")
    return paths


def _assert_safe_checkout_configuration(repository: Path, base_revision: str) -> None:
    head = _run_git(repository, ["rev-parse", "HEAD"]).decode("ascii", errors="strict").strip()
    if head != base_revision:
        raise AdapterConflict("E_SOURCE_DRIFT: repository HEAD differs from the frozen worktree base")
    status = _run_git(repository, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if status:
        raise AdapterConflict("E_SOURCE_DRIFT: dirty or untracked base must be frozen into an explicit scope snapshot before worktree creation")
    tracked = _run_git(repository, ["ls-files", "-z"])
    paths = [item for item in tracked.split(b"\0") if item]
    if len(paths) > 100000 or len(tracked) > _MAX_GIT_OUTPUT:
        raise AdapterConflict("repository checkout surface exceeds the bounded adapter limit")
    attributes = _run_git(repository, ["check-attr", "--cached", "-z", "--all", "--stdin"], input_data=tracked)
    fields = [item for item in attributes.split(b"\0") if item]
    if len(fields) % 3:
        raise AdapterConflict("git attribute probe returned a malformed result")
    active_filters: list[str] = []
    for index in range(0, len(fields), 3):
        path, attribute, value = fields[index : index + 3]
        if attribute == b"filter" and value not in {b"unspecified", b"unset"}:
            active_filters.append(path.decode("utf-8", errors="replace"))
    if active_filters:
        raise AdapterConflict(f"ENVIRONMENT_UNAVAILABLE: checkout filters are not permitted for controller-created worktrees: {active_filters[:8]}")


def _ensure_direct_child_directory(root: Path, name: str) -> Path:
    root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_fd = os.open(root, root_flags)
    except OSError as exc:
        raise AdapterConflict(f"controller root is not a safe directory: {root}: {exc}") from exc
    try:
        try:
            os.mkdir(name, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
        try:
            child_fd = os.open(name, root_flags, dir_fd=root_fd)
        except OSError as exc:
            raise AdapterConflict(f"managed directory is unsafe: {root / name}: {exc}") from exc
        os.close(child_fd)
    finally:
        os.close(root_fd)
    return root / name


def _write_once(directory: Path, name: str, data: bytes) -> None:
    if "/" in name or name in {"", ".", ".."}:
        raise AdapterConflict("immutable artifact name must be a direct child")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(directory, directory_flags)
    except OSError as exc:
        raise AdapterConflict(f"immutable artifact directory is unsafe: {directory}: {exc}") from exc
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    created = False
    try:
        try:
            descriptor = os.open(name, file_flags, 0o600, dir_fd=directory_fd)
            created = True
        except FileExistsError:
            read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                existing_fd = os.open(name, read_flags, dir_fd=directory_fd)
            except OSError as exc:
                raise AdapterConflict(f"existing immutable artifact is unsafe: {directory / name}: {exc}") from exc
            try:
                if not stat.S_ISREG(os.fstat(existing_fd).st_mode):
                    raise AdapterConflict(f"existing immutable artifact is not a regular file: {directory / name}")
                chunks: list[bytes] = []
                remaining = len(data) + 1
                while remaining > 0:
                    chunk = os.read(existing_fd, min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if b"".join(chunks) != data:
                    raise AdapterConflict(f"content-address collision or immutable artifact replacement: {directory / name}")
                return
            finally:
                os.close(existing_fd)
        assert descriptor is not None
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        os.fsync(directory_fd)
    except Exception:
        if created:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory_fd)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, data: bytes, *, failpoint: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if failpoint == "after_fsync":
            raise RuntimeError("injected crash after temp fsync")
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)


def _sync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _exclusive_guard(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".adapter.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise AdapterConflict(f"unsafe or unavailable adapter lock: {lock_path}: {exc}") from exc
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise AdapterConflict(f"adapter lock is not a regular file: {lock_path}")
    locked = False
    try:
        if fcntl is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AdapterConflict(f"adapter lock already held: {lock_path}") from exc
        elif msvcrt is not None:  # pragma: no cover - Windows host path
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AdapterConflict(f"adapter lock already held: {lock_path}") from exc
        else:  # pragma: no cover - unusual host
            raise AdapterConflict("host provides no supported process-scoped file lock")
        locked = True
        if fcntl is not None:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, f"pid={os.getpid()} acquired={datetime.now(timezone.utc).isoformat()}\n".encode("utf-8"))
        os.fsync(descriptor)
        yield
    finally:
        if locked and fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        elif locked and msvcrt is not None:  # pragma: no cover - Windows host path
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        os.close(descriptor)


class LocalWorkflowAdapter:
    def __init__(self, root: Path, state_schema: dict[str, Any], event_schema: dict[str, Any]) -> None:
        self.root = root.resolve()
        self.state_schema = state_schema
        self.event_schema = event_schema
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"
        self.locks_path = self.root / "locks.json"

    def _validated_state(self, state: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(state)
        candidate["state_hash"] = canonical_hash(candidate)
        violations = validate_state(candidate, self.state_schema)
        if violations:
            raise ValueError("invalid workflow state: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
        return candidate

    def initialize(self, state: dict[str, Any], *, failpoint: str | None = None) -> None:
        if state.get("mode") not in {"M2_SPARSE", "M3_FULL"}:
            raise ValueError("local durable adapter is only for M2/M3")
        with _exclusive_guard(self.root):
            candidate = self._validated_state(state)
            marker = self.root / ".initializing.json"
            if self.state_path.exists():
                existing = self.load_state()
                if existing.get("workflow_id") == candidate.get("workflow_id") and canonical_hash(existing) == canonical_hash(candidate):
                    marker.unlink(missing_ok=True)
                    _sync_directory(self.root)
                    return
                raise AdapterConflict(f"workflow already initialized: {self.state_path}")
            existing_names = {path.name for path in self.root.iterdir() if path.name != ".adapter.lock"}
            allowed_retry = {".initializing.json", "artifacts", "capsules", "events.jsonl", "locks.json", "README.md"}
            if existing_names and ".initializing.json" not in existing_names:
                raise AdapterConflict(f"workflow root is not empty/task-owned: {sorted(existing_names)}")
            if existing_names - allowed_retry:
                raise AdapterConflict(f"interrupted initialization contains unmanaged paths: {sorted(existing_names - allowed_retry)}")
            if marker.exists():
                marker_data = load_json(marker)
                if marker_data.get("workflow_id") != candidate.get("workflow_id"):
                    raise AdapterConflict("initialization marker belongs to another workflow")
            else:
                _atomic_write(marker, _json_bytes({"workflow_id": candidate["workflow_id"], "mode": candidate["mode"]}))
            (self.root / "artifacts").mkdir(exist_ok=True)
            (self.root / "capsules").mkdir(exist_ok=True)
            _atomic_write(self.events_path, b"")
            _atomic_write(self.locks_path, _json_bytes(candidate.get("locks", [])))
            _atomic_write(
                self.root / "README.md",
                b"# Task-owned workflow state\n\nGenerated only for M2/M3. Do not git-add automatically. Use the SQW local adapter for validated updates.\n",
            )
            if failpoint == "before_state":
                raise RuntimeError("injected crash before initial state commit")
            _atomic_write(self.state_path, _json_bytes(candidate))
            marker.unlink(missing_ok=True)
            _sync_directory(self.root)

    def load_state(self) -> dict[str, Any]:
        value = load_json(self.state_path)
        if not isinstance(value, dict):
            raise ValueError("state.json must contain an object")
        return value

    def load_effective_state(self) -> dict[str, Any]:
        state = deepcopy(self.load_state())
        state["locks"] = load_json(self.locks_path)
        state["state_hash"] = canonical_hash(state)
        return state

    def commit_state(self, state: dict[str, Any], *, expected_state_version: int, failpoint: str | None = None) -> None:
        with _exclusive_guard(self.root):
            previous = self.load_effective_state()
            if previous.get("execution_policy") == "autonomous_closure" or "closure_run" in state:
                raise AdapterConflict("autonomous closure state is controller-owned; use scripts/advance_closure.py")
            if previous.get("state_version") != expected_state_version:
                raise AdapterConflict(f"stale state version: expected {expected_state_version}, current {previous.get('state_version')}")
            proposed = deepcopy(state)
            proposed["locks"] = load_json(self.locks_path)
            candidate = self._validated_state(proposed)
            transition_errors = validate_transition(previous, candidate)
            if transition_errors:
                raise ValueError("invalid transition: " + "; ".join(f"{item.code}@{item.path}" for item in transition_errors))
            _atomic_write(self.state_path, _json_bytes(candidate), failpoint=failpoint)

    def append_event(self, event: dict[str, Any], *, expected_last_sequence: int) -> None:
        with _exclusive_guard(self.root):
            if self.load_state().get("execution_policy") == "autonomous_closure":
                raise AdapterConflict("autonomous closure events are controller-owned; use scripts/advance_closure.py")
            events = load_json_lines(self.events_path)
            actual = events[-1]["sequence"] if events else 0
            if actual != expected_last_sequence:
                raise AdapterConflict(f"stale event sequence: expected {expected_last_sequence}, current {actual}")
            candidate = events + [deepcopy(event)]
            violations = validate_event_stream(candidate, self.event_schema)
            if violations:
                raise ValueError("invalid event append: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
            payload = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for item in candidate)
            _atomic_write(self.events_path, payload)

    def acquire_lock(self, resource: str, owner: str, *, lease_expires_at: str, expected_state_version: int) -> dict[str, Any]:
        expires = datetime.fromisoformat(lease_expires_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None or expires <= now:
            raise ValueError("lock lease must be timezone-aware and in the future")
        with _exclusive_guard(self.root):
            state = self.load_state()
            if state.get("state_version") != expected_state_version:
                raise AdapterConflict(f"stale state version: expected {expected_state_version}, current {state.get('state_version')}")
            locks = load_json(self.locks_path)
            for lock in locks:
                if lock.get("resource") != resource:
                    continue
                lock_expiry = datetime.fromisoformat(lock["lease_expires_at"].replace("Z", "+00:00"))
                if lock_expiry <= now:
                    raise AdapterConflict(f"expired lock requires reconciliation before reuse: {lock.get('id')}")
                if lock.get("owner") == owner:
                    return lock
                raise AdapterConflict(f"resource already locked by {lock.get('owner')}: {resource}")
            acquired_at = now.isoformat()
            digest = sha256(f"{resource}\0{owner}\0{acquired_at}".encode("utf-8")).hexdigest()[:16]
            lock = {"id": f"LOCK-{digest}", "resource": resource, "owner": owner, "acquired_at": acquired_at, "lease_expires_at": lease_expires_at, "state_version": expected_state_version}
            locks.append(lock)
            _atomic_write(self.locks_path, _json_bytes(locks))
            return lock

    def release_lock(self, resource: str, owner: str) -> None:
        with _exclusive_guard(self.root):
            locks = load_json(self.locks_path)
            matching = [item for item in locks if item.get("resource") == resource]
            if matching and any(item.get("owner") != owner for item in matching):
                raise AdapterConflict(f"cannot release another owner's lock: {resource}")
            retained = [item for item in locks if not (item.get("resource") == resource and item.get("owner") == owner)]
            _atomic_write(self.locks_path, _json_bytes(retained))

    def store_artifact(self, data: bytes, *, sensitive: bool) -> dict[str, str]:
        if not self.state_path.is_file():
            raise AdapterConflict("initialize M2/M3 state before storing local artifacts")
        if sensitive:
            raise ValueError("sensitive payloads require an external controlled pointer and are not stored locally")
        decoded = data.decode("utf-8", errors="replace")
        if contains_secret_like(decoded):
            raise ValueError("raw credential-shaped artifact is forbidden; store an external controlled pointer")
        digest = sha256(data).hexdigest()
        relative = Path("artifacts") / f"sha256-{digest}.bin"
        artifacts = _ensure_direct_child_directory(self.root, "artifacts")
        _write_once(artifacts, relative.name, data)
        return {"artifact_ref": relative.as_posix(), "content_hash": f"sha256:{digest}", "classification": "internal"}

    def _git_worktree_context(
        self,
        repository_root: Path,
        identifier: str,
        base_revision: str,
        *,
        expected_prefix: str,
        expect_absent: bool,
    ) -> tuple[Path, Path, str]:
        if not _WORKTREE_ID.fullmatch(identifier) or not identifier.startswith(expected_prefix + "-"):
            raise AdapterConflict(f"invalid {expected_prefix.lower()} worktree ID: {identifier}")
        state = self.load_state()
        if state.get("execution_policy") != "autonomous_closure" or not isinstance(state.get("closure_run"), dict):
            raise AdapterConflict("candidate worktrees require an initialized autonomous-closure workflow")
        source = state.get("source") if isinstance(state.get("source"), dict) else {}
        if base_revision != source.get("base_revision") or base_revision != source.get("observed_revision"):
            raise AdapterConflict("E_SOURCE_DRIFT: requested worktree base differs from frozen and observed workflow source")
        repository = repository_root.resolve(strict=True)
        try:
            self.root.relative_to(repository)
        except ValueError as exc:
            raise AdapterConflict("workflow controller root must be inside the bound repository") from exc
        top = _run_git(repository, ["rev-parse", "--show-toplevel"]).decode("utf-8", errors="strict").strip()
        if Path(top).resolve(strict=True) != repository:
            raise AdapterConflict("repository_root is not the Git worktree root")
        resolved_base = _run_git(repository, ["rev-parse", "--verify", f"{base_revision}^{{commit}}"]).decode("ascii", errors="strict").strip()
        if resolved_base != base_revision:
            raise AdapterConflict("E_SOURCE_DRIFT: frozen base must be the exact resolved commit ID")
        _assert_safe_checkout_configuration(repository, resolved_base)
        worktrees = _ensure_direct_child_directory(self.root, "worktrees")
        target = worktrees / identifier
        try:
            target.relative_to(worktrees)
        except ValueError as exc:  # pragma: no cover - identifier regex already prevents this
            raise AdapterConflict("worktree path escapes the managed root") from exc
        if expect_absent and os.path.lexists(target):
            raise AdapterConflict(f"E_LOCK_CONFLICT: worktree already exists: {identifier}")
        if not expect_absent:
            try:
                mode = target.lstat().st_mode
            except OSError as exc:
                raise AdapterConflict(f"candidate worktree is missing: {identifier}: {exc}") from exc
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                raise AdapterConflict(f"candidate worktree is not a safe directory: {identifier}")
        return repository, target, resolved_base

    def _write_worktree_view(self, target: Path, artifacts: dict[str, bytes]) -> dict[str, str]:
        if len(artifacts) > 128 or sum(len(value) for value in artifacts.values()) > 8 * 1024 * 1024:
            raise AdapterConflict("closure view exceeds bounded file or byte limits")
        view = target / ".closure-view"
        view.mkdir(mode=0o700)
        hashes: dict[str, str] = {}
        for name, payload in sorted(artifacts.items()):
            if not _safe_relative(name, patterns=False) or name.startswith(".git") or len(payload) > _MAX_SNAPSHOT_FILE:
                raise AdapterConflict(f"unsafe closure-view artifact: {name}")
            path = view / PurePosixPath(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.resolve(strict=False).is_relative_to(view.resolve(strict=True)) is False:
                raise AdapterConflict(f"closure-view artifact escapes projection: {name}")
            _atomic_write(path, payload)
            path.chmod(0o444)
            hashes[name] = "sha256:" + sha256(payload).hexdigest()
        for directory in sorted((path for path in view.rglob("*") if path.is_dir()), reverse=True):
            directory.chmod(0o555)
        view.chmod(0o555)
        return hashes

    def _create_git_worktree(
        self,
        repository_root: Path,
        *,
        identifier: str,
        base_revision: str,
        kind: str,
        writer_id: str,
        allowed_write_paths: list[str],
        protected_paths: list[str],
        view_artifacts: dict[str, bytes],
    ) -> dict[str, Any]:
        repository, target, resolved_base = self._git_worktree_context(
            repository_root,
            identifier,
            base_revision,
            expected_prefix="CAND" if kind == "candidate" else "INTEGRATION",
            expect_absent=True,
        )
        if not isinstance(writer_id, str) or not 1 <= len(writer_id) <= 256:
            raise AdapterConflict("writer ID must be a bounded non-empty string")
        if not _unique_string_list(allowed_write_paths) or not _unique_string_list(protected_paths):
            raise AdapterConflict("worktree scope must use bounded unique path lists")
        if any(not _safe_relative(path, patterns=True) for path in [*allowed_write_paths, *protected_paths]):
            raise AdapterConflict("worktree scope contains an unsafe path pattern")
        if any(patterns_may_overlap(left, right) for left in allowed_write_paths for right in protected_paths):
            raise AdapterConflict("E_PROTECTED_SURFACE_CHANGED: writable scope overlaps a protected path")
        created = False
        try:
            _run_git(repository, ["worktree", "add", "--detach", str(target), resolved_base], timeout=120)
            created = True
            view_hashes = self._write_worktree_view(target, view_artifacts)
            metadata = {
                "schema_version": "1.0",
                "kind": kind,
                "identifier": identifier,
                "workflow_id": self.load_state().get("workflow_id"),
                "base_revision": resolved_base,
                "writer_id": writer_id,
                "worktree_path": target.relative_to(self.root).as_posix(),
                "allowed_write_paths": allowed_write_paths,
                "protected_paths": sorted(set(protected_paths) | {".closure-view/**"}),
                "view_hashes": view_hashes,
            }
            metadata_bytes = _json_bytes(metadata)
            metadata_artifact = self.store_artifact(metadata_bytes, sensitive=False)
            records = _ensure_direct_child_directory(self.root, "worktree-metadata")
            _write_once(records, f"{identifier}.json", metadata_bytes)
        except Exception:
            if created and os.path.lexists(target):
                try:
                    _run_git(repository, ["worktree", "remove", "--force", str(target)], timeout=120)
                except AdapterConflict:
                    pass
            raise
        event_type = "candidate_created" if kind == "candidate" else "artifact_observed"
        return {
            "worktree_path": str(target),
            "base_revision": resolved_base,
            "metadata_artifact": metadata_artifact,
            "event_proposal": {
                "type": event_type,
                "summary": f"{kind} worktree {identifier} created from frozen base",
                "artifact_pointers": [metadata_artifact],
            },
        }

    def create_candidate_worktree(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        base_revision: str,
        writer_id: str,
        allowed_write_paths: list[str],
        protected_paths: list[str],
        view_artifacts: dict[str, bytes] | None = None,
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            return self._create_git_worktree(
                repository_root,
                identifier=candidate_id,
                base_revision=base_revision,
                kind="candidate",
                writer_id=writer_id,
                allowed_write_paths=allowed_write_paths,
                protected_paths=protected_paths,
                view_artifacts=view_artifacts or {},
            )

    def create_integration_worktree(
        self,
        repository_root: Path,
        *,
        integration_id: str,
        base_revision: str,
        allowed_write_paths: list[str] | None = None,
        protected_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            return self._create_git_worktree(
                repository_root,
                identifier=integration_id,
                base_revision=base_revision,
                kind="integration",
                writer_id="controller",
                allowed_write_paths=allowed_write_paths or [],
                protected_paths=protected_paths or [".closure/**", ".closure-view/**"],
                view_artifacts={},
            )

    def _load_worktree_metadata(self, identifier: str, *, expected_kind: str = "candidate") -> dict[str, Any]:
        prefix = "CAND-" if expected_kind == "candidate" else "INTEGRATION-"
        if expected_kind not in {"candidate", "integration"} or not _WORKTREE_ID.fullmatch(identifier) or not identifier.startswith(prefix):
            raise AdapterConflict(f"invalid {expected_kind} worktree ID: {identifier}")
        metadata_path = self.root / "worktree-metadata" / f"{identifier}.json"
        try:
            metadata = load_json(metadata_path)
        except (OSError, ValueError) as exc:
            raise AdapterConflict(f"worktree metadata is unavailable or invalid: {identifier}: {exc}") from exc
        if not isinstance(metadata, dict) or metadata.get("identifier") != identifier or metadata.get("kind") != expected_kind:
            raise AdapterConflict(f"worktree metadata identity mismatch: {identifier}")
        if metadata.get("worktree_path") != f"worktrees/{identifier}":
            raise AdapterConflict(f"worktree metadata path mismatch: {identifier}")
        return metadata

    def _snapshot_file(self, worktree: Path, relative: str) -> tuple[dict[str, Any], bytes, bool]:
        path = worktree / PurePosixPath(relative)
        current = worktree
        for part in PurePosixPath(relative).parts[:-1]:
            current = current / part
            try:
                mode = current.lstat().st_mode
            except FileNotFoundError:
                return {"path": relative, "kind": "deleted"}, b"", False
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                return {"path": relative, "kind": "unsafe-parent"}, b"", True
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {"path": relative, "kind": "deleted"}, b"", False
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(path)
            try:
                unsafe = not path.resolve(strict=False).is_relative_to(worktree.resolve(strict=True))
            except OSError:
                unsafe = True
            payload = target.encode("utf-8", errors="surrogateescape")
            return {"path": relative, "kind": "symlink", "target": target, "content_hash": "sha256:" + sha256(payload).hexdigest()}, payload, unsafe
        if not stat.S_ISREG(info.st_mode):
            return {"path": relative, "kind": "special"}, b"", True
        if info.st_size > _MAX_SNAPSHOT_FILE:
            return {"path": relative, "kind": "oversize", "size": info.st_size}, b"", True
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError:
            return {"path": relative, "kind": "unsafe-read"}, b"", True
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                return {"path": relative, "kind": "special"}, b"", True
            chunks: list[bytes] = []
            remaining = _MAX_SNAPSHOT_FILE + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(descriptor)
        if len(payload) > _MAX_SNAPSHOT_FILE:
            return {"path": relative, "kind": "oversize", "size": len(payload)}, b"", True
        return {
            "path": relative,
            "kind": "regular",
            "mode": stat.S_IMODE(info.st_mode),
            "size": len(payload),
            "content_hash": "sha256:" + sha256(payload).hexdigest(),
        }, payload, False

    def _verify_worktree_view(self, worktree: Path, expected: dict[str, str]) -> list[str]:
        view = worktree / ".closure-view"
        try:
            if not stat.S_ISDIR(view.lstat().st_mode) or stat.S_ISLNK(view.lstat().st_mode):
                return [".closure-view"]
        except OSError:
            return [".closure-view"]
        actual: set[str] = set()
        for index, path in enumerate(view.rglob("*"), 1):
            if index > 256:
                return [".closure-view:too-many-files"]
            try:
                mode = path.lstat().st_mode
            except OSError:
                return [f".closure-view/{path.relative_to(view).as_posix()}:unreadable"]
            if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                actual.add(path.relative_to(view).as_posix())
        mismatches = sorted(actual ^ set(expected))
        for name, expected_hash in expected.items():
            record, _payload, unsafe = self._snapshot_file(view, name)
            if unsafe or record.get("kind") != "regular" or record.get("content_hash") != expected_hash:
                mismatches.append(f".closure-view/{name}")
        return sorted(set(mismatches))

    def _candidate_snapshot(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        expected_base_revision: str,
        allowed_write_paths: list[str],
        protected_paths: list[str],
        expected_kind: str = "candidate",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        expected_prefix = "CAND" if expected_kind == "candidate" else "INTEGRATION"
        repository, worktree, resolved_base = self._git_worktree_context(
            repository_root,
            candidate_id,
            expected_base_revision,
            expected_prefix=expected_prefix,
            expect_absent=False,
        )
        metadata = self._load_worktree_metadata(candidate_id, expected_kind=expected_kind)
        effective_protected = sorted(set(protected_paths) | {".closure-view/**"})
        if metadata.get("base_revision") != resolved_base:
            raise AdapterConflict("E_SOURCE_DRIFT: worktree metadata base differs from frozen source")
        if metadata.get("allowed_write_paths") != allowed_write_paths or metadata.get("protected_paths") != effective_protected:
            raise AdapterConflict("E_ARTIFACT_STALE: supplied worktree scope differs from immutable metadata")
        exclude = ":(exclude).closure-view/**"
        tracked = _git_paths(_run_git(worktree, ["diff", "--name-only", "-z", resolved_base, "--", ".", exclude]))
        untracked = _git_paths(_run_git(worktree, ["ls-files", "--others", "--exclude-standard", "-z", "--", ".", exclude]))
        changed_paths = sorted(set(tracked) | set(untracked))
        records: list[dict[str, Any]] = []
        contents: dict[str, bytes] = {}
        unsafe_paths: list[str] = []
        secret_paths: list[str] = []
        total = 0
        for path in changed_paths:
            record, payload, unsafe = self._snapshot_file(worktree, path)
            records.append(record)
            contents[path] = payload
            total += len(payload)
            if total > _MAX_SNAPSHOT_BYTES:
                raise AdapterConflict("candidate snapshot exceeds the bounded byte limit")
            if unsafe:
                unsafe_paths.append(path)
            if payload and contains_secret_like(payload.decode("utf-8", errors="replace")):
                secret_paths.append(path)
        view_mismatches = self._verify_worktree_view(worktree, metadata.get("view_hashes", {}))
        unsafe_paths.extend(view_mismatches)
        patch = _run_git(worktree, ["diff", "--binary", "--no-ext-diff", resolved_base, "--", ".", exclude])
        if contains_secret_like(patch.decode("utf-8", errors="replace")):
            secret_paths.append("tracked-patch")
        record_by_path = {item["path"]: item for item in records}
        untracked_binding = [{"path": path, "record": record_by_path[path]} for path in untracked]
        patch_hash = "sha256:" + sha256(patch + b"\0" + _json_bytes(untracked_binding)).hexdigest()
        base_tree = _run_git(repository, ["rev-parse", f"{resolved_base}^{{tree}}"]).decode("ascii", errors="strict").strip()
        tree_hash = "sha256:" + sha256(_json_bytes({"base_tree": base_tree, "records": records})).hexdigest()
        protected_changes = sorted(path for path in changed_paths if any(_matches_path(path, pattern) for pattern in effective_protected))
        scope_violations = sorted(path for path in changed_paths if not any(_matches_path(path, pattern) for pattern in allowed_write_paths))
        head = _run_git(worktree, ["rev-parse", "HEAD"]).decode("ascii", errors="strict").strip()
        public = {
            "candidate_id": candidate_id,
            "base_revision": resolved_base,
            "head_revision": head,
            "changed_paths": changed_paths,
            "untracked_paths": sorted(untracked),
            "patch_hash": patch_hash,
            "tree_hash": tree_hash,
            "protected_surface_changes": protected_changes,
            "scope_violations": scope_violations,
            "unsafe_paths": sorted(set(unsafe_paths)),
            "secret_paths": sorted(set(secret_paths)),
        }
        public["snapshot_hash"] = "sha256:" + sha256(_json_bytes(public)).hexdigest()
        public["eligible_for_archive"] = bool(changed_paths) and not any((protected_changes, scope_violations, unsafe_paths, secret_paths))
        internal = {"patch": patch, "contents": contents, "records": records, "untracked": sorted(untracked)}
        return public, internal

    def inspect_candidate_snapshot(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        expected_base_revision: str,
        allowed_write_paths: list[str],
        protected_paths: list[str],
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            snapshot, _internal = self._candidate_snapshot(
                repository_root,
                candidate_id=candidate_id,
                expected_base_revision=expected_base_revision,
                allowed_write_paths=allowed_write_paths,
                protected_paths=protected_paths,
            )
            return snapshot

    def apply_candidate_to_integration(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        integration_id: str,
        expected_candidate_snapshot_hash: str,
        archive_artifact: dict[str, str],
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            candidate_metadata = self._load_worktree_metadata(candidate_id)
            candidate_snapshot, candidate_internal = self._candidate_snapshot(
                repository_root,
                candidate_id=candidate_id,
                expected_base_revision=candidate_metadata["base_revision"],
                allowed_write_paths=candidate_metadata["allowed_write_paths"],
                protected_paths=candidate_metadata["protected_paths"],
            )
            if candidate_snapshot["snapshot_hash"] != expected_candidate_snapshot_hash:
                raise AdapterConflict("E_ARTIFACT_STALE: candidate changed before integration")
            self._validate_candidate_archive(
                candidate_id,
                expected_candidate_snapshot_hash,
                archive_artifact,
                candidate_snapshot,
                candidate_internal,
            )
            integration_metadata = self._load_worktree_metadata(integration_id, expected_kind="integration")
            for field in ("base_revision", "allowed_write_paths", "protected_paths"):
                if integration_metadata.get(field) != candidate_metadata.get(field):
                    raise AdapterConflict(f"E_ARTIFACT_STALE: integration {field} differs from archived candidate")
            before, _before_internal = self._candidate_snapshot(
                repository_root,
                candidate_id=integration_id,
                expected_base_revision=integration_metadata["base_revision"],
                allowed_write_paths=integration_metadata["allowed_write_paths"],
                protected_paths=integration_metadata["protected_paths"],
                expected_kind="integration",
            )
            if before["changed_paths"]:
                raise AdapterConflict("E_ARTIFACT_STALE: integration worktree is not clean")
            integration_path = self.root / "worktrees" / integration_id
            _run_git(
                integration_path,
                ["apply", "--index", "--binary", "--whitespace=nowarn", "-"],
                input_data=candidate_internal["patch"],
                timeout=120,
            )
            records = {item["path"]: item for item in candidate_internal["records"]}
            for relative in candidate_internal["untracked"]:
                record = records[relative]
                if record.get("kind") != "regular":
                    raise AdapterConflict(f"E_SCOPE_VIOLATION: integration cannot materialize non-regular untracked path {relative}")
                target = integration_path / PurePosixPath(relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.parent.resolve(strict=True).is_relative_to(integration_path.resolve(strict=True)) or os.path.lexists(target):
                    raise AdapterConflict(f"E_SCOPE_VIOLATION: integration untracked path is unsafe: {relative}")
                _atomic_write(target, candidate_internal["contents"][relative])
                target.chmod(record["mode"])
            integrated, integrated_internal = self._candidate_snapshot(
                repository_root,
                candidate_id=integration_id,
                expected_base_revision=integration_metadata["base_revision"],
                allowed_write_paths=integration_metadata["allowed_write_paths"],
                protected_paths=integration_metadata["protected_paths"],
                expected_kind="integration",
            )
            for field in ("changed_paths", "patch_hash", "tree_hash"):
                if integrated.get(field) != candidate_snapshot.get(field):
                    raise AdapterConflict(f"E_ARTIFACT_STALE: integration {field} differs from archived candidate")
            record_by_path = {item["path"]: item for item in integrated_internal["records"]}
            scope_manifest = {
                "base_revision": "sha256:" + sha256(integration_metadata["base_revision"].encode("utf-8")).hexdigest(),
                "head_revision": integrated["patch_hash"],
                "scope_hash": self.load_state()["source"]["scope_hash"],
                "paths": [
                    {
                        "path": path,
                        "snapshot_id": record_by_path[path].get("content_hash") or "sha256:" + sha256(_json_bytes(record_by_path[path])).hexdigest(),
                    }
                    for path in integrated["changed_paths"]
                ],
            }
            integration_ref = f"artifact:integration/{integration_id}"
            state = self.load_state()
            integration_artifact = {
                "schema_id": "sqw://artifact-envelope/1.0",
                "artifact_id": integration_id,
                "workflow_id": state["workflow_id"],
                "source_revision": state["source"]["observed_revision"],
                "scope_hash": state["source"]["scope_hash"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "producer": {"actor": "controller", "run_id": "RUN-integration"},
                "classification": "internal",
                "mime_type": "application/json",
                "command_ref": "git apply --index --binary <archived-candidate>",
                "redaction_policy": "none_required",
                "content_hash": "sha256:" + "0" * 64,
                "payload": {
                    "candidate_id": candidate_id,
                    "candidate_snapshot_hash": candidate_snapshot["snapshot_hash"],
                    "archive_artifact": archive_artifact,
                    "integration_snapshot": integrated,
                    "scope_manifest": scope_manifest,
                },
            }
            integration_artifact["content_hash"] = canonical_artifact_hash(integration_artifact)
            integration_pointer = self.store_artifact(_json_bytes(integration_artifact), sensitive=False)
            integration_artifact_path = self._write_closure_artifact(integration_ref, integration_artifact)
            return {
                "worktree_path": str(integration_path),
                "integration_ref": integration_ref,
                "integration_artifact": integration_pointer,
                "integration_artifact_path": str(integration_artifact_path),
                "snapshot": integrated,
                "scope_manifest": scope_manifest,
                "event_proposal": {
                    "type": "artifact_observed",
                    "summary": f"integration {integration_id} reproduces archived candidate {candidate_id}",
                    "artifact_refs": [integration_ref],
                    "artifact_pointers": [integration_pointer],
                },
            }

    def record_integration_signoff(
        self,
        repository_root: Path,
        signoff: dict[str, Any],
        *,
        candidate_manifest: dict[str, Any],
        integration: dict[str, Any],
        review_results: dict[str, dict[str, Any]],
        evidence_artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            state = self.load_state()
            run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
            if state.get("execution_policy") != "autonomous_closure" or not isinstance(run.get("contract_ref"), dict) or not isinstance(run.get("verifier_bundle_ref"), dict) or not isinstance(run.get("baseline_ref"), dict):
                raise AdapterConflict("sign-off requires a fully bound autonomous-closure state")
            integration_ref = integration.get("integration_ref")
            if not isinstance(integration_ref, str) or not _ARTIFACT_REF.fullmatch(integration_ref) or not integration_ref.startswith("artifact:integration/"):
                raise AdapterConflict("integration sign-off has no canonical integration artifact ref")
            integration_name = integration_ref.rsplit("/", 1)[-1]
            try:
                integration_artifact = load_json(self.root / "integration" / f"{integration_name}.json")
            except (OSError, ValueError) as exc:
                raise AdapterConflict(f"integration artifact is unavailable or invalid: {exc}") from exc
            integration_payload = integration_artifact.get("payload") if isinstance(integration_artifact, dict) and isinstance(integration_artifact.get("payload"), dict) else {}
            if any((
                integration_artifact.get("content_hash") != canonical_artifact_hash(integration_artifact),
                integration_artifact.get("workflow_id") != state.get("workflow_id"),
                integration_artifact.get("source_revision") != state.get("source", {}).get("observed_revision"),
                integration_payload.get("integration_snapshot") != integration.get("snapshot"),
                integration_payload.get("scope_manifest") != integration.get("scope_manifest"),
            )):
                raise AdapterConflict("E_ARTIFACT_STALE: integration artifact differs from current sign-off input")
            integration_metadata = self._load_worktree_metadata(integration_name, expected_kind="integration")
            current_integration, _current_internal = self._candidate_snapshot(
                repository_root,
                candidate_id=integration_name,
                expected_base_revision=integration_metadata["base_revision"],
                allowed_write_paths=integration_metadata["allowed_write_paths"],
                protected_paths=integration_metadata["protected_paths"],
                expected_kind="integration",
            )
            if current_integration != integration.get("snapshot"):
                raise AdapterConflict("E_ARTIFACT_STALE: integration worktree changed after review snapshot")

            candidate_ref = f"artifact:candidate/{candidate_manifest.get('payload', {}).get('candidate_id')}"
            if candidate_manifest.get("content_hash") != canonical_artifact_hash(candidate_manifest):
                raise AdapterConflict("E_HASH_MISMATCH: candidate manifest changed before sign-off")
            scope_manifest = integration.get("scope_manifest")
            if not isinstance(scope_manifest, dict) or scope_manifest.get("head_revision") != candidate_manifest.get("payload", {}).get("patch_hash") or scope_manifest.get("base_revision") != candidate_manifest.get("payload", {}).get("base_candidate_hash") or scope_manifest.get("scope_hash") != state.get("source", {}).get("scope_hash"):
                raise AdapterConflict("E_ARTIFACT_STALE: integration review manifest differs from candidate or workflow freshness")

            signoff_payload = signoff.get("payload") if isinstance(signoff, dict) and isinstance(signoff.get("payload"), dict) else {}
            axes = signoff_payload.get("axes") if isinstance(signoff_payload.get("axes"), dict) else {}
            review_refs = []
            for axis_name in ("requirements", "engineering"):
                axis = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else {}
                ref = axis.get("review_result_ref")
                if not isinstance(ref, str) or not ref.startswith("artifact:review/") or ref not in review_results:
                    raise AdapterConflict(f"sign-off {axis_name} axis has no resolved review result")
                if axis.get("review_result_hash") != canonical_artifact_hash(review_results[ref]):
                    raise AdapterConflict(f"E_ARTIFACT_STALE: sign-off {axis_name} review hash differs")
                review_refs.append(ref)
            if set(review_results) != set(review_refs):
                raise AdapterConflict("sign-off review set differs from the two review axes")
            review_schema = load_json(_REVIEW_RESULT_SCHEMA)
            for ref, review in review_results.items():
                violations = validate_review_result(
                    review,
                    review_schema,
                    scope_manifest,
                    current_head=integration["snapshot"]["patch_hash"],
                    current_scope_hash=state["source"]["scope_hash"],
                )
                if violations:
                    raise AdapterConflict("invalid sign-off review: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:12]))
                if review.get("code_review_verdict") != "pass" or review.get("merge_readiness") != "ready":
                    raise AdapterConflict("sign-off review is not pass/ready")

            expected_axis_refs: dict[str, str] = {}
            for ref, artifact in evidence_artifacts.items():
                if not isinstance(ref, str) or not ref.startswith("artifact:evidence/") or not isinstance(artifact, dict):
                    raise AdapterConflict("sign-off evidence map contains an invalid semantic artifact")
                payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
                axis_name = payload.get("axis")
                if axis_name not in {"verifier_integrity", "authority"} or axis_name in expected_axis_refs:
                    raise AdapterConflict("sign-off evidence must contain one distinct artifact per non-review axis")
                expected_axis_refs[axis_name] = ref
                if any((
                    artifact.get("schema_id") != "sqw://artifact-envelope/1.0",
                    artifact.get("artifact_id") != ref.rsplit("/", 1)[-1],
                    artifact.get("workflow_id") != state["workflow_id"],
                    artifact.get("source_revision") != state["source"]["observed_revision"],
                    artifact.get("scope_hash") != state["source"]["scope_hash"],
                    artifact.get("content_hash") != canonical_artifact_hash(artifact),
                    payload.get("verdict") != "pass",
                    payload.get("integration_ref") != integration_ref,
                )):
                    raise AdapterConflict(f"E_ARTIFACT_STALE: {axis_name} evidence differs from sign-off freshness")
                if axis_name == "verifier_integrity" and payload.get("verifier_bundle_hash") != run["verifier_bundle_ref"]["content_hash"]:
                    raise AdapterConflict("E_ARTIFACT_STALE: verifier evidence differs from frozen verifier bundle")
                if axis_name == "authority" and (payload.get("publication_ceiling") != "local_patch" or payload.get("external_writes") is not False):
                    raise AdapterConflict("E_PUBLICATION_CEILING: authority evidence exceeds local patch or permits external writes")
            if set(expected_axis_refs) != {"verifier_integrity", "authority"}:
                raise AdapterConflict("sign-off requires verifier-integrity and authority evidence")
            for axis_name in ("verifier_integrity", "authority"):
                axis = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else {}
                if axis.get("status") != "pass" or axis.get("evidence_refs") != [expected_axis_refs[axis_name]]:
                    raise AdapterConflict(f"sign-off {axis_name} axis must pass with its distinct fresh evidence")
            gates = signoff_payload.get("required_gate_results") if isinstance(signoff_payload.get("required_gate_results"), list) else []
            integration_gates = [gate for gate in gates if isinstance(gate, dict) and gate.get("gate_id") == "integration-reverification"]
            if len(integration_gates) != 1 or integration_gates[0].get("status") != "pass" or integration_ref not in integration_gates[0].get("evidence_refs", []):
                raise AdapterConflict("sign-off requires one passing integration-reverification gate")
            expected_freshness = {
                "source_revision": state["source"]["observed_revision"],
                "scope_hash": state["source"]["scope_hash"],
                "contract_hash": run["contract_ref"]["content_hash"],
                "verifier_bundle_hash": run["verifier_bundle_ref"]["content_hash"],
                "baseline_hash": run["baseline_ref"]["content_hash"],
            }
            if signoff_payload.get("candidate_ref") != candidate_ref or signoff_payload.get("candidate_hash") != candidate_manifest.get("content_hash") or signoff_payload.get("freshness") != expected_freshness:
                raise AdapterConflict("E_ARTIFACT_STALE: sign-off candidate or freshness binding differs")
            artifact_schema = load_json(_CLOSURE_ARTIFACT_SCHEMA)
            violations = validate_closure_artifact(
                signoff,
                artifact_schema,
                expected_workflow_id=state["workflow_id"],
                expected_closure_epoch=run["contract_ref"]["epoch"],
                expected_source_revision=state["source"]["observed_revision"],
                expected_scope_hash=state["source"]["scope_hash"],
                expected_contract_hash=run["contract_ref"]["content_hash"],
                expected_verifier_bundle_hash=run["verifier_bundle_ref"]["content_hash"],
            )
            if violations or signoff_payload.get("verdict") != "pass":
                detail = "; ".join(f"{item.code}@{item.path}" for item in violations[:12])
                raise AdapterConflict("sign-off artifact is invalid or not passing: " + detail)
            if signoff.get("producer", {}).get("actor") != "controller":
                raise AdapterConflict("E_UNAUTHORIZED_TRANSITION: sign-off artifact must be controller-produced")

            pointers: list[dict[str, str]] = []
            for ref, review in review_results.items():
                pointers.append(self.store_artifact(_json_bytes(review), sensitive=False))
                self._write_closure_artifact(ref, review)
            for ref, evidence in evidence_artifacts.items():
                pointers.append(self.store_artifact(_json_bytes(evidence), sensitive=False))
                self._write_closure_artifact(ref, evidence)
            signoff_ref = f"artifact:signoff/{signoff['artifact_id']}"
            signoff_pointer = self.store_artifact(_json_bytes(signoff), sensitive=False)
            self._write_closure_artifact(signoff_ref, signoff)
            pointers.append(signoff_pointer)
            return {
                "signoff_ref": signoff_ref,
                "signoff": signoff,
                "artifact_pointers": pointers,
                "event_proposal": {
                    "type": "signoff_completed",
                    "summary": f"four-axis sign-off passed for {candidate_ref} on {integration_ref}",
                    "artifact_refs": [signoff_ref],
                    "artifact_pointers": pointers,
                },
            }

    def archive_candidate(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        expected_base_revision: str,
        expected_snapshot_hash: str,
        allowed_write_paths: list[str],
        protected_paths: list[str],
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            return self._archive_candidate_unlocked(
                repository_root,
                candidate_id=candidate_id,
                expected_base_revision=expected_base_revision,
                expected_snapshot_hash=expected_snapshot_hash,
                allowed_write_paths=allowed_write_paths,
                protected_paths=protected_paths,
            )

    def _archive_candidate_unlocked(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        expected_base_revision: str,
        expected_snapshot_hash: str,
        allowed_write_paths: list[str],
        protected_paths: list[str],
    ) -> dict[str, Any]:
        snapshot, internal = self._candidate_snapshot(
            repository_root,
            candidate_id=candidate_id,
            expected_base_revision=expected_base_revision,
            allowed_write_paths=allowed_write_paths,
            protected_paths=protected_paths,
        )
        if snapshot["snapshot_hash"] != expected_snapshot_hash:
            raise AdapterConflict("E_ARTIFACT_STALE: candidate changed after the inspected snapshot")
        if not snapshot["eligible_for_archive"]:
            if snapshot["protected_surface_changes"]:
                raise AdapterConflict("E_PROTECTED_SURFACE_CHANGED: candidate cannot be archived as eligible")
            raise AdapterConflict("E_SCOPE_VIOLATION: candidate snapshot is unsafe, empty, secret-shaped, or outside scope")
        record_by_path = {item["path"]: item for item in internal["records"]}
        untracked_files = {
            path: {
                "record": record_by_path[path],
                "content_base64": base64.b64encode(internal["contents"][path]).decode("ascii"),
            }
            for path in internal["untracked"]
        }
        archive_payload = {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "base_revision": expected_base_revision,
            "snapshot_hash": snapshot["snapshot_hash"],
            "patch_hash": snapshot["patch_hash"],
            "tree_hash": snapshot["tree_hash"],
            "changed_paths": snapshot["changed_paths"],
            "tracked_patch_base64": base64.b64encode(internal["patch"]).decode("ascii"),
            "untracked_files": untracked_files,
        }
        archive_bytes = _json_bytes(archive_payload)
        if len(archive_bytes) > _MAX_GIT_OUTPUT:
            raise AdapterConflict("candidate archive exceeds the bounded retention artifact limit")
        archive_artifact = self.store_artifact(archive_bytes, sensitive=False)
        archive_record = {
            "candidate_id": candidate_id,
            "snapshot_hash": snapshot["snapshot_hash"],
            "archive_artifact": archive_artifact,
        }
        records = _ensure_direct_child_directory(self.root, "worktree-metadata")
        _write_once(records, f"{candidate_id}.archive.json", _json_bytes(archive_record))
        return {
            "archive_artifact": archive_artifact,
            "snapshot": snapshot,
            "event_proposal": {
                "type": "artifact_observed",
                "summary": f"candidate {candidate_id} archived at immutable snapshot {snapshot['snapshot_hash']}",
                "artifact_pointers": [archive_artifact],
            },
        }

    def _load_stored_artifact(self, binding: dict[str, str]) -> bytes:
        if not isinstance(binding, dict) or set(binding) != {"artifact_ref", "content_hash", "classification"}:
            raise AdapterConflict("archive artifact binding is malformed")
        raw = PurePosixPath(binding.get("artifact_ref", ""))
        if len(raw.parts) != 2 or raw.parts[0] != "artifacts" or not raw.parts[1].startswith("sha256-") or not raw.parts[1].endswith(".bin"):
            raise AdapterConflict("archive artifact pointer is outside managed content-addressed storage")
        if not _HASH.fullmatch(binding.get("content_hash", "")):
            raise AdapterConflict("archive artifact hash is malformed")
        if raw.parts[1] != f"sha256-{binding['content_hash'].removeprefix('sha256:')}.bin":
            raise AdapterConflict("archive artifact filename differs from its content hash")
        directory = self.root / "artifacts"
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd: int | None = None
        descriptor: int | None = None
        try:
            directory_fd = os.open(directory, directory_flags)
            descriptor = os.open(raw.parts[1], file_flags, dir_fd=directory_fd)
        except OSError as exc:
            if descriptor is not None:
                os.close(descriptor)
            if directory_fd is not None:
                os.close(directory_fd)
            raise AdapterConflict(f"archive artifact is unavailable or unsafe: {exc}") from exc
        try:
            assert descriptor is not None
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_GIT_OUTPUT:
                raise AdapterConflict("archive artifact is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = _MAX_GIT_OUTPUT + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(descriptor)
            assert directory_fd is not None
            os.close(directory_fd)
        if len(payload) > _MAX_GIT_OUTPUT or "sha256:" + sha256(payload).hexdigest() != binding["content_hash"]:
            raise AdapterConflict("E_ARTIFACT_STALE: archive artifact bytes differ from their binding")
        return payload

    def _validate_candidate_archive(
        self,
        candidate_id: str,
        expected_snapshot_hash: str,
        archive_artifact: dict[str, str],
        snapshot: dict[str, Any],
        internal: dict[str, Any],
    ) -> dict[str, Any]:
        archive_record_path = self.root / "worktree-metadata" / f"{candidate_id}.archive.json"
        try:
            archive_record = load_json(archive_record_path)
        except (OSError, ValueError) as exc:
            raise AdapterConflict(f"candidate has no valid controller-owned archive record: {exc}") from exc
        expected_record = {"candidate_id": candidate_id, "snapshot_hash": expected_snapshot_hash, "archive_artifact": archive_artifact}
        if archive_record != expected_record:
            raise AdapterConflict("E_ARTIFACT_STALE: archive binding differs from controller-owned archive record")
        archive_bytes = self._load_stored_artifact(archive_artifact)
        try:
            archive = _decode_json(archive_bytes.decode("utf-8"), str(archive_record_path))
        except (UnicodeDecodeError, ValueError) as exc:
            raise AdapterConflict(f"archive artifact is not valid JSON: {exc}") from exc
        expected_keys = {
            "schema_version", "candidate_id", "base_revision", "snapshot_hash", "patch_hash", "tree_hash",
            "changed_paths", "tracked_patch_base64", "untracked_files",
        }
        if not isinstance(archive, dict) or set(archive) != expected_keys:
            raise AdapterConflict("archive payload shape is invalid")
        if archive.get("candidate_id") != candidate_id or archive.get("snapshot_hash") != expected_snapshot_hash:
            raise AdapterConflict("E_ARTIFACT_STALE: archive identity differs from candidate snapshot")
        if any((
            archive.get("schema_version") != "1.0",
            archive.get("base_revision") != snapshot["base_revision"],
            archive.get("patch_hash") != snapshot["patch_hash"],
            archive.get("tree_hash") != snapshot["tree_hash"],
            archive.get("changed_paths") != snapshot["changed_paths"],
        )):
            raise AdapterConflict("E_ARTIFACT_STALE: archive snapshot fields differ from the current candidate")
        try:
            patch = base64.b64decode(archive["tracked_patch_base64"], validate=True)
        except (TypeError, ValueError) as exc:
            raise AdapterConflict(f"archive tracked patch is not canonical base64: {exc}") from exc
        if patch != internal["patch"]:
            raise AdapterConflict("E_ARTIFACT_STALE: archived tracked patch differs from candidate")
        untracked = archive.get("untracked_files")
        if not isinstance(untracked, dict) or sorted(untracked) != snapshot["untracked_paths"]:
            raise AdapterConflict("E_ARTIFACT_STALE: archive untracked path set differs from candidate")
        records = {item["path"]: item for item in internal["records"]}
        for path, entry in untracked.items():
            if not isinstance(entry, dict) or set(entry) != {"record", "content_base64"} or entry.get("record") != records.get(path):
                raise AdapterConflict(f"E_ARTIFACT_STALE: archive record differs for {path}")
            try:
                content = base64.b64decode(entry["content_base64"], validate=True)
            except (TypeError, ValueError) as exc:
                raise AdapterConflict(f"archive content is not canonical base64 for {path}: {exc}") from exc
            if content != internal["contents"].get(path):
                raise AdapterConflict(f"E_ARTIFACT_STALE: archived content differs for {path}")
        return archive

    def remove_candidate_worktree(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        expected_snapshot_hash: str,
        archive_artifact: dict[str, str] | None,
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            return self._remove_candidate_worktree_unlocked(
                repository_root,
                candidate_id=candidate_id,
                expected_snapshot_hash=expected_snapshot_hash,
                archive_artifact=archive_artifact,
            )

    def _remove_candidate_worktree_unlocked(
        self,
        repository_root: Path,
        *,
        candidate_id: str,
        expected_snapshot_hash: str,
        archive_artifact: dict[str, str] | None,
    ) -> dict[str, Any]:
        if archive_artifact is None:
            raise AdapterConflict("candidate removal requires a verified immutable archive")
        metadata = self._load_worktree_metadata(candidate_id)
        snapshot, internal = self._candidate_snapshot(
            repository_root,
            candidate_id=candidate_id,
            expected_base_revision=metadata["base_revision"],
            allowed_write_paths=metadata["allowed_write_paths"],
            protected_paths=metadata["protected_paths"],
        )
        if snapshot["snapshot_hash"] != expected_snapshot_hash:
            raise AdapterConflict("E_ARTIFACT_STALE: candidate changed after archive")
        self._validate_candidate_archive(candidate_id, expected_snapshot_hash, archive_artifact, snapshot, internal)
        repository = repository_root.resolve(strict=True)
        target = self.root / "worktrees" / candidate_id
        worktrees = (self.root / "worktrees").resolve(strict=True)
        if target.parent.resolve(strict=True) != worktrees or not stat.S_ISDIR(target.lstat().st_mode) or stat.S_ISLNK(target.lstat().st_mode):
            raise AdapterConflict("candidate removal target is outside the safe worktree root")
        _run_git(repository, ["worktree", "remove", "--force", str(target)], timeout=120)
        return {
            "removed_candidate_id": candidate_id,
            "archive_artifact": archive_artifact,
            "event_proposal": {
                "type": "candidate_pruned",
                "summary": f"candidate {candidate_id} removed after immutable archive verification",
                "artifact_pointers": [archive_artifact],
            },
        }

    def _load_task_record(self, task_id: str, suffix: str = "task") -> dict[str, Any]:
        if not _TASK_ID.fullmatch(task_id) or suffix not in {"task", "session", "result"}:
            raise AdapterConflict("invalid task record identity")
        path = self.root / "tasks" / f"{task_id}.{suffix}.json"
        try:
            value = load_json(path)
        except (OSError, ValueError) as exc:
            raise AdapterConflict(f"task {suffix} record is unavailable or invalid: {task_id}: {exc}") from exc
        if not isinstance(value, dict) or value.get("task_id") != task_id:
            raise AdapterConflict(f"task {suffix} record identity mismatch: {task_id}")
        return value

    def prepare_codex_task(self, task: dict[str, Any]) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            state = self.load_state()
            worktrees = self.root / "worktrees"
            errors = validate_codex_task_envelope(task, worktrees_root=worktrees, state=state)
            if errors:
                raise AdapterConflict("invalid Codex task envelope: " + "; ".join(errors[:12]))
            working_directory = Path(task["working_directory"]).resolve(strict=True)
            try:
                mode = working_directory.lstat().st_mode
            except OSError as exc:
                raise AdapterConflict(f"task worktree is unavailable: {exc}") from exc
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                raise AdapterConflict("task worktree is not a safe directory")
            if task.get("role") == "candidate_worker":
                metadata = self._load_worktree_metadata(working_directory.name)
                if metadata.get("base_revision") != task.get("source_revision"):
                    raise AdapterConflict("E_SOURCE_DRIFT: task worktree base differs from task source")
                if metadata.get("allowed_write_paths") != task.get("allowed_write_paths") or metadata.get("protected_paths") != task.get("protected_paths"):
                    raise AdapterConflict("E_ARTIFACT_STALE: task scope differs from immutable worktree metadata")
            payload = _json_bytes(task)
            artifact = self.store_artifact(payload, sensitive=False)
            tasks = _ensure_direct_child_directory(self.root, "tasks")
            _write_once(tasks, f"{task['task_id']}.task.json", payload)
            return {
                "status": "task_prepared",
                "task_id": task["task_id"],
                "task_artifact": artifact,
                "event_proposal": {
                    "type": "artifact_observed",
                    "summary": f"Codex task {task['task_id']} prepared with frozen bindings",
                    "artifact_pointers": [artifact],
                },
            }

    def record_codex_session(self, task_id: str, session: dict[str, Any]) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            task = self._load_task_record(task_id)
            errors = validate_codex_resume(session, task)
            required = {
                "task_id", "session_id", "source_revision", "contract_hash", "contract_epoch", "plan_hash",
                "policy_bundle_hash", "capability_fingerprint", "events_path", "result_path", "progress_path",
            }
            allowed = required | {
                "task_id", "session_id", "thread_id", "source_revision", "contract_hash", "contract_epoch",
                "plan_hash", "policy_bundle_hash", "capability_fingerprint", "events_path", "result_path", "progress_path",
                "termination", "exit_code",
            }
            if not isinstance(session, dict) or set(session) - allowed or required - set(session):
                errors.append(_contract_error("E_SCHEMA_INVALID", "", "session record fields differ from the required binding"))
            for key in ("thread_id", "capability_fingerprint", "events_path", "result_path", "progress_path"):
                if key in session and (not isinstance(session[key], str) or not 1 <= len(session[key]) <= 1024):
                    errors.append(_contract_error("E_SCHEMA_INVALID", f"/{key}", "session metadata must be a bounded non-empty string"))
            if not _HASH.fullmatch(str(session.get("capability_fingerprint", ""))):
                errors.append(_contract_error("E_SCHEMA_INVALID", "/capability_fingerprint", "capability fingerprint must be a SHA-256 binding"))
            termination = session.get("termination")
            exit_code = session.get("exit_code")
            if (termination is None) != (exit_code is None):
                errors.append(_contract_error("E_SCHEMA_INVALID", "/termination", "termination and exit_code must be recorded together"))
            elif termination is not None:
                if termination not in {"completed", "failed", "timeout", "cancelled"}:
                    errors.append(_contract_error("E_SCHEMA_INVALID", "/termination", "termination is not recognized"))
                if not isinstance(exit_code, int) or isinstance(exit_code, bool) or not 0 <= exit_code <= 255:
                    errors.append(_contract_error("E_SCHEMA_INVALID", "/exit_code", "exit_code must be an integer from 0 through 255"))
                elif (termination == "completed") != (exit_code == 0):
                    errors.append(_contract_error("E_SCHEMA_INVALID", "/exit_code", "completed requires zero and all failure terminations require nonzero"))
            output_paths = [session.get(field) for field in ("events_path", "result_path", "progress_path")]
            if len(set(output_paths)) != 3 or any(
                not _safe_relative(path, patterns=False) or len(PurePosixPath(path).parts) != 2 or PurePosixPath(path).parts[0] != "tasks"
                for path in output_paths if isinstance(path, str)
            ) or any(not isinstance(path, str) for path in output_paths):
                errors.append(_contract_error("E_SCOPE_VIOLATION", "/result_path", "session output paths must be distinct direct children of tasks/"))
            reserved = {f"tasks/{task_id}.{suffix}.json" for suffix in ("task", "session", "result")}
            if any(path in reserved for path in output_paths):
                errors.append(_contract_error("E_SCOPE_VIOLATION", "/result_path", "session outputs cannot replace controller task records"))
            if contains_secret_like(session):
                errors.append(_contract_error("E_SCOPE_VIOLATION", "", "session record contains credential-shaped data"))
            if errors:
                raise AdapterConflict("invalid Codex session binding: " + "; ".join(sorted(set(errors))[:12]))
            for field, maximum in (("events_path", _MAX_GIT_OUTPUT), ("progress_path", 16 * 1024 * 1024)):
                self._read_task_output(session[field], maximum=maximum)
            if termination in {"failed", "timeout", "cancelled"}:
                self._read_optional_task_output(session["result_path"], maximum=16 * 1024 * 1024)
            else:
                self._read_task_output(session["result_path"], maximum=16 * 1024 * 1024)
            payload = _json_bytes(session)
            artifact = self.store_artifact(payload, sensitive=False)
            tasks = _ensure_direct_child_directory(self.root, "tasks")
            _write_once(tasks, f"{task_id}.session.json", payload)
            return {"status": "session_recorded", "task_id": task_id, "session_artifact": artifact}

    def _read_task_output(self, relative: str, *, maximum: int) -> bytes:
        raw = PurePosixPath(relative)
        if not _safe_relative(relative, patterns=False) or len(raw.parts) != 2 or raw.parts[0] != "tasks":
            raise AdapterConflict("task output pointer is outside the controller-owned tasks directory")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        directory_fd: int | None = None
        descriptor: int | None = None
        try:
            directory_fd = os.open(self.root / "tasks", directory_flags)
            descriptor = os.open(raw.parts[1], file_flags, dir_fd=directory_fd)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise AdapterConflict("task output is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = maximum + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > maximum:
                raise AdapterConflict("task output exceeds the bounded byte limit")
            return payload
        except OSError as exc:
            raise AdapterConflict(f"task output is unavailable or unsafe: {relative}: {exc}") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory_fd is not None:
                os.close(directory_fd)

    def _read_optional_task_output(self, relative: str, *, maximum: int) -> bytes | None:
        raw = PurePosixPath(relative)
        if not _safe_relative(relative, patterns=False) or len(raw.parts) != 2 or raw.parts[0] != "tasks":
            raise AdapterConflict("task output pointer is outside the controller-owned tasks directory")
        try:
            info = (self.root / raw).lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AdapterConflict(f"task output is unavailable or unsafe: {relative}: {exc}") from exc
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AdapterConflict("task output is not a bounded regular file")
        return self._read_task_output(relative, maximum=maximum)

    def record_codex_execution_failure(self, repository_root: Path, *, task_id: str) -> dict[str, Any]:
        """Map a nonzero Codex process exit with no last message to a typed certificate."""
        with _exclusive_guard(self.root):
            task = self._load_task_record(task_id)
            session = self._load_task_record(task_id, "session")
            if validate_codex_resume(session, task):
                raise AdapterConflict("E_ARTIFACT_STALE: stored session no longer matches task bindings")
            termination = session.get("termination")
            exit_code = session.get("exit_code")
            if termination not in {"failed", "timeout", "cancelled"} or not isinstance(exit_code, int) or exit_code == 0:
                raise AdapterConflict("E_SCHEMA_INVALID: execution failure requires a recorded nonzero termination")
            raw_result = self._read_optional_task_output(session["result_path"], maximum=16 * 1024 * 1024)
            if raw_result and raw_result.strip():
                raise AdapterConflict("E_ARTIFACT_STALE: structured output exists; validate it with record_codex_result")

            events_bytes = self._read_task_output(session["events_path"], maximum=_MAX_GIT_OUTPUT)
            progress_bytes = self._read_task_output(session["progress_path"], maximum=16 * 1024 * 1024)
            if b"\x1b" in progress_bytes:
                raise AdapterConflict("Codex progress log contains untrusted ANSI control bytes")
            try:
                event_lines = [line for line in events_bytes.decode("utf-8", errors="strict").splitlines() if line.strip()]
            except UnicodeDecodeError as exc:
                raise AdapterConflict(f"Codex JSONL event stream is not UTF-8: {exc}") from exc
            if len(event_lines) > 10000:
                raise AdapterConflict("Codex JSONL event stream exceeds the bounded line limit")
            events: list[dict[str, Any]] = []
            try:
                for index, line in enumerate(event_lines, 1):
                    event = _decode_json(line, f"{session['events_path']}:{index}")
                    if not isinstance(event, dict):
                        raise ValueError("event must be an object")
                    events.append(event)
            except ValueError as exc:
                raise AdapterConflict(f"Codex JSONL event stream is invalid: {exc}") from exc

            worktree_id = Path(task["working_directory"]).name
            metadata = self._load_worktree_metadata(worktree_id)
            snapshot, _internal = self._candidate_snapshot(
                repository_root,
                candidate_id=worktree_id,
                expected_base_revision=task["source_revision"],
                allowed_write_paths=metadata["allowed_write_paths"],
                protected_paths=metadata["protected_paths"],
            )
            if snapshot["changed_paths"]:
                raise AdapterConflict("E_UNBOUND_AGENT_CHANGES: failed execution changed the candidate worktree")

            messages: list[str] = []
            for event in events:
                if isinstance(event.get("message"), str):
                    messages.append(event["message"])
                error = event.get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    messages.append(error["message"])
            diagnostic_text = "\n".join(messages).lower()[:8192]
            if termination == "timeout":
                status, code, retryable = "blocked", "E_AGENT_TIMEOUT", False
                summary = "Codex execution timed out before a structured result was produced."
            elif termination == "cancelled":
                status, code, retryable = "blocked", "E_AGENT_CANCELLED", False
                summary = "Codex execution was cancelled before a structured result was produced."
            elif any(marker in diagnostic_text for marker in ("usage limit", "purchase more credits", "rate limit", "quota")):
                status, code, retryable = "blocked", "E_AGENT_CAPACITY", True
                summary = "Codex execution was capacity-blocked before a structured result was produced."
            elif any(marker in diagnostic_text for marker in ("unauthorized", "authentication", "not logged in", "api key")):
                status, code, retryable = "blocked", "E_AGENT_AUTH", False
                summary = "Codex execution was authentication-blocked before a structured result was produced."
            else:
                status, code, retryable = "failed", "E_AGENT_EXECUTION_FAILED", False
                summary = "Codex execution failed before a structured result was produced."

            diagnostic_artifacts = [
                self.store_artifact(events_bytes, sensitive=False),
                self.store_artifact(progress_bytes, sensitive=False),
            ]
            result = {
                "task_id": task_id,
                "status": status,
                "candidate_ref": None,
                "changed_paths": [],
                "proposed_events": ["task_blocked" if status == "blocked" else "task_failed"],
                "verification_requests": [],
                "blocker": {"code": code, "summary": summary, "evidence_refs": [], "retryable": retryable},
                "claims": [],
            }
            result_errors = validate_codex_task_result(result, load_json(_CODEX_RESULT_SCHEMA), task=task)
            if result_errors:
                raise AdapterConflict("invalid controller-generated Codex failure certificate: " + "; ".join(result_errors[:12]))
            result_bytes = _json_bytes(result)
            result_artifact = self.store_artifact(result_bytes, sensitive=False)
            tasks = _ensure_direct_child_directory(self.root, "tasks")
            _write_once(tasks, f"{task_id}.result.json", result_bytes)
            return {
                "status": "result_recorded",
                "task_id": task_id,
                "result": result,
                "result_artifact": result_artifact,
                "diagnostic_artifacts": diagnostic_artifacts,
                "event_proposal": {
                    "type": result["proposed_events"][0],
                    "summary": summary,
                    "artifact_pointers": [result_artifact],
                },
            }

    def _write_closure_artifact(self, artifact_ref: str, artifact: dict[str, Any]) -> Path:
        if not _ARTIFACT_REF.fullmatch(artifact_ref):
            raise AdapterConflict("closure artifact proposal has an invalid semantic ref")
        kind, name = artifact_ref.removeprefix("artifact:").split("/", 1)
        kind_directory = _ensure_direct_child_directory(self.root, kind)
        payload = _json_bytes(artifact)
        _write_once(kind_directory, f"{name}.json", payload)
        return kind_directory / f"{name}.json"

    def record_codex_result(
        self,
        repository_root: Path,
        result: dict[str, Any],
        *,
        candidate_manifest: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with _exclusive_guard(self.root):
            task_id = result.get("task_id") if isinstance(result, dict) else None
            if not isinstance(task_id, str):
                raise AdapterConflict("Codex result has no task identity")
            task = self._load_task_record(task_id)
            session = self._load_task_record(task_id, "session")
            session_errors = validate_codex_resume(session, task)
            if session_errors:
                raise AdapterConflict("E_ARTIFACT_STALE: stored session no longer matches task bindings")
            raw_result = self._read_task_output(session["result_path"], maximum=16 * 1024 * 1024)
            try:
                observed_result = _decode_json(raw_result.decode("utf-8"), session["result_path"])
            except (UnicodeDecodeError, ValueError) as exc:
                raise AdapterConflict(f"Codex structured output is invalid JSON: {exc}") from exc
            if observed_result != result:
                raise AdapterConflict("E_ARTIFACT_STALE: supplied result differs from the recorded Codex output")
            events_bytes = self._read_task_output(session["events_path"], maximum=_MAX_GIT_OUTPUT)
            try:
                event_lines = [line for line in events_bytes.decode("utf-8", errors="strict").splitlines() if line.strip()]
            except UnicodeDecodeError as exc:
                raise AdapterConflict(f"Codex JSONL event stream is not UTF-8: {exc}") from exc
            if len(event_lines) > 10000:
                raise AdapterConflict("Codex JSONL event stream exceeds the bounded line limit")
            try:
                for index, line in enumerate(event_lines, 1):
                    _decode_json(line, f"{session['events_path']}:{index}")
            except ValueError as exc:
                raise AdapterConflict(f"Codex JSONL event stream is invalid: {exc}") from exc
            progress_bytes = self._read_task_output(session["progress_path"], maximum=16 * 1024 * 1024)
            if b"\x1b" in progress_bytes:
                raise AdapterConflict("Codex progress log contains untrusted ANSI control bytes")
            diagnostic_artifacts = [
                self.store_artifact(events_bytes, sensitive=False),
                self.store_artifact(raw_result, sensitive=False),
                self.store_artifact(progress_bytes, sensitive=False),
            ]
            result_schema = load_json(_CODEX_RESULT_SCHEMA)
            result_errors = validate_codex_task_result(result, result_schema, task=task)
            if result_errors:
                raise AdapterConflict("invalid Codex task result: " + "; ".join(result_errors[:12]))
            if result.get("status") != "completed":
                if candidate_manifest is not None or result.get("changed_paths"):
                    raise AdapterConflict("blocked/failed result cannot publish a candidate manifest or unbound changed paths")
                result_bytes = _json_bytes(result)
                result_artifact = self.store_artifact(result_bytes, sensitive=False)
                tasks = _ensure_direct_child_directory(self.root, "tasks")
                _write_once(tasks, f"{task_id}.result.json", result_bytes)
                event_type = "task_blocked" if result.get("status") == "blocked" else "task_failed"
                return {
                    "status": "result_recorded",
                    "task_id": task_id,
                    "result_artifact": result_artifact,
                    "diagnostic_artifacts": diagnostic_artifacts,
                    "event_proposal": {"type": event_type, "summary": result["blocker"]["summary"], "artifact_pointers": [result_artifact]},
                }

            if not isinstance(candidate_manifest, dict):
                raise AdapterConflict("completed candidate result requires a controller-produced candidate manifest")
            worktree_id = Path(task["working_directory"]).name
            metadata = self._load_worktree_metadata(worktree_id)
            snapshot, _internal = self._candidate_snapshot(
                repository_root,
                candidate_id=worktree_id,
                expected_base_revision=task["source_revision"],
                allowed_write_paths=task["allowed_write_paths"],
                protected_paths=task["protected_paths"],
            )
            if not snapshot["eligible_for_archive"]:
                raise AdapterConflict("E_SCOPE_VIOLATION: completed result worktree snapshot is unsafe or ineligible")
            if sorted(result["changed_paths"]) != snapshot["changed_paths"]:
                raise AdapterConflict("E_ARTIFACT_STALE: result changed paths differ from current worktree snapshot")
            state = self.load_state()
            run = state["closure_run"]
            artifact_schema = load_json(_CLOSURE_ARTIFACT_SCHEMA)
            violations = validate_closure_artifact(
                candidate_manifest,
                artifact_schema,
                expected_workflow_id=state["workflow_id"],
                expected_closure_epoch=run["contract_ref"]["epoch"],
                expected_source_revision=state["source"]["observed_revision"],
                expected_scope_hash=state["source"]["scope_hash"],
                expected_contract_hash=run["contract_ref"]["content_hash"],
                expected_verifier_bundle_hash=run["verifier_bundle_ref"]["content_hash"],
            )
            if violations:
                raise AdapterConflict("invalid candidate manifest: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:12]))
            candidate_ref = result["candidate_ref"]
            candidate_id = candidate_ref.rsplit("/", 1)[-1]
            payload = candidate_manifest.get("payload") if isinstance(candidate_manifest.get("payload"), dict) else {}
            expected = {
                "candidate_id": candidate_id,
                "objective": task["objective"],
                "target_counterexample_refs": task["counterexample_refs"],
                "allowed_writes": task["allowed_write_paths"],
                "protected_paths": metadata["protected_paths"],
                "worktree_ref": f"artifact:worktree/{worktree_id}",
                "base_candidate_hash": "sha256:" + sha256(task["source_revision"].encode("utf-8")).hexdigest(),
                "patch_hash": snapshot["patch_hash"],
                "status": "created",
            }
            for field, value in expected.items():
                if payload.get(field) != value:
                    raise AdapterConflict(f"E_ARTIFACT_STALE: candidate manifest {field} differs from task/worktree binding")
            if candidate_manifest.get("artifact_id") != "CM-" + candidate_id.removeprefix("C-"):
                raise AdapterConflict("E_ARTIFACT_STALE: candidate manifest artifact ID differs from candidate identity")
            if candidate_manifest.get("producer") != {"actor": "controller", "run_id": task["run_id"]}:
                raise AdapterConflict("E_UNAUTHORIZED_TRANSITION: candidate manifest must be produced by the controller for this run")
            if candidate_manifest.get("content_hash") != canonical_artifact_hash(candidate_manifest):
                raise AdapterConflict("E_HASH_MISMATCH: candidate manifest content hash differs")

            worktree_ref = payload["worktree_ref"]
            worktree_artifact = {
                "schema_id": "sqw://artifact-envelope/1.0",
                "artifact_id": worktree_id,
                "workflow_id": state["workflow_id"],
                "source_revision": state["source"]["observed_revision"],
                "scope_hash": state["source"]["scope_hash"],
                "created_at": candidate_manifest["created_at"],
                "producer": {"actor": "controller", "run_id": task["run_id"]},
                "classification": "internal",
                "mime_type": "application/json",
                "command_ref": "git worktree add --detach <managed-worktree> <frozen-base>",
                "redaction_policy": "none_required",
                "content_hash": "sha256:" + "0" * 64,
                "payload": {
                    "kind": metadata["kind"],
                    "identifier": metadata["identifier"],
                    "base_revision": metadata["base_revision"],
                    "writer_id": metadata["writer_id"],
                    "worktree_path": metadata["worktree_path"],
                    "allowed_write_paths": metadata["allowed_write_paths"],
                    "protected_paths": metadata["protected_paths"],
                    "view_hashes": metadata["view_hashes"],
                    "snapshot": snapshot,
                },
            }
            worktree_artifact["content_hash"] = canonical_artifact_hash(worktree_artifact)
            worktree_bytes = _json_bytes(worktree_artifact)
            worktree_pointer = self.store_artifact(worktree_bytes, sensitive=False)
            worktree_path = self._write_closure_artifact(worktree_ref, worktree_artifact)
            manifest_bytes = _json_bytes(candidate_manifest)
            manifest_artifact = self.store_artifact(manifest_bytes, sensitive=False)
            manifest_path = self._write_closure_artifact(candidate_ref, candidate_manifest)
            result_bytes = _json_bytes(result)
            result_artifact = self.store_artifact(result_bytes, sensitive=False)
            tasks = _ensure_direct_child_directory(self.root, "tasks")
            _write_once(tasks, f"{task_id}.result.json", result_bytes)
            return {
                "status": "result_recorded",
                "task_id": task_id,
                "result_artifact": result_artifact,
                "diagnostic_artifacts": diagnostic_artifacts,
                "candidate_manifest_artifact": manifest_artifact,
                "worktree_artifact": worktree_pointer,
                "candidate_ref": candidate_ref,
                "candidate_path": str(manifest_path),
                "worktree_ref": worktree_ref,
                "worktree_artifact_path": str(worktree_path),
                "snapshot": snapshot,
                "event_proposal": {
                    "type": "candidate_created",
                    "summary": f"candidate {candidate_id} result, snapshot, and manifest validated",
                    "artifact_refs": [candidate_ref],
                    "artifact_pointers": [result_artifact, manifest_artifact, worktree_pointer],
                },
            }

    def orphan_artifacts(self) -> list[str]:
        state = self.load_state()
        referenced: set[str] = set()
        for artifact in state.get("artifacts", []):
            raw = Path(artifact.get("artifact_ref", ""))
            if raw.parts and raw.parts[0] == ".workflow":
                raw = Path(*raw.parts[1:])
            referenced.add(raw.as_posix())
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.root / "artifacts", flags)
        except OSError as exc:
            raise AdapterConflict(f"artifact directory is unavailable or unsafe: {exc}") from exc
        try:
            entries = list(os.scandir(descriptor))
            if len(entries) > 10000:
                raise AdapterConflict("artifact directory exceeds the bounded orphan scan limit")
            observed: list[str] = []
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise AdapterConflict(f"artifact store contains an unsafe non-regular entry: {entry.name}")
                relative = f"artifacts/{entry.name}"
                if relative not in referenced:
                    observed.append(relative)
            return sorted(observed)
        finally:
            os.close(descriptor)

    def resume(self, *, current_revision: str | None = None, current_scope_hash: str | None = None, current_plan_hash: str | None = None, now_value: str | None = None) -> dict[str, Any]:
        state = self.load_effective_state()
        events = load_json_lines(self.events_path)
        return reconcile(state, current_revision=current_revision, current_scope_hash=current_scope_hash, current_plan_hash=current_plan_hash, workflow_root=self.root, verify_artifacts=True, events=events, event_schema=self.event_schema, now_value=now_value)


def append_trace(trace_path: Path, event: dict[str, Any], event_schema: dict[str, Any], *, expected_last_sequence: int) -> None:
    root = trace_path.resolve().parent
    with _exclusive_guard(root):
        events = load_json_lines(trace_path) if trace_path.exists() else []
        actual = events[-1]["sequence"] if events else 0
        if actual != expected_last_sequence:
            raise AdapterConflict(f"stale trace sequence: expected {expected_last_sequence}, current {actual}")
        candidate = events + [deepcopy(event)]
        violations = validate_event_stream(candidate, event_schema)
        if violations:
            raise ValueError("invalid trace event: " + "; ".join(f"{item.code}@{item.path}" for item in violations[:8]))
        payload = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for item in candidate)
        _atomic_write(trace_path, payload)


def _task_owned_trace_path(root: Path, raw_path: Path) -> Path:
    resolved_root = root.resolve()
    candidate = raw_path if raw_path.is_absolute() else resolved_root / raw_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("M1 trace path must resolve inside the explicit task root") from exc
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--state-schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "workflow-state.schema.json")
    parser.add_argument("--event-schema", type=Path, default=Path(__file__).resolve().parents[1] / "schemas" / "workflow-event.schema.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("state", type=Path)
    commit = subparsers.add_parser("commit")
    commit.add_argument("state", type=Path)
    commit.add_argument("--expected-version", required=True, type=int)
    append = subparsers.add_parser("append-event")
    append.add_argument("event", type=Path)
    append.add_argument("--expected-sequence", required=True, type=int)
    trace = subparsers.add_parser("append-trace")
    trace.add_argument("event", type=Path)
    trace.add_argument("--trace-path", required=True, type=Path)
    trace.add_argument("--expected-sequence", required=True, type=int)
    subparsers.add_parser("resume")
    subparsers.add_parser("probe-codex")
    create_candidate = subparsers.add_parser("create-candidate-worktree")
    create_candidate.add_argument("--repository", required=True, type=Path)
    create_candidate.add_argument("--candidate-id", required=True)
    create_candidate.add_argument("--base-revision", required=True)
    create_candidate.add_argument("--writer-id", required=True)
    create_candidate.add_argument("--allow-write", action="append", default=[])
    create_candidate.add_argument("--protect", action="append", default=[])
    inspect_candidate = subparsers.add_parser("inspect-candidate-snapshot")
    inspect_candidate.add_argument("--repository", required=True, type=Path)
    inspect_candidate.add_argument("--candidate-id", required=True)
    inspect_candidate.add_argument("--base-revision", required=True)
    inspect_candidate.add_argument("--allow-write", action="append", default=[])
    inspect_candidate.add_argument("--protect", action="append", default=[])
    archive_candidate = subparsers.add_parser("archive-candidate")
    archive_candidate.add_argument("--repository", required=True, type=Path)
    archive_candidate.add_argument("--candidate-id", required=True)
    archive_candidate.add_argument("--base-revision", required=True)
    archive_candidate.add_argument("--snapshot-hash", required=True)
    archive_candidate.add_argument("--allow-write", action="append", default=[])
    archive_candidate.add_argument("--protect", action="append", default=[])
    remove_candidate = subparsers.add_parser("remove-candidate-worktree")
    remove_candidate.add_argument("--repository", required=True, type=Path)
    remove_candidate.add_argument("--candidate-id", required=True)
    remove_candidate.add_argument("--snapshot-hash", required=True)
    remove_candidate.add_argument("--archive-artifact", required=True, type=Path)
    create_integration = subparsers.add_parser("create-integration-worktree")
    create_integration.add_argument("--repository", required=True, type=Path)
    create_integration.add_argument("--integration-id", required=True)
    create_integration.add_argument("--base-revision", required=True)
    create_integration.add_argument("--allow-write", action="append", default=[])
    create_integration.add_argument("--protect", action="append", default=[])
    apply_integration = subparsers.add_parser("apply-candidate-to-integration")
    apply_integration.add_argument("--repository", required=True, type=Path)
    apply_integration.add_argument("--candidate-id", required=True)
    apply_integration.add_argument("--integration-id", required=True)
    apply_integration.add_argument("--snapshot-hash", required=True)
    apply_integration.add_argument("--archive-artifact", required=True, type=Path)
    prepare_task = subparsers.add_parser("prepare-codex-task")
    prepare_task.add_argument("task", type=Path)
    record_session = subparsers.add_parser("record-codex-session")
    record_session.add_argument("task_id")
    record_session.add_argument("session", type=Path)
    record_result = subparsers.add_parser("record-codex-result")
    record_result.add_argument("--repository", required=True, type=Path)
    record_result.add_argument("result", type=Path)
    record_result.add_argument("--candidate-manifest", type=Path)
    record_failure = subparsers.add_parser("record-codex-execution-failure")
    record_failure.add_argument("--repository", required=True, type=Path)
    record_failure.add_argument("task_id")
    record_signoff = subparsers.add_parser("record-integration-signoff")
    record_signoff.add_argument("--repository", required=True, type=Path)
    record_signoff.add_argument("--signoff", required=True, type=Path)
    record_signoff.add_argument("--candidate-manifest", required=True, type=Path)
    record_signoff.add_argument("--integration", required=True, type=Path)
    record_signoff.add_argument("--reviews", required=True, type=Path)
    record_signoff.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        event_schema = load_json(args.event_schema)
        if args.command == "append-trace":
            trace_path = _task_owned_trace_path(args.root, args.trace_path)
            append_trace(trace_path, load_json(args.event), event_schema, expected_last_sequence=args.expected_sequence)
            result = {
                "status": "trace_appended",
                "trace_path": trace_path.relative_to(args.root.resolve()).as_posix(),
            }
        else:
            adapter = LocalWorkflowAdapter(args.root, load_json(args.state_schema), event_schema)
        if args.command == "init":
            adapter.initialize(load_json(args.state))
            result = {"status": "initialized"}
        elif args.command == "commit":
            adapter.commit_state(load_json(args.state), expected_state_version=args.expected_version)
            result = {"status": "committed"}
        elif args.command == "append-event":
            adapter.append_event(load_json(args.event), expected_last_sequence=args.expected_sequence)
            result = {"status": "appended"}
        elif args.command == "resume":
            result = adapter.resume()
        elif args.command == "probe-codex":
            result = probe_codex_capabilities()
        elif args.command == "create-candidate-worktree":
            result = adapter.create_candidate_worktree(
                args.repository,
                candidate_id=args.candidate_id,
                base_revision=args.base_revision,
                writer_id=args.writer_id,
                allowed_write_paths=args.allow_write,
                protected_paths=args.protect,
            )
        elif args.command == "inspect-candidate-snapshot":
            result = adapter.inspect_candidate_snapshot(
                args.repository,
                candidate_id=args.candidate_id,
                expected_base_revision=args.base_revision,
                allowed_write_paths=args.allow_write,
                protected_paths=args.protect,
            )
        elif args.command == "archive-candidate":
            result = adapter.archive_candidate(
                args.repository,
                candidate_id=args.candidate_id,
                expected_base_revision=args.base_revision,
                expected_snapshot_hash=args.snapshot_hash,
                allowed_write_paths=args.allow_write,
                protected_paths=args.protect,
            )
        elif args.command == "remove-candidate-worktree":
            result = adapter.remove_candidate_worktree(
                args.repository,
                candidate_id=args.candidate_id,
                expected_snapshot_hash=args.snapshot_hash,
                archive_artifact=load_json(args.archive_artifact),
            )
        elif args.command == "create-integration-worktree":
            result = adapter.create_integration_worktree(
                args.repository,
                integration_id=args.integration_id,
                base_revision=args.base_revision,
                allowed_write_paths=args.allow_write or None,
                protected_paths=args.protect or None,
            )
        elif args.command == "apply-candidate-to-integration":
            result = adapter.apply_candidate_to_integration(
                args.repository,
                candidate_id=args.candidate_id,
                integration_id=args.integration_id,
                expected_candidate_snapshot_hash=args.snapshot_hash,
                archive_artifact=load_json(args.archive_artifact),
            )
        elif args.command == "prepare-codex-task":
            result = adapter.prepare_codex_task(load_json(args.task))
        elif args.command == "record-codex-session":
            result = adapter.record_codex_session(args.task_id, load_json(args.session))
        elif args.command == "record-codex-result":
            result = adapter.record_codex_result(
                args.repository,
                load_json(args.result),
                candidate_manifest=load_json(args.candidate_manifest) if args.candidate_manifest else None,
            )
        elif args.command == "record-codex-execution-failure":
            result = adapter.record_codex_execution_failure(args.repository, task_id=args.task_id)
        elif args.command == "record-integration-signoff":
            result = adapter.record_integration_signoff(
                args.repository,
                load_json(args.signoff),
                candidate_manifest=load_json(args.candidate_manifest),
                integration=load_json(args.integration),
                review_results=load_json(args.reviews),
                evidence_artifacts=load_json(args.evidence),
            )
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0
    except (AdapterConflict, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
