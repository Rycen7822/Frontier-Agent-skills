#!/usr/bin/env python3
"""Build or verify the exact two-skill release identity manifest."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _bundle_hash import FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES, inventory, tree_hash  # noqa: E402


BUNDLE_ID = "frontier-engineering/6.0.0+5.0.0"
SCHEMA_EPOCH = 2
OUTPUT = ROOT / "frontier-engineering.bundle.json"
SCHEMA = ROOT / "bundle" / "frontier-engineering-bundle.schema.json"
SOURCE_MANIFEST = ROOT / "bundle-manifest.json"
EXPECTED_SKILLS = {
    "software-quality-workflows": "6.0.0",
    "writing-plans": "5.0.0",
}
POLICY_REGISTRY = Path("registries/policy-owners.json")
CARD_MANIFEST = Path("registries/reference-cards.manifest.json")
HANDOFF_OWNER = Path("writing-plans/schemas/plan-execution-handoff.schema.json")
def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _rendered_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required regular JSON file is missing or symlinked: {path.relative_to(ROOT)}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path.relative_to(ROOT)}")
    return value


def _content_hash(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"hash input is missing or symlinked: {path.relative_to(ROOT)}")
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _skill_paths(skill_root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in skill_root.rglob("*"):
        relative = path.relative_to(skill_root)
        if any(part in FORBIDDEN_PARTS for part in relative.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            continue
        if path.is_file() or path.is_symlink():
            paths.append(path)
    return paths


def _skill_record(skill_id: str, version: str) -> dict[str, Any]:
    skill_root = ROOT / skill_id
    if skill_root.is_symlink() or not skill_root.is_dir():
        raise ValueError(f"canonical skill root is missing or symlinked: {skill_id}")

    components: dict[str, dict[str, str]] = {}
    for key, relative in (
        ("policy_registry", POLICY_REGISTRY),
        ("reference_card_manifest", CARD_MANIFEST),
    ):
        path = skill_root / relative
        value = _load_json(path)
        expected_identity = {
            "bundle_id": BUNDLE_ID,
            "skill_id": skill_id,
            "skill_version": version,
        }
        observed = {field: value.get(field) for field in expected_identity}
        if observed != expected_identity:
            raise ValueError(f"{skill_id}/{relative} identity mismatch: {observed}")
        components[key] = {
            "path": f"{skill_id}/{relative.as_posix()}",
            "content_hash": _content_hash(path),
        }

    records = inventory(skill_root, _skill_paths(skill_root))
    if not records:
        raise ValueError(f"canonical skill root is empty: {skill_id}")
    return {
        "version": version,
        "root_hash": tree_hash(records),
        **components,
    }


def build_manifest() -> dict[str, Any]:
    source = _load_json(SOURCE_MANIFEST)
    skills = source.get("skills")
    if not isinstance(skills, list):
        raise ValueError("source bundle manifest skills must be an array")
    observed = {
        item.get("id"): item.get("version")
        for item in skills
        if isinstance(item, dict)
    }
    if observed != EXPECTED_SKILLS or len(skills) != len(EXPECTED_SKILLS):
        raise ValueError(f"source bundle must bind the exact vNext skill pair: {observed}")
    if source.get("bundle_schema_version") != "2.0" or source.get("bundle_version") != "2.0.1":
        raise ValueError("source bundle must bind schema 2.0 and release 2.0.1")
    if source.get("cross_skill_contracts") != ["plan-to-workflow", "workflow-plan-change-proposal"]:
        raise ValueError("source bundle must declare the exact two cross-skill contracts")
    if source.get("activation_policy") != {
        "current_level": "implicit_local_pilot",
        "implicit_routing_default": True,
        "remote_writes": False,
    }:
        raise ValueError("source bundle must retain the exact three-field implicit-local policy")

    handoff = _load_json(ROOT / HANDOFF_OWNER)
    contract_id = handoff.get("$id")
    if contract_id != "https://local.frontier-agent/schemas/plan-execution-handoff.schema.json":
        raise ValueError("plan-execution-handoff schema has an unexpected contract ID")

    unsigned: dict[str, Any] = {
        "schema_version": "frontier-engineering-bundle/1.0",
        "bundle_id": BUNDLE_ID,
        "compatible_schema_epoch": SCHEMA_EPOCH,
        "skills": {
            skill_id: _skill_record(skill_id, version)
            for skill_id, version in sorted(EXPECTED_SKILLS.items())
        },
        "contracts": {
            "plan-execution-handoff": {
                "contract_id": contract_id,
                "normative_owner_path": HANDOFF_OWNER.as_posix(),
                "normative_owner_hash": _content_hash(ROOT / HANDOFF_OWNER),
            }
        },
    }
    release_build_id = "build-" + sha256(_canonical_bytes(unsigned)).hexdigest()[:24]
    manifest = {**unsigned, "release_build_id": release_build_id}
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
            temporary.write_bytes(rendered)
            temporary.replace(OUTPUT)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, "path": str(OUTPUT), "release_build_id": manifest["release_build_id"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
