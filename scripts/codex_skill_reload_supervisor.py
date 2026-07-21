#!/usr/bin/env python3
"""Restart Codex around local skill installs without forking the active thread.

The supervisor owns one TUI and one local Unix-socket app-server.  An agent calls
``checkpoint`` after installing a plugin; the configured Codex ``notify`` hook
marks the checkpoint ready only after that turn completes.  The supervisor then
restarts app-server, resumes the exact thread with full access, verifies the
installed skill bytes, conditionally restores a previously active goal, and
starts the continuation turn.
"""

from __future__ import annotations

import argparse
import base64
from collections import deque
from contextlib import contextmanager
from hashlib import sha1, sha256
import fcntl
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, Sequence
import uuid


SUPPORTED_CODEX_VERSION = "0.144.6"
STATE_SCHEMA = "codex-skill-reload-supervisor/1"
STATE_ENV = "CODEX_SKILL_RELOAD_STATE"
MAX_STATE_BYTES = 64 * 1024
MAX_SKILL_FILES = 2048
MAX_SKILL_BYTES = 32 * 1024 * 1024
MAX_CONTINUE_MESSAGE = 2000
DEFAULT_CONTINUE_MESSAGE = (
    "继续当前任务。插件已经重载，本轮指定技能的加载路径和内容哈希已经验证。"
)
REQUIRED_METHODS = {
    "thread/resume",
    "thread/goal/get",
    "thread/goal/set",
    "skills/list",
    "turn/start",
}
GOAL_STATUSES = {
    "active",
    "paused",
    "blocked",
    "usageLimited",
    "budgetLimited",
    "complete",
}


class SupervisorError(RuntimeError):
    """A fail-closed supervisor contract violation."""


def _json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _short_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:512]


