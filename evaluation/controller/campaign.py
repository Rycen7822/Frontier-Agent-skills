#!/usr/bin/env python3
"""Small fail-closed owner for campaign state and provider accounting."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Iterator

from .artifacts import (
    StateError,
    artifact_binding,
    assert_nofollow,
    atomic_write as _atomic_write,
    canonical_bytes,
    canonical_hash,
    contained_file,
    file_hash,
    json_object as _json_object,
    load_json,
    raw_hash,
    require_hash as _require_hash,
    require_nonempty as _require_nonempty,
    self_hashed as _self_hashed,
    verify_self_hash as _verify_self_hash,
    write_json,
    write_or_verify_json,
)


REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SOURCE_ROOT = str(Path(__file__).resolve().parents[2])
MANIFEST_FIELDS = {
    "schema_version",
    "campaign_id",
    "required_requests",
    "conditional_requests",
    "budget",
    "manifest_hash",
}
BUDGET_FIELDS = {
    "scored_call_hard_cap",
    "grader_calibration_call_hard_cap",
    "reviewer_calibration_call_hard_cap",
    "scheduled_provider_calls",
    "retry_provider_call_cap",
    "provider_call_hard_cap",
}
REQUEST_ENTRY_FIELDS = {
    "request_id",
    "stage",
    "study",
    "family",
    "request_kind",
    "subject_id",
    "arm",
    "input_binding_hash",
    "output_schema_hash",
    "requested_model",
    "requested_reasoning_effort",
    "requested_service_tier",
    "attempt_index",
    "predecessor_request_id",
    "activation",
}
REQUEST_FAMILIES = {
    "scored",
    "grader_calibration",
    "reviewer_calibration",
}
FAMILY_REQUEST_KINDS = {
    "scored": {"execute", "model_grade"},
    "grader_calibration": {"grader_calibration"},
    "reviewer_calibration": {"context_isolated_review"},
}
CONDITIONAL_PREDICATE = "official_transient_pair"
REGISTRY_FIELDS = {
    "schema_version",
    "attempt_id",
    "campaign_id",
    "plan_sha256",
    "candidate_revision",
    "candidate_source_tree_hash",
    "candidate_plugin_tree_hash",
    "controller_content_hash",
    "evaluator_source_hash",
    "phase_contract_path",
    "phase_contract_sha256",
    "request_manifest_path",
    "request_manifest_sha256",
    "state_path",
    "provider_ledger_path",
    "continuation_token_hash",
    "registry_hash",
}
LEDGER_ROW_FIELDS = {
    "schema_version",
    "sequence",
    "request_id",
    "entry_hash",
    "request_manifest_hash",
    "previous_row_hash",
    "row_hash",
}
NATIVE_RECEIPT_FIELDS = {
    "request_id",
    "entry_hash",
    "input_binding_hash",
    "output_schema_hash",
    "terminal_status",
    "failure_class",
    "receipt_hash",
}


def _validate_request_entry(
    entry: Any,
    *,
    partition: str,
) -> dict[str, Any]:
    if not isinstance(entry, dict) or set(entry) != REQUEST_ENTRY_FIELDS:
        raise StateError("request manifest entry has unexpected fields")
    for field in ("request_id", "stage", "study", "subject_id"):
        _require_nonempty(entry[field], field)
    family = entry["family"]
    request_kind = entry["request_kind"]
    if family not in REQUEST_FAMILIES:
        raise StateError("request family is invalid")
    if request_kind not in FAMILY_REQUEST_KINDS[family]:
        raise StateError("request kind does not belong to its family")
    if entry["arm"] is not None:
        _require_nonempty(entry["arm"], "arm")
    _require_hash(entry["input_binding_hash"], "input_binding_hash")
    if entry["output_schema_hash"] is not None:
        _require_hash(entry["output_schema_hash"], "output_schema_hash")
    for field in (
        "requested_model",
        "requested_reasoning_effort",
        "requested_service_tier",
    ):
        _require_nonempty(entry[field], field)
    requested = (
        entry["requested_model"],
        entry["requested_reasoning_effort"],
        entry["requested_service_tier"],
    )
    expected = (
        ("gpt-5.6-sol", "max", "priority")
        if family == "reviewer_calibration"
        else ("gpt-5.6-luna", "high", "priority")
    )
    if requested != expected:
        raise StateError("request configuration does not match its family")
    if type(entry["attempt_index"]) is not int or entry["attempt_index"] < 0:
        raise StateError("attempt_index must be a non-negative integer")
    predecessor = entry["predecessor_request_id"]
    if predecessor is not None:
        _require_nonempty(predecessor, "predecessor_request_id")
    if partition == "required":
        if (
            entry["activation"] != "required"
            or entry["attempt_index"] != 0
            or predecessor is not None
        ):
            raise StateError("required request activation lineage is invalid")
    elif partition == "conditional":
        activation = entry["activation"]
        if (
            family != "scored"
            or entry["attempt_index"] != 1
            or predecessor is None
            or not isinstance(activation, dict)
            or set(activation)
            != {"predicate", "pair_predecessor_request_ids"}
            or activation["predicate"] != CONDITIONAL_PREDICATE
            or not isinstance(activation["pair_predecessor_request_ids"], list)
            or len(activation["pair_predecessor_request_ids"]) != 2
        ):
            raise StateError("conditional request activation lineage is invalid")
        for request_id in activation["pair_predecessor_request_ids"]:
            _require_nonempty(request_id, "pair_predecessor_request_id")
    else:
        raise StateError("unknown request manifest partition")
    return entry


def _expected_budget(
    required: list[dict[str, Any]],
    conditional: list[dict[str, Any]],
) -> dict[str, int]:
    required_counts = {
        family: sum(entry["family"] == family for entry in required)
        for family in REQUEST_FAMILIES
    }
    return {
        "scored_call_hard_cap": required_counts["scored"],
        "grader_calibration_call_hard_cap": required_counts[
            "grader_calibration"
        ],
        "reviewer_calibration_call_hard_cap": required_counts[
            "reviewer_calibration"
        ],
        "scheduled_provider_calls": len(required),
        "retry_provider_call_cap": len(conditional),
        "provider_call_hard_cap": len(required) + len(conditional),
    }


def _validate_request_partitions(
    required: Any,
    conditional: Any,
    budget: Any,
) -> None:
    if not isinstance(required, list) or not isinstance(conditional, list):
        raise StateError("request manifest partitions must be arrays")
    required_entries = [
        _validate_request_entry(item, partition="required")
        for item in required
    ]
    conditional_entries = [
        _validate_request_entry(item, partition="conditional")
        for item in conditional
    ]
    entries = [*required_entries, *conditional_entries]
    request_ids = [entry["request_id"] for entry in entries]
    if len(request_ids) != len(set(request_ids)):
        raise StateError("request manifest contains duplicate request IDs")
    required_by_id = {
        entry["request_id"]: entry for entry in required_entries
    }
    if len(conditional_entries) not in {0, 2}:
        raise StateError("conditional requests must be absent or one retry pair")
    if conditional_entries:
        activation = conditional_entries[0]["activation"]
        if any(entry["activation"] != activation for entry in conditional_entries):
            raise StateError("conditional retry pair activation differs")
        pair_ids = activation["pair_predecessor_request_ids"]
        predecessors = [required_by_id.get(request_id) for request_id in pair_ids]
        if any(item is None for item in predecessors):
            raise StateError("conditional retry predecessor is absent")
        assert all(item is not None for item in predecessors)
        predecessor_entries = [item for item in predecessors if item is not None]
        if [item["request_kind"] for item in predecessor_entries] != [
            "execute",
            "model_grade",
        ]:
            raise StateError("conditional activation does not bind execute+grade")
        pair_identity_fields = ("stage", "study", "subject_id", "arm")
        if any(
            predecessor_entries[0][field] != predecessor_entries[1][field]
            for field in pair_identity_fields
        ):
            raise StateError("retry predecessors are not one task/arm pair")
        conditional_by_predecessor = {
            entry["predecessor_request_id"]: entry
            for entry in conditional_entries
        }
        if set(conditional_by_predecessor) != set(pair_ids):
            raise StateError("retry pair does not map each predecessor once")
        lineage_fields = (
            "stage",
            "study",
            "family",
            "request_kind",
            "subject_id",
            "arm",
            "requested_model",
            "requested_reasoning_effort",
            "requested_service_tier",
        )
        for predecessor in predecessor_entries:
            retry = conditional_by_predecessor[predecessor["request_id"]]
            if any(retry[field] != predecessor[field] for field in lineage_fields):
                raise StateError("conditional request lineage fields drift")
    if not isinstance(budget, dict) or set(budget) != BUDGET_FIELDS:
        raise StateError("request manifest budget has unexpected fields")
    if budget != _expected_budget(required_entries, conditional_entries):
        raise StateError("request manifest budget does not match its entries")


def load_request_manifest(path: Path) -> dict[str, Any]:
    target = assert_nofollow(path, kind="file")
    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise StateError(f"request manifest cannot be read: {target}: {exc}") from None
    value = _json_object(raw, target)
    if set(value) != MANIFEST_FIELDS:
        raise StateError("request manifest has unexpected fields")
    if value.get("schema_version") != "frontier-provider-request-manifest/1.0":
        raise StateError("request manifest schema version is invalid")
    _require_nonempty(value.get("campaign_id"), "campaign_id")
    _verify_self_hash(value, "manifest_hash")
    if raw != canonical_bytes(value) + b"\n":
        raise StateError("request manifest bytes are not canonical")
    _validate_request_partitions(
        value.get("required_requests"),
        value.get("conditional_requests"),
        value.get("budget"),
    )
    return value


def build_request_manifest(
    *,
    campaign_id: str,
    required_requests: list[dict[str, Any]],
    conditional_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build and validate the one frozen provider-request inventory."""
    _require_nonempty(campaign_id, "campaign_id")
    budget = _expected_budget(required_requests, conditional_requests)
    _validate_request_partitions(required_requests, conditional_requests, budget)
    return _self_hashed(
        {
            "schema_version": "frontier-provider-request-manifest/1.0",
            "campaign_id": campaign_id,
            "required_requests": required_requests,
            "conditional_requests": conditional_requests,
            "budget": budget,
            "manifest_hash": "",
        },
        "manifest_hash",
    )


