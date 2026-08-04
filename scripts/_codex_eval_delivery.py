"""Exact Skill delivery and workspace isolation for the Codex evaluation Host."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from _bundle_hash import inventory, tree_hash


FORCED_SKILL = re.compile(r"(?<![A-Za-z0-9_-])\$([A-Za-z0-9][A-Za-z0-9._-]{0,127})")
INFRASTRUCTURE_ROOTS = {".agents", ".git"}
MODEL_EVOLUTION_ENV_ALLOWLIST = tuple(sorted({
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "PYTHONDONTWRITEBYTECODE",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
}))
SKILL_ISOLATION_DISABLED_FEATURES = ("plugins", "multi_agent", "multi_agent_v2")


class DeliveryError(ValueError):
    """An exact catalog, treatment, or workspace delivery contract failed."""


def isolated_tool_schema_hash(codex_sha256: str) -> str:
    """Bind the model-visible tool surface to Codex and its feature isolation."""
    descriptor = {
        "codex_sha256": codex_sha256,
        "disabled_features": list(SKILL_ISOLATION_DISABLED_FEATURES),
        "schema_version": 1,
        "transport": "codex-exec-json-single-principal",
    }
    payload = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def project_command_environment(
    command: dict[str, Any],
    source: dict[str, str],
    *,
    require_model_evolution: bool = False,
) -> dict[str, str]:
    allowlist = command.get("env_allowlist")
    if (
        not isinstance(allowlist, list)
        or any(not isinstance(name, str) or not name for name in allowlist)
        or allowlist != sorted(set(allowlist))
    ):
        raise DeliveryError("Host environment allowlist is invalid")
    if require_model_evolution and allowlist != list(MODEL_EVOLUTION_ENV_ALLOWLIST):
        raise DeliveryError("model-evolution Host transport environment differs")
    environment = {name: source[name] for name in allowlist if name in source}
    if "PYTHONDONTWRITEBYTECODE" in allowlist:
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _skill_hashes(plugin_root: Path) -> dict[str, str]:
    skills_root = plugin_root / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        raise DeliveryError("plugin Skill root is invalid")
    hashes: dict[str, str] = {}
    try:
        for skill_root in sorted(skills_root.iterdir()):
            if not skill_root.is_dir() or skill_root.is_symlink():
                raise DeliveryError("plugin Skill entry is not a regular directory")
            paths = [
                path
                for path in skill_root.rglob("*")
                if path.is_file() or path.is_symlink()
            ]
            hashes[skill_root.name] = tree_hash(inventory(skill_root, paths))
    except (OSError, ValueError) as exc:
        raise DeliveryError("plugin Skill inventory is invalid") from exc
    return hashes


def validate_plugin_catalog(plugin_root: Path, manifest: dict[str, Any]) -> None:
    catalog = manifest.get("catalog")
    entries = catalog.get("entries") if isinstance(catalog, dict) else None
    if not isinstance(entries, list):
        raise DeliveryError("Host catalog is invalid")
    expected: dict[str, str] = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or not isinstance(entry.get("root_hash"), str)
            or entry["id"] in expected
        ):
            raise DeliveryError("Host catalog Skill identities are invalid")
        expected[entry["id"]] = entry["root_hash"]
    actual = _skill_hashes(plugin_root)
    if expected != actual:
        raise DeliveryError("plugin Skill bytes differ from the Host catalog")
    catalog_hash = "sha256:" + sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if catalog.get("catalog_hash") != catalog_hash:
        raise DeliveryError("Host catalog hash differs from its entries")
    try:
        plugin_paths = [
            path
            for path in plugin_root.rglob("*")
            if path.is_file() or path.is_symlink()
        ]
        plugin_hash = tree_hash(inventory(plugin_root, plugin_paths))
    except (OSError, ValueError) as exc:
        raise DeliveryError("plugin tree inventory is invalid") from exc
    identity = manifest.get("identity")
    execution = identity.get("execution") if isinstance(identity, dict) else None
    if not isinstance(execution, dict) or execution.get("skill_hash") != plugin_hash:
        raise DeliveryError("plugin tree differs from the Host identity")
    if execution.get("catalog_hash") != catalog_hash:
        raise DeliveryError("Host catalog identity differs from its entries")


def skill_isolation_argv() -> list[str]:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    skills_root = codex_home / "skills"
    disabled = (
        [path.resolve() for path in skills_root.rglob("SKILL.md") if path.is_file()]
        if skills_root.is_dir()
        else []
    )
    argv = [
        value
        for feature in SKILL_ISOLATION_DISABLED_FEATURES
        for value in ("--disable", feature)
    ]
    if disabled:
        entries = ",".join(
            "{path=" + json.dumps(str(path)) + ",enabled=false}"
            for path in sorted(set(disabled))
        )
        argv.extend(["--config", f"skills.config=[{entries}]"])
    return argv


def ensure_trusted_workspace(workspace: Path) -> None:
    trusted = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    owns_repository = False
    if not trusted.returncode:
        try:
            owns_repository = Path(trusted.stdout.strip()).resolve(strict=True) == workspace
        except OSError:
            owns_repository = False
    if not owns_repository:
        initialized = subprocess.run(
            ["git", "-C", str(workspace), "init", "-q"],
            text=True,
            capture_output=True,
            check=False,
        )
        if initialized.returncode:
            raise DeliveryError("cannot initialize a trusted evaluation workspace")


def prepare_workspace(
    workspace: Path,
    plugin_root: Path,
    *,
    exclude_skill_id: str | None,
) -> None:
    ensure_trusted_workspace(workspace)
    target = workspace / ".agents" / "skills"
    if target.exists() or target.is_symlink():
        raise DeliveryError("workspace already contains an Agent Skill catalog")
    target.mkdir(parents=True)
    for source in sorted((plugin_root / "skills").iterdir()):
        if source.name != exclude_skill_id:
            shutil.copytree(source, target / source.name, copy_function=shutil.copy2)


def treatment_delivery(
    payload: dict[str, Any], plugin_root: Path
) -> tuple[str, str, str | None]:
    treatment = payload.get("treatment")
    catalog = payload.get("catalog")
    skill_id = payload.get("subject_skill_id")
    if (
        not isinstance(treatment, dict)
        or not isinstance(catalog, list)
        or not isinstance(skill_id, str)
    ):
        raise DeliveryError("execute payload lacks a bound treatment catalog")
    catalog_ids = [row.get("id") for row in catalog if isinstance(row, dict)]
    if catalog_ids.count(skill_id) != 1 or skill_id not in _skill_hashes(plugin_root):
        raise DeliveryError("subject Skill is not uniquely bound by the catalog")
    profile = treatment.get("profile")
    allowed = {
        "baseline/skill_disabled",
        "candidate/force_loaded",
        "candidate/natural_routing",
    }
    if profile not in allowed:
        raise DeliveryError("treatment delivery profile is unsupported")
    body = None
    if profile.endswith("/force_loaded"):
        body = (plugin_root / "skills" / skill_id / "SKILL.md").read_text(
            encoding="utf-8"
        )
    return skill_id, profile, body


def forced_probe_delivery(prompt: str, plugin_root: Path) -> tuple[str, str]:
    matches = FORCED_SKILL.findall(prompt)
    if len(matches) != 1:
        raise DeliveryError("force-load probe must name exactly one Skill")
    skill_id = matches[0]
    path = plugin_root / "skills" / skill_id / "SKILL.md"
    if not path.is_file() or path.is_symlink():
        raise DeliveryError("force-load probe names an unbound Skill")
    return skill_id, path.read_text(encoding="utf-8")


def force_loaded_prompt(skill_id: str, body: str, user_prompt: str) -> str:
    digest = "sha256:" + sha256(body.encode("utf-8")).hexdigest()
    return (
        f"<force_loaded_skill id={json.dumps(skill_id)} sha256={json.dumps(digest)}>\n"
        f"{body}\n</force_loaded_skill>\n\n<user_task>\n{user_prompt}\n</user_task>"
    )


def _completed_command_items(raw: bytes) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        item = record.get("item")
        if (
            record.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "command_execution"
        ):
            items.append(item)
    return items


def observed_skill_routing(raw: bytes, plugin_root: Path) -> list[str]:
    commands = [
        item.get("command")
        for item in _completed_command_items(raw)
        if item.get("exit_code") == 0
    ]
    return [
        skill_id
        for skill_id in sorted(_skill_hashes(plugin_root))
        if any(
            isinstance(command, str)
            and f".agents/skills/{skill_id}/SKILL.md" in command
            for command in commands
        )
    ]


def observed_permission_denials(raw: bytes, process_stderr: bytes = b"") -> list[str]:
    markers = (
        "permission denied",
        "read-only file system",
        "operation not permitted",
        "writing is blocked by read-only sandbox",
        "rejected by user approval settings",
    )
    denied: list[str] = []
    for item in _completed_command_items(raw):
        output = "\n".join(
            value
            for field in ("aggregated_output", "stderr")
            if isinstance((value := item.get(field)), str)
        ).casefold()
        if item.get("exit_code") not in (None, 0) and any(
            marker in output for marker in markers
        ):
            item_id = item.get("id")
            denied.append(item_id if isinstance(item_id, str) else "command-denied")
    diagnostic = process_stderr.decode("utf-8", errors="replace").casefold()
    if any(marker in diagnostic for marker in markers):
        denied.append("process-denied")
    return sorted(set(denied))


def is_workspace_infrastructure(path: Path) -> bool:
    return bool(path.parts and path.parts[0] in INFRASTRUCTURE_ROOTS)
