"""Opt-in, redacted diagnostics for one Codex child process invocation."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "codex-child-transport-diagnostic/1"
MAX_JSONL_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 4096
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
SECRET_MARKER = re.compile(
    rb"(?:sk-[A-Za-z0-9_-]{8,}|(?:token|secret|password|authorization|api[_-]?key)=)",
    re.IGNORECASE,
)


class DiagnosticCaptureError(ValueError):
    """The opt-in diagnostic capture target is unsafe or ambiguous."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(raw: bytes) -> str:
    return "sha256:" + sha256(raw).hexdigest()


def _safe(value: Any) -> str | None:
    return value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None


def summarize_jsonl(
    raw: bytes,
    *,
    workspace: Path | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    """Return lifecycle facts without retaining event payloads or path text."""
    workspace_bytes = str(workspace).encode() if workspace is not None else b""
    source_bytes = str(source_root).encode() if source_root is not None else b""
    source_path_seen = bool(
        (workspace_bytes and workspace_bytes in raw)
        or (source_bytes and source_bytes in raw)
    )
    credential_marker_seen = bool(SECRET_MARKER.search(raw))
    view: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "byte_count": len(raw),
        "line_count": len(raw.splitlines()),
        "bounded": len(raw) <= MAX_JSONL_BYTES,
        "parse_errors": [],
        "events": [],
        "event_types": [],
        "event_ids": [],
        "turn_started": 0,
        "turn_terminals": [],
        "item_started": [],
        "item_completed": [],
        "incomplete_items": [],
        "usage_records": 0,
        "usage_present": False,
        "final_message_event_present": False,
        "redaction": {
            "source_path_seen": source_path_seen,
            "credential_marker_seen": credential_marker_seen,
            "payloads_omitted": True,
        },
    }
    if len(raw) > MAX_JSONL_BYTES:
        view["parse_errors"].append("stream_size")
        return view
    started: dict[str, str] = {}
    completed: set[str] = set()
    for index, line in enumerate(raw.splitlines(), 1):
        if index > MAX_RECORDS:
            view["parse_errors"].append("record_count")
            break
        if not line:
            continue
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            view["parse_errors"].append(index)
            continue
        if not isinstance(record, dict):
            view["parse_errors"].append(index)
            continue
        record_type = _safe(record.get("type"))
        event_id = _safe(record.get("id"))
        item = record.get("item")
        item_type = _safe(item.get("type")) if isinstance(item, dict) else None
        item_id = _safe(item.get("id")) if isinstance(item, dict) else None
        if record_type:
            view["event_types"].append(record_type)
        if event_id:
            view["event_ids"].append(event_id)
        view["events"].append(
            {
                "index": index,
                "type": record_type,
                "id": event_id,
                "item_type": item_type,
                "item_id": item_id,
            }
        )
        if record_type == "turn.started":
            view["turn_started"] += 1
        if record_type in {"turn.completed", "turn.failed", "turn.cancelled"}:
            view["turn_terminals"].append(record_type)
        if record_type == "item.started" and item_id and item_type:
            started[item_id] = item_type
            view["item_started"].append({"id": item_id, "type": item_type})
        if record_type == "item.completed" and item_id:
            completed.add(item_id)
            view["item_completed"].append({"id": item_id, "type": item_type})
        if record_type == "item.completed" and item_type == "agent_message":
            view["final_message_event_present"] = True
        usage = record.get("usage")
        if isinstance(usage, dict):
            view["usage_present"] = True
            view["usage_records"] += 1
    view["incomplete_items"] = [
        {"id": item_id, "type": item_type}
        for item_id, item_type in started.items()
        if item_id not in completed
    ]
    for key in ("event_types", "event_ids"):
        view[key] = list(dict.fromkeys(view[key]))
    return view


def capture_child(
    capture_dir: Path,
    capture_id: str,
    child: dict[str, Any],
    *,
    workspace: Path,
    source_root: Path | None,
    last_message: Path | None,
    reset_clean: bool | None = None,
) -> Path:
    """Write complete raw channels once and a safe machine-readable audit view."""
    if not capture_dir.is_absolute() or capture_dir.is_symlink():
        raise DiagnosticCaptureError("diagnostic capture directory is unsafe")
    if not SAFE_ID.fullmatch(capture_id):
        raise DiagnosticCaptureError("diagnostic capture id is unsafe")
    if source_root is not None:
        try:
            capture_dir.resolve().relative_to(source_root.resolve())
        except ValueError:
            pass
        else:
            raise DiagnosticCaptureError("diagnostic capture is inside source root")
    try:
        capture_dir.resolve().relative_to(workspace.resolve())
    except ValueError:
        pass
    else:
        raise DiagnosticCaptureError("diagnostic capture is inside workspace")
    capture_dir.mkdir(parents=True, exist_ok=True)
    if capture_dir.is_symlink() or not capture_dir.is_dir():
        raise DiagnosticCaptureError("diagnostic capture directory is not regular")
    target = capture_dir / capture_id
    if target.exists() or target.is_symlink():
        raise DiagnosticCaptureError("diagnostic capture target already exists")
    target.mkdir(mode=0o700)
    stdout = child.get("stdout") if isinstance(child.get("stdout"), bytes) else b""
    stderr = child.get("stderr") if isinstance(child.get("stderr"), bytes) else b""
    stdout_path = target / "child-stdout.raw"
    stderr_path = target / "child-stderr.raw"
    stdout_path.write_bytes(stdout)
    stderr_path.write_bytes(stderr)
    stdout_path.chmod(0o600)
    stderr_path.chmod(0o600)
    view = summarize_jsonl(stdout, workspace=workspace, source_root=source_root)
    view["stderr"] = {
        "byte_count": len(stderr),
        "digest": _digest(stderr),
        "source_path_seen": bool(
            (str(workspace).encode() in stderr)
            or (source_root is not None and str(source_root).encode() in stderr)
        ),
        "credential_marker_seen": bool(SECRET_MARKER.search(stderr)),
    }
    view["stdout_digest"] = _digest(stdout)
    view["process"] = {
        "returncode": child.get("returncode"),
        "timed_out": child.get("timed_out"),
        "runtime_ms": child.get("runtime_ms"),
        "signal": (
            -child["returncode"]
            if isinstance(child.get("returncode"), int) and child["returncode"] < 0
            else None
        ),
    }
    view["final_message"] = {
        "path_checked": last_message is not None,
        "present": bool(last_message and last_message.is_file()),
    }
    view["reset_custody"] = (
        "clean" if reset_clean is True else "dirty" if reset_clean is False else "not_checked"
    )
    audit_path = target / "audit.json"
    audit_path.write_bytes(_canonical(view) + b"\n")
    audit_path.chmod(0o600)
    return target
