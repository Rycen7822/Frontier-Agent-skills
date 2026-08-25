#!/usr/bin/env python3
"""Materialize self-contained formal-plan inputs without provider calls."""

from __future__ import annotations

import copy
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

import yaml

from _bundle_hash import inventory, tree_hash
from _model_evolution_contract import (
    ContractError,
    SKILL_IDS,
    canonical_bytes,
    content_hash,
    load_json,
    load_jsonl,
    resolve_binding,
    validate_formal_plan_timeouts,
    validate_formal_timeout_inputs,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_SCRIPTS = REPOSITORY_ROOT / "skill-evaluator/scripts"
sys.path.insert(0, str(EVALUATOR_SCRIPTS))

import validate_eval_suite as evaluator  # noqa: E402

from _model_evolution_apparatus import (
    materialized_attempt_policy,
    validate_apparatus_retry_policy,
)


class MaterializationError(ValueError):
    """Formal-plan inputs cannot be derived exactly from frozen evidence."""


HOST_ARTIFACT_AUTHORITY_VERSION = "host-artifact-authority/1"
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def _file_hash(path: Path) -> str:
    return "sha256:" + sha256(path.read_bytes()).hexdigest()


def _host_verifier_revision(host: dict[str, Any]) -> str:
    repository = host.get("identity", {}).get("repository")
    revision = repository.get("revision") if isinstance(repository, dict) else None
    if (
        not isinstance(revision, str)
        or _REVISION_RE.fullmatch(revision) is None
        or revision == "0" * 40
    ):
        raise MaterializationError(
            "Host apparatus repository revision is missing or still a template value"
        )
    return revision


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
    _copy_file(source, target, expected_hash=binding.get("digest"))
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
    product: tuple[dict[str, Any], str, str] | None = None,
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
    skills, source_commit, _ = product or _selected_product(campaign, role)
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


def _authority_document(value: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("schema_version") != HOST_ARTIFACT_AUTHORITY_VERSION:
        raise MaterializationError("Host artifact authority version is unsupported")
    bindings = value.get("bindings")
    if not isinstance(bindings, list) or not bindings:
        raise MaterializationError("Host artifact authority bindings are missing")
    if [item.get("index") for item in bindings if isinstance(item, dict)] != list(range(len(bindings))):
        raise MaterializationError("Host artifact authority indices are not contiguous")
    for item in bindings:
        if (
            not isinstance(item, dict)
            or set(item) != {"index", "path", "root", "digest", "encoding"}
            or item["root"] not in {"repository", "campaign"}
            or not isinstance(item["digest"], str)
            or len(item["digest"]) != 71
            or not item["digest"].startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in item["digest"][7:])
            or item["encoding"] not in {"utf-8", "binary"}
        ):
            raise MaterializationError("Host artifact authority binding shape is invalid")
    return bindings


def host_artifact_authority_document(
    host: dict[str, Any], *, repository_root: Path, campaign_root: Path,
    root: str = "repository",
) -> dict[str, Any]:
    if root not in {"repository", "campaign"}:
        raise MaterializationError("Host artifact authority root is invalid")
    probes = [item.get("probe") for item in host.get("capabilities", [])]
    probes.append(host.get("reset", {}).get("probe"))
    bindings: list[dict[str, Any]] = []
    for index, probe in enumerate(probes):
        if not isinstance(probe, dict) or not isinstance(probe.get("artifact"), dict):
            raise MaterializationError(f"Host artifact {index} has no binding")
        artifact = probe["artifact"]
        relative = _relative_path(artifact.get("path"), label="Host artifact")
        source_root = repository_root if root == "repository" else campaign_root
        source = source_root.joinpath(*relative.parts)
        if source.is_symlink() or not source.is_file():
            raise MaterializationError("Host artifact authority source is not a regular file")
        bindings.append(
            {
                "index": index,
                "path": relative.as_posix(),
                "root": root,
                "digest": _file_hash(source),
                "encoding": artifact.get("encoding"),
            }
        )
    _authority_document({"schema_version": HOST_ARTIFACT_AUTHORITY_VERSION, "bindings": bindings})
    return {"schema_version": HOST_ARTIFACT_AUTHORITY_VERSION, "bindings": bindings}


def observed_host_artifact_authority_document(
    host: dict[str, Any], previous: dict[str, Any],
    terminal_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    previous_rows = _authority_document(previous)
    probes = [item.get("probe") for item in host.get("capabilities", [])]
    probes.append(host.get("reset", {}).get("probe"))
    if len(previous_rows) != len(probes):
        raise MaterializationError("previous Host artifact authority count differs from Host")
    terminal_pairs = {
        (item.get("path"), item.get("digest")): item for item in terminal_bindings
    }
    bindings: list[dict[str, Any]] = []
    for index, probe in enumerate(probes):
        if not isinstance(probe, dict) or not isinstance(probe.get("artifact"), dict):
            raise MaterializationError(f"Observed Host artifact {index} has no binding")
        artifact = probe["artifact"]
        pair = (artifact.get("path"), artifact.get("digest"))
        if pair in terminal_pairs:
            root = "campaign"
        else:
            old = previous_rows[index]
            if old["path"] != artifact.get("path") or old["digest"] != artifact.get("digest"):
                raise MaterializationError("Observed Host artifact has no exact authority lineage")
            root = old["root"]
        bindings.append(
            {
                "index": index,
                "path": artifact["path"],
                "root": root,
                "digest": artifact["digest"],
                "encoding": artifact["encoding"],
            }
        )
    return {"schema_version": HOST_ARTIFACT_AUTHORITY_VERSION, "bindings": bindings}


def _repository_tracked(repository_root: Path, relative: PurePosixPath) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "--error-unmatch", "--", relative.as_posix()],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == relative.as_posix()


def _host_artifact_source(
    binding: dict[str, Any], *, repository_root: Path, campaign_root: Path,
    authority_version: str | None = None,
) -> Path:
    relative = _relative_path(binding.get("path"), label="Host artifact")
    if authority_version is None:
        # Legacy v2 Hosts intentionally keep their historical repository-only
        # behavior. This branch is never used by the D29 explicit contract.
        repository_candidate = repository_root.joinpath(*relative.parts)
        if (
            repository_candidate.is_file()
            and not repository_candidate.is_symlink()
            and _file_hash(repository_candidate) == binding.get("digest")
        ):
            return repository_candidate
        campaign_candidate = campaign_root.joinpath(*relative.parts)
        if campaign_candidate.is_file() and not campaign_candidate.is_symlink():
            raise MaterializationError(
                "legacy Host artifact authority is repository, but only a campaign "
                f"copy is available: {relative}"
            )
        raise MaterializationError(
            f"legacy Host artifact must resolve to one exact repository source: {relative}"
        )
    if authority_version != HOST_ARTIFACT_AUTHORITY_VERSION:
        raise MaterializationError("Host artifact authority version is unsupported")
    if set(binding) == {"index", "root", "path", "digest", "encoding"}:
        if not isinstance(binding.get("index"), int) or binding["index"] < 0:
            raise MaterializationError("explicit Host artifact index is invalid")
        binding = {
            field: binding[field]
            for field in ("root", "path", "digest", "encoding")
        }
    if set(binding) != {"root", "path", "digest", "encoding"}:
        raise MaterializationError("explicit Host artifact binding shape is invalid")
    root_name = binding.get("root")
    if root_name not in {"repository", "campaign"}:
        raise MaterializationError("explicit Host artifact root is invalid")
    if not isinstance(binding.get("digest"), str) or not binding["digest"].startswith("sha256:"):
        raise MaterializationError("explicit Host artifact digest is invalid")
    root = repository_root if root_name == "repository" else campaign_root
    root = root.resolve(strict=True)
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise MaterializationError(
            f"Host artifact is missing or symlinked in declared {root_name} root: {relative}"
        )
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise MaterializationError("Host artifact escapes its declared root")
    if root_name == "repository" and not _repository_tracked(repository_root, relative):
        raise MaterializationError(
            f"repository Host artifact is not tracked: {relative}"
        )
    if _file_hash(resolved) != binding["digest"]:
        raise MaterializationError(
            f"Host artifact digest differs in declared {root_name} root: {relative}"
        )
    return resolved


def _host_artifact_inventory(
    host: dict[str, Any], *, repository_root: Path, campaign_root: Path,
    authority: dict[str, Any] | None = None,
    require_explicit: bool = False,
) -> list[dict[str, Any]]:
    authority_rows = _authority_document(authority) if authority is not None else None
    if require_explicit and authority_rows is None:
        raise MaterializationError("Host lacks the D29 artifact authority contract")
    probes = [item.get("probe") for item in host.get("capabilities", [])]
    probes.append(host.get("reset", {}).get("probe"))
    if authority_rows is not None and len(authority_rows) != len(probes):
        raise MaterializationError("Host artifact authority count differs from Host")
    inventory_rows: list[dict[str, Any]] = []
    for index, probe in enumerate(probes):
        if not isinstance(probe, dict) or not isinstance(probe.get("artifact"), dict):
            raise MaterializationError(f"Host artifact {index} has no binding")
        binding = probe["artifact"]
        if probe.get("locator", {}).get("artifact") != binding.get("path"):
            raise MaterializationError(f"Host artifact {index} locator differs from binding")
        if authority_rows is not None:
            authority_binding = authority_rows[index]
            if authority_binding["path"] != binding.get("path") or authority_binding["digest"] != binding.get("digest"):
                raise MaterializationError("Host artifact locator differs from authority binding")
            binding = {
                field: authority_binding[field]
                for field in ("root", "path", "digest", "encoding")
            }
        source = _host_artifact_source(
            binding,
            repository_root=repository_root,
            campaign_root=campaign_root,
            authority_version=(HOST_ARTIFACT_AUTHORITY_VERSION if authority_rows is not None else None),
        )
        inventory_rows.append(
            {
                "index": index,
                "root": binding.get("root", "repository"),
                "path": binding["path"],
                "digest": binding.get("digest"),
                "source": str(source),
            }
        )
    return inventory_rows


def _copy_host_artifacts(
    host: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    target_root: Path,
    authority: dict[str, Any] | None = None,
) -> None:
    for row, probe in zip(
        _host_artifact_inventory(
            host,
            repository_root=repository_root,
            campaign_root=campaign_root,
            authority=authority,
        ),
        [item.get("probe") for item in host.get("capabilities", [])]
        + [host.get("reset", {}).get("probe")],
        strict=True,
    ):
        binding = probe["artifact"]
        source = Path(row["source"])
        relative = _relative_path(binding["path"], label="Host probe artifact")
        _copy_file(
            source,
            target_root.joinpath(*relative.parts),
            expected_hash=binding["digest"],
        )


def validate_materialization_inputs(
    *,
    host: dict[str, Any],
    sentinel: dict[str, Any],
    authority: dict[str, Any] | None,
    repository_root: Path,
    campaign_root: Path,
) -> dict[str, Any]:
    """Run the production resolver over all pre-provider Host inputs."""
    inventory_rows = _host_artifact_inventory(
        host,
        repository_root=repository_root,
        campaign_root=campaign_root,
        authority=authority,
        require_explicit=True,
    )
    resolved_bindings = 0
    for skill_id in SKILL_IDS:
        record = sentinel["skills"][skill_id]
        bindings = [
            record["spec_template"],
            record["public_scenarios"],
            record["calibration_gold"],
            *record["fixture_roots"],
            *record["verifier_roots"],
        ]
        for binding in bindings:
            resolve_binding(binding, repository_root, campaign_root)
            resolved_bindings += 1
    for binding in (
        sentinel["revision_policy"],
        sentinel["manual_authority_protocol"],
        sentinel["case_lineage"],
        sentinel["power_sensitivity"],
        *sentinel["catalog_files"],
    ):
        resolve_binding(binding, repository_root, campaign_root)
        resolved_bindings += 1
    return {
        "schema_version": "model-evolution-materialization-gate/1",
        "authority_version": HOST_ARTIFACT_AUTHORITY_VERSION,
        "host_artifacts": inventory_rows,
        "resolved_bindings": resolved_bindings,
    }


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
    preserve_repository_identity: bool = False,
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
                    "digest": calibration_file_hash,
                    "encoding": "utf-8",
                },
                "locator": {
                    "kind": "json_pointer",
                    "artifact": "grader-calibration.json",
                    "json_pointer": "/metrics",
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
                    "root_digest": selected_skills[skill_id]["root_hash"],
                    "version": selected_skills[skill_id]["version"],
                }
            )
            if not isinstance(item["description"], str) or not item["description"]:
                raise MaterializationError(f"Skill description is invalid: {skill_id}")
            refreshed.append(item)
        catalog_id = f"frontier-{source_commit[:12]}"
        host["catalog"] = {"entries": refreshed, "catalog_id": catalog_id}
        execution = host["identity"]["execution"]
        execution["catalog_id"] = catalog_id
        if not preserve_repository_identity:
            host["identity"]["repository"] = {
                "dirty": False,
                "revision": source_commit,
                "tree": source_tree,
                "worktree": str(repository_root.resolve(strict=True)),
            }
    return host


