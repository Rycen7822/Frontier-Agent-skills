from __future__ import annotations

import copy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import stat
import sys
import textwrap
from typing import Any

from _bundle_hash import inventory, tree_hash
from _codex_eval_delivery import (
    MODEL_EVOLUTION_ENV_ALLOWLIST,
    isolated_tool_schema_hash,
)
from codex_eval_host import adapter_source_hash
from _model_evolution_contract import (
    SKILL_IDS,
    build_initial_campaign,
    make_binding,
    with_self_hash,
)
from _model_evolution_state import CampaignStore
from skill_evaluator_test_support import canonical_hash, make_v5_schema_examples


SOURCE_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = SOURCE_ROOT / "scripts/codex_eval_host.py"
FIXED_COMMIT = "1" * 40
FIXED_TREE = "2" * 40

FAKE_CODEX = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json
    from pathlib import Path
    import sys

    executable = Path(__file__).resolve()
    calls = Path(str(executable) + ".calls.jsonl")
    prompt = sys.stdin.read()
    with calls.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\\n")
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


def write_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def repository_binding(
    path: Path, repository_root: Path, campaign_root: Path
) -> dict[str, str]:
    return make_binding(
        path,
        root="repository",
        repository_root=repository_root,
        campaign_root=campaign_root,
    )


def _copy_product_files(repository_root: Path) -> dict[str, Path]:
    paths = {
        "bundle_manifest": repository_root / "bundle-manifest.json",
        "bundle_build": repository_root / "frontier-engineering.bundle.json",
        "static_report": repository_root / "evaluation/static-contract-diagnostic.json",
    }
    for name, target in paths.items():
        source = {
            "bundle_manifest": SOURCE_ROOT / "bundle-manifest.json",
            "bundle_build": SOURCE_ROOT / "frontier-engineering.bundle.json",
            "static_report": SOURCE_ROOT / "evaluation/static-contract-diagnostic.json",
        }[name]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return paths


def _root_hash(root: Path) -> str:
    members = [path for path in root.rglob("*") if path.is_file() or path.is_symlink()]
    return tree_hash(inventory(root, members))


def _materialize_fake_host(
    repository_root: Path, campaign_root: Path, plugin_root: Path
) -> Path:
    fake = repository_root / "fixtures/fake-codex"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    host_path = campaign_root / "inputs/target-provisional-host.json"
    host = copy.deepcopy(make_v5_schema_examples()["host-manifest-v1.schema.json"])
    host["identity"]["adapter"].update(
        {
            "id": "codex-eval-host",
            "version": "1",
            "sha256": adapter_source_hash(),
        }
    )
    host["identity"]["execution"]["model"] = "fixture-model"
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
                "--host-manifest",
                str(host_path),
                "--model",
                "fixture-model",
                "--effort",
                "high",
                "--profile",
                "fixture-profile",
                "--sandbox",
                "workspace-write",
                "--timeout",
                "5",
                "--plugin-root",
                str(plugin_root),
            ],
            "resolved_executable": str(Path(sys.executable).resolve()),
            "executable_sha256": file_hash(Path(sys.executable).resolve()),
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
            "root_hash": _root_hash(skill_root),
        }
        for skill_root in sorted((plugin_root / "skills").iterdir())
    ]
    host["catalog"]["catalog_hash"] = canonical_hash(
        host["catalog"]["entries"]
    )
    host["identity"]["execution"]["catalog_hash"] = host["catalog"][
        "catalog_hash"
    ]
    host["identity"]["execution"]["skill_hash"] = _root_hash(plugin_root)
    host["identity"]["execution"]["tool_schema_hash"] = isolated_tool_schema_hash(
        file_hash(fake)
    )
    host["capabilities"][0]["probe"]["status"] = "unknown"
    host["manifest_hash"] = canonical_hash(
        {key: value for key, value in host.items() if key != "manifest_hash"}
    )
    return write_json(host_path, host)


def _materialize_plugin_staging(campaign_root: Path) -> tuple[Path, Path]:
    plugin_root = campaign_root / "staging/frontier-engineering-plugin"
    (plugin_root / ".codex-plugin").mkdir(parents=True)
    (plugin_root / ".codex-plugin/plugin.json").write_text(
        "{}\n", encoding="utf-8"
    )
    for skill_id in SKILL_IDS:
        shutil.copytree(
            SOURCE_ROOT / skill_id,
            plugin_root / "skills" / skill_id,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".pytest_cache", ".closure", ".workflow", "dist"
            ),
        )
    plugin_tree_hash = _root_hash(plugin_root)
    evidence = with_self_hash(
        {
            "schema_version": "plugin-build-evidence/3.0",
            "source_revision": FIXED_COMMIT,
            "plugin_tree_hash": plugin_tree_hash,
        },
        "evidence_hash",
    )
    return plugin_root, write_json(
        campaign_root / "inputs/plugin-build-evidence.json",
        evidence,
    )


