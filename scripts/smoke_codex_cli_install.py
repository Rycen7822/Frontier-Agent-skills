#!/usr/bin/env python3
"""Run a real, model-free Codex plugin install/remove smoke in an isolated HOME."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
RELEASE_VALIDATOR = SCRIPT_DIR / "build_codex_plugin.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import inventory, tree_hash  # noqa: E402
from build_codex_plugin import _strict_json, skill_activation  # noqa: E402
from smoke_codex_plugin import inspect_plugin, isolated_smoke  # noqa: E402


EXPECTED_PLUGIN = "frontier-engineering-plugin"
EXPECTED_SKILLS = [
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
]
EXPECTED_ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": True,
    "writing-plans": True,
}
MAX_CLI_OUTPUT = 1024 * 1024
SECRET_ENV_MARKERS = (
    "TOKEN", "API_KEY", "ACCESS_KEY", "SECRET_KEY", "PASSWORD", "COOKIE", "CREDENTIAL"
)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Codex CLI JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _parse_cli_json(payload: str, step: str) -> dict[str, Any]:
    if len(payload.encode("utf-8")) > MAX_CLI_OUTPUT:
        raise ValueError(f"Codex CLI output exceeds bound at {step}")
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"non-finite JSON token: {token}")),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Codex CLI did not return strict JSON at {step}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Codex CLI JSON must be an object at {step}")
    return value


def _content_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_environment(isolated_home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in SECRET_ENV_MARKERS)
        and not key.upper().startswith(("OPENAI_", "CHATGPT_", "ANTHROPIC_", "CODEX_"))
    }
    environment.update(
        {
            "HOME": str(isolated_home),
            "CODEX_HOME": str(isolated_home / ".codex"),
            "XDG_CONFIG_HOME": str(isolated_home / ".config"),
            "XDG_CACHE_HOME": str(isolated_home / ".cache"),
            "XDG_DATA_HOME": str(isolated_home / ".local" / "share"),
            "NO_COLOR": "1",
        }
    )
    return environment


def _run_json(
    codex_bin: str,
    arguments: Sequence[str],
    *,
    environment: dict[str, str],
    cwd: Path,
    step: str,
) -> tuple[dict[str, Any], int]:
    completed = subprocess.run(
        [codex_bin, *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:500]
        raise ValueError(f"Codex CLI step failed at {step} (exit {completed.returncode}): {detail}")
    return _parse_cli_json(completed.stdout, step), completed.returncode


def _run_validator(
    plugin_root: Path,
    build_evidence_path: Path,
    release_authorization_path: Path,
    *,
    environment: dict[str, str],
    cwd: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(RELEASE_VALIDATOR),
            "--source-root",
            str(ROOT),
            "--validate-plugin-root",
            str(plugin_root),
            "--build-evidence",
            str(build_evidence_path),
            "--release-authorization",
            str(release_authorization_path),
        ],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:500]
        suffix = f": {detail}" if detail else ""
        raise ValueError(
            f"repository release validation failed (exit {completed.returncode})"
            f"{suffix}"
        )


def _resolve_codex(command: str) -> str:
    resolved = shutil.which(command)
    if resolved is None:
        raise ValueError(f"Codex CLI is unavailable: {command}")
    return resolved


def _reject_symlink_components(root: Path, target: Path) -> None:
    relative = target.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlinked marketplace path component is forbidden: {relative.as_posix()}")


def _validate_marketplace(marketplace_root: Path, plugin_root: Path) -> tuple[str, dict[str, Any]]:
    root_path = marketplace_root.absolute()
    plugin_path = plugin_root.absolute()
    if root_path.is_symlink() or plugin_path.is_symlink():
        raise ValueError("marketplace/plugin roots must not be symlinks")
    root = root_path.resolve(strict=True)
    plugin = plugin_path.resolve(strict=True)
    if not plugin.is_relative_to(root):
        raise ValueError("marketplace/plugin paths must be real, non-symlinked local paths")
    marketplace_path = root_path / ".agents" / "plugins" / "marketplace.json"
    _reject_symlink_components(root_path, marketplace_path)
    _reject_symlink_components(root_path, plugin_path)
    marketplace = _strict_json(marketplace_path)
    name = marketplace.get("name")
    if not isinstance(name, str) or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name) is None:
        raise ValueError("marketplace name is invalid")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
        raise ValueError("isolated marketplace must contain exactly one plugin")
    entry = plugins[0]
    expected_source = {"source": "local", "path": f"./plugins/{EXPECTED_PLUGIN}"}
    if entry.get("name") != EXPECTED_PLUGIN or entry.get("source") != expected_source:
        raise ValueError("marketplace entry does not bind the expected local plugin")
    if entry.get("policy") != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        raise ValueError("marketplace entry policy is not the fixed isolated contract")
    if entry.get("category") != "Developer Tools":
        raise ValueError("marketplace entry category is not Developer Tools")
    expected_root = (root_path / "plugins" / EXPECTED_PLUGIN).resolve(strict=True)
    if plugin != expected_root:
        raise ValueError("plugin root differs from the marketplace source path")
    return name, marketplace


def _plugin_records(plugin_root: Path) -> list[dict[str, Any]]:
    candidates = [path for path in plugin_root.rglob("*") if path.is_file() or path.is_symlink()]
    return inventory(plugin_root, candidates)


def _expect_list_entry(
    entry: Any,
    *,
    marketplace_name: str,
    marketplace_root: Path,
    plugin_root: Path,
    bundle_version: str,
    installed: bool,
) -> None:
    if not isinstance(entry, dict):
        raise ValueError("Codex plugin list entry must be an object")
    expected = {
        "pluginId": f"{EXPECTED_PLUGIN}@{marketplace_name}",
        "name": EXPECTED_PLUGIN,
        "marketplaceName": marketplace_name,
        "version": bundle_version,
        "installed": installed,
        "enabled": installed,
        "installPolicy": "AVAILABLE",
        "authPolicy": "ON_INSTALL",
    }
    for key, value in expected.items():
        if entry.get(key) != value:
            raise ValueError(f"Codex plugin list mismatch for {key}")
    source = entry.get("source")
    marketplace_source = entry.get("marketplaceSource")
    if not isinstance(source, dict) or source.get("source") != "local":
        raise ValueError("Codex plugin list did not preserve the local plugin source")
    if Path(str(source.get("path"))).resolve(strict=True) != plugin_root.resolve(strict=True):
        raise ValueError("Codex plugin list resolved a different plugin path")
    if not isinstance(marketplace_source, dict) or marketplace_source.get("sourceType") != "local":
        raise ValueError("Codex plugin list did not preserve the local marketplace source")
    if Path(str(marketplace_source.get("source"))).resolve(strict=True) != marketplace_root.resolve(strict=True):
        raise ValueError("Codex plugin list resolved a different marketplace root")


def _expect_single_plugin_list(
    payload: dict[str, Any],
    *,
    marketplace_name: str,
    marketplace_root: Path,
    plugin_root: Path,
    bundle_version: str,
    installed: bool,
) -> None:
    installed_items = payload.get("installed")
    available_items = payload.get("available")
    if not isinstance(installed_items, list) or not isinstance(available_items, list):
        raise ValueError("Codex plugin list lacks installed/available arrays")
    selected = installed_items if installed else available_items
    other = available_items if installed else installed_items
    if len(selected) != 1 or other:
        raise ValueError("Codex plugin list did not contain exactly one plugin in the expected state")
    _expect_list_entry(
        selected[0],
        marketplace_name=marketplace_name,
        marketplace_root=marketplace_root,
        plugin_root=plugin_root,
        bundle_version=bundle_version,
        installed=installed,
    )


def _verify_static_evidence(static_path: Path, build: dict[str, Any]) -> dict[str, Any]:
    static = _strict_json(static_path)
    expected = {
        "schema_version": "static-plugin-smoke/4.0",
        "bundle_id": build.get("bundle_id"),
        "bundle_version": build.get("bundle_version"),
        "plugin_name": EXPECTED_PLUGIN,
        "plugin_tree_hash": build.get("plugin_tree_hash"),
        "activation_ceiling": build.get("activation_ceiling"),
        "actual_codex_cli_install": False,
        "model_invoked": False,
        "remote_writes": False,
        "isolated_install_discovery": True,
        "uninstall_clean": True,
    }
    for key, value in expected.items():
        if static.get(key) != value:
            raise ValueError(f"static smoke evidence mismatch for {key}")
    skills = static.get("discovered_skills")
    if not isinstance(skills, dict) or sorted(skills) != EXPECTED_SKILLS:
        raise ValueError("static smoke evidence does not discover exactly the expected skills")
    if any(
        not isinstance(skills[skill_id], dict)
        or skills[skill_id].get("implicit_eligible") is not EXPECTED_ACTIVATION[skill_id]
        for skill_id in EXPECTED_SKILLS
    ):
        raise ValueError("static smoke evidence does not match the exact mixed activation matrix")
    return static


def run_cli_smoke(
    plugin_root: Path,
    build_evidence_path: Path,
    release_authorization_path: Path,
    static_smoke_path: Path,
    marketplace_root: Path,
    work_root: Path,
    codex_command: str = "codex",
) -> dict[str, Any]:
    if work_root.is_symlink():
        raise ValueError("work root must not be a symlink")
    marketplace_name, _ = _validate_marketplace(marketplace_root, plugin_root)
    plugin_root = plugin_root.resolve(strict=True)
    marketplace_root = marketplace_root.resolve(strict=True)
    work_root = work_root.resolve(strict=True)
    if not work_root.is_dir():
        raise ValueError("work root must be a real directory")
    build = _strict_json(build_evidence_path)
    if (
        build.get("schema_version") != "plugin-build-evidence/4.0"
        or build.get("plugin_name") != EXPECTED_PLUGIN
        or build.get("activation_ceiling") != "implicit_local_pilot"
        or build.get("skill_activation") != EXPECTED_ACTIVATION
    ):
        raise ValueError("CLI smoke build evidence identity is invalid")
    static = _verify_static_evidence(static_smoke_path, build)
    if static != isolated_smoke(plugin_root, build_evidence_path):
        raise ValueError("static smoke evidence is not reproducible from the staged plugin")
    first_inspection = inspect_plugin(plugin_root, build_evidence_path)
    source_records = _plugin_records(plugin_root)
    if tree_hash(source_records) != build.get("plugin_tree_hash"):
        raise ValueError("source plugin tree differs from build evidence")
    release_authorization_path = release_authorization_path.resolve(strict=True)
    if not RELEASE_VALIDATOR.is_file() or RELEASE_VALIDATOR.is_symlink():
        raise ValueError("repository release validator is missing or symlinked")
    codex_bin = _resolve_codex(codex_command)
    marketplace_manifest = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    marketplace_content_hash = _content_hash(marketplace_manifest)

    commands: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="frontier-codex-home-", dir=work_root) as directory:
        isolated_home = Path(directory).resolve(strict=True)
        (isolated_home / ".codex").mkdir(mode=0o700)
        environment = _safe_environment(isolated_home)
        _run_validator(
            plugin_root,
            build_evidence_path,
            release_authorization_path,
            environment=environment,
            cwd=marketplace_root,
        )
        version = subprocess.run(
            [codex_bin, "--version"],
            cwd=marketplace_root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        codex_version = version.stdout.strip()
        if version.returncode != 0 or not codex_version or len(codex_version) > 256 or "\n" in codex_version:
            raise ValueError("Codex CLI version probe failed")

        added, commands["marketplace_add"] = _run_json(
            codex_bin,
            ["plugin", "marketplace", "add", str(marketplace_root), "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="marketplace_add",
        )
        if added.get("marketplaceName") != marketplace_name or added.get("alreadyAdded") is not False:
            raise ValueError("Codex marketplace add did not register a fresh isolated marketplace")
        if Path(str(added.get("installedRoot"))).resolve(strict=True) != marketplace_root:
            raise ValueError("Codex marketplace add installed an unexpected root")

        available, commands["list_available"] = _run_json(
            codex_bin,
            ["plugin", "list", "--marketplace", marketplace_name, "--available", "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="list_available",
        )
        _expect_single_plugin_list(
            available,
            marketplace_name=marketplace_name,
            marketplace_root=marketplace_root,
            plugin_root=plugin_root,
            bundle_version=str(build.get("bundle_version")),
            installed=False,
        )

        installed, commands["plugin_add"] = _run_json(
            codex_bin,
            ["plugin", "add", f"{EXPECTED_PLUGIN}@{marketplace_name}", "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="plugin_add",
        )
        expected_identity = {
            "pluginId": f"{EXPECTED_PLUGIN}@{marketplace_name}",
            "name": EXPECTED_PLUGIN,
            "marketplaceName": marketplace_name,
            "version": build.get("bundle_version"),
            "authPolicy": "ON_INSTALL",
        }
        for key, value in expected_identity.items():
            if installed.get(key) != value:
                raise ValueError(f"Codex plugin add mismatch for {key}")
        cache_root = (isolated_home / ".codex" / "plugins" / "cache").resolve(strict=True)
        installed_root = Path(str(installed.get("installedPath"))).resolve(strict=True)
        if not installed_root.is_relative_to(cache_root):
            raise ValueError("Codex installed the plugin outside the isolated cache")
        installed_records = _plugin_records(installed_root)
        installed_tree_hash = tree_hash(installed_records)
        if installed_records != source_records or installed_tree_hash != build.get("plugin_tree_hash"):
            raise ValueError("installed cache bytes differ from the staged plugin")
        installed_activation = {
            skill_id: skill_activation(installed_root / "skills" / skill_id)
            for skill_id in EXPECTED_SKILLS
        }
        if installed_activation != build.get("skill_activation"):
            raise ValueError("installed skill activation differs from build evidence")
        _run_validator(
            installed_root,
            build_evidence_path,
            release_authorization_path,
            environment=environment,
            cwd=marketplace_root,
        )

        listed, commands["list_installed"] = _run_json(
            codex_bin,
            ["plugin", "list", "--marketplace", marketplace_name, "--available", "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="list_installed",
        )
        _expect_single_plugin_list(
            listed,
            marketplace_name=marketplace_name,
            marketplace_root=marketplace_root,
            plugin_root=plugin_root,
            bundle_version=str(build.get("bundle_version")),
            installed=True,
        )

        removed, commands["plugin_remove"] = _run_json(
            codex_bin,
            ["plugin", "remove", f"{EXPECTED_PLUGIN}@{marketplace_name}", "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="plugin_remove",
        )
        for key, value in {
            "pluginId": f"{EXPECTED_PLUGIN}@{marketplace_name}",
            "name": EXPECTED_PLUGIN,
            "marketplaceName": marketplace_name,
        }.items():
            if removed.get(key) != value:
                raise ValueError(f"Codex plugin remove mismatch for {key}")

        after_remove, commands["list_after_remove"] = _run_json(
            codex_bin,
            ["plugin", "list", "--marketplace", marketplace_name, "--available", "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="list_after_remove",
        )
        _expect_single_plugin_list(
            after_remove,
            marketplace_name=marketplace_name,
            marketplace_root=marketplace_root,
            plugin_root=plugin_root,
            bundle_version=str(build.get("bundle_version")),
            installed=False,
        )
        uninstall_clean = not installed_root.exists()
        if not uninstall_clean:
            raise ValueError("Codex plugin remove left the installed cache behind")

        marketplace_removed, commands["marketplace_remove"] = _run_json(
            codex_bin,
            ["plugin", "marketplace", "remove", marketplace_name, "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="marketplace_remove",
        )
        if marketplace_removed.get("marketplaceName") != marketplace_name:
            raise ValueError("Codex marketplace remove returned the wrong identity")

        final_marketplaces, commands["marketplace_list_final"] = _run_json(
            codex_bin,
            ["plugin", "marketplace", "list", "--json"],
            environment=environment,
            cwd=marketplace_root,
            step="marketplace_list_final",
        )
        if final_marketplaces.get("marketplaces") != []:
            raise ValueError("isolated Codex HOME retained a configured marketplace")
        config_path = isolated_home / ".codex" / "config.toml"
        config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        if len(config_text.encode("utf-8")) > MAX_CLI_OUTPUT:
            raise ValueError("isolated Codex config exceeds bound")
        final_config_clean = EXPECTED_PLUGIN not in config_text and marketplace_name not in config_text
        if not final_config_clean:
            raise ValueError("isolated Codex config retained plugin or marketplace state")

        source_unchanged = (
            inspect_plugin(plugin_root, build_evidence_path) == first_inspection
            and _plugin_records(plugin_root) == source_records
        )
        if not source_unchanged:
            raise ValueError("CLI smoke modified the staged source plugin")
        marketplace_source_unchanged = _content_hash(marketplace_manifest) == marketplace_content_hash
        if not marketplace_source_unchanged:
            raise ValueError("CLI smoke modified the marketplace source manifest")

        activation_ceiling = build["activation_ceiling"]
        output_class = build.get("output_class")
        release_binding = build.get("release_authorization_digest")
        if output_class == "staging" and release_binding is not None:
            raise ValueError("staging build must not bind release authorization")
        if output_class == "release" and not (
            isinstance(release_binding, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", release_binding)
        ):
            raise ValueError("release build must bind the release authorization digest")
        if output_class not in {"staging", "release"}:
            raise ValueError("build evidence output class is invalid")
        release_eligible = output_class == "release"
        result: dict[str, Any] = {
            "schema_version": "cli-install-smoke/4.0",
            "bundle_id": build["bundle_id"],
            "plugin_name": EXPECTED_PLUGIN,
            "bundle_version": build["bundle_version"],
            "plugin_tree_hash": build["plugin_tree_hash"],
            "activation_ceiling": activation_ceiling,
            "release_gate": "passed" if release_eligible else "blocked_prerequisites",
            "blocking_prerequisites": [] if release_eligible else [
                "release_authorization",
                "signed_clean_source_revision",
            ],
            "release_eligible": release_eligible,
            "source_revision_verified": release_eligible,
            "marketplace_name": marketplace_name,
            "codex_cli_version": codex_version,
            "actual_codex_cli_install": True,
            "model_invoked": False,
            "remote_writes": False,
            "credential_environment_inherited": False,
            "marketplace_layout_valid": True,
            "marketplace_added": True,
            "discovered_before_install": True,
            "installed_enabled": True,
            "skill_activation": installed_activation,
            "installed_tree_hash": installed_tree_hash,
            "cache_matches_staging": True,
            "staged_validator_passed": True,
            "installed_validator_passed": True,
            "source_unchanged": True,
            "marketplace_source_unchanged": marketplace_source_unchanged,
            "uninstall_clean": uninstall_clean,
            "marketplace_removed": True,
            "final_config_clean": final_config_clean,
            "discovered_skills": sorted(static["discovered_skills"]),
            "explicit_skill_invocation": "not_run_model_free",
            "implicit_route_invocation": "not_run_model_free",
            "commands": commands,
        }
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--build-evidence", type=Path, required=True)
    parser.add_argument("--release-authorization", type=Path, required=True)
    parser.add_argument("--static-smoke", type=Path, required=True)
    parser.add_argument("--marketplace-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_cli_smoke(
            args.plugin_root,
            args.build_evidence,
            args.release_authorization,
            args.static_smoke,
            args.marketplace_root,
            args.work_root,
            args.codex_bin,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "bundle_id": result["bundle_id"],
                "bundle_version": result["bundle_version"],
                "installed": result["actual_codex_cli_install"],
                "source_installed_equal": result["cache_matches_staging"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
