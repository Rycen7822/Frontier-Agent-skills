"""Structural validation, captured-source reading, and code location for review records.

This module never runs Git, tests, or any other external program. Callers pass
byte content in and receive stable error codes or plain dictionaries back.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

try:  # pragma: no cover - the import failure path is exercised through E_DEPENDENCY
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None  # type: ignore[assignment]


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "review-record.schema.json"
SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"
KIND_REFS = {
    "scope": "#/$defs/scope",
    "record": "#/$defs/record",
    "check_report": "#/$defs/check_report",
}
LAYER_ORDER = ("commit", "range", "index", "worktree", "untracked", "snapshot")
CAPTURED_AVAILABILITY = ("text", "binary", "symlink")
TEXT_AVAILABILITY = "text"
SCOPE_FILE = "scope.json"
SCOPE_SCHEMA_VERSION = "fas-review-scope/1"
RECORD_SCHEMA_VERSION = "fas-review-record/1"
CHECK_SCHEMA_VERSION = "fas-review-check/1"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PACKET_BYTES = 128 * 1024 * 1024
MAX_ITEMS = 20000
MAX_JSON_BYTES = 16 * 1024 * 1024
CANDIDATE_LIMIT = MAX_ITEMS


class ReviewError(ValueError):
    """A stable error code with a readable message.

    ``code`` is reported verbatim in check problems and on stderr; ``pointer``
    is an optional JSON pointer into the offending document.
    """

    def __init__(self, code: str, message: str, pointer: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.pointer = pointer

    def problem(self) -> dict[str, str]:
        return {"code": self.code, "pointer": self.pointer, "message": self.message}


def sha256_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_bytes_limited(path: Path, limit: int, code: str) -> bytes:
    """Read at most ``limit`` bytes, failing instead of truncating the input."""
    with open(path, "rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ReviewError(code, f"{path} exceeds the {limit} byte limit")
    return raw


def load_json(path: Path) -> dict[str, Any]:
    """Parse a JSON object, rejecting duplicate keys and non-finite numbers."""
    target = Path(path)
    try:
        raw = read_bytes_limited(target, MAX_JSON_BYTES, "E_JSON_TOO_LARGE")
    except FileNotFoundError as exc:
        raise ReviewError("E_INPUT_MISSING", f"{target} does not exist") from exc
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError(
            "E_JSON_ENCODING", f"{target} is not valid UTF-8: {exc.reason}"
        ) from exc
    if text.startswith("\ufeff"):
        raise ReviewError("E_JSON_ENCODING", f"{target} starts with a byte-order mark")

    def reject_duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError("E_JSON_DUPLICATE_KEY", f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ReviewError("E_JSON_CONSTANT", f"non-finite JSON number {value}")

    try:
        value = json.loads(
            text, object_pairs_hook=reject_duplicate_key, parse_constant=reject_constant
        )
    except ReviewError:
        raise
    except json.JSONDecodeError as exc:
        raise ReviewError(
            "E_JSON_SYNTAX", f"{target}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewError("E_JSON_ROOT", f"{target} root is not a JSON object")
    return value


_SCHEMA_CACHE: dict[str, Any] | None = None


def _schema_definitions() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        raw = read_bytes_limited(SCHEMA_PATH, MAX_JSON_BYTES, "E_SCHEMA")
        document = json.loads(raw.decode("utf-8"))
        _SCHEMA_CACHE = document["$defs"]
    return _SCHEMA_CACHE


def validate_document(value: dict[str, Any], kind: str) -> None:
    """Validate one of the three roots against the shared schema $defs."""
    if kind not in KIND_REFS:
        raise ReviewError("E_KIND", f"unknown document kind {kind!r}")
    if Draft202012Validator is None:
        raise ReviewError(
            "E_DEPENDENCY", "the jsonschema package is required for document validation"
        )
    entry = {"$schema": SCHEMA_URI, "$ref": KIND_REFS[kind], "$defs": _schema_definitions()}
    errors = sorted(
        Draft202012Validator(entry).iter_errors(value),
        key=lambda error: (list(error.absolute_path), error.message),
    )
    if errors:
        error = errors[0]
        pointer = "".join(f"/{part}" for part in error.absolute_path)
        raise ReviewError(
            "E_SCHEMA", f"{kind} is invalid: {error.message}", pointer
        )


def split_lines(raw: bytes) -> list[bytes]:
    """Split on LF only; a CR adjacent to a removed LF is dropped, a final lone CR kept."""
    if not raw:
        return []
    segments = raw.split(b"\n")
    lines = [
        segment[:-1] if segment.endswith(b"\r") else segment for segment in segments[:-1]
    ]
    tail = segments[-1]
    if tail:
        lines.append(tail)
    return lines


def count_lines(raw: bytes) -> int:
    return len(split_lines(raw))


def read_source(packet: Path, source: dict[str, Any]) -> bytes:
    """Read one captured object, keyed only by its recorded digest."""
    digest = source.get("sha256")
    if not isinstance(digest, str) or not DIGEST_RE.match(digest):
        raise ReviewError("E_SOURCE_OBJECT", "source has no valid sha256 digest")
    objects = Path(packet) / "objects"
    if objects.is_symlink():
        raise ReviewError("E_SOURCE_OBJECT", f"{objects} must not be a symlink")
    blob = objects / f"{digest[7:]}.blob"
    if blob.is_symlink():
        raise ReviewError("E_SOURCE_OBJECT", f"{blob.name} must not be a symlink")
    try:
        raw = read_bytes_limited(blob, MAX_FILE_BYTES, "E_SOURCE_OBJECT")
    except FileNotFoundError as exc:
        raise ReviewError(
            "E_SOURCE_OBJECT", f"captured object {blob.name} is missing from the packet"
        ) from exc
    size = source.get("size_bytes")
    if size != len(raw):
        raise ReviewError(
            "E_SOURCE_OBJECT",
            f"{blob.name} has {len(raw)} bytes but the scope records {size}",
        )
    if sha256_digest(raw) != digest:
        raise ReviewError("E_SOURCE_OBJECT", f"{blob.name} does not match its digest")
    return raw


def _find_matches(lines: list[bytes], snippet_lines: list[bytes]) -> list[tuple[int, int]]:
    span = len(snippet_lines)
    if span == 0 or span > len(lines):
        return []
    matches: list[tuple[int, int]] = []
    for start in range(0, len(lines) - span + 1):
        if lines[start : start + span] == snippet_lines:
            matches.append((start + 1, start + span))
            if len(matches) > CANDIDATE_LIMIT:
                break
    return matches


def locate_anchor(raw: bytes | None, anchor: dict[str, Any]) -> dict[str, Any]:
    """Locate one evidence snippet inside its own source bytes.

    ``raw`` is None when the referenced source holds no text bytes, which is the
    only case that reports ``unsupported_source``. The input anchor is not modified.
    """
    result: dict[str, Any] = {
        "status": "unlocated",
        "start_line": None,
        "end_line": None,
        "candidate_start": None,
        "candidate_end": None,
    }
    if raw is None:
        result["status"] = "unsupported_source"
        return result

    snippet = anchor.get("snippet")
    start = anchor.get("start_line")
    end = anchor.get("end_line")
    if start is None and end is not None:
        raise ReviewError("E_LOCATION_RANGE", "end_line is set without start_line")
    if start is not None and start > end:
        raise ReviewError(
            "E_LOCATION_RANGE", f"line range {start}-{end} starts after it ends"
        )
    if snippet is None:
        return result

    lines = split_lines(raw)
    snippet_lines = split_lines(snippet.encode("utf-8"))
    if start is not None:
        if end > len(lines):
            raise ReviewError(
                "E_LOCATION_RANGE",
                f"line range {start}-{end} exceeds {len(lines)} lines of the source",
            )
        if lines[start - 1 : end] == snippet_lines:
            result.update(status="resolved", start_line=start, end_line=end)
            return result
        result.update(start_line=start, end_line=end)
        matches = _find_matches(lines, snippet_lines)
        if len(matches) == 1:
            result.update(
                status="needs_relocation",
                candidate_start=matches[0][0],
                candidate_end=matches[0][1],
            )
        elif matches:
            result["status"] = "ambiguous"
        return result

    matches = _find_matches(lines, snippet_lines)
    if len(matches) == 1:
        result.update(
            status="resolved",
            start_line=matches[0][0],
            end_line=matches[0][1],
        )
    elif matches:
        result["status"] = "ambiguous"
    return result


def _require(condition: bool, code: str, message: str, pointer: str = "") -> None:
    if not condition:
        raise ReviewError(code, message, pointer)


def _validate_scope_relations(scope: dict[str, Any]) -> None:
    """Cross-field scope rules that JSON Schema does not express."""
    resolved = scope["resolved"]
    oid_digits = 40 if resolved["object_format"] == "sha1" else 64
    for field in ("base_oid", "head_oid", "comparison_base_oid"):
        oid = resolved[field]
        if oid is not None:
            _require(
                len(oid) == oid_digits,
                "E_SCOPE_OID",
                f"resolved.{field} does not match object format {resolved['object_format']}",
                f"/resolved/{field}",
            )

    mode = scope["mode"]
    request = scope["request"]
    observation = scope["observation"]
    if mode == "snapshot":
        expected = (
            "bounded_double_observation"
            if request["revision"] == "WORKTREE"
            else "immutable_commits"
        )
        _require(
            observation == expected,
            "E_SCOPE_OBSERVATION",
            f"snapshot mode with revision {request['revision']!r} needs observation {expected}",
            "/observation",
        )
        _require(
            resolved["head_oid"] is not None or request["revision"] == "WORKTREE",
            "E_SCOPE_OID",
            "snapshot mode without WORKTREE needs a resolved head_oid",
            "/resolved/head_oid",
        )
    if mode == "workspace":
        _require(
            resolved["base_oid"] is None,
            "E_SCOPE_OID",
            "workspace mode has no base_oid",
            "/resolved/base_oid",
        )

    items = scope["items"]
    _require(
        len(items) <= MAX_ITEMS,
        "E_ITEMS_LIMIT",
        f"scope has {len(items)} items, over the {MAX_ITEMS} limit",
    )
    item_ids: set[str] = set()
    previous_key: tuple[int, bytes] | None = None
    for index, item in enumerate(items):
        _require(
            item["id"] == f"I-{index + 1:06d}",
            "E_ITEM_ID",
            f"item {index} has id {item['id']} outside the fixed sequence",
            f"/items/{index}/id",
        )
        _require(
            item["id"] not in item_ids,
            "E_DUPLICATE_ID",
            f"duplicate item id {item['id']}",
            f"/items/{index}/id",
        )
        item_ids.add(item["id"])
        _require(
            (item["layer"] == "snapshot") == (item["status"] == "P"),
            "E_ITEM_STATUS",
            f"item {item['id']} pairs layer {item['layer']} with status {item['status']}",
            f"/items/{index}/status",
        )
        key = (LAYER_ORDER.index(item["layer"]), item["path"].encode("utf-8"))
        if previous_key is not None:
            _require(
                previous_key < key,
                "E_ITEM_ORDER",
                f"item {item['id']} is out of order for ({item['layer']}, {item['path']!r})",
                f"/items/{index}",
            )
        previous_key = key

    sources = scope["sources"]
    source_ids: set[str] = set()
    previous_source: tuple[str, str, bytes, str] | None = None
    for index, source in enumerate(sources):
        _require(
            source["id"] == f"S-{index + 1:06d}",
            "E_SOURCE_ID",
            f"source {index} has id {source['id']} outside the fixed sequence",
            f"/sources/{index}/id",
        )
        _require(
            source["id"] not in source_ids,
            "E_DUPLICATE_ID",
            f"duplicate source id {source['id']}",
            f"/sources/{index}/id",
        )
        source_ids.add(source["id"])
        for field in ("revision", "git_oid"):
            oid = source[field]
            if oid is not None:
                _require(
                    len(oid) == oid_digits,
                    "E_SCOPE_OID",
                    f"source {source['id']} has {field} outside object format "
                    f"{resolved['object_format']}",
                    f"/sources/{index}/{field}",
                )
        key = (
            source["origin"],
            source["revision"] or "",
            source["path"].encode("utf-8"),
            source["git_oid"] or "",
        )
        if previous_source is not None:
            _require(
                previous_source < key,
                "E_SOURCE_ORDER",
                f"source {source['id']} is out of order",
                f"/sources/{index}",
            )
        previous_source = key

    for index, item in enumerate(items):
        for side in ("before", "after"):
            reference = item[side]
            if reference is not None:
                _require(
                    reference in source_ids,
                    "E_REFERENCE_UNKNOWN",
                    f"item {item['id']} references unknown source {reference}",
                    f"/items/{index}/{side}",
                )
    _require(
        len(sources) <= 3 * MAX_ITEMS,
        "E_SOURCES_LIMIT",
        f"scope has {len(sources)} sources, over the {3 * MAX_ITEMS} limit",
    )


def _scope_sources_are_text(scope: dict[str, Any], item: dict[str, Any]) -> bool:
    by_id = {source["id"]: source for source in scope["sources"]}
    for side in ("before", "after"):
        reference = item[side]
        if reference is not None and by_id[reference]["availability"] != TEXT_AVAILABILITY:
            return False
    return True


def _verify_scope_digest(packet: Path, record: dict[str, Any]) -> None:
    scope_path = Path(packet) / SCOPE_FILE
    _require(
        scope_path.is_file(),
        "E_SCOPE_MISSING",
        f"{packet} has no {SCOPE_FILE}",
    )
    scope_raw = read_bytes_limited(scope_path, MAX_JSON_BYTES, "E_JSON_TOO_LARGE")
    _require(
        record["scope_sha256"] == sha256_digest(scope_raw),
        "E_SCOPE_DIGEST",
        "record scope_sha256 does not match the packet scope.json",
        "/scope_sha256",
    )


def _validate_coverage(scope: dict[str, Any], record: dict[str, Any]) -> tuple[str, dict[str, int]]:
    """Cover each item exactly once and report the declared coverage status."""
    items = scope["items"]
    item_ids = {item["id"] for item in items}
    seen: set[str] = set()
    for index, entry in enumerate(record["coverage"]):
        item_id = entry["item_id"]
        _require(
            item_id in item_ids,
            "E_COVERAGE_UNKNOWN",
            f"coverage references unknown item {item_id}",
            f"/coverage/{index}/item_id",
        )
        _require(
            item_id not in seen,
            "E_COVERAGE_DUPLICATE",
            f"coverage repeats item {item_id}",
            f"/coverage/{index}/item_id",
        )
        seen.add(item_id)
    missing = [item["id"] for item in items if item["id"] not in seen]
    _require(
        not missing,
        "E_COVERAGE_MISSING",
        f"coverage omits items {', '.join(sorted(missing))}",
        "/coverage",
    )
    counts = {"total": len(items), "reviewed": 0, "partial": 0, "not_reviewed": 0}
    for entry in record["coverage"]:
        counts[entry["status"]] += 1
    if not items:
        _require(
            not record["findings"] and not record["concerns"],
            "E_EMPTY_SCOPE_FINDINGS",
            "an empty scope cannot carry findings or concerns",
            "/findings",
        )
        return "nothing_in_scope", counts
    declared = {entry["item_id"]: entry["status"] for entry in record["coverage"]}
    for index, item in enumerate(items):
        if declared[item["id"]] == "reviewed" and not _scope_sources_are_text(scope, item):
            raise ReviewError(
                "E_COVERAGE_UNSUPPORTED",
                f"item {item['id']} has a source without captured text bytes "
                "and cannot be declared reviewed",
                f"/coverage/{index}",
            )
    if counts["reviewed"] == counts["total"]:
        return "all_declared_reviewed", counts
    return "partial", counts


def _verify_captured_sources(packet: Path, scope: dict[str, Any]) -> None:
    """Read every captured object back and check its digest and recorded line count."""
    for index, source in enumerate(scope["sources"]):
        availability = source["availability"]
        if availability not in CAPTURED_AVAILABILITY:
            continue
        raw = read_source(packet, source)
        if availability == TEXT_AVAILABILITY:
            actual = count_lines(raw)
            _require(
                source["line_count"] == actual,
                "E_SOURCE_LINES",
                f"source {source['id']} records {source['line_count']} lines "
                f"but holds {actual}",
                f"/sources/{index}/line_count",
            )


def _validate_findings(
    packet: Path, scope: dict[str, Any], record: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check finding references and locate each evidence snippet in its own source."""
    item_ids = {item["id"] for item in scope["items"]}
    sources = {source["id"]: source for source in scope["sources"]}
    finding_ids: set[str] = set()
    anchors: list[dict[str, Any]] = []
    for finding_index, finding in enumerate(record["findings"]):
        _require(
            finding["id"] not in finding_ids,
            "E_DUPLICATE_ID",
            f"duplicate finding id {finding['id']}",
            f"/findings/{finding_index}/id",
        )
        finding_ids.add(finding["id"])
        for item_index, item_id in enumerate(finding["item_ids"]):
            _require(
                item_id in item_ids,
                "E_REFERENCE_UNKNOWN",
                f"finding {finding['id']} references unknown item {item_id}",
                f"/findings/{finding_index}/item_ids/{item_index}",
            )
        for evidence_index, evidence in enumerate(finding["evidence"]):
            source = sources.get(evidence["source_id"])
            _require(
                source is not None,
                "E_REFERENCE_UNKNOWN",
                f"finding {finding['id']} references unknown source "
                f"{evidence['source_id']}",
                f"/findings/{finding_index}/evidence/{evidence_index}/source_id",
            )
            raw = (
                read_source(packet, source)
                if source["availability"] == TEXT_AVAILABILITY
                else None
            )
            location = locate_anchor(raw, evidence)
            anchors.append(
                {
                    "finding_id": finding["id"],
                    "evidence_index": evidence_index,
                    "source_id": source["id"],
                    "path": source["path"],
                    "origin": source["origin"],
                    "revision": source["revision"],
                    **location,
                }
            )
    return anchors


