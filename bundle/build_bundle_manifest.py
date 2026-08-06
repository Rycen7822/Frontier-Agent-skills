#!/usr/bin/env python3
"""Build or verify the exact four-skill Frontier 6.3 bundle manifest."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _bundle_hash import FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES, inventory, tree_hash  # noqa: E402


BUNDLE_ID = "frontier-engineering/6.3.0"
SCHEMA_EPOCH = 5
OUTPUT = ROOT / "frontier-engineering.bundle.json"
SCHEMA = ROOT / "bundle" / "frontier-engineering-bundle.schema.json"
SOURCE_MANIFEST = ROOT / "bundle-manifest.json"
EXPECTED_SKILLS = {
    "long-document-segmented-writing": "1.1.0",
    "skill-evaluator": "3.3.1",
    "software-quality-workflows": "9.0.0",
    "writing-plans": "8.2.3",
}
EXPECTED_ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": False,
    "writing-plans": False,
}
SOURCE_FIELDS = {
    "bundle_schema_version",
    "bundle_version",
    "skills",
    "activation_ceiling",
    "remote_writes",
    "test_profiles",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _rendered_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key in {path.relative_to(ROOT)}: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number in {path.relative_to(ROOT)}: {value}")

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular JSON file is missing or symlinked: {path.relative_to(ROOT)}")
    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.relative_to(ROOT)}")
    return value


def _skill_paths(skill_root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in skill_root.rglob("*"):
        relative = path.relative_to(skill_root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            continue
        if path.is_file() or path.is_symlink():
            paths.append(path)
    return paths


def _frontmatter_version(skill_root: Path) -> str:
    path = skill_root / "SKILL.md"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"skill entry is missing or symlinked: {skill_root.name}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"skill entry frontmatter is invalid: {skill_root.name}")
    metadata = yaml.safe_load(text.split("---\n", 2)[1])
    if not isinstance(metadata, dict) or not isinstance(metadata.get("metadata"), dict):
        raise ValueError(f"skill entry metadata is invalid: {skill_root.name}")
    version = metadata["metadata"].get("version")
    if not isinstance(version, str):
        raise ValueError(f"skill entry version is invalid: {skill_root.name}")
    return version


def _activation(skill_root: Path) -> bool:
    path = skill_root / "agents" / "openai.yaml"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"skill activation metadata is missing or symlinked: {skill_root.name}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {"interface", "policy"}:
        raise ValueError(f"skill activation metadata must contain only interface and policy: {skill_root.name}")
    policy = value.get("policy")
    if not isinstance(policy, dict) or set(policy) != {"allow_implicit_invocation"}:
        raise ValueError(f"skill activation policy has an extra or missing source: {skill_root.name}")
    activation = policy["allow_implicit_invocation"]
    if type(activation) is not bool:
        raise ValueError(f"skill activation policy must be boolean: {skill_root.name}")
    return activation


def _skill_record(skill_id: str, version: str) -> dict[str, Any]:
    skill_root = ROOT / skill_id
    if skill_root.is_symlink() or not skill_root.is_dir():
        raise ValueError(f"canonical skill root is missing or symlinked: {skill_id}")
    if _frontmatter_version(skill_root) != version:
        raise ValueError(f"skill frontmatter version differs from source manifest: {skill_id}")
    activation = _activation(skill_root)
    if activation is not EXPECTED_ACTIVATION[skill_id]:
        raise ValueError(f"skill activation differs from the fixed 6.3 matrix: {skill_id}")
    records = inventory(skill_root, _skill_paths(skill_root))
    if not records:
        raise ValueError(f"canonical skill root is empty: {skill_id}")
    return {
        "version": version,
        "root_hash": tree_hash(records),
        "allow_implicit_invocation": activation,
    }


def build_manifest() -> dict[str, Any]:
    source = _load_json(SOURCE_MANIFEST)
    if set(source) != SOURCE_FIELDS:
        raise ValueError(f"source bundle fields differ from schema 3.0: {sorted(source)}")
    if source.get("bundle_schema_version") != "3.0" or source.get("bundle_version") != "6.3.0":
        raise ValueError("source bundle must bind schema 3.0 and release 6.3.0")
    if source.get("activation_ceiling") != "implicit_local_pilot" or source.get("remote_writes") is not False:
        raise ValueError("source bundle activation ceiling or remote-write boundary is invalid")
    profiles = source.get("test_profiles")
    if (
        not isinstance(profiles, dict)
        or set(profiles) != {"quick", "extended", "release"}
        or any(not isinstance(commands, list) or not commands or any(not isinstance(command, str) or not command for command in commands) for commands in profiles.values())
    ):
        raise ValueError("source bundle test profiles are invalid")
    skills = source.get("skills")
    if not isinstance(skills, list):
        raise ValueError("source bundle manifest skills must be an array")
    if any(not isinstance(item, dict) for item in skills):
        raise ValueError("source bundle skill records must be objects")
    observed = {
        item.get("id"): item.get("version")
        for item in skills
        if set(item) == {"id", "path", "version"} and item.get("path") == item.get("id")
    }
    if observed != EXPECTED_SKILLS or len(skills) != len(EXPECTED_SKILLS):
        raise ValueError(f"source bundle must bind the exact four-skill set: {observed}")
    if [item.get("id") for item in skills] != sorted(EXPECTED_SKILLS):
        raise ValueError("source bundle skills must be sorted by id")

    unsigned: dict[str, Any] = {
        "schema_version": "frontier-engineering-bundle/2.0",
        "bundle_id": BUNDLE_ID,
        "compatible_schema_epoch": SCHEMA_EPOCH,
        "activation_ceiling": "implicit_local_pilot",
        "remote_writes": False,
        "skills": {
            skill_id: _skill_record(skill_id, version)
            for skill_id, version in sorted(EXPECTED_SKILLS.items())
        },
    }
    manifest = {
        **unsigned,
        "release_build_id": "build-" + sha256(_canonical_bytes(unsigned)).hexdigest()[:24],
    }
    schema = _load_json(SCHEMA)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(manifest), key=lambda item: list(item.path))
    if errors:
        raise ValueError("generated bundle manifest violates schema: " + errors[0].message)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail unless the checked-in manifest is exact")
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest()
        rendered = _rendered_bytes(manifest)
        if args.check:
            if OUTPUT.is_symlink() or not OUTPUT.is_file() or OUTPUT.read_bytes() != rendered:
                raise ValueError("frontier-engineering.bundle.json is missing or stale")
        else:
            temporary = OUTPUT.with_suffix(".json.tmp")
            if temporary.is_symlink():
                raise ValueError("temporary bundle output must not be a symlink")
            temporary.write_bytes(rendered)
            temporary.replace(OUTPUT)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, "path": str(OUTPUT), "release_build_id": manifest["release_build_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
