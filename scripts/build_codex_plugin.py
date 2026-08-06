#!/usr/bin/env python3
"""Build an isolated, runtime-free Codex plugin staging tree and hash evidence."""

from __future__ import annotations

import argparse
import ctypes
import errno
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

sys.dont_write_bytecode = True

from jsonschema import Draft202012Validator  # noqa: E402
import yaml  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import bundle_inventory, inventory, tree_hash  # noqa: E402
from _deterministic_zip import (  # noqa: E402
    ZipMember,
    verify_deterministic_zip,
    write_deterministic_zip,
)


FORBIDDEN_PLUGIN_KEYS = {"mcpServers", "apps", "hooks"}
FORBIDDEN_PLUGIN_NAMES = {".mcp.json", ".app.json", "hooks.json"}
TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".py", ".template"}
LOCAL_PATH_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"/home/[A-Za-z0-9._-]+",
    r"/mnt/data(?:/|$)",
    r"/mnt/[A-Za-z]/Users/[^/\s]+",
    r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s]+",
))
PLACEHOLDER_PATTERN = re.compile(re.escape(chr(91)) + "TODO:")
EXPECTED_SKILLS = {
    "long-document-segmented-writing": "1.1.0",
    "skill-evaluator": "3.3.0",
    "software-quality-workflows": "9.0.0",
    "writing-plans": "8.2.1",
}
EXPECTED_ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": False,
    "writing-plans": False,
}
EXPECTED_APPROVED_ACTIVATION = {
    skill_id: "implicit" if enabled else "explicit_only"
    for skill_id, enabled in EXPECTED_ACTIVATION.items()
}
CANONICAL_MARKETPLACE = {
    "name": "frontier-engineering-v6-release",
    "plugins": [{
        "name": "frontier-engineering-plugin",
        "source": {
            "source": "local",
            "path": "./plugins/frontier-engineering-plugin",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Developer Tools",
    }],
}


def _contains_forbidden_reader_marker(text: str) -> bool:
    return PLACEHOLDER_PATTERN.search(text) is not None or any(
        pattern.search(text) for pattern in LOCAL_PATH_PATTERNS
    )


def _regular_bytes(path: Path, maximum: int = 4 * 1024 * 1024) -> bytes:
    _reject_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"input is not a regular file: {path}")
        if info.st_size > maximum:
            raise ValueError(f"JSON input exceeds byte budget: {path}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) > maximum:
            raise ValueError(f"JSON input exceeds byte budget: {path}")
    finally:
        os.close(descriptor)
    return value


def _decode_json(payload: bytes, path: Path) -> dict[str, Any]:

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


def _strict_json(path: Path, maximum: int = 4 * 1024 * 1024) -> dict[str, Any]:
    return _decode_json(_regular_bytes(path, maximum), path)


def _validate_schema(
    source_root: Path,
    schema_name: str,
    document: dict[str, Any],
    label: str,
) -> None:
    schema = _strict_json(source_root / "packaging" / "schemas" / schema_name)
    Draft202012Validator.check_schema(schema)
    if list(Draft202012Validator(schema).iter_errors(document)):
        raise ValueError(f"{label} is invalid")


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


def skill_activation(path: Path) -> bool:
    value = yaml.safe_load((path / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid agents/openai.yaml object: {path}")
    policy = value.get("policy")
    if not isinstance(policy, dict) or set(policy) != {"allow_implicit_invocation"}:
        raise ValueError(f"agents/openai.yaml must declare only policy.allow_implicit_invocation: {path}")
    activation = policy["allow_implicit_invocation"]
    if not isinstance(activation, bool):
        raise ValueError(f"allow_implicit_invocation must be boolean: {path}")
    return activation


def _self_hash_field(report: dict[str, Any], field: str) -> str:
    value = dict(report)
    value.pop(field, None)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _self_hash(report: dict[str, Any]) -> str:
    return _self_hash_field(report, "report_hash")


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
        raise ValueError("frontier-engineering.bundle.json does not match the exact four-skill source")
    rendered = (json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if output_path.is_symlink() or output_path.read_bytes() != rendered:
        raise ValueError("frontier-engineering.bundle.json is not the canonical generated artifact")


def validate_source(source_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    skills = manifest.get("skills")
    if not isinstance(skills, list) or {item.get("id") for item in skills if isinstance(item, dict)} != set(EXPECTED_SKILLS):
        raise ValueError("manifest must declare exactly the four canonical skills")
    if (manifest.get("bundle_schema_version"), manifest.get("bundle_version")) != ("3.0", "6.3.0"):
        raise ValueError("manifest bundle schema/version is invalid")
    if {item.get("id"): item.get("version") for item in skills} != EXPECTED_SKILLS:
        raise ValueError("version mismatch: manifest skill versions do not match the four-skill release identity")
    observed_activation: dict[str, bool] = {}
    for item in skills:
        if not isinstance(item, dict) or set(item) != {"id", "path", "version"}:
            raise ValueError("manifest skill entries must contain only id, path, and version")
        if item["path"] != item["id"]:
            raise ValueError(f"manifest skill path must equal its canonical id: {item['id']}")
        path = source_root / item["path"]
        observed = skill_version(path)
        if observed != item["version"]:
            raise ValueError(f"version mismatch for {item['id']}: manifest={item['version']} skill={observed}")
        observed_activation[item["id"]] = skill_activation(path)
    if observed_activation != EXPECTED_ACTIVATION:
        raise ValueError("skill activation does not match the exact mixed activation matrix")
    _validate_exact_bundle_identity(source_root)
    if manifest.get("activation_ceiling") != "implicit_local_pilot" or manifest.get("remote_writes") is not False:
        raise ValueError("manifest activation ceiling or remote-write boundary is invalid")
    generated = _strict_json(source_root / "frontier-engineering.bundle.json")
    generated_activation = {
        skill_id: record.get("allow_implicit_invocation")
        for skill_id, record in generated.get("skills", {}).items()
        if isinstance(record, dict)
    }
    if generated_activation != EXPECTED_ACTIVATION:
        raise ValueError("generated bundle activation does not match skill metadata")
    records = bundle_inventory(source_root, manifest)
    for record in records:
        path = source_root / record["path"]
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        if _contains_forbidden_reader_marker(text):
            raise ValueError(
                "reader-facing source contains forbidden local/placeholder "
                f"marker: {record['path']}",
            )
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


def _validate_release_authorization(
    authorization: dict[str, Any],
    *,
    source_root: Path,
    manifest: dict[str, Any],
    source_tree_hash: str,
    plugin_tree_hash: str | None = None,
) -> dict[str, Any]:
    _validate_schema(
        source_root,
        "release-authorization-v1.schema.json",
        authorization,
        "release authorization",
    )
    bundle = _strict_json(source_root / "frontier-engineering.bundle.json")
    revision = authorization.get("source_revision")
    authority = authorization.get("authority")
    if (
        authorization.get("authorization_hash")
        != _self_hash_field(authorization, "authorization_hash")
        or authorization.get("bundle_id") != bundle.get("bundle_id")
        or authorization.get("bundle_version") != manifest.get("bundle_version")
        or authorization.get("source_tree_hash") != source_tree_hash
        or authorization.get("approved_skill_activation")
        != EXPECTED_APPROVED_ACTIVATION
        or authorization.get("remote_writes") is not False
        or not isinstance(authority, dict)
        or any(
            not isinstance(authority.get(field), str)
            or not authority[field].strip()
            for field in ("authority_id", "signature_attestation")
        )
        or not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or not _git_release_source_ok(source_root, revision)
    ):
        raise ValueError(
            "release authorization source, bundle, activation, or authority "
            "identity does not match a clean signed revision"
        )
    if (
        plugin_tree_hash is not None
        and authorization.get("plugin_tree_hash") != plugin_tree_hash
    ):
        raise ValueError(
            "release authorization plugin tree hash does not match the staged plugin"
        )
    static_report = _strict_json(
        source_root / "evaluation" / "static-contract-diagnostic.json"
    )
    if (
        static_report.get("report_hash") != _self_hash(static_report)
        or authorization.get("deterministic_report_hash")
        != static_report.get("report_hash")
        or static_report.get("bundle_id") != bundle.get("bundle_id")
        or static_report.get("version") != manifest.get("bundle_version")
        or static_report.get("skill_activation") != EXPECTED_ACTIVATION
    ):
        raise ValueError(
            "static contract diagnostic identity or report hash does not match"
        )
    return authorization


def validate_release_authorization(
    path: Path | None,
    *,
    source_root: Path,
    manifest: dict[str, Any],
    source_tree_hash: str,
    plugin_tree_hash: str | None = None,
) -> dict[str, Any]:
    if path is None:
        raise ValueError("dist output requires matching release authorization")
    _reject_symlink_components(path)
    return _validate_release_authorization(
        _strict_json(path),
        source_root=source_root,
        manifest=manifest,
        source_tree_hash=source_tree_hash,
        plugin_tree_hash=plugin_tree_hash,
    )


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
    if skill_names != set(EXPECTED_SKILLS):
        raise ValueError("staging must contain exactly the four canonical skills")
    candidates = [path for path in staging.rglob("*") if path.is_file() or path.is_symlink()]
    if any(path.name in FORBIDDEN_PLUGIN_NAMES for path in candidates):
        raise ValueError("staging contains a forbidden MCP/app/hook file")
    records = inventory(staging, candidates)
    for record in records:
        path = staging / record["path"]
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            if _contains_forbidden_reader_marker(text):
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


def validate_plugin_build(
    plugin_root: Path,
    build_evidence_path: Path,
    *,
    source_root: Path,
    release_authorization: Path | None,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    _reject_symlink_components(plugin_root)
    _reject_symlink_components(build_evidence_path)
    plugin_root = plugin_root.resolve(strict=True)
    manifest = _strict_json(source_root / "bundle-manifest.json")
    source_records = validate_source(source_root, manifest)
    evidence = _strict_json(build_evidence_path)
    _validate_schema(
        source_root,
        "plugin-build-evidence.schema.json",
        evidence,
        "plugin build evidence",
    )
    if evidence.get("evidence_hash") != _self_hash_field(
        evidence,
        "evidence_hash",
    ):
        raise ValueError("plugin build evidence self-hash is invalid")

    plugin_records = _validate_staging(plugin_root, evidence["plugin_name"])
    versions = {
        skill_id: skill_version(plugin_root / "skills" / skill_id)
        for skill_id in EXPECTED_SKILLS
    }
    activation = {
        skill_id: skill_activation(plugin_root / "skills" / skill_id)
        for skill_id in EXPECTED_SKILLS
    }
    if (
        evidence.get("source_tree_hash") != tree_hash(source_records)
        or evidence.get("source_revision") != _source_revision(source_root)
        or evidence.get("source_file_count") != len(source_records)
        or evidence.get("plugin_tree_hash") != tree_hash(plugin_records)
        or evidence.get("plugin_file_count") != len(plugin_records)
        or evidence.get("files") != plugin_records
        or evidence.get("skill_versions") != versions
        or evidence.get("skill_activation") != activation
    ):
        raise ValueError("plugin build evidence does not match source or plugin bytes")

    output_class = evidence["output_class"]
    if output_class == "staging":
        if release_authorization is not None:
            raise ValueError("staging validation forbids release authorization")
    elif release_authorization is None:
        raise ValueError("release validation requires release authorization")
    else:
        _reject_symlink_components(release_authorization)
        if evidence.get("release_authorization_hash") != _content_hash(
            release_authorization
        ):
            raise ValueError(
                "release authorization content hash does not match build evidence"
            )
        validate_release_authorization(
            release_authorization,
            source_root=source_root,
            manifest=manifest,
            source_tree_hash=evidence["source_tree_hash"],
            plugin_tree_hash=evidence["plugin_tree_hash"],
        )
    return evidence


def _source_revision(source_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "--show-toplevel", "HEAD"],
        text=True, capture_output=True, check=False, timeout=30,
    )
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or len(lines) != 2
        or Path(lines[0]).resolve(strict=True) != source_root.resolve(strict=True)
        or re.fullmatch(r"[0-9a-f]{40}", lines[1]) is None
    ):
        raise ValueError("source root lacks a canonical Git revision")
    return lines[1]


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"symlinked output path component is forbidden: {cursor}")
        if not cursor.exists():
            break


def _rename_no_replace(source: Path, destination: Path) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise ValueError("atomic no-replace publication is unavailable") from None
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    ) == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise ValueError(f"no-overwrite destination appeared: {destination}")
    raise OSError(error, os.strerror(error), destination)


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"owned staging path is not a directory: {path}")
    return info.st_dev, info.st_ino


def _file_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"owned staging path is not a file: {path}")
    return info.st_dev, info.st_ino


