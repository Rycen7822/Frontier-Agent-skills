#!/usr/bin/env python3
"""Evaluate the current Frontier static contracts from source."""

from __future__ import annotations

import argparse
from collections import deque
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import bundle_inventory  # noqa: E402
from _model_evolution_residual import validate_repository_contract  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "evaluation" / "schemas" / "static-contract-diagnostic.schema.json"
SOURCE_MANIFEST = ROOT / "bundle-manifest.json"
GENERATED_BUNDLE = ROOT / "frontier-engineering.bundle.json"
LIMITATIONS = (
    "Does not test natural routing, model behavior, task success, real host tokens, "
    "longitudinal test growth, publication authority, or deployment readiness."
)
BLOCKING_FIELDS = (
    "markdown_link_errors",
    "legacy_runtime_paths_present",
    "legacy_protocol_matches",
    "brainstorming_runtime_copies",
)

MODEL_FACING_EXACT = (
    "README.md",
    "RELEASE_NOTES.md",
    "software-quality-workflows/SKILL.md",
    "software-quality-workflows/agents/openai.yaml",
    "writing-plans/SKILL.md",
    "writing-plans/agents/openai.yaml",
    "skill-evaluator/SKILL.md",
    "skill-evaluator/agents/openai.yaml",
    "long-document-segmented-writing/SKILL.md",
    "long-document-segmented-writing/agents/openai.yaml",
    "packaging/codex-plugin/plugin.json.template",
)
MODEL_FACING_DIRS = (
    "software-quality-workflows/references",
    "software-quality-workflows/operator",
)
LEGACY_RUNTIME_PATHS = (
    "brainstorming",
    "software-quality-workflows/scripts/card_cycle.py",
    "software-quality-workflows/scripts/route_workflow.py",
    "software-quality-workflows/scripts/local_workflow_adapter.py",
    "software-quality-workflows/scripts/_workflow_state.py",
    "software-quality-workflows/registries",
    "software-quality-workflows/schemas/workflow-state.schema.json",
    "software-quality-workflows/schemas/card-protocol.schema.json",
    "writing-plans/scripts/card_cycle.py",
    "writing-plans/scripts/assess_plan_mode.py",
    "writing-plans/scripts/_plan_state.py",
    "writing-plans/references",
    "writing-plans/templates",
    "writing-plans/registries",
    "writing-plans/schemas",
    "evaluation/offline-route-replay.json",
    "scripts/evaluate_offline_route_replay.py",
    "scripts/build_shadow_control_evidence.py",
)
LEGACY_PROTOCOL_PATTERNS = (
    "card_cycle.py",
    "--fields-json",
    "previous_receipt",
    "receipt_kind",
    "card_hash",
    "owner_locator",
    "reference-cards.manifest",
    "decision-card-map",
    "policy-owners",
    "route_workflow",
    "assess_plan_mode",
    ".frontier-sqw-",
    ".frontier-wp-",
    "Return control to Router",
    "Load next only if",
    "workflow-intake",
)
BRAINSTORMING_OWNER_PATTERNS = (
    "$brainstorming",
    "brainstorming/SKILL.md",
    "five-skill",
    "Five bounded",
    "brainstorming owns",
)
MARKDOWN_LINK = re.compile(r"\]\(([^)]+)\)")
HEADING_2 = re.compile(r"^##\s+.+$", re.MULTILINE)


def _strict_object(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            result[key] = value
        return result

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular file is missing or symlinked: {path}")
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number in {path}: {value}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _read_model_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"model-facing path must be a regular non-symlink file: {path}")
    return path.read_text(encoding="utf-8")


def _repository_path(root: Path, relative: str) -> Path:
    candidate = Path(os.path.abspath(root / relative))
    if not candidate.is_relative_to(root):
        raise ValueError(f"model-facing root escapes repository: {relative}")
    return candidate


