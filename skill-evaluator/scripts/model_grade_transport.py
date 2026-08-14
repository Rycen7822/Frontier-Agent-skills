"""Build and validate the blinded execution model-grader transport."""

from __future__ import annotations

import copy
from hashlib import sha256
import json
import re
from typing import Any, Callable

from grader_semantics import semantic_payload_hash


BLINDED_FIELDS = {
    "case_id", "repeat", "requirements", "captured_output",
    "artifacts", "observations",
}
UNCERTAINTY = {"none", "low", "medium", "high"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
CONTEXT_FIELDS = {
    "controlled_bytes": "controlled_bytes",
    "controlled_core_bytes": "controlled_core_bytes",
    "total_bytes": "bytes",
    "unique_reference_bytes": "unique_reference_bytes",
}
LOCAL_PATH_PLACEHOLDER = "local-path-redacted"
UNBOUND_LOCAL_PATH = re.compile(
    r"(?<![:/\\A-Za-z0-9])"
    r"(?:[A-Za-z]:[\\/](?:Users|workspace|workspaces)|/"
    r"(?:home|private|tmp|opt|Users|workspace|workspaces))"
    r"(?:[\\/][^\s`'\"<>()\[\]{},;!?，。；！？]*)?"
    r"(?=$|[\s`'\"<>()\[\]{},;.!?，。；！？])"
)
MAX_BATCH_ITEMS = 6
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


def batch_identity(
    evaluation_id: str,
    case_id: str,
    grader_id: str,
) -> str:
    """Return the shared batch identity for one case and model grader."""
    values = (evaluation_id, case_id, grader_id)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("model grader batch identity fields are invalid")
    identity = f"batch.{evaluation_id}.{case_id}.{grader_id}"
    if not SAFE_ID.fullmatch(identity):
        raise ValueError("model grader batch identity is not a safe ID")
    return identity


def execution_result(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return the sole task-execution result from a terminal receipt."""
    results = [
        result for result in receipt["host_protocol"]["results"]
        if result["envelope"]["request_kind"] == "execute_case"
    ]
    if len(results) != 1:
        raise ValueError("model grader batch member lacks one execution")
    return results[0]


def _task_evidence(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the case identity and user requests bound into execution."""
    payload = entry.get("execute_case_payload")
    turns = payload.get("turns") if isinstance(payload, dict) else None
    if not isinstance(turns, list):
        raise ValueError("model grader execution turns are invalid")
    messages = []
    for turn in turns:
        item = turn.get("input") if isinstance(turn, dict) else None
        if not isinstance(item, dict) or item.get("kind") != "user_message":
            continue
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("model grader user request is invalid")
        messages.append(content)
    if not messages:
        raise ValueError("model grader user request is missing")
    case = payload.get("case")
    case_id = case.get("case_id") if isinstance(case, dict) else None
    tags = case.get("tags") if isinstance(case, dict) else None
    if (
        not isinstance(case_id, str) or not case_id
        or not isinstance(tags, list)
        or not all(isinstance(tag, str) and tag for tag in tags)
    ):
        raise ValueError("model grader task identity is invalid")
    fixture = case.get("fixture")
    initial_files = (
        fixture.get("initial_files") if isinstance(fixture, dict) else None
    )
    if not isinstance(initial_files, list):
        raise ValueError("model grader fixture paths are invalid")
    fixture_paths = set()
    for item in initial_files:
        path = item.get("path") if isinstance(item, dict) else None
        if not _valid_relative_path(path):
            raise ValueError("model grader fixture path is invalid")
        parts = path.split("/")
        fixture_paths.update(
            "/".join(parts[:end]) for end in range(1, len(parts) + 1)
        )
    return {
        "case_id": case_id,
        "fixture_paths": sorted(fixture_paths, key=lambda path: (-len(path), path)),
        "request_text": "\n\n".join(messages),
        "tags": sorted(tags),
    }


def _deterministic_claims(result: dict[str, Any]) -> list[str]:
    """Return locally verified claims bound to declared result artifacts."""
    artifacts = result.get("artifacts")
    assertions = result.get("assertions")
    if not isinstance(artifacts, list) or not isinstance(assertions, list):
        raise ValueError("model grader deterministic evidence is invalid")
    claims = []
    for assertion in assertions:
        if (
            not isinstance(assertion, dict)
            or assertion.get("locally_verifiable") is not True
        ):
            continue
        claim = assertion.get("claim")
        if (
            not isinstance(claim, str)
            or not claim
            or assertion.get("artifact") not in artifacts
        ):
            raise ValueError("model grader deterministic claim is invalid")
        claims.append(claim)
    if not claims:
        raise ValueError("model grader deterministic claims are missing")
    return sorted(set(claims))


def _context_evidence(result: dict[str, Any]) -> dict[str, int]:
    """Return bounded context totals without exposing captured content."""
    context = result.get("context")
    if not isinstance(context, dict):
        raise ValueError("model grader context evidence is invalid")
    summary = {}
    for output_name, source_name in CONTEXT_FIELDS.items():
        value = context.get(source_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("model grader context total is invalid")
        summary[output_name] = value
    components = context.get("components")
    if not isinstance(components, list):
        raise ValueError("model grader context components are invalid")
    counts = {"body": 0, "reference": 0}
    for component in components:
        if not isinstance(component, dict):
            raise ValueError("model grader context component is invalid")
        kind = component.get("kind")
        if kind in counts:
            occurrence = component.get("occurrence", 1)
            if (
                isinstance(occurrence, bool)
                or not isinstance(occurrence, int)
                or occurrence < 1
            ):
                raise ValueError("model grader context occurrence is invalid")
            counts[kind] += occurrence
    summary["body_load_count"] = counts["body"]
    summary["reference_load_count"] = counts["reference"]
    return dict(sorted(summary.items()))


def _grader_observation(
    entry: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Build the typed evidence visible to the model grader."""
    return {
        "context_evidence": _context_evidence(result),
        "deterministic_claims": _deterministic_claims(result),
        "task_evidence": _task_evidence(entry),
    }


def blinded_execution(
    entry: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Project an execution result onto the declared blinded fields."""
    return {
        "case_id": entry["case_id"],
        "repeat": entry["repeat"],
        "requirements": copy.deepcopy(
            entry["execute_case_payload"]["case"]["requirements"],
        ),
        "captured_output": {
            field: copy.deepcopy(result[field])
            for field in (
                "terminal_status", "treatment_error", "refusal", "timeout",
            )
        },
        "artifacts": copy.deepcopy(result["artifacts"]),
        "observations": [_grader_observation(entry, result)],
    }


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
            (
                root
                for root in roots
                if path != root and path.startswith(root + "/")
            ),
            None,
        )
        suffix = path[len(ancestor):] if ancestor is not None else ""
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
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ) == payload


def _host_observation(payload: str) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("model grader host assessment is invalid JSON") from exc
    changed = value.get("changed_paths") if isinstance(value, dict) else None
    turns = value.get("turn_ids") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or set(value) != HOST_OBSERVATION_FIELDS
        or value.get("schema_version") != "codex-host-observation/1"
        or value.get("terminal_status") not in {"completed", "failed"}
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
    return value


def _file_records(value: Any) -> tuple[dict[str, dict[str, Any]], int]:
    if not isinstance(value, list) or len(value) > 128:
        raise ValueError("model grader workspace snapshot is invalid")
    records: dict[str, dict[str, Any]] = {}
    content_bytes = 0
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "path", "sha256", "bytes", "encoding", "content", "truncated",
        }:
            raise ValueError("model grader workspace file record differs")
        path = item["path"]
        raw = item["content"].encode("utf-8") if isinstance(item["content"], str) else None
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
            or (
                raw is None
                and (item["content"] is not None or not item["truncated"])
            )
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
            if before.get(path, {}).get("sha256")
            != after.get(path, {}).get("sha256")
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
        or value["complete"] and (value["overflow"] or truncated_change)
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
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "complete", "overflow", "items"}
        or value.get("schema_version") != "codex-command-trace/1"
        or not isinstance(value.get("complete"), bool)
        or not isinstance(value.get("overflow"), bool)
        or not isinstance(items, list)
        or len(items) > 256
        or value["complete"] != assessment["command_trace_complete"]
        or value["overflow"] != assessment["command_trace_overflow"]
        or value["complete"] and value["overflow"]
    ):
        raise ValueError("model grader command trace differs")
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
            full = base | {
                "status", "exit_code", "command_sha256", "command_preview",
                "output_sha256", "output_preview", "output_bytes",
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
                    (
                        item["status"] is not None
                        and not isinstance(item["status"], str)
                    )
                    or (
                        item["exit_code"] is not None
                        and (
                            isinstance(item["exit_code"], bool)
                            or not isinstance(item["exit_code"], int)
                        )
                    )
                ):
                    raise ValueError("partial command evidence is invalid")
                if value["complete"]:
                    raise ValueError("complete command trace contains partial evidence")
        else:
            if (
                set(item) != base | {"changes"}
                or not isinstance(item["changes"], list)
                or value["complete"] and not item["changes"]
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
                    or change.get("action") not in {"create", "modify", "delete", "rename"}
                    or not _valid_relative_path(change.get("path"))
                    or (
                        change.get("action") == "rename"
                        and not _valid_relative_path(change.get("destination"))
                    )
                ):
                    raise ValueError("model grader file change is invalid")
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
        answers.append({
            "turn_id": turn_id,
            "content": _redact_workspace_paths(
                item["content"], assessment, fixture_paths,
            ),
        })
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
        result.append({
            "role": role,
            "path": path,
            "content": _redact_workspace_paths(
                record["content"], assessment, fixture_paths,
            ),
        })
    return result


