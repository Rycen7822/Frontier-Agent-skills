#!/usr/bin/env python3
"""Deterministic model-card parsing, rendering, and graph validation."""

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
SKILL_ID = "software-quality-workflows"
TARGET_SKILL_VERSION = "5.0.0"
CARD_PREFIX = "sqw."
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
KIND_LIMITS = {
    "entry": (4096, 4),
    "decision": (4096, 3),
    "procedure": (8192, 3),
    "rubric": (8192, 0),
    "recipe": (4096, 0),
    "phase": (8192, 0),
    "safety": (6144, 0),
    "bridge": (4096, 0),
}
HARD_PREDICATES = {
    "public-contract-implicated",
    "fresh-reproduction-missing",
    "material-intent-assessment-missing",
    "independent-read-slices-admitted",
    "merge-conflict-active",
    "repository-state-unsafe",
    "cleanup-authorized",
    "bounded-review-input-ready",
    "stable-requirements-available",
    "read-only-slice-admitted",
    "isolated-write-slice-admitted",
    "live-readiness-required",
    "untrusted-content-implicated",
    "performance-baseline-stable",
    "plugin-registration-implicated",
    "installed-surface-required",
    "runtime-version-boundary-selected",
    "stability-round-required",
    "stability-exit-triggered",
    "merge-sides-identified",
    "test-lifecycle-action-classified",
    "required-gate-failed",
    "required-gates-fresh-pass",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
CARD_ID = re.compile(r"^sqw(?:\.[a-z0-9][a-z0-9-]*)+$")


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


def _nonempty_identifiers(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in value)
        and len(value) == len(set(value))
    )


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render_navigation(metadata: dict[str, Any]) -> str:
    neighbors = metadata.get("neighbors", [])
    if not neighbors:
        return "None. Return control to Router after producing the output contract."
    rows = [
        "| Edge ID | Missing decision | Required evidence | Next card | Evict when |",
        "|---|---|---|---|---|",
    ]
    for edge in neighbors:
        rows.append(
            "| `{}` | {} | {} | `{}` | {} |".format(
                _markdown_cell(edge["edge_id"]),
                _markdown_cell(edge["missing_decision"]),
                _markdown_cell(edge["required_evidence"]),
                _markdown_cell(edge["to_card_id"]),
                _markdown_cell(edge["evict_when"]),
            )
        )
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
    return f"---\n{frontmatter}\n---\n{body}".encode("utf-8")


