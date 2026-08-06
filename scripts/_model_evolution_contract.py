#!/usr/bin/env python3
"""Shared model-evolution schemas, hashing, and artifact bindings."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re
from typing import Any, Callable
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution/schemas"
SCHEMA_FILES = {
    "budget_approval": "budget-approval-v1.schema.json",
    "calibration_rejection_receipt": "calibration-rejection-receipt-v1.schema.json",
    "campaign": "campaign-v2.schema.json",
    "failure_receipt": "failure-receipt-v1.schema.json",
    "interaction_probes": "interaction-probes-v1.schema.json",
    "sentinel_index": "sentinel-index-v1.schema.json",
    "qualification": "qualification-v1.schema.json",
}
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SKILL_IDS = (
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
)
BUDGET_FIELDS = (
    "provider_requests",
    "execute",
    "model_grade",
    "reviewer",
    "optimizer",
    "download_bytes",
    "artifact_bytes",
    "candidates",
)
HOST_CLEANUP_GRACE_SECONDS = 30
HASH_FIELDS = {
    "model-evolution-budget-approval/1": "approval_hash",
    "model-evolution-calibration-rejection-receipt/1": (
        "calibration_rejection_receipt_hash"
    ),
    "model-evolution-campaign/2": "campaign_hash",
    "model-evolution-failure-receipt/1": "failure_receipt_hash",
    "model-evolution-interaction-probes/1": "probe_set_hash",
    "model-evolution-sentinel-index/1": "sentinel_hash",
    "model-qualification/1": "qualification_hash",
}


class ContractError(ValueError):
    """A deterministic contract or binding failure."""


def formal_entry_timeout_floor(
    host: dict[str, Any], *, turn_count: int = 1,
) -> int:
    """Return the outer timeout for bounded per-turn Host executions."""
    if (
        not isinstance(turn_count, int)
        or isinstance(turn_count, bool)
        or turn_count < 1
    ):
        raise ContractError("formal turn count is invalid")
    command = host.get("command")
    argv = command.get("argv") if isinstance(command, dict) else None
    positions = [
        index for index, value in enumerate(argv or []) if value == "--timeout"
    ]
    if len(positions) != 1 or positions[0] + 1 >= len(argv or []):
        raise ContractError("formal Host command lacks one timeout binding")
    try:
        host_timeout = float(argv[positions[0] + 1])
    except (TypeError, ValueError) as exc:
        raise ContractError("formal Host timeout is invalid") from exc
    if not math.isfinite(host_timeout) or host_timeout <= 0:
        raise ContractError("formal Host timeout is invalid")
    return math.ceil(host_timeout) * turn_count + HOST_CLEANUP_GRACE_SECONDS


def validate_formal_timeout_inputs(
    host: dict[str, Any], spec: dict[str, Any], scenarios: list[dict[str, Any]]
) -> int:
    """Reject sentinel inputs that cannot outlive their frozen Host."""
    execution = spec.get("execution")
    execution_timeout = (
        execution.get("timeout_seconds") if isinstance(execution, dict) else None
    )
    scenario_timeouts = []
    scenario_floors = []
    for row in scenarios:
        timeout = row.get("timeout_seconds") if isinstance(row, dict) else None
        turns = row.get("turns") if isinstance(row, dict) else None
        turn_count = len(turns) if isinstance(turns, list) and turns else 1
        scenario_timeouts.append(timeout)
        scenario_floors.append(
            formal_entry_timeout_floor(host, turn_count=turn_count)
        )
    floor = max(scenario_floors, default=formal_entry_timeout_floor(host))
    if (
        not isinstance(execution_timeout, int)
        or isinstance(execution_timeout, bool)
        or execution_timeout < floor
        or not scenarios
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < required
            for value, required in zip(
                scenario_timeouts, scenario_floors, strict=True,
            )
        )
        or any(value > execution_timeout for value in scenario_timeouts)
    ):
        raise ContractError(
            f"formal execution and scenario timeouts must be at least {floor} seconds"
        )
    return floor


def validate_formal_plan_timeouts(
    host: dict[str, Any], plan: dict[str, Any]
) -> int:
    """Reject compiled entries that cannot outlive their frozen Host."""
    entries = plan.get("entries")
    execute_entries = [
        entry for entry in entries or []
        if not isinstance(entry, dict) or entry.get("disposition") == "execute"
    ] if isinstance(entries, list) else []
    floors = []
    for entry in execute_entries:
        payload = (
            entry.get("execute_case_payload")
            if isinstance(entry, dict)
            else None
        )
        turns = payload.get("turns") if isinstance(payload, dict) else None
        turn_count = len(turns) if isinstance(turns, list) and turns else 1
        floors.append(formal_entry_timeout_floor(host, turn_count=turn_count))
    floor = max(floors, default=formal_entry_timeout_floor(host))
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("timeout_seconds"), int)
        or isinstance(entry.get("timeout_seconds"), bool)
        or entry["timeout_seconds"] < required
        for entry, required in zip(execute_entries, floors, strict=True)
    ):
        raise ContractError(
            f"formal execute entry timeouts must be at least {floor} seconds"
        )
    return floor


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def self_hash(value: dict[str, Any], field: str) -> str:
    return content_hash(
        canonical_bytes({key: item for key, item in value.items() if key != field})
    )


def with_self_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(value)
    result[field] = self_hash(result, field)
    return result


def strict_json_bytes(raw: bytes, *, label: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ContractError(f"{label} contains non-finite number {value}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=no_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not strict UTF-8 JSON") from exc


def load_json(path: Path, *, label: str | None = None) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label or path.name} must be a regular non-symlink file")
    return strict_json_bytes(path.read_bytes(), label=label or path.name)


def load_jsonl(path: Path, *, label: str) -> list[Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} must be a regular non-symlink file")
    rows = [
        strict_json_bytes(line, label=f"{label} row {index}")
        for index, line in enumerate(path.read_bytes().splitlines(), start=1)
        if line.strip()
    ]
    if not rows:
        raise ContractError(f"{label} must not be empty")
    return rows


def pre_turn_failure_identity(path: Path, ordinal: int) -> dict[str, Any]:
    """Validate one raw Host terminal that failed before a completed model turn."""
    if path.is_symlink() or not path.is_file():
        raise ContractError("Host result must be a regular non-symlink file")
    lines = [line for line in path.read_bytes().splitlines() if line.strip()]
    if len(lines) != 1:
        raise ContractError("Host result must contain one record")
    result = strict_json_bytes(lines[0], label="Host result")
    if not isinstance(result, dict):
        raise ContractError("Host result must be an object")
    envelope = result.get("envelope")
    usage = result.get("usage")
    context = result.get("context")
    cleanup = result.get("cleanup")
    terminal_status = result.get("terminal_status")
    failure_class = result.get("failure_class")
    expected_failure = {
        "timeout": "model_task_timeout",
        "failed": "provider_nonretryable",
    }
    if (
        result.get("record_type") != "skill-evaluator-host-result/1"
        or not isinstance(envelope, dict)
        or envelope.get("entry_ordinal") != ordinal
        or envelope.get("request_kind") != "model_grade"
        or result.get("terminal") is not True
        or expected_failure.get(terminal_status) != failure_class
        or not isinstance(usage, dict)
        or usage.get("records") != []
        or not isinstance(context, dict)
        or context.get("bytes") != 0
        or not isinstance(cleanup, dict)
        or cleanup.get("status") != "clean"
        or any(
            result.get(field) != []
            for field in (
                "actions",
                "artifacts",
                "assertions",
                "handoffs",
                "principals",
                "state",
            )
        )
    ):
        raise ContractError("Host result is not a clean pre-turn terminal failure")
    entry_id = envelope.get("entry_id")
    request_hash = result.get("request_hash")
    if (
        not isinstance(entry_id, str)
        or not SAFE_ID.fullmatch(entry_id)
        or not isinstance(request_hash, str)
        or not HASH.fullmatch(request_hash)
    ):
        raise ContractError("Host request identity is invalid")
    return {
        "entry_ordinal": ordinal,
        "entry_id": entry_id,
        "request_hash": request_hash,
        "terminal_status": terminal_status,
        "failure_class": failure_class,
    }


def _schema(name: str) -> dict[str, Any]:
    try:
        path = SCHEMA_ROOT / SCHEMA_FILES[name]
    except KeyError as exc:
        raise ContractError(f"unknown schema {name!r}") from exc
    value = load_json(path, label=f"{name} schema")
    if not isinstance(value, dict):
        raise ContractError(f"{name} schema is not an object")
    return value


def validate_schema(value: Any, name: str) -> None:
    try:
        jsonschema.Draft202012Validator(
            _schema(name), format_checker=jsonschema.FormatChecker()
        ).validate(value)
    except jsonschema.ValidationError as exc:
        location = "/" + "/".join(str(item) for item in exc.absolute_path)
        raise ContractError(
            f"{name} schema violation at {location}: {exc.message}"
        ) from exc


def verify_self_hash(value: dict[str, Any], field: str) -> None:
    claimed = value.get(field)
    if not isinstance(claimed, str) or claimed != self_hash(value, field):
        raise ContractError(f"{field} differs from canonical content")


def validate_document(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} document must be an object")
    validate_schema(value, name)
    schema_version = value.get("schema_version")
    field = HASH_FIELDS.get(schema_version)
    if field is None:
        raise ContractError(f"{name} schema version has no hash owner")
    verify_self_hash(value, field)
    if name == "interaction_probes":
        probe_ids = [probe["probe_id"] for probe in value["probes"]]
        if len(probe_ids) != len(set(probe_ids)):
            raise ContractError("interaction probe IDs must be unique")
        capabilities = [probe["capability"] for probe in value["probes"]]
        if len(capabilities) != len(set(capabilities)):
            raise ContractError("interaction probe capabilities must be unique")
    return value


def _relative_path(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path or "://" in path or "\\" in path:
        raise ContractError("artifact path must be a normalized relative POSIX path")
    relative = PurePosixPath(path)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ContractError("artifact path escapes its declared root")
    if relative.as_posix() != path:
        raise ContractError("artifact path is not normalized")
    return relative


def resolve_binding(
    binding: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
) -> Path:
    if set(binding) != {"root", "path", "sha256"} or not HASH.fullmatch(
        str(binding.get("sha256"))
    ):
        raise ContractError("artifact binding shape is invalid")
    roots = {"repository": repository_root, "campaign": campaign_root}
    try:
        root = roots[binding["root"]].resolve(strict=True)
    except (KeyError, OSError) as exc:
        raise ContractError("artifact binding root is invalid") from exc
    relative = _relative_path(binding["path"])
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(
            f"bound artifact is missing or symlinked: {binding['path']}"
        )
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ContractError("bound artifact escapes its declared root")
    if content_hash(resolved.read_bytes()) != binding["sha256"]:
        raise ContractError(f"bound artifact hash differs: {binding['path']}")
    return resolved


def make_binding(
    path: Path,
    *,
    root: str,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, str]:
    roots = {"repository": repository_root, "campaign": campaign_root}
    if root not in roots:
        raise ContractError("artifact binding root is invalid")
    base = roots[root].resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ContractError(
            "artifact binding target must be a regular non-symlink file"
        )
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(base):
        raise ContractError("artifact is outside its declared root")
    relative = resolved.relative_to(base).as_posix()
    _relative_path(relative)
    return {
        "root": root,
        "path": relative,
        "sha256": content_hash(resolved.read_bytes()),
    }


def validate_all_bindings(
    value: Any,
    repository_root: Path,
    campaign_root: Path,
    repository_fallback: Callable[[str, str], bool] | None = None,
) -> None:
    if isinstance(value, dict):
        if set(value) == {"root", "path", "sha256"}:
            if value["root"] == "repository" and repository_fallback is not None:
                if not HASH.fullmatch(str(value["sha256"])):
                    raise ContractError("artifact binding shape is invalid")
                relative = _relative_path(value["path"])
                candidate = repository_root.joinpath(*relative.parts)
                if candidate.is_symlink() or not candidate.resolve(
                    strict=False
                ).is_relative_to(repository_root.resolve(strict=True)):
                    raise ContractError(
                        f"bound artifact is symlinked or escapes: {value['path']}"
                    )
                try:
                    resolve_binding(value, repository_root, campaign_root)
                except ContractError:
                    if not repository_fallback(value["path"], value["sha256"]):
                        raise
            else:
                resolve_binding(value, repository_root, campaign_root)
            return
        for item in value.values():
            validate_all_bindings(
                item,
                repository_root,
                campaign_root,
                repository_fallback,
            )
    elif isinstance(value, list):
        for item in value:
            validate_all_bindings(
                item,
                repository_root,
                campaign_root,
                repository_fallback,
            )


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError("timestamp must be UTC and end in Z")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ContractError("timestamp is not ISO-8601 UTC") from exc


@lru_cache(maxsize=1)
def _external_schema_store() -> dict[str, dict[str, Any]]:
    root = REPOSITORY_ROOT / "skill-evaluator/schemas"
    store: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        value = load_json(path, label=f"evaluator schema {path.name}")
        if not isinstance(value, dict) or not isinstance(value.get("$id"), str):
            raise ContractError(f"evaluator schema lacks local $id: {path.name}")
        store[value["$id"]] = value
        store[path.name] = value
    return store


def _no_remote_schema(uri: str) -> Resource:
    raise NoSuchResource(ref=uri)


def _validate_external_schema(
    value: dict[str, Any], schema_path: Path, label: str
) -> None:
    schema = load_json(schema_path, label=f"{label} schema")
    store = _external_schema_store()
    base = schema.get("$id", "")
    for name, item in list(store.items()):
        if "://" not in name:
            store[urljoin(base, name)] = item
    registry = Registry(retrieve=_no_remote_schema).with_resources(
        (uri, Resource.from_contents(item))
        for uri, item in store.items()
        if "://" in uri
    )
    try:
        jsonschema.Draft202012Validator(schema, registry=registry).validate(value)
    except jsonschema.ValidationError as exc:
        location = "/" + "/".join(str(item) for item in exc.absolute_path)
        raise ContractError(f"{label} violation at {location}: {exc.message}") from exc
    except Unresolvable as exc:
        raise ContractError(
            f"{label} has an unresolved local schema reference"
        ) from exc


def evaluator_evidence_status(path: Path, *, kind: str) -> str:
    value = load_json(path, label=f"{kind} evidence")
    if not isinstance(value, dict):
        raise ContractError(f"{kind} evidence must be an object")
    if kind in {"current_summary", "candidate_summary", "holdout_summary"}:
        _validate_external_schema(
            value,
            REPOSITORY_ROOT / "skill-evaluator/schemas/analysis-summary-v4.schema.json",
            kind,
        )
        verify_self_hash(value, "summary_hash")
        if (
            value["evidence_status"] != "complete"
            or value["final_authority_status"] != "eligible"
        ):
            return "blocked"
        return "pass" if value["usefulness_status"] == "supported" else "limited"
    if kind in {"transition_report", "revision_report"}:
        _validate_external_schema(
            value,
            REPOSITORY_ROOT
            / "skill-evaluator/schemas/comparison-report-v1.schema.json",
            kind,
        )
        verify_self_hash(value, "comparison_report_hash")
        if value["authority_eligibility"] != "eligible":
            return "blocked"
        result = value["result"]
        if kind == "revision_report":
            return (
                "pass"
                if result.get("kind") == "revision" and result.get("status") == "closed"
                else "blocked"
            )
        if result.get("kind") != "model_transition":
            return "blocked"
        return (
            "pass"
            if result.get("classification") == "retained_specialized_value"
            else "limited"
        )
    if kind == "grader_calibration":
        _validate_external_schema(
            value,
            REPOSITORY_ROOT
            / "skill-evaluator/schemas/grader-calibration-v2.schema.json",
            kind,
        )
        verify_self_hash(value, "calibration_hash")
        return "pass"
    raise ContractError(f"unsupported evaluator evidence kind {kind!r}")


def validate_bundle_build(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("plugin build must be a JSON object")
    schema = load_json(
        REPOSITORY_ROOT / "bundle/frontier-engineering-bundle.schema.json",
        label="Bundle build schema",
    )
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as exc:
        location = "/" + "/".join(str(item) for item in exc.absolute_path)
        raise ContractError(
            f"plugin build schema violation at {location}: {exc.message}"
        ) from exc
    unsigned = {key: item for key, item in value.items() if key != "release_build_id"}
    expected = "build-" + sha256(canonical_bytes(unsigned)).hexdigest()[:24]
    if value["release_build_id"] != expected:
        raise ContractError(
            "plugin build release_build_id differs from canonical content"
        )
    if set(value["skills"]) != set(SKILL_IDS):
        raise ContractError("plugin build does not contain exact four Skill identities")
    return value