def _validate_concerns(record: dict[str, Any], item_ids: set[str]) -> None:
    concern_ids: set[str] = set()
    for index, concern in enumerate(record["concerns"]):
        _require(
            concern["id"] not in concern_ids,
            "E_DUPLICATE_ID",
            f"duplicate concern id {concern['id']}",
            f"/concerns/{index}/id",
        )
        concern_ids.add(concern["id"])
        for item_index, item_id in enumerate(concern["item_ids"]):
            _require(
                item_id in item_ids,
                "E_REFERENCE_UNKNOWN",
                f"concern {concern['id']} references unknown item {item_id}",
                f"/concerns/{index}/item_ids/{item_index}",
            )


def _validate_verification(record: dict[str, Any]) -> None:
    verification_ids: set[str] = set()
    for index, entry in enumerate(record["verification"]):
        _require(
            entry["id"] not in verification_ids,
            "E_DUPLICATE_ID",
            f"duplicate verification id {entry['id']}",
            f"/verification/{index}/id",
        )
        verification_ids.add(entry["id"])


def validate_record(
    packet: Path, scope: dict[str, Any], record: dict[str, Any]
) -> dict[str, Any]:
    """Validate structure, set relations, captured objects, and anchors."""
    validate_document(scope, "scope")
    validate_document(record, "record")
    _validate_scope_relations(scope)
    _verify_scope_digest(packet, record)
    coverage_status, counts = _validate_coverage(scope, record)
    _verify_captured_sources(packet, scope)
    anchors = _validate_findings(packet, scope, record)
    _validate_concerns(record, {item["id"] for item in scope["items"]})
    _validate_verification(record)
    return {
        "validation": "valid",
        "coverage_status": coverage_status,
        "item_counts": counts,
        "finding_count": len(record["findings"]),
        "concern_count": len(record["concerns"]),
        "failed_verification": any(
            entry["status"] == "failed" for entry in record["verification"]
        ),
        "anchors": anchors,
        "problems": [],
        "limitations": list(record["limitations"]),
    }


