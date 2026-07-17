#!/usr/bin/env python3
"""Build an isolated, runtime-free Codex plugin staging tree and hash evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import bundle_inventory, inventory, tree_hash  # noqa: E402


FORBIDDEN_PLUGIN_KEYS = {"mcpServers", "apps", "hooks"}
FORBIDDEN_PLUGIN_NAMES = {".mcp.json", ".app.json", "hooks.json"}
TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".py", ".template"}
RELEASE_FIELDS = {
    "schema_version", "bundle_id", "bundle_version", "source_tree_hash", "source_revision",
    "source_revision_signed", "source_clean", "deterministic_report_hash",
    "l2_scored_report_hash", "activation_decision_hash", "release_gate",
    "approved_activation_level",
}


def _strict_json(path: Path, maximum: int = 4 * 1024 * 1024) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError(f"JSON input exceeds byte budget: {path}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > maximum:
            raise ValueError(f"JSON input exceeds byte budget: {path}")
    finally:
        os.close(descriptor)

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number in {path}: {value}")

    value = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _content_hash(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"hash input is not a regular file: {path}")
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)


def skill_version(path: Path) -> str:
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^  version:\s*([^\s#]+)\s*$", text)
    if not match:
        raise ValueError(f"missing metadata.version in {path / 'SKILL.md'}")
    return match.group(1)


def _validate_exact_bundle_identity(source_root: Path) -> None:
    builder_path = source_root / "bundle" / "build_bundle_manifest.py"
    output_path = source_root / "frontier-engineering.bundle.json"
    if builder_path.is_symlink() or not builder_path.is_file():
        raise ValueError("exact bundle identity builder is missing or symlinked")
    namespace: dict[str, Any] = {
        "__file__": str(builder_path),
        "__name__": "frontier_bundle_identity_validation",
    }
    exec(compile(builder_path.read_text(encoding="utf-8"), str(builder_path), "exec"), namespace)
    expected = namespace["build_manifest"]()
    observed = _strict_json(output_path)
    if observed != expected:
        raise ValueError("frontier-engineering.bundle.json does not match the exact two-skill source")
    rendered = (json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if output_path.is_symlink() or output_path.read_bytes() != rendered:
        raise ValueError("frontier-engineering.bundle.json is not the canonical generated artifact")


def validate_source(source_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    skills = manifest.get("skills")
    if not isinstance(skills, list) or {item.get("id") for item in skills if isinstance(item, dict)} != {"writing-plans", "software-quality-workflows"}:
        raise ValueError("manifest must declare exactly the two canonical skills")
    if (manifest.get("bundle_schema_version"), manifest.get("bundle_version")) != ("2.0", "2.0.0"):
        raise ValueError("manifest bundle schema/version is invalid")
    if {item.get("id"): item.get("version") for item in skills} != {
        "writing-plans": "5.0.0", "software-quality-workflows": "6.0.0",
    }:
        raise ValueError("version mismatch: manifest skill versions do not match the 6+5 release identity")
    for item in skills:
        if not isinstance(item, dict) or set(item) != {"id", "path", "version"}:
            raise ValueError("manifest skill entries must contain only id, path, and version")
        path = source_root / item["path"]
        observed = skill_version(path)
        if observed != item["version"]:
            raise ValueError(f"version mismatch for {item['id']}: manifest={item['version']} skill={observed}")
    _validate_exact_bundle_identity(source_root)
    activation = manifest.get("activation_policy")
    required_activation = {
        "current_level": "shadow", "implicit_routing_default": False, "remote_writes": False,
    }
    if activation != required_activation:
        raise ValueError("manifest activation policy fields are invalid")
    if manifest.get("cross_skill_contracts") != ["plan-to-workflow", "workflow-plan-change-proposal"]:
        raise ValueError("manifest cross-skill contracts do not match the 6+5 release identity")
    records = bundle_inventory(source_root, manifest)
    for record in records:
        path = source_root / record["path"]
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("/" + "home" + "/", "/" + "mnt" + "/" + "data" + "/", "[TODO:"):
            if marker in text:
                raise ValueError(f"reader-facing source contains forbidden local/placeholder marker: {record['path']}")
    return records


def _validate_template(template: dict[str, Any], bundle_version: str) -> dict[str, Any]:
    if FORBIDDEN_PLUGIN_KEYS & set(template):
        raise ValueError("plugin template declares a forbidden runtime surface")
    required = {"name", "version", "description", "author", "license", "keywords", "skills", "interface"}
    if not required <= set(template) or template.get("version") != "${BUNDLE_VERSION}" or template.get("skills") != "./skills/":
        raise ValueError("plugin template is missing a required portable manifest binding")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(template.get("name", ""))):
        raise ValueError("plugin name must be normalized lower-case hyphen-case")
    if template.get("name") != "frontier-engineering-plugin":
        raise ValueError("plugin template name is not the canonical release identity")
    serialized = json.dumps(template, ensure_ascii=False, sort_keys=True).lower()
    if "closure" in serialized or "autonomous" in serialized:
        raise ValueError("plugin template contains retired product identity")
    author = template.get("author")
    interface = template.get("interface")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str):
        raise ValueError("plugin template requires author.name")
    required_interface = {"displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities"}
    if not isinstance(interface, dict) or not required_interface <= set(interface):
        raise ValueError("plugin template lacks required interface metadata")
    prompts = interface.get("defaultPrompt", [])
    if not isinstance(prompts, list) or len(prompts) > 3 or any(not isinstance(item, str) or len(item) > 128 for item in prompts):
        raise ValueError("plugin defaultPrompt must contain at most three bounded strings")
    rendered = json.loads(json.dumps(template))
    rendered["version"] = bundle_version
    return rendered


def _git_release_source_ok(source_root: Path, revision: str) -> bool:
    commands = (
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        ["git", "-C", str(source_root), "status", "--porcelain", "--untracked-files=all", "--", "."],
        ["git", "-C", str(source_root), "verify-commit", revision],
    )
    results = [subprocess.run(command, text=True, capture_output=True, check=False, timeout=30) for command in commands]
    return results[0].returncode == 0 and results[0].stdout.strip() == revision and results[1].returncode == 0 and not results[1].stdout.strip() and results[2].returncode == 0


def validate_release_evidence(
    path: Path | None,
    *,
    source_root: Path,
    manifest: dict[str, Any],
    source_tree_hash: str,
) -> dict[str, Any]:
    if path is None:
        raise ValueError("dist output requires matching passed release evidence")
    evidence = _strict_json(path)
    if set(evidence) != RELEASE_FIELDS or evidence.get("schema_version") != "release-evidence/2.0":
        raise ValueError("release evidence schema is invalid")
    bundle = _strict_json(source_root / "frontier-engineering.bundle.json")
    report = _strict_json(source_root / "evaluation" / "offline-route-replay.json")
    if (
        evidence.get("bundle_id") != bundle.get("bundle_id")
        or evidence.get("bundle_version") != manifest.get("bundle_version")
        or evidence.get("source_tree_hash") != source_tree_hash
    ):
        raise ValueError("release evidence source tree or bundle identity does not match")
    if evidence.get("deterministic_report_hash") != report.get("report_hash"):
        raise ValueError("release evidence deterministic report hash does not match")
    revision = evidence.get("source_revision")
    if (
        evidence.get("release_gate") != "passed"
        or evidence.get("approved_activation_level") != "explicit_local_pilot"
        or evidence.get("source_revision_signed") is not True
        or evidence.get("source_clean") is not True
        or not isinstance(revision, str)
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
        or not _git_release_source_ok(source_root, revision)
    ):
        raise ValueError("release evidence lacks a clean signed source revision and explicit local pilot approval")
    return evidence


def _validate_staging(staging: Path, plugin_name: str) -> list[dict[str, Any]]:
    if {path.name for path in staging.iterdir()} != {".codex-plugin", "skills"}:
        raise ValueError("plugin staging root must contain only .codex-plugin and skills")
    plugin_directory = staging / ".codex-plugin"
    if {path.name for path in plugin_directory.iterdir()} != {"plugin.json"}:
        raise ValueError(".codex-plugin must contain only plugin.json")
    manifest = _strict_json(plugin_directory / "plugin.json")
    if manifest.get("name") != plugin_name or FORBIDDEN_PLUGIN_KEYS & set(manifest):
        raise ValueError("rendered plugin manifest identity or runtime surface is invalid")
    skill_names = {path.name for path in (staging / "skills").iterdir() if path.is_dir()}
    if skill_names != {"writing-plans", "software-quality-workflows"}:
        raise ValueError("staging must contain exactly the two canonical skills")
    candidates = [path for path in staging.rglob("*") if path.is_file() or path.is_symlink()]
    if any(path.name in FORBIDDEN_PLUGIN_NAMES for path in candidates):
        raise ValueError("staging contains a forbidden MCP/app/hook file")
    records = inventory(staging, candidates)
    for record in records:
        path = staging / record["path"]
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            if "/" + "home" + "/" in text or "/" + "mnt" + "/" + "data" + "/" in text:
                raise ValueError(f"staging contains a developer absolute path: {record['path']}")
    return records


def _assert_skill_copy_matches(source_records: list[dict[str, Any]], plugin_records: list[dict[str, Any]]) -> None:
    plugin_by_path = {record["path"]: record for record in plugin_records}
    for source in source_records:
        if source["path"] == "bundle-manifest.json":
            continue
        target_path = "skills/" + source["path"]
        target = plugin_by_path.get(target_path)
        if target is None or any(target[field] != source[field] for field in ("content_hash", "size", "mode")):
            raise ValueError(f"E_SOURCE_DRIFT: staged skill bytes differ from frozen source inventory: {source['path']}")


def _source_revision(source_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        text=True, capture_output=True, check=False, timeout=30,
    )
    revision = completed.stdout.strip()
    if completed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("source root lacks a canonical Git revision")
    return revision


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"symlinked output path component is forbidden: {cursor}")
        if not cursor.exists():
            break


def build(source_root: Path, output: Path, release_evidence: Path | None, evidence_output: Path) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    output = output.absolute()
    evidence_output = evidence_output.absolute()
    _reject_symlink_components(output)
    _reject_symlink_components(evidence_output)
    manifest = _strict_json(source_root / "bundle-manifest.json")
    source_records = validate_source(source_root, manifest)
    source_tree_hash = tree_hash(source_records)
    if output.exists() or evidence_output.exists():
        raise ValueError("output and evidence paths are no-overwrite")
    if evidence_output == output or evidence_output.is_relative_to(output):
        raise ValueError("build evidence must be outside the plugin staging tree")

    template = _validate_template(
        _strict_json(source_root / "packaging" / "codex-plugin" / "plugin.json.template"),
        str(manifest["bundle_version"]),
    )
    if output.name != template["name"]:
        raise ValueError(f"plugin output folder must match manifest name: {template['name']}")
    is_release = release_evidence is not None or "dist" in output.parts
    release_binding: dict[str, Any] | None = None
    if is_release:
        release_binding = validate_release_evidence(
            release_evidence,
            source_root=source_root,
            manifest=manifest,
            source_tree_hash=source_tree_hash,
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    staging = evidence_output.parent / "plugin-build-staging"
    if staging.exists() or staging.is_symlink():
        raise ValueError("plugin build staging path is no-overwrite")
    if output.parent.stat().st_dev != evidence_output.parent.stat().st_dev:
        raise ValueError("plugin staging and destination must share one filesystem")
    staging.mkdir(mode=0o700)
    evidence_temporary: Path | None = None
    published = False
    try:
        (staging / ".codex-plugin").mkdir()
        (staging / "skills").mkdir()
        (staging / ".codex-plugin" / "plugin.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for item in manifest["skills"]:
            shutil.copytree(source_root / item["path"], staging / "skills" / item["id"])
        plugin_records = _validate_staging(staging, template["name"])
        _assert_skill_copy_matches(source_records, plugin_records)
        if validate_source(source_root, manifest) != source_records:
            raise ValueError("E_SOURCE_DRIFT: bundle source changed during plugin staging")
        if is_release:
            validate_release_evidence(
                release_evidence,
                source_root=source_root,
                manifest=manifest,
                source_tree_hash=source_tree_hash,
            )
        plugin_tree_hash = tree_hash(plugin_records)
        release_evidence_hash = _content_hash(release_evidence) if release_evidence is not None else None
        evidence: dict[str, Any] = {
            "schema_version": "plugin-build-evidence/2.0",
            "bundle_id": _strict_json(source_root / "frontier-engineering.bundle.json")["bundle_id"],
            "bundle_version": manifest["bundle_version"],
            "skill_versions": {item["id"]: item["version"] for item in sorted(manifest["skills"], key=lambda item: item["id"])},
            "source_tree_hash": source_tree_hash,
            "source_revision": _source_revision(source_root),
            "source_file_count": len(source_records),
            "plugin_tree_hash": plugin_tree_hash,
            "plugin_file_count": len(plugin_records),
            "plugin_name": template["name"],
            "output_class": "release" if is_release else "staging",
            "release_evidence_hash": release_evidence_hash,
            "activation_ceiling": "explicit_local_pilot" if release_binding is not None else "shadow",
            "files": plugin_records,
        }
        evidence["evidence_hash"] = "sha256:" + sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        descriptor, temporary_name = tempfile.mkstemp(prefix="plugin-build-evidence-", dir=evidence_output.parent)
        evidence_temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        staging.rename(output)
        published = True
        os.link(evidence_temporary, evidence_output)
        evidence_temporary.unlink()
        evidence_temporary = None
        return evidence
    except BaseException:
        if published and not evidence_output.exists() and not staging.exists() and (output.exists() or output.is_symlink()):
            output.rename(staging)
        if evidence_temporary is not None:
            evidence_temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--release-evidence", type=Path)
    args = parser.parse_args(argv)
    try:
        evidence = build(args.source_root, args.output, args.release_evidence, args.evidence_output)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "ok": True,
        "plugin_name": evidence["plugin_name"],
        "output_class": evidence["output_class"],
        "plugin_tree_hash": evidence["plugin_tree_hash"],
        "evidence_hash": evidence["evidence_hash"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