def validate_card(card: Card) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    metadata = card.metadata
    required = {
        "card_id", "card_version", "kind", "consumes", "produces",
        "max_active_neighbors", "max_bytes", "neighbors",
    }
    if set(metadata) != required:
        issues.append(ContractIssue("card.frontmatter-keys", card.relative_path, f"expected exact keys {sorted(required)}"))
    card_id = metadata.get("card_id")
    if not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
        issues.append(ContractIssue("card.id", card.relative_path, "card_id is not a canonical SQW ID"))
    if not isinstance(metadata.get("card_version"), int) or isinstance(metadata.get("card_version"), bool) or metadata.get("card_version", 0) < 1:
        issues.append(ContractIssue("card.version", card.relative_path, "card_version must be a positive integer"))
    kind = metadata.get("kind")
    if kind not in KIND_LIMITS:
        issues.append(ContractIssue("card.kind", card.relative_path, "unknown card kind"))
        kind_limit, edge_limit = (0, 0)
    else:
        kind_limit, edge_limit = KIND_LIMITS[kind]
    for field in ("consumes", "produces"):
        if not _nonempty_identifiers(metadata.get(field)):
            issues.append(ContractIssue(f"card.{field}", card.relative_path, f"{field} must be unique canonical identifiers"))
    max_bytes = metadata.get("max_bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 512 or max_bytes > kind_limit:
        issues.append(ContractIssue("card.max-bytes", card.relative_path, f"max_bytes must be 512..{kind_limit}"))
    elif len(card.raw) > max_bytes:
        issues.append(ContractIssue("card.bytes", card.relative_path, f"actual bytes {len(card.raw)} exceed max_bytes {max_bytes}"))
    neighbors = metadata.get("neighbors")
    if not isinstance(neighbors, list):
        issues.append(ContractIssue("card.neighbors", card.relative_path, "neighbors must be an array"))
        neighbors = []
    if len(neighbors) > edge_limit:
        issues.append(ContractIssue("card.outdegree", card.relative_path, f"{kind} cards allow at most {edge_limit} edges"))
    active_limit = metadata.get("max_active_neighbors")
    expected_active_limit = 1 if neighbors else 0
    if active_limit != expected_active_limit:
        issues.append(ContractIssue("card.active-neighbors", card.relative_path, f"max_active_neighbors must be {expected_active_limit}"))
    edge_ids: set[str] = set()
    for index, edge in enumerate(neighbors):
        pointer = f"{card.relative_path}#/neighbors/{index}"
        if not isinstance(edge, dict):
            issues.append(ContractIssue("edge.shape", pointer, "edge must be an object"))
            continue
        base_keys = {"edge_id", "to_card_id", "edge_mode", "missing_decision", "required_evidence", "evict_when"}
        expected_keys = base_keys | ({"hard_predicate_id"} if edge.get("edge_mode") == "hard" else set())
        if set(edge) != expected_keys:
            issues.append(ContractIssue("edge.keys", pointer, f"edge keys must be {sorted(expected_keys)}"))
        edge_id = edge.get("edge_id")
        if not isinstance(edge_id, str) or not IDENTIFIER.fullmatch(edge_id) or edge_id in edge_ids:
            issues.append(ContractIssue("edge.id", pointer, "edge_id must be unique and canonical"))
        else:
            edge_ids.add(edge_id)
        target = edge.get("to_card_id")
        if not isinstance(target, str) or not CARD_ID.fullmatch(target):
            issues.append(ContractIssue("edge.target", pointer, "target must be a local SQW card ID"))
        mode = edge.get("edge_mode")
        if mode not in {"hard", "semantic"}:
            issues.append(ContractIssue("edge.mode", pointer, "edge_mode must be hard or semantic"))
        if mode == "hard" and edge.get("hard_predicate_id") not in HARD_PREDICATES:
            issues.append(ContractIssue("edge.predicate", pointer, "hard predicate is not registered"))
        for field in ("missing_decision", "required_evidence", "evict_when"):
            if not isinstance(edge.get(field), str) or not edge[field].strip():
                issues.append(ContractIssue(f"edge.{field}", pointer, f"{field} must be non-empty"))
    heading_positions = [card.body.find(f"## {section}\n") for section in BODY_SECTIONS]
    if any(position < 0 for position in heading_positions) or heading_positions != sorted(heading_positions):
        issues.append(ContractIssue("card.sections", card.relative_path, "fixed body sections are missing or out of order"))
    if not re.search(r"^# [^#\n].+$", card.body, re.MULTILINE):
        issues.append(ContractIssue("card.title", card.relative_path, "card must have one H1 title"))
    procedure = re.search(r"## Procedure\n(?P<body>.*?)(?=\n## Output contract\n)", card.body, re.DOTALL)
    steps = re.findall(r"^\d+\. ", procedure.group("body"), re.MULTILINE) if procedure else []
    if not 5 <= len(steps) <= 9:
        issues.append(ContractIssue("card.procedure", card.relative_path, "procedure must contain 5-9 numbered steps"))
    navigation = re.search(r"## Load next only if\n\n?(?P<body>.*?)(?=\n## Stop\n)", card.body, re.DOTALL)
    if navigation is None or navigation.group("body").strip() != render_navigation(metadata):
        issues.append(ContractIssue("card.navigation-render", card.relative_path, "navigation body is not generated from frontmatter"))
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
            "consumes": card.metadata.get("consumes"),
            "kind": card.metadata.get("kind"),
            "max_active_neighbors": card.metadata.get("max_active_neighbors"),
            "max_bytes": card.metadata.get("max_bytes"),
            "neighbors": card.metadata.get("neighbors"),
            "path": card.relative_path,
            "produces": card.metadata.get("produces"),
            "sha256": card.sha256,
        })
    entries.sort(key=lambda item: str(item.get("card_id")))
    manifest = {
        "bundle_id": BUNDLE_ID,
        "cards": entries,
        "schema_version": SCHEMA_VERSION,
        "skill_id": SKILL_ID,
        "skill_version": TARGET_SKILL_VERSION,
    }
    issues.extend(validate_navigation_graph(manifest))
    return manifest, issues


def validate_navigation_graph(manifest: dict[str, Any]) -> list[ContractIssue]:
    issues: list[ContractIssue] = []
    cards = manifest.get("cards", [])
    by_id = {item.get("card_id"): item for item in cards if isinstance(item, dict)}
    graph: dict[str, list[str]] = {}
    for card_id, card in by_id.items():
        graph[card_id] = []
        for edge in card.get("neighbors", []) if isinstance(card.get("neighbors"), list) else []:
            target = edge.get("to_card_id") if isinstance(edge, dict) else None
            if target not in by_id:
                issues.append(ContractIssue("graph.target-missing", str(card_id), f"missing target: {target}"))
            else:
                graph[card_id].append(target)
    def walk(card_id: str, path: tuple[str, ...]) -> None:
        if card_id in path:
            issues.append(ContractIssue("graph.cycle", card_id, "navigation graph contains a cycle"))
            return
        if len(path) > 3:
            issues.append(ContractIssue("graph.depth", card_id, "navigation path exceeds three hops"))
            return
        for target in graph.get(card_id, []):
            walk(target, path + (card_id,))

    for card_id in sorted(graph):
        walk(card_id, ())
    return issues


def issue_payload(issues: Iterable[ContractIssue]) -> list[dict[str, str]]:
    return [issue.as_dict() for issue in issues]
