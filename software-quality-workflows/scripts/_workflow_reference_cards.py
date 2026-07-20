#!/usr/bin/env python3
"""Deterministic Software Quality Workflows decision-card contracts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable


SCHEMA_VERSION = "2.0"
BUNDLE_ID = "frontier-engineering/8.0.0+7.0.0"
SKILL_ID = "software-quality-workflows"
TARGET_SKILL_VERSION = "8.0.0"
MAX_INPUT_BYTES = 2 * 1024 * 1024
BODY_SECTIONS = (
    "Decision this card owns",
    "Use when",
    "Do not use when",
    "Required inputs",
    "Procedure",
    "Output contract",
    "Load next only if",
    "Stop",
)
CARD_KINDS = {"decision", "procedure", "rubric", "recipe", "safety", "bridge"}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
CARD_ID = re.compile(r"^sqw(?:\.[a-z0-9][a-z0-9-]*)+$")
MAPPING_KEYS = {
    "decision_id", "card_id", "priority", "required_artifact_ids", "produced_artifact_ids",
    "positive_fixture_id", "near_miss_fixture_id",
}


@dataclass(frozen=True)
class ContractIssue:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class Card:
    path: Path
    relative_path: str
    metadata: dict[str, Any]
    body: str
    raw: bytes

    @property
    def sha256(self) -> str:
        return "sha256:" + sha256(self.raw).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_bytes(data: bytes, *, source: str) -> Any:
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes: {source}")
    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite number: {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid UTF-8 JSON in {source}: {exc}") from exc


def load_json(path: Path) -> Any:
    info = path.lstat()
    if not path.is_file() or path.is_symlink() or info.st_nlink != 1:
        raise ValueError(f"unsafe JSON input: {path}")
    return strict_json_bytes(path.read_bytes(), source=str(path))


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _cross_skill_projection(root: Path) -> dict[str, Any]:
    source_path = root.parent / "bundle-manifest.json"
    if source_path.is_file() and not source_path.is_symlink():
        section = load_json(source_path).get("cross_skill_routes")
    else:
        existing = load_json(root / "registries" / "reference-cards.manifest.json").get("cross_skill_routes")
        if not isinstance(existing, dict) or set(existing) != {"source_hash", "outbound", "inbound"}:
            raise ValueError("cross-skill route source and local projection are both unavailable")
        section = {
            "schema_version": "frontier-cross-skill-routes/1",
            "routes": sorted(existing["outbound"] + existing["inbound"], key=lambda row: row.get("route_id", "")),
        }
    if not isinstance(section, dict) or set(section) != {"schema_version", "routes"}:
        raise ValueError("cross_skill_routes shape is invalid")
    routes = section.get("routes")
    route_keys = {
        "route_id", "source_skill_id", "target_skill_id", "contract_id",
        "copied_fields", "intent_status_map", "constants",
    }
    pairs = {
        ("sqw-to-writing-plans", "software-quality-workflows", "writing-plans", "workflow-plan-change-proposal"),
        ("writing-plans-to-sqw", "writing-plans", "software-quality-workflows", "plan-to-workflow"),
    }
    if (
        section.get("schema_version") != "frontier-cross-skill-routes/1"
        or not isinstance(routes, list)
        or len(routes) != 2
        or any(not isinstance(route, dict) or set(route) != route_keys for route in routes)
    ):
        raise ValueError("cross_skill_routes rows are invalid")
    observed_pairs = {
        (route["route_id"], route["source_skill_id"], route["target_skill_id"], route["contract_id"])
        for route in routes
    }
    if observed_pairs != pairs or any(route["copied_fields"] != ["intent_status", "root_cause_status"] for route in routes):
        raise ValueError("cross_skill_routes bindings are invalid")
    normalized = {"schema_version": section["schema_version"], "routes": sorted(routes, key=lambda row: row["route_id"])}
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "source_hash": "sha256:" + sha256(encoded).hexdigest(),
        "outbound": [route for route in normalized["routes"] if route["source_skill_id"] == SKILL_ID],
        "inbound": [route for route in normalized["routes"] if route["target_skill_id"] == SKILL_ID],
    }


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise ValueError(f"refusing to replace symlink: {path}")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_card(path: Path, root: Path) -> Card:
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_nlink != 1:
        raise ValueError(f"unsafe card input: {path}")
    raw = path.read_bytes()
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"card exceeds parser limit: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"card is not UTF-8: {path}") from exc
    if not text.startswith("---\n"):
        raise ValueError(f"card frontmatter is missing: {path}")
    boundary = text.find("\n---\n", 4)
    if boundary < 0:
        raise ValueError(f"card frontmatter is unterminated: {path}")
    metadata_text = text[4:boundary].strip()
    if not metadata_text.startswith("{"):
        raise ValueError(f"card frontmatter must use canonical JSON/YAML syntax: {path}")
    metadata = strict_json_bytes(metadata_text.encode("utf-8"), source=f"{path}:frontmatter")
    if not isinstance(metadata, dict):
        raise ValueError(f"card frontmatter must be an object: {path}")
    body = text[boundary + 5 :]
    return Card(path, path.relative_to(root).as_posix(), metadata, body, raw)


def is_model_card(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(5) == b"---\n{"
    except OSError:
        return False


def _identifiers(value: Any, *, allow_empty: bool) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and len(value) == len(set(value))
        and all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in value)
    )


def render_navigation(metadata: dict[str, Any]) -> str:
    return "None. Return control to Router after producing the output contract."


def replace_navigation(card: Card) -> bytes:
    start_marker = "## Load next only if\n"
    stop_marker = "\n## Stop\n"
    start = card.body.find(start_marker)
    stop = card.body.find(stop_marker)
    if start < 0 or stop < 0 or stop <= start:
        raise ValueError(f"card lacks renderable navigation section: {card.path}")
    start += len(start_marker)
    body = card.body[:start] + "\n" + render_navigation(card.metadata) + "\n" + card.body[stop:]
    frontmatter = json.dumps(card.metadata, ensure_ascii=False, indent=2, sort_keys=False)
    return f"---\n{frontmatter}\n---\n{body}".encode("utf-8")


def validate_card(card: Card) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    metadata = card.metadata
    required = {
        "card_id", "card_version", "kind", "decision_id",
        "required_artifact_ids", "produced_artifact_ids", "max_bytes",
    }
    if set(metadata) != required:
        issues.append(ContractIssue("card.frontmatter-keys", card.relative_path, "frontmatter keys differ"))
    card_id = metadata.get("card_id")
    if not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
        issues.append(ContractIssue("card.id", card.relative_path, "card_id is not canonical"))
    if not isinstance(metadata.get("card_version"), int) or isinstance(metadata.get("card_version"), bool) or metadata.get("card_version", 0) < 1:
        issues.append(ContractIssue("card.version", card.relative_path, "card_version must be positive"))
    kind = metadata.get("kind")
    if kind not in CARD_KINDS:
        issues.append(ContractIssue("card.kind", card.relative_path, "unknown kind"))
    decision_id = metadata.get("decision_id")
    if not isinstance(decision_id, str) or not re.fullmatch(r"sqw\.select\.[a-z0-9.-]+", decision_id):
        issues.append(ContractIssue("card.decision", card.relative_path, "decision_id is not canonical"))
    if not _identifiers(metadata.get("required_artifact_ids"), allow_empty=True):
        issues.append(ContractIssue("card.required-artifacts", card.relative_path, "required artifacts are invalid"))
    if not _identifiers(metadata.get("produced_artifact_ids"), allow_empty=False):
        issues.append(ContractIssue("card.produced-artifacts", card.relative_path, "produced artifacts are invalid"))
    max_bytes = metadata.get("max_bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 512 <= max_bytes <= 8192:
        issues.append(ContractIssue("card.max-bytes", card.relative_path, "max_bytes must be between 512 and 8192"))
    elif len(card.raw) > max_bytes:
        issues.append(ContractIssue("card.bytes", card.relative_path, f"actual bytes {len(card.raw)} exceed {max_bytes}"))
    heading_positions = [card.body.find(f"## {section}\n") for section in BODY_SECTIONS]
    if any(position < 0 for position in heading_positions) or heading_positions != sorted(heading_positions):
        issues.append(ContractIssue("card.sections", card.relative_path, "fixed body sections are missing or out of order"))
    if not re.search(r"^# [^#\n].+$", card.body, re.MULTILINE):
        issues.append(ContractIssue("card.title", card.relative_path, "card must have one H1 title"))
    procedure = re.search(r"## Procedure\n(?P<body>.*?)(?=\n## Output contract\n)", card.body, re.DOTALL)
    steps = re.findall(r"^\d+\. ", procedure.group("body"), re.MULTILINE) if procedure else []
    if not 3 <= len(steps) <= 20:
        issues.append(ContractIssue("card.procedure", card.relative_path, "procedure must contain 3-20 numbered steps"))
    navigation = re.search(r"## Load next only if\n\n?(?P<body>.*?)(?=\n## Stop\n)", card.body, re.DOTALL)
    if navigation is None or navigation.group("body").strip() != render_navigation(metadata):
        issues.append(ContractIssue("card.navigation-render", card.relative_path, "navigation is stale"))
    if re.search(r"\]\([^)]*operator/", card.body):
        issues.append(ContractIssue("card.operator-link", card.relative_path, "model card links to operator material"))
    return issues


def discover_cards(root: Path) -> list[Card]:
    references = root / "references"
    cards = [parse_card(path, root) for path in sorted(references.rglob("*.md")) if is_model_card(path)]
    return cards


def skill_version(root: Path) -> str:
    text = (root / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^metadata:\n(?:  .*\n)*?  version: ([0-9]+\.[0-9]+\.[0-9]+)$", text, re.MULTILINE)
    if not match:
        raise ValueError("SKILL.md lacks canonical metadata.version")
    return match.group(1)


def validate_decision_contract(root: Path, entries: list[dict[str, Any]]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    map_path = root / "registries" / "decision-card-map.json"
    fixture_path = root / "tests" / "fixtures" / "decision-route-cases-v8.json"
    try:
        decision_map = load_json(map_path)
        fixtures = load_json(fixture_path)
    except (OSError, ValueError) as exc:
        return [ContractIssue("decision-map.invalid", "registries/decision-card-map.json", str(exc))]
    if not isinstance(decision_map, dict) or set(decision_map) != {"schema_version", "skill_id", "skill_version", "decisions"}:
        return [ContractIssue("decision-map.shape", "registries/decision-card-map.json", "map keys differ")]
    if (decision_map.get("schema_version"), decision_map.get("skill_id"), decision_map.get("skill_version")) != (
        "decision-card-map/1.0", SKILL_ID, TARGET_SKILL_VERSION,
    ):
        issues.append(ContractIssue("decision-map.identity", "registries/decision-card-map.json", "map identity differs"))
    rows = decision_map.get("decisions")
    if not isinstance(rows, list):
        return issues + [ContractIssue("decision-map.shape", "registries/decision-card-map.json", "decisions must be an array")]
    valid_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != MAPPING_KEYS:
            issues.append(ContractIssue("decision-map.row", f"registries/decision-card-map.json#/decisions/{index}", "mapping keys differ"))
        else:
            valid_rows.append(row)
    for field in ("decision_id", "card_id", "priority", "positive_fixture_id", "near_miss_fixture_id"):
        values = [row[field] for row in valid_rows]
        if len(values) != len(set(values)):
            issues.append(ContractIssue("decision-map.duplicate", "registries/decision-card-map.json", f"{field} must be unique"))
    by_card = {row["card_id"]: row for row in valid_rows}
    if {entry["card_id"] for entry in entries} != set(by_card):
        issues.append(ContractIssue("decision-map.coverage", "registries/decision-card-map.json", "map must own every card exactly once"))
    for entry in entries:
        row = by_card.get(entry["card_id"], {})
        for field in ("decision_id", "required_artifact_ids", "produced_artifact_ids"):
            if entry[field] != row.get(field):
                issues.append(ContractIssue("decision-map.binding", entry["path"], f"{field} differs from decision map"))
    if not isinstance(fixtures, dict):
        return issues + [ContractIssue("decision-fixture.invalid", "tests/fixtures/decision-route-cases-v8.json", "fixture must be an object")]
    positive = {case.get("id"): case for case in fixtures.get("positive_cases", []) if isinstance(case, dict)}
    near_miss = {case.get("id"): case for case in fixtures.get("near_miss_cases", []) if isinstance(case, dict)}
    if {row["positive_fixture_id"] for row in valid_rows} != set(positive):
        issues.append(ContractIssue("decision-fixture.coverage", "tests/fixtures/decision-route-cases-v8.json", "positive fixture ownership differs"))
    if {row["near_miss_fixture_id"] for row in valid_rows} != set(near_miss):
        issues.append(ContractIssue("decision-fixture.coverage", "tests/fixtures/decision-route-cases-v8.json", "near-miss fixture ownership differs"))
    for row in valid_rows:
        positive_case = positive.get(row["positive_fixture_id"], {})
        near_case = near_miss.get(row["near_miss_fixture_id"], {})
        if (positive_case.get("decision_id"), positive_case.get("expected_card_id")) != (row["decision_id"], row["card_id"]):
            issues.append(ContractIssue("decision-fixture.binding", row["positive_fixture_id"], "positive fixture differs from mapping"))
        if near_case.get("excluded_card_id") != row["card_id"]:
            issues.append(ContractIssue("decision-fixture.binding", row["near_miss_fixture_id"], "near-miss fixture does not exclude mapped card"))
    return issues


def build_manifest(root: Path) -> tuple[dict[str, Any], list[ContractIssue]]:
    cards = discover_cards(root)
    issues: list[ContractIssue] = []
    card_ids: set[str] = set()
    entries: list[dict[str, Any]] = []
    for card in cards:
        issues.extend(validate_card(card))
        card_id = card.metadata.get("card_id")
        if card_id in card_ids:
            issues.append(ContractIssue("card.duplicate-id", card.relative_path, f"duplicate card ID: {card_id}"))
        elif isinstance(card_id, str):
            card_ids.add(card_id)
        entries.append({
            "bytes": len(card.raw),
            "card_id": card_id,
            "card_version": card.metadata.get("card_version"),
            "decision_id": card.metadata.get("decision_id"),
            "kind": card.metadata.get("kind"),
            "max_bytes": card.metadata.get("max_bytes"),
            "path": card.relative_path,
            "required_artifact_ids": card.metadata.get("required_artifact_ids"),
            "produced_artifact_ids": card.metadata.get("produced_artifact_ids"),
            "sha256": card.sha256,
        })
    entries.sort(key=lambda item: str(item.get("card_id")))
    manifest = {
        "bundle_id": BUNDLE_ID,
        "cards": entries,
        "cross_skill_routes": _cross_skill_projection(root),
        "schema_version": SCHEMA_VERSION,
        "skill_id": SKILL_ID,
        "skill_version": TARGET_SKILL_VERSION,
    }
    issues.extend(validate_decision_contract(root, entries))
    return manifest, issues


def issue_payload(issues: Iterable[ContractIssue]) -> list[dict[str, str]]:
    return [issue.as_dict() for issue in issues]
