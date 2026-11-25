"""Build and validate the blinded execution model-grader transport."""

from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Any


UNCERTAINTY = {"none", "low", "medium", "high"}
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
LOCAL_PATH_PLACEHOLDER = "local-path-redacted"
UNBOUND_LOCAL_PATH = re.compile(
    r"(?<![:/\\A-Za-z0-9])"
    r"(?:[A-Za-z]:[\\/](?:Users|workspace|workspaces)|/"
    r"(?:home|private|tmp|opt|Users|workspace|workspaces))"
    r"(?:[\\/][^\s`'\"<>()\[\]{},;!?，。；！？]*)?"
    r"(?=$|[\s`'\"<>()\[\]{},;.!?，。；！？])"
)
MAX_WORKSPACE_EVIDENCE_BYTES = 6 * 1024 * 1024
MAX_COMMAND_TRACE_BYTES = 4 * 1024 * 1024
WORKSPACE_EVIDENCE_FIELDS = {
    "schema_version",
    "complete",
    "overflow",
    "initial",
    "turn_snapshots",
    "final",
    "diff",
}
HOST_OBSERVATION_FIELDS = {
    "schema_version",
    "terminal_status",
    "codex_status",
    "turn_ids",
    "changed_paths",
    "command_trace_complete",
    "command_trace_overflow",
    "workspace_evidence_complete",
    "workspace_evidence_overflow",
}
HOST_OBSERVATION_LIFECYCLE_FIELDS = HOST_OBSERVATION_FIELDS | {"lifecycle"}
COMMAND_TRACE_FIELDS = {"schema_version", "complete", "overflow", "items"}
COMMAND_TRACE_V2 = "codex-command-trace/2"
HOST_OBSERVATION_V2 = "codex-host-observation/2"
EVIDENCE_PATHS = {
    "host-observation": "workspace/host-observation.json",
    "command-trace": "workspace/command-trace.json",
    "workspace-evidence": "workspace/workspace-evidence.json",
    "final-answer": "workspace/final-answer.md",
    "turn-answers": "workspace/turn-answers.json",
}


def _valid_relative_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith("/")
        and "\\" not in value
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
        and re.match(r"^[A-Za-z]:", value) is None
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _relative_evidence_paths(
    assessment: dict[str, Any],
    fixture_paths: list[str] | None = None,
) -> list[str]:
    """Validate and collect fixture-relative paths from host evidence."""
    paths = set(fixture_paths or [])
    if any(not _valid_relative_path(path) for path in paths):
        raise ValueError("model grader fixture path is invalid")
    for value in assessment.get("changed_paths", []):
        if not _valid_relative_path(value):
            raise ValueError("model grader changed path is invalid")
        paths.add(value)
    return sorted(paths, key=len, reverse=True)


def _blind_unbound_local_paths(value: str) -> str:
    """Blind roots while preserving suffixes below an explicitly cited root."""
    paths = {
        match.group(0).rstrip(".").replace("\\", "/").rstrip("/")
        for match in UNBOUND_LOCAL_PATH.finditer(value)
    }
    roots = sorted(paths, key=len)

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        trailing_periods = len(raw) - len(raw.rstrip("."))
        path = raw.rstrip(".").replace("\\", "/").rstrip("/")
        ancestor = next(
            (root for root in roots if path != root and path.startswith(root + "/")),
            None,
        )
        suffix = path[len(ancestor) :] if ancestor is not None else ""
        return LOCAL_PATH_PLACEHOLDER + suffix + "." * trailing_periods

    return UNBOUND_LOCAL_PATH.sub(replace, value)