def finish_report(
    validation: dict[str, Any], freshness: dict[str, Any]
) -> dict[str, Any]:
    """Combine validation and freshness into the single check report shape."""
    if validation.get("validation") != "valid":
        problems = validation.get("problems") or [
            {"code": "E_SCHEMA", "pointer": "", "message": "the record is invalid"}
        ]
        return {
            "schema_version": CHECK_SCHEMA_VERSION,
            "validation": "invalid",
            "coverage_status": "unavailable",
            "freshness": {"status": "not_checked", "changed_paths": []},
            "finding_count": None,
            "concern_count": None,
            "item_counts": None,
            "anchors": [],
            "problems": problems,
            "limitations": list(validation.get("limitations") or []),
            "exit_code": 2,
        }

    exit_code = 0
    if validation["coverage_status"] == "partial":
        exit_code = 4
    if freshness.get("status") in ("changed", "incomplete"):
        exit_code = 4
    if any(anchor["status"] != "resolved" for anchor in validation["anchors"]):
        exit_code = 4
    if validation["concern_count"]:
        exit_code = 4
    if validation.get("failed_verification"):
        exit_code = 4
    return {
        "schema_version": CHECK_SCHEMA_VERSION,
        "validation": "valid",
        "coverage_status": validation["coverage_status"],
        "freshness": {
            "status": freshness["status"],
            "changed_paths": list(freshness["changed_paths"]),
        },
        "finding_count": validation["finding_count"],
        "concern_count": validation["concern_count"],
        "item_counts": dict(validation["item_counts"]),
        "anchors": list(validation["anchors"]),
        "problems": list(validation["problems"]),
        "limitations": list(validation["limitations"]),
        "exit_code": exit_code,
    }
