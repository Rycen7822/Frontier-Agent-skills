#!/usr/bin/env python3
"""Shared, dependency-free primitives for SQW typed workflow artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from fnmatch import fnmatchcase
from hashlib import sha256
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterable


MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 40
MAX_COLLECTION_ITEMS = 1000
LOCAL_ID_RE = re.compile(r"^(?:N|EV|VER|I|AP|LOCK|X|ERR|RUN)-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXTERNAL_REF_RE = re.compile(r"^(?:plan|workflow|review|longdoc):[A-Za-z0-9._-]+#[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SECRET_LIKE_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*[\"']?[^\s,\"'}]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class Violation:
    code: str
    path: str
    message: str
    object_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if result["object_id"] is None:
            result.pop("object_id")
        return result


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _check_bounds(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise InputError(f"input nesting exceeds {MAX_DEPTH}")
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise InputError(f"object exceeds {MAX_COLLECTION_ITEMS} items")
        for child in value.values():
            _check_bounds(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise InputError(f"array exceeds {MAX_COLLECTION_ITEMS} items")
        for child in value:
            _check_bounds(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise InputError("non-finite JSON number is not allowed")


def _decode_json(text: str, source: str) -> Any:
    try:
        value = json.loads(text, object_pairs_hook=_pairs_no_duplicates)
    except (json.JSONDecodeError, InputError) as exc:
        raise InputError(f"{source}: {exc}") from exc
    _check_bounds(value)
    return value


def _read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise InputError(f"input is not a regular file: {path}")
            if metadata.st_size > MAX_INPUT_BYTES:
                raise InputError(f"input is {metadata.st_size} bytes; maximum is {MAX_INPUT_BYTES}")
            payload = stream.read(MAX_INPUT_BYTES + 1)
    except (OSError, InputError) as exc:
        raise InputError(str(exc)) from exc
    if len(payload) > MAX_INPUT_BYTES:
        raise InputError(f"input exceeds maximum of {MAX_INPUT_BYTES} bytes")
    return payload


def load_json(path: str | Path) -> Any:
    source = Path(path)
    try:
        text = _read_regular_bytes(source).decode("utf-8")
    except (OSError, UnicodeError, InputError) as exc:
        raise InputError(str(exc)) from exc
    return _decode_json(text, str(source))


def load_json_lines(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    try:
        lines = _read_regular_bytes(source).decode("utf-8").splitlines()
    except (OSError, UnicodeError, InputError) as exc:
        raise InputError(str(exc)) from exc
    if len(lines) > MAX_COLLECTION_ITEMS:
        raise InputError(f"event stream exceeds {MAX_COLLECTION_ITEMS} records")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines, 1):
        if not line.strip():
            raise InputError(f"{source}:{index}: blank JSONL record")
        value = _decode_json(line, f"{source}:{index}")
        if not isinstance(value, dict):
            raise InputError(f"{source}:{index}: event must be an object")
        records.append(value)
    return records


def pointer(parts: Iterable[str | int]) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped) if escaped else ""


def canonical_hash(state: dict[str, Any]) -> str:
    clean = dict(state)
    clean.pop("state_hash", None)
    clean.pop("context_trace_ref", None)
    _check_bounds(clean)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def canonical_artifact_hash(artifact: dict[str, Any]) -> str:
    clean = dict(artifact)
    clean.pop("content_hash", None)
    _check_bounds(clean)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def validate_closure_artifact(
    artifact: Any,
    schema: dict[str, Any],
    *,
    expected_workflow_id: str | None = None,
    expected_closure_epoch: int | None = None,
    expected_source_revision: str | None = None,
    expected_scope_hash: str | None = None,
    expected_contract_hash: str | None = None,
    expected_verifier_bundle_hash: str | None = None,
) -> list[Violation]:
    violations = validate_against_schema(artifact, schema, code="artifact.schema")
    if not isinstance(artifact, dict):
        return violations
    if isinstance(artifact.get("content_hash"), str) and artifact["content_hash"] != canonical_artifact_hash(artifact):
        violations.append(Violation("artifact.hash", "/content_hash", "content_hash does not match canonical artifact content", artifact.get("artifact_id")))
    expected = {
        "workflow_id": expected_workflow_id,
        "closure_epoch": expected_closure_epoch,
        "source_revision": expected_source_revision,
        "scope_hash": expected_scope_hash,
        "contract_hash": expected_contract_hash,
        "verifier_bundle_hash": expected_verifier_bundle_hash,
    }
    for field, value in expected.items():
        if value is not None and artifact.get(field) != value:
            violations.append(Violation("artifact.identity", f"/{field}", f"artifact {field} differs from expected binding", artifact.get("artifact_id")))

    payload = artifact.get("payload")
    if not isinstance(payload, dict):
        return violations
    schema_id = artifact.get("schema_id")
    if schema_id == "sqw://closure-artifacts/candidate-manifest/1.0":
        allowed = payload.get("allowed_writes", []) if isinstance(payload.get("allowed_writes"), list) else []
        protected = payload.get("protected_paths", []) if isinstance(payload.get("protected_paths"), list) else []
        for write_pattern in allowed:
            if isinstance(write_pattern, str) and any(isinstance(item, str) and patterns_may_overlap(write_pattern, item) for item in protected):
                violations.append(Violation("artifact.scope", "/payload/allowed_writes", "candidate allowed writes overlap protected paths", payload.get("candidate_id")))
                break
        if payload.get("parent") == payload.get("candidate_id"):
            violations.append(Violation("artifact.scope", "/payload/parent", "candidate cannot be its own parent", payload.get("candidate_id")))
    if schema_id == "sqw://closure-artifacts/candidate-evaluation/1.0" and payload.get("eligible_for_promotion") is True:
        failed = any(
            isinstance(item, dict) and item.get("status") == "fail"
            for field in ("hard_constraint_results", "regression_results")
            for item in (payload.get(field) if isinstance(payload.get(field), list) else [])
        )
        blocking_risk = any(isinstance(item, dict) and item.get("blocking") is True for item in (payload.get("risk_findings") if isinstance(payload.get("risk_findings"), list) else []))
        if failed or blocking_risk:
            violations.append(Violation("artifact.evaluation", "/payload/eligible_for_promotion", "promotion eligibility cannot coexist with failed hard/regression gates or blocking risk", payload.get("candidate_id")))
    if schema_id == "sqw://closure-artifacts/signoff-result/1.0":
        axes = payload.get("axes", {}) if isinstance(payload.get("axes"), dict) else {}
        statuses = [axis.get("status") for axis in axes.values() if isinstance(axis, dict)]
        expected_verdict = "pass" if len(statuses) == 4 and all(status == "pass" for status in statuses) else "fail" if "fail" in statuses else "inconclusive"
        if payload.get("verdict") != expected_verdict:
            violations.append(Violation("artifact.signoff", "/payload/axes", "sign-off verdict must match the four axis statuses", artifact.get("artifact_id")))
        if payload.get("verdict") == "pass" and any(isinstance(item, dict) and item.get("status") != "pass" for item in (payload.get("required_gate_results") if isinstance(payload.get("required_gate_results"), list) else [])):
            violations.append(Violation("artifact.signoff", "/payload/required_gate_results", "pass verdict requires every required gate to pass", artifact.get("artifact_id")))
        freshness = payload.get("freshness", {}) if isinstance(payload.get("freshness"), dict) else {}
        for field in ("source_revision", "scope_hash", "contract_hash", "verifier_bundle_hash"):
            if field in freshness and freshness.get(field) != artifact.get(field):
                violations.append(Violation("artifact.signoff", f"/payload/freshness/{field}", f"sign-off freshness {field} differs from envelope", artifact.get("artifact_id")))
    if schema_id == "sqw://closure-artifacts/terminal-certificate/1.0":
        status = payload.get("terminal_status")
        if payload.get("source_revision") != artifact.get("source_revision") or payload.get("scope_hash") != artifact.get("scope_hash") or payload.get("contract_hash") != artifact.get("contract_hash") or payload.get("verifier_bundle_hash") != artifact.get("verifier_bundle_hash"):
            violations.append(Violation("artifact.terminal", "/payload", "terminal identity differs from envelope", artifact.get("artifact_id")))
        if status == "SPEC_UNDERDETERMINED" and not payload.get("minimal_missing_information"):
            violations.append(Violation("artifact.terminal", "/payload/minimal_missing_information", "SPEC_UNDERDETERMINED requires minimal missing information", artifact.get("artifact_id")))
        if status == "SPEC_UNSAT" and not payload.get("minimal_unsat_core"):
            violations.append(Violation("artifact.terminal", "/payload/minimal_unsat_core", "SPEC_UNSAT requires a minimal unsat core", artifact.get("artifact_id")))
        if status in {"NON_CONVERGED", "BUDGET_EXHAUSTED"} and (not payload.get("attempted_strategies") or not payload.get("budget_consumed")):
            violations.append(Violation("artifact.terminal", "/payload/attempted_strategies", f"{status} requires attempted strategies and consumed budget", artifact.get("artifact_id")))
        if status == "CLOSED":
            required = ("incumbent_candidate_ref", "signoff_result_ref", "required_gate_result_refs", "residual_risk_refs", "publication_state_ref")
            if payload.get("blocking_items") or payload.get("minimal_missing_information") or payload.get("minimal_unsat_core") or any(field not in payload for field in required):
                violations.append(Violation("artifact.terminal", "/payload", "CLOSED requires clean blockers and complete incumbent/sign-off/gate/risk/publication refs", artifact.get("artifact_id")))
            if artifact.get("workflow_id") == "not_created" or artifact.get("closure_epoch") == 0 or artifact.get("contract_hash") == "not_frozen" or artifact.get("verifier_bundle_hash") == "not_frozen":
                violations.append(Violation("artifact.terminal", "/workflow_id", "CLOSED requires a durable workflow and frozen contract/verifier bindings", artifact.get("artifact_id")))
        elif status not in {"SPEC_UNDERDETERMINED", "SPEC_UNSAT", "NON_CONVERGED", "BUDGET_EXHAUSTED"} and (not payload.get("blocking_items") or not payload.get("evidence_refs")):
            violations.append(Violation("artifact.terminal", "/payload/blocking_items", f"{status} requires a structured blocker and evidence", artifact.get("artifact_id")))
    return violations


def validate_review_result(
    result: Any,
    schema: dict[str, Any],
    manifest: Any,
    *,
    current_head: str,
    current_scope_hash: str,
) -> list[Violation]:
    violations = validate_against_schema(result, schema, code="review.schema")
    if not isinstance(result, dict):
        return violations
    findings = result.get("findings") if isinstance(result.get("findings"), list) else []
    coverage = result.get("coverage") if isinstance(result.get("coverage"), list) else []
    blocking_reasons = result.get("blocking_reasons") if isinstance(result.get("blocking_reasons"), list) else []

    finding_ids = [item.get("id") for item in findings if isinstance(item, dict) and isinstance(item.get("id"), str)]
    if len(finding_ids) != len(set(finding_ids)):
        violations.append(Violation("review.consistency", "/findings", "finding IDs must be unique"))
    blocking_ids = {item.get("id") for item in findings if isinstance(item, dict) and item.get("blocking") is True}
    if not blocking_ids.issubset(set(blocking_reasons)):
        violations.append(Violation("review.consistency", "/blocking_reasons", "every blocking finding must be named in blocking_reasons"))
    if result.get("code_review_verdict") == "pass" and (blocking_ids or blocking_reasons or any(isinstance(item, dict) and item.get("status") == "not_reviewed" for item in coverage)):
        violations.append(Violation("review.consistency", "/code_review_verdict", "pass cannot coexist with blockers or not-reviewed coverage"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("paths"), list):
        violations.append(Violation("review.manifest", "", "a frozen scope manifest is required"))
        return violations
    expected_paths: dict[str, str] = {}
    duplicate_manifest_path = False
    for item in manifest["paths"]:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("snapshot_id"), str):
            if item["path"] in expected_paths:
                duplicate_manifest_path = True
            expected_paths[item["path"]] = item["snapshot_id"]
    if duplicate_manifest_path:
        violations.append(Violation("review.manifest", "/paths", "frozen manifest paths must be unique"))
    observed_paths: dict[str, str] = {}
    duplicate_coverage = False
    for item in coverage:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = item["path"]
        if path in observed_paths:
            duplicate_coverage = True
        observed_paths[path] = item.get("snapshot_id")
    if duplicate_coverage or set(observed_paths) != set(expected_paths):
        violations.append(Violation("review.manifest", "/coverage", "coverage must exactly and uniquely match the frozen manifest"))
    for path, snapshot_id in observed_paths.items():
        if expected_paths.get(path) != snapshot_id:
            violations.append(Violation("review.manifest", "/coverage", f"snapshot differs from frozen manifest: {path}"))
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        if finding.get("path") not in expected_paths:
            violations.append(Violation("review.manifest", pointer(("findings", index, "path")), "finding path is outside frozen scope", finding.get("id")))
        if finding.get("source_revision") != result.get("reviewed_head_sha"):
            violations.append(Violation("review.freshness", pointer(("findings", index, "source_revision")), "finding revision differs from reviewed head", finding.get("id")))
    if result.get("reviewed_base_sha") != manifest.get("base_revision") or result.get("reviewed_head_sha") != manifest.get("head_revision") or result.get("reviewed_scope_hash") != manifest.get("scope_hash"):
        violations.append(Violation("review.manifest", "", "review identity differs from frozen manifest"))
    if current_head != manifest.get("head_revision") or current_scope_hash != manifest.get("scope_hash"):
        violations.append(Violation("review.freshness", "", "current source or scope differs from frozen review manifest"))
    return violations


def validate_publication_readiness(
    result: Any,
    schema: dict[str, Any],
    review_result: Any,
    review_schema: dict[str, Any],
    manifest: Any,
    *,
    current_head: str,
    current_scope_hash: str,
) -> list[Violation]:
    """Validate remote publication readiness without treating local review as authority."""

    violations = validate_against_schema(result, schema, code="publication.schema")
    if not isinstance(result, dict) or not isinstance(review_result, dict):
        if not isinstance(review_result, dict):
            violations.append(Violation("publication.review", "/review_result_ref", "a validated local review result is required"))
        return violations

    review_violations = validate_review_result(
        review_result,
        review_schema,
        manifest,
        current_head=current_head,
        current_scope_hash=current_scope_hash,
    )
    violations.extend(
        Violation("publication.review", f"/review_result{item.path}", item.message, item.object_id)
        for item in review_violations
    )

    if result.get("review_result_hash") != canonical_artifact_hash(review_result):
        violations.append(Violation("publication.review", "/review_result_hash", "review result hash does not match the supplied local review"))
    if result.get("source_revision") != review_result.get("reviewed_head_sha") or result.get("scope_hash") != review_result.get("reviewed_scope_hash"):
        violations.append(Violation("publication.review", "", "publication source and scope must match the local review"))
    if current_head != result.get("source_revision") or current_scope_hash != result.get("scope_hash"):
        violations.append(Violation("publication.freshness", "", "current source or scope differs from the publication decision"))

    ceiling = result.get("publication_ceiling") if isinstance(result.get("publication_ceiling"), dict) else {}
    allowed_actions = ceiling.get("allowed_actions") if isinstance(ceiling.get("allowed_actions"), list) else []
    if result.get("requested_action") not in allowed_actions:
        violations.append(Violation("publication.authority", "/requested_action", "requested publication action is outside the explicit authority ceiling"))

    remote_checks = result.get("remote_checks") if isinstance(result.get("remote_checks"), list) else []
    approvals = result.get("required_approvals") if isinstance(result.get("required_approvals"), list) else []
    check_ids = [item.get("check_id") for item in remote_checks if isinstance(item, dict) and isinstance(item.get("check_id"), str)]
    approval_ids = [item.get("approval_id") for item in approvals if isinstance(item, dict) and isinstance(item.get("approval_id"), str)]
    if len(check_ids) != len(set(check_ids)):
        violations.append(Violation("publication.consistency", "/remote_checks", "remote check IDs must be unique"))
    if len(approval_ids) != len(set(approval_ids)):
        violations.append(Violation("publication.consistency", "/required_approvals", "approval IDs must be unique"))
    if result.get("readiness") in {"blocked", "unknown"} and not result.get("blocking_reasons"):
        violations.append(Violation("publication.consistency", "/blocking_reasons", "blocked or unknown readiness requires a blocking reason"))

    if result.get("readiness") == "ready":
        local_ready = review_supports_full_signoff(review_result)
        remote_ready = (
            bool(remote_checks)
            and all(isinstance(item, dict) and item.get("status") in {"passed", "not_applicable"} for item in remote_checks)
            and all(isinstance(item, dict) and item.get("status") in {"satisfied", "not_applicable"} for item in approvals)
            and isinstance(result.get("branch_policy"), dict)
            and result["branch_policy"].get("status") in {"satisfied", "not_applicable"}
            and not result.get("blocking_reasons")
        )
        if not local_ready or not remote_ready:
            violations.append(Violation("publication.consistency", "/readiness", "ready requires a fresh full-scope local pass, complete applicable traceability, remote checks, approvals, branch policy, and no blockers"))
    return violations


def review_supports_full_signoff(result: Any) -> bool:
    """Return whether a validated local review can support full-scope sign-off."""

    if not isinstance(result, dict):
        return False
    coverage = result.get("coverage") if isinstance(result.get("coverage"), list) else []
    traceability = result.get("spec_traceability") if isinstance(result.get("spec_traceability"), dict) else {}
    return (
        result.get("code_review_verdict") == "pass"
        and result.get("verification_status") == "passed"
        and bool(coverage)
        and all(isinstance(item, dict) and item.get("status") == "full" for item in coverage)
        and traceability.get("status") in {"complete", "not_applicable"}
        and not result.get("blocking_reasons")
    )


def contains_secret_like(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_LIKE_PATTERNS)
    if isinstance(value, dict):
        return any(contains_secret_like(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_secret_like(child) for child in value)
    return False


def redact_secret_like(value: str) -> str:
    result = value
    for pattern in SECRET_LIKE_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return result


def is_local_id(value: Any) -> bool:
    return isinstance(value, str) and LOCAL_ID_RE.fullmatch(value) is not None


def is_ref(value: Any) -> bool:
    return is_local_id(value) or (isinstance(value, str) and EXTERNAL_REF_RE.fullmatch(value) is not None)


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise InputError(f"unsupported schema ref: {ref}")
    current: Any = root
    for segment in ref[2:].split("/"):
        current = current[segment.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise InputError(f"schema ref does not resolve to object: {ref}")
    return current


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)


def validate_against_schema(
    value: Any,
    schema: dict[str, Any],
    root_schema: dict[str, Any] | None = None,
    parts: tuple[str | int, ...] = (),
    *,
    code: str = "workflow.schema",
) -> list[Violation]:
    root = root_schema or schema
    if "$ref" in schema:
        return validate_against_schema(value, _resolve_ref(root, schema["$ref"]), root, parts, code=code)
    violations: list[Violation] = []
    if "oneOf" in schema:
        candidates = [validate_against_schema(value, candidate, root, parts, code=code) for candidate in schema["oneOf"]]
        if sum(not errors for errors in candidates) != 1:
            violations.append(Violation(code, pointer(parts), "value must satisfy exactly one schema alternative"))
    if "anyOf" in schema:
        candidates = [validate_against_schema(value, candidate, root, parts, code=code) for candidate in schema["anyOf"]]
        if not any(not errors for errors in candidates):
            violations.append(Violation(code, pointer(parts), "value must satisfy at least one schema alternative"))

    for candidate in schema.get("allOf", []):
        violations.extend(validate_against_schema(value, candidate, root, parts, code=code))
    if "if" in schema:
        predicate_errors = validate_against_schema(value, schema["if"], root, parts, code=code)
        branch = schema.get("then") if not predicate_errors else schema.get("else")
        if isinstance(branch, dict):
            violations.extend(validate_against_schema(value, branch, root, parts, code=code))
    if "not" in schema and not validate_against_schema(value, schema["not"], root, parts, code=code):
        violations.append(Violation(code, pointer(parts), "value satisfies a forbidden schema"))
    expected = schema.get("type")
    if expected and not _type_matches(value, expected):
        return [Violation(code, pointer(parts), f"expected {expected}, got {type(value).__name__}")]
    if "const" in schema and value != schema["const"]:
        violations.append(Violation(code, pointer(parts), f"expected constant {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        violations.append(Violation(code, pointer(parts), f"value is not in enum {schema['enum']}"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            violations.append(Violation(code, pointer(parts), "string is shorter than minLength"))
        if len(value) > schema.get("maxLength", 10**9):
            violations.append(Violation(code, pointer(parts), "string exceeds maxLength"))
        if schema.get("pattern") and re.search(schema["pattern"], value) is None:
            violations.append(Violation(code, pointer(parts), f"string does not match {schema['pattern']}"))
        if schema.get("format") == "date-time":
            try:
                observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if observed.utcoffset() is None:
                    raise ValueError("timezone offset is required")
            except ValueError:
                violations.append(Violation(code, pointer(parts), "invalid RFC3339/ISO date-time"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            violations.append(Violation(code, pointer(parts), "number must be finite"))
        if "minimum" in schema and value < schema["minimum"]:
            violations.append(Violation(code, pointer(parts), "number is below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            violations.append(Violation(code, pointer(parts), "number exceeds maximum"))

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            violations.append(Violation(code, pointer(parts), "array is shorter than minItems"))
        if len(value) > schema.get("maxItems", 10**9):
            violations.append(Violation(code, pointer(parts), "array exceeds maxItems"))
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            violations.append(Violation(code, pointer(parts), "array items must be unique"))
        if schema.get("items"):
            for index, child in enumerate(value):
                violations.extend(validate_against_schema(child, schema["items"], root, parts + (index,), code=code))
        if isinstance(schema.get("contains"), dict):
            matches = sum(
                not validate_against_schema(child, schema["contains"], root, parts + (index,), code=code)
                for index, child in enumerate(value)
            )
            if matches < schema.get("minContains", 1) or matches > schema.get("maxContains", 10**9):
                violations.append(Violation(code, pointer(parts), "array contains match count is outside bounds"))

    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            violations.append(Violation(code, pointer(parts), "object has fewer than minProperties"))
        if len(value) > schema.get("maxProperties", 10**9):
            violations.append(Violation(code, pointer(parts), "object exceeds maxProperties"))
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                violations.append(Violation(code, pointer(parts + (required,)), "required property is missing"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    violations.append(Violation(code, pointer(parts + (key,)), "unknown property"))
        for key, child_schema in properties.items():
            if key in value:
                violations.extend(validate_against_schema(value[key], child_schema, root, parts + (key,), code=code))
    return violations


def normalized_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix().lstrip("./")


def path_allowed(path: str, patterns: list[str]) -> bool:
    candidate = normalized_path(path)
    for pattern in patterns:
        normalized = normalized_path(pattern)
        prefix = normalized.split("*", 1)[0].rstrip("/")
        if fnmatchcase(candidate, normalized) or (prefix and (candidate == prefix or candidate.startswith(prefix + "/"))):
            return True
    return False


def patterns_may_overlap(left: str, right: str) -> bool:
    a, b = normalized_path(left), normalized_path(right)
    if a == b or fnmatchcase(a, b) or fnmatchcase(b, a):
        return True
    pa, pb = a.split("*", 1)[0].rstrip("/"), b.split("*", 1)[0].rstrip("/")
    if not pa or not pb:
        return True
    return pa == pb or pa.startswith(pb + "/") or pb.startswith(pa + "/")