def _copy_calibration(
    calibration_source: Path, *, target_root: Path
) -> tuple[dict[str, Any], Path]:
    calibration = load_json(calibration_source, label="recorded grader calibration")
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


def provider_free_calibration_preview(
    *,
    skill_id: str,
    template: dict[str, Any],
    labels_source: Path,
    scenarios_source: Path,
    host: dict[str, Any],
    target_root: Path,
) -> Path:
    """Create a temporary calibration input for ready-contract projection.

    The preview is derived only from tracked gold labels and the selected Host
    identity.  It is validated by the production calibration command and is
    never bound into campaign state or counted as observed calibration.
    """
    preview_root = target_root / "provider-free-calibration"
    preview_root.mkdir(parents=True, exist_ok=True)
    labels = load_jsonl(labels_source, label="calibration gold")
    if not labels:
        raise MaterializationError("calibration gold is empty")
    model_grader = [
        item for item in template.get("graders", [])
        if item.get("type") == "model"
    ]
    if len(model_grader) != 1:
        raise MaterializationError("provider-free preview requires one model grader")
    model_grader = model_grader[0]
    execution = host.get("identity", {}).get("execution", {})
    host_identity = host.get("identity", {})
    model = execution.get("model")
    model_revision = execution.get("model_revision")
    host_id = host_identity.get("host_id")
    host_version = host_identity.get("host_version")
    if not all(
        isinstance(value, str) and value
        for value in (model, model_revision, host_id, host_version)
    ):
        raise MaterializationError("Host identity is incomplete for calibration preview")

    created = "2026-01-01T00:00:00Z"
    expires = "2027-01-01T00:00:00Z"
    spec = copy.deepcopy(template)
    spec["execution"]["as_of"] = "2026-06-01T00:00:00Z"
    spec["subject"]["claimed_hosts"] = [host_id]
    spec["host"]["manifest"] = {"path": "host.json"}
    spec["suite"]["scenarios"] = {"path": "scenarios.public.jsonl"}
    spec["suite"]["public_scenarios"] = {"path": "scenarios.public.jsonl"}
    model_grader = next(
        item for item in spec["graders"] if item.get("type") == "model"
    )
    model_grader["model"] = model

    labels_path = preview_root / "calibration-gold.jsonl"
    preview_labels: list[dict[str, Any]] = []
    for label in labels:
        if not isinstance(label, dict):
            raise MaterializationError("calibration gold row is not an object")
        row = copy.deepcopy(label)
        row["host"] = host_id
        row["model"] = model
        preview_labels.append(row)
    _write_exact(
        labels_path,
        b"".join(canonical_bytes(row) + b"\n" for row in preview_labels),
    )
    _copy_file(scenarios_source, preview_root / "scenarios.public.jsonl")
    _write_exact(preview_root / "host.json", canonical_bytes(host))
    _write_exact(preview_root / "spec.json", canonical_bytes(spec))

    labels_digest = _file_hash(labels_path)
    ratings: list[dict[str, Any]] = []
    for position, label in enumerate(preview_labels, start=1):
        ratings.append(
            {
                "schema_version": 3,
                "rating_id": f"preview-rating-{position:02d}",
                "example_id": label["example_id"],
                "grader_id": model_grader["grader_id"],
                "dimension": label["dimension"],
                "check_id": label["check_id"],
                "label": label["gold_label"],
                "severity": label["gold_severity"],
                "position": position,
                "blinded_treatment_labels": True,
                "reviewer": {
                    "reviewer_id": "provider-free-preview-judge",
                    "role": "judge",
                    "authority": "calibration-owner",
                    "principal_id": "provider-free-preview-judge-principal",
                    "blinded": True,
                },
                "grader_identity": {
                    "grader_id": model_grader["grader_id"],
                    "model": model,
                    "model_revision": model_revision,
                    "prompt_id": model_grader["prompt_id"],
                    "schema_id": model_grader["schema_id"],
                },
                "independence_facts": {
                    "candidate_principal_id": "provider-free-preview-candidate",
                    "grader_principal_id": "provider-free-preview-judge-principal",
                    "context_mode": "fresh",
                    "rationale_exposed": False,
                    "candidate_model_genealogy": ["provider-free-preview-candidate"],
                    "grader_model_genealogy": ["provider-free-preview-grader"],
                    "candidate_evidence_source_ids": ["provider-free-preview-input"],
                    "grader_evidence_source_ids": ["provider-free-preview-gold"],
                },
                "ordering": {
                    "method": "counterbalanced",
                    "seed": 0,
                    "schedule_id": model_grader["batch_schedule_id"],
                },
                "created": created,
                "expires": expires,
                "drift_triggers": [
                    {
                        "field": "prompt_id",
                        "expected": model_grader["prompt_id"],
                        "observed": model_grader["prompt_id"],
                        "status": "unchanged",
                    },
                    {
                        "field": "host_version",
                        "expected": host_version,
                        "observed": host_version,
                        "status": "unchanged",
                    },
                ],
                "adjudication_policy": "provider-free ready projection only",
                "thresholds": {"minimum_agreement": 0.8, "minimum_examples": 8},
                "execution_profile": {
                    "host_id": host_id,
                    "host_version": host_version,
                    "harness": execution["harness"],
                    "harness_version": execution["harness_version"],
                    "model_genealogy": ["provider-free-preview-grader"],
                    "context_exposure": [],
                    "evidence_sources": [
                        {"path": labels_path.name, "digest": labels_digest}
                    ],
                },
            }
        )
    ratings_path = preview_root / "calibration-ratings.jsonl"
    _write_exact(
        ratings_path,
        b"".join(canonical_bytes(row) + b"\n" for row in ratings),
    )
    calibration_path = preview_root / "grader-calibration.json"
    _run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "skill-evaluator/scripts/validate_eval_suite.py"),
            "calibration",
            "--spec", str(preview_root / "spec.json"),
            "--ratings", str(ratings_path),
            "--labels", str(labels_path),
            "--output", str(calibration_path),
        ],
        repository_root=REPOSITORY_ROOT,
        label=f"{skill_id} provider-free calibration preview",
    )
    return calibration_path


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
        _copy_file(source, target_root / relative)

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
    value["custody"]["split_bindings"] = evaluator._quality_split_bindings(
        spec, scenarios
    )
    return value