def write_request_manifest(
    path: Path,
    *,
    campaign_id: str,
    required_requests: list[dict[str, Any]],
    conditional_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Write the lower-level frozen manifest exactly once."""
    target = assert_nofollow(path, allow_absent_leaf=True)
    if target.exists():
        raise StateError("request manifest already exists")
    manifest = build_request_manifest(
        campaign_id=campaign_id,
        required_requests=required_requests,
        conditional_requests=conditional_requests,
    )
    _atomic_write(
        target,
        canonical_bytes(manifest) + b"\n",
        replace=False,
    )
    observed = load_request_manifest(target)
    if observed != manifest:
        raise StateError("request manifest post-read differs")
    return observed


def initialize_attempt(
    root: Path,
    *,
    attempt_id: str,
    campaign_id: str,
    plan_sha256: str,
    candidate_revision: str,
    candidate_source_tree_hash: str,
    candidate_plugin_tree_hash: str,
    controller_content_hash: str,
    evaluator_source_hash: str,
    phase_contract_path: Path,
    request_manifest_path: Path,
    stage: str,
    continuation_token: str,
) -> dict[str, Any]:
    """Bind one manifest and phase contract, resuming exact local prefixes."""
    root = assert_nofollow(root, kind="directory")
    request_manifest_path = assert_nofollow(
        request_manifest_path,
        kind="file",
    )
    phase_contract_path = assert_nofollow(
        phase_contract_path,
        kind="file",
    )
    try:
        relative_manifest = request_manifest_path.relative_to(root)
        relative_contract = phase_contract_path.relative_to(root)
    except ValueError:
        raise StateError(
            "manifest or phase contract is outside the attempt root"
        ) from None
    if (
        len(relative_manifest.parts) != 1
        or len(relative_contract.parts) != 1
        or relative_manifest == relative_contract
    ):
        raise StateError(
            "manifest and phase contract must be distinct direct children"
        )
    base_names = {relative_manifest.name, relative_contract.name}
    registry_names = base_names | {"attempt-registry.json"}
    state_names = registry_names | {"stage-state.json"}
    complete_names = state_names | {"provider-ledger.jsonl"}
    observed_names = {path.name for path in root.iterdir()}
    if observed_names not in (
        base_names,
        registry_names,
        state_names,
        complete_names,
    ):
        raise StateError("attempt root is not an authorized prefix")
    manifest = load_request_manifest(request_manifest_path)
    if manifest["campaign_id"] != campaign_id:
        raise StateError("request manifest campaign identity drift")
    for field, value in (
        ("attempt_id", attempt_id),
        ("campaign_id", campaign_id),
        ("stage", stage),
        ("continuation_token", continuation_token),
    ):
        _require_nonempty(value, field)
    if REVISION_PATTERN.fullmatch(candidate_revision) is None:
        raise StateError("candidate_revision must be a full Git object ID")
    for field, value in (
        ("plan_sha256", plan_sha256),
        ("candidate_source_tree_hash", candidate_source_tree_hash),
        ("candidate_plugin_tree_hash", candidate_plugin_tree_hash),
        ("controller_content_hash", controller_content_hash),
        ("evaluator_source_hash", evaluator_source_hash),
    ):
        _require_hash(value, field)

    registry = _self_hashed({
        "schema_version": "frontier-attempt-registry/2.0",
        "attempt_id": attempt_id,
        "campaign_id": campaign_id,
        "plan_sha256": plan_sha256,
        "candidate_revision": candidate_revision,
        "candidate_source_tree_hash": candidate_source_tree_hash,
        "candidate_plugin_tree_hash": candidate_plugin_tree_hash,
        "controller_content_hash": controller_content_hash,
        "evaluator_source_hash": evaluator_source_hash,
        "phase_contract_path": relative_contract.as_posix(),
        "phase_contract_sha256": raw_hash(phase_contract_path.read_bytes()),
        "request_manifest_path": relative_manifest.as_posix(),
        "request_manifest_sha256": raw_hash(request_manifest_path.read_bytes()),
        "state_path": "stage-state.json",
        "provider_ledger_path": "provider-ledger.jsonl",
        "continuation_token_hash": raw_hash(continuation_token.encode("utf-8")),
        "registry_hash": "",
    }, "registry_hash")
    state = _self_hashed({
        "schema_version": "frontier-stage-state/1.0",
        "attempt_id": attempt_id,
        "sequence": 0,
        "stage": stage,
        "status": "initialized",
        "zero_call_restart_used": False,
        "continuation_token_consumed": False,
        "previous_state_hash": None,
        "registry_hash": registry["registry_hash"],
        "state_hash": "",
    }, "state_hash")

    def write_or_verify(path: Path, payload: bytes) -> None:
        if path.exists() or path.is_symlink():
            target = assert_nofollow(path, kind="file")
            if target.read_bytes() != payload:
                raise StateError(
                    f"attempt initialization prefix differs: {path.name}"
                )
            return
        _atomic_write(path, payload, replace=False)
        if assert_nofollow(path, kind="file").read_bytes() != payload:
            raise StateError(
                f"attempt initialization readback differs: {path.name}"
            )

    write_or_verify(
        root / "attempt-registry.json",
        canonical_bytes(registry) + b"\n",
    )
    write_or_verify(
        root / "stage-state.json",
        canonical_bytes(state) + b"\n",
    )
    write_or_verify(root / "provider-ledger.jsonl", b"")
    observed_registry, observed_state = load_attempt(root)
    if observed_registry != registry or observed_state != state:
        raise StateError("attempt initialization readback differs")
    return observed_state


def _load_registry_and_manifest(
    root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = assert_nofollow(root, kind="directory")
    registry = load_json(root / "attempt-registry.json")
    if set(registry) != REGISTRY_FIELDS:
        raise StateError("attempt registry has unexpected fields")
    if registry.get("schema_version") != "frontier-attempt-registry/2.0":
        raise StateError("attempt registry schema version is invalid")
    _verify_self_hash(registry, "registry_hash")
    for field in ("attempt_id", "campaign_id"):
        _require_nonempty(registry.get(field), field)
    if REVISION_PATTERN.fullmatch(str(registry.get("candidate_revision"))) is None:
        raise StateError("attempt registry candidate revision is invalid")
    for field in (
        "plan_sha256",
        "candidate_source_tree_hash",
        "candidate_plugin_tree_hash",
        "controller_content_hash",
        "evaluator_source_hash",
        "phase_contract_sha256",
        "request_manifest_sha256",
        "continuation_token_hash",
        "registry_hash",
    ):
        _require_hash(registry.get(field), field)
    if (
        registry.get("state_path") != "stage-state.json"
        or registry.get("provider_ledger_path") != "provider-ledger.jsonl"
    ):
        raise StateError("attempt registry state or ledger path drift")
    relative_paths = {
        label: Path(str(registry.get(field)))
        for label, field in (
            ("manifest", "request_manifest_path"),
            ("phase contract", "phase_contract_path"),
        )
    }
    for label, relative in relative_paths.items():
        if (
            relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name in {"", ".", ".."}
        ):
            raise StateError(
                f"attempt registry {label} path is not a direct child"
            )
    if len(set(relative_paths.values())) != 2:
        raise StateError("attempt registry artifact paths collide")
    manifest_path = assert_nofollow(
        root / relative_paths["manifest"],
        kind="file",
    )
    raw = manifest_path.read_bytes()
    if raw_hash(raw) != registry["request_manifest_sha256"]:
        raise StateError("bound request manifest raw hash drift")
    contract_path = assert_nofollow(
        root / relative_paths["phase contract"],
        kind="file",
    )
    if raw_hash(contract_path.read_bytes()) != registry[
        "phase_contract_sha256"
    ]:
        raise StateError("bound phase contract raw hash drift")
    manifest = load_request_manifest(manifest_path)
    if manifest["campaign_id"] != registry["campaign_id"]:
        raise StateError("attempt registry and request manifest differ")
    return registry, manifest


def load_attempt(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    registry, manifest = _load_registry_and_manifest(root)
    state = load_json(root / "stage-state.json")
    _verify_self_hash(state, "state_hash")
    if state.get("registry_hash") != registry["registry_hash"]:
        raise StateError("state does not bind the immutable registry")
    if state.get("attempt_id") != registry.get("attempt_id"):
        raise StateError("attempt identity drift")
    _verify_ledger(root / registry["provider_ledger_path"], manifest)
    return registry, state


def transition(
    root: Path,
    *,
    expected_state_hash: str,
    stage: str,
    status: str,
    zero_call_restart_used: bool | None = None,
    continuation_token_consumed: bool | None = None,
) -> dict[str, Any]:
    registry, current = load_attempt(root)
    if current["state_hash"] != expected_state_hash:
        raise StateError("state compare-and-swap precondition failed")
    if current["status"] in {"complete", "failed", "blocked"}:
        raise StateError("terminal state cannot transition")
    next_state = {
        **current,
        "sequence": current["sequence"] + 1,
        "stage": stage,
        "status": status,
        "previous_state_hash": current["state_hash"],
        "registry_hash": registry["registry_hash"],
    }
    if zero_call_restart_used is not None:
        next_state["zero_call_restart_used"] = zero_call_restart_used
    if continuation_token_consumed is not None:
        next_state["continuation_token_consumed"] = continuation_token_consumed
    next_state = _self_hashed(next_state, "state_hash")
    write_json(root / registry["state_path"], next_state)
    _, observed = load_attempt(root)
    if observed != next_state:
        raise StateError("state post-read differs from the committed transition")
    return next_state


def ledger_rows(path: Path) -> list[dict[str, Any]]:
    target = assert_nofollow(path, kind="file")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        target.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        try:
            row = _json_object(line.encode("utf-8"), target)
        except StateError as exc:
            raise StateError(
                f"invalid provider ledger row {line_number}: {exc}",
            ) from None
        if line.encode("utf-8") != canonical_bytes(row):
            raise StateError(
                f"provider ledger row {line_number} is not canonical",
            )
        rows.append(row)
    return rows


def _request_entries(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        entry["request_id"]: entry
        for entry in [
            *manifest["required_requests"],
            *manifest["conditional_requests"],
        ]
    }


def request_entry(root: Path, request_id: str) -> dict[str, Any]:
    """Return one exact frozen descriptor."""
    _require_nonempty(request_id, "request_id")
    _, manifest = _load_registry_and_manifest(root)
    entry = _request_entries(manifest).get(request_id)
    if entry is None:
        raise StateError("provider request is outside the request manifest")
    return dict(entry)


def native_attempt_receipt(
    entry: dict[str, Any],
    *,
    terminal_status: str,
    failure_class: str | None = None,
) -> dict[str, Any]:
    if terminal_status not in {"completed", "failed"}:
        raise StateError("native receipt terminal status is invalid")
    if failure_class is not None and (
        terminal_status != "failed"
        or not isinstance(failure_class, str)
        or not failure_class
    ):
        raise StateError("native receipt failure class is invalid")
    value = {
        "request_id": entry["request_id"],
        "entry_hash": canonical_hash(entry),
        "input_binding_hash": entry["input_binding_hash"],
        "output_schema_hash": entry["output_schema_hash"],
        "terminal_status": terminal_status,
        "failure_class": failure_class,
    }
    return {**value, "receipt_hash": canonical_hash(value)}


def validate_native_attempt_receipt(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "request_id",
            "entry_hash",
            "input_binding_hash",
            "output_schema_hash",
            "terminal_status",
            "failure_class",
            "receipt_hash",
        }
        or value["terminal_status"] not in {"completed", "failed"}
        or value["receipt_hash"]
        != canonical_hash({
            key: item for key, item in value.items() if key != "receipt_hash"
        })
        or (
            value["failure_class"] is not None
            and (
                value["terminal_status"] != "failed"
                or not isinstance(value["failure_class"], str)
                or not value["failure_class"]
            )
        )
    ):
        raise StateError("native attempt receipt is invalid")
    return value


def execute_bound_entry(
    *,
    attempt_root: Path,
    entry: dict[str, Any],
    request: dict[str, Any],
    effect_root: Path,
    result_root: Path,
    effect: Callable[[], dict[str, Any]],
    activation_receipts: list[dict[str, Any]] | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, str],
    dict[str, str],
    dict[str, str],
]:
    effect_root.mkdir(parents=True, exist_ok=True)
    request_path = effect_root / "request.json"
    result_path = effect_root / "result.json"
    receipt_path = effect_root / "native-receipt.json"
    write_or_verify_json(request_path, request)
    ledger_ids = {
        row["request_id"]
        for row in verify_ledger(attempt_root / "provider-ledger.jsonl")
    }
    result = None
    receipt = None
    if entry["request_id"] in ledger_ids:
        terminal = (result_path.is_file(), receipt_path.is_file())
        if terminal == (True, True):
            result = load_json(result_path)
            receipt = validate_native_attempt_receipt(load_json(receipt_path))
        elif terminal != (False, False):
            raise StateError("terminal request artifacts are incomplete")
    else:
        reserve_provider_request(
            attempt_root,
            request_id=entry["request_id"],
            entry_hash=canonical_hash(entry),
            native_receipts=activation_receipts,
        )
    if result is None:
        try:
            result = effect()
        except Exception as exc:
            result = {
                "schema_version": "frontier-host-failure/1.0",
                "terminal_status": "failed",
                "failure_class": None,
                "exception_type": type(exc).__name__,
            }
        terminal_status = result.get("terminal_status")
        if terminal_status not in {"completed", "failed"}:
            raise StateError("host effect has no terminal status")
        failure_class = (
            "official_transient"
            if (
                terminal_status == "failed"
                and result.get("failure_class") == "official_transient"
            )
            else None
        )
        receipt = native_attempt_receipt(
            entry,
            terminal_status=terminal_status,
            failure_class=failure_class,
        )
        write_or_verify_json(result_path, result)
        write_or_verify_json(receipt_path, receipt)
    projected_failure = (
        "official_transient"
        if (
            result["terminal_status"] == "failed"
            and result.get("failure_class") == "official_transient"
        )
        else None
    )
    expected = native_attempt_receipt(
        entry,
        terminal_status=result["terminal_status"],
        failure_class=projected_failure,
    )
    if receipt != expected:
        raise StateError("terminal result and native receipt differ")
    return (
        result,
        artifact_binding(receipt_path, result_root),
        artifact_binding(request_path, result_root),
        artifact_binding(result_path, result_root),
    )


def execute_compiled_plan(
    *,
    attempt_root: Path,
    study_root: Path,
    runner_path: Path,
    plan_path: Path,
    index_path: Path,
    bindings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run official plan entries once while closing the provider ledger."""
    plan = _json_object(plan_path.read_bytes(), plan_path)
    entries = {item["entry_id"]: item for item in plan["entries"]}
    if len(entries) != len(plan["entries"]):
        raise StateError("compiled plan entry identity is ambiguous")

    def index_rows() -> dict[str, dict[str, Any]]:
        if not index_path.exists():
            return {}
        rows = {}
        for position, line in enumerate(index_path.read_bytes().splitlines(), 1):
            row = _json_object(line, f"{index_path}:{position}")
            entry_id = row.get("entry_id")
            if entry_id not in entries or entry_id in rows:
                raise StateError("run index entry identity is invalid")
            rows[entry_id] = row
        return rows

    native = []
    manifest_entries = _request_entries(bound_request_manifest(attempt_root))
    for binding in bindings:
        if (
            not isinstance(binding, dict)
            or set(binding) != {"entry_id", "request_ids"}
            or binding["entry_id"] not in entries
            or not isinstance(binding["request_ids"], list)
            or not binding["request_ids"]
        ):
            raise StateError("plan provider binding is invalid")
        request_entries = [
            manifest_entries.get(request_id)
            for request_id in binding["request_ids"]
        ]
        if any(
            item is None or item["family"] != "scored"
            for item in request_entries
        ):
            raise StateError("plan provider request is outside scored manifest")
        rows = index_rows()
        ledger_ids = {
            row["request_id"]
            for row in verify_ledger(attempt_root / "provider-ledger.jsonl")
        }
        reserved = set(binding["request_ids"]) & ledger_ids
        completed = binding["entry_id"] in rows
        if (reserved or completed) and (
            reserved != set(binding["request_ids"]) or not completed
        ):
            raise StateError("reserved plan entry lacks closed runner evidence")
        if not completed:
            for item in request_entries:
                reserve_provider_request(
                    attempt_root,
                    request_id=item["request_id"],
                    entry_hash=canonical_hash(item),
                )
            arguments = [
                "python3",
                str(runner_path),
                str(plan_path),
                "--index",
                str(index_path),
                "--entry-id",
                binding["entry_id"],
            ]
            if index_path.exists():
                arguments.append("--resume")
            completed_process = subprocess.run(
                arguments,
                cwd=study_root,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": SOURCE_ROOT,
                },
                check=False,
            )
            if completed_process.returncode:
                diagnostic = (
                    completed_process.stderr or completed_process.stdout
                ).strip()[:2000]
                raise StateError(
                    "official runner failed after provider reservation: "
                    f"{diagnostic}"
                )
            rows = index_rows()
        row = rows.get(binding["entry_id"])
        if row is None:
            raise StateError("official runner emitted no bound index row")
        receipt = contained_file(
            study_root / "artifacts",
            row["receipt"]["path"],
            "official runner receipt",
        )
        if file_hash(receipt) != row["receipt"]["sha256"]:
            raise StateError("official runner receipt binding differs")
        document = _json_object(receipt.read_bytes(), receipt)
        _verify_self_hash(document, "receipt_hash")
        if (
            document["run"]["entry_id"] != binding["entry_id"]
            or document["run"]["plan_hash"] != plan["plan_hash"]
            or document["run"]["terminal"] != "completed"
            or document["run"]["valid"] is not True
        ):
            raise StateError("official runner receipt is not terminal-valid")
        native.extend(
            native_attempt_receipt(item, terminal_status="completed")
            for item in request_entries
        )
    return native