def _redact_workspace_paths(
    final_answer: str,
    assessment: dict[str, Any],
    fixture_paths: list[str] | None = None,
) -> str:
    """Blind local paths while retaining bound relative evidence paths."""
    if not isinstance(final_answer, str):
        raise ValueError("model grader final answer is invalid")
    redacted = final_answer
    for path in _relative_evidence_paths(assessment, fixture_paths):
        angle_path = re.compile(
            rf"<[^>\n]*/{re.escape(path)}(?P<line>:\d+)?>",
        )
        redacted = angle_path.sub(
            lambda match: f"<{path}{match.group('line') or ''}>",
            redacted,
        )
        plain_path = re.compile(
            rf"(?<![:A-Za-z0-9])(?:[A-Za-z]:[\\/]|/)"
            rf"[^\s`'\"<>()]*{re.escape(path)}(?P<line>:\d+)?",
        )
        redacted = plain_path.sub(
            lambda match: f"{path}{match.group('line') or ''}",
            redacted,
        )
    return _blind_unbound_local_paths(redacted)


def _canonical_payload(value: dict[str, Any], payload: str) -> bool:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        == payload
    )


def _validate_lifecycle_projection(value: Any) -> dict[str, Any]:
    common = {
        "contract_version",
        "branch",
        "incomplete_items",
        "turn_completed",
        "final_message_present",
        "usage_present",
        "custody_closed",
        "retryable",
        "reserve_consumption",
        "sample_valid",
        "process_gate",
        "unknown_completion",
    }
    if not isinstance(value, dict) or set(value) != common:
        raise ValueError("model grader lifecycle projection differs")
    if (
        value.get("contract_version") != "codex-child-lifecycle/2"
        or value.get("branch") != "outcome_bearing_abandoned"
        or value.get("turn_completed") is not True
        or value.get("final_message_present") is not True
        or value.get("usage_present") is not True
        or value.get("custody_closed") is not True
        or value.get("retryable") is not False
        or value.get("reserve_consumption") is not False
        or value.get("sample_valid") is not True
        or value.get("process_gate")
        != {
            "status": "fail",
            "reason": "command completion, exit code, and output remain unknown",
        }
    ):
        raise ValueError("model grader lifecycle projection contradicts its branch")
    incomplete = value.get("incomplete_items")
    unknown = value.get("unknown_completion")
    if (
        not isinstance(incomplete, list)
        or not incomplete
        or not isinstance(unknown, list)
        or unknown != [item.get("id") for item in incomplete]
        or len(unknown) != len(set(unknown))
    ):
        raise ValueError("model grader lifecycle item identity differs")
    for item in incomplete:
        if (
            not isinstance(item, dict)
            or set(item) - {"id", "type", "command", "status"}
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or item.get("type") != "command_execution"
            or ("command" in item and not isinstance(item["command"], str))
            or ("status" in item and not isinstance(item["status"], str))
        ):
            raise ValueError("model grader lifecycle item shape differs")
    return value