def _remove_owned_tree(path: Path, identity: tuple[int, int]) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if _directory_identity(path) != identity:
        raise RuntimeError(f"owned staging inode changed: {path}")
    shutil.rmtree(path)


def _remove_owned_file(path: Path, identity: tuple[int, int]) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if _file_identity(path) != identity:
        raise RuntimeError(f"owned staging inode changed: {path}")
    path.unlink()


def _plugin_publication_matches(
    output: Path,
    identity: tuple[int, int],
    plugin_name: str,
    records: list[dict[str, Any]],
) -> bool:
    try:
        return (
            _directory_identity(output) == identity
            and _validate_staging(output, plugin_name) == records
        )
    except (OSError, ValueError):
        return False


def _marketplace_publication_matches(
    marketplace_root: Path,
    marketplace_identity: tuple[int, int],
    manifest_identity: tuple[int, int],
    manifest_bytes: bytes,
    output: Path,
    output_identity: tuple[int, int],
    plugin_name: str,
    records: list[dict[str, Any]],
) -> bool:
    manifest_path = (
        marketplace_root / ".agents" / "plugins" / "marketplace.json"
    )
    try:
        return (
            _directory_identity(marketplace_root) == marketplace_identity
            and _file_identity(manifest_path) == manifest_identity
            and manifest_path.read_bytes() == manifest_bytes
            and _plugin_publication_matches(
                output,
                output_identity,
                plugin_name,
                records,
            )
        )
    except (OSError, ValueError):
        return False


