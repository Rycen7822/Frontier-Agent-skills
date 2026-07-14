#!/usr/bin/env python3
"""Build an isolated, runtime-free Codex plugin staging tree and hash evidence."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
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
    "schema_version", "bundle_version", "source_tree_hash", "source_revision",
    "source_revision_signed", "source_clean", "p5_report_content_hash",
    "release_gate", "approved_activation_level",
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


def _safe_bundle_relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("bundle artifact reference must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("bundle artifact reference escapes the source root")
    return value


def skill_version(path: Path) -> str:
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^  version:\s*([^\s#]+)\s*$", text)
    if not match:
        raise ValueError(f"missing metadata.version in {path / 'SKILL.md'}")
    return match.group(1)


def validate_source(source_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    skills = manifest.get("skills")
    if not isinstance(skills, list) or {item.get("id") for item in skills if isinstance(item, dict)} != {"writing-plans", "software-quality-workflows"}:
        raise ValueError("manifest must declare exactly the two canonical skills")
    if manifest.get("bundle_schema_version") != "1.0" or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", str(manifest.get("bundle_version", ""))):
        raise ValueError("manifest bundle schema/version is invalid")
    for item in skills:
        if not isinstance(item, dict) or set(item) != {"id", "path", "version"}:
            raise ValueError("manifest skill entries must contain only id, path, and version")
        path = source_root / item["path"]
        observed = skill_version(path)
        if observed != item["version"]:
            raise ValueError(f"version mismatch for {item['id']}: manifest={item['version']} skill={observed}")
    activation = manifest.get("activation_policy")
    required_activation = {
        "current_level", "live_autonomous_closure_default", "multi_candidate_enabled",
        "remote_writes", "p5_report", "p5_control_evidence",
    }
    if not isinstance(activation, dict) or set(activation) != required_activation:
        raise ValueError("manifest activation policy fields are invalid")
    if (
        activation.get("current_level") != "shadow"
        or activation.get("live_autonomous_closure_default") is not False
        or activation.get("multi_candidate_enabled") is not False
        or activation.get("remote_writes") is not False
    ):
        raise ValueError("source activation policy exceeds the checked-in shadow ceiling")
    for field in ("p5_report", "p5_control_evidence"):
        relative = _safe_bundle_relative(activation[field])
        target = source_root / relative
        if target.is_symlink() or not target.is_file() or not target.resolve(strict=True).is_relative_to(source_root):
            raise ValueError(f"manifest activation artifact is missing, symlinked, or escaping: {relative}")
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
    if set(evidence) != RELEASE_FIELDS or evidence.get("schema_version") != "p6-release-evidence/1.0":
        raise ValueError("release evidence schema is invalid")
    if evidence.get("bundle_version") != manifest.get("bundle_version") or evidence.get("source_tree_hash") != source_tree_hash:
        raise ValueError("release evidence source tree or bundle version does not match")
    report_relative = _safe_bundle_relative(manifest.get("activation_policy", {}).get("p5_report"))
    report_path = source_root / report_relative
    report = _strict_json(report_path)
    if evidence.get("p5_report_content_hash") != _content_hash(report_path):
        raise ValueError("release evidence P5 report hash does not match")
    if report.get("decision") != "eligible_for_p6_canary" or report.get("activation_ceiling") != "explicit_only":
        raise ValueError("P5 report does not authorize a P6 canary")
    revision = evidence.get("source_revision")
    if (
        evidence.get("release_gate") != "passed"
        or evidence.get("approved_activation_level") != "explicit_only"
        or evidence.get("source_revision_signed") is not True
        or evidence.get("source_clean") is not True
        or not isinstance(revision, str)
        or not re.fullmatch(r"[0-9a-f]{40,64}", revision)
        or not _git_release_source_ok(source_root, revision)
    ):
        raise ValueError("release evidence lacks a clean signed source revision and explicit-only approval")
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


def _cleanup_published_output(output: Path, expected_hash: str) -> None:
    try:
        if output.is_dir() and not output.is_symlink():
            records = inventory(output, [path for path in output.rglob("*") if path.is_file() or path.is_symlink()])
            if tree_hash(records) == expected_hash:
                shutil.rmtree(output)
    except (OSError, ValueError):
        pass


def build(source_root: Path, output: Path, release_evidence: Path | None, evidence_output: Path) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    output = output.resolve(strict=False)
    evidence_output = evidence_output.resolve(strict=False)
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
    is_release = "dist" in output.parts
    if is_release:
        validate_release_evidence(
            release_evidence,
            source_root=source_root,
            manifest=manifest,
            source_tree_hash=source_tree_hash,
        )

    report_path = source_root / manifest["activation_policy"]["p5_report"]
    p5_report = _strict_json(report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="closure-plugin-", dir=output.parent))
    evidence_temporary: Path | None = None
    published = False
    plugin_tree_hash = ""
    try:
        (temporary / ".codex-plugin").mkdir()
        (temporary / "skills").mkdir()
        (temporary / ".codex-plugin" / "plugin.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for item in manifest["skills"]:
            shutil.copytree(source_root / item["path"], temporary / "skills" / item["id"])
        plugin_records = _validate_staging(temporary, template["name"])
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
        evidence: dict[str, Any] = {
            "schema_version": "p6-plugin-build-evidence/1.0",
            "bundle_version": manifest["bundle_version"],
            "skill_versions": {item["id"]: item["version"] for item in sorted(manifest["skills"], key=lambda item: item["id"])},
            "source_tree_hash": source_tree_hash,
            "source_file_count": len(source_records),
            "plugin_tree_hash": plugin_tree_hash,
            "plugin_file_count": len(plugin_records),
            "plugin_name": template["name"],
            "output_class": "release" if is_release else "staging",
            "release_gate_used": is_release,
            "p5_report_content_hash": _content_hash(report_path),
            "p5_decision": p5_report.get("decision"),
            "files": plugin_records,
        }
        evidence["evidence_hash"] = "sha256:" + sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        descriptor, temporary_name = tempfile.mkstemp(prefix="closure-evidence-", dir=evidence_output.parent)
        evidence_temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.rename(output)
        published = True
        os.link(evidence_temporary, evidence_output)
        evidence_temporary.unlink()
        evidence_temporary = None
        return evidence
    except BaseException:
        if published and not evidence_output.exists() and plugin_tree_hash:
            _cleanup_published_output(output, plugin_tree_hash)
        shutil.rmtree(temporary, ignore_errors=True)
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