def _host_observation(payload: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("model grader host assessment is invalid JSON") from exc
    changed = value.get("changed_paths") if isinstance(value, dict) else None
    turns = value.get("turn_ids") if isinstance(value, dict) else None
    version = value.get("schema_version") if isinstance(value, dict) else None
    lifecycle = None
    if (
        version != HOST_OBSERVATION_V2
        or set(value) != HOST_OBSERVATION_LIFECYCLE_FIELDS
    ):
        raise ValueError("model grader host assessment differs")
    if value["lifecycle"] is not None:
        lifecycle = _validate_lifecycle_projection(value["lifecycle"])
    if (
        value.get("terminal_status") not in {"completed", "failed"}
        or value.get("codex_status") not in {"completed", "failed", "protocol_error"}
        or not isinstance(turns, list)
        or not turns
        or any(not isinstance(turn, str) or not turn for turn in turns)
        or len(turns) != len(set(turns))
        or not isinstance(changed, list)
        or any(not isinstance(path, str) for path in changed)
        or changed != sorted(set(changed))
        or any(not _valid_relative_path(path) for path in changed)
        or any(
            not isinstance(value[field], bool)
            for field in (
                "command_trace_complete",
                "command_trace_overflow",
                "workspace_evidence_complete",
                "workspace_evidence_overflow",
            )
        )
        or not _canonical_payload(value, payload)
    ):
        raise ValueError("model grader host assessment differs")
    value = dict(value)
    value["_lifecycle"] = lifecycle
    return value


def _file_records(value: Any) -> tuple[dict[str, dict[str, Any]], int]:
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError("model grader workspace snapshot is invalid")
    records: dict[str, dict[str, Any]] = {}
    content_bytes = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "sha256",
            "bytes",
            "encoding",
            "content",
            "truncated",
        }:
            raise ValueError("model grader workspace file record differs")
        path = item["path"]
        raw = (
            item["content"].encode("utf-8")
            if isinstance(item["content"], str)
            else None
        )
        if (
            not _valid_relative_path(path)
            or path in records
            or not isinstance(item["sha256"], str)
            or not HASH.fullmatch(item["sha256"])
            or isinstance(item["bytes"], bool)
            or not isinstance(item["bytes"], int)
            or item["bytes"] < 0
            or item["encoding"] not in {"utf-8", "binary"}
            or not isinstance(item["truncated"], bool)
            or (raw is None and (item["content"] is not None or not item["truncated"]))
            or (
                raw is not None
                and (
                    item["encoding"] != "utf-8"
                    or item["truncated"]
                    or len(raw) > 64 * 1024
                    or item["bytes"] != len(raw)
                    or item["sha256"] != "sha256:" + sha256(raw).hexdigest()
                )
            )
            or (item["encoding"] == "binary" and raw is not None)
        ):
            raise ValueError("model grader workspace file record is invalid")
        records[path] = item
        content_bytes += 0 if raw is None else len(raw)
    if list(records) != sorted(records):
        raise ValueError("model grader workspace files are not ordered")
    return records, content_bytes


def _workspace_evidence(
    payload: str,
    assessment: dict[str, Any],
) -> dict[str, Any]:
    if len(payload.encode("utf-8")) > MAX_WORKSPACE_EVIDENCE_BYTES:
        raise ValueError("model grader workspace evidence exceeds its bound")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("model grader workspace evidence is invalid JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) != WORKSPACE_EVIDENCE_FIELDS
        or value.get("schema_version") != "codex-workspace-evidence/1"
        or not isinstance(value.get("complete"), bool)
        or not isinstance(value.get("overflow"), bool)
        or not isinstance(value.get("turn_snapshots"), list)
        or not isinstance(value.get("diff"), str)
        or len(value["diff"].encode("utf-8")) > 256 * 1024
    ):
        raise ValueError("model grader workspace evidence differs")
    initial, content_bytes = _file_records(value["initial"])
    final, final_bytes = _file_records(value["final"])
    content_bytes += final_bytes
    snapshot_turns: list[str] = []
    snapshots: list[dict[str, dict[str, Any]]] = []
    for snapshot in value["turn_snapshots"]:
        if not isinstance(snapshot, dict) or set(snapshot) != {"turn_id", "files"}:
            raise ValueError("model grader workspace turn snapshot differs")
        snapshot_turns.append(snapshot["turn_id"])
        records, snapshot_bytes = _file_records(snapshot["files"])
        snapshots.append(records)
        content_bytes += snapshot_bytes
    changed_set: set[str] = set()
    truncated_change = False
    timeline = [initial, *snapshots, final]
    for before, after in zip(timeline, timeline[1:]):
        transition = {
            path
            for path in before.keys() | after.keys()
            if before.get(path, {}).get("sha256") != after.get(path, {}).get("sha256")
        }
        changed_set.update(transition)
        truncated_change = truncated_change or any(
            record is not None and record["truncated"]
            for path in transition
            for record in (before.get(path), after.get(path))
        )
    changed = sorted(changed_set)
    if (
        content_bytes > 512 * 1024
        or snapshot_turns != assessment["turn_ids"]
        or changed != assessment["changed_paths"]
        or value["complete"] != assessment["workspace_evidence_complete"]
        or value["overflow"] != assessment["workspace_evidence_overflow"]
        or value["complete"]
        and (value["overflow"] or truncated_change)
        or not _canonical_payload(value, payload)
    ):
        raise ValueError("model grader workspace evidence binding differs")
    return value


