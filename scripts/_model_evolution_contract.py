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
from typing import Any
from urllib.parse import urljoin

import jsonschema
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource, Unresolvable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPOSITORY_ROOT / "evaluation/model-evolution/schemas"
SCHEMA_FILES = {
    "budget_approval": "budget-approval-v2.schema.json",
    "calibration_rejection_receipt": "calibration-rejection-receipt-v2.schema.json",
    "campaign": "campaign-v3.schema.json",
    "failure_receipt": "failure-receipt-v2.schema.json",
    "interaction_probes": "interaction-probes-v2.schema.json",
    "sentinel_index": "sentinel-index-v2.schema.json",
    "qualification": "qualification-v3.schema.json",
}
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SKILL_IDS = (
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
)
DECISION_AXES = (
    "task_behavior",
    "protected_safety",
    "routing",
    "operational_cost",
    "loop_pathology",
    "apparatus",
    "manual_authority",
)
GATE_RESULT_FIELDS = (
    "gate_id", "decision_axis", "kind", "metric", "direction", "threshold",
    "required",
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
        result.get("record_type") != "skill-evaluator-host-result/2"
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
    request_id = envelope.get("request_id")
    if (
        not isinstance(entry_id, str)
        or not SAFE_ID.fullmatch(entry_id)
        or not isinstance(request_id, str)
        or not SAFE_ID.fullmatch(request_id)
    ):
        raise ContractError("Host request identity is invalid")
    return {
        "entry_ordinal": ordinal,
        "entry_id": entry_id,
        "request_id": request_id,
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


def validate_document(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} document must be an object")
    validate_schema(value, name)
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


def _resolve_owned_path(binding: dict[str, Any], root: Path) -> Path:
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise ContractError("artifact binding root is unavailable") from exc
    relative = _relative_path(binding["path"])
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractError(
            f"bound artifact is missing or symlinked: {binding['path']}"
        )
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ContractError("bound artifact escapes its declared root")
    return resolved


def _artifact_schema_version(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        value = load_json(path, label=path.name)
        version = value.get("schema_version") if isinstance(value, dict) else None
        return str(version) if version is not None else "json/1"
    if suffix == ".jsonl":
        rows = [line for line in path.read_bytes().splitlines() if line.strip()]
        if rows:
            value = strict_json_bytes(rows[0], label=path.name)
            version = value.get("schema_version") if isinstance(value, dict) else None
            if version is not None:
                return f"jsonl/{version}"
        return "jsonl/1"
    if suffix in {".md", ".txt", ".log"}:
        path.read_text(encoding="utf-8")
        return "text/utf-8"
    return "bytes/1"


def resolve_repository_ref(
    binding: dict[str, Any], repository_root: Path,
) -> Path:
    if set(binding) != {"root", "path"} or binding.get("root") != "repository":
        raise ContractError("repository binding shape is invalid")
    return _resolve_owned_path(binding, repository_root)


def resolve_campaign_ref(binding: dict[str, Any], campaign_root: Path) -> Path:
    if (
        set(binding) != {"root", "path", "schema_version"}
        or binding.get("root") != "campaign"
        or not isinstance(binding.get("schema_version"), str)
    ):
        raise ContractError("campaign binding shape is invalid")
    resolved = _resolve_owned_path(binding, campaign_root)
    if _artifact_schema_version(resolved) != binding["schema_version"]:
        raise ContractError(f"campaign artifact schema differs: {binding['path']}")
    return resolved


def resolve_external_binding(binding: dict[str, Any], campaign_root: Path) -> Path:
    if (
        set(binding) != {"root", "path", "digest", "schema_version"}
        or binding.get("root") != "external"
        or not HASH.fullmatch(str(binding.get("digest")))
        or not isinstance(binding.get("schema_version"), str)
    ):
        raise ContractError("external binding shape is invalid")
    resolved = _resolve_owned_path(binding, campaign_root)
    if content_hash(resolved.read_bytes()) != binding["digest"]:
        raise ContractError(f"external artifact digest differs: {binding['path']}")
    return resolved


def resolve_binding(
    binding: dict[str, Any], repository_root: Path, campaign_root: Path,
) -> Path:
    root = binding.get("root") if isinstance(binding, dict) else None
    if root == "repository":
        return resolve_repository_ref(binding, repository_root)
    if root == "campaign":
        return resolve_campaign_ref(binding, campaign_root)
    if root == "external":
        return resolve_external_binding(binding, campaign_root)
    raise ContractError("artifact binding root is invalid")


def make_binding(
    path: Path,
    *,
    root: str,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, str]:
    roots = {
        "repository": repository_root,
        "campaign": campaign_root,
        "external": campaign_root,
    }
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
    if root == "repository":
        return {"root": root, "path": relative}
    binding = {
        "root": root,
        "path": relative,
        "schema_version": _artifact_schema_version(resolved),
    }
    if root == "external":
        binding["digest"] = content_hash(resolved.read_bytes())
    return binding


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


_CATEGORICAL_GATE_STATUSES = {
    "manual": {"approve": "pass", "hold": "fail", "reject": "fail"},
    "quality": {"pass": "pass", "fail": "fail"},
    "calibration": {"pass": "pass", "fail": "fail", "expired": "fail"},
    "host": {"feasible": "pass", "unsupported": "fail"},
}


def _replay_gate_status(gate: dict[str, Any]) -> str:
    observed = gate["observed"]
    if observed is None:
        return "not_evaluable"
    kind = gate["kind"]
    if kind in _CATEGORICAL_GATE_STATUSES:
        return _CATEGORICAL_GATE_STATUSES[kind].get(observed, "not_evaluable")
    direction = gate["direction"]
    threshold = gate["threshold"]
    if direction == "present":
        return "pass"
    if direction == "equal":
        return "pass" if observed == threshold else "fail"
    if (
        not isinstance(observed, (int, float))
        or isinstance(observed, bool)
        or not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
    ):
        return "not_evaluable"
    if direction == "at_least":
        return "pass" if observed >= threshold else "fail"
    if direction == "at_most":
        return "pass" if observed <= threshold else "fail"
    return "not_evaluable"


def _summary_axes(
    value: dict[str, Any],
    *,
    kind: str,
    expected_gates: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    _validate_external_schema(
        value,
        REPOSITORY_ROOT / "skill-evaluator/schemas/analysis-summary-v6.schema.json",
        kind,
    )
    gate_results = value["gate_results"]
    gate_ids = [item["gate_id"] for item in gate_results]
    if len(gate_ids) != len(set(gate_ids)):
        raise ContractError(f"{kind} gate results contain duplicate IDs")
    if expected_gates is not None and [
        {field: item[field] for field in GATE_RESULT_FIELDS}
        for item in gate_results
    ] != [
        {field: item[field] for field in GATE_RESULT_FIELDS}
        for item in expected_gates
    ]:
        raise ContractError(f"{kind} gate results differ from the frozen spec")
    for item in gate_results:
        if item["status"] != _replay_gate_status(item):
            raise ContractError(f"{kind} gate {item['gate_id']} status replay differs")
    evidence_observed = (
        value["evidence_status"] == "complete"
        and value["feasibility_status"] == "feasible"
    )
    axes: dict[str, str] = {}
    for axis in DECISION_AXES:
        required = [
            item for item in gate_results
            if item["required"] is True and item["decision_axis"] == axis
        ]
        if not required:
            axes[axis] = "not_applicable"
        elif not evidence_observed:
            axes[axis] = "unobserved"
        elif any(item["status"] == "fail" for item in required):
            axes[axis] = "blocked"
        elif any(item["status"] == "not_evaluable" for item in required):
            axes[axis] = "unobserved"
        else:
            axes[axis] = "pass"
    if axes["task_behavior"] == "pass" and value["baseline_ceiling"] is True:
        axes["task_behavior"] = "limited_native_absorption"
    return axes


def evaluator_summary_axes(
    path: Path,
    *,
    kind: str,
    expected_gates: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    value = load_json(path, label=f"{kind} evidence")
    if not isinstance(value, dict):
        raise ContractError(f"{kind} evidence must be an object")
    return _summary_axes(value, kind=kind, expected_gates=expected_gates)


def evaluator_evidence_status(
    path: Path,
    *,
    kind: str,
    expected_gates: list[dict[str, Any]] | None = None,
) -> str:
    value = load_json(path, label=f"{kind} evidence")
    if not isinstance(value, dict):
        raise ContractError(f"{kind} evidence must be an object")
    if kind in {"current_summary", "candidate_summary", "holdout_summary"}:
        statuses = set(
            _summary_axes(value, kind=kind, expected_gates=expected_gates).values()
        )
        if "blocked" in statuses:
            return "blocked"
        if "unobserved" in statuses:
            return "unobserved"
        if "limited_native_absorption" in statuses:
            return "limited_native_absorption"
        return "pass"
    if kind in {"transition_report", "revision_report"}:
        _validate_external_schema(
            value,
            REPOSITORY_ROOT
            / "skill-evaluator/schemas/comparison-report-v3.schema.json",
            kind,
        )
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
        return "pass" if result.get("classification") == "retained_specialized_value" else "blocked"
    if kind == "grader_calibration":
        _validate_external_schema(
            value,
            REPOSITORY_ROOT
            / "skill-evaluator/schemas/grader-calibration-v3.schema.json",
            kind,
        )
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
