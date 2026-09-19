#!/usr/bin/env python3
"""Build or verify the Qoder plugin manifest that ships with this repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "bundle-manifest.json"
TEMPLATE = ROOT / "packaging" / "qoder-plugin" / "plugin.json.template"
OUTPUT = ROOT / ".qoder-plugin" / "plugin.json"
PLUGIN_NAME = "frontier-engineering"
VERSION_PLACEHOLDER = "${BUNDLE_VERSION}"
KEBAB = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DOCUMENTED_FIELDS = {
    "name",
    "version",
    "displayName",
    "description",
    "descriptionZh",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
    "dependencies",
    "commands",
    "agents",
    "skills",
    "outputStyles",
    "workflowsPath",
    "workflowsPaths",
    "hooks",
    "mcpServers",
    "settings",
}
RUNTIME_FIELDS = {
    "dependencies",
    "commands",
    "agents",
    "outputStyles",
    "workflowsPath",
    "workflowsPaths",
    "hooks",
    "mcpServers",
    "settings",
}
LOCAL_PATH_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"/home/[A-Za-z0-9._-]+",
        r"/mnt/data(?:/|$)",
        r"/mnt/[A-Za-z]/Users/[^/\s]+",
        r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+",
    )
)


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


def _rendered_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _source_skill_paths() -> list[str]:
    source = _load_json(SOURCE_MANIFEST)
    if source.get("bundle_schema_version") != "3.0":
        raise ValueError("source bundle must bind schema 3.0")
    version = source.get("bundle_version")
    if not isinstance(version, str) or re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        raise ValueError("source bundle version is not a release version")
    skills = source.get("skills")
    if not isinstance(skills, list) or not skills:
        raise ValueError("source bundle must declare its skills")
    paths: list[str] = []
    for item in skills:
        if not isinstance(item, dict) or set(item) != {"id", "path", "version"}:
            raise ValueError(f"source bundle skill record is invalid: {item!r}")
        if item["path"] != item["id"]:
            raise ValueError(f"source bundle skill path differs from its id: {item!r}")
        paths.append(str(item["path"]))
    if paths != sorted(paths) or len(set(paths)) != len(paths):
        raise ValueError("source bundle skills must be unique and sorted by id")
    return paths


def _validate_skill(skill_id: str) -> None:
    skill_root = ROOT / skill_id
    if skill_root.is_symlink() or not skill_root.is_dir():
        raise ValueError(f"declared skill root is missing or symlinked: {skill_id}")
    entry = skill_root / "SKILL.md"
    if entry.is_symlink() or not entry.is_file():
        raise ValueError(f"declared skill has no regular SKILL.md: {skill_id}")
    text = entry.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, flags=re.DOTALL)
    if match is None:
        raise ValueError(f"declared skill frontmatter is invalid: {skill_id}")
    frontmatter = yaml.safe_load(match.group(1))
    if not isinstance(frontmatter, dict) or frontmatter.get("name") != skill_id:
        raise ValueError(f"declared skill frontmatter name differs from its directory: {skill_id}")
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"declared skill frontmatter needs a description: {skill_id}")


def _validate_template(template: dict[str, Any], skill_paths: list[str]) -> dict[str, Any]:
    unknown = sorted(set(template) - DOCUMENTED_FIELDS)
    if unknown:
        raise ValueError(f"plugin template declares fields outside the documented schema: {unknown}")
    runtime = sorted(set(template) & RUNTIME_FIELDS)
    if runtime:
        raise ValueError(f"plugin template declares a runtime surface: {runtime}")
    required = {"name", "displayName", "version", "description", "descriptionZh", "author", "license", "keywords", "skills"}
    if not required <= set(template):
        raise ValueError("plugin template is missing required portable metadata")
    if template.get("name") != PLUGIN_NAME or KEBAB.fullmatch(str(template.get("name"))) is None:
        raise ValueError("plugin template name is not the canonical kebab-case identity")
    if template.get("version") != VERSION_PLACEHOLDER:
        raise ValueError("plugin template version is not the bundle version placeholder")
    if template.get("skills") != [f"./{path}" for path in skill_paths]:
        raise ValueError("plugin template must declare exactly the canonical skill directories")
    author = template.get("author")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"]:
        raise ValueError("plugin template requires author.name")
    if not isinstance(template.get("keywords"), list) or not all(
        isinstance(item, str) and item for item in template["keywords"]
    ):
        raise ValueError("plugin template keywords must be a list of non-empty strings")
    for field in ("displayName", "description", "descriptionZh", "license"):
        if not isinstance(template.get(field), str) or not template[field].strip():
            raise ValueError(f"plugin template needs a non-empty {field}")
    for field in ("homepage", "repository"):
        value = template.get(field)
        if value is not None and (not isinstance(value, str) or not value.startswith("https://")):
            raise ValueError(f"plugin template {field} must be an https URL")
    return template


def render_manifest() -> dict[str, Any]:
    skill_paths = _source_skill_paths()
    for skill_id in skill_paths:
        _validate_skill(skill_id)
    template = _validate_template(_load_json(TEMPLATE), skill_paths)
    source = _load_json(SOURCE_MANIFEST)
    rendered = json.loads(json.dumps(template))
    rendered["version"] = source["bundle_version"]
    text = _rendered_bytes(rendered).decode("utf-8")
    if any(pattern.search(text) for pattern in LOCAL_PATH_PATTERNS):
        raise ValueError("plugin manifest contains a developer absolute path")
    return rendered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail unless the checked-in manifest is exact")
    args = parser.parse_args(argv)
    try:
        rendered = _rendered_bytes(render_manifest())
        if args.check:
            if OUTPUT.is_symlink() or not OUTPUT.is_file() or OUTPUT.read_bytes() != rendered:
                raise ValueError(".qoder-plugin/plugin.json is missing or stale")
        else:
            if OUTPUT.parent.is_symlink() or (OUTPUT.parent.exists() and not OUTPUT.parent.is_dir()):
                raise ValueError("plugin manifest directory is invalid")
            OUTPUT.parent.mkdir(parents=True, exist_ok=True)
            temporary = OUTPUT.with_suffix(".json.tmp")
            if temporary.is_symlink():
                raise ValueError("temporary plugin manifest must not be a symlink")
            temporary.write_bytes(rendered)
            temporary.replace(OUTPUT)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, "path": str(OUTPUT.relative_to(ROOT))}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