def _semantic_workspace_complete(
    workspace: dict[str, Any],
    assessment: dict[str, Any],
) -> bool:
    """Accept metadata-only Python caches without weakening source evidence."""
    if workspace["complete"]:
        return True
    if workspace["overflow"]:
        return False
    snapshots = [
        workspace["initial"],
        *(snapshot["files"] for snapshot in workspace["turn_snapshots"]),
        workspace["final"],
    ]
    incomplete_found = False
    for path in assessment["changed_paths"]:
        incomplete = [
            record
            for snapshot in snapshots
            for record in snapshot
            if record["path"] == path and record["truncated"]
        ]
        if not incomplete:
            continue
        incomplete_found = True
        parts = path.split("/")
        if (
            "__pycache__" not in parts
            or not path.endswith(".pyc")
            or any(record["encoding"] != "binary" for record in incomplete)
        ):
            return False
    return incomplete_found


def _command_trace(payload: str, assessment: dict[str, Any]) -> dict[str, Any]:
    if len(payload.encode("utf-8")) > MAX_COMMAND_TRACE_BYTES:
        raise ValueError("model grader command trace exceeds its bound")
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("model grader command trace is invalid JSON") from exc
    items = value.get("items") if isinstance(value, dict) else None
    version = value.get("schema_version") if isinstance(value, dict) else None
    lifecycle = assessment.get("_lifecycle")
    if (
        not isinstance(value, dict)
        or set(value) != COMMAND_TRACE_FIELDS
        or version != COMMAND_TRACE_V2
        or not isinstance(value.get("complete"), bool)
        or not isinstance(value.get("overflow"), bool)
        or not isinstance(items, list)
        or len(items) > 256
        or value["complete"] != assessment["command_trace_complete"]
        or value["overflow"] != assessment["command_trace_overflow"]
        or value["complete"]
        and value["overflow"]
    ):
        raise ValueError("model grader command trace differs")
    abandoned_ids: list[str] = []
    for ordinal, item in enumerate(items, 1):
        base = {"ordinal", "turn_id", "type"}
        if (
            not isinstance(item, dict)
            or item.get("ordinal") != ordinal
            or item.get("turn_id") not in assessment["turn_ids"]
            or item.get("type") not in {"command_execution", "file_change"}
        ):
            raise ValueError("model grader command trace item is invalid")
        if item["type"] == "command_execution":
            if "item_id" in item:
                abandoned_fields = {
                    "ordinal",
                    "turn_id",
                    "type",
                    "item_id",
                    "status",
                    "completion",
                    "exit_code",
                    "output_sha256",
                    "output_bytes",
                    "command_sha256",
                    "command_preview",
                }
                if (
                    lifecycle is None
                    or set(item) != abandoned_fields
                    or not isinstance(item["item_id"], str)
                    or not item["item_id"]
                    or item["status"] != "abandoned"
                    or item["completion"] != "unknown"
                    or item["exit_code"] is not None
                    or item["output_sha256"] is not None
                    or item["output_bytes"] is not None
                    or not isinstance(item["command_sha256"], str)
                    or not HASH.fullmatch(item["command_sha256"])
                    or not isinstance(item["command_preview"], str)
                    or len(item["command_preview"].encode("utf-8")) > 1024
                ):
                    raise ValueError("model grader abandoned command item differs")
                abandoned_ids.append(item["item_id"])
                continue
            full = base | {
                "status",
                "exit_code",
                "command_sha256",
                "command_preview",
                "output_sha256",
                "output_preview",
                "output_bytes",
            }
            partial = base | {"status", "exit_code"}
            fields = frozenset(item)
            if fields not in {frozenset(full), frozenset(partial)}:
                raise ValueError("model grader command item fields differ")
            if fields == full:
                if (
                    not isinstance(item["status"], str)
                    or isinstance(item["exit_code"], bool)
                    or not isinstance(item["exit_code"], int)
                    or not isinstance(item["command_sha256"], str)
                    or not HASH.fullmatch(item["command_sha256"])
                    or not isinstance(item["output_sha256"], str)
                    or not HASH.fullmatch(item["output_sha256"])
                    or not isinstance(item["command_preview"], str)
                    or len(item["command_preview"].encode("utf-8")) > 1024
                    or not isinstance(item["output_preview"], str)
                    or len(item["output_preview"].encode("utf-8")) > 1024
                    or isinstance(item["output_bytes"], bool)
                    or not isinstance(item["output_bytes"], int)
                    or item["output_bytes"] < 0
                ):
                    raise ValueError("model grader command item is invalid")
            else:
                if (
                    item["status"] is not None and not isinstance(item["status"], str)
                ) or (
                    item["exit_code"] is not None
                    and (
                        isinstance(item["exit_code"], bool)
                        or not isinstance(item["exit_code"], int)
                    )
                ):
                    raise ValueError("partial command evidence is invalid")
                if value["complete"]:
                    raise ValueError("complete command trace contains partial evidence")
        else:
            if (
                set(item) != base | {"changes"}
                or not isinstance(item["changes"], list)
                or value["complete"]
                and not item["changes"]
            ):
                raise ValueError("model grader file-change item differs")
            for change in item["changes"]:
                if not isinstance(change, dict):
                    raise ValueError("model grader file change is invalid")
                expected = (
                    {"path", "action", "destination"}
                    if change.get("action") == "rename"
                    else {"path", "action"}
                )
                if (
                    set(change) != expected
                    or change.get("action")
                    not in {"create", "modify", "delete", "rename"}
                    or not _valid_relative_path(change.get("path"))
                    or (
                        change.get("action") == "rename"
                        and not _valid_relative_path(change.get("destination"))
                    )
                ):
                    raise ValueError("model grader file change is invalid")
    if abandoned_ids:
        if (
            lifecycle is None
            or value["complete"]
            or value["overflow"]
            or lifecycle.get("branch") != "outcome_bearing_abandoned"
            or abandoned_ids != lifecycle.get("unknown_completion")
        ):
            raise ValueError("model grader abandoned command lifecycle differs")
    elif lifecycle is not None:
        raise ValueError("model grader command trace lacks lifecycle items")
    if not _canonical_payload(value, payload):
        raise ValueError("model grader command trace is not canonical")
    return value


