#!/usr/bin/env python3
"""Validate a frozen SQW verifier bundle and its qualification claims."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "verifier-bundle.schema.json"
LEVEL = {"addressable": 0, "stable": 1, "discriminating": 2, "independent": 3}
MAX_INPUT_BYTES = 4 * 1024 * 1024


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


def _reject_constant(value: str) -> None:
    raise InputError(f"non-finite JSON number is not allowed: {value}")


def load_json(path: str | Path) -> Any:
    source = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise InputError(f"input is not a regular file: {source}")
            if metadata.st_size > MAX_INPUT_BYTES:
                raise InputError(f"input is {metadata.st_size} bytes; maximum is {MAX_INPUT_BYTES}")
            payload = stream.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise InputError(f"input exceeds maximum of {MAX_INPUT_BYTES} bytes")
        text = payload.decode("utf-8")
        return json.loads(text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError, InputError, RecursionError) as exc:
        raise InputError(f"{source}: {exc}") from exc


def _json_pointer(parts: Any) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped) if escaped else ""


def validate_against_schema(value: Any, schema: dict[str, Any], *, code: str) -> list[Violation]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise InputError(f"invalid JSON schema: {exc.message}") from exc
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda item: (_json_pointer(item.absolute_path), item.message))
    return [Violation(code, _json_pointer(error.absolute_path), error.message) for error in errors]


def canonical_bundle_hash(bundle: dict[str, Any]) -> str:
    clean = dict(bundle)
    clean.pop("content_hash", None)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _safe_protected_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/"):
        return False
    parts = PurePosixPath(value).parts
    return ".." not in parts and "." not in parts


def validate_bundle(
    bundle: Any,
    schema: dict[str, Any],
    *,
    expected_contract_hash: str | None = None,
    expected_source_revision: str | None = None,
    expected_scope_hash: str | None = None,
    expected_environment_fingerprint: str | None = None,
) -> list[Violation]:
    schema_errors = validate_against_schema(bundle, schema, code="E_SCHEMA_INVALID")
    violations = list(schema_errors)
    if not isinstance(bundle, dict):
        return violations
    bundle_id = bundle.get("bundle_id") if isinstance(bundle.get("bundle_id"), str) else None
    try:
        observed_hash = canonical_bundle_hash(bundle)
    except (TypeError, ValueError) as exc:
        violations.append(Violation("E_SCHEMA_INVALID", "", str(exc), bundle_id))
        observed_hash = None
    if observed_hash is not None and bundle.get("content_hash") != observed_hash:
        violations.append(Violation("E_HASH_MISMATCH", "/content_hash", "content_hash does not match canonical verifier bundle", bundle_id))

    if expected_contract_hash is not None and bundle.get("contract_hash") != expected_contract_hash:
        violations.append(Violation("E_CONTRACT_MISMATCH", "/contract_hash", "contract hash differs from expected binding", bundle_id))
    if expected_source_revision is not None and bundle.get("source_revision") != expected_source_revision:
        violations.append(Violation("E_SOURCE_DRIFT", "/source_revision", "source revision differs from expected binding", bundle_id))
    if expected_scope_hash is not None and bundle.get("scope_hash") != expected_scope_hash:
        violations.append(Violation("E_SCOPE_VIOLATION", "/scope_hash", "scope hash differs from expected binding", bundle_id))
    if expected_environment_fingerprint is not None and bundle.get("environment_fingerprint") != expected_environment_fingerprint:
        violations.append(Violation("E_SOURCE_DRIFT", "/environment_fingerprint", "environment fingerprint differs from expected binding", bundle_id))

    protected_paths = bundle.get("protected_paths") if isinstance(bundle.get("protected_paths"), list) else []
    if not protected_paths or len(protected_paths) != len(set(item for item in protected_paths if isinstance(item, str))) or any(not isinstance(item, str) or not _safe_protected_path(item) for item in protected_paths):
        violations.append(Violation("E_PROTECTED_SURFACE_CHANGED", "/protected_paths", "protected paths must be unique safe relative patterns", bundle_id))

    oracles = bundle.get("oracles") if isinstance(bundle.get("oracles"), list) else []
    rows = [row for row in oracles if isinstance(row, dict) and isinstance(row.get("id"), str)]
    oracle_ids = [row["id"] for row in rows]
    if len(oracle_ids) != len(set(oracle_ids)) or len(rows) != len(oracles):
        violations.append(Violation("E_VERIFIER_UNRESOLVED", "/oracles", "oracle IDs must be unique and every oracle must be structured", bundle_id))
    oracle_by_id = {row["id"]: row for row in rows}

    summary = bundle.get("qualification_summary") if isinstance(bundle.get("qualification_summary"), dict) else {}
    required = set(summary.get("required_oracle_ids", [])) if isinstance(summary.get("required_oracle_ids"), list) else set()
    qualified = set(summary.get("qualified_oracle_ids", [])) if isinstance(summary.get("qualified_oracle_ids"), list) else set()
    unqualified = set(summary.get("unqualified_oracle_ids", [])) if isinstance(summary.get("unqualified_oracle_ids"), list) else set()
    unknown = (required | qualified | unqualified) - set(oracle_ids)
    if unknown or qualified & unqualified:
        violations.append(Violation("E_VERIFIER_UNRESOLVED", "/qualification_summary", f"qualification summary has unknown or contradictory oracle IDs: {sorted(unknown)}", bundle_id))

    for index, oracle in enumerate(rows):
        authority = oracle.get("authority")
        level = oracle.get("qualification_level")
        oracle_id = oracle["id"]
        if authority == "candidate_supplementary" and (oracle_id in required or level == "independent" or oracle.get("protected_from_candidate") is True):
            violations.append(Violation("E_VERIFIER_UNRESOLVED", f"/oracles/{index}/authority", "candidate supplementary oracle cannot satisfy required/independent protected qualification", oracle_id))
        if oracle_id in required and authority != "candidate_supplementary" and oracle.get("protected_from_candidate") is not True:
            violations.append(Violation("E_PROTECTED_SURFACE_CHANGED", f"/oracles/{index}/protected_from_candidate", "required oracle must be protected from candidate writes", oracle_id))
        if oracle.get("class") in {"security_negative", "hidden"} and oracle_id in required and LEVEL.get(level, -1) < LEVEL["independent"]:
            violations.append(Violation("E_VERIFIER_NONDISCRIMINATING", f"/oracles/{index}/qualification_level", "security/hidden required oracle must be independently qualified", oracle_id))
        repeat = oracle.get("repeat_policy") if isinstance(oracle.get("repeat_policy"), dict) else {}
        if oracle_id in required and LEVEL.get(level, -1) >= LEVEL["stable"] and (not isinstance(repeat.get("runs"), int) or repeat.get("runs", 0) < 2 or not repeat.get("evidence_refs")):
            violations.append(Violation("E_VERIFIER_UNSTABLE", f"/oracles/{index}/repeat_policy", "stable qualification requires repeated-run evidence", oracle_id))

    if bundle.get("status") == "qualified":
        if not required or summary.get("status") != "pass" or not required.issubset(qualified) or required & unqualified:
            violations.append(Violation("E_VERIFIER_UNRESOLVED", "/qualification_summary", "qualified bundle requires a non-empty, fully qualified required oracle set", bundle_id))
        weak = [oracle_id for oracle_id in required if LEVEL.get(oracle_by_id.get(oracle_id, {}).get("qualification_level"), -1) < LEVEL["stable"]]
        if weak or not summary.get("baseline_result_refs"):
            violations.append(Violation("E_VERIFIER_UNSTABLE", "/qualification_summary/baseline_result_refs", f"qualified bundle lacks stable baseline evidence for {sorted(weak)}", bundle_id))
        discriminating = [oracle_id for oracle_id in required if LEVEL.get(oracle_by_id.get(oracle_id, {}).get("qualification_level"), -1) >= LEVEL["discriminating"]]
        if not discriminating or not summary.get("discrimination_evidence_refs"):
            violations.append(Violation("E_VERIFIER_NONDISCRIMINATING", "/qualification_summary/discrimination_evidence_refs", "qualified bundle needs a required discriminating oracle and evidence", bundle_id))
        independent = [oracle_id for oracle_id in required if LEVEL.get(oracle_by_id.get(oracle_id, {}).get("qualification_level"), -1) >= LEVEL["independent"]]
        if independent and not summary.get("independence_evidence_refs"):
            violations.append(Violation("E_VERIFIER_NONDISCRIMINATING", "/qualification_summary/independence_evidence_refs", "independent qualification requires independent evidence", bundle_id))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--contract-hash")
    parser.add_argument("--source-revision")
    parser.add_argument("--scope-hash")
    parser.add_argument("--environment-fingerprint")
    args = parser.parse_args(argv)
    try:
        bundle = load_json(args.bundle)
        schema = load_json(args.schema)
        violations = validate_bundle(
            bundle,
            schema,
            expected_contract_hash=args.contract_hash,
            expected_source_revision=args.source_revision,
            expected_scope_hash=args.scope_hash,
            expected_environment_fingerprint=args.environment_fingerprint,
        )
    except (OSError, InputError, TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "errors": [{"code": "E_SCHEMA_INVALID", "path": "", "message": str(exc)}]}, ensure_ascii=False, indent=2))
        return 2
    if violations:
        print(json.dumps({"ok": False, "errors": [item.as_dict() for item in violations]}, ensure_ascii=False, indent=2))
        return 2
    assert isinstance(bundle, dict)
    print(json.dumps({"ok": True, "bundle_id": bundle["bundle_id"], "status": bundle["status"], "content_hash": bundle["content_hash"], "oracle_count": len(bundle["oracles"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