def deterministic_findings(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project locally bound deterministic results into semantic facts."""
    findings = []
    for output in outputs:
        checks = output.get("checks") if isinstance(output, dict) else None
        if (
            not isinstance(output, dict)
            or set(output) != {
                "overall_pass", "score", "checks", "missing_evidence",
                "grader_failure", "grader_failure_reason",
            }
            or output.get("grader_failure") is not False
            or output.get("grader_failure_reason") is not None
            or not isinstance(checks, list)
        ):
            raise ValueError("model grader deterministic output is invalid")
        for check in checks:
            evidence = check.get("evidence") if isinstance(check, dict) else None
            if (
                not isinstance(check, dict)
                or not isinstance(check.get("check_id"), str)
                or not isinstance(check.get("pass"), bool)
                or not isinstance(evidence, list)
            ):
                raise ValueError("model grader deterministic check is invalid")
            observations = []
            for item in evidence:
                observation = item.get("observation") if isinstance(item, dict) else None
                if isinstance(observation, str) and observation:
                    observations.append(_blind_unbound_local_paths(observation))
            findings.append({
                "check_id": check["check_id"],
                "pass": check["pass"],
                "observations": observations,
            })
    return findings


def execution_item(
    blinded: dict[str, Any],
    *,
    grader_id: str,
    grader_checks: list[dict[str, Any]],
    deterministic_findings: list[dict[str, Any]],
    entry_id: str,
    read_artifact: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """Project one execution receipt into a blinded batch item."""
    if not isinstance(blinded, dict) or set(blinded) != BLINDED_FIELDS:
        raise ValueError("model blinded projection fields are invalid")
    requirements = [
        item for item in blinded["requirements"]
        if isinstance(item, dict) and item.get("grader_id") == grader_id
    ]
    if not requirements:
        raise ValueError("model grader has no selected requirements")
    declarations = {
        check.get("check_id"): check
        for check in grader_checks
        if isinstance(check, dict)
    }
    requirement_ids = [item.get("check_id") for item in requirements]
    if (
        len(declarations) != len(grader_checks)
        or len(requirement_ids) != len(set(requirement_ids))
        or any(
            not isinstance(check_id, str)
            or not check_id
            or check_id not in declarations
            or not isinstance(declarations[check_id].get("pass_condition"), str)
            or not declarations[check_id]["pass_condition"].strip()
            or declarations[check_id].get("dimension")
            != requirement.get("dimension")
            or declarations[check_id].get("required")
            is not requirement.get("required")
            for check_id, requirement in zip(requirement_ids, requirements)
        )
    ):
        raise ValueError("model grader check declarations are invalid")
    evidence = {}
    for label, path in EVIDENCE_PATHS.items():
        matches = [
            item for item in blinded["artifacts"]
            if (
                isinstance(item, dict)
                and item.get("path") == path
                and item.get("encoding") == "utf-8"
            )
        ]
        if len(matches) != 1:
            raise ValueError(f"model grader {label} evidence is invalid")
        evidence[label] = read_artifact(matches[0])
    assessment = _host_observation(evidence["host-observation"])
    captured_output = blinded["captured_output"]
    if (
        not isinstance(captured_output, dict)
        or assessment["terminal_status"] != captured_output.get("terminal_status")
    ):
        raise ValueError("model grader host terminal binding differs")
    observations = blinded["observations"]
    if (
        not isinstance(observations, list)
        or len(observations) != 1
        or not isinstance(observations[0], dict)
        or set(observations[0]) != {
            "context_evidence",
            "deterministic_claims",
            "task_evidence",
        }
    ):
        raise ValueError("model grader typed evidence is invalid")
    workspace = _workspace_evidence(
        evidence["workspace-evidence"], assessment,
    )
    command_trace = _command_trace(evidence["command-trace"], assessment)
    task_evidence = observations[0]["task_evidence"]
    fixture_paths = task_evidence.get("fixture_paths", [])
    turn_answers = _turn_answers(
        evidence["turn-answers"], assessment, fixture_paths,
    )
    final_answer = _redact_workspace_paths(
        evidence["final-answer"], assessment, fixture_paths,
    )
    if (
        not command_trace["complete"]
        or not _semantic_workspace_complete(workspace, assessment)
    ):
        raise ValueError("model grader deterministic evidence is incomplete")
    if not turn_answers or turn_answers[-1]["content"].strip() != final_answer.strip():
        raise ValueError("model grader final answer differs from its last turn")
    grader_view = {
        "captured_output": captured_output,
        **copy.deepcopy(observations[0]),
        "deterministic_findings": copy.deepcopy(deterministic_findings),
        "turn_answers": turn_answers,
        "semantic_files": _semantic_files(
            workspace, assessment, fixture_paths,
        ),
    }
    checks = []
    for check_id in requirement_ids:
        pass_condition = declarations[check_id]["pass_condition"]
        checks.append({
            "id": check_id,
            "pass_condition": pass_condition,
        })
    return {
        "item_id": entry_id,
        "checks": checks,
        "grader_view": grader_view,
    }


def execution_batch(
    items: list[dict[str, Any]],
    *,
    batch_id: str,
) -> dict[str, Any]:
    """Bind multiple blinded execution items to one provider request."""
    item_ids = [
        item.get("item_id") for item in items if isinstance(item, dict)
    ]
    check_lists = [
        item.get("checks") for item in items if isinstance(item, dict)
    ]
    if (
        not isinstance(batch_id, str)
        or not batch_id
        or not items
        or len(items) > MAX_BATCH_ITEMS
        or len(item_ids) != len(items)
        or any(
            set(item) != {"item_id", "checks", "grader_view"}
            for item in items
        )
        or any(not isinstance(item_id, str) or not item_id for item_id in item_ids)
        or len(item_ids) != len(set(item_ids))
        or len(check_lists) != len(items)
        or any(
            not isinstance(checks, list)
            or not checks
            or any(
                not isinstance(check, dict)
                or set(check) != {"id", "pass_condition"}
                or not isinstance(check["id"], str)
                or not check["id"]
                or not isinstance(check["pass_condition"], str)
                or not check["pass_condition"].strip()
                for check in checks
            )
            or len({check["id"] for check in checks}) != len(checks)
            for checks in check_lists
        )
        or any(
            [
                (check["id"], check["pass_condition"])
                for check in checks
            ]
            != [
                (check["id"], check["pass_condition"])
                for check in check_lists[0]
            ]
            for checks in check_lists[1:]
        )
    ):
        raise ValueError("model grader batch items are invalid")
    return {"batch_id": batch_id, "items": items}


def request_payload(
    *,
    grader_id: str,
    batch: dict[str, Any],
    schedule_id: str,
    prompt_bytes: bytes,
    prompt_id: str,
    schema_id: str,
) -> dict[str, Any]:
    """Bind the declared grader instruction into one Host request."""
    try:
        prompt = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("model grader prompt is not UTF-8") from exc
    if (
        not isinstance(grader_id, str)
        or not grader_id
        or not isinstance(batch, dict)
        or not SAFE_ID.fullmatch(schedule_id)
        or not SAFE_ID.fullmatch(prompt_id)
        or not SAFE_ID.fullmatch(schema_id)
    ):
        raise ValueError("model grader request identity is invalid")
    return {
        "grader_id": grader_id,
        "schedule_id": schedule_id,
        "grader_prompt": prompt,
        "grader_prompt_id": prompt_id,
        "grader_schema_id": schema_id,
        "blinded_input": copy.deepcopy(batch),
    }


def calibration_item(label: dict[str, Any]) -> dict[str, Any]:
    """Project one blinded gold payload into the public grader batch shape."""
    payload = label.get("payload")
    if (
        not isinstance(payload, dict)
        or label.get("payload_digest") != semantic_payload_hash(payload)
        or label.get("check_id") != payload["check"]["check_id"]
    ):
        raise ValueError("calibration label semantic payload is invalid")
    return {
        "item_id": label["example_id"],
        "checks": [{
            "id": label["check_id"],
            "pass_condition": payload["check"]["pass_condition"],
        }],
        "grader_view": copy.deepcopy(payload["view"]),
    }


def calibration_projection(check: dict[str, Any]) -> tuple[str, int]:
    """Map the public raw check contract onto calibration label semantics."""
    if (
        not isinstance(check, dict)
        or set(check) != {"id", "pass", "notes", "uncertainty"}
        or not isinstance(check.get("pass"), bool)
        or not isinstance(check.get("notes"), str)
        or check.get("uncertainty") not in UNCERTAINTY
    ):
        raise ValueError("calibration judgment check is invalid")
    if check["uncertainty"] == "high":
        return "abstain", 0
    return ("pass", 0) if check["pass"] else ("fail", 1)


def normalize_judgment(
    output: Any,
    *,
    batch: dict[str, Any],
    requirements: list[dict[str, Any]],
    item_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate a batch judgment and normalize one bound item."""
    items = output.get("items") if isinstance(output, dict) else None
    expected_items = {
        item["item_id"]: [check["id"] for check in item["checks"]]
        for item in batch["items"]
    }
    observed_items = {
        item.get("item_id"): item
        for item in items or []
        if isinstance(item, dict)
    }
    if (
        not isinstance(output, dict) or not expected_items
        or set(output) != {"batch_id", "items"}
        or output["batch_id"] != batch["batch_id"]
        or not isinstance(items, list)
        or len(items) != len(expected_items)
        or set(observed_items) != set(expected_items)
        or any(set(item) != {"item_id", "checks"} for item in items)
    ):
        raise ValueError("model grader judgment differs from the bound batch")
    for observed_id, expected in expected_items.items():
        checks = observed_items[observed_id].get("checks")
        observed = [
            check.get("id") for check in checks if isinstance(check, dict)
        ] if isinstance(checks, list) else []
        if (
            set(observed) != set(expected)
            or len(observed) != len(expected)
            or len(observed) != len(set(observed))
            or any(
                set(check) != {"id", "pass", "notes", "uncertainty"}
                or not isinstance(check["pass"], bool)
                or not isinstance(check["notes"], str)
                or check["uncertainty"] not in UNCERTAINTY
                for check in checks or []
            )
        ):
            raise ValueError("model grader judgment differs from the bound batch")
    item = observed_items.get(item_id)
    if item is None:
        raise ValueError("model grader item is outside the bound batch")
    checks = item["checks"]
    required = {
        item["check_id"] for item in requirements if item["required"]
    }
    results = {check["id"]: check["pass"] for check in checks}
    score = (sum(results.values()) * 100 + len(checks) // 2) // len(checks)
    normalized = {
        "overall_pass": all(
            check["pass"] for check in checks if check["id"] in required
        ),
        "score": score,
        "checks": [{
            "check_id": check["id"],
            "pass": check["pass"],
            "evidence": [],
            "notes": check["notes"],
            "uncertainty": check["uncertainty"],
        } for check in checks],
        "missing_evidence": [],
        "grader_failure": False,
        "grader_failure_reason": None,
    }
    item_position = items.index(item)
    pointers = {
        check["id"]: f"/items/{item_position}/checks/{index}/pass"
        for index, check in enumerate(checks)
    }
    return normalized, pointers
