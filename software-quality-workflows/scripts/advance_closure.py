#!/usr/bin/env python3
"""Accept one closure proposal and publish a crash-replayable deterministic transition."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
from fnmatch import fnmatchcase
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

from _closure import ClosureError, apply_event, rank_candidates
from _workflow_state import (
    InputError,
    canonical_artifact_hash,
    canonical_hash,
    contains_secret_like,
    load_json,
    load_json_lines,
    patterns_may_overlap,
    validate_against_schema,
    validate_closure_artifact,
    validate_review_result,
)
from local_workflow_adapter import AdapterConflict, _atomic_write, _exclusive_guard, _json_bytes, _sync_directory
from validate_verifier_bundle import validate_bundle
from validate_workflow_state import validate_event_stream, validate_state, validate_transition


ROOT = Path(__file__).resolve().parents[1]
STATE_SCHEMA = ROOT / "schemas" / "workflow-state.schema.json"
EVENT_SCHEMA = ROOT / "schemas" / "workflow-event.schema.json"
ARTIFACT_SCHEMA = ROOT / "schemas" / "closure-artifacts.schema.json"
REVIEW_SCHEMA = ROOT / "schemas" / "review-result.schema.json"
VERIFIER_SCHEMA = ROOT / "schemas" / "verifier-bundle.schema.json"
ARTIFACT_REF_RE = re.compile(r"^artifact:([a-z][a-z0-9-]*)/([A-Za-z0-9][A-Za-z0-9._-]{0,127})$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
WRITING_ROOT = ROOT.parent / "writing-plans"
WRITING_CONTRACT_SCHEMA = WRITING_ROOT / "schemas" / "closure-contract.schema.json"
WRITING_CONTRACT_VALIDATOR = WRITING_ROOT / "scripts" / "validate_closure_contract.py"
_WRITING_VALIDATOR_CACHE: tuple[Any, dict[str, Any]] | None = None
GENESIS_EVENT_HASH = "sha256:" + "0" * 64
CONTROLLER_EVENT_FIELDS = {"previous_event_hash", "source_state_hash", "result_state_hash", "event_hash"}
MAX_ARTIFACTS_PER_TRANSITION = 1000
MAX_HISTORICAL_ARTIFACTS = 5000


class ControllerConflict(RuntimeError):
    pass


STABLE_ERROR_CODES = {
    "E_SCHEMA_INVALID", "E_HASH_MISMATCH", "E_EPOCH_MISMATCH", "E_SOURCE_DRIFT", "E_SCOPE_VIOLATION",
    "E_PROTECTED_SURFACE_CHANGED", "E_UNAUTHORIZED_TRANSITION", "E_VERIFIER_UNRESOLVED", "E_VERIFIER_UNSTABLE",
    "E_VERIFIER_NONDISCRIMINATING", "E_BASELINE_UNSTABLE", "E_BUDGET_EXHAUSTED", "E_LOCK_CONFLICT",
    "E_ARTIFACT_STALE", "E_PUBLICATION_CEILING", "E_OPTIONAL_OWNER_MISSING",
}


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, AdapterConflict):
        return "E_LOCK_CONFLICT"
    if isinstance(exc, InputError):
        return "E_SCHEMA_INVALID"
    message = str(exc)
    embedded = re.search(r"\b(E_[A-Z_]+)\b", message)
    if embedded and embedded.group(1) in STABLE_ERROR_CODES:
        return embedded.group(1)
    lowered = message.lower()
    if "lock" in lowered or "overwrite" in lowered or "already exists" in lowered:
        return "E_LOCK_CONFLICT"
    if "source revision" in lowered or "source_drift" in lowered:
        return "E_SOURCE_DRIFT"
    if "protected" in lowered:
        return "E_PROTECTED_SURFACE_CHANGED"
    if "scope" in lowered or "allowed write" in lowered:
        return "E_SCOPE_VIOLATION"
    if "epoch" in lowered:
        return "E_EPOCH_MISMATCH"
    if "historical artifact" in lowered or "bound artifact" in lowered or "artifact bindings differ" in lowered or "artifact is missing" in lowered:
        return "E_ARTIFACT_STALE"
    if "hash" in lowered or "digest" in lowered or "changed after acceptance" in lowered:
        return "E_HASH_MISMATCH"
    if "budget" in lowered:
        return "E_BUDGET_EXHAUSTED"
    if "controller-only" in lowered or "actor" in lowered or "not eligible" in lowered or "state_version" in lowered or "promotion" in lowered or "conflict" in lowered:
        return "E_UNAUTHORIZED_TRANSITION"
    return "E_SCHEMA_INVALID"


def _writing_validator() -> tuple[Any, dict[str, Any]]:
    global _WRITING_VALIDATOR_CACHE
    if _WRITING_VALIDATOR_CACHE is not None:
        return _WRITING_VALIDATOR_CACHE
    if not WRITING_CONTRACT_VALIDATOR.is_file() or not WRITING_CONTRACT_SCHEMA.is_file():
        raise ControllerConflict("writing-plans Closure Contract validator is unavailable")
    scripts_path = str(WRITING_CONTRACT_VALIDATOR.parent)
    sys.path.insert(0, scripts_path)
    try:
        spec = importlib.util.spec_from_file_location("_sqw_writing_contract_validator", WRITING_CONTRACT_VALIDATOR)
        if spec is None or spec.loader is None:
            raise ControllerConflict("cannot load writing-plans Closure Contract validator")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if sys.path and sys.path[0] == scripts_path:
            sys.path.pop(0)
    _WRITING_VALIDATOR_CACHE = (module.validate_contract, load_json(WRITING_CONTRACT_SCHEMA))
    return _WRITING_VALIDATOR_CACHE


def _event_digest(event: dict[str, Any], *, include_artifact_bindings: bool = False) -> str:
    canonical = deepcopy(event)
    if not include_artifact_bindings and isinstance(canonical.get("payload"), dict):
        canonical["payload"].pop("artifact_bindings", None)
        for field in CONTROLLER_EVENT_FIELDS:
            canonical.pop(field, None)
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _accepted_event_hash(event: dict[str, Any]) -> str:
    canonical = deepcopy(event)
    canonical.pop("event_hash", None)
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _validate_event_chain(events: list[dict[str, Any]]) -> None:
    previous_hash = GENESIS_EVENT_HASH
    previous_result: str | None = None
    for event in events:
        if not CONTROLLER_EVENT_FIELDS.issubset(event):
            raise ControllerConflict(f"accepted event lacks controller hash chain: {event.get('event_id')}")
        if event.get("previous_event_hash") != previous_hash or event.get("event_hash") != _accepted_event_hash(event):
            raise ControllerConflict(f"accepted event hash chain is invalid: {event.get('event_id')}")
        if previous_result is not None and event.get("source_state_hash") != previous_result:
            raise ControllerConflict(f"accepted event state-hash chain is invalid: {event.get('event_id')}")
        if not all(isinstance(event.get(field), str) and HASH_RE.fullmatch(event[field]) for field in ("source_state_hash", "result_state_hash", "event_hash")):
            raise ControllerConflict(f"accepted event hash fields are malformed: {event.get('event_id')}")
        previous_hash = event["event_hash"]
        previous_result = event["result_state_hash"]


def _inside(root: Path, path: Path) -> Path:
    absolute = path if path.is_absolute() else Path.cwd() / path
    if absolute.is_symlink():
        raise ControllerConflict(f"controller path must not be a symlink: {path}")
    resolved = absolute.parent.resolve() / absolute.name
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ControllerConflict(f"controller path must remain inside artifacts root: {path}") from exc
    return resolved


def _artifact_path(root: Path, ref: str) -> Path:
    match = ARTIFACT_REF_RE.fullmatch(ref)
    if match is None:
        raise ControllerConflict(f"invalid artifact ref: {ref}")
    return _inside(root, root / match.group(1) / f"{match.group(2)}.json")


def _supporting_refs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if ARTIFACT_REF_RE.fullmatch(value) else []
    if isinstance(value, dict):
        return [ref for child in value.values() for ref in _supporting_refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _supporting_refs(child)]
    return []


def _load_artifacts(root: Path, event: dict[str, Any], state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    pending = list(payload.get("artifact_refs", [])) if isinstance(payload.get("artifact_refs"), list) else []
    run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
    for field in ("contract_ref", "baseline_ref", "verifier_bundle_ref"):
        binding = run.get(field) if isinstance(run.get(field), dict) else {}
        if isinstance(binding.get("artifact_ref"), str):
            pending.append(binding["artifact_ref"])
    if isinstance(run.get("incumbent_candidate_ref"), str):
        pending.append(run["incumbent_candidate_ref"])
    if isinstance(run.get("terminal_certificate_ref"), str):
        pending.append(run["terminal_certificate_ref"])
    for field in ("active_candidate_refs", "active_counterexample_refs"):
        if isinstance(run.get(field), list):
            pending.extend(ref for ref in run[field] if isinstance(ref, str))
    loaded: dict[str, dict[str, Any]] = {}
    while pending:
        ref = pending.pop(0)
        if not isinstance(ref, str) or ref in loaded:
            continue
        if len(loaded) >= MAX_ARTIFACTS_PER_TRANSITION:
            raise ControllerConflict(f"transition artifact graph exceeds {MAX_ARTIFACTS_PER_TRANSITION} refs")
        try:
            value = load_json(_artifact_path(root, ref))
        except InputError as exc:
            raise ControllerConflict(f"artifact ref cannot be resolved immutably: {ref}: {exc}") from exc
        if not isinstance(value, dict):
            raise ControllerConflict(f"artifact must be a JSON object: {ref}")
        loaded[ref] = value
        for supporting in _supporting_refs(value):
            if supporting not in loaded:
                pending.append(supporting)
        schema_id = value.get("schema_id")
        artifact_payload = value.get("payload") if isinstance(value.get("payload"), dict) else {}
        if schema_id == "sqw://closure-artifacts/candidate-manifest/1.0" and isinstance(artifact_payload.get("parent"), str):
            pending.append(f"artifact:candidate/{artifact_payload['parent']}")
        if schema_id == "sqw://closure-artifacts/candidate-evaluation/1.0" and isinstance(artifact_payload.get("candidate_id"), str):
            pending.append(f"artifact:candidate/{artifact_payload['candidate_id']}")
        if len(pending) > MAX_ARTIFACTS_PER_TRANSITION * 4:
            raise ControllerConflict("transition artifact graph fan-out is unbounded")
    return loaded


def _artifact_bindings(artifacts: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"artifact_ref": ref, "content_hash": canonical_artifact_hash(artifact)}
        for ref, artifact in sorted(artifacts.items())
    ]


def _validate_historical_artifacts(root: Path, events: list[dict[str, Any]]) -> None:
    observed_hashes: dict[str, str] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        bindings = payload.get("artifact_bindings")
        if not isinstance(bindings, list):
            raise ControllerConflict(f"accepted event lacks controller artifact bindings: {event.get('event_id')}")
        refs: set[str] = set()
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != {"artifact_ref", "content_hash"}:
                raise ControllerConflict(f"accepted event has malformed artifact binding: {event.get('event_id')}")
            ref, expected = binding.get("artifact_ref"), binding.get("content_hash")
            if not isinstance(ref, str) or ref in refs or not isinstance(expected, str) or not HASH_RE.fullmatch(expected):
                raise ControllerConflict(f"accepted event has duplicate or invalid artifact binding: {event.get('event_id')}")
            refs.add(ref)
            if ref not in observed_hashes:
                if len(observed_hashes) >= MAX_HISTORICAL_ARTIFACTS:
                    raise ControllerConflict(f"historical artifact set exceeds {MAX_HISTORICAL_ARTIFACTS} refs")
                try:
                    artifact = load_json(_artifact_path(root, ref))
                except InputError as exc:
                    raise ControllerConflict(f"historical artifact is missing: {ref}: {exc}") from exc
                if not isinstance(artifact, dict):
                    raise ControllerConflict(f"historical artifact is malformed: {ref}")
                observed_hashes[ref] = canonical_artifact_hash(artifact)
            if observed_hashes[ref] != expected:
                raise ControllerConflict(f"historical artifact changed after acceptance: {ref}")


def _validate_generic_artifact(ref: str, artifact: dict[str, Any], state: dict[str, Any]) -> list[str]:
    required = {
        "schema_id", "artifact_id", "workflow_id", "source_revision", "scope_hash", "created_at", "producer",
        "classification", "mime_type", "command_ref", "redaction_policy", "content_hash", "payload",
    }
    errors: list[str] = []
    if set(artifact) != required:
        errors.append("generic artifact envelope fields differ from the canonical contract")
    if artifact.get("schema_id") != "sqw://artifact-envelope/1.0":
        errors.append("unsupported canonical artifact type")
    expected_id = ref.rsplit("/", 1)[-1]
    if artifact.get("artifact_id") != expected_id:
        errors.append("artifact_id differs from artifact ref")
    expected = {
        "workflow_id": state.get("workflow_id"),
        "source_revision": state.get("source", {}).get("observed_revision"),
        "scope_hash": state.get("source", {}).get("scope_hash"),
    }
    for field, value in expected.items():
        if artifact.get(field) != value:
            errors.append(f"{field} differs from workflow binding")
    if artifact.get("classification") not in {"public", "internal", "sensitive"}:
        errors.append("classification is invalid")
    if artifact.get("redaction_policy") not in {"none_required", "redacted", "external_controlled"}:
        errors.append("redaction_policy is invalid")
    if artifact.get("classification") == "sensitive" and artifact.get("redaction_policy") == "none_required":
        errors.append("sensitive artifact requires redaction or an external controlled pointer")
    producer = artifact.get("producer") if isinstance(artifact.get("producer"), dict) else {}
    if set(producer) != {"actor", "run_id"} or producer.get("actor") not in {"controller", "worker", "reviewer", "tool"} or not isinstance(producer.get("run_id"), str) or re.fullmatch(r"RUN-[A-Za-z0-9][A-Za-z0-9._-]{0,95}", producer["run_id"]) is None:
        errors.append("producer is invalid")
    for field, maximum in (("mime_type", 256), ("command_ref", 1024)):
        if not isinstance(artifact.get(field), str) or not artifact[field] or len(artifact[field]) > maximum:
            errors.append(f"{field} is missing")
    try:
        created = datetime.fromisoformat(str(artifact.get("created_at", "")).replace("Z", "+00:00"))
        if created.tzinfo is None:
            errors.append("created_at must be timezone-aware")
    except ValueError:
        errors.append("created_at is invalid")
    if not isinstance(artifact.get("content_hash"), str) or not HASH_RE.fullmatch(artifact["content_hash"]) or artifact["content_hash"] != canonical_artifact_hash(artifact):
        errors.append("content_hash does not match canonical artifact content")
    if artifact.get("redaction_policy") == "none_required" and contains_secret_like(json.dumps(artifact.get("payload"), ensure_ascii=False, sort_keys=True)):
        errors.append("unredacted payload contains credential-shaped content")
    return [f"{ref}: {message}" for message in errors]


def _pattern_within(pattern: str, ceiling: str) -> bool:
    if pattern == ceiling or ceiling == "**":
        return True
    if ceiling.endswith("/**"):
        prefix = ceiling[:-3].rstrip("/")
        return pattern.startswith(prefix + "/") and not pattern.startswith("../")
    return False


def _validate_scope_and_protected(event: dict[str, Any], artifacts: dict[str, dict[str, Any]], state: dict[str, Any]) -> list[str]:
    scope = state.get("scope") if isinstance(state.get("scope"), dict) else {}
    allowed = [item for item in scope.get("allowed_writes", []) if isinstance(item, str)]
    protected = [item for item in scope.get("protected_paths", []) if isinstance(item, str)]
    run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
    contract_binding = run.get("contract_ref") if isinstance(run.get("contract_ref"), dict) else {}
    contract = artifacts.get(contract_binding.get("artifact_ref"))
    contract_allowed: list[str] = []
    if isinstance(contract, dict):
        contract_scope = contract.get("scope") if isinstance(contract.get("scope"), dict) else {}
        contract_allowed = [item for item in contract_scope.get("allowed_write_paths", []) if isinstance(item, str)]
        surfaces = contract.get("protected_surfaces") if isinstance(contract.get("protected_surfaces"), list) else []
        protected.extend(item["path"] for item in surfaces if isinstance(item, dict) and isinstance(item.get("path"), str))
    verifier_binding = run.get("verifier_bundle_ref") if isinstance(run.get("verifier_bundle_ref"), dict) else {}
    verifier = artifacts.get(verifier_binding.get("artifact_ref"))
    if isinstance(verifier, dict):
        protected.extend(item for item in verifier.get("protected_paths", []) if isinstance(item, str))
    protected = sorted(set(protected))
    manifests = [item for item in artifacts.values() if item.get("schema_id") == "sqw://closure-artifacts/candidate-manifest/1.0"]
    errors: list[str] = []
    candidate_allowed: list[str] = []
    for manifest in manifests:
        payload = manifest.get("payload") if isinstance(manifest.get("payload"), dict) else {}
        declared_protected = [item for item in payload.get("protected_paths", []) if isinstance(item, str)]
        missing = sorted(set(protected) - set(declared_protected))
        if missing:
            errors.append(f"candidate {payload.get('candidate_id')} omits protected surfaces: {', '.join(missing)}")
        for write_pattern in payload.get("allowed_writes", []):
            if not isinstance(write_pattern, str):
                continue
            candidate_allowed.append(write_pattern)
            if not any(_pattern_within(write_pattern, ceiling) for ceiling in allowed):
                errors.append(f"candidate write pattern exceeds workflow scope: {write_pattern}")
            if contract_allowed and not any(_pattern_within(write_pattern, ceiling) for ceiling in contract_allowed):
                errors.append(f"candidate write pattern exceeds frozen contract scope: {write_pattern}")
            if any(patterns_may_overlap(write_pattern, item) for item in protected):
                errors.append(f"candidate write pattern overlaps protected surface: {write_pattern}")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    effective_allowed = candidate_allowed or allowed
    for changed in payload.get("changed_refs", []):
        if not isinstance(changed, str):
            continue
        if any(fnmatchcase(changed, item) or patterns_may_overlap(changed, item) for item in protected):
            errors.append(f"changed ref crosses protected surface: {changed}")
        if not any(fnmatchcase(changed, item) for item in effective_allowed):
            errors.append(f"changed ref exceeds allowed write scope: {changed}")
    return errors


def _validate_promotion(event: dict[str, Any], artifacts: dict[str, dict[str, Any]], state: dict[str, Any]) -> list[str]:
    if event.get("type") != "candidate_promoted":
        return []
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    refs = payload.get("artifact_refs") if isinstance(payload.get("artifact_refs"), list) else []
    manifests = [artifacts.get(ref) for ref in refs if isinstance(ref, str) and isinstance(artifacts.get(ref), dict) and artifacts[ref].get("schema_id") == "sqw://closure-artifacts/candidate-manifest/1.0"]
    if len(manifests) != 1:
        return ["promotion requires exactly one candidate manifest"]
    promoted_id = manifests[0].get("payload", {}).get("candidate_id")
    evaluations = [
        artifacts[ref]
        for ref in refs
        if isinstance(ref, str)
        and isinstance(artifacts.get(ref), dict)
        and artifacts[ref].get("schema_id") == "sqw://closure-artifacts/candidate-evaluation/1.0"
    ]
    promoted = [item for item in evaluations if item.get("payload", {}).get("candidate_id") == promoted_id]
    if len(promoted) != 1 or promoted[0].get("payload", {}).get("eligible_for_promotion") is not True:
        return ["promotion requires one eligible evaluation for the promoted candidate"]
    run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
    incumbent_ref = run.get("incumbent_candidate_ref")
    if not isinstance(incumbent_ref, str):
        return []
    incumbent = artifacts.get(incumbent_ref)
    incumbent_id = incumbent.get("payload", {}).get("candidate_id") if isinstance(incumbent, dict) else None
    if incumbent_id == promoted_id:
        return ["promotion cannot replace the incumbent with itself"]
    if run.get("active_counterexample_refs"):
        return []
    incumbent_evaluations = [item for item in evaluations if item.get("payload", {}).get("candidate_id") == incumbent_id]
    if len(incumbent_evaluations) != 1:
        return ["replacement promotion requires the incumbent evaluation or an active disproof"]
    contract_binding = run.get("contract_ref") if isinstance(run.get("contract_ref"), dict) else {}
    contract = artifacts.get(contract_binding.get("artifact_ref"))
    if not isinstance(contract, dict):
        return ["replacement promotion has no frozen contract"]
    try:
        ranked = rank_candidates([promoted[0], incumbent_evaluations[0]], contract)
    except ClosureError as exc:
        return [f"replacement ranking failed: {exc}"]
    scores = {item["candidate_id"]: item["score"] for item in ranked["ranked"]}
    if promoted_id not in scores or incumbent_id not in scores or not scores[promoted_id] < scores[incumbent_id]:
        return ["replacement candidate is not strictly better than the feasible incumbent"]
    return []


def _validate_contract(ref: str, artifact: dict[str, Any], state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    observed_revision = source.get("observed_revision", source.get("base_revision"))
    if artifact.get("status") != "frozen" or not isinstance(artifact.get("epoch"), int) or artifact.get("epoch", 0) < 1:
        errors.append("contract is not frozen with a positive epoch")
    if not isinstance(artifact.get("content_hash"), str) or not HASH_RE.fullmatch(artifact["content_hash"]):
        errors.append("contract content_hash is malformed")
    elif canonical_artifact_hash(artifact) != artifact["content_hash"]:
        errors.append("contract content_hash mismatch")
    if observed_revision != state.get("source", {}).get("observed_revision"):
        errors.append("contract source revision drift")
    if source.get("scope_hash") != state.get("source", {}).get("scope_hash"):
        errors.append("contract scope hash drift")
    if source.get("policy_bundle_hash") != state.get("policy_bundle_hash"):
        errors.append("contract policy bundle drift")
    validate_contract, schema = _writing_validator()
    violations = validate_contract(
        artifact,
        schema,
        expected_scope_hash=state.get("source", {}).get("scope_hash"),
        authority_ceiling=state.get("authority", {}).get("risk_ceiling"),
        expected_base_revision=state.get("source", {}).get("base_revision"),
        expected_policy_bundle_hash=state.get("policy_bundle_hash"),
    )
    errors.extend(f"writing contract {item.code}@{item.path}" for item in violations)
    return [f"{ref}: {message}" for message in errors]


def _enforce_contract_epoch(root: Path, events: list[dict[str, Any]], event: dict[str, Any], artifacts: dict[str, dict[str, Any]]) -> None:
    if event.get("type") != "contract_frozen":
        return
    refs = event.get("payload", {}).get("artifact_refs", []) if isinstance(event.get("payload"), dict) else []
    current = [(ref, artifacts.get(ref)) for ref in refs if isinstance(ref, str) and ref.startswith("artifact:contract/")]
    if len(current) != 1 or not isinstance(current[0][1], dict):
        raise ControllerConflict("contract_frozen requires exactly one canonical contract artifact")
    new_epoch = current[0][1].get("epoch")
    previous_epochs: list[int] = []
    for accepted in events:
        if accepted.get("type") != "contract_frozen":
            continue
        payload = accepted.get("payload") if isinstance(accepted.get("payload"), dict) else {}
        historical_refs = [ref for ref in payload.get("artifact_refs", []) if isinstance(ref, str) and ref.startswith("artifact:contract/")]
        if len(historical_refs) != 1:
            raise ControllerConflict("historical contract_frozen event has no unique contract artifact")
        historical = load_json(_artifact_path(root, historical_refs[0]))
        if not isinstance(historical, dict) or historical.get("status") != "frozen" or historical.get("content_hash") != canonical_artifact_hash(historical):
            raise ControllerConflict("historical frozen contract is missing or has changed")
        epoch = historical.get("epoch")
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ControllerConflict("historical frozen contract has an invalid epoch")
        previous_epochs.append(epoch)
    if not isinstance(new_epoch, int) or isinstance(new_epoch, bool):
        raise ControllerConflict("frozen contract epoch must be an integer")
    if not previous_epochs and new_epoch != 1:
        raise ControllerConflict("the first frozen contract must use epoch 1")
    if previous_epochs and new_epoch <= max(previous_epochs):
        raise ControllerConflict("replacement contract epoch must exceed every previously frozen epoch")


def _validate_artifacts(
    artifacts: dict[str, dict[str, Any]],
    state: dict[str, Any],
    artifact_schema: dict[str, Any],
    review_schema: dict[str, Any],
    verifier_schema: dict[str, Any],
    *,
    expected_source_revision: str | None = None,
) -> list[str]:
    errors: list[str] = []
    run = state.get("closure_run") if isinstance(state.get("closure_run"), dict) else {}
    contract_binding = run.get("contract_ref") if isinstance(run.get("contract_ref"), dict) else {}
    verifier_binding = run.get("verifier_bundle_ref") if isinstance(run.get("verifier_bundle_ref"), dict) else {}
    state_source_revision = state.get("source", {}).get("observed_revision")
    for ref, artifact in artifacts.items():
        schema_id = artifact.get("schema_id")
        if ref.startswith("artifact:contract/"):
            errors.extend(_validate_contract(ref, artifact, state))
        elif isinstance(schema_id, str) and schema_id.startswith("sqw://closure-artifacts/"):
            source_revision = expected_source_revision if expected_source_revision is not None and schema_id == "sqw://closure-artifacts/terminal-certificate/1.0" else state_source_revision
            expected_verifier_hash = "not_frozen" if schema_id == "sqw://closure-artifacts/baseline-result/1.0" else verifier_binding.get("content_hash") if verifier_binding else None
            violations = validate_closure_artifact(
                artifact,
                artifact_schema,
                expected_workflow_id=state.get("workflow_id"),
                expected_closure_epoch=contract_binding.get("epoch") if contract_binding else None,
                expected_source_revision=source_revision,
                expected_scope_hash=state.get("source", {}).get("scope_hash"),
                expected_contract_hash=contract_binding.get("content_hash") if contract_binding else None,
                expected_verifier_bundle_hash=expected_verifier_hash,
            )
            errors.extend(f"{ref}: {item.code}@{item.path}" for item in violations)
        elif ref.startswith("artifact:verifier/"):
            violations = validate_bundle(
                artifact,
                verifier_schema,
                expected_closure_epoch=contract_binding.get("epoch") if contract_binding else None,
                expected_contract_hash=contract_binding.get("content_hash") if contract_binding else None,
                expected_source_revision=state_source_revision,
                expected_scope_hash=state.get("source", {}).get("scope_hash"),
            )
            errors.extend(f"{ref}: {item.code}@{item.path}" for item in violations)
        elif ref.startswith("artifact:review/"):
            violations = validate_against_schema(artifact, review_schema, code="review.schema")
            errors.extend(f"{ref}: {item.code}@{item.path}" for item in violations)
            candidate_ref = run.get("incumbent_candidate_ref")
            candidate = artifacts.get(candidate_ref) if isinstance(candidate_ref, str) else None
            candidate_payload = candidate.get("payload") if isinstance(candidate, dict) and isinstance(candidate.get("payload"), dict) else {}
            if candidate_payload:
                coverage = artifact.get("coverage") if isinstance(artifact.get("coverage"), list) else []
                manifest = {
                    "base_revision": candidate_payload.get("base_candidate_hash"),
                    "head_revision": candidate_payload.get("patch_hash"),
                    "scope_hash": state.get("source", {}).get("scope_hash"),
                    "paths": [
                        {"path": item.get("path"), "snapshot_id": item.get("snapshot_id")}
                        for item in coverage if isinstance(item, dict)
                    ],
                }
                semantic = validate_review_result(
                    artifact,
                    review_schema,
                    manifest,
                    current_head=candidate_payload.get("patch_hash"),
                    current_scope_hash=state.get("source", {}).get("scope_hash"),
                )
                errors.extend(f"{ref}: {item.code}@{item.path}" for item in semantic)
            else:
                errors.append(f"{ref}: review result has no bound incumbent candidate")
        else:
            errors.extend(_validate_generic_artifact(ref, artifact, state))
    bindings = {
        "contract_ref": run.get("contract_ref"),
        "baseline_ref": run.get("baseline_ref"),
        "verifier_bundle_ref": run.get("verifier_bundle_ref"),
    }
    for field, binding in bindings.items():
        if not isinstance(binding, dict):
            continue
        ref = binding.get("artifact_ref")
        artifact = artifacts.get(ref) if isinstance(ref, str) else None
        if not isinstance(artifact, dict):
            errors.append(f"{field}: bound artifact is missing")
            continue
        if artifact.get("content_hash") != binding.get("content_hash"):
            errors.append(f"{field}: bound artifact content hash changed")
        if "epoch" in binding:
            observed_epoch = artifact.get("epoch") if field == "contract_ref" else artifact.get("closure_epoch")
            if observed_epoch != binding.get("epoch"):
                errors.append(f"{field}: bound artifact epoch changed")
    contract = artifacts.get(contract_binding.get("artifact_ref")) if contract_binding else None
    baseline_binding = run.get("baseline_ref") if isinstance(run.get("baseline_ref"), dict) else {}
    baseline = artifacts.get(baseline_binding.get("artifact_ref")) if baseline_binding else None
    if isinstance(contract, dict):
        requirement_ids = {item.get("id") for item in contract.get("verifier_requirements", []) if isinstance(item, dict)}
        constraint_ids = {item.get("id") for item in contract.get("hard_constraints", []) if isinstance(item, dict)}
        corner_ids = {item.get("id") for item in contract.get("corners", []) if isinstance(item, dict)}
        contract_protected = {item.get("path") for item in contract.get("protected_surfaces", []) if isinstance(item, dict)}
        state_protected = set(state.get("scope", {}).get("protected_paths", []))
        for ref, verifier in artifacts.items():
            if not ref.startswith("artifact:verifier/"):
                continue
            oracle_requirements: set[str] = set()
            for oracle in verifier.get("oracles", []):
                if not isinstance(oracle, dict):
                    continue
                observed_requirements = set(oracle.get("requirement_refs", []))
                observed_constraints = set(oracle.get("constraint_refs", []))
                observed_corners = set(oracle.get("corner_refs", []))
                oracle_requirements.update(observed_requirements)
                if not observed_requirements.issubset(requirement_ids):
                    errors.append(f"{ref}: verifier oracle references unknown contract requirements")
                if not observed_constraints.issubset(constraint_ids):
                    errors.append(f"{ref}: verifier oracle references unknown hard constraints")
                if not observed_corners.issubset(corner_ids):
                    errors.append(f"{ref}: verifier oracle references unknown contract corners")
            if requirement_ids - oracle_requirements:
                errors.append(f"{ref}: verifier bundle does not cover every contract verifier requirement")
            if not (contract_protected | state_protected).issubset(set(verifier.get("protected_paths", []))):
                errors.append(f"{ref}: verifier bundle omits protected contract or workflow paths")
            if isinstance(baseline, dict):
                if verifier.get("environment_fingerprint") != baseline.get("payload", {}).get("environment_fingerprint"):
                    errors.append(f"{ref}: verifier environment differs from qualified baseline")
                baseline_refs = verifier.get("qualification_summary", {}).get("baseline_result_refs", [])
                if baseline_binding.get("artifact_ref") not in baseline_refs:
                    errors.append(f"{ref}: verifier qualification does not cite the bound baseline")
    for ref, artifact in artifacts.items():
        if artifact.get("schema_id") == "sqw://closure-artifacts/candidate-manifest/1.0":
            payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
            parent_id = payload.get("parent")
            if isinstance(parent_id, str):
                parent = artifacts.get(f"artifact:candidate/{parent_id}")
                if not isinstance(parent, dict) or payload.get("base_candidate_hash") != parent.get("content_hash"):
                    errors.append(f"{ref}: candidate base hash differs from immutable parent candidate")
        if artifact.get("schema_id") == "sqw://closure-artifacts/candidate-evaluation/1.0":
            payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
            candidate_id = payload.get("candidate_id")
            candidate = artifacts.get(f"artifact:candidate/{candidate_id}") if isinstance(candidate_id, str) else None
            candidate_payload = candidate.get("payload") if isinstance(candidate, dict) and isinstance(candidate.get("payload"), dict) else {}
            relationships = {
                "parent_candidate_ref": "parent",
                "strategy_family_ref": "strategy_family_ref",
                "patch_hash": "patch_hash",
                "worktree_ref": "worktree_ref",
            }
            if not candidate_payload:
                errors.append(f"{ref}: candidate evaluation has no immutable candidate manifest")
            else:
                for evaluation_field, candidate_field in relationships.items():
                    if payload.get(evaluation_field) != candidate_payload.get(candidate_field):
                        errors.append(f"{ref}: evaluation {evaluation_field} differs from candidate manifest")
        if artifact.get("schema_id") != "sqw://closure-artifacts/signoff-result/1.0":
            continue
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        candidate_ref = payload.get("candidate_ref")
        candidate = artifacts.get(candidate_ref) if isinstance(candidate_ref, str) else None
        if not isinstance(candidate, dict) or candidate.get("schema_id") != "sqw://closure-artifacts/candidate-manifest/1.0":
            errors.append(f"{ref}: sign-off candidate artifact is missing")
        elif payload.get("candidate_hash") != candidate.get("content_hash"):
            errors.append(f"{ref}: sign-off candidate hash differs from candidate manifest")
        baseline_ref = run.get("baseline_ref") if isinstance(run.get("baseline_ref"), dict) else {}
        baseline = artifacts.get(baseline_ref.get("artifact_ref"))
        baseline_hash = baseline.get("payload", {}).get("baseline_hash") if isinstance(baseline, dict) else None
        if payload.get("freshness", {}).get("baseline_hash") != baseline_hash:
            errors.append(f"{ref}: sign-off baseline freshness differs from bound baseline")
        axes = payload.get("axes") if isinstance(payload.get("axes"), dict) else {}
        for axis_name in ("requirements", "engineering"):
            axis = axes.get(axis_name) if isinstance(axes.get(axis_name), dict) else {}
            review_ref = axis.get("review_result_ref")
            review = artifacts.get(review_ref) if isinstance(review_ref, str) else None
            if not isinstance(review, dict):
                errors.append(f"{ref}: {axis_name} review result is missing")
                continue
            if axis.get("review_result_hash") != canonical_artifact_hash(review):
                errors.append(f"{ref}: {axis_name} review result hash differs from referenced review")
            if axis.get("status") == "pass" and (
                review.get("code_review_verdict") != "pass"
                or review.get("verification_status") != "passed"
                or review.get("merge_readiness") != "ready"
            ):
                errors.append(f"{ref}: passing {axis_name} axis requires a passing ready review result")
    budget = run.get("budget") if isinstance(run.get("budget"), dict) else {}
    expected_budget = {
        "iterations": budget.get("iterations_used", 0),
        "candidate_evaluations": budget.get("candidate_evaluations_used", 0),
        "review_rounds": budget.get("review_rounds_used", 0),
    }
    for ref, artifact in artifacts.items():
        if artifact.get("schema_id") != "sqw://closure-artifacts/terminal-certificate/1.0":
            continue
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        reported_budget = payload.get("budget_consumed") if isinstance(payload.get("budget_consumed"), dict) else {}
        if reported_budget and reported_budget != expected_budget:
            errors.append(f"{ref}: terminal budget differs from controller ledger")
        if not reported_budget and any(expected_budget.values()):
            errors.append(f"{ref}: terminal omits consumed controller budget")
        if payload.get("terminal_status") != "CLOSED":
            continue
        incumbent_ref = run.get("incumbent_candidate_ref")
        if payload.get("incumbent_candidate_ref") != incumbent_ref:
            errors.append(f"{ref}: CLOSED incumbent differs from controller state")
        signoff_ref = payload.get("signoff_result_ref")
        signoff = artifacts.get(signoff_ref) if isinstance(signoff_ref, str) else None
        if not isinstance(signoff, dict) or signoff.get("payload", {}).get("verdict") != "pass":
            errors.append(f"{ref}: CLOSED sign-off ref is missing or not passing")
            continue
        gate_refs = {
            evidence_ref
            for result in signoff.get("payload", {}).get("required_gate_results", [])
            if isinstance(result, dict)
            for evidence_ref in result.get("evidence_refs", [])
            if isinstance(evidence_ref, str)
        }
        if set(payload.get("required_gate_result_refs", [])) != gate_refs:
            errors.append(f"{ref}: CLOSED required gate refs differ from passing sign-off evidence")
        residual = signoff.get("payload", {}).get("residual_risk", [])
        if len(payload.get("residual_risk_refs", [])) != len(residual):
            errors.append(f"{ref}: CLOSED residual-risk refs do not cover sign-off residual risks")
    return errors


def _event_payload(events: list[dict[str, Any]]) -> bytes:
    return b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8") for item in events)


def _recover_pending(
    journal_path: Path,
    event: dict[str, Any],
    state_source: Path,
    output: Path,
    events_path: Path,
    root: Path,
    state_schema: dict[str, Any],
    event_schema: dict[str, Any],
    artifact_schema: dict[str, Any],
    review_schema: dict[str, Any],
    verifier_schema: dict[str, Any],
) -> dict[str, Any] | None:
    if not journal_path.exists():
        return None
    journal = load_json(journal_path)
    required = {"schema_version", "event_id", "event_digest", "accepted_event_digest", "source_state_hash", "next_state_hash", "event", "next_state"}
    if not isinstance(journal, dict) or set(journal) != required or journal.get("event_id") != event.get("event_id") or journal.get("event_digest") != _event_digest(event):
        raise ControllerConflict("pending transition belongs to another or conflicting event")
    next_state = journal.get("next_state")
    accepted_event = journal.get("event")
    if not isinstance(next_state, dict) or not isinstance(accepted_event, dict):
        raise ControllerConflict("pending transition journal is malformed")
    if _event_digest(accepted_event) != journal.get("event_digest") or _event_digest(accepted_event, include_artifact_bindings=True) != journal.get("accepted_event_digest"):
        raise ControllerConflict("pending journal event content differs from its digest")
    if next_state.get("state_hash") != journal.get("next_state_hash") or canonical_hash(next_state) != journal.get("next_state_hash"):
        raise ControllerConflict("pending journal next state differs from its digest")
    current_state = load_json(state_source)
    if not isinstance(current_state, dict) or canonical_hash(current_state) != journal.get("source_state_hash"):
        raise ControllerConflict("pending transition source state has changed")
    state_errors = validate_state(current_state, state_schema)
    if state_errors:
        raise ControllerConflict("pending transition source state is invalid")
    events = load_json_lines(events_path) if events_path.exists() else []
    _validate_event_chain(events)
    _validate_historical_artifacts(root, events)
    matching = [item for item in events if item.get("event_id") == accepted_event.get("event_id")]
    if matching and any(_event_digest(item) != _event_digest(accepted_event) for item in matching):
        raise ControllerConflict("event ID was reused with conflicting content")
    if matching and any(_event_digest(item, include_artifact_bindings=True) != _event_digest(accepted_event, include_artifact_bindings=True) for item in matching):
        raise ControllerConflict("accepted event artifact bindings differ from pending journal")
    if matching and (len(matching) != 1 or matching[0].get("source_state_hash") != current_state.get("state_hash") or matching[0].get("result_state_hash") != next_state.get("state_hash")):
        raise ControllerConflict("pending event state hashes differ from source or next state")
    if not matching and events and events[-1].get("result_state_hash") != current_state.get("state_hash"):
        raise ControllerConflict("pending source state differs from accepted event chain head")
    stream_errors = validate_event_stream(events if matching else events + [accepted_event], event_schema)
    if stream_errors:
        raise ControllerConflict("pending event stream is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in stream_errors[:8]))
    _validate_event_chain(events if matching else events + [accepted_event])
    observed_revision = current_state.get("source", {}).get("observed_revision")
    source_drift = accepted_event.get("type") == "source_drift_detected"
    if source_drift and accepted_event.get("source_revision") == observed_revision:
        raise ControllerConflict("pending source_drift_detected has no changed source revision")
    if not source_drift and accepted_event.get("source_revision") != observed_revision:
        raise ControllerConflict("pending proposal source revision differs from workflow source")
    artifacts = _load_artifacts(root, accepted_event, current_state)
    if accepted_event.get("payload", {}).get("artifact_bindings") != _artifact_bindings(artifacts):
        raise ControllerConflict("pending accepted event artifact bindings differ from current artifacts")
    artifact_errors = _validate_artifacts(
        artifacts,
        current_state,
        artifact_schema,
        review_schema,
        verifier_schema,
        expected_source_revision=accepted_event.get("source_revision") if source_drift else None,
    )
    if artifact_errors:
        raise ControllerConflict("pending artifact validation failed: " + "; ".join(artifact_errors[:8]))
    scope_errors = _validate_scope_and_protected(accepted_event, artifacts, current_state)
    if scope_errors:
        raise ControllerConflict("pending scope validation failed: " + "; ".join(scope_errors[:8]))
    promotion_errors = _validate_promotion(accepted_event, artifacts, current_state)
    if promotion_errors:
        raise ControllerConflict("pending promotion validation failed: " + "; ".join(promotion_errors[:8]))
    prior_events = [item for item in events if item.get("event_id") != accepted_event.get("event_id")]
    _enforce_contract_epoch(root, prior_events, accepted_event, artifacts)
    try:
        expected_state = apply_event(current_state, accepted_event, artifacts)
    except ClosureError as exc:
        raise ControllerConflict(f"pending deterministic replay failed: {exc}") from exc
    if expected_state != next_state:
        raise ControllerConflict("pending journal next state differs from deterministic replay")
    transition_errors = validate_transition(current_state, next_state, actor_kind="controller")
    next_errors = validate_state(next_state, state_schema)
    if transition_errors or next_errors:
        raise ControllerConflict("pending journal transition or next state is invalid")
    if not matching:
        _atomic_write(events_path, _event_payload(events + [accepted_event]))
    if output.exists():
        existing = load_json(output)
        if existing != next_state:
            raise ControllerConflict("transition output exists with conflicting content")
    else:
        _atomic_write(output, _json_bytes(next_state))
    journal_path.unlink(missing_ok=True)
    _sync_directory(journal_path.parent)
    return next_state


def advance_once(
    state_path: str | Path,
    event_path: str | Path,
    artifacts_root: str | Path,
    output_path: str | Path,
    *,
    failpoint: str | None = None,
) -> dict[str, Any]:
    root = Path(artifacts_root).resolve()
    if not root.is_dir():
        raise ControllerConflict(f"artifacts root is not a directory: {root}")
    state_source = _inside(root, Path(state_path))
    event_source = _inside(root, Path(event_path))
    output = _inside(root, Path(output_path))
    if len({state_source, event_source, output}) != 3:
        raise ControllerConflict("state, event, and output paths must be distinct")
    events_path = root / "events.jsonl"
    journal_path = root / ".advance-pending.json"

    state_schema = load_json(STATE_SCHEMA)
    event_schema = load_json(EVENT_SCHEMA)
    artifact_schema = load_json(ARTIFACT_SCHEMA)
    review_schema = load_json(REVIEW_SCHEMA)
    verifier_schema = load_json(VERIFIER_SCHEMA)
    event = load_json(event_source)
    if not isinstance(event, dict):
        raise ControllerConflict("proposal event must be a JSON object")
    if (isinstance(event.get("payload"), dict) and "artifact_bindings" in event["payload"]) or CONTROLLER_EVENT_FIELDS & set(event):
        raise ControllerConflict("controller-owned hash and artifact bindings must be absent from proposals")

    with _exclusive_guard(root):
        recovered = _recover_pending(
            journal_path,
            event,
            state_source,
            output,
            events_path,
            root,
            state_schema,
            event_schema,
            artifact_schema,
            review_schema,
            verifier_schema,
        )
        if recovered is not None:
            return recovered
        state = load_json(state_source)
        if not isinstance(state, dict):
            raise ControllerConflict("workflow state must be a JSON object")
        state_errors = validate_state(state, state_schema)
        if state_errors:
            raise ControllerConflict("current workflow state is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in state_errors[:8]))
        events = load_json_lines(events_path) if events_path.exists() else []
        historical_event_errors = validate_event_stream(events, event_schema)
        if historical_event_errors:
            raise ControllerConflict("accepted event stream is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in historical_event_errors[:8]))
        _validate_event_chain(events)
        _validate_historical_artifacts(root, events)
        matching = [item for item in events if item.get("event_id") == event.get("event_id")]
        if matching:
            if len(matching) != 1 or matching[0].get("source_state_hash") != state.get("state_hash"):
                raise ControllerConflict("idempotent proposal source state differs from accepted event")
            if any(_event_digest(item) != _event_digest(event) for item in matching):
                raise ControllerConflict("event ID was reused with conflicting content")
            if not output.exists():
                raise ControllerConflict("event was accepted but output is absent and no recovery journal exists")
            existing = load_json(output)
            if not isinstance(existing, dict) or existing.get("state_hash") != canonical_hash(existing):
                raise ControllerConflict("idempotent output is invalid")
            if matching[0].get("result_state_hash") != existing.get("state_hash"):
                raise ControllerConflict("idempotent output differs from accepted event state hash")
            artifacts = _load_artifacts(root, event, state)
            if matching[0].get("payload", {}).get("artifact_bindings") != _artifact_bindings(artifacts):
                raise ControllerConflict("idempotent artifact bindings differ from accepted event")
            expected_revision = event.get("source_revision") if event.get("type") == "source_drift_detected" else None
            artifact_errors = _validate_artifacts(artifacts, state, artifact_schema, review_schema, verifier_schema, expected_source_revision=expected_revision)
            if artifact_errors:
                raise ControllerConflict("idempotent artifact validation failed: " + "; ".join(artifact_errors[:8]))
            scope_errors = _validate_scope_and_protected(event, artifacts, state)
            if scope_errors:
                raise ControllerConflict("idempotent scope validation failed: " + "; ".join(scope_errors[:8]))
            promotion_errors = _validate_promotion(event, artifacts, state)
            if promotion_errors:
                raise ControllerConflict("idempotent promotion validation failed: " + "; ".join(promotion_errors[:8]))
            try:
                expected = apply_event(state, event, artifacts)
            except ClosureError as exc:
                raise ControllerConflict(str(exc)) from exc
            if existing != expected:
                raise ControllerConflict("idempotent output differs from deterministic replay")
            return existing
        if events and events[-1].get("result_state_hash") != state.get("state_hash"):
            raise ControllerConflict("current state differs from the accepted event chain head")
        if output.exists():
            raise ControllerConflict("refusing to overwrite transition output")
        candidate_events = events + [deepcopy(event)]
        event_errors = validate_event_stream(candidate_events, event_schema)
        if event_errors:
            raise ControllerConflict("proposal event is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in event_errors[:8]))
        observed_revision = state.get("source", {}).get("observed_revision")
        source_drift = event.get("type") == "source_drift_detected"
        if source_drift and event.get("source_revision") == observed_revision:
            raise ControllerConflict("source_drift_detected must identify a changed source revision")
        if not source_drift and event.get("source_revision") != observed_revision:
            raise ControllerConflict("proposal source revision differs from workflow source")
        artifacts = _load_artifacts(root, event, state)
        artifact_errors = _validate_artifacts(
            artifacts,
            state,
            artifact_schema,
            review_schema,
            verifier_schema,
            expected_source_revision=event.get("source_revision") if source_drift else None,
        )
        if artifact_errors:
            raise ControllerConflict("artifact validation failed: " + "; ".join(artifact_errors[:8]))
        scope_errors = _validate_scope_and_protected(event, artifacts, state)
        if scope_errors:
            raise ControllerConflict("scope validation failed: " + "; ".join(scope_errors[:8]))
        promotion_errors = _validate_promotion(event, artifacts, state)
        if promotion_errors:
            raise ControllerConflict("promotion validation failed: " + "; ".join(promotion_errors[:8]))
        _enforce_contract_epoch(root, events, event, artifacts)
        try:
            next_state = apply_event(state, event, artifacts)
        except ClosureError as exc:
            raise ControllerConflict(str(exc)) from exc
        transition_errors = validate_transition(state, next_state, actor_kind="controller")
        if transition_errors:
            raise ControllerConflict("controller transition is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in transition_errors[:8]))
        next_errors = validate_state(next_state, state_schema)
        if next_errors:
            raise ControllerConflict("next workflow state is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in next_errors[:8]))
        accepted_event = deepcopy(event)
        accepted_event["payload"]["artifact_bindings"] = _artifact_bindings(artifacts)
        accepted_event.update({
            "previous_event_hash": events[-1]["event_hash"] if events else GENESIS_EVENT_HASH,
            "source_state_hash": state["state_hash"],
            "result_state_hash": next_state["state_hash"],
        })
        accepted_event["event_hash"] = _accepted_event_hash(accepted_event)
        accepted_events = events + [accepted_event]
        accepted_event_errors = validate_event_stream(accepted_events, event_schema)
        if accepted_event_errors:
            raise ControllerConflict("accepted event is invalid: " + "; ".join(f"{item.code}@{item.path}" for item in accepted_event_errors[:8]))
        _validate_event_chain(accepted_events)
        journal = {
            "schema_version": "closure-transition-journal/1.0",
            "event_id": event["event_id"],
            "event_digest": _event_digest(event),
            "accepted_event_digest": _event_digest(accepted_event, include_artifact_bindings=True),
            "source_state_hash": canonical_hash(state),
            "next_state_hash": next_state["state_hash"],
            "event": accepted_event,
            "next_state": next_state,
        }
        _atomic_write(journal_path, _json_bytes(journal))
        if failpoint == "after_journal":
            raise RuntimeError("injected crash after transition journal")
        _atomic_write(events_path, _event_payload(accepted_events))
        if failpoint == "after_event":
            raise RuntimeError("injected crash after event append")
        _atomic_write(output, _json_bytes(next_state))
        if failpoint == "after_state":
            raise RuntimeError("injected crash after state publication")
        journal_path.unlink(missing_ok=True)
        _sync_directory(root)
        return next_state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--artifacts-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        state = advance_once(args.state, args.event, args.artifacts_root, args.output)
    except (ControllerConflict, AdapterConflict, InputError, OSError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": {"code": _error_code(exc), "message": str(exc)}}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, "workflow_id": state["workflow_id"], "state_version": state["state_version"], "state_hash": state["state_hash"], "phase": state["closure_run"]["phase"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