def _archive_members(
    root: Path,
    records: list[dict[str, Any]],
) -> list[ZipMember]:
    return [
        (
            str(record["path"]),
            root / str(record["path"]),
            int(str(record["mode"]), 8),
        )
        for record in records
    ]


def build(
    source_root: Path,
    output: Path,
    release_authorization: Path | None,
    evidence_output: Path,
    marketplace_root: Path | None = None,
    marketplace_archive_output: Path | None = None,
) -> dict[str, Any]:
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
    is_release = release_authorization is not None
    if is_release:
        if marketplace_root is None or marketplace_archive_output is None:
            raise ValueError(
                "release build requires canonical marketplace and archive outputs"
            )
        marketplace_root = marketplace_root.absolute()
        marketplace_archive_output = marketplace_archive_output.absolute()
        _reject_symlink_components(marketplace_root)
        _reject_symlink_components(marketplace_archive_output)
        if marketplace_root.exists() or marketplace_root.is_symlink():
            raise ValueError("marketplace root is no-overwrite")
        if (
            marketplace_archive_output.exists()
            or marketplace_archive_output.is_symlink()
        ):
            raise ValueError("marketplace archive output is no-overwrite")
        if marketplace_archive_output.suffix.lower() != ".zip":
            raise ValueError("marketplace archive output must be a .zip file")
        if marketplace_archive_output == evidence_output:
            raise ValueError("marketplace archive and build evidence must be distinct")
        if output != marketplace_root / "plugins" / template["name"]:
            raise ValueError("release plugin output must be inside the canonical marketplace")
        if evidence_output.is_relative_to(marketplace_root):
            raise ValueError("build evidence must be outside the canonical marketplace")
        if marketplace_archive_output.is_relative_to(marketplace_root):
            raise ValueError("marketplace archive must be outside the canonical marketplace")
        validate_release_authorization(
            release_authorization,
            source_root=source_root,
            manifest=manifest,
            source_tree_hash=source_tree_hash,
        )
    elif marketplace_root is not None or marketplace_archive_output is not None:
        raise ValueError("staging build forbids marketplace outputs")

    if is_release:
        assert marketplace_root is not None
        assert marketplace_archive_output is not None
        marketplace_root.parent.mkdir(parents=True, exist_ok=True)
        marketplace_archive_output.parent.mkdir(parents=True, exist_ok=True)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    staging = evidence_output.parent / "plugin-build-staging"
    if staging.exists() or staging.is_symlink():
        raise ValueError("plugin build staging path is no-overwrite")
    publish_parent = marketplace_root.parent if marketplace_root is not None else output.parent
    if publish_parent.stat().st_dev != evidence_output.parent.stat().st_dev:
        raise ValueError("plugin staging and destination must share one filesystem")
    if is_release and (
        marketplace_archive_output is None
        or marketplace_archive_output.parent.stat().st_dev
        != evidence_output.parent.stat().st_dev
    ):
        raise ValueError("marketplace archive and staging must share one filesystem")
    marketplace_staging = evidence_output.parent / "marketplace-build-staging"
    if is_release and (
        marketplace_staging.exists() or marketplace_staging.is_symlink()
    ):
        raise ValueError("marketplace build staging path is no-overwrite")
    staging.mkdir(mode=0o700)
    staging_identity = _directory_identity(staging)
    marketplace_staging_identity: tuple[int, int] | None = None
    marketplace_manifest_identity: tuple[int, int] | None = None
    marketplace_manifest_bytes: bytes | None = None
    marketplace_records: list[dict[str, Any]] | None = None
    archive_temporary: Path | None = None
    archive_identity: tuple[int, int] | None = None
    archive_published = False
    evidence_temporary: Path | None = None
    evidence_identity: tuple[int, int] | None = None
    evidence_bytes: bytes | None = None
    published = False
    plugin_records: list[dict[str, Any]] | None = None

    def publication_still_matches() -> bool:
        if plugin_records is None:
            return False
        if is_release:
            if (
                marketplace_root is None
                or marketplace_staging_identity is None
                or marketplace_manifest_identity is None
                or marketplace_manifest_bytes is None
            ):
                return False
            return _marketplace_publication_matches(
                marketplace_root,
                marketplace_staging_identity,
                marketplace_manifest_identity,
                marketplace_manifest_bytes,
                output,
                staging_identity,
                template["name"],
                plugin_records,
            )
        return _plugin_publication_matches(
            output,
            staging_identity,
            template["name"],
            plugin_records,
        )

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
        plugin_tree_hash = tree_hash(plugin_records)
        if is_release:
            validate_release_authorization(
                release_authorization,
                source_root=source_root,
                manifest=manifest,
                source_tree_hash=source_tree_hash,
                plugin_tree_hash=plugin_tree_hash,
            )
        release_authorization_hash = (
            _content_hash(release_authorization)
            if release_authorization is not None
            else None
        )
        evidence: dict[str, Any] = {
            "schema_version": "plugin-build-evidence/3.0",
            "bundle_id": _strict_json(source_root / "frontier-engineering.bundle.json")["bundle_id"],
            "bundle_version": manifest["bundle_version"],
            "skill_versions": {item["id"]: item["version"] for item in sorted(manifest["skills"], key=lambda item: item["id"])},
            "skill_activation": dict(EXPECTED_ACTIVATION),
            "source_tree_hash": source_tree_hash,
            "source_revision": _source_revision(source_root),
            "source_file_count": len(source_records),
            "plugin_tree_hash": plugin_tree_hash,
            "plugin_file_count": len(plugin_records),
            "plugin_name": template["name"],
            "output_class": "release" if is_release else "staging",
            "release_authorization_hash": release_authorization_hash,
            "activation_ceiling": manifest["activation_ceiling"],
            "files": plugin_records,
        }
        evidence["evidence_hash"] = "sha256:" + sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        _validate_schema(
            source_root,
            "plugin-build-evidence.schema.json",
            evidence,
            "plugin build evidence",
        )
        descriptor, temporary_name = tempfile.mkstemp(prefix="plugin-build-evidence-", dir=evidence_output.parent)
        evidence_temporary = Path(temporary_name)
        evidence_identity = _file_identity(evidence_temporary)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _file_identity(evidence_temporary) != evidence_identity:
            raise RuntimeError("build evidence staging inode changed")
        evidence_bytes = evidence_temporary.read_bytes()
        if is_release:
            assert marketplace_root is not None
            marketplace_staging.mkdir(mode=0o700)
            marketplace_staging_identity = _directory_identity(
                marketplace_staging
            )
            (marketplace_staging / "plugins").mkdir()
            marketplace_manifest = (
                marketplace_staging / ".agents" / "plugins" / "marketplace.json"
            )
            marketplace_manifest.parent.mkdir(parents=True)
            marketplace_manifest_bytes = (
                json.dumps(
                    CANONICAL_MARKETPLACE,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            marketplace_manifest.write_bytes(marketplace_manifest_bytes)
            marketplace_manifest_identity = _file_identity(
                marketplace_manifest
            )
            staging.rename(
                marketplace_staging / "plugins" / template["name"],
            )
            marketplace_records = inventory(
                marketplace_staging,
                [
                    path
                    for path in marketplace_staging.rglob("*")
                    if path.is_file() or path.is_symlink()
                ],
            )
            archive_descriptor, archive_name = tempfile.mkstemp(
                prefix="marketplace-archive-",
                suffix=".zip",
                dir=evidence_output.parent,
            )
            os.close(archive_descriptor)
            archive_temporary = Path(archive_name)
            archive_identity = _file_identity(archive_temporary)
            write_deterministic_zip(
                archive_temporary,
                _archive_members(marketplace_staging, marketplace_records),
            )
            os.chmod(archive_temporary, 0o644)
            if _file_identity(archive_temporary) != archive_identity:
                raise RuntimeError("marketplace archive staging inode changed")
            verify_deterministic_zip(
                archive_temporary,
                _archive_members(marketplace_staging, marketplace_records),
            )
            _rename_no_replace(marketplace_staging, marketplace_root)
        else:
            _rename_no_replace(staging, output)
        published = True
        if not publication_still_matches():
            raise ValueError("published plugin tree changed during publication")
        if is_release:
            assert marketplace_root is not None
            assert marketplace_archive_output is not None
            assert marketplace_records is not None
            assert archive_temporary is not None
            assert archive_identity is not None
            os.link(archive_temporary, marketplace_archive_output)
            archive_published = True
            if _file_identity(marketplace_archive_output) != archive_identity:
                raise RuntimeError("published marketplace archive inode changed")
            verify_deterministic_zip(
                marketplace_archive_output,
                _archive_members(marketplace_root, marketplace_records),
            )
        assert evidence_identity is not None
        assert evidence_bytes is not None
        os.link(evidence_temporary, evidence_output)
        if (
            _file_identity(evidence_output) != evidence_identity
            or evidence_output.read_bytes() != evidence_bytes
        ):
            raise ValueError("published build evidence changed")
        _remove_owned_file(evidence_temporary, evidence_identity)
        evidence_temporary = None
        if archive_temporary is not None and archive_identity is not None:
            _remove_owned_file(archive_temporary, archive_identity)
            archive_temporary = None
        if (
            _file_identity(evidence_output) != evidence_identity
            or evidence_output.read_bytes() != evidence_bytes
        ):
            raise ValueError("published build evidence readback differs")
        if not publication_still_matches():
            raise ValueError(
                "published plugin tree changed after evidence publication"
            )
        if is_release:
            assert marketplace_root is not None
            assert marketplace_archive_output is not None
            assert marketplace_records is not None
            verify_deterministic_zip(
                marketplace_archive_output,
                _archive_members(marketplace_root, marketplace_records),
            )
        return evidence
    except BaseException:
        if evidence_identity is not None and (
            evidence_output.exists() or evidence_output.is_symlink()
        ):
            try:
                if _file_identity(evidence_output) == evidence_identity:
                    _remove_owned_file(
                        evidence_output,
                        evidence_identity,
                    )
            except (OSError, ValueError):
                pass
        if (
            archive_published
            and archive_identity is not None
            and marketplace_archive_output is not None
            and (
                marketplace_archive_output.exists()
                or marketplace_archive_output.is_symlink()
            )
        ):
            try:
                if _file_identity(marketplace_archive_output) == archive_identity:
                    _remove_owned_file(
                        marketplace_archive_output,
                        archive_identity,
                    )
            except (OSError, ValueError):
                pass
        if (
            published
            and not staging.exists()
            and publication_still_matches()
        ):
            if is_release:
                assert marketplace_root is not None
                _rename_no_replace(marketplace_root, marketplace_staging)
            else:
                _rename_no_replace(output, staging)
        if is_release and marketplace_staging.exists():
            staged_plugin = (
                marketplace_staging / "plugins" / template["name"]
            )
            if staged_plugin.exists() and not staging.exists():
                _rename_no_replace(staged_plugin, staging)
            assert marketplace_staging_identity is not None
            _remove_owned_tree(
                marketplace_staging,
                marketplace_staging_identity,
            )
        if staging.exists() or staging.is_symlink():
            _remove_owned_tree(staging, staging_identity)
        if evidence_temporary is not None and evidence_identity is not None:
            _remove_owned_file(evidence_temporary, evidence_identity)
        if archive_temporary is not None and archive_identity is not None:
            _remove_owned_file(archive_temporary, archive_identity)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--release-authorization", type=Path)
    parser.add_argument("--marketplace-root", type=Path)
    parser.add_argument("--marketplace-archive-output", type=Path)
    parser.add_argument("--validate-plugin-root", type=Path)
    parser.add_argument("--build-evidence", type=Path)
    args = parser.parse_args(argv)

    validation_mode = (
        args.validate_plugin_root is not None
        or args.build_evidence is not None
    )
    if validation_mode:
        if (
            args.validate_plugin_root is None
            or args.build_evidence is None
            or args.output is not None
            or args.evidence_output is not None
            or args.marketplace_root is not None
            or args.marketplace_archive_output is not None
        ):
            return 2
        try:
            validate_plugin_build(
                args.validate_plugin_root,
                args.build_evidence,
                source_root=args.source_root,
                release_authorization=args.release_authorization,
            )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
        ):
            return 2
        return 0

    if args.output is None or args.evidence_output is None:
        print(json.dumps({
            "ok": False,
            "error": "build mode requires --output and --evidence-output",
        }, ensure_ascii=False))
        return 1
    try:
        evidence = build(
            args.source_root,
            args.output,
            args.release_authorization,
            args.evidence_output,
            args.marketplace_root,
            args.marketplace_archive_output,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "ok": True,
        "plugin_name": evidence["plugin_name"],
        "output_class": evidence["output_class"],
        "plugin_tree_hash": evidence["plugin_tree_hash"],
        "evidence_hash": evidence["evidence_hash"],
        "marketplace_archive_hash": (
            _content_hash(args.marketplace_archive_output)
            if args.marketplace_archive_output is not None
            else None
        ),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
