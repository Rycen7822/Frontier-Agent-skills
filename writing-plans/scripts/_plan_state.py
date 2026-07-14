#!/usr/bin/env python3
"""Shared stdlib-only helpers for writing-plans state tools."""

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
LOCAL_ID_RE = re.compile(r"^(I|F|D|E|P|R|G|X|AP|S)-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXTERNAL_REF_RE = re.compile(r"^[a-z_]+:[A-Za-z0-9._:-]+#[A-Za-z0-9._-]+$")
SECRET_LIKE_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)\b\s*[:=]\s*[\"']?[^\s,\"'}]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
CONTROLLED_SECRET_POINTER = re.compile(
    r"(?i)^(?:env|vault|secret|keyring|credential)(?:://|:)[A-Za-z0-9_./@-]+$"
)
VERIFIER_REF_SCHEMES = {"command", "path", "pytest", "schema", "script", "test"}


class PlanInputError(ValueError):
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
            raise PlanInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _check_bounds(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise PlanInputError(f"input nesting exceeds {MAX_DEPTH}")
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PlanInputError(f"object exceeds {MAX_COLLECTION_ITEMS} items")
        for child in value.values():
            _check_bounds(child, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PlanInputError(f"array exceeds {MAX_COLLECTION_ITEMS} items")
        for child in value:
            _check_bounds(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise PlanInputError("non-finite JSON number is not allowed")


def load_json(path: str | Path) -> Any:
    source = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise PlanInputError(f"input is not a regular file: {source}")
            if metadata.st_size > MAX_INPUT_BYTES:
                raise PlanInputError(f"input is {metadata.st_size} bytes; maximum is {MAX_INPUT_BYTES}")
            payload = stream.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise PlanInputError(f"input exceeds maximum of {MAX_INPUT_BYTES} bytes")
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError, PlanInputError) as exc:
        raise PlanInputError(str(exc)) from exc
    _check_bounds(value)
    return value


def pointer(parts: Iterable[str | int]) -> str:
    escaped = [str(p).replace("~", "~0").replace("/", "~1") for p in parts]
    return "/" + "/".join(escaped) if escaped else ""


def canonical_state_hash(state: dict[str, Any]) -> str:
    clean = dict(state)
    clean.pop("content_hash", None)
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def capsule_source_hash(state: dict[str, Any]) -> str:
    """Hash canonical plan semantics while excluding generated capsule records."""
    clean = dict(state)
    clean["snapshots"] = [
        snapshot
        for snapshot in state.get("snapshots", [])
        if not isinstance(snapshot, dict) or snapshot.get("kind") != "capsule"
    ]
    return canonical_state_hash(clean)


def file_hash(path: str | Path) -> str:
    return "sha256:" + sha256(Path(path).read_bytes()).hexdigest()


def contains_secret_like(value: Any) -> bool:
    """Conservatively identify raw credential-shaped values in state payloads."""
    if isinstance(value, str):
        assignment_pattern, *direct_patterns = SECRET_LIKE_PATTERNS
        for match in assignment_pattern.finditer(value):
            parts = re.split(r"\s*[:=]\s*", match.group(0), maxsplit=1)
            assigned = parts[1].strip("\"'") if len(parts) == 2 else ""
            if not CONTROLLED_SECRET_POINTER.fullmatch(assigned):
                return True
        return any(pattern.search(value) for pattern in direct_patterns)
    if isinstance(value, dict):
        return any(contains_secret_like(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_secret_like(child) for child in value)
    return False


def redact_secret_like(value: str) -> str:
    """Defense-in-depth redaction for generated projections."""
    result = value
    for pattern in SECRET_LIKE_PATTERNS:
        result = pattern.sub("[REDACTED_SECRET]", result)
    return result


def is_local_id(value: Any) -> bool:
    return isinstance(value, str) and LOCAL_ID_RE.fullmatch(value) is not None


def verifier_ref_is_structured(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    scheme, separator, target = value.partition(":")
    return separator == ":" and scheme in VERIFIER_REF_SCHEMES and bool(target.strip())


def is_ref(value: Any) -> bool:
    return is_local_id(value) or (isinstance(value, str) and EXTERNAL_REF_RE.fullmatch(value) is not None)


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise PlanInputError(f"unsupported schema ref: {ref}")
    current: Any = root_schema
    for segment in ref[2:].split("/"):
        current = current[segment.replace("~1", "/").replace("~0", "~")]
    if not isinstance(current, dict):
        raise PlanInputError(f"schema ref does not resolve to object: {ref}")
    return current


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _valid_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def validate_against_schema(value: Any, schema: dict[str, Any], root_schema: dict[str, Any] | None = None, parts: tuple[str | int, ...] = ()) -> list[Violation]:
    root = root_schema or schema
    if "$ref" in schema:
        return validate_against_schema(value, _resolve_ref(root, schema["$ref"]), root, parts)
    if "oneOf" in schema:
        candidates = [validate_against_schema(value, candidate, root, parts) for candidate in schema["oneOf"]]
        if sum(not errors for errors in candidates) != 1:
            return [Violation("plan.schema", pointer(parts), "value must satisfy exactly one schema alternative")]
        return []

    violations: list[Violation] = []
    expected = schema.get("type")
    if expected and not _type_matches(value, expected):
        return [Violation("plan.schema", pointer(parts), f"expected {expected}, got {type(value).__name__}")]
    if "const" in schema and value != schema["const"]:
        violations.append(Violation("plan.schema", pointer(parts), f"expected constant {schema['const']!r}"))
    if "enum" in schema and value not in schema["enum"]:
        violations.append(Violation("plan.schema", pointer(parts), f"value is not in enum {schema['enum']}"))

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            violations.append(Violation("plan.schema", pointer(parts), "string is shorter than minLength"))
        if len(value) > schema.get("maxLength", 10**9):
            violations.append(Violation("plan.schema", pointer(parts), "string exceeds maxLength"))
        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            violations.append(Violation("plan.schema", pointer(parts), f"string does not match {pattern}"))
        if schema.get("format") == "date-time" and not _valid_datetime(value):
            violations.append(Violation("plan.schema", pointer(parts), "invalid RFC3339/ISO date-time"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            violations.append(Violation("plan.schema", pointer(parts), "number is below minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            violations.append(Violation("plan.schema", pointer(parts), "number exceeds maximum"))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            violations.append(Violation("plan.schema", pointer(parts), "number is not above exclusiveMinimum"))

    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10**9):
            violations.append(Violation("plan.schema", pointer(parts), "array exceeds maxItems"))
        item_schema = schema.get("items")
        if item_schema:
            for index, child in enumerate(value):
                violations.extend(validate_against_schema(child, item_schema, root, parts + (index,)))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                violations.append(Violation("plan.schema", pointer(parts + (required,)), "required property is missing"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    violations.append(Violation("plan.schema", pointer(parts + (key,)), "unknown property"))
        for key, child_schema in properties.items():
            if key in value:
                violations.extend(validate_against_schema(value[key], child_schema, root, parts + (key,)))
    return violations


def normalized_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix().lstrip("./")


def path_allowed(path: str, patterns: list[str]) -> bool:
    candidate = normalized_path(path)
    for pattern in patterns:
        normalized = normalized_path(pattern)
        if fnmatchcase(candidate, normalized) or fnmatchcase(candidate, normalized.rstrip("/**") + "/**"):
            return True
        prefix = normalized.split("*", 1)[0].rstrip("/")
        if prefix and (candidate == prefix or candidate.startswith(prefix + "/")):
            return True
    return False


def _static_prefix(pattern: str) -> str:
    return normalized_path(pattern).split("*", 1)[0].rstrip("/")


def patterns_may_overlap(left: str, right: str) -> bool:
    a, b = normalized_path(left), normalized_path(right)
    if a == b or fnmatchcase(a, b) or fnmatchcase(b, a):
        return True
    pa, pb = _static_prefix(a), _static_prefix(b)
    if not pa or not pb:
        return True
    return pa == pb or pa.startswith(pb + "/") or pb.startswith(pa + "/")


def json_output(ok: bool, violations: list[Violation], **extra: Any) -> dict[str, Any]:
    return {"ok": ok, "violations": [item.as_dict() for item in violations], **extra}