def _materialize_probe_set(repository_root: Path, campaign_root: Path) -> Path:
    fixture = repository_root / "fixtures/probe.txt"
    fixture.write_text("inert probe fixture\n", encoding="utf-8")
    probe_set = with_self_hash(
        {
            "schema_version": "model-evolution-interaction-probes/1",
            "probe_set_id": "codex-host-probes-v1",
            "adapter_protocol_version": "codex-interaction-probe/1.0",
            "probes": [
                {
                    "probe_id": "force-load",
                    "capability": "force_load",
                    "prompt": "$skill-evaluator Return a short inert completion.",
                    "fixture": repository_binding(
                        fixture, repository_root, campaign_root
                    ),
                    "sandbox": "workspace-write",
                    "network": "denied",
                    "required_observations": ["thread.started", "turn.completed"],
                    "request_ceiling": 1,
                }
            ],
        },
        "probe_set_hash",
    )
    return write_json(repository_root / "codex-interaction-probes-v1.json", probe_set)


def _materialize_sentinel(repository_root: Path, campaign_root: Path) -> Path:
    fixture = repository_root / "sentinels/shared-fixture.txt"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("sentinel fixture\n", encoding="utf-8")
    binding = repository_binding(fixture, repository_root, campaign_root)
    requests = write_json(repository_root / "sentinels/requests.jsonl", {})
    request_binding = repository_binding(requests, repository_root, campaign_root)
    skills = {
        skill_id: {
            "critical_bucket_id": f"{skill_id}-critical",
            "spec_template": binding,
            "public_scenarios": request_binding,
            "calibration_gold": request_binding,
            "calibration_request_ceiling": 1,
            "fixture_roots": [binding],
            "verifier_roots": [binding],
            "required_coverage_tags": ["critical"],
            "protected_case_ids": [f"{skill_id}-protected"],
            "external_holdout_contract_id": f"{skill_id}-holdout",
            "holdout_case_ceiling": 2,
        }
        for skill_id in SKILL_IDS
    }
    sentinel = with_self_hash(
        {
            "schema_version": "model-evolution-sentinel-index/1",
            "sentinel_id": "frontier-sentinel-v1",
            "skills": skills,
        },
        "sentinel_hash",
    )
    return write_json(repository_root / "sentinel-index-v1.json", sentinel)


