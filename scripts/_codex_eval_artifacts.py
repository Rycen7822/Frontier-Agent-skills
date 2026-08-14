"""Build bounded, deterministic evidence for Codex evaluation attempts."""

from __future__ import annotations

import difflib
from hashlib import sha256
import os
from pathlib import Path
from typing import Any, Callable


MAX_TRACE_ITEMS = 256
MAX_WORKSPACE_PATHS = 128
MAX_FILE_CONTENT_BYTES = 64 * 1024
MAX_TOTAL_CONTENT_BYTES = 512 * 1024
MAX_DIFF_BYTES = 256 * 1024
MAX_PREVIEW_BYTES = 1024


class ArtifactError(ValueError):
    """A direct Host evidence artifact cannot be constructed safely."""


def _digest(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _utf8_prefix(value: str, limit: int) -> str:
    raw = value.encode("utf-8")
    return raw[:limit].decode("utf-8", errors="ignore")


def _diff_lines(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
        lines.append("\\ No newline at end of file\n")
    return lines


def _relative_path(value: Any, workspace: Path, workspace_alias: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ArtifactError("Codex file change path is invalid")
    relative = value
    if value.startswith("/"):
        for root in (workspace.as_posix().rstrip("/"), workspace_alias.rstrip("/")):
            if root and value.startswith(root + "/"):
                relative = value[len(root) + 1 :]
                break
        else:
            raise ArtifactError("Codex file change escapes the workspace")
    parts = relative.split("/")
    if (
        any(part in {"", ".", ".."} for part in parts)
        or (
            len(relative) >= 2
            and relative[0].isalpha()
            and relative[1] == ":"
        )
    ):
        raise ArtifactError("Codex file change path is not normalized")
    return relative


def _change_kind(change: dict[str, Any]) -> tuple[str, str | None]:
    kind = change.get("kind")
    move_path = change.get("move_path")
    if kind in {"add", "create"}:
        if move_path is not None:
            raise ArtifactError("Codex create change has a rename destination")
        return "create", None
    if kind == "delete":
        if move_path is not None:
            raise ArtifactError("Codex delete change has a rename destination")
        return "delete", None
    if kind in {"update", "modify"}:
        if move_path is None:
            return "modify", None
        if not isinstance(move_path, str):
            raise ArtifactError("Codex rename destination is invalid")
        return "rename", move_path
    raise ArtifactError("Codex file change kind is unsupported")


def build_command_trace(
    turns: list[dict[str, Any]],
    turn_ids: list[str],
    *,
    workspace: Path,
    workspace_alias: str,
    normalize_text: Callable[[str], str],
) -> dict[str, Any]:
    """Project only direct completed command and file-change facts."""
    complete = True
    overflow = False
    items: list[dict[str, Any]] = []
    ordinal = 0
    for turn_id, turn in zip(turn_ids, turns, strict=True):
        for fact in turn["items"]:
            if fact.get("phase") != "completed" or fact.get("type") not in {
                "command_execution",
                "file_change",
            }:
                continue
            if fact["type"] == "file_change" and fact.get("changes") == []:
                continue
            ordinal += 1
            if ordinal > MAX_TRACE_ITEMS:
                overflow = True
                complete = False
                continue
            base = {"ordinal": ordinal, "turn_id": turn_id, "type": fact["type"]}
            if fact["type"] == "command_execution":
                command = fact.get("command")
                output = fact.get("aggregated_output")
                exit_code = fact.get("exit_code")
                status = fact.get("status")
                valid = (
                    isinstance(command, str)
                    and isinstance(output, str)
                    and isinstance(exit_code, int)
                    and not isinstance(exit_code, bool)
                    and isinstance(status, str)
                )
                if not valid:
                    complete = False
                    items.append(base | {
                        "status": status if isinstance(status, str) else None,
                        "exit_code": (
                            exit_code
                            if isinstance(exit_code, int) and not isinstance(exit_code, bool)
                            else None
                        ),
                    })
                    continue
                normalized_command = normalize_text(command.replace("\r\n", "\n").replace("\r", "\n"))
                normalized_output = normalize_text(output.replace("\r\n", "\n").replace("\r", "\n"))
                command_bytes = normalized_command.encode("utf-8")
                output_bytes = normalized_output.encode("utf-8")
                items.append(base | {
                    "status": status,
                    "exit_code": exit_code,
                    "command_sha256": _digest(command_bytes),
                    "command_preview": _utf8_prefix(normalized_command, MAX_PREVIEW_BYTES),
                    "output_sha256": _digest(output_bytes),
                    "output_preview": _utf8_prefix(normalized_output, MAX_PREVIEW_BYTES),
                    "output_bytes": len(output_bytes),
                })
                continue

            changes = fact.get("changes")
            projected: list[dict[str, str]] = []
            if not isinstance(changes, list) or not changes:
                complete = False
            else:
                for change in changes:
                    try:
                        if not isinstance(change, dict):
                            raise ArtifactError("Codex file change is not an object")
                        action, destination = _change_kind(change)
                        item = {
                            "path": _relative_path(
                                change.get("path"), workspace, workspace_alias
                            ),
                            "action": action,
                        }
                        if destination is not None:
                            item["destination"] = _relative_path(
                                destination, workspace, workspace_alias
                            )
                        projected.append(item)
                    except ArtifactError:
                        complete = False
            items.append(base | {"changes": projected})
    return {
        "schema_version": "codex-command-trace/1",
        "complete": complete,
        "overflow": overflow,
        "items": items,
    }


class WorkspaceEvidence:
    """Capture one bounded workspace timeline and deterministic final diff."""

    def __init__(
        self,
        workspace: Path,
        *,
        ignored: Callable[[Path], bool],
    ) -> None:
        self.workspace = workspace
        self.ignored = ignored
        self.remaining_content = MAX_TOTAL_CONTENT_BYTES
        self.complete = True
        self.overflow = False
        self.initial: list[dict[str, Any]] | None = None
        self.turn_snapshots: list[dict[str, Any]] = []
        self._initial_bytes: dict[str, bytes] = {}
        self._turn_bytes: list[dict[str, bytes]] = []

    def _files(self) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        pending = [self.workspace]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as scan:
                    entries = sorted(scan, key=lambda item: item.name)
            except OSError as exc:
                raise ArtifactError("workspace evidence directory is unreadable") from exc
            directories: list[Path] = []
            for entry in entries:
                path = Path(entry.path)
                relative = path.relative_to(self.workspace)
                if self.ignored(relative):
                    continue
                if entry.is_symlink():
                    raise ArtifactError("workspace contains an undeclared symlink")
                if entry.is_dir(follow_symlinks=False):
                    directories.append(path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    raise ArtifactError("workspace contains an unsupported file type")
                name = _relative_path(relative.as_posix(), self.workspace, "")
                if name in files:
                    raise ArtifactError("workspace evidence contains a duplicate path")
                if len(files) == MAX_WORKSPACE_PATHS:
                    self.complete = False
                    self.overflow = True
                    return files
                try:
                    files[name] = path.read_bytes()
                except OSError as exc:
                    raise ArtifactError("workspace evidence file is unreadable") from exc
            pending.extend(reversed(directories))
        return files

    def _records(self, files: dict[str, bytes]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path, raw in sorted(files.items()):
            encoding = "utf-8"
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                encoding = "binary"
                text = None
            content = None
            truncated = True
            if (
                text is not None
                and len(raw) <= MAX_FILE_CONTENT_BYTES
                and len(raw) <= self.remaining_content
            ):
                content = text
                truncated = False
                self.remaining_content -= len(raw)
            records.append({
                "path": path,
                "sha256": _digest(raw),
                "bytes": len(raw),
                "encoding": encoding,
                "content": content,
                "truncated": truncated,
            })
        return records

    def capture_initial(self) -> None:
        if self.initial is not None:
            raise ArtifactError("workspace initial snapshot is duplicated")
        self._initial_bytes = self._files()
        self.initial = self._records(self._initial_bytes)

    def capture_turn(self, turn_id: str) -> None:
        if self.initial is None or not isinstance(turn_id, str) or not turn_id:
            raise ArtifactError("workspace turn snapshot is invalid")
        files = self._files()
        self._turn_bytes.append(files)
        self.turn_snapshots.append({
            "turn_id": turn_id,
            "files": self._records(files),
        })

    def finish(self) -> tuple[dict[str, Any], list[str]]:
        if self.initial is None:
            raise ArtifactError("workspace initial snapshot is absent")
        final_bytes = self._files()
        final = self._records(final_bytes)
        byte_snapshots = [self._initial_bytes, *self._turn_bytes, final_bytes]
        record_snapshots = [
            {item["path"]: item for item in self.initial},
            *[
                {item["path"]: item for item in snapshot["files"]}
                for snapshot in self.turn_snapshots
            ],
            {item["path"]: item for item in final},
        ]
        changed_set: set[str] = set()
        for before_bytes, after_bytes, before_records, after_records in zip(
            byte_snapshots[:-1],
            byte_snapshots[1:],
            record_snapshots[:-1],
            record_snapshots[1:],
            strict=True,
        ):
            transition = {
                path
                for path in before_bytes.keys() | after_bytes.keys()
                if before_bytes.get(path) != after_bytes.get(path)
            }
            changed_set.update(transition)
            if any(
                record is not None and record["truncated"]
                for path in transition
                for record in (before_records.get(path), after_records.get(path))
            ):
                self.complete = False
        changed = sorted(changed_set)
        initial_records = {item["path"]: item for item in self.initial}
        final_records = {item["path"]: item for item in final}
        diff_parts: list[str] = []
        final_delta = sorted(
            path
            for path in self._initial_bytes.keys() | final_bytes.keys()
            if self._initial_bytes.get(path) != final_bytes.get(path)
        )
        for path in final_delta:
            before = initial_records.get(path)
            after = final_records.get(path)
            if (
                (before is not None and before["truncated"])
                or (after is not None and after["truncated"])
            ):
                self.complete = False
                continue
            before_text = "" if before is None else before["content"]
            after_text = "" if after is None else after["content"]
            if not isinstance(before_text, str) or not isinstance(after_text, str):
                self.complete = False
                continue
            before_lines = _diff_lines(before_text)
            after_lines = _diff_lines(after_text)
            diff_parts.extend(difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="\n",
            ))
        diff = "".join(diff_parts)
        if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
            diff = _utf8_prefix(diff, MAX_DIFF_BYTES)
            self.complete = False
            self.overflow = True
        return ({
            "schema_version": "codex-workspace-evidence/1",
            "complete": self.complete,
            "overflow": self.overflow,
            "initial": self.initial,
            "turn_snapshots": self.turn_snapshots,
            "final": final,
            "diff": diff,
        }, changed)


def build_host_observation(
    *,
    terminal_status: str,
    codex_status: str,
    turn_ids: list[str],
    changed_paths: list[str],
    command_trace: dict[str, Any],
    workspace_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Bind Host status to the two bounded evidence streams."""
    return {
        "schema_version": "codex-host-observation/1",
        "terminal_status": terminal_status,
        "codex_status": codex_status,
        "turn_ids": turn_ids,
        "changed_paths": changed_paths,
        "command_trace_complete": command_trace["complete"],
        "command_trace_overflow": command_trace["overflow"],
        "workspace_evidence_complete": workspace_evidence["complete"],
        "workspace_evidence_overflow": workspace_evidence["overflow"],
    }
