#!/usr/bin/env python3
"""Run a model-free, isolated discovery/install/uninstall smoke on a staged plugin."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import inventory, tree_hash  # noqa: E402
from build_codex_plugin import _strict_json  # noqa: E402


EXPECTED_SKILLS = {"writing-plans", "software-quality-workflows"}


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError(f"skill frontmatter is missing: {path}")
    block = text.split("\n---\n", 1)[0].removeprefix("---\n")
    result: dict[str, str] = {}
    for line in block.splitlines():
        if line and not line.startswith((" ", "\t")) and ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip('"')
        elif line.startswith("  version: "):
            result["version"] = line.removeprefix("  version: ").strip().strip('"')
    for field in ("name", "description", "version"):
        if not result.get(field):
            raise ValueError(f"skill frontmatter lacks {field}: {path}")
    return result


def inspect_plugin(plugin_root: Path, evidence_path: Path) -> dict[str, Any]:
    plugin_root = plugin_root.resolve(strict=True)
    evidence = _strict_json(evidence_path)
    unhashed = dict(evidence)
    observed_evidence_hash = unhashed.pop("evidence_hash", None)
    expected_evidence_hash = "sha256:" + sha256(
        json.dumps(unhashed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if observed_evidence_hash != expected_evidence_hash:
        raise ValueError("build evidence self-hash is invalid")
    manifest = _strict_json(plugin_root / ".codex-plugin" / "plugin.json")
    if plugin_root.name != manifest.get("name") or manifest.get("name") != evidence.get("plugin_name"):
        raise ValueError("plugin directory, manifest, and build evidence identities differ")
    if manifest.get("version") != evidence.get("bundle_version") or manifest.get("skills") != "./skills/":
        raise ValueError("plugin version or skill discovery path differs from build evidence")
    candidates = [path for path in plugin_root.rglob("*") if path.is_file() or path.is_symlink()]
    records = inventory(plugin_root, candidates)
    if tree_hash(records) != evidence.get("plugin_tree_hash") or records != evidence.get("files"):
        raise ValueError("staged plugin bytes differ from immutable build evidence")

    discovered: dict[str, dict[str, Any]] = {}
    skills_root = plugin_root / "skills"
    if {path.name for path in skills_root.iterdir() if path.is_dir()} != EXPECTED_SKILLS:
        raise ValueError("static discovery did not find exactly the two canonical skills")
    for name in sorted(EXPECTED_SKILLS):
        skill_root = skills_root / name
        fields = _frontmatter(skill_root / "SKILL.md")
        if fields["name"] != name or evidence.get("skill_versions", {}).get(name) != fields["version"]:
            raise ValueError(f"explicit skill identity/version mismatch: {name}")
        metadata = (skill_root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        if "allow_implicit_invocation: false" not in metadata or "default_prompt:" not in metadata or f"${name}" not in metadata:
            raise ValueError(f"Codex invocation metadata is incomplete: {name}")
        if any(marker in metadata for marker in ("hooks:", "mcp:", "apps:", "remote_writes_default: true")):
            raise ValueError(f"skill metadata attempts to widen plugin authority: {name}")
        discovered[name] = {
            "version": fields["version"],
            "description_hash": "sha256:" + sha256(fields["description"].encode("utf-8")).hexdigest(),
            "explicit_invocation": True,
            "implicit_eligible": False,
        }
    return {
        "schema_version": "static-plugin-smoke/2.0",
        "plugin_name": manifest["name"],
        "plugin_tree_hash": evidence["plugin_tree_hash"],
        "build_evidence_hash": evidence["evidence_hash"],
        "activation_ceiling": "shadow",
        "actual_codex_cli_install": False,
        "model_invoked": False,
        "remote_writes": False,
        "discovered_skills": discovered,
    }


def isolated_smoke(plugin_root: Path, evidence_path: Path) -> dict[str, Any]:
    first = inspect_plugin(plugin_root, evidence_path)
    with tempfile.TemporaryDirectory() as directory:
        installation = Path(directory) / plugin_root.name
        shutil.copytree(plugin_root, installation)
        installed = inspect_plugin(installation, evidence_path)
        if installed != first:
            raise ValueError("isolated installed discovery differs from staged discovery")
        shutil.rmtree(installation)
        uninstall_clean = not installation.exists()
    return {**first, "isolated_install_discovery": True, "uninstall_clean": uninstall_clean}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--build-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = isolated_smoke(args.plugin_root, args.build_evidence)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "plugin_tree_hash": result["plugin_tree_hash"], "actual_codex_cli_install": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