def _bind_scenarios(spec: dict[str, Any], scenarios: list[dict[str, Any]]) -> None:
    case_ids = [row["case_id"] for row in scenarios]
    tags = sorted({tag for row in scenarios for tag in row["tags"]})
    for treatment in spec["treatments"]:
        treatment["scenario_ids"] = case_ids
        treatment["scenario_tags"] = tags


def _materialized_spec(
    template: dict[str, Any],
    *,
    skill_id: str,
    selected_skill: dict[str, Any],
    source_commit: str,
    host: dict[str, Any],
    calibration: dict[str, Any],
    calibration_file_hash: str,
    scenarios: list[dict[str, Any]],
    runner_attempt_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = copy.deepcopy(template)
    spec["execution"]["as_of"] = calibration["created"]
    spec["execution"]["ready"] = False
    spec["subject"]["claimed_hosts"] = [host["identity"]["host_id"]]
    spec["subject"]["version"] = selected_skill["version"]
    spec["subject"]["package"] = {
        "path": "package",
        "package_digest": selected_skill["root_hash"],
        "source_revision": source_commit,
        "dirty_state": "clean",
    }
    spec["host"]["manifest"] = {"path": "host.json"}
    verifier_revision = _host_verifier_revision(host)
    for grader in spec["graders"]:
        if grader["type"] == "deterministic":
            grader["verifier"]["source_revision"] = verifier_revision
    model_grader = next(item for item in spec["graders"] if item["type"] == "model")
    model_grader["model"] = host["identity"]["execution"]["model"]
    spec["suite"]["calibration"] = {
        "path": "grader-calibration.json",
        "digest": calibration_file_hash,
        "schema_version": "grader-calibration/3",
    }
    _bind_scenarios(spec, scenarios)
    if runner_attempt_policy is not None:
        spec["execution"]["retry_policy"] = copy.deepcopy(runner_attempt_policy)
    return spec


def _campaign_runner_attempt_policy(
    campaign: dict[str, Any], *, role: str, repository_root: Path, campaign_root: Path
) -> dict[str, Any] | None:
    binding = campaign.get("apparatus_retry_policy")
    if binding is None:
        return None
    policy = validate_apparatus_retry_policy(
        load_json(
            resolve_binding(binding, repository_root, campaign_root),
            label="apparatus retry policy",
        )
    )
    if role not in policy["scope"]["roles"]:
        return None
    return materialized_attempt_policy(policy)


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
    product: tuple[dict[str, Any], str, str] | None = None,
    source_repository_root: Path | None = None,
    preserve_host_repository: bool = False,
    calibration_source: Path | None = None,
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
    calibration_source = calibration_source or resolve_binding(
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
        product=product,
    )
    _copy_file(plugin_evidence, root / "selected-plugin-build.json")
    _, source_commit, source_tree = product or _selected_product(campaign, role)

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
        authority=(
            load_json(
                resolve_binding(
                    campaign["host_artifact_authority"],
                    repository_root,
                    campaign_root,
                ),
                label="Host artifact authority",
            )
            if campaign.get("host_artifact_authority") is not None
            else None
        ),
    )
    host_path = root / "host.json"
    retarget = role in {"target_candidate", "target_prior"}
    selected_repository_root = source_repository_root or repository_root
    if not retarget and _plugin_argument(base_host) != plugin_root.resolve(strict=True):
        raise MaterializationError("observed Host plugin differs from selected staging")
    host = promoted_model_grading_host(
        base_host,
        host_path=final_root / "host.json",
        calibration_file_hash=_file_hash(calibration_path),
        plugin_root=plugin_root if retarget else None,
        selected_skills=selected_skills if retarget else None,
        repository_root=selected_repository_root if retarget else None,
        source_commit=source_commit if retarget else None,
        source_tree=source_tree if retarget else None,
        preserve_repository_identity=preserve_host_repository,
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
        host=host,
        calibration=calibration,
        calibration_file_hash=_file_hash(calibration_path),
        scenarios=scenarios,
        runner_attempt_policy=_campaign_runner_attempt_policy(
            campaign,
            role=role,
            repository_root=repository_root,
            campaign_root=campaign_root,
        ),
    )
    try:
        validate_formal_timeout_inputs(host, spec, scenarios)
    except ContractError as exc:
        raise MaterializationError(str(exc)) from exc
    if role == "target_candidate":
        scenario_binding = {"path": scenario_path.name}
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
    spec["suite"]["quality"] = {
        "path": quality_path.name,
        "digest": _file_hash(quality_path),
        "schema_version": "suite-quality/2",
    }
    spec["execution"]["ready"] = True
    spec_path.write_bytes(canonical_bytes(spec))
    plan_path = root / "plan.json"
    _compile_and_validate(root, repository_root=repository_root, plan_path=plan_path)
    plan = load_json(plan_path, label="compiled formal plan")
    try:
        validate_formal_plan_timeouts(host, plan)
    except ContractError as exc:
        raise MaterializationError(str(exc)) from exc
    return {
        "root": root,
        "spec": spec_path,
        "host": host_path,
        "plan": plan_path,
        "plan_id": plan["plan_id"],
        "plan_digest": _file_hash(plan_path),
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
