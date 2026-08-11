from __future__ import annotations

import copy
import json
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any

from _bundle_hash import inventory, tree_hash
from _model_evolution_campaign import build_initial_campaign
from _model_evolution_contract import (
    SKILL_IDS,
    make_binding,
)
from _model_evolution_state import CampaignStore
from support.model_evolution.documents import analysis_summary, host_manifest

SOURCE_ROOT = Path(__file__).resolve().parents[3]
FIXED_COMMIT = "1" * 40
FIXED_TREE = "2" * 40


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


def copy_product_files(repository_root: Path) -> dict[str, Path]:
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


def root_hash(root: Path) -> str:
    members = [path for path in root.rglob("*") if path.is_file() or path.is_symlink()]
    return tree_hash(inventory(root, members))


def campaign_layout(root: Path) -> tuple[Path, Path]:
    canonical_root = root / "Frontier-Agent-skills"
    repository_root = canonical_root / ".worktrees/fixture"
    campaign_root = canonical_root / ".work/campaign"
    repository_root.mkdir(parents=True)
    campaign_root.mkdir(parents=True)
    return repository_root, campaign_root


def assemble_campaign(
    *,
    repository_root: Path,
    campaign_root: Path,
    product: dict[str, Path],
    plugin_root: Path,
    plugin_build: Path,
    host: Path,
    probe_set: Path,
    sentinel: Path,
) -> dict[str, Any]:
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


def materialize_campaign(root: Path) -> dict[str, Any]:
    repository_root, campaign_root = campaign_layout(root)
    product = copy_product_files(repository_root)
    plugin_root = campaign_root / "staging/frontier-engineering-plugin"
    write_json(plugin_root / ".codex-plugin/plugin.json", {})
    for skill_id in SKILL_IDS:
        skill_root = plugin_root / "skills" / skill_id
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            f"---\nname: {skill_id}\ndescription: Synthetic fixture.\n---\n",
            encoding="utf-8",
        )
    plugin_tree_hash = root_hash(plugin_root)
    plugin_build = write_json(
        campaign_root / "inputs/plugin-build-evidence.json",
        {
            "schema_version": "plugin-build-evidence/3.0",
            "source_revision": FIXED_COMMIT,
            "plugin_tree_hash": plugin_tree_hash,
        },
    )
    host_path = campaign_root / "inputs/target-provisional-host.json"
    host_value = host_manifest()
    host_value["identity"]["repository"].update(
        {
            "dirty": False,
            "revision": FIXED_COMMIT,
            "tree": FIXED_TREE,
            "worktree": str(repository_root.resolve()),
        }
    )
    prototype = host_value["catalog"]["entries"][0]
    host_value["catalog"]["entries"] = [
        {
            **prototype,
            "id": skill_id,
            "name": skill_id,
            "version": "1.0.0",
            "root_digest": root_hash(plugin_root / "skills" / skill_id),
        }
        for skill_id in SKILL_IDS
    ]
    host_value["catalog"]["catalog_id"] = "fixture-frontier-catalog"
    host_value["identity"]["execution"]["catalog_id"] = "fixture-frontier-catalog"
    host_value["command"]["argv"] = [
        "python3",
        "synthetic-host.py",
        "--host-manifest",
        str(host_path),
    ]
    host = write_json(host_path, host_value)
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


def materialize_probe_set(repository_root: Path, campaign_root: Path) -> Path:
    fixture = repository_root / "fixtures/probe.txt"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("inert probe fixture\n", encoding="utf-8")
    probe_set = {
        "schema_version": "model-evolution-interaction-probes/2",
        "probe_set_id": "codex-host-probes-v2",
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
    }
    return write_json(repository_root / "codex-interaction-probes-v2.json", probe_set)


def materialize_sentinel(repository_root: Path, campaign_root: Path) -> Path:
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
    sentinel = {
        "schema_version": "model-evolution-sentinel-index/2",
        "sentinel_id": "frontier-sentinel-v2",
        "skills": skills,
    }
    return write_json(repository_root / "sentinel-index-v2.json", sentinel)


def materialize_bootstrap_evidence(fixture: dict[str, Any]) -> dict[str, Any]:
    campaign_root = fixture["campaign_root"]
    repository_root = fixture["repository_root"]
    summary_path = write_json(campaign_root / "summary.json", analysis_summary())
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
    return state


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
        {
            "schema_version": "model-evolution-budget-approval/2",
            "campaign_id": state["campaign_id"],
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
    )


def materialize_apparatus_report(
    fixture: dict[str, Any],
    state: dict[str, Any] | None = None,
) -> dict[str, str]:
    state = fixture["campaign"] if state is None else state
    report = {
        "schema_version": "model-evolution-apparatus-report/2",
        "campaign_id": state["campaign_id"],
        "state_revision": state["state_revision"],
        "source_commit": state["product"]["source_commit"],
        "source_tree": state["product"]["source_tree"],
        "status": "pass",
        "operations": [
            {
                "operation_id": "fixture-preflight",
                "status": "pass",
                "duration_ms": 1,
                "state_revision": state["state_revision"],
                "exit_code": 0,
                "diagnostic": None,
            }
        ],
    }
    path = write_json(fixture["campaign_root"] / "apparatus-report.json", report)
    return make_binding(
        path,
        root="campaign",
        repository_root=fixture["repository_root"],
        campaign_root=fixture["campaign_root"],
    )
