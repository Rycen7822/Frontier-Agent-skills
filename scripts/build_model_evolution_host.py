#!/usr/bin/env python3
"""Build one exact provisional Codex Host manifest for a campaign staging tree."""

from __future__ import annotations

import argparse
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

from _bundle_hash import inventory, tree_hash  # noqa: E402
from _codex_eval_delivery import (  # noqa: E402
    MODEL_EVOLUTION_ENV_ALLOWLIST,
    validate_plugin_catalog,
)
import codex_eval_host  # noqa: E402


class HostBuildError(ValueError):
    """The provisional Host cannot be derived from its exact inputs."""


def _hash_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HostBuildError(f"required input is invalid: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise HostBuildError(f"required input is not an object: {path.name}")
    return value


def _replace(argv: list[str], option: str, value: str) -> None:
    positions = [index for index, item in enumerate(argv) if item == option]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise HostBuildError(f"template must bind {option} exactly once")
    argv[positions[0] + 1] = value


def _git(repository_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise HostBuildError(f"git {' '.join(args)} failed")
    return result.stdout.strip()


def _repository_identity(repository_root: Path) -> dict[str, Any]:
    return {
        "dirty": bool(_git(repository_root, "status", "--porcelain", "--untracked-files=no")),
        "revision": _git(repository_root, "rev-parse", "HEAD"),
        "tree": _git(repository_root, "rev-parse", "HEAD^{tree}"),
        "worktree": str(repository_root.resolve(strict=True)),
    }


def _tree_hash(root: Path) -> str:
    paths = [path for path in root.rglob("*") if path.is_file() or path.is_symlink()]
    return tree_hash(inventory(root, paths))


def build_host(
    *,
    repository_root: Path,
    template_path: Path,
    plugin_root: Path,
    plugin_build_path: Path,
    output_path: Path,
    manifest_id: str,
    session_id: str,
) -> dict[str, Any]:
    repository_root = repository_root.resolve(strict=True)
    plugin_root = plugin_root.resolve(strict=True)
    template = _load(template_path.resolve(strict=True))
    evidence = _load(plugin_build_path.resolve(strict=True))
    value = copy.deepcopy(template)
    command = value.get("command")
    argv = command.get("argv") if isinstance(command, dict) else None
    if not isinstance(argv, list) or len(argv) < 2:
        raise HostBuildError("template Host command is invalid")

    executable = Path(sys.executable).resolve(strict=True)
    adapter = (repository_root / "scripts/codex_eval_host.py").resolve(strict=True)
    argv[0:2] = [str(executable), str(adapter)]
    codex_path = Path(argv[argv.index("--codex") + 1]).resolve(strict=True)
    codex_hash = _hash_bytes(codex_path.read_bytes())
    _replace(argv, "--mode", "host")
    _replace(argv, "--codex", str(codex_path))
    _replace(argv, "--codex-sha256", codex_hash)
    _replace(argv, "--host-manifest", str(output_path.resolve()))
    _replace(argv, "--plugin-root", str(plugin_root))
    command.update({
        "argv": argv,
        "resolved_executable": str(executable),
        "executable_sha256": _hash_bytes(executable.read_bytes()),
        "env_allowlist": list(MODEL_EVOLUTION_ENV_ALLOWLIST),
    })

    entries = value.get("catalog", {}).get("entries")
    if not isinstance(entries, list):
        raise HostBuildError("template Host catalog is invalid")
    versions = evidence.get("skill_versions")
    roots = {path.name: path for path in (plugin_root / "skills").iterdir() if path.is_dir()}
    if not isinstance(versions, dict) or set(versions) != set(roots):
        raise HostBuildError("plugin build Skill versions differ from staging")
    by_id = {entry.get("id"): entry for entry in entries if isinstance(entry, dict)}
    if set(by_id) != set(roots) or len(by_id) != len(entries):
        raise HostBuildError("template Host catalog differs from staged Skills")
    refreshed = []
    for skill_id in sorted(roots):
        entry = copy.deepcopy(by_id[skill_id])
        entry["version"] = versions[skill_id]
        entry["root_hash"] = _tree_hash(roots[skill_id])
        refreshed.append(entry)
    catalog_hash = _hash_bytes(_canonical_bytes(refreshed))
    value["catalog"] = {"entries": refreshed, "catalog_hash": catalog_hash}

    identity = value["identity"]
    execution = identity["execution"]
    execution["catalog_hash"] = catalog_hash
    execution["skill_hash"] = _tree_hash(plugin_root)
    if execution.get("model") != argv[argv.index("--model") + 1]:
        raise HostBuildError("template model identity differs from its command")
    identity["adapter"].update(
        {
            "sha256": _hash_bytes(adapter.read_bytes()),
            "version": codex_eval_host.ADAPTER_VERSION,
        }
    )
    identity["host_build"] = codex_hash
    repository_identity = _repository_identity(repository_root)
    if repository_identity["dirty"]:
        raise HostBuildError("repository has tracked changes")
    identity["repository"] = repository_identity
    identity["platform"] = {
        "os": platform.platform(),
        "runtime": f"python-{platform.python_version()}",
    }
    identity["session"] = {"session_id": session_id, "topology": "single"}
    value["manifest_id"] = manifest_id

    for probe in [value.get("reset", {}).get("probe"), *[
        row.get("probe") for row in value.get("capabilities", []) if isinstance(row, dict)
    ]]:
        artifact = probe.get("artifact") if isinstance(probe, dict) else None
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise HostBuildError("template probe artifact binding is invalid")
        path = (repository_root / artifact["path"]).resolve(strict=True)
        if not path.is_relative_to(repository_root) or path.is_symlink() or not path.is_file():
            raise HostBuildError("template probe artifact escapes the repository")
        artifact["sha256"] = _hash_bytes(path.read_bytes())

    value["manifest_hash"] = _hash_bytes(_canonical_bytes({
        key: item for key, item in value.items() if key != "manifest_hash"
    }))
    validate_plugin_catalog(plugin_root, value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with output_path.open("xb") as handle:
            created = True
            handle.write(_canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        codex_eval_host.validate_bound_manifest(output_path, plugin_root)
    except FileExistsError as exc:
        raise HostBuildError(f"refusing to replace Host manifest: {output_path.name}") from exc
    except Exception:
        if created:
            output_path.unlink(missing_ok=True)
        raise
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--plugin-build-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()
    try:
        value = build_host(
            repository_root=args.repository_root,
            template_path=args.template,
            plugin_root=args.plugin_root,
            plugin_build_path=args.plugin_build_evidence,
            output_path=args.output,
            manifest_id=args.manifest_id,
            session_id=args.session_id,
        )
    except (HostBuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"build_model_evolution_host: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"manifest_hash": value["manifest_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