def bound_request_manifest(root: Path) -> dict[str, Any]:
    """Return the manifest bound by the immutable attempt registry."""
    _, manifest = _load_registry_and_manifest(root)
    return _json_object(canonical_bytes(manifest), "bound request manifest")


def _verify_ledger(
    path: Path,
    manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = ledger_rows(path)
    previous: str | None = None
    request_ids: set[str] = set()
    entries = _request_entries(manifest)
    for sequence, row in enumerate(rows):
        if set(row) != LEDGER_ROW_FIELDS:
            raise StateError("provider ledger row has unexpected fields")
        _verify_self_hash(row, "row_hash")
        if row["schema_version"] != "frontier-provider-ledger-row/2.0":
            raise StateError("provider ledger row schema version is invalid")
        if row["sequence"] != sequence or row["previous_row_hash"] != previous:
            raise StateError("provider ledger hash chain is discontinuous")
        if row["request_id"] in request_ids:
            raise StateError("provider request ID was reused")
        entry = entries.get(row["request_id"])
        if entry is None:
            raise StateError("provider ledger row is outside the manifest")
        if row["entry_hash"] != canonical_hash(entry):
            raise StateError("provider ledger entry hash drift")
        if row["request_manifest_hash"] != manifest["manifest_hash"]:
            raise StateError("provider ledger manifest hash drift")
        request_ids.add(row["request_id"])
        previous = row["row_hash"]
    required_ids = {
        entry["request_id"] for entry in manifest["required_requests"]
    }
    required_count = sum(
        request_id in required_ids for request_id in request_ids
    )
    conditional_count = len(rows) - required_count
    if (
        required_count > manifest["budget"]["scheduled_provider_calls"]
        or conditional_count > manifest["budget"]["retry_provider_call_cap"]
        or len(rows) > manifest["budget"]["provider_call_hard_cap"]
    ):
        raise StateError("provider ledger exceeds manifest-derived budget")
    return rows


def verify_ledger(path: Path) -> list[dict[str, Any]]:
    target = assert_nofollow(path, kind="file")
    registry, manifest = _load_registry_and_manifest(target.parent)
    expected = assert_nofollow(
        target.parent / registry["provider_ledger_path"],
        kind="file",
    )
    if target != expected:
        raise StateError("provider ledger is foreign to the attempt")
    return _verify_ledger(target, manifest)


def verify_ledger_snapshot(
    path: Path,
    request_manifest_path: Path,
) -> list[dict[str, Any]]:
    """Verify an exported ledger against its explicitly bound manifest."""
    target = assert_nofollow(path, kind="file")
    manifest = load_request_manifest(request_manifest_path)
    return _verify_ledger(target, manifest)


def _validate_native_receipts(
    manifest: dict[str, Any],
    native_receipts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(native_receipts, list):
        raise StateError("native receipt inventory must be an array")
    entries = _request_entries(manifest)
    receipts: dict[str, dict[str, Any]] = {}
    for receipt in native_receipts:
        if not isinstance(receipt, dict) or set(receipt) != NATIVE_RECEIPT_FIELDS:
            raise StateError("native receipt binding has unexpected fields")
        _verify_self_hash(receipt, "receipt_hash")
        request_id = receipt["request_id"]
        entry = entries.get(request_id)
        if entry is None or request_id in receipts:
            raise StateError("native receipt request ID is foreign or duplicated")
        if (
            receipt["entry_hash"] != canonical_hash(entry)
            or receipt["input_binding_hash"] != entry["input_binding_hash"]
            or receipt["output_schema_hash"] != entry["output_schema_hash"]
        ):
            raise StateError("native receipt does not match its request")
        if receipt["terminal_status"] not in {"completed", "failed"}:
            raise StateError("native receipt status is not terminal")
        failure_class = receipt["failure_class"]
        if failure_class not in {None, "official_transient"}:
            raise StateError("native receipt failure class is invalid")
        if failure_class == "official_transient" and (
            receipt["terminal_status"] != "failed"
            or entry["family"] != "scored"
            or entry["attempt_index"] != 0
        ):
            raise StateError("official transient classification is ineligible")
        receipts[request_id] = receipt
    return receipts


def _conditional_pair_is_active(
    manifest: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
) -> bool:
    conditional = manifest["conditional_requests"]
    if not conditional:
        return False
    predecessor_ids = conditional[0]["activation"][
        "pair_predecessor_request_ids"
    ]
    predecessors = [receipts.get(request_id) for request_id in predecessor_ids]
    return all(item is not None for item in predecessors) and any(
        item is not None and item["failure_class"] == "official_transient"
        for item in predecessors
    )


def reserve_provider_request(
    root: Path,
    *,
    request_id: str,
    entry_hash: str,
    native_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registry, _ = load_attempt(root)
    ledger_path = assert_nofollow(
        root / registry["provider_ledger_path"],
        kind="file",
    )
    descriptor = os.open(ledger_path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        observed_registry, manifest = _load_registry_and_manifest(root)
        if observed_registry != registry:
            raise StateError("attempt registry changed while reserving")
        rows = _verify_ledger(ledger_path, manifest)
        entry = _request_entries(manifest).get(request_id)
        if entry is None:
            raise StateError("provider request is outside the manifest")
        expected_entry_hash = canonical_hash(entry)
        if entry_hash != expected_entry_hash:
            raise StateError("provider request entry hash mismatch")
        existing = next(
            (row for row in rows if row["request_id"] == request_id),
            None,
        )
        if existing is not None:
            if (
                existing["entry_hash"] != entry_hash
                or existing["request_manifest_hash"]
                != manifest["manifest_hash"]
            ):
                raise StateError("request ID has a different descriptor")
            return existing
        if entry["activation"] != "required":
            receipts = _validate_native_receipts(
                manifest,
                native_receipts if native_receipts is not None else [],
            )
            reserved_ids = {row["request_id"] for row in rows}
            predecessor_ids = set(
                entry["activation"]["pair_predecessor_request_ids"]
            )
            if not predecessor_ids.issubset(reserved_ids):
                raise StateError("retry predecessors were not reserved")
            if not predecessor_ids.issubset(receipts):
                raise StateError("retry predecessors are not both terminal")
            if not set(receipts).issubset(reserved_ids):
                raise StateError("retry activation uses an unreserved receipt")
            if not _conditional_pair_is_active(manifest, receipts):
                raise StateError("conditional retry predicate is not satisfied")
        row = _self_hashed({
            "schema_version": "frontier-provider-ledger-row/2.0",
            "sequence": len(rows),
            "request_id": request_id,
            "entry_hash": entry_hash,
            "request_manifest_hash": manifest["manifest_hash"],
            "previous_row_hash": rows[-1]["row_hash"] if rows else None,
            "row_hash": "",
        }, "row_hash")
        payload = canonical_bytes(row) + b"\n"
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written < 1:
                raise StateError("provider reservation append made no progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
        if _verify_ledger(ledger_path, manifest)[-1] != row:
            raise StateError("provider reservation post-read failed")
        return row
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def verify_request_completion(
    root: Path,
    native_receipts: list[dict[str, Any]],
) -> None:
    registry, _ = load_attempt(root)
    _, manifest = _load_registry_and_manifest(root)
    rows = _verify_ledger(root / registry["provider_ledger_path"], manifest)
    receipts = _validate_native_receipts(manifest, native_receipts)
    reserved_ids = {row["request_id"] for row in rows}
    if reserved_ids != set(receipts):
        raise StateError("reserved requests and terminal receipts do not close")
    required_ids = {
        entry["request_id"] for entry in manifest["required_requests"]
    }
    if not required_ids.issubset(reserved_ids):
        raise StateError("required request reservation is missing")
    conditional_ids = {
        entry["request_id"] for entry in manifest["conditional_requests"]
    }
    active = _conditional_pair_is_active(manifest, receipts)
    if active and not conditional_ids.issubset(reserved_ids):
        raise StateError("active retry pair is incomplete")
    if not active and conditional_ids.intersection(reserved_ids):
        raise StateError("inactive retry pair was consumed")


def consume_continuation_token(root: Path, token: str) -> dict[str, Any]:
    registry, state = load_attempt(root)
    if state["continuation_token_consumed"]:
        raise StateError("continuation token was already consumed")
    if raw_hash(token.encode("utf-8")) != registry["continuation_token_hash"]:
        raise StateError("continuation token mismatch")
    return transition(
        root,
        expected_state_hash=state["state_hash"],
        stage=state["stage"],
        status="resumed",
        continuation_token_consumed=True,
    )


def zero_call_restart(root: Path, *, next_stage: str) -> dict[str, Any]:
    registry, state = load_attempt(root)
    if state["zero_call_restart_used"]:
        raise StateError("zero-call restart was already used")
    if verify_ledger(root / registry["provider_ledger_path"]):
        raise StateError("zero-call restart is forbidden after a provider reservation")
    return transition(
        root,
        expected_state_hash=state["state_hash"],
        stage=next_stage,
        status="restarted",
        zero_call_restart_used=True,
    )


@contextmanager
def action_context(root: Path, lease_name: str = ".action.lease") -> Iterator[Path]:
    """Pin cwd and hold one no-follow exclusive lease for a controller action."""
    resolved = assert_nofollow(root, kind="directory")
    lease = resolved / lease_name
    descriptor = os.open(
        lease,
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    previous_cwd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.chdir(resolved)
        yield resolved
    finally:
        os.fchdir(previous_cwd)
        os.close(previous_cwd)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