def _canonical_thread_id(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise SupervisorError("--thread-id must be an exact UUID; names and --last are forbidden") from exc
    canonical = str(parsed)
    if value.lower() != canonical:
        raise SupervisorError("--thread-id must use the canonical UUID form")
    return canonical


def _private_parent(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise SupervisorError(f"state parent is not a real directory: {path.parent}")
    if path.parent.parent == Path("/tmp"):
        os.chmod(path.parent, 0o700)
    info = path.parent.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise SupervisorError("state parent must be owned by the current user and not group/world writable")


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    _private_parent(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path.parent, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_state_unlocked(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise SupervisorError(f"supervisor state does not exist: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES:
            raise SupervisorError("supervisor state is not a bounded regular file")
        payload = os.read(descriptor, MAX_STATE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(payload) > MAX_STATE_BYTES:
        raise SupervisorError("supervisor state exceeds its byte ceiling")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError("supervisor state is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("schema_version") != STATE_SCHEMA:
        raise SupervisorError("supervisor state schema is invalid")
    return value


def read_state(path: Path) -> dict[str, Any]:
    with _state_lock(path):
        return _read_state_unlocked(path)


def _write_state_unlocked(path: Path, value: dict[str, Any]) -> None:
    value = dict(value)
    value["schema_version"] = STATE_SCHEMA
    value["updated_at"] = int(time.time())
    payload = (_json_line(value) + "\n").encode("utf-8")
    if len(payload) > MAX_STATE_BYTES:
        raise SupervisorError("supervisor state exceeds its byte ceiling")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_state(path: Path, value: dict[str, Any]) -> None:
    with _state_lock(path):
        _write_state_unlocked(path, value)


def mutate_state(path: Path, mutator: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    with _state_lock(path):
        value = mutator(_read_state_unlocked(path))
        _write_state_unlocked(path, value)
        return value


def default_state_path(thread_id: str) -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime else Path(tempfile.gettempdir()) / f"codex-skill-reload-{os.getuid()}"
    token = sha256(thread_id.encode("ascii")).hexdigest()[:20]
    return (base / "codex-skill-reload" / f"{token}.json").absolute()


def resolve_state_path(value: str | None, *, thread_id: str | None = None) -> Path:
    raw = value or os.environ.get(STATE_ENV)
    if raw:
        return Path(raw).expanduser().absolute()
    if thread_id is not None:
        return default_state_path(thread_id)
    raise SupervisorError(f"state path is required; pass --state or preserve ${STATE_ENV}")


def _pid_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _assert_no_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise SupervisorError(f"symlinked skill/plugin path is forbidden: {cursor}")


def skill_tree_hash(skill_md: Path) -> str:
    skill_md = skill_md.absolute()
    if skill_md.name != "SKILL.md" or not skill_md.is_file():
        raise SupervisorError(f"expected a regular SKILL.md: {skill_md}")
    root = skill_md.parent
    _assert_no_symlink_components(root)
    records: list[dict[str, object]] = []
    total = 0
    for current, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        current_path = Path(current)
        for name in sorted(directories):
            if (current_path / name).is_symlink():
                raise SupervisorError(f"symlink inside skill tree is forbidden: {current_path / name}")
        for name in sorted(files):
            path = current_path / name
            if path.is_symlink():
                raise SupervisorError(f"symlink inside skill tree is forbidden: {path}")
            if not path.is_file():
                raise SupervisorError(f"non-regular file inside skill tree: {path}")
            relative = path.relative_to(root).as_posix()
            payload = path.read_bytes()
            total += len(payload)
            records.append({
                "path": relative,
                "mode": stat.S_IMODE(path.stat().st_mode),
                "size": len(payload),
                "sha256": sha256(payload).hexdigest(),
            })
            if len(records) > MAX_SKILL_FILES or total > MAX_SKILL_BYTES:
                raise SupervisorError(f"skill tree exceeds its file/byte ceiling: {root}")
    if not records or not any(record["path"] == "SKILL.md" for record in records):
        raise SupervisorError(f"skill tree is empty or missing SKILL.md: {root}")
    return "sha256:" + sha256(_json_line(records).encode("utf-8")).hexdigest()


def _strict_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise SupervisorError(f"invalid bounded JSON file: {path}")
    def hook(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise SupervisorError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=hook)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SupervisorError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise SupervisorError(f"expected JSON object: {path}")
    return value


def _plugin_skill_root(plugin_root: Path) -> tuple[dict[str, Any], Path]:
    plugin_root = plugin_root.absolute()
    _assert_no_symlink_components(plugin_root)
    manifest = _strict_object(plugin_root / ".codex-plugin" / "plugin.json")
    raw = manifest.get("skills")
    if not isinstance(raw, str):
        raise SupervisorError(f"plugin does not declare one skills directory: {plugin_root}")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise SupervisorError("plugin skills path must stay inside the plugin root")
    skills_root = (plugin_root / relative).resolve(strict=True)
    if not skills_root.is_relative_to(plugin_root.resolve(strict=True)) or not skills_root.is_dir():
        raise SupervisorError("plugin skills directory escapes or is missing")
    return manifest, skills_root


def _discover_skill_map(plugin_root: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    manifest, skills_root = _plugin_skill_root(plugin_root)
    discovered: dict[str, Path] = {}
    for child in sorted(skills_root.iterdir(), key=lambda item: item.name):
        if child.is_symlink():
            raise SupervisorError(f"symlinked plugin skill is forbidden: {child}")
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.is_file():
            discovered[child.name] = skill_md.absolute()
    if not discovered:
        raise SupervisorError(f"plugin contains no skills: {plugin_root}")
    return manifest, discovered


def _run_json(command: Sequence[str], *, timeout: float = 30) -> dict[str, Any]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout)
    if completed.returncode != 0:
        detail = _short_error(RuntimeError(completed.stderr or completed.stdout or "command failed"))
        raise SupervisorError(f"command failed ({command[0]}): {detail}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SupervisorError(f"command did not return JSON: {command[0]}") from exc
    if not isinstance(value, dict):
        raise SupervisorError(f"command returned a non-object JSON value: {command[0]}")
    return value


def discover_plugin_skills(codex: str, codex_home: Path, selector: str) -> list[dict[str, str]]:
    if selector.count("@") != 1:
        raise SupervisorError("--plugin must be the exact PLUGIN@MARKETPLACE selector")
    plugin_name, marketplace = selector.split("@", 1)
    component = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
    if component.fullmatch(plugin_name) is None or component.fullmatch(marketplace) is None:
        raise SupervisorError("plugin and marketplace names must be bounded path-safe identifiers")
    listing = _run_json([codex, "plugin", "list", "--json"])
    matches = [
        item for item in listing.get("installed", [])
        if isinstance(item, dict) and item.get("pluginId") == selector
    ]
    if len(matches) != 1:
        raise SupervisorError(f"installed plugin selector is not unique: {selector}")
    item = matches[0]
    if item.get("installed") is not True or item.get("enabled") is not True:
        raise SupervisorError(f"plugin is not installed and enabled: {selector}")
    version = item.get("version")
    source = item.get("source")
    if not isinstance(version, str) or not version or not isinstance(source, dict):
        raise SupervisorError("plugin listing lacks a version or source")
    if source.get("source") != "local" or not isinstance(source.get("path"), str):
        raise SupervisorError("the reload supervisor accepts local marketplace plugins only")
    source_root = Path(source["path"]).expanduser().absolute()
    cache_root = (codex_home / "plugins" / "cache" / marketplace / plugin_name / version).absolute()
    source_manifest, source_skills = _discover_skill_map(source_root)
    cache_manifest, cache_skills = _discover_skill_map(cache_root)
    for manifest, label in ((source_manifest, "source"), (cache_manifest, "cache")):
        if manifest.get("name") != plugin_name or manifest.get("version") != version:
            raise SupervisorError(f"{label} plugin identity does not match plugin list")
    if set(source_skills) != set(cache_skills):
        raise SupervisorError("installed plugin skill set differs from its local source")
    expected: list[dict[str, str]] = []
    for skill_id in sorted(source_skills):
        source_hash = skill_tree_hash(source_skills[skill_id])
        cache_hash = skill_tree_hash(cache_skills[skill_id])
        if source_hash != cache_hash:
            raise SupervisorError(f"installed skill bytes differ from local source: {skill_id}")
        expected.append({
            "name": f"{plugin_name}:{skill_id}",
            "path": str(cache_skills[skill_id]),
            "tree_hash": cache_hash,
        })
    return expected


def parse_explicit_skill(value: str) -> dict[str, str]:
    if "=" not in value:
        raise SupervisorError("--skill must use NAME=/absolute/path/to/SKILL.md")
    name, raw_path = value.split("=", 1)
    if not name or not raw_path:
        raise SupervisorError("--skill requires both an exact name and path")
    path = Path(raw_path).expanduser().absolute()
    return {"name": name, "path": str(path), "tree_hash": skill_tree_hash(path)}


def _all_strings(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.add(value)
    elif isinstance(value, list):
        for item in value:
            found.update(_all_strings(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.add(str(key))
            found.update(_all_strings(item))
    return found


def verify_codex_runtime(codex: str) -> dict[str, str]:
    try:
        completed = subprocess.run(
            [codex, "--version"], text=True, capture_output=True, check=False, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SupervisorError(f"unable to run Codex CLI: {codex}") from exc
    match = re.fullmatch(r"codex-cli\s+(\S+)\s*", completed.stdout)
    if completed.returncode != 0 or match is None or match.group(1) != SUPPORTED_CODEX_VERSION:
        observed = match.group(1) if match else "unknown"
        raise SupervisorError(
            f"Codex CLI schema pin mismatch: required={SUPPORTED_CODEX_VERSION} observed={observed}"
        )
    with tempfile.TemporaryDirectory(prefix="codex-reload-schema-") as directory:
        schema_root = Path(directory)
        generated = subprocess.run(
            [codex, "app-server", "generate-json-schema", "--experimental", "--out", str(schema_root)],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if generated.returncode != 0:
            raise SupervisorError(f"unable to generate pinned app-server schema: {_short_error(RuntimeError(generated.stderr))}")
        names = [
            "ClientRequest.json",
            "v2/ThreadResumeParams.json",
            "v2/ThreadResumeResponse.json",
            "v2/ThreadGoalGetParams.json",
            "v2/ThreadGoalGetResponse.json",
            "v2/ThreadGoalSetParams.json",
            "v2/SkillsListParams.json",
            "v2/SkillsListResponse.json",
            "v2/TurnStartParams.json",
        ]
        schemas = {name: _strict_object(schema_root / name) for name in names}
        method_strings = _all_strings(schemas["ClientRequest.json"])
        if not REQUIRED_METHODS <= method_strings:
            raise SupervisorError("app-server schema is missing a required method")
        resume_params = schemas["v2/ThreadResumeParams.json"]
        resume_response = schemas["v2/ThreadResumeResponse.json"]
        skills_params = schemas["v2/SkillsListParams.json"]
        skills_response = schemas["v2/SkillsListResponse.json"]
        turn_params = schemas["v2/TurnStartParams.json"]
        required_resume = {"approvalPolicy", "cwd", "sandbox", "threadId"}
        if not required_resume <= set(resume_params.get("properties", {})):
            raise SupervisorError("thread/resume override fields changed")
        if "danger-full-access" not in _all_strings(resume_params):
            raise SupervisorError("thread/resume no longer accepts danger-full-access")
        if not {"approvalPolicy", "cwd", "sandbox", "thread"} <= set(resume_response.get("required", [])):
            raise SupervisorError("thread/resume proof fields changed")
        if "dangerFullAccess" not in _all_strings(resume_response):
            raise SupervisorError("thread/resume response cannot prove full access")
        if not {"cwds", "forceReload"} <= set(skills_params.get("properties", {})):
            raise SupervisorError("skills/list reload fields changed")
        if not {"enabled", "name", "path", "scope", "errors"} <= _all_strings(skills_response):
            raise SupervisorError("skills/list identity fields changed")
        if not {"input", "threadId"} <= set(turn_params.get("required", [])):
            raise SupervisorError("turn/start required fields changed")
        if not {"skill", "name", "path", "sandboxPolicy", "approvalPolicy"} <= _all_strings(turn_params):
            raise SupervisorError("turn/start skill or permission fields changed")
        if not GOAL_STATUSES <= _all_strings(schemas["v2/ThreadGoalGetResponse.json"]):
            raise SupervisorError("goal status enum changed")
        goal_set = schemas["v2/ThreadGoalSetParams.json"]
        if "status" not in goal_set.get("properties", {}) or "active" not in _all_strings(goal_set):
            raise SupervisorError("thread/goal/set active-status contract changed")
    return {"codex": str(Path(codex).resolve()), "version": SUPPORTED_CODEX_VERSION}


class JsonRpcClient:
    """JSON-RPC over a local app-server Unix WebSocket."""

    def __init__(self, socket_path: Path, *, timeout: float = 15) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        try:
            self._socket.connect(str(socket_path))
            self._websocket_handshake()
        except BaseException:
            self._socket.close()
            raise
        self._socket.settimeout(None)
        self._responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._response_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, name="codex-reload-rpc", daemon=True)
        self._reader.start()
        with self._response_lock:
            identifier = self._next_id
            self._next_id += 1
            target: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._responses[identifier] = target
        self._send({
            "method": "initialize",
            "id": identifier,
            "params": {
                "clientInfo": {
                    "name": "frontier_skill_reload_supervisor",
                    "title": "Frontier Skill Reload Supervisor",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        })
        self.notify("initialized", {})
        try:
            response = target.get(timeout=timeout)
        except queue.Empty as exc:
            self.close()
            raise SupervisorError("app-server initialize timed out") from exc
        finally:
            with self._response_lock:
                self._responses.pop(identifier, None)
        initialized = self._decode_response("initialize", response)
        if not isinstance(initialized.get("codexHome"), str):
            self.close()
            raise SupervisorError("app-server initialize response lacks codexHome")
        self.codex_home = Path(initialized["codexHome"]).absolute()

    def _websocket_handshake(self) -> None:
        nonce = os.urandom(16)
        key = base64.b64encode(nonce).decode("ascii")
        request = (
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self._socket.sendall(request)
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = self._socket.recv(4096)
            if not chunk:
                raise SupervisorError("app-server closed during WebSocket handshake")
            response.extend(chunk)
            if len(response) > 16 * 1024:
                raise SupervisorError("app-server WebSocket handshake exceeded its byte ceiling")
        header, remainder = bytes(response).split(b"\r\n\r\n", 1)
        if remainder:
            raise SupervisorError("unexpected bytes followed the WebSocket handshake")
        lines = header.decode("ascii", errors="strict").split("\r\n")
        if not lines or " 101 " not in f" {lines[0]} ":
            raise SupervisorError(f"app-server rejected WebSocket handshake: {lines[0] if lines else 'empty'}")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" not in line:
                continue
            name, value = line.split(":", 1)
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(
            sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise SupervisorError("app-server WebSocket accept proof is invalid")

    def _recv_exact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = size
        while remaining:
            chunk = self._socket.recv(remaining)
            if not chunk:
                raise EOFError("WebSocket closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._recv_exact(2)
        if first & 0x70:
            raise SupervisorError("app-server used unsupported WebSocket RSV bits")
        final = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if masked:
            raise SupervisorError("app-server sent an invalid masked WebSocket frame")
        if length > 16 * 1024 * 1024:
            raise SupervisorError("app-server WebSocket frame exceeds its byte ceiling")
        return final, opcode, self._recv_exact(length)

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, 0x80 | length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 0x80 | 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 0x80 | 127)) + struct.pack("!Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self._socket.sendall(header + mask + masked)

    def _send(self, payload: dict[str, Any]) -> None:
        encoded = _json_line(payload).encode("utf-8")
        with self._write_lock:
            if self._closed.is_set():
                raise SupervisorError("app-server WebSocket is closed")
            try:
                self._send_frame(0x1, encoded)
            except (BrokenPipeError, OSError) as exc:
                raise SupervisorError("app-server WebSocket write failed") from exc

    def _read_loop(self) -> None:
        fragments = bytearray()
        fragment_opcode: int | None = None
        try:
            while not self._closed.is_set():
                final, opcode, payload = self._read_frame()
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    with self._write_lock:
                        self._send_frame(0xA, payload)
                    continue
                if opcode == 0xA:
                    continue
                if opcode in {0x1, 0x2}:
                    if fragment_opcode is not None:
                        raise SupervisorError("overlapping WebSocket fragments")
                    fragment_opcode = opcode
                    fragments.extend(payload)
                elif opcode == 0x0 and fragment_opcode is not None:
                    fragments.extend(payload)
                else:
                    raise SupervisorError(f"unsupported WebSocket opcode: {opcode}")
                if len(fragments) > 16 * 1024 * 1024:
                    raise SupervisorError("app-server WebSocket message exceeds its byte ceiling")
                if not final:
                    continue
                if fragment_opcode != 0x1:
                    raise SupervisorError("app-server sent a non-text WebSocket message")
                try:
                    message = json.loads(bytes(fragments).decode("utf-8", errors="strict"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    fragments.clear()
                    fragment_opcode = None
                    continue
                fragments.clear()
                fragment_opcode = None
                if not isinstance(message, dict):
                    continue
                identifier = message.get("id")
                if isinstance(identifier, int) and ("result" in message or "error" in message):
                    with self._response_lock:
                        target = self._responses.get(identifier)
                    if target is not None:
                        try:
                            target.put_nowait(message)
                        except queue.Full:
                            pass
                elif isinstance(identifier, int) and isinstance(message.get("method"), str):
                    try:
                        self._send({
                            "id": identifier,
                            "error": {
                                "code": -32601,
                                "message": "reload supervisor does not handle interactive server requests",
                            },
                        })
                    except SupervisorError:
                        break
        except (EOFError, OSError, SupervisorError):
            pass
        finally:
            self._closed.set()
            with self._response_lock:
                pending = list(self._responses.values())
            for target in pending:
                try:
                    target.put_nowait({"error": {"code": -32000, "message": "app-server WebSocket closed"}})
                except queue.Full:
                    pass

    def request(self, method: str, params: dict[str, Any], *, timeout: float = 15) -> dict[str, Any]:
        with self._response_lock:
            identifier = self._next_id
            self._next_id += 1
            target: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._responses[identifier] = target
        try:
            self._send({"method": method, "id": identifier, "params": params})
            try:
                response = target.get(timeout=timeout)
            except queue.Empty as exc:
                raise SupervisorError(f"app-server request timed out: {method}") from exc
        finally:
            with self._response_lock:
                self._responses.pop(identifier, None)
        return self._decode_response(method, response)

    @staticmethod
    def _decode_response(method: str, response: dict[str, Any]) -> dict[str, Any]:
        error = response.get("error")
        if error is not None:
            detail = error.get("message") if isinstance(error, dict) else str(error)
            raise SupervisorError(f"app-server request failed: {method}: {detail}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise SupervisorError(f"app-server returned a non-object result: {method}")
        return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def close(self) -> None:
        if not self._closed.is_set():
            try:
                with self._write_lock:
                    self._send_frame(0x8, b"")
            except OSError:
                pass
        self._closed.set()
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._socket.close()
        self._reader.join(timeout=1)


def _drain_stream(stream: Any, sink: deque[str]) -> None:
    for line in stream:
        sink.append(line.rstrip())


def _terminate_process(process: subprocess.Popen[Any] | None, *, process_group: bool = False) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if process_group:
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if process_group:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=5)
    except ProcessLookupError:
        pass


def _socket_uri(path: Path) -> str:
    encoded = os.fsencode(str(path))
    if len(encoded) > 100:
        raise SupervisorError("Unix socket path is too long; choose a shorter --state path")
    return "unix://" + str(path)


def _remove_socket(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode):
        raise SupervisorError(f"refusing to remove a non-socket path: {path}")
    path.unlink()


def _toml_string_array(values: Sequence[str]) -> str:
    return json.dumps(list(values), ensure_ascii=True, separators=(",", ":"))


def start_app_server(
    codex: str,
    socket_path: Path,
    *,
    state_path: Path | None,
    env: dict[str, str],
    timeout: float = 20,
) -> tuple[subprocess.Popen[str], JsonRpcClient, deque[str]]:
    _remove_socket(socket_path)
    command = [codex, "app-server", "--strict-config", "--listen", _socket_uri(socket_path)]
    if state_path is not None:
        callback = [sys.executable, str(Path(__file__).resolve()), "notify", "--state", str(state_path)]
        command.extend(["-c", "notify=" + _toml_string_array(callback)])
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=env,
    )
    logs: deque[str] = deque(maxlen=64)
    assert process.stdout is not None and process.stderr is not None
    threading.Thread(target=_drain_stream, args=(process.stdout, logs), daemon=True).start()
    threading.Thread(target=_drain_stream, args=(process.stderr, logs), daemon=True).start()
    deadline = time.monotonic() + timeout
    delay = 0.05
    last_error = "socket not ready"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        if socket_path.exists():
            try:
                client = JsonRpcClient(socket_path, timeout=min(5, max(1, deadline - time.monotonic())))
                return process, client, logs
            except (OSError, SupervisorError) as exc:
                last_error = _short_error(exc)
        time.sleep(delay)
        delay = min(0.5, delay * 1.5)
    _terminate_process(process, process_group=True)
    detail = " | ".join(logs)[-512:] or last_error
    raise SupervisorError(f"app-server did not become ready: {detail}")


def validate_resume_response(result: dict[str, Any], thread_id: str, cwd: Path) -> None:
    thread = result.get("thread")
    sandbox = result.get("sandbox")
    observed_cwd = result.get("cwd")
    if not isinstance(thread, dict) or thread.get("id") != thread_id:
        raise SupervisorError("thread/resume returned a different thread id")
    if result.get("approvalPolicy") != "never":
        raise SupervisorError("thread/resume did not apply approvalPolicy=never")
    if not isinstance(sandbox, dict) or sandbox.get("type") != "dangerFullAccess":
        raise SupervisorError("thread/resume did not apply dangerFullAccess")
    if not isinstance(observed_cwd, str) or Path(observed_cwd).resolve() != cwd:
        raise SupervisorError("thread/resume returned a different cwd")


def resume_thread(client: JsonRpcClient, thread_id: str, cwd: Path) -> None:
    result = client.request(
        "thread/resume",
        {
            "threadId": thread_id,
            "cwd": str(cwd),
            "sandbox": "danger-full-access",
            "approvalPolicy": "never",
        },
        timeout=30,
    )
    validate_resume_response(result, thread_id, cwd)


def get_goal(client: JsonRpcClient, thread_id: str) -> dict[str, Any] | None:
    result = client.request("thread/goal/get", {"threadId": thread_id})
    goal = result.get("goal")
    if goal is None:
        return None
    if not isinstance(goal, dict) or goal.get("threadId") != thread_id or goal.get("status") not in GOAL_STATUSES:
        raise SupervisorError("thread/goal/get returned an invalid goal")
    return goal


def restore_goal_if_required(
    client: JsonRpcClient,
    thread_id: str,
    pre_reload_status: str | None,
) -> bool:
    """Return whether an automatic continuation turn is allowed."""
    current = get_goal(client, thread_id)
    if pre_reload_status is None:
        if current is not None:
            raise SupervisorError("a goal appeared across the reload boundary")
        return True
    if pre_reload_status != "active":
        return False
    if current is None:
        raise SupervisorError("the active goal disappeared across the reload boundary")
    status = current["status"]
    if status == "active":
        return True
    if status not in {"paused", "blocked"}:
        raise SupervisorError(f"active goal became non-resumable across reload: {status}")
    result = client.request("thread/goal/set", {"threadId": thread_id, "status": "active"})
    goal = result.get("goal")
    if not isinstance(goal, dict) or goal.get("threadId") != thread_id or goal.get("status") != "active":
        raise SupervisorError("thread/goal/set did not restore the active goal")
    return True


def verify_expected_skills(
    client: JsonRpcClient,
    cwd: Path,
    expected: Sequence[dict[str, str]],
) -> list[dict[str, str]]:
    result = client.request("skills/list", {"cwds": [str(cwd)], "forceReload": True}, timeout=30)
    data = result.get("data")
    if not isinstance(data, list):
        raise SupervisorError("skills/list returned no data array")
    entries = [
        entry for entry in data
        if isinstance(entry, dict)
        and isinstance(entry.get("cwd"), str)
        and Path(entry["cwd"]).resolve() == cwd
    ]
    if len(entries) != 1:
        raise SupervisorError("skills/list did not return one exact cwd entry")
    entry = entries[0]
    skills = entry.get("skills")
    errors = entry.get("errors")
    if not isinstance(skills, list) or not isinstance(errors, list):
        raise SupervisorError("skills/list entry lacks skills or errors")
    verified: list[dict[str, str]] = []
    for wanted in expected:
        wanted_path = Path(wanted["path"]).absolute()
        matches = [
            skill for skill in skills
            if isinstance(skill, dict)
            and skill.get("name") == wanted["name"]
            and isinstance(skill.get("path"), str)
            and Path(skill["path"]).absolute() == wanted_path
        ]
        if len(matches) != 1 or matches[0].get("enabled") is not True:
            raise SupervisorError(f"expected skill is not uniquely enabled at its pinned path: {wanted['name']}")
        for error in errors:
            if not isinstance(error, dict) or not isinstance(error.get("path"), str):
                continue
            error_path = Path(error["path"]).absolute()
            if error_path == wanted_path or error_path.is_relative_to(wanted_path.parent):
                raise SupervisorError(f"expected skill has a load error: {wanted['name']}")
        observed_hash = skill_tree_hash(wanted_path)
        if observed_hash != wanted["tree_hash"]:
            raise SupervisorError(f"expected skill hash changed before reload verification: {wanted['name']}")
        verified.append(dict(wanted))
    return verified


def build_tui_command(
    codex: str,
    socket_path: Path,
    cwd: Path,
    thread_id: str,
    *,
    no_alt_screen: bool,
) -> list[str]:
    command = [
        codex,
        "resume",
        "--remote",
        _socket_uri(socket_path),
        "-C",
        str(cwd),
        "--sandbox",
        "danger-full-access",
        "--ask-for-approval",
        "never",
    ]
    if no_alt_screen:
        command.append("--no-alt-screen")
    command.append(thread_id)
    if "fork" in command or "--last" in command:
        raise SupervisorError("internal invariant violated: fork/--last is forbidden")
    return command


def start_continuation_turn(
    client: JsonRpcClient,
    thread_id: str,
    cwd: Path,
    expected: Sequence[dict[str, str]],
    message: str,
) -> str:
    inputs: list[dict[str, str]] = [
        {"type": "skill", "name": item["name"], "path": item["path"]}
        for item in expected
    ]
    inputs.append({"type": "text", "text": message})
    result = client.request(
        "turn/start",
        {
            "threadId": thread_id,
            "cwd": str(cwd),
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "dangerFullAccess"},
            "input": inputs,
        },
        timeout=30,
    )
    turn = result.get("turn")
    if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
        raise SupervisorError("turn/start did not return a turn id")
    return turn["id"]


class ReloadSupervisor:
    def __init__(
        self,
        *,
        codex: str,
        thread_id: str,
        cwd: Path,
        state_path: Path,
        no_alt_screen: bool,
    ) -> None:
        self.codex = codex
        self.thread_id = thread_id
        self.cwd = cwd
        self.state_path = state_path
        self.socket_path = state_path.with_suffix(".sock")
        self.no_alt_screen = no_alt_screen
        self.env = dict(os.environ)
        self.env[STATE_ENV] = str(state_path)
        self.app_server: subprocess.Popen[str] | None = None
        self.client: JsonRpcClient | None = None
        self.tui: subprocess.Popen[Any] | None = None
        self.logs: deque[str] = deque(maxlen=64)
        self.stop_requested = False

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA,
            "owner_pid": os.getpid(),
            "thread_id": self.thread_id,
            "cwd": str(self.cwd),
            "codex": self.codex,
            "codex_version": SUPPORTED_CODEX_VERSION,
            "codex_home": None,
            "socket": str(self.socket_path),
            "phase": "starting",
            "cycle": 0,
            "no_alt_screen": self.no_alt_screen,
            "expected_skills": [],
            "continuation_skills": [],
            "continue_message": None,
            "pre_reload_goal_status": None,
            "resume_after_restart": False,
            "last_error": None,
        }

    def prepare_state(self) -> None:
        if self.state_path.is_symlink():
            raise SupervisorError("symlinked supervisor state is forbidden")
        if self.state_path.exists():
            previous = read_state(self.state_path)
            if _pid_alive(previous.get("owner_pid")):
                raise SupervisorError("another live supervisor owns this state file")
        write_state(self.state_path, self._initial_state())

    def _update(self, **changes: Any) -> dict[str, Any]:
        def apply(value: dict[str, Any]) -> dict[str, Any]:
            if value.get("owner_pid") != os.getpid() or value.get("thread_id") != self.thread_id:
                raise SupervisorError("supervisor state ownership changed")
            value.update(changes)
            return value

        return mutate_state(self.state_path, apply)

    def start_server(self) -> None:
        process, client, logs = start_app_server(
            self.codex,
            self.socket_path,
            state_path=self.state_path,
            env=self.env,
        )
        self.app_server = process
        self.client = client
        self.logs = logs
        current = read_state(self.state_path)
        previous_home = current.get("codex_home")
        if previous_home is not None and Path(previous_home).absolute() != client.codex_home:
            raise SupervisorError("Codex home changed across the reload boundary")
        self._update(codex_home=str(client.codex_home))

    def stop_server(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        _terminate_process(self.app_server, process_group=True)
        self.app_server = None
        _remove_socket(self.socket_path)

    def start_tui(self) -> None:
        command = build_tui_command(
            self.codex,
            self.socket_path,
            self.cwd,
            self.thread_id,
            no_alt_screen=self.no_alt_screen,
        )
        self.tui = subprocess.Popen(command, env=self.env)

    def stop_tui(self) -> None:
        _terminate_process(self.tui)
        self.tui = None

    def _require_client(self) -> JsonRpcClient:
        if self.client is None:
            raise SupervisorError("app-server control client is unavailable")
        return self.client

    def initial_resume(self) -> None:
        self.start_server()
        resume_thread(self._require_client(), self.thread_id, self.cwd)
        self._update(phase="ready")

    def reload(self, state: dict[str, Any]) -> None:
        expected = state.get("expected_skills")
        continuation_names = state.get("continuation_skills")
        message = state.get("continue_message")
        if not isinstance(expected, list) or not expected or not all(isinstance(item, dict) for item in expected):
            raise SupervisorError("reload checkpoint has no expected skills")
        if not isinstance(message, str) or not message or len(message) > MAX_CONTINUE_MESSAGE:
            raise SupervisorError("reload checkpoint has an invalid continuation message")
        if not isinstance(continuation_names, list) or not continuation_names:
            raise SupervisorError("reload checkpoint has no continuation skill")
        old_goal = get_goal(self._require_client(), self.thread_id)
        pre_status = old_goal["status"] if old_goal is not None else None
        self._update(
            phase="restarting",
            pre_reload_goal_status=pre_status,
            resume_after_restart=pre_status == "active",
        )
        self.stop_tui()
        self.stop_server()
        self.start_server()
        client = self._require_client()
        resume_thread(client, self.thread_id, self.cwd)
        verified = verify_expected_skills(client, self.cwd, expected)
        continuation = [item for item in verified if item["name"] in continuation_names]
        if len(continuation) != len(continuation_names):
            raise SupervisorError("a continuation skill was not verified")
        continue_allowed = restore_goal_if_required(client, self.thread_id, pre_status)
        self.start_tui()
        time.sleep(0.35)
        if self.tui is None or self.tui.poll() is not None:
            raise SupervisorError("resumed TUI exited before continuation")
        if continue_allowed:
            start_continuation_turn(client, self.thread_id, self.cwd, continuation, message)
        self._update(
            phase="running",
            cycle=int(state.get("cycle", 0)) + 1,
            expected_skills=verified,
            continuation_skills=continuation_names,
            continue_message=None,
            pre_reload_goal_status=pre_status,
            resume_after_restart=False,
            last_error=None,
        )

    def _handle_signal(self, _signum: int, _frame: object) -> None:
        self.stop_requested = True

    def run(self) -> int:
        self.prepare_state()
        previous_handlers = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        try:
            self.initial_resume()
            print(_json_line({
                "ok": True,
                "phase": "running",
                "state": str(self.state_path),
                "thread": self.thread_id[:8] + "…",
                "sandbox": "danger-full-access",
                "approval_policy": "never",
            }), flush=True)
            self.start_tui()
            self._update(phase="running")
            delay = 0.2
            while not self.stop_requested:
                if self.tui is None or self.tui.poll() is not None:
                    break
                state = read_state(self.state_path)
                if state.get("phase") == "turn_complete":
                    self.reload(state)
                    delay = 0.2
                    continue
                time.sleep(delay)
                delay = min(1.0, delay * 1.25)
            self._update(phase="stopped")
            return 0
        except BaseException as exc:
            try:
                self._update(phase="failed", last_error=_short_error(exc))
            except BaseException:
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise
        finally:
            self.stop_tui()
            self.stop_server()
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)


def _resolve_codex(value: str) -> str:
    located = shutil.which(value)
    if located is None:
        raise SupervisorError(f"Codex CLI is not executable: {value}")
    return str(Path(located).resolve())


def command_run(args: argparse.Namespace) -> int:
    thread_id = _canonical_thread_id(args.thread_id)
    cwd = Path(args.cwd).expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise SupervisorError("--cwd must be an existing directory")
    state_path = resolve_state_path(args.state, thread_id=thread_id)
    codex = _resolve_codex(args.codex)
    verify_codex_runtime(codex)
    supervisor = ReloadSupervisor(
        codex=codex,
        thread_id=thread_id,
        cwd=cwd,
        state_path=state_path,
        no_alt_screen=args.no_alt_screen,
    )
    return supervisor.run()


def command_checkpoint(args: argparse.Namespace) -> int:
    state_path = resolve_state_path(args.state)
    state = read_state(state_path)
    if state.get("phase") not in {"running", "reload_requested"}:
        raise SupervisorError(f"checkpoint requires a running supervisor, observed={state.get('phase')}")
    if not _pid_alive(state.get("owner_pid")):
        raise SupervisorError("checkpoint supervisor owner is not alive")
    codex = state.get("codex")
    codex_home = state.get("codex_home")
    if not isinstance(codex, str) or not isinstance(codex_home, str):
        raise SupervisorError("checkpoint state lacks Codex runtime identity")
    expected: list[dict[str, str]] = []
    for selector in args.plugin:
        expected.extend(discover_plugin_skills(codex, Path(codex_home), selector))
    expected.extend(parse_explicit_skill(item) for item in args.skill)
    if not expected:
        raise SupervisorError("checkpoint requires at least one --plugin or --skill")
    if len(expected) > 16:
        raise SupervisorError("checkpoint exceeds the expected-skill ceiling")
    names = [item["name"] for item in expected]
    paths = [item["path"] for item in expected]
    if len(names) != len(set(names)) or len(paths) != len(set(paths)):
        raise SupervisorError("checkpoint skill names and paths must be unique")
    message = args.message
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_CONTINUE_MESSAGE:
        raise SupervisorError("checkpoint continuation message is empty or too large")
    expected = sorted(expected, key=lambda item: (item["name"], item["path"]))
    continuation_names = sorted(args.continue_skill or ([expected[0]["name"]] if len(expected) == 1 else []))
    if not continuation_names:
        raise SupervisorError("multi-skill checkpoints require at least one --continue-skill")
    if len(continuation_names) > 3 or len(continuation_names) != len(set(continuation_names)):
        raise SupervisorError("continuation skills must be unique and limited to three")
    if not set(continuation_names) <= set(names):
        raise SupervisorError("every --continue-skill must name a checkpointed skill")

    def apply(value: dict[str, Any]) -> dict[str, Any]:
        if value.get("thread_id") != state.get("thread_id") or value.get("owner_pid") != state.get("owner_pid"):
            raise SupervisorError("checkpoint state identity changed")
        if value.get("phase") == "reload_requested":
            if (
                value.get("expected_skills") == expected
                and value.get("continuation_skills") == continuation_names
                and value.get("continue_message") == message
            ):
                return value
            raise SupervisorError("a different reload checkpoint is already pending")
        if value.get("phase") != "running":
            raise SupervisorError("supervisor stopped before checkpoint commit")
        value.update({
            "phase": "reload_requested",
            "expected_skills": expected,
            "continuation_skills": continuation_names,
            "continue_message": message,
            "pre_reload_goal_status": None,
            "resume_after_restart": False,
            "last_error": None,
        })
        return value

    mutate_state(state_path, apply)
    print(_json_line({"ok": True, "phase": "reload_requested", "skills": len(expected)}))
    return 0


def _load_notify_payload(raw: str | None) -> dict[str, Any]:
    if raw is None and not sys.stdin.isatty():
        raw = sys.stdin.read(MAX_STATE_BYTES + 1)
    if raw is None or len(raw.encode("utf-8")) > MAX_STATE_BYTES:
        raise SupervisorError("notify payload is missing or oversized")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SupervisorError("notify payload is not JSON") from exc
    if not isinstance(value, dict):
        raise SupervisorError("notify payload must be an object")
    return value


def command_notify(args: argparse.Namespace) -> int:
    state_path = resolve_state_path(args.state)
    payload = _load_notify_payload(args.payload)
    if payload.get("type") != "agent-turn-complete":
        return 0
    event_thread = payload.get("thread-id", payload.get("thread_id"))
    event_cwd = payload.get("cwd")
    observed = read_state(state_path)
    if observed.get("phase") in {"running", "turn_complete", "restarting", "stopped"}:
        return 0

    def apply(value: dict[str, Any]) -> dict[str, Any]:
        if event_thread != value.get("thread_id"):
            raise SupervisorError("notify thread id does not match supervisor state")
        if isinstance(event_cwd, str) and Path(event_cwd).resolve() != Path(value["cwd"]).resolve():
            raise SupervisorError("notify cwd does not match supervisor state")
        phase = value.get("phase")
        if phase == "reload_requested":
            value["phase"] = "turn_complete"
        elif phase != "turn_complete":
            raise SupervisorError(f"notify arrived in invalid phase: {phase}")
        return value

    mutate_state(state_path, apply)
    return 0


def _redacted_status(state: dict[str, Any]) -> dict[str, Any]:
    thread_id = state.get("thread_id")
    return {
        "ok": state.get("phase") not in {"failed"},
        "phase": state.get("phase"),
        "cycle": state.get("cycle"),
        "thread": thread_id[:8] + "…" if isinstance(thread_id, str) else None,
        "owner_alive": _pid_alive(state.get("owner_pid")),
        "expected_skills": len(state.get("expected_skills", [])),
        "continuation_skills": len(state.get("continuation_skills", [])),
        "last_error": state.get("last_error"),
    }


def command_status(args: argparse.Namespace) -> int:
    state_path = resolve_state_path(args.state)
    state = read_state(state_path)
    print(_json_line(_redacted_status(state)))
    return 1 if state.get("phase") == "failed" else 0


def command_validate(args: argparse.Namespace) -> int:
    codex = _resolve_codex(args.codex)
    verified = verify_codex_runtime(codex)
    probe_cwd = Path(args.probe_cwd).expanduser().resolve(strict=True) if args.probe_cwd else None
    if probe_cwd is not None:
        if not probe_cwd.is_dir():
            raise SupervisorError("--probe-cwd must be an existing directory")
        with tempfile.TemporaryDirectory(prefix="codex-reload-probe-") as directory:
            socket_path = Path(directory) / "app.sock"
            process: subprocess.Popen[str] | None = None
            client: JsonRpcClient | None = None
            try:
                process, client, _logs = start_app_server(
                    codex,
                    socket_path,
                    state_path=Path(directory) / "notify-state.json",
                    env=dict(os.environ),
                )
                result = client.request(
                    "skills/list", {"cwds": [str(probe_cwd)], "forceReload": True}, timeout=30,
                )
                data = result.get("data")
                if not isinstance(data, list) or not any(
                    isinstance(item, dict)
                    and isinstance(item.get("cwd"), str)
                    and Path(item["cwd"]).resolve() == probe_cwd
                    for item in data
                ):
                    raise SupervisorError("app-server probe did not return the requested cwd")
            finally:
                if client is not None:
                    client.close()
                _terminate_process(process, process_group=True)
                _remove_socket(socket_path)
        verified["probe"] = "passed"
    print(_json_line({"ok": True, **verified}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="own one exact thread through reload cycles")
    run_parser.add_argument("--thread-id", required=True)
    run_parser.add_argument("--cwd", default=os.getcwd())
    run_parser.add_argument("--state")
    run_parser.add_argument("--codex", default="codex")
    run_parser.add_argument("--no-alt-screen", action="store_true")
    run_parser.set_defaults(handler=command_run)

    checkpoint_parser = subparsers.add_parser(
        "checkpoint", help="pin newly installed skill bytes for restart after this turn",
    )
    checkpoint_parser.add_argument("--state")
    checkpoint_parser.add_argument("--plugin", action="append", default=[], metavar="PLUGIN@MARKETPLACE")
    checkpoint_parser.add_argument("--skill", action="append", default=[], metavar="NAME=SKILL.md")
    checkpoint_parser.add_argument("--continue-skill", action="append", default=[], metavar="NAME")
    checkpoint_parser.add_argument("--message", default=DEFAULT_CONTINUE_MESSAGE)
    checkpoint_parser.set_defaults(handler=command_checkpoint)

    notify_parser = subparsers.add_parser("notify", help="internal agent-turn-complete callback")
    notify_parser.add_argument("--state")
    notify_parser.add_argument("payload", nargs="?")
    notify_parser.set_defaults(handler=command_notify)

    status_parser = subparsers.add_parser("status", help="show one compact redacted state summary")
    status_parser.add_argument("--state")
    status_parser.set_defaults(handler=command_status)

    validate_parser = subparsers.add_parser("validate", help="verify the pinned Codex protocol")
    validate_parser.add_argument("--codex", default="codex")
    validate_parser.add_argument("--probe-cwd")
    validate_parser.set_defaults(handler=command_validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, SupervisorError, subprocess.SubprocessError) as exc:
        print(_json_line({"ok": False, "error": _short_error(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
