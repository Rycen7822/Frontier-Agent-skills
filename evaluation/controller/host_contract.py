"""Materialize self-contained host inputs around the tracked controller CLI."""

from __future__ import annotations

import copy
from pathlib import Path
import shutil
import sys
from typing import Any

from .artifacts import (
    HASH_PATTERN,
    artifact_binding,
    assert_nofollow,
    atomic_write,
    canonical_hash,
    contained_file,
    file_hash,
    json_object,
    write_json,
)
from .specs import MODEL, StudyDesign


HOST_ASSETS = (
    "host_grader.py",
    "model_grader_prompt.md",
    "model_judgment.schema.json",
)


def _codex_binding(
    runtime: dict[str, dict[str, Any]],
) -> tuple[Path, str]:
    binding = runtime.get("executable")
    path = (
        Path(str(binding.get("path")))
        if isinstance(binding, dict)
        else Path()
    )
    digest = binding.get("sha256") if isinstance(binding, dict) else None
    path = assert_nofollow(path, kind="file")
    if (
        not isinstance(digest, str)
        or not HASH_PATTERN.fullmatch(digest)
        or file_hash(path) != digest
    ):
        raise ValueError("Codex executable binding differs")
    return path, digest


def _capabilities(design: StudyDesign) -> list[str]:
    profiles = {
        profile
        for case in design.cases
        for profile in case.applicable_profiles
    }
    names = []
    if any(profile.endswith("/force_loaded") for profile in profiles):
        names.append("force_load")
    if any(
        profile.endswith("/natural_routing")
        or profile.startswith("comparator/")
        for profile in profiles
    ):
        names.extend(("discovery", "natural_routing"))
    if any(case.model_grading for case in design.cases):
        names.append("model_grading")
    if design.level == "L4":
        names.append("clock_capture")
    return names


def _command(
    study: Path,
    candidate: Path,
    prior: Path | None,
    codex_path: Path,
    codex_hash: str,
) -> list[str]:
    argv = [
        "python3",
        "-m",
        "evaluation.controller.cli",
        "host",
        "--host-manifest",
        "host-manifest-v1.json",
        "--candidate",
        candidate.relative_to(study).as_posix(),
        "--grader-prompt",
        "host/model_grader_prompt.md",
        "--grader-schema",
        "host/model_judgment.schema.json",
        "--codex-bin",
        str(codex_path),
        "--codex-bin-sha256",
        codex_hash,
    ]
    if prior is not None:
        argv.extend(("--prior", prior.relative_to(study).as_posix()))
    return argv


def _identity(
    manifest: dict[str, Any],
    *,
    repository: dict[str, str],
    controller_hash: str,
    cli_hash: str,
    design: StudyDesign,
    package_hash: str,
) -> str:
    identity = manifest["identity"]
    identity.update({
        "host_id": "frontier-se3-host",
        "host_name": "Frontier SE3 Host",
        "host_version": "1.0.0",
        "host_build": controller_hash,
        "adapter": {
            "id": "frontier-jsonl-adapter",
            "version": "1",
            "sha256": cli_hash,
        },
    })
    identity["repository"].update({
        **repository,
        "dirty": False,
        "worktree": "candidate",
    })
    identity["session"].update({
        "topology": "single",
        "session_id": "ephemeral-per-entry",
    })
    identity["platform"].update({
        "os": sys.platform,
        "runtime": f"python-{sys.version_info.major}.{sys.version_info.minor}",
    })
    catalog_hash = canonical_hash([{
        "id": design.skill_id,
        "root_hash": package_hash,
    }])
    identity["execution"].update({
        "provider": "openai",
        "model": MODEL,
        "model_revision": MODEL,
        "harness": "codex-app-server",
        "skill_hash": package_hash,
        "catalog_hash": catalog_hash,
        "pricing_id": "provider-reported",
    })
    return catalog_hash


def _finish_manifest(
    manifest: dict[str, Any],
    *,
    design: StudyDesign,
    command: list[str],
    adapter_binding: dict[str, str],
    catalog_hash: str,
) -> None:
    probe = {
        "status": "pass",
        "artifact": {**adapter_binding, "encoding": "utf-8"},
        "locator": {
            "kind": "text_lines",
            "artifact": adapter_binding["path"],
            "start_line": 1,
            "end_line": 1,
        },
        "observed": "tracked controller adapter binding passed",
    }
    manifest["capabilities"] = [{
        "capability": name,
        "declared": True,
        "probe": copy.deepcopy(probe),
    } for name in _capabilities(design)]
    manifest["reset"]["probe"] = copy.deepcopy(probe)
    manifest["catalog"] = {
        "catalog_hash": catalog_hash,
        "entries": [{
            "id": design.skill_id,
            "name": design.skill_id,
            "description": "Frozen candidate skill",
            "scope": "evaluation",
            "source": "local",
            "version": "6.0.0",
            "root_hash": manifest["identity"]["execution"]["skill_hash"],
        }],
    }
    manifest["manifest_id"] = (
        "hm-"
        + canonical_hash({
            "adapter": manifest["identity"]["adapter"],
            "repository": manifest["identity"]["repository"],
            "command": command,
        }).removeprefix("sha256:")[:24]
    )
    manifest["manifest_hash"] = canonical_hash({
        key: value for key, value in manifest.items()
        if key != "manifest_hash"
    })


