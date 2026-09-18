"""Structural validation, captured-source reading, and code location for review records.

This module never runs Git or any other external program: callers pass bytes in
and receive stable error codes or plain dictionaries back.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable

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
CHECK_SCHEMA_VERSION = "fas-review-check/1"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_PACKET_BYTES = 128 * 1024 * 1024
MAX_ITEMS = 20000
MAX_JSON_BYTES = 16 * 1024 * 1024
WORKTREE_REVISION = "WORKTREE"
MAX_PATH_BYTES = 4096
PROBLEM_MESSAGE_LIMIT = 512
PROBLEM_POINTER_LIMIT = 1024


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


def read_bytes_limited(
    path: Path,
    limit: int,
    code: str,
    *,
    missing_code: str | None = None,
    type_code: str | None = None,
    io_code: str | None = None,
) -> bytes:
    """Read at most ``limit`` bytes, mapping expected IO failures to typed errors."""
    try:
        with open(path, "rb") as stream:
            raw = stream.read(limit + 1)
    except IsADirectoryError as exc:
        raise ReviewError(type_code or code, f"{path} is a directory") from exc
    except FileNotFoundError as exc:
        raise ReviewError(missing_code or code, f"{path} does not exist") from exc
    except PermissionError as exc:
        raise ReviewError(io_code or code, f"{path} cannot be read: permission denied") from exc
    except OSError as exc:
        raise ReviewError(io_code or code, f"{path} cannot be read: {exc.strerror}") from exc
    if len(raw) > limit:
        raise ReviewError(code, f"{path} exceeds the {limit} byte limit")
    return raw


def encode_document(value: dict[str, Any], code: str = "E_JSON_TOO_LARGE") -> bytes:
    """Encode one document and bound it before anything is written."""
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(raw) > MAX_JSON_BYTES:
        raise ReviewError(
            code, f"the document needs {len(raw)} bytes, over the {MAX_JSON_BYTES} limit"
        )
    return raw


def dedupe_texts(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))
def normalize_path(path: str, label: str) -> str:
    """Reject forbidden literal paths and return the canonical Git spelling.

    Collapsing ``.`` segments is safe only after the raw value is known to
    carry no parent or metadata component, so the checks run first.
    """
    if not path or "\x00" in path:
        raise ReviewError("E_PATH_INVALID", f"the {label} is empty or holds a NUL byte")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in path):
        raise ReviewError("E_PATH_ENCODING", f"the {label} is not decodable UTF-8 text")
    if len(path.encode("utf-8")) > MAX_PATH_BYTES:
        raise ReviewError("E_PATH_INVALID", f"the {label} exceeds {MAX_PATH_BYTES} UTF-8 bytes")
    components = path.split("/")
    if path.startswith("/") or ".." in components or ".git" in components:
        raise ReviewError("E_PATH_INVALID", f"the {label} {path!r} is not a literal path")
    return PurePosixPath(path).as_posix()


def decode_json(raw: bytes, label: str) -> dict[str, Any]:
    """Parse one JSON object, rejecting bad text, duplicate keys, and lone surrogates.

    The strict encode catches unpaired surrogates that ``json.loads`` accepts
    from escape sequences while leaving valid pairs untouched.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewError("E_JSON_ENCODING", f"{label} is not valid UTF-8: {exc.reason}") from exc
    if text.startswith("\ufeff"):
        raise ReviewError("E_JSON_ENCODING", f"{label} starts with a byte-order mark")

    def reject_duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReviewError(
                    "E_JSON_DUPLICATE_KEY",
                    f"the JSON object repeats a key name of length {len(key)}",
                )
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
        raise ReviewError("E_JSON_SYNTAX", f"{label}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ReviewError("E_JSON_ROOT", f"{label} root is not a JSON object")
    try:
        json.dumps(value, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ReviewError("E_JSON_ENCODING", f"{label} holds an unpaired surrogate") from exc
    return value


def load_json(path: Path) -> dict[str, Any]:
    """Read and parse one JSON object from the file system."""
    target = Path(path)
    bounds = {
        "missing_code": "E_INPUT_MISSING",
        "type_code": "E_INPUT_TYPE",
        "io_code": "E_INPUT_IO",
    }
    return decode_json(read_bytes_limited(target, MAX_JSON_BYTES, "E_JSON_TOO_LARGE", **bounds),
                       str(target))


_SCHEMA_CACHE: dict[str, Any] | None = None


def _schema_definitions() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        document = json.loads(read_bytes_limited(SCHEMA_PATH, MAX_JSON_BYTES, "E_SCHEMA"))
        _SCHEMA_CACHE = document["$defs"]
    return _SCHEMA_CACHE


def _schema_error(kind: str, error: Any) -> ReviewError:
    """Turn the first schema failure into a bounded diagnostic.

    The message carries the failed validator and, when the schema fixes a short
    limit, that value; instance content is never echoed, and a pointer that
    cannot be expressed inside the protocol bound is dropped instead of cut.
    """
    parts = list(error.absolute_path)
    pointer = "".join(f"/{str(part).replace('~', '~0').replace('/', '~1')}" for part in parts)
    dropped = bool(parts) and len(pointer) > PROBLEM_POINTER_LIMIT
    if dropped:
        pointer = ""
    limit = error.validator_value
    short_limit = (
        f" ({limit})" if isinstance(limit, (int, bool)) or (isinstance(limit, str) and len(limit) <= 40)
        else ""
    )
    message = f"{kind} is invalid: {error.validator} failed{short_limit}"
    if dropped:
        message += "; the failing path is too long to report"
    if len(message) > PROBLEM_MESSAGE_LIMIT:
        message = message[: PROBLEM_MESSAGE_LIMIT - 3] + "..."
    return ReviewError("E_SCHEMA", message, pointer)


def validate_document(value: dict[str, Any], kind: str) -> None:
    """Validate one of the three roots against the shared schema $defs."""
    if kind not in KIND_REFS:
        raise ReviewError("E_KIND", f"unknown document kind {kind!r}")
    if Draft202012Validator is None:
        raise ReviewError(
            "E_DEPENDENCY", "the jsonschema package is required for document validation"
        )
    entry = {"$schema": SCHEMA_URI, "$ref": KIND_REFS[kind], "$defs": _schema_definitions()}
    for error in Draft202012Validator(entry).iter_errors(value):
        raise _schema_error(kind, error)


def validate_scope(scope: dict[str, Any]) -> None:
    """Validate one scope document: schema shape plus cross-object relations."""
    validate_document(scope, "scope")
    _validate_scope_mode(scope)
    _validate_scope_items(scope)
    _validate_scope_sources(scope)


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
    """Count LF-terminated lines without building a line array."""
    if not raw:
        return 0
    return raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)


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
    raw = read_bytes_limited(blob, MAX_FILE_BYTES, "E_SOURCE_OBJECT")
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
            if len(matches) == 2:
                break
    return matches


def locate_anchor(raw: bytes | None, anchor: dict[str, Any]) -> dict[str, Any]:
    """Locate one evidence snippet inside its own source bytes."""
    return _locate_in_lines(None if raw is None else split_lines(raw), anchor)


def _locate_in_lines(
    lines: list[bytes] | None, anchor: dict[str, Any]
) -> dict[str, Any]:
    """Locate one snippet inside lines the caller already split.

    ``lines`` is None when the referenced source holds no text bytes, which is
    the only case that reports ``unsupported_source``. Every text anchor of one
    blob shares a single line list; snippets are always split here.
    """
    result: dict[str, Any] = {
        "status": "unlocated",
        "start_line": None,
        "end_line": None,
        "candidate_start": None,
        "candidate_end": None,
    }
    if lines is None:
        result["status"] = "unsupported_source"
        return result

    snippet = anchor.get("snippet")
    start, end = anchor.get("start_line"), anchor.get("end_line")
    if start is None and end is not None:
        raise ReviewError("E_LOCATION_RANGE", "end_line is set without start_line")
    if start is not None and start > end:
        raise ReviewError("E_LOCATION_RANGE", f"line range {start}-{end} starts after it ends")
    if snippet is None:
        return result

    snippet_lines = split_lines(snippet.encode("utf-8"))
    if start is not None:
        result.update(start_line=start, end_line=end)
        if end > len(lines):
            raise ReviewError(
                "E_LOCATION_RANGE",
                f"line range {start}-{end} exceeds {len(lines)} lines of the source",
            )
        if lines[start - 1 : end] == snippet_lines:
            result["status"] = "resolved"
            return result
        matches = _find_matches(lines, snippet_lines)
        if len(matches) == 1:
            result.update(status="needs_relocation", candidate_start=matches[0][0],
                          candidate_end=matches[0][1])
        elif matches:
            result["status"] = "ambiguous"
        return result

    matches = _find_matches(lines, snippet_lines)
    if len(matches) == 1:
        result.update(status="resolved", start_line=matches[0][0], end_line=matches[0][1])
    elif matches:
        result["status"] = "ambiguous"
    return result


def _require(condition: bool, code: str, message: str, pointer: str = "") -> None:
    if not condition:
        raise ReviewError(code, message, pointer)


def _require_canonical_path(path: str, label: str, pointer: str) -> None:
    """Reject a recorded path that is not already in canonical spelling."""
    canonical = normalize_path(path, label)
    _require(
        path == canonical,
        "E_SCOPE_PATH",
        f"the {label} {path!r} is not canonical; capture the scope again",
        pointer,
    )


def _validate_scope_mode(scope: dict[str, Any]) -> None:
    """Check the mode relations the schema cannot express."""
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
    request = scope["request"]
    for field in ("paths", "context_paths"):
        for index, path in enumerate(request[field]):
            _require_canonical_path(path, f"request {field}", f"/request/{field}/{index}")
    if scope["mode"] != "snapshot":
        return
    expected = (
        "bounded_double_observation"
        if request["revision"] == WORKTREE_REVISION
        else "immutable_commits"
    )
    _require(
        scope["observation"] == expected,
        "E_SCOPE_OBSERVATION",
        f"snapshot mode with revision {request['revision']!r} needs observation {expected}",
        "/observation",
    )
    _require(
        resolved["head_oid"] is not None or request["revision"] == WORKTREE_REVISION,
        "E_SCOPE_OID",
        "snapshot mode without WORKTREE needs a resolved head_oid",
        "/resolved/head_oid",
    )


def _validate_scope_items(scope: dict[str, Any]) -> None:
    """Check the item sequence and ordering; the fixed sequence rules out duplicates."""
    previous_key: tuple[int, bytes] | None = None
    for index, item in enumerate(scope["items"]):
        _require_canonical_path(item["path"], "item path", f"/items/{index}/path")
        _require(
            item["id"] == f"I-{index + 1:06d}",
            "E_ITEM_ID",
            f"item {index} has id {item['id']} outside the fixed sequence",
            f"/items/{index}/id",
        )
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


def _validate_scope_sources(scope: dict[str, Any]) -> None:
    """Check the source sequence and ordering, then every item reference."""
    resolved = scope["resolved"]
    oid_digits = 40 if resolved["object_format"] == "sha1" else 64
    source_ids: set[str] = set()
    previous_source: tuple[str, str, bytes, str] | None = None
    for index, source in enumerate(scope["sources"]):
        _require_canonical_path(source["path"], "source path", f"/sources/{index}/path")
        _require(
            source["id"] == f"S-{index + 1:06d}",
            "E_SOURCE_ID",
            f"source {index} has id {source['id']} outside the fixed sequence",
            f"/sources/{index}/id",
        )
        source_ids.add(source["id"])
        for field in ("revision", "git_oid"):
            oid = source[field]
            if oid is not None:
                _require(
                    len(oid) == oid_digits,
                    "E_SCOPE_OID",
                    f"source {source['id']} has {field} outside "
                    f"{resolved['object_format']}",
                    f"/sources/{index}/{field}",
                )
        key = (source["origin"], source["revision"] or "",
               source["path"].encode("utf-8"), source["git_oid"] or "")
        if previous_source is not None:
            _require(
                previous_source < key,
                "E_SOURCE_ORDER",
                f"source {source['id']} is out of order",
                f"/sources/{index}",
            )
        previous_source = key
    for index, item in enumerate(scope["items"]):
        for side in ("before", "after"):
            reference = item[side]
            if reference is not None:
                _require(
                    reference in source_ids,
                    "E_REFERENCE_UNKNOWN",
                    f"item {item['id']} references unknown source {reference}",
                    f"/items/{index}/{side}",
                )


def _verify_scope_digest(scope_bytes: bytes, record: dict[str, Any]) -> None:
    """Compare the record digest with the scope bytes the caller already parsed."""
    _require(
        record["scope_sha256"] == sha256_digest(scope_bytes),
        "E_SCOPE_DIGEST",
        "record scope_sha256 does not match the scope bytes that were read",
        "/scope_sha256",
    )


def _validate_coverage(scope: dict[str, Any], record: dict[str, Any]) -> tuple[str, dict[str, int]]:
    """Cover each item exactly once and report the declared coverage status."""
    items = scope["items"]
    item_ids = {item["id"] for item in items}
    sources = {source["id"]: source for source in scope["sources"]}
    declared: dict[str, str] = {}
    counts = {"total": len(items), "reviewed": 0, "partial": 0, "not_reviewed": 0}
    for index, entry in enumerate(record["coverage"]):
        item_id = entry["item_id"]
        _require(
            item_id in item_ids and item_id not in declared,
            "E_COVERAGE_UNKNOWN" if item_id not in item_ids else "E_COVERAGE_DUPLICATE",
            f"coverage references {item_id} twice or not at all",
            f"/coverage/{index}/item_id",
        )
        declared[item_id] = entry["status"]
        counts[entry["status"]] += 1
    missing = [item["id"] for item in items if item["id"] not in declared]
    _require(
        not missing,
        "E_COVERAGE_MISSING",
        f"coverage omits items {', '.join(sorted(missing))}",
        "/coverage",
    )
    if not items:
        _require(
            not record["findings"] and not record["concerns"],
            "E_EMPTY_SCOPE_FINDINGS",
            "an empty scope cannot carry findings or concerns",
            "/findings",
        )
        return "nothing_in_scope", counts
    for index, item in enumerate(items):
        if declared[item["id"]] != "reviewed":
            continue
        supported = all(
            item[side] is None or sources[item[side]]["availability"] == TEXT_AVAILABILITY
            for side in ("before", "after")
        )
        _require(
            supported,
            "E_COVERAGE_UNSUPPORTED",
            f"item {item['id']} has a source without captured text bytes "
            "and cannot be declared reviewed",
            f"/coverage/{index}",
        )
    if counts["reviewed"] == counts["total"]:
        return "all_declared_reviewed", counts
    return "partial", counts


def _locate_anchors(
    packet: Path, scope: dict[str, Any], record: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check every finding reference, then verify objects and locate their anchors.

    Anchors keep their declared order, and each captured digest is read once.
    """
    item_ids = {item["id"] for item in scope["items"]}
    sources = {source["id"]: source for source in scope["sources"]}
    anchors: list[dict[str, Any]] = []
    requests: dict[str, list[int]] = {}
    evidences: list[dict[str, Any]] = []
    for index, finding in enumerate(record["findings"]):
        for item_index, item_id in enumerate(finding["item_ids"]):
            _require(
                item_id in item_ids,
                "E_REFERENCE_UNKNOWN",
                f"finding {finding['id']} references unknown item {item_id}",
                f"/findings/{index}/item_ids/{item_index}",
            )
        for evidence_index, evidence in enumerate(finding["evidence"]):
            _require(
                evidence["source_id"] in sources,
                "E_REFERENCE_UNKNOWN",
                f"finding {finding['id']} references unknown source {evidence['source_id']}",
                f"/findings/{index}/evidence/{evidence_index}/source_id",
            )
            requests.setdefault(evidence["source_id"], []).append(len(anchors))
            evidences.append(evidence)
            source = sources[evidence["source_id"]]
            anchors.append({
                "finding_id": finding["id"],
                "evidence_index": evidence_index,
                "source_id": source["id"],
                "path": source["path"],
                "origin": source["origin"],
                "revision": source["revision"],
                **locate_anchor(None, evidence),
            })
    groups: dict[Any, list[tuple[int, dict[str, Any]]]] = {}
    for index, source in enumerate(scope["sources"]):
        if source["availability"] in CAPTURED_AVAILABILITY:
            groups.setdefault(source["sha256"], []).append((index, source))
    for group in groups.values():
        raw = read_source(packet, group[0][1])
        actual_lines: int | None = None
        for index, source in group:
            size = source["size_bytes"]
            _require(
                size == len(raw),
                "E_SOURCE_OBJECT",
                f"source {source['id']} records {size} bytes but its object holds {len(raw)}",
                f"/sources/{index}/size_bytes",
            )
            # A shared digest only means shared bytes: a symlink records no line count.
            if source["availability"] != TEXT_AVAILABILITY:
                continue
            if actual_lines is None:
                actual_lines = count_lines(raw)
            _require(
                source["line_count"] == actual_lines,
                "E_SOURCE_LINES",
                f"source {source['id']} records {source['line_count']} lines "
                f"but holds {actual_lines}",
                f"/sources/{index}/line_count",
            )
        positions = [position for _, source in group for position in requests.get(source["id"], [])]
        text = [position for position in positions
                if sources[anchors[position]["source_id"]]["availability"] == TEXT_AVAILABILITY]
        lines = split_lines(raw) if text else None
        for position in positions:
            anchors[position].update(_locate_in_lines(lines if position in text else None,
                                                      evidences[position]))
    return anchors


def _require_unique_ids(entries: list[dict[str, Any]], section: str) -> None:
    """Findings, concerns, and verification entries each need their own ids."""
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        _require(
            entry["id"] not in seen,
            "E_DUPLICATE_ID",
            f"duplicate {section[:-1]} id {entry['id']}",
            f"/{section}/{index}/id",
        )
        seen.add(entry["id"])


def _validate_concern_references(record: dict[str, Any], item_ids: set[str]) -> None:
    for index, concern in enumerate(record["concerns"]):
        for item_index, item_id in enumerate(concern["item_ids"]):
            _require(
                item_id in item_ids,
                "E_REFERENCE_UNKNOWN",
                f"concern {concern['id']} references unknown item {item_id}",
                f"/concerns/{index}/item_ids/{item_index}",
            )


def validate_record(
    packet: Path,
    scope: dict[str, Any],
    record: dict[str, Any],
    *,
    scope_bytes: bytes,
) -> dict[str, Any]:
    """Validate structure, relations, captured objects, and anchors.

    ``scope_bytes`` must be the exact bytes ``scope`` was parsed from, so the
    record digest is never checked against a file that was read again.
    """
    validate_scope(scope)
    validate_document(record, "record")
    _verify_scope_digest(scope_bytes, record)
    for section in ("findings", "concerns", "verification"):
        _require_unique_ids(record[section], section)
    item_ids = {item["id"] for item in scope["items"]}
    coverage_status, counts = _validate_coverage(scope, record)
    _validate_concern_references(record, item_ids)
    anchors = _locate_anchors(packet, scope, record)
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
        "limitations": dedupe_texts([*scope["limitations"], *record["limitations"]]),
    }


def finish_report(
    validation: dict[str, Any], freshness: dict[str, Any]
) -> dict[str, Any]:
    """Combine validation and freshness into the single check report shape."""
    # The schema bounds every text list with the same count as the item limit.
    limitations = list(validation.get("limitations") or [])
    if len(limitations) > MAX_ITEMS:
        raise ReviewError(
            "E_REPORT_LIMIT",
            f"the merged limitations hold {len(limitations)} entries, over the {MAX_ITEMS} limit",
        )
    valid = validation.get("validation") == "valid"
    report: dict[str, Any] = {
        "schema_version": CHECK_SCHEMA_VERSION,
        "validation": "valid" if valid else "invalid",
        "coverage_status": "unavailable",
        "freshness": {"status": "not_checked", "changed_paths": []},
        "finding_count": None,
        "concern_count": None,
        "item_counts": None,
        "anchors": [],
        "problems": validation.get("problems") or [
            {"code": "E_SCHEMA", "pointer": "", "message": "the record is invalid"}
        ],
        "limitations": limitations,
        "exit_code": 2,
    }
    if not valid:
        return report
    partial = (
        validation["coverage_status"] == "partial"
        or freshness.get("status") in ("changed", "incomplete")
        or any(anchor["status"] != "resolved" for anchor in validation["anchors"])
        or bool(validation["concern_count"])
        or validation.get("failed_verification")
    )
    report.update(
        coverage_status=validation["coverage_status"],
        freshness={
            "status": freshness["status"],
            "changed_paths": list(freshness["changed_paths"]),
        },
        finding_count=validation["finding_count"],
        concern_count=validation["concern_count"],
        item_counts=dict(validation["item_counts"]),
        anchors=list(validation["anchors"]),
        problems=list(validation["problems"]),
        exit_code=4 if partial else 0,
    )
    return report
