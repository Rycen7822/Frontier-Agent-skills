#!/usr/bin/env python3
"""Build or verify the deterministic Frontier 6.1 static contract report."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
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

from _bundle_hash import bundle_inventory


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation" / "static-contract-diagnostic.json"
SCHEMA = ROOT / "evaluation" / "schemas" / "static-contract-diagnostic.schema.json"
SOURCE_MANIFEST = ROOT / "bundle-manifest.json"
GENERATED_BUNDLE = ROOT / "frontier-engineering.bundle.json"
LIMITATIONS = (
    "Does not test natural routing, model behavior, task success, real host tokens, "
    "longitudinal test growth, publication authority, or deployment readiness."
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


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "sha256:" + sha256(payload).hexdigest()


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _read_model_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"model-facing path must be a regular non-symlink file: {path}")
    return path.read_text(encoding="utf-8")


def model_facing_paths(root: Path = ROOT) -> list[Path]:
    paths: set[Path] = set()
    for relative in MODEL_FACING_EXACT:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"required model-facing file is missing or symlinked: {relative}")
        paths.add(path)
    for relative in MODEL_FACING_DIRS:
        directory = root / relative
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError(f"required model-facing directory is missing or symlinked: {relative}")
        paths.update(path for path in directory.rglob("*") if path.is_file() or path.is_symlink())
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def _current_release_section(text: str) -> tuple[str, int]:
    headings = list(HEADING_2.finditer(text))
    if not headings:
        return text, 0
    start = headings[0].start()
    end = headings[1].start() if len(headings) > 1 else len(text)
    return text[start:end], start


def _pattern_matches(root: Path, patterns: Iterable[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for path in model_facing_paths(root):
        relative = path.relative_to(root).as_posix()
        full_text = _read_model_text(path)
        text, base = _current_release_section(full_text) if relative == "RELEASE_NOTES.md" else (full_text, 0)
        for pattern in patterns:
            offset = text.find(pattern)
            if offset >= 0:
                matches.append({"path": relative, "line": _line_number(full_text, base + offset), "pattern": pattern})
    return matches


def markdown_link_errors(root: Path = ROOT) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    resolved_root = root.resolve(strict=True)
    for path in model_facing_paths(root):
        if path.suffix.lower() != ".md":
            continue
        text = _read_model_text(path)
        relative = path.relative_to(root).as_posix()
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip().strip("<>")
            if target.startswith(("#", "//")) or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            resource = target.split("#", 1)[0].split("?", 1)[0]
            if not resource:
                continue
            candidate = path.parent / resource
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                resolved = None
            if resolved is None or not resolved.is_relative_to(resolved_root) or candidate.is_symlink() or not resolved.is_file():
                errors.append({"path": relative, "line": _line_number(text, match.start(1)), "target": target})
    return errors


def collect_legacy_contract(root: Path = ROOT) -> dict[str, list[Any]]:
    return {
        "legacy_runtime_paths_present": [relative for relative in LEGACY_RUNTIME_PATHS if (root / relative).exists() or (root / relative).is_symlink()],
        "legacy_protocol_matches": _pattern_matches(root, LEGACY_PROTOCOL_PATTERNS),
        "brainstorming_runtime_copies": _pattern_matches(root, BRAINSTORMING_OWNER_PATTERNS),
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

    profile_hashes: dict[str, str] = {}
    for name, commands in sorted(profiles.items()):
        if not isinstance(commands, list) or any(not isinstance(command, str) for command in commands):
            raise ValueError(f"invalid test profile: {name}")
        profile_hashes[name] = _canonical_hash(commands)

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
        "model_facing_files_checked": [path.relative_to(root).as_posix() for path in model_facing_paths(root)],
        "markdown_link_errors": markdown_link_errors(root),
        **collect_legacy_contract(root),
        "profile_command_hashes": profile_hashes,
        "package_file_count": len(package),
        "package_bytes": sum(item["size"] for item in package),
        "limitations": LIMITATIONS,
    }
    report["report_hash"] = _canonical_hash(report)
    schema = _strict_object(root / SCHEMA.relative_to(ROOT))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    return report


def _encoded(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report()
        expected = _encoded(report)
        if args.check:
            if OUTPUT.is_symlink() or not OUTPUT.is_file() or OUTPUT.read_bytes() != expected:
                raise ValueError("checked-in static contract diagnostic is missing or stale")
        else:
            if OUTPUT.is_symlink():
                raise ValueError("refusing to replace symlinked static contract diagnostic")
            OUTPUT.write_bytes(expected)
    except (OSError, TypeError, ValueError, SchemaError, ValidationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    blocking = sum(len(report[field]) for field in ("markdown_link_errors", "legacy_runtime_paths_present", "legacy_protocol_matches", "brainstorming_runtime_copies"))
    print(json.dumps({"ok": blocking == 0, "report_hash": report["report_hash"], "blocking_facts": blocking}, sort_keys=True))
    return 0 if blocking == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
