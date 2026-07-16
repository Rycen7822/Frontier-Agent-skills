#!/usr/bin/env python3
"""Validate the active software-quality-workflows skill with stdlib only."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _workflow_reference_cards import (  # noqa: E402
    build_manifest as build_reference_manifest,
    canonical_json_bytes as canonical_reference_json_bytes,
    load_json as load_reference_json,
)


SKILL_NAME = "software-quality-workflows"
REQUIRED_OWNER_IDS: set[str] = set()
REQUIRED_CORE = {f"references/{owner_id}.md" for owner_id in REQUIRED_OWNER_IDS}
RESOURCE_PREFIXES = ("references/", "templates/", "scripts/", "schemas/", "adapters/", "assets/")
STALE_MARKERS = {
    "multi_agent_v1": "legacy collaboration API",
    "$software-quality-workflows": "Codex-style skill invocation",
    "$writing-plans": "Codex-style skill invocation",
    "$long-document-segmented-writing": "Codex-style skill invocation",
    "Retired skill body": "retired migration body",
    "/" + "home" + "/" + "xu" + "/": "personal absolute path",
    "/" + "home" + "/" + "bb" + "/": "personal absolute path",
    "HY Memory": "product-specific case",
    "Codex-Scientist": "product-specific case",
    "CodexScientist": "product-specific case",
}
UNSAFE_EXECUTABLE_MARKERS = {
    "git add -A": "unscoped staging",
    "git reset --hard": "destructive git reset",
    "git checkout --": "destructive worktree discard",
    "--inspect=0.0.0.0": "public debugger binding",
    "npm i -g": "global package installation",
    "npx -y": "implicit network package execution",
}
UNSUPPORTED_SLOGANS = (
    "100% confidence",
    "Delete it. Start over.",
    "systematic always wins",
    "95% vs 40%",
)
GATE_WORDS = re.compile(
    r"\b(pytest|unittest|ruff|mypy|lint|typecheck|test|tests|build|verify|verification|"
    r"cargo|npm|pnpm|yarn|gradle|mvn|go\s+test)\b",
    re.IGNORECASE,
)
PIPELINE_MASK = re.compile(r"\|\s*(?:head|tail)\b|\|\s*(?:grep|sed|awk)\b", re.IGNORECASE)
LOCAL_MARKDOWN_LINK = re.compile(
    r"\]\(((?:references|templates|scripts|schemas|adapters|assets)/[^)\s#]+)(?:#[^)\s]+)?\)"
)
MARKDOWN_LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)")
LOCAL_BACKTICK_PATH = re.compile(
    r"`((?:references|templates|scripts|schemas|adapters|assets)/[^`\s,;:]+)`"
)


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    line: int
    message: str


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_local_resources(text: str) -> set[str]:
    resources = {match.group(1) for match in LOCAL_MARKDOWN_LINK.finditer(text)}
    resources.update(match.group(1).rstrip(".);,") for match in LOCAL_BACKTICK_PATH.finditer(text))
    return resources


def markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    skill = root / "SKILL.md"
    if skill.is_file():
        files.append(skill)
    for directory in (root / "references", root / "templates", root / "adapters"):
        if directory.is_dir():
            files.extend(path for path in directory.rglob("*.md") if path.is_file())
    return sorted(files)


FRONTMATTER_SLUG = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]*$")
FRONTMATTER_PLAIN_SCALAR = re.compile(r"^[A-Za-z][A-Za-z0-9 .,_/()+&-]*$")
# SemVer 2.0.0 FAQ reference expression, with explicit ASCII digits for Python.
SEMANTIC_VERSION = re.compile(
    r"^(?P<major>0|[1-9][0-9]*)\."
    r"(?P<minor>0|[1-9][0-9]*)\."
    r"(?P<patch>0|[1-9][0-9]*)"
    r"(?:-(?P<prerelease>"
    r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*"
    r"))?"
    r"(?:\+(?P<buildmetadata>"
    r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*"
    r"))?$"
)
YAML_IMPLICIT_NON_STRINGS = {
    "null",
    "true",
    "false",
    "yes",
    "no",
    "on",
    "off",
    "~",
}


def _parse_frontmatter_scalar(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} must be a non-empty string")
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"{field} has invalid double-quoted syntax") from error
        if not isinstance(parsed, str) or not parsed:
            raise ValueError(f"{field} must be a non-empty string")
        return parsed
    if (
        value.lower() in YAML_IMPLICIT_NON_STRINGS
        or not FRONTMATTER_PLAIN_SCALAR.fullmatch(value)
    ):
        raise ValueError(f"{field} must use a canonical string scalar")
    return value


def _parse_inline_slug_list(value: str, field: str) -> list[str]:
    value = value.strip()
    if not value.startswith("[") or not value.endswith("]"):
        raise ValueError(f"{field} must be an inline list")
    body = value[1:-1].strip()
    if not body:
        raise ValueError(f"{field} must not be empty")
    items = [item.strip() for item in body.split(",")]
    if any(
        not item
        or item.lower() in YAML_IMPLICIT_NON_STRINGS
        or not FRONTMATTER_SLUG.fullmatch(item)
        for item in items
    ):
        raise ValueError(f"{field} contains an empty, non-string, or invalid entry")
    if len(items) != len(set(items)):
        raise ValueError(f"{field} contains duplicate entries")
    return items


def _parse_dual_host_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise ValueError("opening delimiter is missing")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("closing delimiter is missing")
    lines = text[4:end].splitlines()
    if len(lines) != 11:
        raise ValueError(f"expected 11 canonical dual-host frontmatter lines; got {len(lines)}")

    scalar_top_keys = ("name", "description", "license")
    raw: dict[str, str] = {}
    for index, key in enumerate(scalar_top_keys):
        prefix = f"{key}: "
        line = lines[index]
        if line.startswith((" ", "\t")) or not line.startswith(prefix):
            raise ValueError(f"expected top-level scalar field {key} at line {index + 1}")
        raw[key] = line[len(prefix):].strip()
    if lines[3] != "metadata:":
        raise ValueError("metadata must be a mapping")

    metadata_keys = ("version", "author")
    raw_metadata: dict[str, str] = {}
    for index, key in enumerate(metadata_keys, start=4):
        prefix = f"  {key}: "
        line = lines[index]
        if not line.startswith(prefix):
            raise ValueError(f"expected metadata.{key}")
        raw_metadata[key] = line[len(prefix):].strip()
    hosts_prefix = "  hosts: "
    if not lines[6].startswith(hosts_prefix):
        raise ValueError("expected metadata.hosts")
    hosts = _parse_inline_slug_list(lines[6][len(hosts_prefix):], "metadata.hosts")
    if hosts != ["codex", "hermes-agent"]:
        raise ValueError("metadata.hosts must be exactly [codex, hermes-agent]")
    if lines[7] != "  hermes:":
        raise ValueError("metadata.hermes must be a mapping")

    nested_keys = ("tags", "category", "related_skills")
    nested: dict[str, str] = {}
    for index, key in enumerate(nested_keys, start=8):
        prefix = f"    {key}: "
        line = lines[index]
        if not line.startswith(prefix):
            raise ValueError(f"expected metadata.hermes.{key}")
        nested[key] = line[len(prefix):].strip()

    name = _parse_frontmatter_scalar(raw["name"], "name")
    description = _parse_frontmatter_scalar(raw["description"], "description")
    version = raw_metadata["version"].strip()
    if version.startswith('"'):
        try:
            version = json.loads(version)
        except json.JSONDecodeError as error:
            raise ValueError("metadata.version has invalid double-quoted syntax") from error
    if not isinstance(version, str) or not version:
        raise ValueError("metadata.version must be a non-empty string")
    if not SEMANTIC_VERSION.fullmatch(version):
        raise ValueError("version must use canonical semantic-version syntax")
    author = _parse_frontmatter_scalar(raw_metadata["author"], "metadata.author")
    license_name = _parse_frontmatter_scalar(raw["license"], "license")
    category = _parse_frontmatter_scalar(nested["category"], "metadata.hermes.category")
    tags = _parse_inline_slug_list(nested["tags"], "metadata.hermes.tags")
    related = _parse_inline_slug_list(
        nested["related_skills"], "metadata.hermes.related_skills"
    )
    return {
        "name": name,
        "description": description,
        "license": license_name,
        "metadata": {
            "version": version,
            "author": author,
            "hosts": hosts,
            "hermes": {
                "tags": tags,
                "category": category,
                "related_skills": related,
            }
        },
    }


# Compatibility alias for callers that consumed the former private parser name.
_parse_hermes_frontmatter = _parse_dual_host_frontmatter


def _check_skill_entry(root: Path, violations: list[Violation]) -> set[str]:
    path = root / "SKILL.md"
    if not path.is_file():
        violations.append(Violation("entry.missing", "SKILL.md", 0, "required entrypoint is missing"))
        return set()
    text = path.read_text(encoding="utf-8")
    try:
        frontmatter = _parse_dual_host_frontmatter(text)
    except ValueError as error:
        violations.append(
            Violation(
                "entry.frontmatter",
                "SKILL.md",
                1,
                f"invalid canonical dual-host frontmatter: {error}",
            )
        )
    else:
        if frontmatter["name"] != SKILL_NAME:
            violations.append(
                Violation("entry.name", "SKILL.md", 2, "skill name does not match directory")
            )
        if not SEMANTIC_VERSION.fullmatch(frontmatter["metadata"]["version"]):
            violations.append(Violation("entry.version", "SKILL.md", 1, "version must be semantic"))
        category = frontmatter["metadata"]["hermes"]["category"]
        if category != "software-development":
            violations.append(
                Violation(
                    "entry.category",
                    "SKILL.md",
                    1,
                    "Hermes category must be software-development",
                )
            )
    if "## Policy ownership" not in text:
        violations.append(Violation("entry.owners", "SKILL.md", 1, "missing policy ownership section"))
    direct = extract_local_resources(text)
    missing_core = sorted(REQUIRED_CORE - direct)
    for resource in missing_core:
        violations.append(
            Violation("entry.core-owner", "SKILL.md", 1, f"missing required core owner: {resource}")
        )
    return direct


def _registered_reference_cards(root: Path, violations: list[Violation]) -> set[str]:
    manifest_path = root / "registries" / "reference-cards.manifest.json"
    if not manifest_path.exists():
        return set()
    relative_manifest = manifest_path.relative_to(root).as_posix()
    try:
        expected, issues = build_reference_manifest(root)
        actual = load_reference_json(manifest_path)
    except (OSError, TypeError, ValueError) as exc:
        violations.append(Violation("reference-cards.invalid", relative_manifest, 1, str(exc)))
        return set()
    if issues:
        first = issues[0]
        violations.append(
            Violation(
                "reference-cards.invalid",
                relative_manifest,
                1,
                f"{len(issues)} card contract issue(s); first: {first.code} in {first.path}: {first.message}",
            )
        )
        return set()
    if canonical_reference_json_bytes(actual) != canonical_reference_json_bytes(expected):
        violations.append(
            Violation(
                "reference-cards.manifest-stale",
                relative_manifest,
                1,
                "manifest does not match the registered card bytes",
            )
        )
        return set()
    return {item["path"] for item in expected["cards"]}


def _check_active_set(
    root: Path,
    direct: set[str],
    registered_reference_cards: set[str],
    violations: list[Violation],
) -> None:
    actual: set[str] = set()
    for directory_name in ("references",):
        directory = root / directory_name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.md"):
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                actual.add(relative)
                if (
                    directory_name == "references"
                    and path.parent != directory
                    and relative not in registered_reference_cards
                ):
                    violations.append(
                        Violation(
                            "active.nested-reference",
                            relative,
                            1,
                            "active references must be flat and directly discoverable",
                        )
                    )
    direct_markdown = {item for item in direct if item.endswith(".md") and item.startswith("references/")}
    for relative in sorted(actual - direct_markdown - registered_reference_cards):
        violations.append(
            Violation("active.orphan", relative, 1, "Markdown resource is not linked directly from SKILL.md")
        )
    for relative in sorted(direct_markdown - actual):
        violations.append(Violation("active.missing", "SKILL.md", 1, f"direct resource does not exist: {relative}"))


def _check_agent_metadata(root: Path, violations: list[Violation]) -> None:
    agents = root / "agents"
    if not agents.exists():
        return
    if not agents.is_dir():
        violations.append(Violation("agent-metadata.type", "agents", 0, "agents must be a directory"))
        return
    entries = sorted(path for path in agents.iterdir())
    for path in entries:
        relative = path.relative_to(root).as_posix()
        if path.name != "openai.yaml" or not path.is_file() or path.is_symlink():
            violations.append(Violation("agent-metadata.unexpected", relative, 0, "only a regular agents/openai.yaml metadata file is allowed"))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            violations.append(Violation("agent-metadata.read", relative, 0, str(exc)))
            continue
        if len(text.encode("utf-8")) > 8192:
            violations.append(Violation("agent-metadata.size", relative, 0, "agent metadata exceeds 8192 bytes"))
        for marker in ("hooks:", "mcp:", "apps:", "remote_writes_default: true", "live_autonomous_closure_default: true"):
            if marker in text:
                violations.append(Violation("agent-metadata.unsafe", relative, 1, f"agent metadata contains forbidden setting: {marker}"))
        for required in ("interface:", "display_name:", "short_description:", "default_prompt:", "allow_implicit_invocation:"):
            if required not in text:
                violations.append(Violation("agent-metadata.required", relative, 1, f"agent metadata lacks {required}"))


def _check_links(root: Path, files: Iterable[Path], violations: list[Violation]) -> None:
    resolved_root = root.resolve()
    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        for match in MARKDOWN_LINK_TARGET.finditer(text):
            raw_target = match.group(1).strip("<>")
            if raw_target.startswith(("#", "//")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw_target):
                continue
            resource = raw_target.split("#", 1)[0].split("?", 1)[0]
            if not resource:
                continue
            candidate = (path.parent / resource).resolve()
            if not candidate.is_relative_to(resolved_root):
                violations.append(
                    Violation(
                        "link.outside",
                        relative,
                        _line_number(text, match.start(1)),
                        f"local link escapes the active skill: {raw_target}",
                    )
                )
            elif not candidate.is_file():
                violations.append(
                    Violation(
                        "link.missing",
                        relative,
                        _line_number(text, match.start(1)),
                        f"local link does not resolve from its document: {raw_target}",
                    )
                )


def _check_markdown(
    root: Path,
    files: Iterable[Path],
    registered_reference_cards: set[str],
    violations: list[Violation],
) -> None:
    for path in files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root).as_posix()
        lines = text.splitlines()
        if relative.startswith("references/") and len(lines) > 100:
            if not any(heading in text for heading in ("## Contents", "## Table of Contents", "## 目录")):
                violations.append(
                    Violation("markdown.toc", relative, 1, f"{len(lines)}-line reference lacks a contents section")
                )
        if text.count("```") % 2:
            violations.append(Violation("markdown.fence", relative, 1, "unbalanced fenced code block"))
        if (
            relative != "SKILL.md"
            and text.startswith("---\n")
            and relative not in registered_reference_cards
        ):
            violations.append(Violation("markdown.reference-frontmatter", relative, 1, "active reference has legacy frontmatter"))
        for marker, explanation in STALE_MARKERS.items():
            offset = text.find(marker)
            if offset >= 0:
                violations.append(
                    Violation("portability.stale", relative, _line_number(text, offset), f"{explanation}: {marker}")
                )
        for marker, explanation in UNSAFE_EXECUTABLE_MARKERS.items():
            offset = text.find(marker)
            if offset >= 0:
                violations.append(
                    Violation("authority.unsafe-example", relative, _line_number(text, offset), f"{explanation}: {marker}")
                )
        for slogan in UNSUPPORTED_SLOGANS:
            offset = text.find(slogan)
            if offset >= 0:
                violations.append(
                    Violation("wording.unsupported", relative, _line_number(text, offset), f"unsupported slogan: {slogan}")
                )
        for line_number, line in enumerate(lines, start=1):
            if GATE_WORDS.search(line) and (PIPELINE_MASK.search(line) or "|| true" in line):
                violations.append(
                    Violation(
                        "gate.masked-exit",
                        relative,
                        line_number,
                        "canonical-looking gate masks or replaces the original exit status",
                    )
                )


def _check_version_recipes(root: Path, violations: list[Violation]) -> None:
    legacy = root / "references" / "version-sensitive-recipes.md"
    if legacy.exists():
        violations.append(Violation("recipe.compatibility", "references/version-sensitive-recipes.md", 1, "legacy recipe aggregator must stay deleted"))


def validate_decision_cases(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, list) or not data:
        return ["decision cases must be a non-empty list"]
    ids: list[str] = []
    modes = {"report", "diagnose", "change"}
    risks = {"READ_ONLY", "LOCAL_REVERSIBLE", "EXTERNAL_STATE", "PRIVILEGED_DANGEROUS"}
    gate_names = {"red", "focused", "affected", "public_surface", "canonical", "static_contract"}
    for index, case in enumerate(data):
        prefix = f"case[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        required = {"id", "prompt", "mode", "max_risk", "required_gates", "forbidden_actions"}
        missing = required - case.keys()
        if missing:
            errors.append(f"{prefix} missing {sorted(missing)}")
            continue
        if not _is_nonempty_string(case["id"]):
            errors.append(f"{prefix}.id must be a non-empty string")
        else:
            ids.append(case["id"])
        if not _is_nonempty_string(case["prompt"]):
            errors.append(f"{prefix}.prompt must be a non-empty string")
        if not isinstance(case["mode"], str) or case["mode"] not in modes:
            errors.append(f"{prefix}.mode must be one of {sorted(modes)}")
        if not isinstance(case["max_risk"], str) or case["max_risk"] not in risks:
            errors.append(f"{prefix}.max_risk must be one of {sorted(risks)}")
        gates = case["required_gates"]
        if (
            not isinstance(gates, list)
            or any(not isinstance(item, str) or item not in gate_names for item in gates)
            or len(gates) != len(set(gates))
        ):
            errors.append(f"{prefix}.required_gates must be a unique list from {sorted(gate_names)}")
        actions = case["forbidden_actions"]
        if (
            not isinstance(actions, list)
            or not actions
            or any(not _is_nonempty_string(item) for item in actions)
            or len(actions) != len(set(actions))
        ):
            errors.append(f"{prefix}.forbidden_actions must be a unique list of non-empty strings")
    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate decision case ids: {duplicates}")
    return errors


def _check_decision_fixture(root: Path, violations: list[Violation]) -> None:
    path = root / "tests" / "fixtures" / "decision-cases.json"
    relative = "tests/fixtures/decision-cases.json"
    if not path.is_file():
        violations.append(Violation("fixture.missing", relative, 0, "decision fixture is missing"))
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        violations.append(Violation("fixture.json", relative, 1, str(error)))
        return
    for error in validate_decision_cases(data):
        violations.append(Violation("fixture.contract", relative, 1, error))


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_scope_manifest(data: Any) -> tuple[list[str], dict[str, Any] | None]:
    """Validate and normalize the frozen manifest used to address review inputs."""

    errors: list[str] = []
    if not isinstance(data, dict):
        return ["scope_manifest must be an object"], None
    required = {"base_revision", "head_revision", "scope_hash", "paths"}
    missing = required - data.keys()
    if missing:
        return [f"scope_manifest missing fields: {sorted(missing)}"], None

    for field in ("base_revision", "head_revision", "scope_hash"):
        if not _is_nonempty_string(data[field]):
            errors.append(f"scope_manifest.{field} must be a non-empty string")

    snapshots: dict[str, str] = {}
    if not isinstance(data["paths"], list):
        errors.append("scope_manifest.paths must be a list")
    else:
        statuses = {"added", "modified", "deleted", "renamed", "untracked", "unchanged"}
        seen_paths: list[str] = []
        for index, item in enumerate(data["paths"]):
            prefix = f"scope_manifest.paths[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            item_missing = {"path", "status", "snapshot_id"} - item.keys()
            if item_missing:
                errors.append(f"{prefix} missing {sorted(item_missing)}")
                continue
            path_value = item["path"]
            snapshot_value = item["snapshot_id"]
            if not _is_nonempty_string(path_value):
                errors.append(f"{prefix}.path must be a non-empty string")
            else:
                seen_paths.append(path_value)
            if not isinstance(item["status"], str) or item["status"] not in statuses:
                errors.append(f"{prefix}.status must be one of {sorted(statuses)}")
            if not _is_nonempty_string(snapshot_value):
                errors.append(f"{prefix}.snapshot_id must be a non-empty string")
            if _is_nonempty_string(path_value) and _is_nonempty_string(snapshot_value):
                snapshots.setdefault(path_value, snapshot_value)
        duplicates = sorted(item for item, count in Counter(seen_paths).items() if count > 1)
        if duplicates:
            errors.append(f"duplicate scope_manifest paths: {duplicates}")

    context = {
        "base_revision": data["base_revision"],
        "head_revision": data["head_revision"],
        "scope_hash": data["scope_hash"],
        "snapshots": snapshots,
    }
    return errors, context


def validate_review_result(
    data: Any,
    *,
    scope_manifest: Any = None,
    current_head: str | None = None,
    current_scope_hash: str | None = None,
) -> list[str]:
    """Validate a review envelope and the manifest/revision context needed to trust it."""

    errors: list[str] = []
    if not isinstance(data, dict):
        return ["result must be an object"]

    def validate_enum(field: str, allowed: set[str]) -> None:
        value = data[field]
        if not isinstance(value, str) or value not in allowed:
            errors.append(f"{field} must be one of {sorted(allowed)}")

    required = {
        "schema_version",
        "code_review_verdict",
        "verification_status",
        "spec_traceability",
        "coverage",
        "blocking_reasons",
        "reviewed_base_sha",
        "reviewed_head_sha",
        "reviewed_scope_hash",
        "findings",
    }
    missing = required - data.keys()
    if missing:
        errors.append(f"missing result fields: {sorted(missing)}")
        if data.get("schema_version") in {"1.0", "2.0"}:
            errors.append("pre-3.0 results require re-review against a frozen manifest")
        return errors

    manifest_context: dict[str, Any] | None = None
    if scope_manifest is None:
        errors.append("scope_manifest context is required")
    else:
        manifest_errors, manifest_context = validate_scope_manifest(scope_manifest)
        errors.extend(manifest_errors)

    if current_head is None:
        errors.append("current_head context is required")
    elif not _is_nonempty_string(current_head):
        errors.append("current_head context must be a non-empty string")
    if current_scope_hash is None:
        errors.append("current_scope_hash context is required")
    elif not _is_nonempty_string(current_scope_hash):
        errors.append("current_scope_hash context must be a non-empty string")

    allowed_scope = set(manifest_context["snapshots"]) if manifest_context is not None else None

    allowed_fields = required | {"summary", "positive_notes"}
    unexpected = sorted(data.keys() - allowed_fields)
    if unexpected:
        errors.append(f"unexpected result fields: {unexpected}")

    if data["schema_version"] != "3.0":
        errors.append("schema_version must be '3.0'; earlier results require re-review")
    enums = {
        "code_review_verdict": {"pass", "changes_requested", "inconclusive"},
        "verification_status": {"passed", "failed", "partial", "not_run"},
    }
    for field, values in enums.items():
        validate_enum(field, values)

    traceability = data["spec_traceability"]
    if not isinstance(traceability, dict):
        errors.append("spec_traceability must be an object")
    else:
        unexpected_traceability = sorted(traceability.keys() - {"status", "evidence_refs"})
        if unexpected_traceability:
            errors.append(f"unexpected spec_traceability fields: {unexpected_traceability}")
        status = traceability.get("status")
        allowed_traceability = {"complete", "partial", "not_assessed", "not_applicable"}
        if not isinstance(status, str) or status not in allowed_traceability:
            errors.append(f"spec_traceability.status must be one of {sorted(allowed_traceability)}")
        evidence_refs = traceability.get("evidence_refs")
        if not isinstance(evidence_refs, list):
            errors.append("spec_traceability.evidence_refs must be a list")
        else:
            for index, ref in enumerate(evidence_refs):
                if not _is_nonempty_string(ref):
                    errors.append(f"spec_traceability.evidence_refs[{index}] must be a non-empty string")
            if status in {"complete", "partial"} and not evidence_refs:
                errors.append(f"spec_traceability.status={status} requires evidence_refs")

    for field in ("reviewed_base_sha", "reviewed_head_sha", "reviewed_scope_hash"):
        if not _is_nonempty_string(data[field]):
            errors.append(f"{field} must be a non-empty string")
    if data["reviewed_head_sha"] == "not_applicable":
        errors.append("reviewed_head_sha must identify the reviewed snapshot")

    if manifest_context is not None:
        if data["reviewed_base_sha"] != manifest_context["base_revision"]:
            errors.append("reviewed_base_sha does not match the frozen scope manifest")
        if data["reviewed_head_sha"] != manifest_context["head_revision"]:
            errors.append("reviewed_head_sha does not match the frozen scope manifest")
        if data["reviewed_scope_hash"] != manifest_context["scope_hash"]:
            errors.append("reviewed_scope_hash does not match the frozen scope manifest")
        if _is_nonempty_string(current_head) and current_head != manifest_context["head_revision"]:
            errors.append("current head differs from the frozen scope manifest")
        if (
            _is_nonempty_string(current_scope_hash)
            and current_scope_hash != manifest_context["scope_hash"]
        ):
            errors.append("current scope hash differs from the frozen scope manifest")

    if not isinstance(data["coverage"], list):
        errors.append("coverage must be a list")
        coverage = []
    else:
        coverage = data["coverage"]
    coverage_statuses: list[str] = []
    coverage_paths: list[str] = []
    for index, item in enumerate(coverage):
        if not isinstance(item, dict):
            errors.append(f"coverage[{index}] must be an object")
            continue
        if not {"path", "status", "snapshot_id"} <= item.keys():
            errors.append(f"coverage[{index}] requires path, status, and snapshot_id")
            continue
        unexpected_coverage = sorted(item.keys() - {"path", "status", "snapshot_id", "sampling_note"})
        if unexpected_coverage:
            errors.append(f"coverage[{index}] has unexpected fields: {unexpected_coverage}")

        path_value = item["path"]
        if not _is_nonempty_string(path_value):
            errors.append(f"coverage[{index}].path must be a non-empty string")
        else:
            coverage_paths.append(path_value)
            if allowed_scope is not None and path_value not in allowed_scope:
                errors.append(f"coverage[{index}].path is outside the scope allowlist")

        snapshot_value = item["snapshot_id"]
        if not _is_nonempty_string(snapshot_value):
            errors.append(f"coverage[{index}].snapshot_id must be a non-empty string")
        elif manifest_context is not None and _is_nonempty_string(path_value):
            expected_snapshot = manifest_context["snapshots"].get(path_value)
            if expected_snapshot is not None and snapshot_value != expected_snapshot:
                errors.append(
                    f"coverage[{index}].snapshot_id does not match the frozen scope manifest"
                )

        status_value = item["status"]
        allowed_coverage = {"full", "sampled", "not_reviewed"}
        if not isinstance(status_value, str) or status_value not in allowed_coverage:
            errors.append(f"coverage[{index}].status must be one of {sorted(allowed_coverage)}")
        else:
            coverage_statuses.append(status_value)
            if status_value == "sampled" and not _is_nonempty_string(item.get("sampling_note")):
                errors.append(f"coverage[{index}].sampling_note is required for sampled coverage")

    duplicate_coverage = sorted(
        item for item, count in Counter(coverage_paths).items() if count > 1
    )
    if duplicate_coverage:
        errors.append(f"duplicate coverage paths: {duplicate_coverage}")
    if allowed_scope is not None:
        missing_coverage = sorted(allowed_scope - set(coverage_paths))
        if missing_coverage:
            errors.append(f"coverage is missing allowlisted paths: {missing_coverage}")

    if not isinstance(data["blocking_reasons"], list):
        errors.append("blocking_reasons must be a list")
        blocking_reasons: list[str] = []
    else:
        blocking_reasons = []
        for index, reason in enumerate(data["blocking_reasons"]):
            if not _is_nonempty_string(reason):
                errors.append(f"blocking_reasons[{index}] must be a non-empty string")
            else:
                blocking_reasons.append(reason)
        duplicate_reasons = sorted(
            item for item, count in Counter(blocking_reasons).items() if count > 1
        )
        if duplicate_reasons:
            errors.append(f"duplicate blocking_reasons: {duplicate_reasons}")

    if not isinstance(data["findings"], list):
        errors.append("findings must be a list")
        findings: list[Any] = []
    else:
        findings = data["findings"]
    finding_required = {
        "id",
        "severity",
        "blocking",
        "category",
        "path",
        "line",
        "evidence",
        "impact",
        "recommended_fix",
        "confidence",
        "verification",
        "code_fixable",
        "source_revision",
    }
    ids: list[str] = []
    blocking_ids: list[str] = []
    for index, finding in enumerate(findings):
        prefix = f"findings[{index}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing_finding = finding_required - finding.keys()
        if missing_finding:
            errors.append(f"{prefix} missing {sorted(missing_finding)}")
            continue

        for field in (
            "id",
            "category",
            "path",
            "evidence",
            "impact",
            "recommended_fix",
            "verification",
            "source_revision",
        ):
            if not _is_nonempty_string(finding[field]):
                errors.append(f"{prefix}.{field} must be a non-empty string")

        if _is_nonempty_string(finding["id"]):
            ids.append(finding["id"])
        if _is_nonempty_string(finding["category"]) and not re.fullmatch(
            r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", finding["category"]
        ):
            errors.append(f"{prefix}.category must be lower_snake_case")

        allowed_severity = {"critical", "high", "medium", "low", "info"}
        if not isinstance(finding["severity"], str) or finding["severity"] not in allowed_severity:
            errors.append(f"{prefix}.severity must be one of {sorted(allowed_severity)}")
        if not isinstance(finding["blocking"], bool):
            errors.append(f"{prefix}.blocking must be boolean")
        elif finding["blocking"] and _is_nonempty_string(finding["id"]):
            blocking_ids.append(finding["id"])
        if not isinstance(finding["code_fixable"], bool):
            errors.append(f"{prefix}.code_fixable must be boolean")

        allowed_confidence = {"high", "medium", "low"}
        if not isinstance(finding["confidence"], str) or finding["confidence"] not in allowed_confidence:
            errors.append(f"{prefix}.confidence must be one of {sorted(allowed_confidence)}")

        line_value = finding["line"]
        if line_value is not None and (type(line_value) is not int or line_value < 1):
            errors.append(f"{prefix}.line must be null or a positive integer")
        if _is_nonempty_string(finding["source_revision"]) and finding["source_revision"] != data["reviewed_head_sha"]:
            errors.append(f"{prefix}.source_revision does not match reviewed_head_sha")
        if (
            allowed_scope is not None
            and _is_nonempty_string(finding["path"])
            and finding["path"] not in allowed_scope
        ):
            errors.append(f"{prefix}.path is outside the scope allowlist")

    duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate finding ids: {duplicates}")

    for finding_id in blocking_ids:
        if finding_id not in blocking_reasons:
            errors.append(f"blocking finding {finding_id!r} is missing from blocking_reasons")

    blocking = bool(blocking_ids)
    if blocking and data["code_review_verdict"] == "pass":
        errors.append("blocking finding conflicts with code_review_verdict=pass")
    if blocking_reasons and data["code_review_verdict"] == "pass":
        errors.append("blocking_reasons conflict with code_review_verdict=pass")
    if "not_reviewed" in coverage_statuses and data["code_review_verdict"] == "pass":
        errors.append("not_reviewed coverage conflicts with code_review_verdict=pass")

    if (
        manifest_context is not None
        and _is_nonempty_string(current_head)
        and current_head != manifest_context["head_revision"]
    ):
        errors.append("review result is stale for the current head revision")
    return errors


def validate_skill(root: Path) -> list[Violation]:
    root = root.resolve()
    violations: list[Violation] = []
    direct = _check_skill_entry(root, violations)
    files = markdown_files(root)
    registered_reference_cards = _registered_reference_cards(root, violations)
    _check_active_set(root, direct, registered_reference_cards, violations)
    _check_agent_metadata(root, violations)
    _check_links(root, files, violations)
    _check_markdown(root, files, registered_reference_cards, violations)
    _check_version_recipes(root, violations)
    _check_decision_fixture(root, violations)
    return sorted(set(violations))


def compact_violations(violations: Sequence[Violation], *, per_code: int = 4) -> str:
    grouped: dict[str, list[Violation]] = defaultdict(list)
    for violation in violations:
        grouped[violation.code].append(violation)
    lines = [f"FAIL: {len(violations)} contract violation(s) across {len(grouped)} check(s)"]
    for code in sorted(grouped):
        items = grouped[code]
        lines.append(f"[{code}] {len(items)}")
        for item in items[:per_code]:
            location = f"{item.path}:{item.line}" if item.line else item.path
            lines.append(f"  {location} - {item.message}")
        if len(items) > per_code:
            lines.append(f"  ... {len(items) - per_code} more")
    return "\n".join(lines)


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--review-result", type=Path)
    parser.add_argument("--scope-manifest", type=Path)
    parser.add_argument("--current-head")
    parser.add_argument("--current-scope-hash")
    args = parser.parse_args(argv)
    if args.review_result:
        try:
            data = _load_json(args.review_result)
        except (OSError, json.JSONDecodeError) as error:
            print(f"FAIL: unable to read review result: {error}")
            return 1
        scope_manifest = None
        if args.scope_manifest is not None:
            try:
                scope_manifest = _load_json(args.scope_manifest)
            except (OSError, json.JSONDecodeError) as error:
                print(f"FAIL: unable to read scope manifest: {error}")
                return 1
        errors = validate_review_result(
            data,
            scope_manifest=scope_manifest,
            current_head=args.current_head,
            current_scope_hash=args.current_scope_hash,
        )
        if errors:
            print(f"FAIL: {len(errors)} review-result contract violation(s)")
            for error in errors[:12]:
                print(f"  {error}")
            if len(errors) > 12:
                print(f"  ... {len(errors) - 12} more")
            return 1
        print("OK: local review result satisfies schema 3.0")
        return 0
    violations = validate_skill(args.root)
    if violations:
        print(compact_violations(violations))
        return 1
    print("OK: software-quality-workflows contracts satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
