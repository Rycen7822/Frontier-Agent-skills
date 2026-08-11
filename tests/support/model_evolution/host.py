from __future__ import annotations

import shutil
import stat
import sys
import textwrap
from pathlib import Path
from typing import Any

from _codex_eval_delivery import (
    MODEL_EVOLUTION_ENV_ALLOWLIST,
    isolated_tool_schema_id,
)
from _model_evolution_contract import SKILL_IDS
from codex_eval_host import ADAPTER_VERSION
from support.model_evolution.documents import host_manifest
from support.model_evolution.repository import (
    FIXED_COMMIT,
    FIXED_TREE,
    assemble_campaign,
    campaign_layout,
    copy_product_files,
    file_hash,
    materialize_probe_set,
    materialize_sentinel,
    root_hash,
    write_json,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = SOURCE_ROOT / "scripts/codex_eval_host.py"

FAKE_CODEX = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    import sys

    prompt = sys.stdin.read()
    records = [
        {"type": "thread.started", "thread_id": "019aa111-1111-7111-8111-111111111111"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {
            "id": "message-1", "type": "agent_message", "text": "fixture complete",
        }},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}},
    ]
    for record in records:
        print(json.dumps(record, separators=(",", ":")), flush=True)
    """
)


def _materialize_fake_host(
    repository_root: Path, campaign_root: Path, plugin_root: Path
) -> Path:
    fake = repository_root / "fixtures/fake-codex"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    code_mode_host = fake.with_name("codex-code-mode-host")
    shutil.copyfile(fake, code_mode_host)
    code_mode_host.chmod(code_mode_host.stat().st_mode | stat.S_IXUSR)
    isolation_name = shutil.which("bwrap")
    if isolation_name is None:
        raise RuntimeError("bubblewrap fixture dependency is unavailable")
    isolation_tool = Path(isolation_name).resolve(strict=True)
    isolation_hash = file_hash(isolation_tool)
    host_path = campaign_root / "inputs/target-provisional-host.json"
    host = host_manifest()
    host["identity"]["adapter"] = {
        "id": "codex-eval-host",
        "version": ADAPTER_VERSION,
    }
    host["identity"]["host_build"] = "codex-cli-0.0.0"
    host["identity"]["host_version"] = "0.0.0"
    host["identity"]["execution"]["model"] = "fixture-model"
    host["identity"]["execution"]["harness"] = "codex-cli"
    host["identity"]["execution"]["harness_version"] = "0.0.0"
    host["identity"]["execution"]["model_revision"] = "codex-catalog-0.0.0"
    host["identity"]["repository"] = {
        "dirty": False,
        "revision": FIXED_COMMIT,
        "tree": FIXED_TREE,
        "worktree": str(repository_root.resolve()),
    }
    host["command"].update(
        {
            "argv": [
                sys.executable,
                str(ADAPTER),
                "--mode",
                "host",
                "--codex",
                str(fake),
                "--codex-sha256",
                file_hash(fake),
                "--codex-version",
                "0.0.0",
                "--isolation-tool",
                str(isolation_tool),
                "--isolation-tool-sha256",
                isolation_hash,
                "--code-mode-host",
                str(code_mode_host),
                "--code-mode-host-sha256",
                file_hash(code_mode_host),
                "--host-manifest",
                str(host_path),
                "--model",
                "fixture-model",
                "--effort",
                "high",
                "--profile",
                "fixture-profile",
                "--sandbox",
                "read-only",
                "--timeout",
                "5",
                "--plugin-root",
                str(plugin_root),
            ],
            "resolved_executable": str(Path(sys.executable).resolve()),
            "executable_digest": file_hash(Path(sys.executable).resolve()),
            "env_allowlist": list(MODEL_EVOLUTION_ENV_ALLOWLIST),
        }
    )
    prototype = host["catalog"]["entries"][0]
    host["catalog"]["entries"] = [
        {
            **prototype,
            "id": skill_root.name,
            "name": skill_root.name,
            "version": "1.0.0",
            "root_digest": root_hash(skill_root),
        }
        for skill_root in sorted((plugin_root / "skills").iterdir())
    ]
    host["catalog"]["catalog_id"] = "frontier-engineering-catalog"
    host["identity"]["execution"]["catalog_id"] = "frontier-engineering-catalog"
    host["identity"]["execution"]["skill_id"] = "frontier-engineering-plugin"
    host["identity"]["execution"].update(
        {
            "tool_schema_id": isolated_tool_schema_id(
                file_hash(fake),
                isolation_hash,
                file_hash(code_mode_host),
            ),
        }
    )
    host["capabilities"][0]["probe"]["status"] = "unknown"
    return write_json(host_path, host)


def _materialize_plugin_staging(campaign_root: Path) -> tuple[Path, Path]:
    plugin_root = campaign_root / "staging/frontier-engineering-plugin"
    (plugin_root / ".codex-plugin").mkdir(parents=True)
    (plugin_root / ".codex-plugin/plugin.json").write_text("{}\n", encoding="utf-8")
    for skill_id in SKILL_IDS:
        shutil.copytree(
            SOURCE_ROOT / skill_id,
            plugin_root / "skills" / skill_id,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", ".closure", ".workflow", "dist"
            ),
        )
    plugin_tree_hash = root_hash(plugin_root)
    evidence = {
        "schema_version": "plugin-build-evidence/3.0",
        "source_revision": FIXED_COMMIT,
        "plugin_tree_hash": plugin_tree_hash,
    }
    return plugin_root, write_json(
        campaign_root / "inputs/plugin-build-evidence.json",
        evidence,
    )


def materialize_campaign(root: Path) -> dict[str, Any]:
    repository_root, campaign_root = campaign_layout(root)
    product = copy_product_files(repository_root)
    plugin_root, plugin_build = _materialize_plugin_staging(campaign_root)
    host = _materialize_fake_host(repository_root, campaign_root, plugin_root)
    probe_set = materialize_probe_set(repository_root, campaign_root)
    sentinel = materialize_sentinel(repository_root, campaign_root)
    return assemble_campaign(
        repository_root=repository_root,
        campaign_root=campaign_root,
        product=product,
        plugin_root=plugin_root,
        plugin_build=plugin_build,
        host=host,
        probe_set=probe_set,
        sentinel=sentinel,
    )