def _turn_answers(
    payload: str,
    assessment: dict[str, Any],
    fixture_paths: list[str],
) -> list[dict[str, str]]:
    """Validate and blind the ordered semantic output from every turn."""
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("model grader turn answers are invalid JSON") from exc
    items = value.get("items") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "items"}
        or value.get("schema_version") != "codex-turn-answers/1"
        or not isinstance(items, list)
        or len(items) != len(assessment["turn_ids"])
    ):
        raise ValueError("model grader turn answers differ")
    answers = []
    for turn_id, item in zip(assessment["turn_ids"], items, strict=True):
        if (
            not isinstance(item, dict)
            or set(item) != {"turn_id", "content"}
            or item.get("turn_id") != turn_id
            or not isinstance(item.get("content"), str)
            or len(item["content"].encode("utf-8")) > 64 * 1024
        ):
            raise ValueError("model grader turn answer is invalid")
        answers.append(
            {
                "turn_id": turn_id,
                "content": _redact_workspace_paths(
                    item["content"],
                    assessment,
                    fixture_paths,
                ),
            }
        )
    if not _canonical_payload(value, payload):
        raise ValueError("model grader turn answers are not canonical")
    return answers


def _semantic_files(
    workspace: dict[str, Any],
    assessment: dict[str, Any],
    fixture_paths: list[str],
) -> list[dict[str, str]]:
    """Expose each readable source/final file once, without trace duplication."""
    initial = {item["path"]: item for item in workspace["initial"]}
    final = {item["path"]: item for item in workspace["final"]}
    selected: list[tuple[str, str, dict[str, Any]]] = []
    selected.extend(
        ("task_fixture", path, initial[path])
        for path in fixture_paths
        if path in initial
    )
    selected.extend(
        ("final_workspace", path, final[path])
        for path in assessment["changed_paths"]
        if path in final
    )
    result = []
    for role, path, record in selected:
        if record["encoding"] != "utf-8" or record["truncated"]:
            continue
        result.append(
            {
                "role": role,
                "path": path,
                "content": _redact_workspace_paths(
                    record["content"],
                    assessment,
                    fixture_paths,
                ),
            }
        )
    return result


