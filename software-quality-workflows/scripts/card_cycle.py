#!/usr/bin/env python3
"""Run one bounded SQW route or completion cycle without sibling control files."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator

from _workflow_reference_cards import load_json, strict_json_bytes
from local_workflow_adapter import AdapterConflict, AdapterSourceDrift, LocalWorkflowAdapter, bootstrap_v3, project_source_snapshot
from route_workflow import assess, validate_route_result


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "card-protocol.schema.json"
REGISTRY_PATH = ROOT / "registries" / "artifact-family-contracts.json"
MANIFEST_PATH = ROOT / "registries" / "reference-cards.manifest.json"
POLICY_PATH = ROOT / "registries" / "policy-owners.json"
STATE_SCHEMA_PATH = ROOT / "schemas" / "workflow-state.schema.json"
EVENT_SCHEMA_PATH = ROOT / "schemas" / "workflow-event.schema.json"
COMMAND_MAX_BYTES = 65_536
RECEIPT_MAX_BYTES = 12_288
SOURCE_FILE_MAX_BYTES = 8 * 1024 * 1024
SOURCE_TOTAL_MAX_BYTES = 32 * 1024 * 1024
SOURCE_MAX_FILES = 4_096
SURFACE_FAMILIES = [
    "public_contract",
    "data_state",
    "security_privacy",
    "runtime_platform",
    "dependency_supply_chain",
    "browser_ui",
    "performance_resource",
    "plugin_installed_surface",
    "migration_release",
    "workspace_vcs",
    "external_side_effect",
    "test_fixture_benchmark",
    "observability_operations",
    "concurrency_shared_state",
]


class CycleError(ValueError):
    def __init__(self, code: str, message: str, *, exit_code: int = 2, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.retryable = retryable


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: Any) -> str:
    return "sha256:" + sha256(_canonical(value)).hexdigest()


def _load_contracts() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    schema = load_json(SCHEMA_PATH)
    registry = load_json(REGISTRY_PATH)
    manifest = load_json(MANIFEST_PATH)
    try:
        Draft202012Validator.check_schema(schema)
        registry_schema = {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/artifactContractRegistry",
        }
        errors = list(Draft202012Validator(registry_schema).iter_errors(registry))
    except (KeyError, TypeError, ValueError) as exc:
        raise CycleError("E_CONTRACT_INVALID", "card protocol contract is invalid", exit_code=5) from exc
    if errors:
        raise CycleError("E_CONTRACT_INVALID", "artifact registry is invalid", exit_code=5)
    families = registry["families"]
    if set(registry["artifacts"].values()) != set(families):
        raise CycleError("E_CONTRACT_INVALID", "artifact registry contains missing or unused families", exit_code=5)
    for family in families.values():
        for field in ("human_def", "payload_def"):
            if family[field].split("/")[-1] not in schema["$defs"]:
                raise CycleError("E_CONTRACT_INVALID", "artifact registry references an unknown definition", exit_code=5)
    return schema, registry, manifest


def _read_command() -> dict[str, Any]:
    data = sys.stdin.buffer.read(COMMAND_MAX_BYTES + 1)
    if len(data) > COMMAND_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "command exceeds the byte limit", exit_code=4)
    try:
        value = strict_json_bytes(data, source="stdin")
    except ValueError as exc:
        raise CycleError("E_COMMAND_SCHEMA", "command is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CycleError("E_COMMAND_SCHEMA", "command must be one JSON object")
    return value


def _validate_command(schema: dict[str, Any], command: dict[str, Any]) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(command), key=lambda item: list(item.path))
    if errors:
        field = "/".join(str(part) for part in errors[0].absolute_path) or "command"
        raise CycleError("E_COMMAND_SCHEMA", f"command field is invalid: {field}")


def _read_source_file(path: Path) -> tuple[str, int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source file cannot be opened", exit_code=5) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise CycleError("E_SOURCE_UNAVAILABLE", "source contains a non-regular entry", exit_code=5)
        if before.st_size > SOURCE_FILE_MAX_BYTES:
            raise CycleError("E_SOURCE_UNAVAILABLE", "source file exceeds the byte limit", exit_code=5)
        chunks: list[bytes] = []
        remaining = SOURCE_FILE_MAX_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if len(payload) > SOURCE_FILE_MAX_BYTES or any(
            getattr(before, field) != getattr(after, field) for field in stable_fields
        ):
            raise CycleError("E_SOURCE_DRIFT", "source changed during observation", exit_code=3, retryable=True)
        return "sha256:" + sha256(payload).hexdigest(), len(payload), f"{stat.S_IMODE(before.st_mode):04o}"
    finally:
        os.close(descriptor)


def _source_observation(source_root: Path) -> dict[str, Any]:
    try:
        info = source_root.lstat()
        resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is unavailable", exit_code=5) from exc
    if source_root.is_symlink() or not stat.S_ISDIR(info.st_mode) or resolved != source_root.absolute():
        raise CycleError("E_SOURCE_UNAVAILABLE", "source root is not canonical", exit_code=5)
    repository = (resolved / ".git").exists()
    head_commit = None
    head_tree = None
    if repository:
        environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"}

        def git_value(*arguments: str) -> str:
            try:
                completed = subprocess.run(
                    ["git", "-C", str(resolved), *arguments],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                    env=environment,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise CycleError("E_SOURCE_UNAVAILABLE", "repository identity cannot be observed", exit_code=5) from exc
            value = completed.stdout.strip()
            if completed.returncode != 0 or "\n" in value:
                raise CycleError("E_SOURCE_UNAVAILABLE", "repository identity cannot be observed", exit_code=5)
            return value

        try:
            if Path(git_value("rev-parse", "--show-toplevel")).resolve(strict=True) != resolved:
                raise CycleError("E_SOURCE_UNAVAILABLE", "source root is not the repository root", exit_code=5)
        except OSError as exc:
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository root is unavailable", exit_code=5) from exc
        head_commit = git_value("rev-parse", "--verify", "HEAD")
        head_tree = git_value("rev-parse", "--verify", "HEAD^{tree}")
        if len(head_commit) not in {40, 64} or len(head_tree) not in {40, 64} or any(character not in "0123456789abcdef" for character in head_commit + head_tree):
            raise CycleError("E_SOURCE_UNAVAILABLE", "repository revision identity is invalid", exit_code=5)

    records: list[dict[str, Any]] = []
    total = 0
    for current, directories, filenames in os.walk(resolved, followlinks=False):
        directories[:] = [name for name in directories if name != ".git"]
        filenames[:] = [name for name in filenames if name != ".git"]
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        for name in directories:
            entry = current_path / name
            entry_info = entry.lstat()
            if stat.S_ISLNK(entry_info.st_mode) or not stat.S_ISDIR(entry_info.st_mode):
                raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an unsafe directory", exit_code=5)
        for name in filenames:
            entry = current_path / name
            relative = entry.relative_to(resolved).as_posix()
            if any(ord(character) < 32 for character in relative):
                raise CycleError("E_SOURCE_UNAVAILABLE", "source contains an invalid path", exit_code=5)
            content_hash, size, mode = _read_source_file(entry)
            total += size
            if total > SOURCE_TOTAL_MAX_BYTES or len(records) >= SOURCE_MAX_FILES:
                raise CycleError("E_SOURCE_UNAVAILABLE", "source observation exceeds its bound", exit_code=5)
            records.append({"path": relative, "content_hash": content_hash, "bytes": size, "mode": mode})
    return {
        "kind": "repository" if repository else "unversioned",
        "root_binding": {"dev": info.st_dev, "ino": info.st_ino},
        "head_commit": head_commit,
        "head_tree": head_tree,
        "records": records,
    }


def _capture_source(source_root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    opening = _source_observation(source_root)
    closing = _source_observation(source_root)
    if opening != closing:
        raise CycleError("E_SOURCE_DRIFT", "source changed during the stability fence", exit_code=3, retryable=True)
    return {"kind": opening["kind"], "identity_hash": _hash(opening)}, opening


def _receipt_id(receipt: dict[str, Any]) -> str:
    return _hash({key: value for key, value in receipt.items() if key != "receipt_id"})


def _validate_receipt(schema: dict[str, Any], receipt: Any, source_identity: dict[str, str], *, enforce_source: bool = True) -> dict[str, Any]:
    validator_schema = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/receipt",
    }
    errors = list(Draft202012Validator(validator_schema).iter_errors(receipt))
    if errors or not isinstance(receipt, dict):
        raise CycleError("E_RECEIPT_INVALID", "previous receipt is invalid", exit_code=3)
    if receipt["receipt_id"] != _receipt_id(receipt):
        raise CycleError("E_RECEIPT_INVALID", "previous receipt hash is invalid", exit_code=3)
    if enforce_source and receipt["source_identity"] != source_identity:
        raise CycleError("E_SOURCE_REVISION_CHANGED", "source identity changed", exit_code=3)
    return receipt


def _card(manifest: dict[str, Any], card_id: str) -> dict[str, Any]:
    matches = [card for card in manifest.get("cards", []) if card.get("card_id") == card_id]
    if len(matches) != 1:
        raise CycleError("E_CONTRACT_INVALID", "selected card is unavailable", exit_code=5)
    return matches[0]


def _next_step(manifest: dict[str, Any], route: dict[str, Any]) -> dict[str, Any]:
    if route.get("route_action") != "select_card" or route.get("primary_card") is None:
        raise CycleError("E_UNSUPPORTED_VARIANT", "this slice requires a card route", exit_code=4)
    card = _card(manifest, route["primary_card"]["card_id"])
    return {
        "kind": "card",
        "decision_id": route["selected_decision_id"],
        "card_id": card["card_id"],
        "card_path": card["path"],
        "card_hash": card["sha256"],
    }


def _route_facts(fields: dict[str, Any], **queue: Any) -> dict[str, Any]:
    is_continuation = bool(
        queue.get("pending")
        or queue.get("available")
        or queue.get("completed")
        or queue.get("just_completed")
        or queue.get("decision_request")
    )
    return {
        "schema_version": "2.0",
        "route_phase": "active_queue" if is_continuation else "entry",
        **fields,
        "surface_assessment": {
            "taxonomy_version": "sqw-route-surfaces/1",
            "coverage": "complete",
            "assessed_families": SURFACE_FAMILIES,
            "evidence_refs": ["sqw-card-cycle/1"],
        },
        "pending_decision_ids": queue.get("pending", []),
        "available_artifact_ids": queue.get("available", []),
        "completed_decision_ids": queue.get("completed", []),
        "just_completed_card_id": queue.get("just_completed"),
        "decision_request": queue.get("decision_request"),
    }


def _select(manifest: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    route = assess(facts)
    if validate_route_result(route):
        raise CycleError("E_CONTRACT_INVALID", "route result is invalid", exit_code=5)
    if route["route_action"] == "terminal":
        return {"kind": "terminal", "decision_id": None, "reason_codes": route["reason_codes"]}
    return _next_step(manifest, route)


def _completion(
    artifact_id: str,
    producer_card_id: str,
    decision_id: str,
    fields: dict[str, Any],
    blocker: str | None,
    next_decision_id: str | None,
) -> dict[str, Any]:
    payload = {
        "artifact_id": artifact_id,
        "producer_card_id": producer_card_id,
        "decision_id": decision_id,
        "fields": fields,
        "outcome": {"blocker": blocker, "decision_request": next_decision_id},
    }
    return {**payload, "content_hash": _hash(payload)}


def _enforce_human_budget(registry: dict[str, Any], artifact_id: str, fields: dict[str, Any], outcome: dict[str, Any]) -> None:
    family_name = registry["artifacts"].get(artifact_id)
    family = registry["families"].get(family_name)
    if family is None:
        raise CycleError("E_CONTRACT_INVALID", "artifact family is unavailable", exit_code=5)
    if len(_canonical({"fields": fields, "outcome": outcome})) > family["human_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "human input exceeds its family budget", exit_code=4)


def _base_receipt(manifest: dict[str, Any], source_identity: dict[str, str], next_step: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "sqw-card-receipt/1",
        "receipt_kind": "route",
        "receipt_id": "",
        "bundle_id": manifest["bundle_id"],
        "skill_id": "software-quality-workflows",
        "source_identity": source_identity,
        "next_step": next_step,
        "route_context": None,
        "completion": None,
        "scope_binding": None,
        "owner_locator": None,
        "current_lease": None,
        "state_version": None,
        "state_hash": None,
        "source_fresh": True,
        "pending_source_transition": None,
        "already_completed": False,
    }


def _route_initial(command: dict[str, Any], manifest: dict[str, Any], source_identity: dict[str, str]) -> dict[str, Any]:
    fields = command["fields"]
    receipt = _base_receipt(manifest, source_identity, _select(manifest, _route_facts(fields)))
    receipt["route_context"] = fields
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _route_resume(
    command: dict[str, Any],
    manifest: dict[str, Any],
    source_identity: dict[str, str],
    source_observation: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    adapter = LocalWorkflowAdapter(work_root, load_json(STATE_SCHEMA_PATH), load_json(EVENT_SCHEMA_PATH))
    expected_cards = {card["card_id"]: (card["path"], card["sha256"]) for card in manifest["cards"]}
    try:
        state, lease, pending_transition, source_fresh, blocked_reason = adapter.resume(
            command["fields"]["owner_locator"],
            source_identity,
            current_source_observation=source_observation,
            expected_bundle_id=manifest["bundle_id"],
            expected_policy_bundle_hash=_hash(load_json(POLICY_PATH)),
            expected_card_manifest_hash=_hash(manifest),
            expected_cards=expected_cards,
        )
    except AdapterSourceDrift as exc:
        raise CycleError("E_SOURCE_REVISION_CHANGED", str(exc), exit_code=5) from exc
    except AdapterConflict as exc:
        raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
    frontier = state["active_frontier"]
    next_step = (
        {"kind": "blocked", "decision_id": None, "reason_code": blocked_reason}
        if blocked_reason is not None
        else frontier or {"kind": "terminal", "decision_id": None, "reason_codes": ["ACTIVE_QUEUE_EMPTY"]}
    )
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "owner_locator": command["fields"]["owner_locator"],
        "current_lease": lease,
        "scope_binding": state["scope_binding"],
        "state_version": state["state_version"],
        "state_hash": state["state_hash"],
        "source_fresh": source_fresh,
        "pending_source_transition": pending_transition,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _producer_request(previous: dict[str, Any], artifact_id: str, requested: str) -> dict[str, str]:
    return {
        "decision_id": requested,
        "produced_by_card_id": previous["next_step"]["card_id"],
        "produced_artifact_id": artifact_id,
    }


def _complete_entry(
    command: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
) -> dict[str, Any]:
    entry_cards = {
        "sqw.entry.diagnose-failure", "sqw.entry.direct-change", "sqw.entry.intent-discovery",
        "sqw.entry.read-only-audit", "sqw.entry.recovery",
    }
    if previous["next_step"]["card_id"] not in entry_cards or previous["route_context"] is None:
        raise CycleError("E_RECEIPT_INVALID", "entry completion does not match the active card", exit_code=3)
    artifact_id = "workflow-intake"
    _enforce_human_budget(registry, artifact_id, command["fields"], command["outcome"])
    request = _producer_request(previous, artifact_id, "sqw.select.control.scope-authority-and-effects")
    next_step = _select(
        manifest,
        _route_facts(
            previous["route_context"],
            available=[artifact_id],
            completed=[previous["next_step"]["decision_id"]],
            just_completed=previous["next_step"]["card_id"],
            decision_request=request,
        ),
    )
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion",
        "route_context": previous["route_context"],
        "completion": _completion(
            artifact_id,
            previous["next_step"]["card_id"],
            previous["next_step"]["decision_id"],
            command["fields"],
            command["outcome"]["blocker"],
            request["decision_id"],
        ),
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _normalize_paths(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        path = PurePosixPath(value)
        if path.is_absolute() or value in {"", "."} or any(part in {"", ".", ".."} for part in path.parts):
            raise CycleError("E_SCOPE_PATH", "scope path is not canonical", exit_code=4)
        if any(ord(character) < 32 for character in value):
            raise CycleError("E_SCOPE_PATH", "scope path contains a control character", exit_code=4)
        normalized.append(path.as_posix())
    return sorted(normalized)


def _complete_scope(
    command: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
) -> dict[str, Any]:
    if previous["next_step"]["card_id"] != "sqw.control.scope-authority-and-effects":
        raise CycleError("E_RECEIPT_INVALID", "scope completion does not match the active card", exit_code=3)
    artifact_id = "control-scope-authority-and-effects"
    fields = dict(command["fields"])
    fields["allowed_reads"] = _normalize_paths(fields["allowed_reads"])
    fields["allowed_writes"] = _normalize_paths(fields["allowed_writes"])
    _enforce_human_budget(registry, artifact_id, fields, command["outcome"])
    context = previous["route_context"]
    if context["root_cause_status"] == "unknown":
        next_decision = "sqw.select.diagnosis.evidence-and-hypothesis"
    elif context["intent_status"] == "materially_underdefined":
        next_decision = "sqw.select.intent.discovery-and-freeze"
    elif context["request_mode"] == "recovery":
        next_decision = "sqw.select.recovery.repository-recovery"
    elif context["request_mode"] == "review":
        next_decision = "sqw.select.review.tier-selection"
    elif context["request_mode"] == "report":
        next_decision = "sqw.select.verify.classification-and-completion"
    else:
        next_decision = "sqw.select.test.behavior-cycle"
    request = _producer_request(previous, artifact_id, next_decision)
    prior_decision = previous["completion"]["decision_id"]
    next_step = _select(
        manifest,
        _route_facts(
            previous["route_context"],
            available=["workflow-intake", artifact_id],
            completed=[prior_decision, previous["next_step"]["decision_id"]],
            just_completed=previous["next_step"]["card_id"],
            decision_request=request,
        ),
    )
    binding_payload = {**fields, "source_identity": source_identity}
    scope_binding = {"binding_id": _hash(binding_payload), **fields}
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion",
        "completion": _completion(
            artifact_id,
            previous["next_step"]["card_id"],
            previous["next_step"]["decision_id"],
            fields,
            command["outcome"]["blocker"],
            request["decision_id"],
        ),
        "scope_binding": scope_binding,
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _complete_active(
    command: dict[str, Any],
    schema: dict[str, Any],
    manifest: dict[str, Any],
    registry: dict[str, Any],
    previous: dict[str, Any],
    source_identity: dict[str, str],
    source_snapshot: dict[str, Any],
    work_root: Path,
) -> dict[str, Any]:
    card = _card(manifest, previous["next_step"]["card_id"])
    artifact_ids = card["produced_artifact_ids"]
    if len(artifact_ids) != 1:
        raise CycleError("E_CONTRACT_INVALID", "active card must produce exactly one artifact", exit_code=5)
    artifact_id = artifact_ids[0]
    family_name = registry["artifacts"][artifact_id]
    family = registry["families"][family_name]
    if family["persistence_class"] not in {"semantic_inline", "boundary_by_contract"}:
        raise CycleError("E_UNSUPPORTED_VARIANT", "artifact persistence class is not active", exit_code=4)
    human_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": family["human_def"]}
    if list(Draft202012Validator(human_schema).iter_errors(command["fields"])):
        raise CycleError("E_COMMAND_SCHEMA", "human fields do not match the routed artifact family")
    _enforce_human_budget(registry, artifact_id, command["fields"], command["outcome"])
    if command["outcome"]["blocker"] is not None:
        raise CycleError("E_UNSUPPORTED_VARIANT", "blocked durable completion requires the blocked route slice", exit_code=4)
    completion = _completion(
        artifact_id,
        previous["next_step"]["card_id"],
        previous["next_step"]["decision_id"],
        command["fields"],
        None,
        command["outcome"]["decision_request"],
    )
    completion["source_transition"] = previous["pending_source_transition"]
    completion["content_hash"] = _hash({key: value for key, value in completion.items() if key != "content_hash"})
    if len(_canonical(completion)) > family["payload_max_bytes"]:
        raise CycleError("E_COMMAND_BUDGET", "completion payload exceeds its family budget", exit_code=4)
    materialized = family["persistence_class"] == "boundary_by_contract"
    artifact_payload = _canonical({key: value for key, value in completion.items() if key != "content_hash"}) + b"\n" if materialized else None
    content_locator = {
        "schema_version": "content-locator/1",
        "content_kind": "artifact",
        "artifact_id": artifact_id,
        "content_hash": completion["content_hash"],
        "bytes": len(artifact_payload),
    } if materialized else None

    def select_next(state: dict[str, Any], current_completion: dict[str, Any]) -> dict[str, Any]:
        decision_by_card = {item["card_id"]: item["decision_id"] for item in manifest["cards"]}
        inline = [entry.get("completion", {}) for entry in state["card_completions"] if entry["storage"] == "inline"]
        materialized_entries = [entry for entry in state["card_completions"] if entry["storage"] == "materialized"]
        available = [item["artifact_id"] for item in inline if isinstance(item.get("artifact_id"), str)]
        available.extend(item["artifact_id"] for item in materialized_entries)
        completed = [item["decision_id"] for item in inline if isinstance(item.get("decision_id"), str)]
        completed.extend(decision_by_card[item["card_id"]] for item in materialized_entries)
        available.append(current_completion["artifact_id"])
        completed.append(current_completion["decision_id"])
        requested = current_completion["outcome"]["decision_request"]
        decision_request = None if requested is None else {
            "decision_id": requested,
            "produced_by_card_id": current_completion["producer_card_id"],
            "produced_artifact_id": current_completion["artifact_id"],
        }
        context = {
            "request_mode": state["request_mode"],
            "intent_status": "adequate",
            "root_cause_status": "known",
            "implicated_surfaces": [],
            "unknown_implicated_facts": [],
            "persistence_need": "durable",
            "delegation_need": "none",
            "external_side_effect": "none",
        }
        return _select(
            manifest,
            _route_facts(
                context,
                available=available,
                completed=completed,
                just_completed=current_completion["producer_card_id"],
                decision_request=decision_request,
            ),
        )

    adapter = LocalWorkflowAdapter(work_root, load_json(STATE_SCHEMA_PATH), load_json(EVENT_SCHEMA_PATH))
    try:
        state, lease, completion_outcome = adapter.complete_card(
            previous["owner_locator"],
            previous,
            source_identity,
            completion,
            select_next,
            current_source_snapshot=source_snapshot,
            materialized_payload=artifact_payload,
            content_locator=content_locator,
            expected_bundle_id=manifest["bundle_id"],
            expected_policy_bundle_hash=_hash(load_json(POLICY_PATH)),
            expected_card_manifest_hash=_hash(manifest),
            expected_cards={item["card_id"]: (item["path"], item["sha256"]) for item in manifest["cards"]},
        )
    except AdapterSourceDrift as exc:
        raise CycleError("E_SOURCE_REVISION_CHANGED", str(exc), exit_code=5) from exc
    except AdapterConflict as exc:
        raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
    blocked_reason = completion_outcome.split(":", 1)[1] if completion_outcome.startswith("replayed_blocked:") else None
    next_step = (
        {"kind": "blocked", "decision_id": None, "reason_code": blocked_reason}
        if blocked_reason is not None
        else state["active_frontier"] or {"kind": "terminal", "decision_id": None, "reason_codes": ["ACTIVE_QUEUE_EMPTY"]}
    )
    receipt = _base_receipt(manifest, source_identity, next_step)
    receipt.update({
        "receipt_kind": "completion",
        "completion": ({
            "artifact_id": completion["artifact_id"],
            "content_hash": completion["content_hash"],
            "producer_card_id": completion["producer_card_id"],
            "decision_id": completion["decision_id"],
            "outcome": completion["outcome"],
            "content_locator": content_locator,
        } if materialized else completion),
        "scope_binding": state["scope_binding"],
        "owner_locator": previous["owner_locator"],
        "current_lease": lease,
        "state_version": state["state_version"],
        "state_hash": state["state_hash"],
        "source_fresh": blocked_reason is None,
        "already_completed": completion_outcome != "committed",
    })
    receipt["receipt_id"] = _receipt_id(receipt)
    return receipt


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.input != "-":
        raise CycleError("E_COMMAND_SCHEMA", "--input must be stdin")
    schema, registry, manifest = _load_contracts()
    command = _read_command()
    _validate_command(schema, command)
    is_route = command["contract_id"] in {"sqw.route.initial/1", "sqw.route.resume/1"}
    expected_subcommand = "route" if is_route else "complete"
    if args.subcommand != expected_subcommand:
        raise CycleError("E_COMMAND_SCHEMA", "subcommand does not match contract")
    durable_scope = command["contract_id"] == "sqw.complete.scope/1" and command["fields"]["mode"] in {"M2", "M3"}
    durable_resume = command["contract_id"] == "sqw.route.resume/1"
    durable_active = command["contract_id"] == "sqw.complete.card/1"
    if (durable_scope or durable_resume or durable_active) and args.work_root is None:
        raise CycleError("E_ROOT_ROLE", "durable command requires a work root")
    if not (durable_scope or durable_resume or durable_active) and args.work_root is not None:
        raise CycleError("E_ROOT_ROLE", "this command does not accept a work root")
    source_identity, source_observation = _capture_source(Path(args.source_root))
    if command["contract_id"] == "sqw.route.initial/1":
        receipt = _route_initial(command, manifest, source_identity)
    elif durable_resume:
        receipt = _route_resume(command, manifest, source_identity, source_observation, Path(args.work_root))
    else:
        previous = _validate_receipt(schema, command["previous_receipt"], source_identity, enforce_source=not durable_active)
        if previous["bundle_id"] != manifest["bundle_id"]:
            raise CycleError("E_RECEIPT_INVALID", "previous receipt bundle is stale", exit_code=3)
        if command["contract_id"] == "sqw.complete.entry/1":
            receipt = _complete_entry(command, manifest, registry, previous, source_identity)
        elif command["contract_id"] == "sqw.complete.scope/1":
            receipt = _complete_scope(command, manifest, registry, previous, source_identity)
            if durable_scope:
                try:
                    state, locator, lease = bootstrap_v3(
                        Path(args.work_root),
                        Path(args.source_root),
                        bundle_id=manifest["bundle_id"],
                        policy_bundle_hash=_hash(load_json(POLICY_PATH)),
                        card_manifest_hash=_hash(manifest),
                        mode=command["fields"]["mode"],
                        request_mode=previous["route_context"]["request_mode"],
                        entry_completion=previous["completion"],
                        scope_completion=receipt["completion"],
                        scope_binding=receipt["scope_binding"],
                        source_identity=source_identity,
                        source_snapshot=project_source_snapshot(source_observation, source_identity, receipt["scope_binding"]),
                        next_step=receipt["next_step"],
                    )
                except AdapterConflict as exc:
                    raise CycleError("E_ORPHAN_CONFLICT", str(exc), exit_code=5) from exc
                receipt["owner_locator"] = locator
                receipt["current_lease"] = lease
                receipt["state_version"] = state["state_version"]
                receipt["state_hash"] = state["state_hash"]
                receipt["receipt_id"] = _receipt_id(receipt)
        elif durable_active:
            source_snapshot = project_source_snapshot(source_observation, source_identity, previous["scope_binding"])
            receipt = _complete_active(command, schema, manifest, registry, previous, source_identity, source_snapshot, Path(args.work_root))
        else:
            raise CycleError("E_UNSUPPORTED_VARIANT", "command contract is not active", exit_code=4)
    receipt_validator = {
        "$schema": schema["$schema"],
        "$defs": schema["$defs"],
        "$ref": "#/$defs/receipt",
    }
    if list(Draft202012Validator(receipt_validator).iter_errors(receipt)):
        raise CycleError("E_CONTRACT_INVALID", "generated receipt is invalid", exit_code=5)
    if len(_canonical(receipt)) + 1 > RECEIPT_MAX_BYTES:
        raise CycleError("E_COMMAND_BUDGET", "receipt exceeds the byte limit", exit_code=4)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    for name in ("route", "complete"):
        command = subparsers.add_parser(name)
        command.add_argument("--input", required=True)
        command.add_argument("--source-root", required=True)
        command.add_argument("--work-root")
    return parser


def _emit_error(error: CycleError) -> int:
    message = " ".join(str(error).split())[:512] or "card cycle failed"
    payload = {"code": error.code, "message": message, "retryable": error.retryable}
    encoded = _canonical(payload)
    if len(encoded) > 1_024:
        payload["message"] = "card cycle failed"
        encoded = _canonical(payload)
    sys.stderr.buffer.write(encoded + b"\n")
    return error.exit_code


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = _execute(args)
    except CycleError as exc:
        return _emit_error(exc)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return _emit_error(CycleError("E_CONTRACT_INVALID", "card cycle failed", exit_code=5))
    sys.stdout.buffer.write(_canonical(receipt) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