def _has_symlink_component(root: Path, path: Path) -> bool:
    current = root
    for part in path.relative_to(root).parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def model_facing_graph(
    root: Path = ROOT,
    exact_roots: Iterable[str] = MODEL_FACING_EXACT,
    directory_roots: Iterable[str] = MODEL_FACING_DIRS,
) -> tuple[list[Path], list[dict[str, Any]]]:
    root = root.resolve(strict=True)
    paths: set[Path] = set()
    for relative in exact_roots:
        path = _repository_path(root, relative)
        if _has_symlink_component(root, path) or not path.is_file():
            raise ValueError(f"required model-facing file is missing or symlinked: {relative}")
        paths.add(path)
    for relative in directory_roots:
        directory = _repository_path(root, relative)
        if _has_symlink_component(root, directory) or not directory.is_dir():
            raise ValueError(f"required model-facing directory is missing or symlinked: {relative}")
        paths.update(
            path
            for path in directory.rglob("*")
            if path.is_file() and not _has_symlink_component(root, path)
        )

    pending = deque(
        sorted(
            (path for path in paths if path.suffix.lower() == ".md"),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
    visited: set[Path] = set()
    errors: list[dict[str, Any]] = []
    while pending:
        path = pending.popleft()
        if path in visited:
            continue
        visited.add(path)
        text = _read_model_text(path)
        relative = path.relative_to(root).as_posix()
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if target.startswith(("#", "//")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            resource = target.split("#", 1)[0].split("?", 1)[0]
            if not resource:
                continue
            try:
                candidate = Path(os.path.abspath(path.parent / resource))
                valid = (
                    candidate.is_relative_to(root)
                    and not _has_symlink_component(root, candidate)
                    and candidate.is_file()
                )
            except (OSError, ValueError):
                valid = False
            if not valid:
                errors.append({"path": relative, "line": _line_number(text, match.start(1)), "target": target})
                continue
            if candidate not in paths:
                paths.add(candidate)
                if candidate.suffix.lower() == ".md":
                    pending.append(candidate)

    ordered_paths = sorted(paths, key=lambda path: path.relative_to(root).as_posix())
    ordered_errors = sorted(errors, key=lambda item: (item["path"], item["line"], item["target"]))
    return ordered_paths, ordered_errors


def model_facing_paths(root: Path = ROOT) -> list[Path]:
    return model_facing_graph(root)[0]


def _current_release_section(text: str) -> tuple[str, int]:
    headings = list(HEADING_2.finditer(text))
    if not headings:
        return text, 0
    start = headings[0].start()
    end = headings[1].start() if len(headings) > 1 else len(text)
    return text[start:end], start


def _pattern_matches(root: Path, patterns: Iterable[str], paths: Iterable[Path]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        full_text = _read_model_text(path)
        text, base = _current_release_section(full_text) if relative == "RELEASE_NOTES.md" else (full_text, 0)
        for pattern in patterns:
            offset = text.find(pattern)
            if offset >= 0:
                matches.append({"path": relative, "line": _line_number(full_text, base + offset), "pattern": pattern})
    return matches


def markdown_link_errors(root: Path = ROOT) -> list[dict[str, Any]]:
    return model_facing_graph(root)[1]


def collect_legacy_contract(root: Path = ROOT, paths: Iterable[Path] | None = None) -> dict[str, list[Any]]:
    model_paths = list(paths) if paths is not None else model_facing_paths(root)
    return {
        "legacy_runtime_paths_present": [relative for relative in LEGACY_RUNTIME_PATHS if (root / relative).exists() or (root / relative).is_symlink()],
        "legacy_protocol_matches": _pattern_matches(root, LEGACY_PROTOCOL_PATTERNS, model_paths),
        "brainstorming_runtime_copies": _pattern_matches(root, BRAINSTORMING_OWNER_PATTERNS, model_paths),
    }


def _skill_frontmatter(path: Path) -> dict[str, Any]:
    text = _read_model_text(path)
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"missing YAML frontmatter: {path}")
    _, frontmatter, _ = text.split("---\n", 2)
    value = yaml.safe_load(frontmatter)
    if not isinstance(value, dict):
        raise ValueError(f"invalid YAML frontmatter: {path}")
    return value


def _skill_activation(path: Path) -> bool:
    value = yaml.safe_load(_read_model_text(path))
    try:
        activation = value["policy"]["allow_implicit_invocation"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"missing activation policy: {path}") from exc
    if type(activation) is not bool:
        raise ValueError(f"activation policy must be boolean: {path}")
    return activation


def build_report(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve(strict=True)
    validate_repository_contract(root)
    source_manifest = _strict_object(root / SOURCE_MANIFEST.relative_to(ROOT))
    generated_bundle = _strict_object(root / GENERATED_BUNDLE.relative_to(ROOT))
    skills = source_manifest.get("skills")
    profiles = source_manifest.get("test_profiles")
    if not isinstance(skills, list) or not isinstance(profiles, dict):
        raise ValueError("source bundle manifest lacks skills or test_profiles")

    skill_versions: dict[str, str] = {}
    skill_activation: dict[str, bool] = {}
    entry_bytes: dict[str, int] = {}
    for item in skills:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) for key in ("id", "path", "version")):
            raise ValueError("invalid source skill record")
        skill_id = item["id"]
        skill_root = root / item["path"]
        frontmatter = _skill_frontmatter(skill_root / "SKILL.md")
        metadata = frontmatter.get("metadata")
        version = metadata.get("version") if isinstance(metadata, dict) else None
        if version != item["version"]:
            raise ValueError(f"skill version differs from source manifest: {skill_id}")
        skill_versions[skill_id] = version
        skill_activation[skill_id] = _skill_activation(skill_root / "agents" / "openai.yaml")
        entry_bytes[skill_id] = len((skill_root / "SKILL.md").read_bytes())

    for name, commands in sorted(profiles.items()):
        if not isinstance(commands, list) or any(not isinstance(command, str) for command in commands):
            raise ValueError(f"invalid test profile: {name}")

    model_paths, link_errors = model_facing_graph(root)
    package = bundle_inventory(root, source_manifest)
    report: dict[str, Any] = {
        "schema_version": "static-contract-diagnostic/1.0",
        "classification": "static_contract_diagnostic",
        "bundle_id": generated_bundle.get("bundle_id"),
        "version": source_manifest.get("bundle_version"),
        "schema_epoch": generated_bundle.get("compatible_schema_epoch"),
        "skill_versions": skill_versions,
        "skill_activation": skill_activation,
        "entry_bytes": entry_bytes,
        "model_facing_files_checked": [path.relative_to(root).as_posix() for path in model_paths],
        "markdown_link_errors": link_errors,
        **collect_legacy_contract(root, model_paths),
        "package_file_count": len(package),
        "package_bytes": sum(item["size"] for item in package),
        "limitations": LIMITATIONS,
    }
    schema = _strict_object(root / SCHEMA.relative_to(ROOT))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    return report


def _encoded(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def blocking_fact_count(report: dict[str, Any]) -> int:
    return sum(len(report[field]) for field in BLOCKING_FIELDS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = build_report()
        if args.output is not None:
            if args.output.is_symlink():
                raise ValueError("release evidence output must be a regular file")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(_encoded(report))
    except (OSError, TypeError, ValueError, SchemaError, ValidationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    blocking = blocking_fact_count(report)
    print(json.dumps({"ok": blocking == 0, "blocking_facts": blocking}, sort_keys=True))
    return 0 if blocking == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