def materialize_campaign(root: Path) -> dict[str, Any]:
    repository_root = root / "repository"
    campaign_root = root / "campaign"
    repository_root.mkdir(parents=True)
    campaign_root.mkdir(parents=True)
    product = _copy_product_files(repository_root)
    plugin_root, plugin_build = _materialize_plugin_staging(campaign_root)
    host = _materialize_fake_host(repository_root, campaign_root, plugin_root)
    probe_set = _materialize_probe_set(repository_root, campaign_root)
    sentinel = _materialize_sentinel(repository_root, campaign_root)
    bindings = {
        name: repository_binding(path, repository_root, campaign_root)
        for name, path in {
            **product,
            "probe_set": probe_set,
            "sentinel": sentinel,
        }.items()
    }
    bindings["host"] = make_binding(
        host,
        root="campaign",
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    bindings["plugin_build"] = make_binding(
        plugin_build,
        root="campaign",
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    values = {name: json.loads(path.read_text()) for name, path in product.items()}
    campaign = build_initial_campaign(
        campaign_id="campaign-fixture",
        git_identity={"commit": FIXED_COMMIT, "tree": FIXED_TREE},
        bundle_manifest=values["bundle_manifest"],
        bundle_manifest_binding=bindings["bundle_manifest"],
        bundle_build=values["bundle_build"],
        bundle_build_binding=bindings["bundle_build"],
        plugin_build_binding=bindings["plugin_build"],
        plugin_root=plugin_root.relative_to(campaign_root).as_posix(),
        plugin_tree_hash=json.loads(plugin_build.read_text())["plugin_tree_hash"],
        calibration_requests=4,
        static_report=values["static_report"],
        static_report_binding=bindings["static_report"],
        target_host_binding=bindings["host"],
        probe_set_binding=bindings["probe_set"],
        sentinel_binding=bindings["sentinel"],
        ceilings={
            "provider_requests": 40,
            "execute": 24,
            "model_grade": 12,
            "reviewer": 0,
            "optimizer": 0,
            "download_bytes": 0,
            "artifact_bytes": None,
            "candidates": 1,
        },
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    store = CampaignStore(campaign_root, repository_root)
    store.create(
        campaign,
        bootstrap_paths=(
            host,
            plugin_build,
            *(path for path in plugin_root.rglob("*") if path.is_file()),
        ),
    )
    return {
        "repository_root": repository_root,
        "campaign_root": campaign_root,
        "campaign": campaign,
        "store": store,
        "bindings": bindings,
        "paths": {
            **product,
            "host": host,
            "plugin_build": plugin_build,
            "plugin_root": plugin_root,
            "probe_set": probe_set,
            "sentinel": sentinel,
        },
    }


def materialize_bootstrap_evidence(fixture: dict[str, Any]) -> dict[str, Any]:
    campaign_root = fixture["campaign_root"]
    repository_root = fixture["repository_root"]
    summary_path = write_json(
        campaign_root / "summary.json",
        with_self_hash(
            make_v5_schema_examples()["analysis-summary-v4.schema.json"],
            "summary_hash",
        ),
    )
    apparatus = materialize_apparatus_report(fixture)
    summary = make_binding(
        summary_path,
        root="campaign",
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    state = copy.deepcopy(fixture["campaign"])
    state["phase"] = "holdout_ready"
    state["apparatus_report"] = apparatus
    state["profiles"]["target_observed"] = fixture["bindings"]["host"]
    mark_probe_passed(state, fixture)
    state["skill_evidence"]["plugin_build"] = fixture["bindings"]["plugin_build"]
    for skill_id in SKILL_IDS:
        state["skill_evidence"][skill_id]["current_summary"] = summary
        state["skill_evidence"][skill_id]["holdout_summary"] = summary
    return with_self_hash(state, "campaign_hash")


def mark_probe_passed(state: dict[str, Any], fixture: dict[str, Any]) -> None:
    state["interaction_probes"]["requests"] = [
        {
            "request_id": "probe-fixture-01",
            "probe_id": "force-load",
            "status": "closed",
            "artifact": fixture["bindings"]["host"],
            "result_status": "pass",
        }
    ]
    state["interaction_probes"]["results"] = fixture["bindings"]["host"]


def materialize_budget_approval(
    fixture: dict[str, Any],
    state: dict[str, Any],
    name: str = "budget-approval.json",
) -> Path:
    probe_set = json.loads(fixture["paths"]["probe_set"].read_text())
    return write_json(
        fixture["campaign_root"] / name,
        with_self_hash(
            {
                "schema_version": "model-evolution-budget-approval/1",
                "campaign_id": state["campaign_id"],
                "campaign_hash": state["campaign_hash"],
                "state_revision": state["state_revision"],
                "ceilings": state["budgets"]["ceiling"],
                "planned": {
                    "interaction_probe_requests": len(probe_set["probes"]),
                    "public_plan_count": 4,
                    "artifact_file_ceiling": 5_000,
                    "wall_clock_seconds": 21_600,
                },
                "approved": True,
                "approved_by": "fixture-release-owner",
                "approved_at": "2026-08-03T00:00:00Z",
            },
            "approval_hash",
        ),
    )


def materialize_apparatus_report(
    fixture: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> dict[str, str]:
    state = fixture["campaign"] if state is None else state
    report = with_self_hash(
        {
            "schema_version": "model-evolution-apparatus-report/1",
            "campaign_id": state["campaign_id"],
            "source_commit": state["product"]["source_commit"],
            "source_tree": state["product"]["source_tree"],
            "campaign_hash": state["campaign_hash"],
            "status": "pass",
            "operations": [
                {
                    "operation_id": "fixture-preflight",
                    "input_hash": "sha256:" + "3" * 64,
                    "command_hash": "sha256:" + "4" * 64,
                    "status": "pass",
                    "duration_ms": 1,
                }
            ],
        },
        "apparatus_report_hash",
    )
    path = write_json(fixture["campaign_root"] / "apparatus-report.json", report)
    return make_binding(
        path,
        root="campaign",
        repository_root=fixture["repository_root"],
        campaign_root=fixture["campaign_root"],
    )
