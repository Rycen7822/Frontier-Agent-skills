#!/usr/bin/env python3
"""Deterministic Writing Plans model-card contracts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
BUNDLE_ID = "frontier-engineering/5.0.0+4.0.0"
SKILL_ID = "writing-plans"
TARGET_SKILL_VERSION = "4.0.0"
MAX_INPUT_BYTES = 2 * 1024 * 1024
BODY_SECTIONS = (
    "Decision this card owns", "Use when", "Do not use when", "Required inputs",
    "Procedure", "Output contract", "Load next only if", "Stop",
)
KIND_LIMITS = {
    "entry": (4096, 4), "decision": (4096, 3), "procedure": (8192, 3),
    "rubric": (8192, 0), "recipe": (4096, 0), "phase": (8192, 0),
    "safety": (6144, 0), "bridge": (4096, 0),
}
HARD_PREDICATES = {
    "closure-contract-sections-complete",
    "design-depth-needs-evidence",
    "alternatives-compared",
    "cross-context-slice",
    "output-class-selected",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
CARD_ID = re.compile(r"^wp(?:\.[a-z0-9][a-z0-9-]*)+$")


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
    if path.is_symlink() or not path.is_file() or info.st_nlink != 1:
        raise ValueError(f"unsafe JSON input: {path}")
    return strict_json_bytes(path.read_bytes(), source=str(path))


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


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
    metadata = strict_json_bytes(metadata_text.encode(), source=f"{path}:frontmatter")
    if not isinstance(metadata, dict):
        raise ValueError(f"card frontmatter must be an object: {path}")
    return Card(path, path.relative_to(root).as_posix(), metadata, text[boundary + 5 :], raw)


def is_model_card(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(5) == b"---\n{"
    except OSError:
        return False


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render_navigation(metadata: dict[str, Any]) -> str:
    neighbors = metadata.get("neighbors", [])
    if not neighbors:
        return "None. Return control to Router after producing the output contract."
    rows = ["| Edge ID | Missing decision | Required evidence | Next card | Evict when |", "|---|---|---|---|---|"]
    for edge in neighbors:
        rows.append("| `{}` | {} | {} | `{}` | {} |".format(
            _markdown_cell(edge["edge_id"]), _markdown_cell(edge["missing_decision"]),
            _markdown_cell(edge["required_evidence"]), _markdown_cell(edge["to_card_id"]),
            _markdown_cell(edge["evict_when"]),
        ))
    return "\n".join(rows)


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
    return f"---\n{frontmatter}\n---\n{body}".encode()


def _identifiers(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and len(value) == len(set(value)) and all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in value)


def validate_card(card: Card) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    metadata = card.metadata
    required = {"card_id", "card_version", "kind", "consumes", "produces", "max_active_neighbors", "max_bytes", "neighbors"}
    if set(metadata) != required:
        issues.append(ContractIssue("card.frontmatter-keys", card.relative_path, "frontmatter keys differ"))
    card_id = metadata.get("card_id")
    if not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
        issues.append(ContractIssue("card.id", card.relative_path, "card_id is not canonical"))
    if not isinstance(metadata.get("card_version"), int) or isinstance(metadata.get("card_version"), bool) or metadata.get("card_version", 0) < 1:
        issues.append(ContractIssue("card.version", card.relative_path, "card_version must be positive"))
    kind = metadata.get("kind")
    kind_limit, edge_limit = KIND_LIMITS.get(kind, (0, 0))
    if kind not in KIND_LIMITS:
        issues.append(ContractIssue("card.kind", card.relative_path, "unknown kind"))
    for field in ("consumes", "produces"):
        if not _identifiers(metadata.get(field)):
            issues.append(ContractIssue(f"card.{field}", card.relative_path, f"invalid {field}"))
    max_bytes = metadata.get("max_bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 512 <= max_bytes <= kind_limit:
        issues.append(ContractIssue("card.max-bytes", card.relative_path, f"max_bytes must not exceed {kind_limit}"))
    elif len(card.raw) > max_bytes:
        issues.append(ContractIssue("card.bytes", card.relative_path, f"actual bytes {len(card.raw)} exceed {max_bytes}"))
    neighbors = metadata.get("neighbors")
    if not isinstance(neighbors, list):
        issues.append(ContractIssue("card.neighbors", card.relative_path, "neighbors must be an array"))
        neighbors = []
    if len(neighbors) > edge_limit:
        issues.append(ContractIssue("card.outdegree", card.relative_path, f"outdegree exceeds {edge_limit}"))
    if metadata.get("max_active_neighbors") != (1 if neighbors else 0):
        issues.append(ContractIssue("card.active-neighbors", card.relative_path, "active neighbor limit does not match edges"))
    edge_ids: set[str] = set()
    for index, edge in enumerate(neighbors):
        pointer = f"{card.relative_path}#/neighbors/{index}"
        if not isinstance(edge, dict):
            issues.append(ContractIssue("edge.shape", pointer, "edge must be an object"))
            continue
        base = {"edge_id", "to_card_id", "edge_mode", "missing_decision", "required_evidence", "evict_when"}
        expected = base | ({"hard_predicate_id"} if edge.get("edge_mode") == "hard" else set())
        if set(edge) != expected:
            issues.append(ContractIssue("edge.keys", pointer, "edge keys differ"))
        edge_id = edge.get("edge_id")
        if not isinstance(edge_id, str) or not IDENTIFIER.fullmatch(edge_id) or edge_id in edge_ids:
            issues.append(ContractIssue("edge.id", pointer, "edge ID is invalid or duplicate"))
        else:
            edge_ids.add(edge_id)
        if not isinstance(edge.get("to_card_id"), str) or not CARD_ID.fullmatch(edge["to_card_id"]):
            issues.append(ContractIssue("edge.target", pointer, "target must be a local WP card"))
        if edge.get("edge_mode") not in {"hard", "semantic"}:
            issues.append(ContractIssue("edge.mode", pointer, "edge mode is invalid"))
        if edge.get("edge_mode") == "hard" and edge.get("hard_predicate_id") not in HARD_PREDICATES:
            issues.append(ContractIssue("edge.predicate", pointer, "hard predicate is not registered"))
        for field in ("missing_decision", "required_evidence", "evict_when"):
            if not isinstance(edge.get(field), str) or not edge[field].strip():
                issues.append(ContractIssue(f"edge.{field}", pointer, f"{field} must be non-empty"))
    positions = [card.body.find(f"## {section}\n") for section in BODY_SECTIONS]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        issues.append(ContractIssue("card.sections", card.relative_path, "fixed sections are absent or unordered"))
    if not re.search(r"^# [^#\n].+$", card.body, re.MULTILINE):
        issues.append(ContractIssue("card.title", card.relative_path, "H1 title is missing"))
    procedure = re.search(r"## Procedure\n(?P<body>.*?)(?=\n## Output contract\n)", card.body, re.DOTALL)
    steps = re.findall(r"^\d+\. ", procedure.group("body"), re.MULTILINE) if procedure else []
    if not 5 <= len(steps) <= 9:
        issues.append(ContractIssue("card.procedure", card.relative_path, "procedure must contain 5-9 steps"))
    navigation = re.search(r"## Load next only if\n\n?(?P<body>.*?)(?=\n## Stop\n)", card.body, re.DOTALL)
    if navigation is None or navigation.group("body").strip() != render_navigation(metadata):
        issues.append(ContractIssue("card.navigation-render", card.relative_path, "navigation is stale"))
    if re.search(r"\]\([^)]*operator/", card.body):
        issues.append(ContractIssue("card.operator-link", card.relative_path, "operator link is forbidden"))
    return issues


def discover_cards(root: Path) -> list[Card]:
    return [parse_card(path, root) for path in sorted((root / "references").rglob("*.md")) if is_model_card(path)]


def validate_navigation_graph(manifest: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    by_id = {item.get("card_id"): item for item in manifest.get("cards", []) if isinstance(item, dict)}
    graph: dict[str, list[str]] = {}
    for card_id, card in by_id.items():
        graph[card_id] = []
        for edge in card.get("neighbors", []):
            target = edge.get("to_card_id")
            if target not in by_id:
                issues.append(ContractIssue("graph.target-missing", str(card_id), f"missing target: {target}"))
            else:
                graph[card_id].append(target)

    def walk(card_id: str, path: tuple[str, ...]) -> None:
        if card_id in path:
            issues.append(ContractIssue("graph.cycle", card_id, "navigation cycle"))
            return
        if len(path) > 3:
            issues.append(ContractIssue("graph.depth", card_id, "navigation exceeds three hops"))
            return
        for target in graph.get(card_id, []):
            walk(target, path + (card_id,))

    for card_id in sorted(graph):
        walk(card_id, ())
    return issues


def build_manifest(root: Path) -> tuple[dict[str, Any], list[ContractIssue]]:
    issues: list[ContractIssue] = []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in discover_cards(root):
        issues.extend(validate_card(card))
        card_id = card.metadata.get("card_id")
        if card_id in seen:
            issues.append(ContractIssue("card.duplicate-id", card.relative_path, f"duplicate card ID: {card_id}"))
        elif isinstance(card_id, str):
            seen.add(card_id)
        entries.append({
            "bytes": len(card.raw), "card_id": card_id, "card_version": card.metadata.get("card_version"),
            "consumes": card.metadata.get("consumes"), "kind": card.metadata.get("kind"),
            "max_active_neighbors": card.metadata.get("max_active_neighbors"), "max_bytes": card.metadata.get("max_bytes"),
            "neighbors": card.metadata.get("neighbors"), "path": card.relative_path,
            "produces": card.metadata.get("produces"), "sha256": card.sha256,
        })
    entries.sort(key=lambda item: str(item.get("card_id")))
    manifest = {"bundle_id": BUNDLE_ID, "cards": entries, "schema_version": SCHEMA_VERSION, "skill_id": SKILL_ID, "skill_version": TARGET_SKILL_VERSION}
    issues.extend(validate_navigation_graph(manifest))
    return manifest, issues


def issue_payload(issues: Iterable[ContractIssue]) -> list[dict[str, str]]:
    return [issue.as_dict() for issue in issues]
