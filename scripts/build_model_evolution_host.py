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
import re
import shutil
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

from _bundle_hash import inventory, tree_hash  # noqa: E402
from _codex_eval_delivery import (  # noqa: E402
    MODEL_EVOLUTION_ENV_ALLOWLIST,
    isolated_tool_schema_id,
    validate_plugin_catalog,
)
import codex_eval_host  # noqa: E402


class HostBuildError(ValueError):
    """The provisional Host cannot be derived from its exact inputs."""


CODEX_VERSION = re.compile(r"codex-cli ([0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)")


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


def _bind(argv: list[str], option: str, value: str) -> None:
    if option in argv:
        _replace(argv, option, value)
        return
    position = argv.index("--host-manifest")
    argv[position:position] = [option, value]


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


def _codex_runtime(entrypoint: Path) -> tuple[Path, str]:
    runtime = entrypoint.resolve(strict=True)
    package_version: str | None = None
    if runtime.suffix == ".js":
        package_root = runtime.parent.parent
        package = _load(package_root / "package.json")
        package_version = package.get("version")
        targets = {
            ("linux", "aarch64"): ("codex-linux-arm64", "aarch64-unknown-linux-musl"),
            ("linux", "x86_64"): ("codex-linux-x64", "x86_64-unknown-linux-musl"),
        }
        target = targets.get((sys.platform, platform.machine().lower()))
        if not isinstance(package_version, str) or target is None:
            raise HostBuildError("Codex package runtime identity is unsupported")
        package_name, target_triple = target
        runtime = (
            package_root
            / "node_modules"
            / "@openai"
            / package_name
            / "vendor"
            / target_triple
            / "bin"
            / "codex"
        ).resolve(strict=True)
    if runtime.is_symlink() or not runtime.is_file() or not os.access(runtime, os.X_OK):
        raise HostBuildError("Codex runtime executable is invalid")
    result = subprocess.run(
        [str(runtime), "--version"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    match = CODEX_VERSION.fullmatch(result.stdout.strip())
    if result.returncode or result.stderr or match is None:
        raise HostBuildError("Codex runtime version probe failed")
    version = match.group(1)
    if package_version is not None and package_version != version:
        raise HostBuildError("Codex package and runtime versions differ")
    return runtime, version


def _model_revision(model: str, codex_version: str) -> str:
    cache = _load(Path.home() / ".codex/models_cache.json")
    models = cache.get("models")
    selected = (
        [row for row in models if isinstance(row, dict) and row.get("slug") == model]
        if isinstance(models, list)
        else []
    )
    if cache.get("client_version") != codex_version or len(selected) != 1:
        raise HostBuildError("Codex model catalog differs from the bound runtime")
    return f"codex-catalog-{codex_version}"


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
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, list) or sum(
        isinstance(item, dict) and item.get("capability") == "model_grading"
        for item in capabilities
    ) != 1:
        raise HostBuildError("template must contain one model-grading fixture")
    value["capabilities"] = [
        item
        for item in capabilities
        if not isinstance(item, dict) or item.get("capability") != "model_grading"
    ]

    executable = Path(sys.executable).resolve(strict=True)
    adapter = (repository_root / "scripts/codex_eval_host.py").resolve(strict=True)
    argv[0:2] = [str(executable), str(adapter)]
    codex_path, codex_version = _codex_runtime(
        Path(argv[argv.index("--codex") + 1])
    )
    codex_hash = _hash_bytes(codex_path.read_bytes())
    code_mode_host_input = codex_path.with_name("codex-code-mode-host")
    if code_mode_host_input.is_symlink() or not code_mode_host_input.is_file():
        raise HostBuildError("Codex code-mode Host executable is invalid")
    code_mode_host = code_mode_host_input.resolve(strict=True)
    if not os.access(code_mode_host, os.X_OK):
        raise HostBuildError("Codex code-mode Host executable is invalid")
    code_mode_host_hash = _hash_bytes(code_mode_host.read_bytes())
    isolation_name = shutil.which("bwrap")
    if isolation_name is None:
        raise HostBuildError("bubblewrap isolation executable is unavailable")
    isolation_tool = Path(isolation_name).resolve(strict=True)
    isolation_hash = _hash_bytes(isolation_tool.read_bytes())
    _replace(argv, "--mode", "host")
    _replace(argv, "--codex", str(codex_path))
    _replace(argv, "--codex-sha256", codex_hash)
    _bind(argv, "--codex-version", codex_version)
    _bind(argv, "--isolation-tool", str(isolation_tool))
    _bind(argv, "--isolation-tool-sha256", isolation_hash)
    _bind(argv, "--code-mode-host", str(code_mode_host))
    _bind(argv, "--code-mode-host-sha256", code_mode_host_hash)
    _replace(argv, "--host-manifest", str(output_path.resolve()))
    _replace(argv, "--plugin-root", str(plugin_root))
    command.update({
        "argv": argv,
        "resolved_executable": str(executable),
        "executable_digest": _hash_bytes(executable.read_bytes()),
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
        entry["root_digest"] = _tree_hash(roots[skill_id])
        refreshed.append(entry)
    bundle_version = evidence.get("bundle_version")
    if not isinstance(bundle_version, str):
        raise HostBuildError("plugin build bundle version is invalid")
    catalog_id = f"frontier-engineering-{bundle_version}"
    value["catalog"] = {"catalog_id": catalog_id, "entries": refreshed}

    identity = value["identity"]
    execution = identity["execution"]
    execution["catalog_id"] = catalog_id
    execution["tool_schema_id"] = isolated_tool_schema_id(
        codex_hash,
        isolation_hash,
        code_mode_host_hash,
    )
    if execution.get("model") != argv[argv.index("--model") + 1]:
        raise HostBuildError("template model identity differs from its command")
    execution["model_revision"] = _model_revision(execution["model"], codex_version)
    execution["harness"] = "codex-cli"
    execution["harness_version"] = codex_version
    identity["adapter"].update(
        {
            "id": "codex-eval-host",
            "version": codex_eval_host.ADAPTER_VERSION,
        }
    )
    identity["host_build"] = f"codex-cli-{codex_version}"
    identity["host_version"] = codex_version
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
        artifact["digest"] = _hash_bytes(path.read_bytes())

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
    print(json.dumps({"manifest_id": value["manifest_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
