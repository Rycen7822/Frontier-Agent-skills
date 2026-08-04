#!/usr/bin/env python3
"""Closed contracts, artifact bindings, and qualification projection."""

from __future__ import annotations

import copy
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
    "campaign": "campaign-v1.schema.json",
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
GATE_IDS = (
    "apparatus",
    "identity_comparability",
    "critical_function",
    "safety_protected",
    "incremental_value",
    "revision",
    "context_cost",
    "statistical_support",
    "release_identity",
)
CRITICAL_PROBE_CAPABILITIES = {
    "force_load",
    "natural_routing",
    "action_authorization_trace",
}
HOST_CLEANUP_GRACE_SECONDS = 30
HASH_FIELDS = {
    "model-evolution-budget-approval/1": "approval_hash",
    "model-evolution-calibration-rejection-receipt/1": (
        "calibration_rejection_receipt_hash"
    ),
    "model-evolution-campaign/1": "campaign_hash",
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
    elif name == "campaign":
        has_apparatus = value["apparatus_report"] is not None
        if (value["phase"] == "declared" and has_apparatus) or (
            value["phase"] != "declared" and not has_apparatus
        ):
            raise ContractError("campaign phase and apparatus report differ")
        observed_host = value["profiles"]["target_observed"]
        requests = value["interaction_probes"]["requests"]
        results = value["interaction_probes"]["results"]
        if observed_host is not None and (
            not requests
            or results is None
            or any(request["status"] != "closed" for request in requests)
        ):
            raise ContractError("observed Host lacks a closed probe result set")
        if (
            value["phase"] not in {"declared", "apparatus_ready"}
            and observed_host is None
        ):
            raise ContractError("campaign phase requires an observed Host")
    elif name == "qualification":
        if [gate["gate_id"] for gate in value["gates"]] != list(GATE_IDS):
            raise ContractError("qualification gates are not in canonical order")
        if (
            derive_decision(value["gates"], value["limits"], value["blockers"])
            != value["decision"]
        ):
            raise ContractError("qualification decision differs from ordered gates")
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


def qualification_request_ceilings(
    sentinel: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    probe_count: int,
) -> dict[str, int]:
    public_cases: dict[str, int] = {}
    calibration_requests = 0
    holdout_cases = 0
    for skill_id in SKILL_IDS:
        record = sentinel["skills"][skill_id]
        scenarios = (
            resolve_binding(record["public_scenarios"], repository_root, campaign_root)
            .read_bytes()
            .splitlines()
        )
        calibration = (
            resolve_binding(record["calibration_gold"], repository_root, campaign_root)
            .read_bytes()
            .splitlines()
        )
        if not scenarios or not calibration:
            raise ContractError(f"{skill_id} sentinel request corpus is empty")
        for index, row in enumerate((*scenarios, *calibration), start=1):
            strict_json_bytes(row, label=f"{skill_id} request row {index}")
        if len(calibration) != record["calibration_request_ceiling"]:
            raise ContractError(
                f"{skill_id} calibration request ceiling differs from gold"
            )
        public_cases[skill_id] = len(scenarios)
        calibration_requests += len(calibration)
        holdout_cases += record["holdout_case_ceiling"]
    current_execute = sum(public_cases.values()) * 2
    # Each unaffected Skill keeps one positive control so its protected
    # regression slice remains valid under the existing L2 quality contract.
    candidate_cases = max(
        public_cases[owner]
        + sum(
            len(sentinel["skills"][skill_id]["protected_case_ids"]) + 1
            for skill_id in SKILL_IDS
            if skill_id != owner
        )
        for owner in SKILL_IDS
    )
    # Every exposed holdout scenario keeps the no-Skill comparator and the
    # selected Skill treatment, just like the public and candidate plans.
    execute = current_execute + candidate_cases * 2 + holdout_cases * 2
    model_grade = calibration_requests + execute
    return {
        "provider_requests": probe_count + execute + model_grade,
        "execute": execute,
        "model_grade": model_grade,
        "calibration": calibration_requests,
    }


def build_initial_campaign(
    *,
    campaign_id: str,
    git_identity: dict[str, str],
    bundle_manifest: dict[str, Any],
    bundle_manifest_binding: dict[str, Any],
    bundle_build: dict[str, Any],
    bundle_build_binding: dict[str, Any],
    plugin_build_binding: dict[str, Any],
    plugin_root: str,
    plugin_tree_hash: str,
    calibration_requests: int,
    static_report: dict[str, Any],
    static_report_binding: dict[str, Any],
    target_host_binding: dict[str, Any],
    probe_set_binding: dict[str, Any],
    sentinel_binding: dict[str, Any],
    ceilings: dict[str, int | None],
    repository_root: Path,
    campaign_root: Path,
    predecessor: dict[str, Any] | None = None,
    supersedes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(campaign_id):
        raise ContractError("campaign ID is unsafe")
    if set(bundle_build.get("skills", {})) != set(SKILL_IDS):
        raise ContractError("Bundle build does not contain the exact four Skills")
    manifest_skills = {
        item["id"]: item
        for item in bundle_manifest.get("skills", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if set(manifest_skills) != set(SKILL_IDS):
        raise ContractError(
            "Bundle source manifest does not contain the exact four Skills"
        )
    if (
        static_report.get("bundle_id")
        != f"frontier-engineering/{bundle_manifest.get('bundle_version')}"
    ):
        raise ContractError("Bundle and static report identities differ")
    verify_self_hash(static_report, "report_hash")
    probe_set = load_json(
        resolve_binding(probe_set_binding, repository_root, campaign_root),
        label="interaction probe set",
    )
    sentinel = load_json(
        resolve_binding(sentinel_binding, repository_root, campaign_root),
        label="sentinel index",
    )
    host = load_json(
        resolve_binding(target_host_binding, repository_root, campaign_root),
        label="target provisional Host",
    )
    validate_document(probe_set, "interaction_probes")
    validate_document(sentinel, "sentinel_index")
    _validate_external_schema(
        host,
        REPOSITORY_ROOT / "skill-evaluator/schemas/host-manifest-v1.schema.json",
        "target provisional Host",
    )
    verify_self_hash(host, "manifest_hash")
    expected_counts = {
        "provider_requests",
        "execute",
        "model_grade",
        "reviewer",
        "optimizer",
        "download_bytes",
        "artifact_bytes",
        "candidates",
    }
    if set(ceilings) != expected_counts:
        raise ContractError("campaign budget ceilings are incomplete")
    reserved = (
        dict(supersedes["imported_reserved"])
        if supersedes is not None
        else {field: 0 for field in ceilings}
    )
    observed: dict[str, int | None] = (
        dict(supersedes["imported_observed"])
        if supersedes is not None
        else {field: 0 for field in ceilings}
    )
    if supersedes is None:
        observed["artifact_bytes"] = None
    for field, amount in reserved.items():
        if amount is None or (ceilings[field] is not None and amount > ceilings[field]):
            raise ContractError(
                f"imported reservation exceeds campaign ceiling for {field}"
            )
    skills = {
        skill_id: {
            "version": bundle_build["skills"][skill_id]["version"],
            "root_hash": bundle_build["skills"][skill_id]["root_hash"],
            "allow_implicit_invocation": bundle_build["skills"][skill_id][
                "allow_implicit_invocation"
            ],
        }
        for skill_id in SKILL_IDS
    }
    for skill_id in SKILL_IDS:
        if skills[skill_id]["version"] != manifest_skills[skill_id]["version"]:
            raise ContractError(f"Bundle Skill version differs for {skill_id}")
    evidence_item = {
        "grader_calibration": None,
        "current_summary": None,
        "transition_report": None,
        "candidate_summary": None,
        "revision_report": None,
        "holdout_summary": None,
    }
    state = {
        "schema_version": "model-evolution-campaign/1",
        "campaign_id": campaign_id,
        "supersedes": supersedes,
        "state_revision": 0,
        "phase": "declared",
        "apparatus_report": None,
        "product": {
            "bundle_id": static_report["bundle_id"],
            "bundle_version": bundle_manifest["bundle_version"],
            "source_commit": git_identity["commit"],
            "source_tree": git_identity["tree"],
            "dirty": False,
            "plugin_tree": plugin_tree_hash,
            "plugin_build": plugin_build_binding,
            "plugin_root": plugin_root,
            "calibration_requests": calibration_requests,
            "bundle_manifest": bundle_manifest_binding,
            "bundle_build": bundle_build_binding,
            "static_report": static_report_binding,
            "skills": skills,
        },
        "profiles": {
            "predecessor": predecessor,
            "target_provisional": target_host_binding,
            "target_observed": None,
        },
        "interaction_probes": {
            "probe_set": probe_set_binding,
            "results": None,
            "requests": [],
            "blocker": None,
        },
        "sentinel_index": sentinel_binding,
        "budgets": {
            "ceiling": ceilings,
            "reserved": reserved,
            "observed": observed,
            "candidate_count": reserved["candidates"],
        },
        "plans": [],
        "skill_evidence": {
            **{skill_id: dict(evidence_item) for skill_id in SKILL_IDS},
            "plugin_build": None,
        },
        "candidate": None,
    }
    state = with_self_hash(state, "campaign_hash")
    validate_document(state, "campaign")
    return state


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


def prepare_predecessor(
    *,
    cycle_binding: dict[str, Any],
    host_binding: dict[str, Any],
    comparison_binding: dict[str, Any],
    qualification_binding: dict[str, Any] | None,
    current_bundle_id: str,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, Any]:
    cycle = load_json(
        resolve_binding(cycle_binding, repository_root, campaign_root),
        label="predecessor campaign",
    )
    validate_document(cycle, "campaign")
    if cycle["phase"] != "holdout_ready":
        raise ContractError("predecessor campaign is not closed at holdout_ready")
    if cycle["product"]["bundle_id"] != current_bundle_id:
        raise ContractError("predecessor product differs from current Bundle")
    observed_host = cycle["profiles"]["target_observed"]
    if observed_host is None or observed_host["sha256"] != host_binding["sha256"]:
        raise ContractError("predecessor Host differs from its closed campaign")
    host = load_json(
        resolve_binding(host_binding, repository_root, campaign_root),
        label="predecessor Host",
    )
    _validate_external_schema(
        host,
        REPOSITORY_ROOT / "skill-evaluator/schemas/host-manifest-v1.schema.json",
        "predecessor Host",
    )
    verify_self_hash(host, "manifest_hash")
    comparison_path = resolve_binding(
        comparison_binding, repository_root, campaign_root
    )
    if (
        evaluator_evidence_status(comparison_path, kind="transition_report")
        == "blocked"
    ):
        raise ContractError("predecessor comparison is not closed evidence")
    comparison = load_json(comparison_path, label="predecessor comparison")
    product_hash = cycle["product"]["plugin_tree"]
    if qualification_binding is not None:
        qualification = load_json(
            resolve_binding(qualification_binding, repository_root, campaign_root),
            label="predecessor qualification",
        )
        validate_document(qualification, "qualification")
        if qualification["campaign_hash"] != cycle["campaign_hash"]:
            raise ContractError("predecessor qualification differs from its campaign")
        if qualification["decision"] == "blocked":
            raise ContractError("blocked qualification cannot be a predecessor")
        product_hash = qualification["identity"]["plugin_tree"]
    return {
        "cycle": cycle_binding,
        "host": host_binding,
        "product_hash": product_hash,
        "sentinel_hash": cycle["sentinel_index"]["sha256"],
        "comparison_hash": comparison["comparison_report_hash"],
        "qualification": qualification_binding,
    }


def _validate_lineage_campaign(value: dict[str, Any], label: str) -> None:
    try:
        validate_document(value, "campaign")
        return
    except ContractError as current_error:
        evidence = value.get("skill_evidence")
        legacy_keys = {*SKILL_IDS, "grader_calibration", "plugin_build"}
        if (
            not isinstance(evidence, dict)
            or set(evidence) != legacy_keys
            or evidence.get("grader_calibration") is not None
            or any(
                not isinstance(evidence.get(skill_id), dict)
                or "grader_calibration" in evidence[skill_id]
                for skill_id in SKILL_IDS
            )
        ):
            raise current_error
        verify_self_hash(value, "campaign_hash")
        migrated = copy.deepcopy(value)
        del migrated["skill_evidence"]["grader_calibration"]
        for skill_id in SKILL_IDS:
            migrated["skill_evidence"][skill_id]["grader_calibration"] = None
        migrated = with_self_hash(migrated, "campaign_hash")
        try:
            validate_document(migrated, "campaign")
        except ContractError as exc:
            raise ContractError(
                f"{label} legacy calibration shape is invalid"
            ) from exc


def _is_single_calibration_correction(value: dict[str, Any]) -> bool:
    evidence = value["skill_evidence"]
    per_skill = [evidence[skill_id] for skill_id in SKILL_IDS]
    calibrations_empty = (
        evidence.get("grader_calibration") is None
        if "grader_calibration" in evidence
        else all(item.get("grader_calibration") is None for item in per_skill)
    )
    return (
        value["phase"] == "target_profile_ready"
        and value["plans"] == []
        and value["candidate"] is None
        and evidence["plugin_build"] is None
        and calibrations_empty
        and all(
            all(
                field == "grader_calibration" or binding is None
                for field, binding in item.items()
            )
            for item in per_skill
        )
    )


def _is_partial_calibration_correction(value: dict[str, Any]) -> bool:
    evidence = value["skill_evidence"]
    per_skill = [evidence[skill_id] for skill_id in SKILL_IDS]
    recorded = sum(item["grader_calibration"] is not None for item in per_skill)
    return (
        value["phase"] == "target_profile_ready"
        and 0 < recorded < len(SKILL_IDS)
        and value["plans"] == []
        and value["candidate"] is None
        and evidence["plugin_build"] is None
        and all(
            all(
                field == "grader_calibration" or binding is None
                for field, binding in item.items()
            )
            for item in per_skill
        )
    )


def _is_single_probe_contract_correction(value: dict[str, Any]) -> bool:
    evidence = value["skill_evidence"]
    per_skill = [evidence[skill_id] for skill_id in SKILL_IDS]
    requests = value["interaction_probes"]["requests"]
    return (
        value["phase"] == "apparatus_ready"
        and value["interaction_probes"]["blocker"]
        == "critical interaction probes did not pass: natural_routing"
        and requests
        and all(request["status"] == "closed" for request in requests)
        and any(request["result_status"] == "unknown" for request in requests)
        and value["interaction_probes"]["results"] is not None
        and value["profiles"]["target_observed"] is not None
        and value["apparatus_report"] is not None
        and value["plans"] == []
        and value["candidate"] is None
        and evidence["plugin_build"] is None
        and all(all(binding is None for binding in item.values()) for item in per_skill)
    )


def _is_formal_projection_correction(value: dict[str, Any]) -> bool:
    evidence = value["skill_evidence"]
    per_skill = [evidence[skill_id] for skill_id in SKILL_IDS]
    plans = value["plans"]
    requests = value["interaction_probes"]["requests"]
    return (
        value["phase"] == "calibration_ready"
        and value["candidate"] is None
        and evidence["plugin_build"] is None
        and len(plans) == len(SKILL_IDS)
        and {
            (plan.get("role"), plan.get("skill_id")) for plan in plans
        } == {("target_current", skill_id) for skill_id in SKILL_IDS}
        and all(item["grader_calibration"] is not None for item in per_skill)
        and all(
            all(
                field == "grader_calibration" or binding is None
                for field, binding in item.items()
            )
            for item in per_skill
        )
        and value["interaction_probes"]["blocker"] is None
        and len(requests) == 6
        and {request["probe_id"] for request in requests}
        == {
            "force-load",
            "natural-routing",
            "multi-turn",
            "principal-tracing",
            "usage-capture",
            "authorization-trace",
        }
        and all(request["status"] == "closed" for request in requests)
    )


def _is_model_grade_path_correction(value: dict[str, Any]) -> bool:
    product = value["product"]
    budgets = value["budgets"]
    request_fields = ("provider_requests", "model_grade", "execute")
    return (
        _is_formal_projection_correction(value)
        and value["campaign_id"] == "model-evolution-6-3-projection-ec0d79d"
        and product["source_commit"]
        == "ec0d79d59f4325389d3b15b1d0c5a4d176495bfc"
        and tuple(budgets["ceiling"][field] for field in request_fields)
        == (450, 248, 184)
        and tuple(budgets["reserved"][field] for field in request_fields)
        == (370, 208, 144)
        and tuple(budgets["observed"][field] for field in request_fields)
        == (210, 192, 0)
    )


def _is_multiturn_timeout_correction(value: dict[str, Any]) -> bool:
    product = value["product"]
    budgets = value["budgets"]
    request_fields = ("provider_requests", "model_grade", "execute")
    return (
        _is_formal_projection_correction(value)
        and value["campaign_id"]
        == "model-evolution-6-3-path-blinding-7ac1ecb"
        and product["source_commit"]
        == "7ac1ecba016345cf2133d387ca3123a5d8f29d22"
        and tuple(budgets["ceiling"][field] for field in request_fields)
        == (552, 296, 232)
        and tuple(budgets["reserved"][field] for field in request_fields)
        == (472, 256, 192)
        and tuple(budgets["observed"][field] for field in request_fields)
        == (280, 256, 0)
    )


def _is_systemd_environment_correction(value: dict[str, Any]) -> bool:
    product = value["product"]
    budgets = value["budgets"]
    request_fields = ("provider_requests", "model_grade", "execute")
    return (
        _is_formal_projection_correction(value)
        and value["campaign_id"]
        == "model-evolution-6-3-multiturn-timeout-8e867db"
        and product["source_commit"]
        == "8e867dbf550c0c216b404a03b23d155d8af32b53"
        and tuple(budgets["ceiling"][field] for field in request_fields)
        == (718, 408, 280)
        and tuple(budgets["reserved"][field] for field in request_fields)
        == (574, 304, 240)
        and tuple(budgets["observed"][field] for field in request_fields)
        == (350, 320, 0)
    )


def _is_single_principal_exec_correction(value: dict[str, Any]) -> bool:
    product = value["product"]
    budgets = value["budgets"]
    request_fields = ("provider_requests", "model_grade", "execute")
    return (
        _is_formal_projection_correction(value)
        and value["campaign_id"]
        == "model-evolution-6-3-systemd-environment-abf4929"
        and product["source_commit"]
        == "abf4929be4f5b4298695b108f6734c0c2242bdd0"
        and tuple(budgets["ceiling"][field] for field in request_fields)
        == (820, 456, 328)
        and tuple(budgets["reserved"][field] for field in request_fields)
        == (676, 352, 288)
        and tuple(budgets["observed"][field] for field in request_fields)
        == (420, 384, 0)
    )


def _is_source_workspace_isolation_correction(value: dict[str, Any]) -> bool:
    evidence = value["skill_evidence"]
    per_skill = [evidence[skill_id] for skill_id in SKILL_IDS]
    requests = value["interaction_probes"]["requests"]
    request_fields = ("provider_requests", "model_grade", "execute")
    return (
        value["campaign_id"]
        == "model-evolution-6-3-single-principal-4ad0902"
        and value["product"]["source_commit"]
        == "4ad0902cba9e531fda0e5f910cfc431930e4805a"
        and value["phase"] == "calibration_ready"
        and value["state_revision"] == 7
        and value["plans"] == []
        and value["candidate"] is None
        and evidence["plugin_build"] is None
        and all(item["grader_calibration"] is not None for item in per_skill)
        and all(
            all(
                field == "grader_calibration" or binding is None
                for field, binding in item.items()
            )
            for item in per_skill
        )
        and value["interaction_probes"]["blocker"] is None
        and value["interaction_probes"]["results"] is not None
        and value["profiles"]["target_observed"] is not None
        and value["apparatus_report"] is not None
        and len(requests) == 6
        and {request["probe_id"] for request in requests}
        == {
            "force-load",
            "natural-routing",
            "multi-turn",
            "principal-tracing",
            "usage-capture",
            "authorization-trace",
        }
        and all(request["status"] == "closed" for request in requests)
        and tuple(
            value["budgets"]["ceiling"][field] for field in request_fields
        ) == (922, 536, 376)
        and tuple(
            value["budgets"]["reserved"][field] for field in request_fields
        ) == (682, 352, 288)
        and tuple(
            value["budgets"]["observed"][field] for field in request_fields
        ) == (490, 448, 0)
    )


def _is_child_environment_isolation_correction(value: dict[str, Any]) -> bool:
    request_fields = ("provider_requests", "model_grade", "execute")
    return (
        _is_formal_projection_correction(value)
        and value["campaign_id"]
        == "model-evolution-6-3-source-workspace-isolation-5cff930"
        and value["product"]["source_commit"]
        == "5cff930e90f73774b88289e8104e7f78d07e3d55"
        and value["state_revision"] == 11
        and tuple(
            value["budgets"]["ceiling"][field] for field in request_fields
        ) == (928, 600, 376)
        and tuple(
            value["budgets"]["reserved"][field] for field in request_fields
        ) == (784, 400, 336)
        and tuple(
            value["budgets"]["observed"][field] for field in request_fields
        ) == (560, 512, 0)
    )


def _validate_child_environment_isolation_evidence(
    campaign: dict[str, Any], campaign_root: Path, repository_root: Path,
) -> None:
    plans = {record["skill_id"]: record for record in campaign["plans"]}
    for skill_id in SKILL_IDS:
        plan_path = resolve_binding(
            plans[skill_id]["plan"], repository_root, campaign_root,
        )
        plan = load_json(plan_path, label=f"{skill_id} child-env parent plan")
        artifacts = plan_path.parent / plan["artifacts"]["root"]
        index_path = artifacts / plan["artifacts"]["index_relpath"]
        attempts = list((artifacts / "entries").glob("*/attempt-*"))
        if skill_id != "skill-evaluator":
            if index_path.exists() or attempts:
                raise ContractError("child-env parent started an unexpected plan")
            continue

        rows = load_jsonl(index_path, label="child-env parent index")
        expected = {
            "pe-9bbf96d9f91228d492776a6e": (True, "normal", "completed"),
            "pe-234a7ca6e66b3f19631998a7": (
                False, "resume_seal", "interrupted",
            ),
        }
        if {row.get("entry_id") for row in rows} != set(expected):
            raise ContractError("child-env parent index differs")
        indexed_attempts: set[Path] = set()
        candidate_attempt: Path | None = None
        candidate_receipt: dict[str, Any] | None = None
        for row in rows:
            entry_id = row["entry_id"]
            attempt = artifacts.joinpath(*_relative_path(row["artifact_dir"]).parts)
            receipt_binding = row["receipt"]
            receipt_path = artifacts.joinpath(
                *_relative_path(receipt_binding["path"]).parts,
            )
            if (
                row.get("attempt") != 1
                or attempt.is_symlink()
                or not attempt.is_dir()
                or receipt_path != attempt / "receipt.json"
                or receipt_path.is_symlink()
                or not receipt_path.is_file()
                or content_hash(receipt_path.read_bytes())
                != receipt_binding.get("sha256")
            ):
                raise ContractError("child-env parent receipt binding differs")
            receipt = load_json(receipt_path, label="child-env parent receipt")
            verify_self_hash(receipt, "receipt_hash")
            valid, origin, terminal = expected[entry_id]
            run = receipt.get("run", {})
            if (
                run.get("entry_id") != entry_id
                or run.get("attempt") != 1
                or run.get("valid") is not valid
                or run.get("completion_origin") != origin
                or run.get("terminal") != terminal
                or (not valid and run.get("error") != "interrupted")
            ):
                raise ContractError("child-env parent run differs")
            indexed_attempts.add(attempt.resolve())
            if not valid:
                candidate_attempt = attempt
                candidate_receipt = receipt
        if (
            len(rows) != 2
            or len(attempts) != 2
            or {path.resolve() for path in attempts} != indexed_attempts
            or candidate_attempt is None
            or candidate_receipt is None
        ):
            raise ContractError("child-env parent attempt set differs")

        protocol = candidate_receipt.get("host_protocol", {})
        requests = protocol.get("requests")
        stdout_path = candidate_attempt / "host-stdout.jsonl"
        stderr_path = candidate_attempt / "host-stderr.txt"
        if (
            protocol.get("results") != []
            or not isinstance(requests, list)
            or len(requests) != 1
            or requests[0].get("envelope", {}).get("entry_id")
            != "pe-234a7ca6e66b3f19631998a7"
            or protocol.get("raw_stdout", {}).get("sha256")
            != content_hash(stdout_path.read_bytes())
            or protocol.get("raw_stderr", {}).get("sha256")
            != content_hash(stderr_path.read_bytes())
            or stderr_path.read_bytes() != b""
        ):
            raise ContractError("child-env parent Host receipt differs")
        results = load_jsonl(stdout_path, label="child-env parent Host result")
        result = results[0] if len(results) == 1 else None
        if (
            not isinstance(result, dict)
            or result.get("request_hash") != requests[0].get("request_hash")
            or result.get("terminal_status") != "protocol_error"
            or result.get("provider_error_code") is not None
            or result.get("principals") != []
            or result.get("actions") != []
            or result.get("usage", {}).get("records") != []
            or result.get("protocol_error") != {
                "artifact": None,
                "kind": "malformed_record",
                "message": "Codex output exposed the bound source repository",
                "seq": None,
            }
        ):
            raise ContractError("child-env parent Host evidence differs")


def _validate_single_principal_exec_evidence(
    campaign: dict[str, Any], campaign_root: Path, repository_root: Path,
) -> None:
    expected = {
        "long-document-segmented-writing": (12, 12, 0),
        "skill-evaluator": (11, 10, 1),
        "software-quality-workflows": (7, 6, 1),
        "writing-plans": (6, 5, 1),
    }
    plans = {record["skill_id"]: record for record in campaign["plans"]}
    for skill_id, (indexed, valid, invalid) in expected.items():
        plan_path = resolve_binding(
            plans[skill_id]["plan"], repository_root, campaign_root,
        )
        plan = load_json(plan_path, label=f"{skill_id} exec parent plan")
        execute_entries = [
            entry for entry in plan["entries"]
            if entry["disposition"] == "execute"
        ]
        artifacts = plan_path.parent / plan["artifacts"]["root"]
        rows = load_jsonl(
            artifacts / plan["artifacts"]["index_relpath"],
            label=f"{skill_id} exec parent index",
        )
        attempt_paths = list((artifacts / "entries").glob("*/attempt-*"))
        indexed_paths: set[Path] = set()
        validity: list[bool] = []
        for row in rows:
            attempt = artifacts.joinpath(*_relative_path(row["artifact_dir"]).parts)
            receipt_binding = row["receipt"]
            receipt_path = artifacts.joinpath(
                *_relative_path(receipt_binding["path"]).parts,
            )
            if (
                attempt.is_symlink()
                or not attempt.is_dir()
                or receipt_path != attempt / "receipt.json"
                or receipt_path.is_symlink()
                or not receipt_path.is_file()
                or content_hash(receipt_path.read_bytes())
                != receipt_binding["sha256"]
            ):
                raise ContractError("exec parent receipt binding differs")
            receipt = load_json(receipt_path, label=f"{skill_id} exec receipt")
            verify_self_hash(receipt, "receipt_hash")
            run = receipt.get("run", {})
            if (
                run.get("entry_id") != row.get("entry_id")
                or run.get("attempt") != row.get("attempt")
            ):
                raise ContractError("exec parent receipt identity differs")
            is_valid = run.get("valid") is True
            validity.append(is_valid)
            indexed_paths.add(attempt.resolve())
            if not is_valid and (
                run.get("completion_origin") != "resume_seal"
                or run.get("terminal") != "interrupted"
                or run.get("error") != "interrupted"
            ):
                raise ContractError("exec parent invalid receipt differs")
        attempts = {path.resolve() for path in attempt_paths}
        if (
            len(execute_entries) != 12
            or len(rows) != indexed
            or sum(validity) != valid
            or len(validity) - sum(validity) != invalid
            or len(indexed_paths) != len(rows)
            or len(attempt_paths) != len(rows)
            or any(path.is_symlink() or not path.is_dir() for path in attempt_paths)
            or attempts != indexed_paths
        ):
            raise ContractError("exec parent attempt state differs")


def _validate_systemd_environment_evidence(
    campaign: dict[str, Any], campaign_root: Path, repository_root: Path,
) -> None:
    expected_entries = {
        "long-document-segmented-writing": "pe-0e13d369786c6271a5a7681b",
        "skill-evaluator": "pe-f50df320b2ef368e3ad619eb",
        "software-quality-workflows": "pe-163b8dbdc3e59a8dd289eccb",
        "writing-plans": "pe-c55a7c135152e77b3fbd8801",
    }
    plans = {record["skill_id"]: record for record in campaign["plans"]}
    for skill_id, entry_id in expected_entries.items():
        plan_path = resolve_binding(
            plans[skill_id]["plan"], repository_root, campaign_root,
        )
        plan = load_json(plan_path, label=f"{skill_id} environment parent plan")
        artifacts = plan_path.parent / plan["artifacts"]["root"]
        rows = load_jsonl(
            artifacts / plan["artifacts"]["index_relpath"],
            label=f"{skill_id} environment parent index",
        )
        if len(rows) != 1:
            raise ContractError("environment parent index differs")
        row = rows[0]
        attempt = artifacts / "entries" / entry_id / "attempt-0001"
        receipt_path = attempt / "receipt.json"
        attempt_paths = list((artifacts / "entries").glob("*/attempt-*"))
        if (
            row.get("entry_id") != entry_id
            or row.get("attempt") != 1
            or row.get("artifact_dir")
            != attempt.relative_to(artifacts).as_posix()
            or row.get("receipt", {}).get("path")
            != receipt_path.relative_to(artifacts).as_posix()
            or attempt_paths != [attempt]
            or attempt.is_symlink()
            or not attempt.is_dir()
            or receipt_path.is_symlink()
            or not receipt_path.is_file()
            or content_hash(receipt_path.read_bytes())
            != row.get("receipt", {}).get("sha256")
        ):
            raise ContractError("environment parent attempt set differs")
        receipt = load_json(receipt_path, label=f"{skill_id} environment receipt")
        verify_self_hash(receipt, "receipt_hash")
        run = receipt.get("run", {})
        protocol = receipt.get("host_protocol", {})
        requests = protocol.get("requests")
        if (
            run.get("completion_origin") != "resume_seal"
            or run.get("terminal") != "interrupted"
            or run.get("error") != "interrupted"
            or run.get("valid") is not False
            or protocol.get("results") != []
            or not isinstance(requests, list)
            or len(requests) != 1
            or requests[0].get("envelope", {}).get("entry_id") != entry_id
        ):
            raise ContractError("environment parent receipt differs")
        stdout_path = attempt / "host-stdout.jsonl"
        stderr_path = attempt / "host-stderr.txt"
        if (
            protocol.get("raw_stdout", {}).get("sha256")
            != content_hash(stdout_path.read_bytes())
            or protocol.get("raw_stderr", {}).get("sha256")
            != content_hash(stderr_path.read_bytes())
        ):
            raise ContractError("environment parent raw evidence differs")
        results = load_jsonl(stdout_path, label=f"{skill_id} environment Host result")
        result = results[0] if len(results) == 1 else None
        stderr = stderr_path.read_text(encoding="utf-8")
        if (
            not isinstance(result, dict)
            or result.get("terminal_status") != "timeout"
            or result.get("failure_class") != "model_task_timeout"
            or result.get("timeout") is not True
            or result.get("provider_error_code") is not None
            or result.get("protocol_error") is not None
            or result.get("request_hash") != requests[0].get("request_hash")
            or result.get("usage", {}).get("records") != []
            or result.get("context", {}).get("status") != "missing"
            or "HTTP 403" not in stderr
            or "chatgpt.com/backend-api/ps/mcp" not in stderr
            or "failed to refresh available models" not in stderr
        ):
            raise ContractError("environment parent Host evidence differs")


def _validate_multiturn_timeout_evidence(
    campaign: dict[str, Any], campaign_root: Path, repository_root: Path,
) -> None:
    expected = {
        "long-document-segmented-writing": (8, "pe-810132ec4b90d371d73a527a"),
        "skill-evaluator": (5, "pe-38534738d5cc38b2e83e86a3"),
        "software-quality-workflows": (6, "pe-cf8a6db76631e6fadd1b87a7"),
        "writing-plans": (4, "pe-a3f01f7e39ea4a87fb38d049"),
    }
    plans = {record["skill_id"]: record for record in campaign["plans"]}
    for skill_id, (completed, recoverable_id) in expected.items():
        plan_path = resolve_binding(
            plans[skill_id]["plan"], repository_root, campaign_root,
        )
        plan = load_json(plan_path, label=f"{skill_id} timeout parent plan")
        artifacts = plan_path.parent / plan["artifacts"]["root"]
        index = artifacts / plan["artifacts"]["index_relpath"]
        rows = load_jsonl(index, label=f"{skill_id} timeout parent index")
        if len(rows) != completed:
            raise ContractError("timeout parent completion count differs")
        indexed_attempts = set()
        for row in rows:
            attempt = artifacts.joinpath(*_relative_path(row["artifact_dir"]).parts)
            receipt_binding = row["receipt"]
            receipt = artifacts.joinpath(
                *_relative_path(receipt_binding["path"]).parts,
            )
            if (
                attempt.is_symlink()
                or not attempt.is_dir()
                or receipt.is_symlink()
                or not receipt.is_file()
                or content_hash(receipt.read_bytes()) != receipt_binding["sha256"]
            ):
                raise ContractError("timeout parent indexed receipt differs")
            indexed_attempts.add(attempt.resolve())
        recoverable = artifacts / "entries" / recoverable_id / "attempt-0001"
        attempt_paths = list((artifacts / "entries").glob("*/attempt-*"))
        if any(path.is_symlink() or not path.is_dir() for path in attempt_paths):
            raise ContractError("timeout parent attempt set is unsafe")
        attempts = {path.resolve() for path in attempt_paths}
        if (
            recoverable.resolve() in indexed_attempts
            or not recoverable.is_dir()
            or (recoverable / "receipt.json").exists()
            or attempts != indexed_attempts | {recoverable.resolve()}
        ):
            raise ContractError("timeout parent recoverable set differs")

    timeout_path = (
        campaign_root
        / "current-plans/writing-plans/artifacts/entries"
        / "pe-a3f01f7e39ea4a87fb38d049/attempt-0001/host-stdout.jsonl"
    )
    results = load_jsonl(timeout_path, label="timeout parent Host result")
    result = results[0] if len(results) == 1 else None
    if (
        not isinstance(result, dict)
        or result.get("terminal_status") != "timeout"
        or result.get("timeout") is not True
        or result.get("failure_class") != "model_task_timeout"
        or result.get("provider_error_code") is not None
        or result.get("protocol_error") is not None
        or result.get("treatment_error")
        != "Codex child exceeded the adapter timeout"
        or result.get("request_hash")
        != "sha256:9b13280c435e3edd14d199ca28d08cc3370c35a75a66567915bea302960b0904"
    ):
        raise ContractError("timeout parent Host result differs")


def _failure_receipt_request_count(
    binding: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign_hash: str,
) -> int:
    receipt = load_json(
        resolve_binding(binding, repository_root, campaign_root),
        label="failed-request receipt",
    )
    validate_document(receipt, "failure_receipt")
    validate_all_bindings(receipt, repository_root, campaign_root)
    request_count = receipt["request_count"]
    if (
        receipt["campaign_hash"] != campaign_hash
        or request_count != len(receipt["requests"])
        or request_count != sum(receipt["outcomes"].values())
        or sorted(row["entry_ordinal"] for row in receipt["requests"])
        != list(range(request_count))
    ):
        raise ContractError("failed-request receipt differs from its campaign")
    request_hashes: set[str] = set()
    for row in receipt["requests"]:
        identity = pre_turn_failure_identity(
            resolve_binding(
                row["host_result"],
                repository_root,
                campaign_root,
            ),
            row["entry_ordinal"],
        )
        if any(identity[field] != row[field] for field in identity):
            raise ContractError("failed-request receipt differs from Host evidence")
        request_hashes.add(identity["request_hash"])
    if len(request_hashes) != request_count:
        raise ContractError("failed-request receipt repeats a request hash")
    return request_count


def _calibration_rejection_request_count(
    binding: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
) -> int:
    from _model_evolution_calibration_receipt import (
        validate_calibration_rejection_receipt,
    )

    return validate_calibration_rejection_receipt(
        binding,
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
    )


def _blocked_supersession_lineage(
    old: dict[str, Any],
    old_path: Path,
    repository_root: Path,
) -> list[tuple[dict[str, Any], Path]]:
    """Load at most nine closed campaigns and verify every budget carry."""
    lineage = [(old, old_path)]
    current, current_path = old, old_path
    while current["supersedes"] is not None:
        if len(lineage) == 9:
            raise ContractError("supersession repair depth is exhausted")
        parent_path = resolve_binding(
            current["supersedes"]["campaign"],
            repository_root,
            current_path.parent,
        )
        parent = load_json(parent_path, label="supersession ancestor campaign")
        _validate_lineage_campaign(parent, "supersession ancestor campaign")
        lineage.append((parent, parent_path))
        current, current_path = parent, parent_path
    for (child, _), (parent, parent_path) in zip(lineage, lineage[1:]):
        expected_reserved = dict(parent["budgets"]["reserved"])
        expected_observed = dict(parent["budgets"]["observed"])
        receipt_binding = child["supersedes"].get("failure_receipt")
        if receipt_binding is not None:
            request_count = _failure_receipt_request_count(
                receipt_binding,
                repository_root=repository_root,
                campaign_root=parent_path.parent,
                campaign_hash=parent["campaign_hash"],
            )
            expected_reserved["provider_requests"] += request_count
            expected_reserved["model_grade"] += request_count
        rejection_binding = child["supersedes"].get(
            "calibration_rejection_receipt"
        )
        if rejection_binding is not None:
            request_count = _calibration_rejection_request_count(
                rejection_binding,
                repository_root=repository_root,
                campaign_root=parent_path.parent,
                campaign=parent,
            )
            expected_reserved["provider_requests"] += request_count
            expected_reserved["model_grade"] += request_count
            if expected_observed["model_grade"] is not None:
                expected_observed["model_grade"] += request_count
        if (
            child["supersedes"]["imported_reserved"] != expected_reserved
            or child["supersedes"]["imported_observed"]
            != expected_observed
        ):
            raise ContractError("supersession lineage budget differs")
        qualification = load_json(
            parent_path.parent / "qualification/qualification.json",
            label="supersession ancestor qualification",
        )
        validate_document(qualification, "qualification")
        if (
            qualification["campaign_hash"] != parent["campaign_hash"]
            or qualification["decision"] != "blocked"
        ):
            raise ContractError("supersession ancestor is not closed as blocked")
    return lineage


def prepare_supersedes(
    *,
    campaign_binding: dict[str, Any],
    target_host_binding: dict[str, Any],
    failure_receipt_binding: dict[str, Any] | None = None,
    calibration_rejection_receipt_binding: dict[str, Any] | None = None,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, Any]:

    old_path = resolve_binding(campaign_binding, repository_root, campaign_root)
    old = load_json(old_path, label="superseded campaign")
    _validate_lineage_campaign(old, "superseded campaign")
    lineage = _blocked_supersession_lineage(old, old_path, repository_root)
    probe_contract_correction = (
        len(lineage) == 6 and _is_single_probe_contract_correction(old)
    )
    calibration_contract_correction = (
        len(lineage) == 7 and _is_single_calibration_correction(old)
    )
    calibration_fixture_correction = (
        len(lineage) == 8 and _is_partial_calibration_correction(old)
    )
    formal_projection_correction = (
        len(lineage) == 9 and _is_formal_projection_correction(old)
    )
    model_grade_path_correction = (
        len(lineage) == 3 and _is_model_grade_path_correction(old)
    )
    multiturn_timeout_correction = (
        len(lineage) == 4 and _is_multiturn_timeout_correction(old)
    )
    systemd_environment_correction = (
        len(lineage) == 5 and _is_systemd_environment_correction(old)
    )
    single_principal_exec_correction = (
        len(lineage) == 6 and _is_single_principal_exec_correction(old)
    )
    source_workspace_isolation_correction = (
        len(lineage) == 7 and _is_source_workspace_isolation_correction(old)
    )
    child_environment_isolation_correction = (
        len(lineage) == 8 and _is_child_environment_isolation_correction(old)
    )
    transport_lineage = any(
        campaign["campaign_id"] == "model-evolution-6-3-projection-ec0d79d"
        for campaign, _ in lineage
    )
    if transport_lineage and not (
        model_grade_path_correction
        or multiturn_timeout_correction
        or systemd_environment_correction
        or single_principal_exec_correction
        or source_workspace_isolation_correction
        or child_environment_isolation_correction
    ):
        raise ContractError("supersession repair depth is exhausted")
    if len(lineage) == 9 and not formal_projection_correction:
        raise ContractError("supersession repair depth is exhausted")
    if len(lineage) == 8 and not (
        calibration_fixture_correction or child_environment_isolation_correction
    ):
        raise ContractError("supersession repair depth is exhausted")
    if len(lineage) == 7 and not (
        calibration_contract_correction or source_workspace_isolation_correction
    ):
        raise ContractError("supersession repair depth is exhausted")
    if len(lineage) == 6 and not (
        probe_contract_correction or single_principal_exec_correction
    ):
        raise ContractError("supersession repair depth is exhausted")
    if len(lineage) >= 3 and not (
        _is_single_calibration_correction(old)
        or probe_contract_correction
        or calibration_contract_correction
        or calibration_fixture_correction
        or formal_projection_correction
        or model_grade_path_correction
        or multiturn_timeout_correction
        or systemd_environment_correction
        or single_principal_exec_correction
        or source_workspace_isolation_correction
        or child_environment_isolation_correction
    ):
        raise ContractError("supersession repair depth is exhausted")
    receipt_hop = (
        len(lineage) in {4, 5}
        and not (multiturn_timeout_correction or systemd_environment_correction)
    )
    if receipt_hop and failure_receipt_binding is None:
        raise ContractError("late supersession requires a failed-request receipt")
    if failure_receipt_binding is not None and not receipt_hop:
        raise ContractError("failed-request receipt is only legal for a late repair")
    if (
        calibration_contract_correction or calibration_fixture_correction
    ) and calibration_rejection_receipt_binding is None:
        raise ContractError(
            "calibration correction requires a rejection receipt"
        )
    if (
        calibration_rejection_receipt_binding is not None
        and not (
            calibration_contract_correction or calibration_fixture_correction
        )
    ):
        raise ContractError(
            "calibration rejection receipt is only legal for a calibration correction"
        )
    old_host = load_json(
        resolve_binding(
            old["profiles"]["target_provisional"],
            repository_root,
            old_path.parent,
        ),
        label="superseded target Host",
    )
    target_host = load_json(
        resolve_binding(target_host_binding, repository_root, campaign_root),
        label="replacement target Host",
    )
    stable_execution = (
        "provider",
        "model",
        "model_revision",
        "harness",
        "prompt_hash",
        "policy_hash",
        "tokenizer_id",
        "pricing_id",
        "utc_clock_id",
        "monotonic_clock_id",
    )
    if not single_principal_exec_correction:
        stable_execution += ("tool_schema_hash",)
    stable_options = (
        "--codex-sha256",
        "--model",
        "--effort",
        "--profile",
        "--sandbox",
    )

    def stable_host_identity(host: dict[str, Any]) -> tuple[dict[str, Any], float]:
        identity = host.get("identity")
        execution = identity.get("execution") if isinstance(identity, dict) else None
        adapter = identity.get("adapter") if isinstance(identity, dict) else None
        command = host.get("command")
        argv = command.get("argv") if isinstance(command, dict) else None
        capabilities = host.get("capabilities")
        if (
            not isinstance(execution, dict)
            or not isinstance(adapter, dict)
            or not isinstance(argv, list)
            or not isinstance(capabilities, list)
        ):
            raise ContractError("supersession Host identity is invalid")

        def option(name: str) -> str:
            positions = [index for index, value in enumerate(argv) if value == name]
            if len(positions) != 1 or positions[0] + 1 >= len(argv):
                raise ContractError("supersession Host command is invalid")
            value = argv[positions[0] + 1]
            if not isinstance(value, str):
                raise ContractError("supersession Host command is invalid")
            return value

        capability_contract = [
            (row.get("capability"), row.get("declared"))
            for row in capabilities
            if isinstance(row, dict)
        ]
        if len(capability_contract) != len(capabilities):
            raise ContractError("supersession Host capabilities are invalid")
        try:
            timeout = float(option("--timeout"))
        except ValueError as exc:
            raise ContractError("supersession Host timeout is invalid") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ContractError("supersession Host timeout is invalid")
        return (
            {
                "execution": {
                    field: execution.get(field) for field in stable_execution
                },
                "adapter": {
                    field: adapter.get(field) for field in ("id", "version")
                },
                "command": {name: option(name) for name in stable_options},
                "capabilities": capability_contract,
            },
            timeout,
        )

    old_identity, old_timeout = stable_host_identity(old_host)
    target_identity, target_timeout = stable_host_identity(target_host)
    if old_identity != target_identity or target_timeout < old_timeout:
        raise ContractError("superseded campaign targets a different Host")
    if (
        single_principal_exec_correction
        and old_host["identity"]["execution"]["tool_schema_hash"]
        == target_host["identity"]["execution"]["tool_schema_hash"]
    ):
        raise ContractError("exec correction did not change the tool schema identity")
    if (
        (
            source_workspace_isolation_correction
            or child_environment_isolation_correction
        )
        and old_host["identity"]["adapter"]["sha256"]
        == target_host["identity"]["adapter"]["sha256"]
    ):
        raise ContractError("workspace correction did not change the Host adapter")
    qualification_path = old_path.parent / "qualification/qualification.json"
    qualification = load_json(qualification_path, label="superseded qualification")
    validate_document(qualification, "qualification")
    if qualification["campaign_hash"] != old["campaign_hash"]:
        raise ContractError("superseded qualification differs from its campaign")
    if qualification["decision"] != "blocked":
        raise ContractError("only a blocked pre-public campaign may be superseded")
    if multiturn_timeout_correction:
        if qualification["qualification_id"] != "mq-6be58b785027ed665f6b5620":
            raise ContractError("timeout parent qualification differs")
        _validate_multiturn_timeout_evidence(old, old_path.parent, repository_root)
    if systemd_environment_correction:
        if qualification["qualification_id"] != "mq-be17f8c2be4c15e4c157788c":
            raise ContractError("environment parent qualification differs")
        _validate_systemd_environment_evidence(
            old, old_path.parent, repository_root,
        )
    if single_principal_exec_correction:
        expected_blockers = {("final-plugin-unobserved", "release")} | {
            (f"{skill_id}-current", skill_id) for skill_id in SKILL_IDS
        }
        blockers = {
            (row.get("code"), row.get("scope"))
            for row in qualification["blockers"]
        }
        if blockers != expected_blockers:
            raise ContractError("exec parent qualification blockers differ")
        _validate_single_principal_exec_evidence(
            old, old_path.parent, repository_root,
        )
    if source_workspace_isolation_correction:
        expected_blockers = {("final-plugin-unobserved", "release")} | {
            (f"{skill_id}-current", skill_id) for skill_id in SKILL_IDS
        }
        blockers = {
            (row.get("code"), row.get("scope"))
            for row in qualification["blockers"]
        }
        if blockers != expected_blockers:
            raise ContractError("workspace parent qualification blockers differ")
    if child_environment_isolation_correction:
        expected_blockers = {("final-plugin-unobserved", "release")} | {
            (f"{skill_id}-current", skill_id) for skill_id in SKILL_IDS
        }
        blockers = {
            (row.get("code"), row.get("scope"))
            for row in qualification["blockers"]
        }
        if blockers != expected_blockers:
            raise ContractError("child-env parent qualification blockers differ")
        _validate_child_environment_isolation_evidence(
            old, old_path.parent, repository_root,
        )
    imported_reserved = dict(old["budgets"]["reserved"])
    imported_observed = dict(old["budgets"]["observed"])
    result = {
        "campaign": campaign_binding,
        "imported_reserved": imported_reserved,
        "imported_observed": imported_observed,
    }
    if failure_receipt_binding is not None:
        request_count = _failure_receipt_request_count(
            failure_receipt_binding,
            repository_root=repository_root,
            campaign_root=old_path.parent,
            campaign_hash=old["campaign_hash"],
        )
        imported_reserved["provider_requests"] += request_count
        imported_reserved["model_grade"] += request_count
        result["failure_receipt"] = failure_receipt_binding
    if calibration_rejection_receipt_binding is not None:
        request_count = _calibration_rejection_request_count(
            calibration_rejection_receipt_binding,
            repository_root=repository_root,
            campaign_root=old_path.parent,
            campaign=old,
        )
        imported_reserved["provider_requests"] += request_count
        imported_reserved["model_grade"] += request_count
        if imported_observed["model_grade"] is not None:
            imported_observed["model_grade"] += request_count
        result["calibration_rejection_receipt"] = (
            calibration_rejection_receipt_binding
        )
    return result


def derive_decision(
    gates: list[dict[str, Any]],
    limits: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
) -> str:
    statuses = {gate["status"] for gate in gates}
    if blockers or statuses & {"blocked", "unobserved"}:
        return "blocked"
    if limits or "limited" in statuses:
        return "qualified_with_limits"
    return "qualified"


def _counts_remaining(
    ceiling: dict[str, Any], reserved: dict[str, Any]
) -> dict[str, Any]:
    return {
        field: (
            None
            if ceiling[field] is None or reserved[field] is None
            else ceiling[field] - reserved[field]
        )
        for field in ceiling
    }


def _apparatus_artifact(
    campaign: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, str] | None:
    binding = campaign["apparatus_report"]
    if binding is None:
        return None
    value = load_json(
        resolve_binding(binding, repository_root, campaign_root),
        label="apparatus report",
    )
    required = {
        "schema_version",
        "campaign_id",
        "source_commit",
        "source_tree",
        "campaign_hash",
        "status",
        "operations",
        "apparatus_report_hash",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ContractError("apparatus report shape is invalid")
    verify_self_hash(value, "apparatus_report_hash")
    operation_fields = {
        "operation_id",
        "input_hash",
        "command_hash",
        "status",
        "duration_ms",
    }

    def valid_operation(operation: Any) -> bool:
        return (
            isinstance(operation, dict)
            and set(operation) == operation_fields
            and isinstance(operation.get("operation_id"), str)
            and SAFE_ID.fullmatch(operation["operation_id"]) is not None
            and HASH.fullmatch(str(operation.get("input_hash"))) is not None
            and HASH.fullmatch(str(operation.get("command_hash"))) is not None
            and operation.get("status") == "pass"
            and isinstance(operation.get("duration_ms"), int)
            and not isinstance(operation["duration_ms"], bool)
            and operation["duration_ms"] >= 0
        )

    if (
        value["schema_version"] != "model-evolution-apparatus-report/1"
        or value["campaign_id"] != campaign["campaign_id"]
        or value["source_commit"] != campaign["product"]["source_commit"]
        or value["source_tree"] != campaign["product"]["source_tree"]
        or value["status"] != "pass"
        or not value["operations"]
        or any(not valid_operation(operation) for operation in value["operations"])
    ):
        raise ContractError("apparatus report identity or operation status is invalid")
    return binding


def _evidence_result(
    binding: dict[str, Any] | None,
    *,
    kind: str,
    repository_root: Path,
    campaign_root: Path,
) -> str:
    if binding is None:
        return "unobserved"
    path = resolve_binding(binding, repository_root, campaign_root)
    return evaluator_evidence_status(path, kind=kind)


def _issue(
    code: str, scope: str, evidence: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"code": code, "scope": scope, "evidence": evidence}


def assess_interaction_probes(
    campaign: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    requests = campaign["interaction_probes"]["requests"]
    if not requests:
        return "unobserved", [], []
    probe_set = load_json(
        resolve_binding(
            campaign["interaction_probes"]["probe_set"],
            repository_root,
            campaign_root,
        ),
        label="interaction probe set",
    )
    validate_document(probe_set, "interaction_probes")
    capabilities = {row["probe_id"]: row["capability"] for row in probe_set["probes"]}
    blockers: list[dict[str, Any]] = []
    limits: list[dict[str, Any]] = []
    for request in requests:
        if request["result_status"] == "pass":
            continue
        capability = capabilities[request["probe_id"]]
        issue = _issue(
            "critical-probe-not-pass"
            if capability in CRITICAL_PROBE_CAPABILITIES
            else "noncritical-probe-not-pass",
            capability,
            request["artifact"],
        )
        (blockers if capability in CRITICAL_PROBE_CAPABILITIES else limits).append(
            issue
        )
    return (
        ("blocked" if blockers else "limited" if limits else "pass"),
        limits,
        blockers,
    )


def _gate(
    gate_id: str,
    status: str,
    evidence: dict[str, Any] | None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": status,
        "evidence": evidence,
        "reason_code": reason_code,
    }


def _final_skill_identities(
    campaign: dict[str, Any],
) -> dict[str, Any]:
    skills = (
        campaign["candidate"]["skills"]
        if campaign["candidate"] is not None
        else campaign["product"]["skills"]
    )
    if not isinstance(skills, dict) or set(skills) != set(SKILL_IDS):
        raise ContractError(
            "plugin build does not bind the exact four Skill identities"
        )
    return {
        skill_id: {
            "version": skills[skill_id]["version"],
            "root_hash": skills[skill_id]["root_hash"],
        }
        for skill_id in SKILL_IDS
    }


def _selected_plugin_tree(
    campaign: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
) -> str:
    binding = campaign["skill_evidence"]["plugin_build"]
    if binding is None:
        return campaign["product"]["plugin_tree"]
    evidence = load_json(
        resolve_binding(binding, repository_root, campaign_root),
        label="plugin build evidence",
    )
    if not isinstance(evidence, dict):
        raise ContractError("plugin build evidence must be an object")
    verify_self_hash(evidence, "evidence_hash")
    plugin_tree = evidence.get("plugin_tree_hash")
    if not isinstance(plugin_tree, str) or not HASH.fullmatch(plugin_tree):
        raise ContractError("plugin build evidence lacks a valid plugin tree")
    return plugin_tree


def project_qualification(
    campaign: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    observed_as_of: str,
    valid_until: str,
    repository_fallback: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    validate_document(campaign, "campaign")
    validate_all_bindings(
        campaign,
        repository_root,
        campaign_root,
        repository_fallback,
    )
    if parse_utc(valid_until) <= parse_utc(observed_as_of):
        raise ContractError("qualification valid-until must be after observed-as-of")

    apparatus = _apparatus_artifact(campaign, repository_root, campaign_root)
    observed_host = campaign["profiles"]["target_observed"]
    plugin_build = campaign["skill_evidence"]["plugin_build"]
    skill_status: dict[str, dict[str, str]] = {}
    limits: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    probe_status, probe_limits, probe_blockers = assess_interaction_probes(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    limits.extend(probe_limits)
    blockers.extend(probe_blockers)
    for skill_id in SKILL_IDS:
        evidence = campaign["skill_evidence"][skill_id]
        current = _evidence_result(
            evidence["current_summary"],
            kind="current_summary",
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        transition = (
            "limited"
            if campaign["profiles"]["predecessor"] is None
            else _evidence_result(
                evidence["transition_report"],
                kind="transition_report",
                repository_root=repository_root,
                campaign_root=campaign_root,
            )
        )
        revision = (
            "pass"
            if campaign["candidate"] is None
            else _evidence_result(
                evidence["revision_report"],
                kind="revision_report",
                repository_root=repository_root,
                campaign_root=campaign_root,
            )
        )
        holdout = _evidence_result(
            evidence["holdout_summary"],
            kind="holdout_summary",
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        blocking = next(
            (
                f"{skill_id}-{name.replace('_', '-')}"
                for name, status in (
                    ("current", current),
                    ("transition", transition),
                    ("revision", revision),
                    ("holdout", holdout),
                )
                if status in {"blocked", "unobserved"}
            ),
            None,
        )
        skill_status[skill_id] = {
            "current_usefulness": current,
            "critical_protected_safety": current,
            "transition": transition,
            "revision": revision,
            "holdout": holdout,
            "blocker": blocking,
        }
    if apparatus is None:
        blockers.append(_issue("apparatus-unobserved", "campaign"))
    if observed_host is None:
        blockers.append(_issue("target-host-unobserved", "host"))
    if campaign["interaction_probes"]["blocker"] is not None:
        blockers.append(_issue("interaction-probe-blocked", "host"))
    if plugin_build is None:
        blockers.append(_issue("final-plugin-unobserved", "release"))
    for skill_id, result in skill_status.items():
        if result["blocker"] is not None:
            blockers.append(_issue(result["blocker"], skill_id))
    if campaign["profiles"]["predecessor"] is None:
        limits.append(_issue("bootstrap-lineage", "longitudinal"))

    all_current = [result["current_usefulness"] for result in skill_status.values()]
    all_transition = [result["transition"] for result in skill_status.values()]
    all_revision = [result["revision"] for result in skill_status.values()]
    all_holdout = [result["holdout"] for result in skill_status.values()]

    def combined(values: list[str]) -> str:
        if "blocked" in values:
            return "blocked"
        if "unobserved" in values:
            return "unobserved"
        if "limited" in values:
            return "limited"
        return "pass"

    lanes = {
        "static_product": {
            "status": "pass",
            "evidence": campaign["product"]["static_report"],
        },
        "host_integration": {
            "status": probe_status if observed_host is not None else "unobserved",
            "evidence": observed_host,
        },
        "task_behavior": {
            "status": combined(all_current + all_holdout),
            "evidence": next(
                (
                    campaign["skill_evidence"][skill_id]["holdout_summary"]
                    for skill_id in SKILL_IDS
                    if campaign["skill_evidence"][skill_id]["holdout_summary"]
                    is not None
                ),
                None,
            ),
        },
        "context_cost": {
            "status": combined(all_current),
            "evidence": next(
                (
                    campaign["skill_evidence"][skill_id]["current_summary"]
                    for skill_id in SKILL_IDS
                    if campaign["skill_evidence"][skill_id]["current_summary"]
                    is not None
                ),
                None,
            ),
        },
        "longitudinal": {
            "status": "limited"
            if campaign["profiles"]["predecessor"] is None
            else combined(all_transition),
            "evidence": next(
                (
                    campaign["skill_evidence"][skill_id]["transition_report"]
                    for skill_id in SKILL_IDS
                    if campaign["skill_evidence"][skill_id]["transition_report"]
                    is not None
                ),
                None,
            ),
        },
    }
    gates = [
        _gate(
            "apparatus",
            "pass" if apparatus else "unobserved",
            apparatus,
            "apparatus-unobserved" if apparatus is None else None,
        ),
        _gate(
            "identity_comparability",
            probe_status if observed_host else "unobserved",
            observed_host,
            (
                "target-host-unobserved"
                if observed_host is None
                else "interaction-probe-not-pass"
                if probe_status != "pass"
                else None
            ),
        ),
        _gate(
            "critical_function",
            combined(all_current + all_holdout),
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "safety_protected",
            combined(all_current + all_holdout),
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "incremental_value",
            combined(all_current),
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "revision",
            combined(all_revision),
            next(
                (
                    campaign["skill_evidence"][skill_id]["revision_report"]
                    for skill_id in SKILL_IDS
                    if campaign["skill_evidence"][skill_id]["revision_report"]
                ),
                None,
            ),
        ),
        _gate("context_cost", combined(all_current), lanes["context_cost"]["evidence"]),
        _gate(
            "statistical_support",
            combined(all_holdout),
            lanes["task_behavior"]["evidence"],
        ),
        _gate(
            "release_identity",
            "pass" if plugin_build else "unobserved",
            plugin_build,
            "final-plugin-unobserved" if plugin_build is None else None,
        ),
    ]
    decision = derive_decision(gates, limits, blockers)
    final_commit = (
        campaign["candidate"]["candidate_commit"]
        if campaign["candidate"] is not None
        else campaign["product"]["source_commit"]
    )
    final_tree = (
        campaign["candidate"]["candidate_tree"]
        if campaign["candidate"] is not None
        else campaign["product"]["source_tree"]
    )
    host_binding = observed_host or campaign["profiles"]["target_provisional"]
    host = load_json(
        resolve_binding(host_binding, repository_root, campaign_root),
        label="target host",
    )
    execution = (
        host.get("identity", {}).get("execution", {}) if isinstance(host, dict) else {}
    )
    host_revision = (
        "/".join(
            str(item)
            for item in (
                host.get("identity", {}).get("host_version")
                if isinstance(host, dict)
                else None,
                execution.get("model_revision"),
            )
            if item
        )
        or "unobserved"
    )
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    budget = campaign["budgets"]
    qualification = {
        "schema_version": "model-qualification/1",
        "qualification_id": "mq-"
        + content_hash(
            canonical_bytes([campaign["campaign_hash"], observed_as_of, valid_until])
        ).removeprefix("sha256:")[:24],
        "campaign_hash": campaign["campaign_hash"],
        "identity": {
            "source_commit": final_commit,
            "source_tree": final_tree,
            "plugin_tree": _selected_plugin_tree(
                campaign,
                repository_root,
                campaign_root,
            ),
            "bundle_id": campaign["product"]["bundle_id"],
            "bundle_version": campaign["product"]["bundle_version"],
            "skills": _final_skill_identities(campaign),
            "target_observed_host": observed_host,
        },
        "claim": {
            "host_model_revision": host_revision,
            "activation_modes": ["catalog", "force_loaded", "skill_disabled"],
            "skill_scope": list(SKILL_IDS),
            "task_version": sentinel["sentinel_id"],
            "sentinel_version": sentinel["sentinel_id"],
            "ceiling": "diagnostic_only"
            if decision == "blocked"
            else "bounded"
            if limits
            else "full",
        },
        "lanes": lanes,
        "skills": skill_status,
        "gates": gates,
        "budget": {
            "ceiling": budget["ceiling"],
            "reserved": budget["reserved"],
            "observed": budget["observed"],
            "remaining": _counts_remaining(budget["ceiling"], budget["reserved"]),
        },
        "decision": decision,
        "limits": limits,
        "blockers": blockers,
        "validity": {
            "observed_as_of": observed_as_of,
            "valid_until": valid_until,
            "drift_triggers": [
                "source_commit",
                "plugin_tree",
                "host_identity",
                "model_revision",
                "tool_policy",
                "interaction_probe_set",
                "sentinel_index",
            ],
            "predecessor": (
                campaign["profiles"]["predecessor"]["qualification"]
                if campaign["profiles"]["predecessor"] is not None
                else None
            ),
        },
    }
    qualification = with_self_hash(qualification, "qualification_hash")
    validate_document(qualification, "qualification")
    return qualification


def render_qualification_markdown(value: dict[str, Any]) -> str:
    validate_document(value, "qualification")
    lines = [
        f"# Model qualification {value['qualification_id']}",
        "",
        f"Decision: `{value['decision']}`",
        f"Campaign: `{value['campaign_hash']}`",
        f"Validity: `{value['validity']['observed_as_of']}` to `{value['validity']['valid_until']}`",
        "",
        "## Ordered gates",
        "",
    ]
    lines.extend(
        f"- `{gate['gate_id']}`: `{gate['status']}`"
        + (f" ({gate['reason_code']})" if gate["reason_code"] else "")
        for gate in value["gates"]
    )
    lines.extend(["", "## Skill results", ""])
    lines.extend(
        f"- `{skill_id}`: current `{result['current_usefulness']}`, holdout `{result['holdout']}`"
        for skill_id, result in value["skills"].items()
    )
    if value["limits"]:
        lines.extend(["", "## Limits", ""])
        lines.extend(
            f"- `{item['code']}` ({item['scope']})" for item in value["limits"]
        )
    if value["blockers"]:
        lines.extend(["", "## Blockers", ""])
        lines.extend(
            f"- `{item['code']}` ({item['scope']})" for item in value["blockers"]
        )
    lines.extend(["", f"Qualification hash: `{value['qualification_hash']}`", ""])
    return "\n".join(lines)


def project_observed_host(
    provisional: dict[str, Any],
    *,
    probe_set: dict[str, Any],
    results: list[dict[str, Any]],
    observed_manifest_path: Path,
) -> dict[str, Any]:
    observed = json.loads(json.dumps(provisional))
    by_probe = {row["probe_id"]: row for row in probe_set["probes"]}
    by_capability = {row["capability"]: row for row in probe_set["probes"]}
    by_result = {row["probe_id"]: row for row in results}
    if set(by_probe) != set(by_result):
        raise ContractError("probe result set differs from the frozen probe set")
    host_capabilities = {row["capability"] for row in observed["capabilities"]}
    missing = set(by_capability) - host_capabilities
    if missing:
        raise ContractError(f"target Host lacks probed capability {sorted(missing)[0]}")
    for capability in observed["capabilities"]:
        row = by_capability.get(capability["capability"])
        if row is None:
            continue
        result = by_result[row["probe_id"]]
        terminal = result["terminal"]
        capability["probe"] = {
            "status": result["status"],
            "artifact": {
                "path": terminal["path"],
                "sha256": terminal["sha256"],
                "encoding": "utf-8",
            },
            "locator": {
                "kind": "json_pointer",
                "artifact": terminal["path"],
                "json_pointer": "/result",
            },
            "observed": "bound interaction probe terminal",
        }
    command = observed["command"]["argv"]
    if "--host-manifest" not in command:
        raise ContractError("target Host command does not bind its manifest path")
    command[command.index("--host-manifest") + 1] = str(observed_manifest_path)
    observed["manifest_hash"] = self_hash(observed, "manifest_hash")
    return observed
