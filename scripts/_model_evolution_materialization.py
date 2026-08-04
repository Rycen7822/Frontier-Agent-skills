#!/usr/bin/env python3
"""Materialize self-contained formal-plan inputs without provider calls."""

from __future__ import annotations

import copy
from hashlib import sha256
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import yaml

from _bundle_hash import inventory, tree_hash
from _model_evolution_contract import (
    SKILL_IDS,
    canonical_bytes,
    content_hash,
    load_json,
    load_jsonl,
    resolve_binding,
    self_hash,
    verify_self_hash,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_SCRIPTS = REPOSITORY_ROOT / "skill-evaluator/scripts"
sys.path.insert(0, str(EVALUATOR_SCRIPTS))

import validate_eval_suite as evaluator  # noqa: E402


class MaterializationError(ValueError):
    """Formal-plan inputs cannot be derived exactly from frozen evidence."""


def _file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _relative_path(value: Any, *, label: str) -> PurePosixPath:
    if not isinstance(value, str):
        raise MaterializationError(f"{label} path must be a string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise MaterializationError(f"{label} path is unsafe")
    return path


def _write_exact(path: Path, value: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != value:
            raise MaterializationError(f"refusing to replace different bytes: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _copy_file(source: Path, target: Path, *, expected_hash: str | None = None) -> None:
    if source.is_symlink() or not source.is_file():
        raise MaterializationError(f"required source is not a regular file: {source}")
    value = source.read_bytes()
    if expected_hash is not None and content_hash(value) != expected_hash:
        raise MaterializationError(f"source hash differs: {source}")
    _write_exact(target, value)


def _copy_relative_binding(
    binding: dict[str, Any], *, source_root: Path, target_root: Path, label: str
) -> Path:
    relative = _relative_path(binding.get("path"), label=label)
    source = source_root.joinpath(*relative.parts)
    target = target_root.joinpath(*relative.parts)
    _copy_file(source, target, expected_hash=binding.get("sha256"))
    return target


def _tree_hash(root: Path) -> str:
    paths = [path for path in root.rglob("*") if path.is_file() or path.is_symlink()]
    return tree_hash(inventory(root, paths))


def _assert_tree_equal(observed: Path, expected: Path, *, label: str) -> None:
    observed_files = {
        path.relative_to(observed).as_posix(): path
        for path in observed.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    expected_files = {
        path.relative_to(expected).as_posix(): path
        for path in expected.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    if set(observed_files) != set(expected_files):
        raise MaterializationError(f"{label} file inventory differs from derivation")
    for relative, observed_path in observed_files.items():
        expected_path = expected_files[relative]
        if observed_path.is_symlink() or expected_path.is_symlink():
            raise MaterializationError(f"{label} contains a symlink at {relative}")
        if observed_path.read_bytes() != expected_path.read_bytes():
            raise MaterializationError(f"{label} differs at {relative}")


def _copy_tree(source: Path, target: Path, *, expected_hash: str) -> None:
    if source.is_symlink() or not source.is_dir() or target.exists():
        raise MaterializationError("Skill package source or destination is invalid")
    if any(path.is_symlink() for path in source.rglob("*")):
        raise MaterializationError("Skill package contains a symlink")
    shutil.copytree(source, target)
    if _tree_hash(target) != expected_hash:
        raise MaterializationError("copied Skill package hash differs from campaign")


def _selected_product(
    campaign: dict[str, Any], role: str
) -> tuple[dict[str, Any], str, str]:
    if role == "target_current" or campaign.get("candidate") is None:
        return (
            campaign["product"]["skills"],
            campaign["product"]["source_commit"],
            campaign["product"]["source_tree"],
        )
    candidate = campaign["candidate"]
    return candidate["skills"], candidate["candidate_commit"], candidate["candidate_tree"]


def _plugin_argument(host: dict[str, Any]) -> Path:
    argv = host.get("command", {}).get("argv")
    positions = [index for index, item in enumerate(argv or []) if item == "--plugin-root"]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise MaterializationError("Host command lacks one plugin-root binding")
    return Path(argv[positions[0] + 1]).resolve(strict=True)


def _skill_frontmatter(skill_root: Path) -> dict[str, Any]:
    path = skill_root / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise MaterializationError(f"Skill frontmatter is invalid: {skill_root.name}")
    value = yaml.safe_load(text.split("---\n", 2)[1])
    if not isinstance(value, dict):
        raise MaterializationError(f"Skill frontmatter is invalid: {skill_root.name}")
    return value


def _validate_selected_plugin(
    *,
    campaign: dict[str, Any],
    campaign_root: Path,
    role: str,
    plugin_root: Path,
    evidence_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if plugin_root.is_symlink() or evidence_path.is_symlink():
        raise MaterializationError("selected plugin staging must not be a symlink")
    plugin_root = plugin_root.resolve(strict=True)
    evidence_path = evidence_path.resolve(strict=True)
    if (
        not plugin_root.is_dir()
        or not plugin_root.is_relative_to(campaign_root)
        or not evidence_path.is_file()
        or not evidence_path.is_relative_to(campaign_root)
    ):
        raise MaterializationError("selected plugin staging must be campaign-local")
    evidence = load_json(evidence_path, label="selected plugin build")
    verify_self_hash(evidence, "evidence_hash")
    skills, source_commit, _ = _selected_product(campaign, role)
    if (
        evidence.get("source_revision") != source_commit
        or evidence.get("plugin_tree_hash") != _tree_hash(plugin_root)
    ):
        raise MaterializationError("selected plugin build identity differs")
    skill_roots = {
        path.name: path
        for path in (plugin_root / "skills").iterdir()
        if path.is_dir() and not path.is_symlink()
    }
    if set(skill_roots) != set(SKILL_IDS):
        raise MaterializationError("selected plugin does not contain exact four Skills")
    for skill_id, skill_root in skill_roots.items():
        frontmatter = _skill_frontmatter(skill_root)
        metadata = frontmatter.get("metadata")
        if (
            _tree_hash(skill_root) != skills[skill_id]["root_hash"]
            or not isinstance(metadata, dict)
            or metadata.get("version") != skills[skill_id]["version"]
        ):
            raise MaterializationError(f"selected plugin Skill differs: {skill_id}")
    return evidence, skills


def _run(command: list[str], *, repository_root: Path, label: str) -> None:
    result = subprocess.run(
        command,
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        diagnostic = (result.stderr or result.stdout).strip()[-1200:]
        raise MaterializationError(f"{label} failed: {diagnostic}")


def _host_artifact_source(
    binding: dict[str, Any], *, repository_root: Path, campaign_root: Path
) -> Path:
    relative = _relative_path(binding.get("path"), label="Host probe artifact")
    matches = []
    for root in (campaign_root, repository_root):
        candidate = root.joinpath(*relative.parts)
        if (
            candidate.is_file()
            and not candidate.is_symlink()
            and _file_hash(candidate) == binding.get("sha256")
        ):
            matches.append(candidate)
    if len(matches) != 1:
        raise MaterializationError(
            f"Host probe artifact must resolve to one exact source: {relative}"
        )
    return matches[0]


def _copy_host_artifacts(
    host: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    target_root: Path,
) -> None:
    probes = [item.get("probe") for item in host.get("capabilities", [])]
    probes.append(host.get("reset", {}).get("probe"))
    for index, probe in enumerate(probes):
        if not isinstance(probe, dict) or not isinstance(probe.get("artifact"), dict):
            raise MaterializationError(f"Host probe {index} has no artifact binding")
        binding = probe["artifact"]
        source = _host_artifact_source(
            binding, repository_root=repository_root, campaign_root=campaign_root
        )
        relative = _relative_path(binding["path"], label="Host probe artifact")
        _copy_file(
            source,
            target_root.joinpath(*relative.parts),
            expected_hash=binding["sha256"],
        )


def promoted_model_grading_host(
    base_host: dict[str, Any],
    *,
    host_path: Path,
    calibration_file_hash: str,
    plugin_root: Path | None = None,
    selected_skills: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    source_commit: str | None = None,
    source_tree: str | None = None,
) -> dict[str, Any]:
    """Derive the exact ready Host from observed probes plus calibration evidence."""
    host = copy.deepcopy(base_host)
    if any(
        item.get("capability") == "model_grading"
        for item in host.get("capabilities", [])
        if isinstance(item, dict)
    ):
        raise MaterializationError("observed Host already owns model_grading")
    host["capabilities"].append(
        {
            "capability": "model_grading",
            "declared": True,
            "probe": {
                "status": "pass",
                "artifact": {
                    "path": "grader-calibration.json",
                    "sha256": calibration_file_hash,
                    "encoding": "utf-8",
                },
                "locator": {
                    "kind": "json_pointer",
                    "artifact": "grader-calibration.json",
                    "json_pointer": "/calibration_hash",
                },
                "observed": "bound validated grader calibration",
            },
        }
    )
    argv = host.get("command", {}).get("argv")
    positions = [
        index for index, item in enumerate(argv or []) if item == "--host-manifest"
    ]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise MaterializationError("observed Host command lacks one manifest binding")
    argv[positions[0] + 1] = str(host_path.resolve())
    retarget = (
        plugin_root,
        selected_skills,
        repository_root,
        source_commit,
        source_tree,
    )
    if any(item is not None for item in retarget):
        if any(item is None for item in retarget):
            raise MaterializationError("Host retarget inputs are incomplete")
        assert plugin_root is not None
        assert selected_skills is not None
        assert repository_root is not None
        plugin_positions = [
            index for index, item in enumerate(argv) if item == "--plugin-root"
        ]
        if len(plugin_positions) != 1 or plugin_positions[0] + 1 >= len(argv):
            raise MaterializationError("observed Host command lacks one plugin binding")
        argv[plugin_positions[0] + 1] = str(plugin_root.resolve(strict=True))
        entries = host.get("catalog", {}).get("entries")
        by_id = {
            item.get("id"): item
            for item in entries or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        if len(by_id) != len(entries or []) or set(by_id) != set(SKILL_IDS):
            raise MaterializationError("observed Host catalog differs from exact Skills")
        refreshed = []
        for skill_id in sorted(SKILL_IDS):
            skill_root = plugin_root / "skills" / skill_id
            frontmatter = _skill_frontmatter(skill_root)
            item = copy.deepcopy(by_id[skill_id])
            item.update(
                {
                    "description": frontmatter.get("description"),
                    "root_hash": selected_skills[skill_id]["root_hash"],
                    "version": selected_skills[skill_id]["version"],
                }
            )
            if not isinstance(item["description"], str) or not item["description"]:
                raise MaterializationError(f"Skill description is invalid: {skill_id}")
            refreshed.append(item)
        catalog_hash = content_hash(canonical_bytes(refreshed))
        host["catalog"] = {"entries": refreshed, "catalog_hash": catalog_hash}
        execution = host["identity"]["execution"]
        execution["catalog_hash"] = catalog_hash
        execution["skill_hash"] = _tree_hash(plugin_root)
        host["identity"]["repository"] = {
            "dirty": False,
            "revision": source_commit,
            "tree": source_tree,
            "worktree": str(repository_root.resolve(strict=True)),
        }
    host["manifest_hash"] = self_hash(host, "manifest_hash")
    return host


def _copy_calibration(
    calibration_source: Path, *, target_root: Path
) -> tuple[dict[str, Any], Path]:
    calibration = load_json(calibration_source, label="recorded grader calibration")
    verify_self_hash(calibration, "calibration_hash")
    target = target_root / "grader-calibration.json"
    _copy_file(calibration_source, target)
    for field in ("labeled_examples", "raw_ratings"):
        binding = calibration.get(field)
        if not isinstance(binding, dict):
            raise MaterializationError(f"calibration lacks {field} binding")
        _copy_relative_binding(
            binding,
            source_root=calibration_source.parent,
            target_root=target_root,
            label=f"calibration {field}",
        )
    return calibration, target


def _copy_sentinel_inputs(
    record: dict[str, Any],
    *,
    template_path: Path,
    template: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
    target_root: Path,
) -> tuple[Path, Path]:
    scenario_source = resolve_binding(
        record["public_scenarios"], repository_root, campaign_root
    )
    scenario_target = target_root / "scenarios.public.jsonl"
    _copy_file(scenario_source, scenario_target)

    proof_target = _copy_sentinel_support(
        record,
        template_path=template_path,
        template=template,
        repository_root=repository_root,
        campaign_root=campaign_root,
        target_root=target_root,
    )
    return scenario_target, proof_target


def _copy_sentinel_support(
    record: dict[str, Any],
    *,
    template_path: Path,
    template: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
    target_root: Path,
) -> Path:

    for binding in (*record["fixture_roots"], *record["verifier_roots"]):
        source = resolve_binding(binding, repository_root, campaign_root)
        try:
            relative = source.relative_to(template_path.parent)
        except ValueError as exc:
            raise MaterializationError("sentinel input escapes its Skill root") from exc
        _copy_file(source, target_root / relative, expected_hash=binding["sha256"])

    model_graders = [item for item in template["graders"] if item["type"] == "model"]
    if len(model_graders) != 1:
        raise MaterializationError("current materialization requires one model grader")
    for field in ("prompt", "output_schema"):
        binding = model_graders[0][field]
        _copy_relative_binding(
            binding,
            source_root=template_path.parent,
            target_root=target_root,
            label=f"model grader {field}",
        )

    quality_source = template_path.parent / template["suite"]["quality"]["path"]
    quality = load_json(quality_source, label="draft suite quality")
    raw_proofs = quality.get("raw_proofs", {})
    bindings = [
        raw_proofs.get(field)
        for field in ("golden", "known_bad", "mutations", "reviews")
    ]
    if (
        not bindings
        or not isinstance(bindings[0], dict)
        or any(binding != bindings[0] for binding in bindings)
    ):
        raise MaterializationError("suite-quality raw proof binding is ambiguous")
    proof_target = _copy_relative_binding(
        bindings[0],
        source_root=quality_source.parent,
        target_root=target_root,
        label="suite-quality proof",
    )
    return proof_target


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = b"".join(canonical_bytes(row) + b"\n" for row in rows)
    _write_exact(path, payload)


def _candidate_rows(
    rows: list[dict[str, Any]],
    *,
    skill_id: str,
    candidate_owner: str,
    protected_ids: list[str],
) -> list[dict[str, Any]]:
    selected = (
        {row["case_id"] for row in rows}
        if skill_id == candidate_owner
        else set(protected_ids)
    )
    if skill_id != candidate_owner:
        controls = [
            row["case_id"]
            for row in rows
            if "core" in row.get("tags", [])
            and not {"boundary", "failure", "protected"}
            & set(row.get("tags", []))
        ]
        if not controls:
            raise MaterializationError("candidate plan lacks a positive control scenario")
        selected.add(controls[0])
    result = [row for row in rows if row.get("case_id") in selected]
    if {row.get("case_id") for row in result} != selected:
        raise MaterializationError("candidate scenario selection is incomplete")
    return result


def _filter_quality_proof(
    proof: dict[str, Any],
    *,
    spec: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = {row["case_id"] for row in scenarios}
    value = copy.deepcopy(proof)
    value["case_classes"] = [
        item for item in value["case_classes"] if item.get("case_id") in selected
    ]
    for field in ("case_ids", "passed_ids"):
        value["golden"][field] = [
            case_id for case_id in value["golden"][field] if case_id in selected
        ]
    filtered_groups = []
    for group in value["duplicate_groups"]:
        reduced = [case_id for case_id in group["case_ids"] if case_id in selected]
        if len(reduced) > 1:
            filtered_groups.append({**group, "case_ids": reduced})
    value["duplicate_groups"] = filtered_groups
    clusters = []
    for cluster in value["provenance_clusters"]:
        reduced = [case_id for case_id in cluster["case_ids"] if case_id in selected]
        if reduced:
            clusters.append({**cluster, "case_ids": reduced})
    value["provenance_clusters"] = clusters
    value["custody"]["split_hashes"] = evaluator._quality_split_hashes(
        spec, scenarios
    )
    return value


def _bind_scenarios(spec: dict[str, Any], scenarios: list[dict[str, Any]]) -> None:
    case_ids = [row["case_id"] for row in scenarios]
    tags = sorted({tag for row in scenarios for tag in row["tags"]})
    for treatment in spec["treatments"]:
        treatment["scenario_ids"] = case_ids
        treatment["scenario_tags"] = tags
    spec["suite"]["fixture_set_hash"] = evaluator.v5_fixture_set_hash(scenarios)
    spec["suite"]["grader_set_hash"] = evaluator.v5_grader_set_hash(spec["graders"])
    spec["suite"]["grader_schedule_hash"] = evaluator.v5_grader_schedule_hash(
        spec, scenarios
    )
    spec["suite"]["treatment_contract_hash"] = evaluator.v5_treatment_contract_hash(
        spec["treatments"]
    )
    spec["suite"]["quality_contract_hash"] = evaluator.quality_contract_hash(spec)


def _materialized_spec(
    template: dict[str, Any],
    *,
    skill_id: str,
    selected_skill: dict[str, Any],
    source_commit: str,
    source_tree: str,
    host: dict[str, Any],
    host_file_hash: str,
    calibration: dict[str, Any],
    calibration_file_hash: str,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    spec = copy.deepcopy(template)
    spec["execution"]["as_of"] = calibration["created"]
    spec["execution"]["ready"] = False
    spec["subject"]["claimed_hosts"] = [host["identity"]["host_id"]]
    spec["subject"]["version"] = selected_skill["version"]
    spec["subject"]["package"] = {
        "path": "package",
        "package_hash": selected_skill["root_hash"],
        "repository_revision": source_commit,
        "repository_tree": source_tree,
        "dirty_state": "clean",
    }
    spec["host"]["manifest"] = {
        "path": "host.json",
        "sha256": host_file_hash,
    }
    model_grader = next(item for item in spec["graders"] if item["type"] == "model")
    model_grader["model"] = host["identity"]["execution"]["model"]
    spec["suite"]["calibration"] = {
        "path": "grader-calibration.json",
        "sha256": calibration_file_hash,
    }
    _bind_scenarios(spec, scenarios)
    return spec


def _compile_and_validate(
    root: Path,
    *,
    repository_root: Path,
    plan_path: Path,
    scenarios_name: str = "scenarios.public.jsonl",
) -> None:
    validator = repository_root / "skill-evaluator/scripts/validate_eval_suite.py"
    compiler = repository_root / "skill-evaluator/scripts/compile_eval_plan.py"
    _run(
        [
            sys.executable,
            str(validator),
            "contract",
            str(root / "eval-spec.json"),
            str(root / scenarios_name),
            str(root / "host.json"),
            "--json",
            "-",
        ],
        repository_root=repository_root,
        label="ready evaluation contract",
    )
    _run(
        [
            sys.executable,
            str(compiler),
            str(root / "eval-spec.json"),
            str(root / scenarios_name),
            str(root / "host.json"),
            "--output",
            str(plan_path),
        ],
        repository_root=repository_root,
        label="formal plan compilation",
    )


def _build_public_plan(
    root: Path,
    *,
    final_root: Path,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    role: str,
    plugin_root: Path,
    plugin_evidence: Path,
) -> dict[str, Any]:
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    record = sentinel["skills"][skill_id]
    template_path = resolve_binding(
        record["spec_template"], repository_root, campaign_root
    )
    template = load_json(template_path, label=f"{skill_id} spec template")
    calibration_source = resolve_binding(
        campaign["skill_evidence"][skill_id]["grader_calibration"],
        repository_root,
        campaign_root,
    )
    calibration, calibration_path = _copy_calibration(
        calibration_source, target_root=root
    )
    if calibration.get("evaluation_id") != template.get("evaluation_id"):
        raise MaterializationError("calibration differs from the selected Skill")

    scenario_path, proof_path = _copy_sentinel_inputs(
        record,
        template_path=template_path,
        template=template,
        repository_root=repository_root,
        campaign_root=campaign_root,
        target_root=root,
    )
    scenarios = load_jsonl(scenario_path, label=f"{skill_id} public scenarios")
    if role == "target_candidate":
        candidate = campaign.get("candidate")
        if not isinstance(candidate, dict):
            raise MaterializationError("candidate plan has no accepted candidate")
        scenarios = _candidate_rows(
            scenarios,
            skill_id=skill_id,
            candidate_owner=candidate["owner_surface"],
            protected_ids=record["protected_case_ids"],
        )
        scenario_path.unlink()
        _write_jsonl(scenario_path, scenarios)

    _, selected_skills = _validate_selected_plugin(
        campaign=campaign,
        campaign_root=campaign_root,
        role=role,
        plugin_root=plugin_root,
        evidence_path=plugin_evidence,
    )
    _copy_file(plugin_evidence, root / "selected-plugin-build.json")
    _, source_commit, source_tree = _selected_product(campaign, role)

    base_host = load_json(
        resolve_binding(
            campaign["profiles"]["target_observed"], repository_root, campaign_root
        ),
        label="target observed Host",
    )
    _copy_host_artifacts(
        base_host,
        repository_root=repository_root,
        campaign_root=campaign_root,
        target_root=root,
    )
    host_path = root / "host.json"
    retarget = role == "target_candidate"
    if not retarget and _plugin_argument(base_host) != plugin_root.resolve(strict=True):
        raise MaterializationError("observed Host plugin differs from selected staging")
    host = promoted_model_grading_host(
        base_host,
        host_path=final_root / "host.json",
        calibration_file_hash=_file_hash(calibration_path),
        plugin_root=plugin_root if retarget else None,
        selected_skills=selected_skills if retarget else None,
        repository_root=repository_root if retarget else None,
        source_commit=source_commit if retarget else None,
        source_tree=source_tree if retarget else None,
    )
    _write_exact(host_path, canonical_bytes(host))

    _copy_tree(
        plugin_root / "skills" / skill_id,
        root / "package",
        expected_hash=selected_skills[skill_id]["root_hash"],
    )
    spec = _materialized_spec(
        template,
        skill_id=skill_id,
        selected_skill=selected_skills[skill_id],
        source_commit=source_commit,
        source_tree=source_tree,
        host=host,
        host_file_hash=_file_hash(host_path),
        calibration=calibration,
        calibration_file_hash=_file_hash(calibration_path),
        scenarios=scenarios,
    )
    if role == "target_candidate":
        scenario_binding = {
            "path": scenario_path.name,
            "sha256": _file_hash(scenario_path),
        }
        spec["suite"]["scenarios"] = scenario_binding
        spec["suite"]["public_scenarios"] = copy.deepcopy(scenario_binding)
        _bind_scenarios(spec, scenarios)
        proof = load_json(proof_path, label="public suite-quality proof")
        proof_path.unlink()
        _write_exact(
            proof_path,
            canonical_bytes(
                _filter_quality_proof(proof, spec=spec, scenarios=scenarios)
            ),
        )
    spec_path = root / "eval-spec.json"
    _write_exact(spec_path, canonical_bytes(spec))

    quality_path = root / "suite-quality.json"
    _run(
        [
            sys.executable,
            str(repository_root / "skill-evaluator/scripts/validate_eval_suite.py"),
            "suite-quality",
            "--spec",
            str(spec_path),
            "--proof",
            str(proof_path),
            "--output",
            str(quality_path),
        ],
        repository_root=repository_root,
        label="suite-quality normalization",
    )
    spec["suite"]["quality"]["sha256"] = _file_hash(quality_path)
    spec["execution"]["ready"] = True
    spec_path.write_bytes(canonical_bytes(spec))
    plan_path = root / "plan.json"
    _compile_and_validate(root, repository_root=repository_root, plan_path=plan_path)
    plan = load_json(plan_path, label="compiled formal plan")
    verify_self_hash(plan, "plan_hash")
    return {
        "root": root,
        "spec": spec_path,
        "host": host_path,
        "plan": plan_path,
        "plan_id": plan["plan_id"],
        "plan_hash": plan["plan_hash"],
        "execute_ceiling": sum(
            entry.get("disposition") == "execute" for entry in plan["entries"]
        ),
    }


def _prepare_public_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    role: str,
    directory: str,
    required_phase: str,
    plugin_root: Path,
    plugin_evidence: Path,
) -> dict[str, Any]:
    if skill_id not in SKILL_IDS or campaign["phase"] != required_phase:
        raise MaterializationError(f"{role} plans require {required_phase}")
    final_root = campaign_root / directory / skill_id
    if final_root.exists():
        raise MaterializationError(f"current plan already exists: {skill_id}")
    parent = final_root.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{skill_id}-", dir=parent))
    try:
        result = _build_public_plan(
            temporary,
            final_root=final_root,
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            skill_id=skill_id,
            role=role,
            plugin_root=plugin_root,
            plugin_evidence=plugin_evidence,
        )
        temporary.rename(final_root)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return {
        **result,
        "root": final_root,
        "spec": final_root / "eval-spec.json",
        "host": final_root / "host.json",
        "plan": final_root / "plan.json",
    }


def prepare_current_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
) -> dict[str, Any]:
    return _prepare_public_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=skill_id,
        role="target_current",
        directory="current-plans",
        required_phase="calibration_ready",
        plugin_root=campaign_root / campaign["product"]["plugin_root"],
        plugin_evidence=resolve_binding(
            campaign["product"]["plugin_build"], repository_root, campaign_root
        ),
    )


def prepare_candidate_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plugin_root: Path,
    plugin_evidence: Path,
) -> dict[str, Any]:
    return _prepare_public_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=skill_id,
        role="target_candidate",
        directory="candidate-plans",
        required_phase="candidate_registered",
        plugin_root=plugin_root,
        plugin_evidence=plugin_evidence,
    )


def _validate_public_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plan_path: Path,
    role: str,
    directory: str,
) -> dict[str, Any]:
    root = campaign_root / directory / skill_id
    if plan_path != (root / "plan.json").resolve(strict=True):
        raise MaterializationError(f"{role} plan is outside its canonical directory")
    calibration_source = resolve_binding(
        campaign["skill_evidence"][skill_id]["grader_calibration"],
        repository_root,
        campaign_root,
    )
    calibration_path = root / "grader-calibration.json"
    if _file_hash(calibration_path) != _file_hash(calibration_source):
        raise MaterializationError("materialized calibration differs from campaign")
    selected_evidence = root / "selected-plugin-build.json"
    if role == "target_current":
        source = resolve_binding(
            campaign["product"]["plugin_build"], repository_root, campaign_root
        )
        if selected_evidence.read_bytes() != source.read_bytes():
            raise MaterializationError("current plugin evidence differs from campaign")
    host = load_json(root / "host.json", label=f"materialized {role} Host")
    plugin_root = _plugin_argument(host)
    _, selected_skills = _validate_selected_plugin(
        campaign=campaign,
        campaign_root=campaign_root,
        role=role,
        plugin_root=plugin_root,
        evidence_path=selected_evidence,
    )
    base_host = load_json(
        resolve_binding(
            campaign["profiles"]["target_observed"], repository_root, campaign_root
        ),
        label="target observed Host",
    )
    _, source_commit, source_tree = _selected_product(campaign, role)
    retarget = role == "target_candidate"
    expected_host = promoted_model_grading_host(
        base_host,
        host_path=root / "host.json",
        calibration_file_hash=_file_hash(calibration_path),
        plugin_root=plugin_root if retarget else None,
        selected_skills=selected_skills if retarget else None,
        repository_root=repository_root if retarget else None,
        source_commit=source_commit if retarget else None,
        source_tree=source_tree if retarget else None,
    )
    if canonical_bytes(host) != canonical_bytes(expected_host):
        raise MaterializationError(f"materialized {role} Host differs from derivation")
    if _tree_hash(root / "package") != selected_skills[skill_id]["root_hash"]:
        raise MaterializationError(f"materialized {role} package differs from campaign")
    with tempfile.TemporaryDirectory(dir=root.parent, prefix=".register-check-") as raw:
        expected_root = Path(raw) / "expected"
        _build_public_plan(
            expected_root,
            final_root=root,
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            skill_id=skill_id,
            role=role,
            plugin_root=plugin_root,
            plugin_evidence=(
                resolve_binding(
                    campaign["product"]["plugin_build"],
                    repository_root,
                    campaign_root,
                )
                if role == "target_current"
                else selected_evidence
            ),
        )
        _assert_tree_equal(root, expected_root, label=role)
    return host


def validate_current_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plan_path: Path,
) -> dict[str, Any]:
    return _validate_public_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=skill_id,
        plan_path=plan_path,
        role="target_current",
        directory="current-plans",
    )


def validate_candidate_plan(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    plan_path: Path,
) -> dict[str, Any]:
    return _validate_public_plan(
        repository_root=repository_root,
        campaign_root=campaign_root,
        campaign=campaign,
        skill_id=skill_id,
        plan_path=plan_path,
        role="target_candidate",
        directory="candidate-plans",
    )