def execution_item(entry, result, *, grader, item_id, findings, paths):
    """Expose task outputs and oracle findings without treatment or model identity."""
    case = entry["execute_case_payload"]["case"]
    selected = {
        r["check_id"]
        for r in case["requirements"]
        if r["grader_id"] == grader["grader_id"]
    }
    evidence = {
        label: paths[path].read_text(encoding="utf-8")
        for label, path in EVIDENCE_PATHS.items()
    }
    assessment = _host_observation(evidence["host-observation"])
    if assessment["terminal_status"] != result["terminal_status"]:
        raise ValueError("model grader host terminal binding differs")
    workspace = _workspace_evidence(evidence["workspace-evidence"], assessment)
    trace = _command_trace(evidence["command-trace"], assessment)
    fixture_paths = [item["path"] for item in case["fixture"]["initial_files"]]
    answers = _turn_answers(evidence["turn-answers"], assessment, fixture_paths)
    final = _redact_workspace_paths(evidence["final-answer"], assessment, fixture_paths)
    abandoned = assessment["_lifecycle"] is not None
    if (
        not _semantic_workspace_complete(workspace, assessment)
        or not trace["complete"]
        and not abandoned
    ):
        raise ValueError("model grader evidence is incomplete")
    if not answers or answers[-1]["content"].strip() != final.strip():
        raise ValueError("model grader final answer differs from its last turn")
    if abandoned:
        findings = [
            *findings,
            {
                "check_id": "process-check",
                "pass": False,
                "observations": [
                    "command completion, exit code, and output remain unknown"
                ],
            },
        ]
    return {
        "item_id": item_id,
        "checks": [
            {"id": check["check_id"], "pass_condition": check["pass_condition"]}
            for check in grader["checks"]
            if check["check_id"] in selected
        ],
        "grader_view": {
            "task_evidence": {
                "request_text": "\n\n".join(
                    turn["input"]["content"] for turn in case["turns"]
                ),
                "tags": case["tags"],
            },
            "captured_output": {
                field: result[field]
                for field in ("terminal_status", "refusal", "timeout")
            },
            "deterministic_findings": findings,
            "turn_answers": answers,
            "semantic_files": _semantic_files(workspace, assessment, fixture_paths),
        },
    }


def judgment_checks(output, batch):
    """Check a provider response once and return its per-item boolean outcomes."""
    if (
        not isinstance(output, dict)
        or set(output) != {"batch_id", "items"}
        or output["batch_id"] != batch["batch_id"]
    ):
        raise ValueError("model grader judgment differs from the bound batch")
    items = output["items"]
    expected = {
        item["item_id"]: {check["id"] for check in item["checks"]}
        for item in batch["items"]
    }
    if not isinstance(items, list) or len(items) != len(expected):
        raise ValueError("model grader judgment item count differs")
    outcomes = {}
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != {"item_id", "checks"}
            or item["item_id"] not in expected
            or item["item_id"] in outcomes
        ):
            raise ValueError("model grader judgment item identity differs")
        checks = item["checks"]
        if not isinstance(checks, list) or len(checks) != len(
            expected[item["item_id"]]
        ):
            raise ValueError("model grader judgment check count differs")
        values = {}
        for check in checks:
            if (
                not isinstance(check, dict)
                or set(check) != {"id", "pass", "notes", "uncertainty"}
                or check["id"] not in expected[item["item_id"]]
                or check["id"] in values
                or type(check["pass"]) is not bool
                or not isinstance(check["notes"], str)
                or check["uncertainty"] not in UNCERTAINTY
            ):
                raise ValueError("model grader judgment check differs")
            values[check["id"]] = check["pass"]
        outcomes[item["item_id"]] = values
    return outcomes