def materialize(
    *,
    study_root: Path,
    evaluator_root: Path,
    candidate_skill: Path,
    prior_skill: Path | None,
    package_hash: str,
    repository: dict[str, str],
    design: StudyDesign,
    codex_runtime: dict[str, dict[str, Any]],
    controller_content_hash: str,
) -> dict[str, Any]:
    """Stage immutable host inputs without copying controller implementation."""
    study = assert_nofollow(study_root, kind="directory")
    candidate = assert_nofollow(candidate_skill, kind="file")
    prior = (
        None
        if prior_skill is None
        else assert_nofollow(prior_skill, kind="file")
    )
    if (
        not HASH_PATTERN.fullmatch(package_hash)
        or not HASH_PATTERN.fullmatch(controller_content_hash)
        or set(repository) != {"revision", "tree"}
    ):
        raise ValueError("host source identity is invalid")
    codex_path, codex_hash = _codex_binding(codex_runtime)
    controller = Path(__file__).parent
    host_dir = study / "host"
    host_dir.mkdir()
    for name in HOST_ASSETS:
        atomic_write(host_dir / name, (controller / name).read_bytes())
    adapter = {
        "schema_version": "frontier-controller-adapter-binding/1.0",
        "controller_content_hash": controller_content_hash,
        "cli_path": "evaluation/controller/cli.py",
        "cli_sha256": file_hash(controller / "cli.py"),
        "binding_hash": "",
    }
    adapter["binding_hash"] = canonical_hash({
        key: value for key, value in adapter.items()
        if key != "binding_hash"
    })
    adapter_path = host_dir / "adapter-binding.json"
    write_json(adapter_path, adapter)
    template_path = contained_file(
        evaluator_root,
        "templates/host-manifest.example.json",
        "host manifest template",
    )
    manifest = json_object(template_path.read_bytes(), template_path)
    python = Path(shutil.which("python3") or "").resolve()
    if not python.is_file():
        raise ValueError("python3 executable is unavailable")
    command = _command(
        study,
        candidate,
        prior,
        codex_path,
        codex_hash,
    )
    catalog_hash = _identity(
        manifest,
        repository=repository,
        controller_hash=controller_content_hash,
        cli_hash=adapter["cli_sha256"],
        design=design,
        package_hash=package_hash,
    )
    manifest["command"].update({
        "argv": command,
        "resolved_executable": str(python),
        "executable_sha256": file_hash(python),
        "protocol_version": 1,
        "env_allowlist": ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH", "SSL_CERT_DIR", "SSL_CERT_FILE"],
    })
    _finish_manifest(
        manifest,
        design=design,
        command=command,
        adapter_binding=artifact_binding(adapter_path, study),
        catalog_hash=catalog_hash,
    )
    return manifest


def rebind_scenarios(
    scenarios: list[dict[str, Any]],
    host_manifest_hash: str,
) -> list[dict[str, Any]]:
    if not HASH_PATTERN.fullmatch(host_manifest_hash):
        raise ValueError("host manifest hash is invalid")
    rebound = copy.deepcopy(scenarios)
    for scenario in rebound:
        fixture = scenario.get("fixture")
        if not isinstance(fixture, dict):
            raise ValueError("scenario fixture is invalid")
        fixture["manifest"] = "host-manifest-v1.json"
        fixture["sha256"] = host_manifest_hash
    return rebound


def rebind_spec(
    spec: dict[str, Any],
    *,
    host_manifest_hash: str,
    scenarios_hash: str,
    holdout_payload_hash: str,
    holdout_manifest_hash: str,
    host_asset_hashes: dict[str, str],
) -> dict[str, Any]:
    hashes = {
        host_manifest_hash,
        scenarios_hash,
        holdout_payload_hash,
        holdout_manifest_hash,
        *host_asset_hashes.values(),
    }
    if (
        set(host_asset_hashes) != set(HOST_ASSETS)
        or any(not HASH_PATTERN.fullmatch(item) for item in hashes)
    ):
        raise ValueError("study host binding is invalid")
    rebound = copy.deepcopy(spec)
    rebound["host"]["manifest"]["sha256"] = host_manifest_hash
    suite = rebound["suite"]
    suite["scenarios"]["sha256"] = scenarios_hash
    suite["public_scenarios"]["sha256"] = scenarios_hash
    suite["holdout"]["payload"]["sha256"] = holdout_payload_hash
    suite["holdout"]["manifest"]["sha256"] = holdout_manifest_hash
    for grader in rebound["graders"]:
        if grader["type"] == "deterministic":
            grader["verifier"]["sha256"] = host_asset_hashes[
                "host_grader.py"
            ]
        elif grader["type"] == "model":
            grader["prompt"]["sha256"] = host_asset_hashes[
                "model_grader_prompt.md"
            ]
            grader["output_schema"]["sha256"] = host_asset_hashes[
                "model_judgment.schema.json"
            ]
    return rebound
