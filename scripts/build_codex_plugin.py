#!/usr/bin/env python3
"""Build an isolated, runtime-free Codex plugin staging tree and hash evidence."""

from __future__ import annotations

import argparse
import ctypes
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bundle_hash import bundle_inventory, inventory, tree_hash  # noqa: E402


FORBIDDEN_PLUGIN_KEYS = {"mcpServers", "apps", "hooks"}
FORBIDDEN_PLUGIN_NAMES = {".mcp.json", ".app.json", "hooks.json"}
TEXT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".py", ".template"}
EVALUATED_SKILL_IDS = [
    "software-quality-workflows",
    "writing-plans",
]
EXPECTED_FORMAL_ARM_USAGE = {
    "software-quality-workflows": {
        "scheduled": 108,
        "observed": 108,
        "graded": 12,
        "missing": 0,
        "duplicate": 0,
        "retries": 0,
        "provider_calls": 108,
    },
    "writing-plans": {
        "scheduled": 98,
        "observed": 98,
        "graded": 10,
        "missing": 0,
        "duplicate": 0,
        "retries": 0,
        "provider_calls": 98,
    },
}
EXPECTED_FORMAL_BUDGET = {
    "schema_version": "provider-budget-contract/1.0",
    "scheduled_provider_calls": 214,
    "scored_call_hard_cap": 206,
    "grader_calibration_call_hard_cap": 4,
    "reviewer_calibration_call_hard_cap": 4,
    "provider_call_hard_cap": 214,
}
EXPECTED_FORMAL_AGGREGATE_USAGE = {
    "scored_model_calls": 206,
    "grader_calibration_calls": 4,
    "reviewer_calibration_calls": 4,
    "apparatus_model_calls": 8,
    "total_provider_calls": 214,
    "retries": 0,
}
P3_AGGREGATE_FIELDS = {
    "schema_version", "candidate_revision", "candidate_source_tree_hash",
    "candidate_plugin_tree_hash", "decision_contract_content_hash",
    "evaluated_skill_ids", "arm_report_content_hashes", "aggregate_status",
    "scored_model_calls", "grader_calibration_calls",
    "reviewer_calibration_calls", "apparatus_model_calls",
    "total_provider_calls", "retries", "gates", "report_hash",
}
EXPECTED_SKILLS = {
    "long-document-segmented-writing": "1.0.0",
    "skill-evaluator": "3.0.0",
    "software-quality-workflows": "9.0.0",
    "writing-plans": "8.1.0",
}
EXPECTED_ACTIVATION = {
    "long-document-segmented-writing": True,
    "skill-evaluator": False,
    "software-quality-workflows": False,
    "writing-plans": False,
}
EXPECTED_APPROVED_ACTIVATION = {
    skill_id: "implicit" if enabled else "explicit_only"
    for skill_id, enabled in EXPECTED_ACTIVATION.items()
}
CANONICAL_MARKETPLACE = {
    "name": "frontier-engineering-v6-release",
    "plugins": [{
        "name": "frontier-engineering-plugin",
        "source": {
            "source": "local",
            "path": "./plugins/frontier-engineering-plugin",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Developer Tools",
    }],
}


def _regular_bytes(path: Path, maximum: int = 4 * 1024 * 1024) -> bytes:
    _reject_symlink_components(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"input is not a regular file: {path}")
        if info.st_size > maximum:
            raise ValueError(f"JSON input exceeds byte budget: {path}")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) > maximum:
            raise ValueError(f"JSON input exceeds byte budget: {path}")
    finally:
        os.close(descriptor)
    return value


def _decode_json(payload: bytes, path: Path) -> dict[str, Any]:

    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in {path}: {key}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number in {path}: {value}")

    value = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=pairs_hook, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _strict_json(path: Path, maximum: int = 4 * 1024 * 1024) -> dict[str, Any]:
    return _decode_json(_regular_bytes(path, maximum), path)


def _validate_schema(
    source_root: Path,
    schema_name: str,
    document: dict[str, Any],
    label: str,
) -> None:
    schema = _strict_json(source_root / "packaging" / "schemas" / schema_name)
    Draft202012Validator.check_schema(schema)
    if list(Draft202012Validator(schema).iter_errors(document)):
        raise ValueError(f"{label} is invalid")


def _validate_prior_migration_claim(skill_id: str, arm: dict[str, Any]) -> None:
    claim_id = "prior_reference_migration_claim"
    metrics = arm["metrics"]
    if skill_id != "writing-plans":
        if claim_id in metrics:
            raise ValueError("prior migration claim has the wrong arm owner")
        return
    claim = metrics.get(claim_id)
    fields = {
        "status",
        "minimum_reference_cases",
        "observed_reference_cases",
        "mixed_prior_cases",
        "reduction_selector",
        "minimum_reduction",
        "observed_reduction",
    }
    if not isinstance(claim, dict) or set(claim) != fields:
        raise ValueError("prior migration claim structure is invalid")
    reference_cases = claim["observed_reference_cases"]
    mixed_cases = claim["mixed_prior_cases"]
    reduction = claim["observed_reduction"]
    if (
        not isinstance(claim["minimum_reference_cases"], int)
        or isinstance(claim["minimum_reference_cases"], bool)
        or claim["minimum_reference_cases"] != 4
        or claim["reduction_selector"] != "lower"
        or claim["minimum_reduction"] != 0.5
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (reference_cases, mixed_cases)
        )
    ):
        raise ValueError("prior migration claim policy is invalid")
    if reference_cases < 4 or mixed_cases:
        expected_status = "unavailable"
        if reduction is not None:
            raise ValueError("unavailable prior migration claim has a reduction")
    else:
        if (
            not isinstance(reduction, (int, float))
            or isinstance(reduction, bool)
        ):
            raise ValueError("prior migration claim reduction is invalid")
        expected_status = "supported" if reduction >= 0.5 else "not_supported"
    if claim["status"] != expected_status:
        raise ValueError("prior migration claim status is invalid")


def _bytes_hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _content_hash(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"hash input is not a regular file: {path}")
        digest = sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    finally:
        os.close(descriptor)


def skill_version(path: Path) -> str:
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"(?m)^  version:\s*([^\s#]+)\s*$", text)
    if not match:
        raise ValueError(f"missing metadata.version in {path / 'SKILL.md'}")
    return match.group(1)


def skill_activation(path: Path) -> bool:
    value = yaml.safe_load((path / "agents" / "openai.yaml").read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid agents/openai.yaml object: {path}")
    policy = value.get("policy")
    if not isinstance(policy, dict) or set(policy) != {"allow_implicit_invocation"}:
        raise ValueError(f"agents/openai.yaml must declare only policy.allow_implicit_invocation: {path}")
    activation = policy["allow_implicit_invocation"]
    if not isinstance(activation, bool):
        raise ValueError(f"allow_implicit_invocation must be boolean: {path}")
    return activation


def _self_hash_field(report: dict[str, Any], field: str) -> str:
    value = dict(report)
    value.pop(field, None)
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def _self_hash(report: dict[str, Any]) -> str:
    return _self_hash_field(report, "report_hash")


def _validate_exact_bundle_identity(source_root: Path) -> None:
    builder_path = source_root / "bundle" / "build_bundle_manifest.py"
    output_path = source_root / "frontier-engineering.bundle.json"
    if builder_path.is_symlink() or not builder_path.is_file():
        raise ValueError("exact bundle identity builder is missing or symlinked")
    namespace: dict[str, Any] = {
        "__file__": str(builder_path),
        "__name__": "frontier_bundle_identity_validation",
    }
    exec(compile(builder_path.read_text(encoding="utf-8"), str(builder_path), "exec"), namespace)
    expected = namespace["build_manifest"]()
    observed = _strict_json(output_path)
    if observed != expected:
        raise ValueError("frontier-engineering.bundle.json does not match the exact four-skill source")
    rendered = (json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if output_path.is_symlink() or output_path.read_bytes() != rendered:
        raise ValueError("frontier-engineering.bundle.json is not the canonical generated artifact")


def validate_source(source_root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    skills = manifest.get("skills")
    if not isinstance(skills, list) or {item.get("id") for item in skills if isinstance(item, dict)} != set(EXPECTED_SKILLS):
        raise ValueError("manifest must declare exactly the four canonical skills")
    if (manifest.get("bundle_schema_version"), manifest.get("bundle_version")) != ("3.0", "6.0.0"):
        raise ValueError("manifest bundle schema/version is invalid")
    if {item.get("id"): item.get("version") for item in skills} != EXPECTED_SKILLS:
        raise ValueError("version mismatch: manifest skill versions do not match the four-skill release identity")
    observed_activation: dict[str, bool] = {}
    for item in skills:
        if not isinstance(item, dict) or set(item) != {"id", "path", "version"}:
            raise ValueError("manifest skill entries must contain only id, path, and version")
        if item["path"] != item["id"]:
            raise ValueError(f"manifest skill path must equal its canonical id: {item['id']}")
        path = source_root / item["path"]
        observed = skill_version(path)
        if observed != item["version"]:
            raise ValueError(f"version mismatch for {item['id']}: manifest={item['version']} skill={observed}")
        observed_activation[item["id"]] = skill_activation(path)
    if observed_activation != EXPECTED_ACTIVATION:
        raise ValueError("skill activation does not match the exact mixed activation matrix")
    _validate_exact_bundle_identity(source_root)
    if manifest.get("activation_ceiling") != "implicit_local_pilot" or manifest.get("remote_writes") is not False:
        raise ValueError("manifest activation ceiling or remote-write boundary is invalid")
    generated = _strict_json(source_root / "frontier-engineering.bundle.json")
    generated_activation = {
        skill_id: record.get("allow_implicit_invocation")
        for skill_id, record in generated.get("skills", {}).items()
        if isinstance(record, dict)
    }
    if generated_activation != EXPECTED_ACTIVATION:
        raise ValueError("generated bundle activation does not match skill metadata")
    records = bundle_inventory(source_root, manifest)
    for record in records:
        path = source_root / record["path"]
        if path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("/" + "home" + "/", "/" + "mnt" + "/" + "data" + "/", "[TODO:"):
            if marker in text:
                raise ValueError(f"reader-facing source contains forbidden local/placeholder marker: {record['path']}")
    return records


def _validate_template(template: dict[str, Any], bundle_version: str) -> dict[str, Any]:
    if FORBIDDEN_PLUGIN_KEYS & set(template):
        raise ValueError("plugin template declares a forbidden runtime surface")
    required = {"name", "version", "description", "author", "license", "keywords", "skills", "interface"}
    if not required <= set(template) or template.get("version") != "${BUNDLE_VERSION}" or template.get("skills") != "./skills/":
        raise ValueError("plugin template is missing a required portable manifest binding")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(template.get("name", ""))):
        raise ValueError("plugin name must be normalized lower-case hyphen-case")
    if template.get("name") != "frontier-engineering-plugin":
        raise ValueError("plugin template name is not the canonical release identity")
    serialized = json.dumps(template, ensure_ascii=False, sort_keys=True).lower()
    if "closure" in serialized or "autonomous" in serialized:
        raise ValueError("plugin template contains retired product identity")
    author = template.get("author")
    interface = template.get("interface")
    if not isinstance(author, dict) or not isinstance(author.get("name"), str):
        raise ValueError("plugin template requires author.name")
    required_interface = {"displayName", "shortDescription", "longDescription", "developerName", "category", "capabilities"}
    if not isinstance(interface, dict) or not required_interface <= set(interface):
        raise ValueError("plugin template lacks required interface metadata")
    prompts = interface.get("defaultPrompt", [])
    if not isinstance(prompts, list) or len(prompts) > 3 or any(not isinstance(item, str) or len(item) > 128 for item in prompts):
        raise ValueError("plugin defaultPrompt must contain at most three bounded strings")
    rendered = json.loads(json.dumps(template))
    rendered["version"] = bundle_version
    return rendered


def _git_release_source_ok(source_root: Path, revision: str) -> bool:
    commands = (
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        ["git", "-C", str(source_root), "status", "--porcelain", "--untracked-files=all", "--", "."],
        ["git", "-C", str(source_root), "verify-commit", revision],
    )
    results = [subprocess.run(command, text=True, capture_output=True, check=False, timeout=30) for command in commands]
    return results[0].returncode == 0 and results[0].stdout.strip() == revision and results[1].returncode == 0 and not results[1].stdout.strip() and results[2].returncode == 0


def validate_release_evidence(
    path: Path | None,
    *,
    source_root: Path,
    manifest: dict[str, Any],
    source_tree_hash: str,
    plugin_tree_hash: str | None = None,
) -> dict[str, Any]:
    if path is None:
        raise ValueError("dist output requires matching passed release evidence")
    _reject_symlink_components(path)
    evidence = _strict_json(path)
    _validate_schema(
        source_root,
        "release-evidence.schema.json",
        evidence,
        "release evidence",
    )
    bundle = _strict_json(source_root / "frontier-engineering.bundle.json")
    evaluator_source_hash = (
        bundle.get("skills", {})
        .get("skill-evaluator", {})
        .get("root_hash")
    )
    if (
        evidence.get("bundle_id") != bundle.get("bundle_id")
        or evidence.get("bundle_version") != manifest.get("bundle_version")
        or evidence.get("source_tree_hash") != source_tree_hash
        or evidence.get("approved_skill_activation") != EXPECTED_APPROVED_ACTIVATION
        or evidence.get("remote_writes") is not False
        or not isinstance(evaluator_source_hash, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", evaluator_source_hash)
    ):
        raise ValueError("release evidence source, bundle, or activation identity does not match")
    if plugin_tree_hash is not None and evidence.get("plugin_tree_hash") != plugin_tree_hash:
        raise ValueError("release evidence plugin tree hash does not match the staged plugin")
    revision = evidence.get("source_revision")
    if (
        evidence.get("release_gate") != "passed"
        or evidence.get("source_revision_signed") is not True
        or evidence.get("source_clean") is not True
        or not isinstance(revision, str)
        or not re.fullmatch(r"[0-9a-f]{40}", revision)
        or not _git_release_source_ok(source_root, revision)
    ):
        raise ValueError("release evidence lacks a clean signed source revision and passed release gate")

    static_report = _strict_json(source_root / "evaluation" / "static-contract-diagnostic.json")
    if (
        static_report.get("report_hash") != _self_hash(static_report)
        or evidence.get("deterministic_report_hash") != static_report.get("report_hash")
        or static_report.get("bundle_id") != bundle.get("bundle_id")
        or static_report.get("version") != manifest.get("bundle_version")
        or static_report.get("skill_activation") != EXPECTED_ACTIVATION
    ):
        raise ValueError("static contract diagnostic identity or report hash does not match")

    evidence_root = path.absolute().parent
    _require_closed_directory(
        evidence_root,
        {
            "activation-decision.json",
            "release-evidence.json",
            "l2",
            "longitudinal",
        },
        "release evidence",
    )
    l2_root = evidence_root / "l2"
    _require_closed_directory(
        l2_root,
        {
            "p3-decision-contract.json",
            "aggregate-report.json",
            *EVALUATED_SKILL_IDS,
        },
        "release evidence L2",
    )
    for skill_id in EVALUATED_SKILL_IDS:
        _require_closed_directory(
            l2_root / skill_id,
            {"report.json"},
            f"{skill_id} release arm",
        )
    _require_closed_directory(
        evidence_root / "longitudinal",
        {"report.json"},
        "release longitudinal",
    )
    aggregate_path = l2_root / "aggregate-report.json"
    aggregate_bytes = _regular_bytes(aggregate_path, 16 * 1024 * 1024)
    aggregate = _decode_json(aggregate_bytes, aggregate_path)
    if (
        set(aggregate) != P3_AGGREGATE_FIELDS
        or aggregate.get("schema_version") != "p3-aggregate-report/2.0"
        or aggregate.get("report_hash") != _self_hash(aggregate)
        or aggregate.get("evaluated_skill_ids") != EVALUATED_SKILL_IDS
        or set(aggregate.get("arm_report_content_hashes", {}))
        != set(EVALUATED_SKILL_IDS)
    ):
        raise ValueError("aggregate L2 schema, self-hash, or arm inventory is invalid")
    arm_paths = {
        skill_id: l2_root / skill_id / "report.json"
        for skill_id in aggregate["evaluated_skill_ids"]
    }
    external_paths = {
        **arm_paths,
        "decision_contract": l2_root / "p3-decision-contract.json",
        "aggregate": aggregate_path,
        "longitudinal": evidence_root / "longitudinal" / "report.json",
        "activation": evidence_root / "activation-decision.json",
    }
    external_bytes = {name: _regular_bytes(item, 16 * 1024 * 1024) for name, item in external_paths.items()}
    if external_bytes["aggregate"] != aggregate_bytes:
        raise ValueError("aggregate L2 report changed during validation")
    external = {name: _decode_json(value, external_paths[name]) for name, value in external_bytes.items()}
    hashes = {name: _bytes_hash(value) for name, value in external_bytes.items()}
    arms = {skill_id: external[skill_id] for skill_id in EVALUATED_SKILL_IDS}
    decision_contract = external["decision_contract"]
    aggregate = external["aggregate"]
    longitudinal = external["longitudinal"]
    activation = external["activation"]

    _validate_schema(
        source_root,
        "p3-decision-contract-v4.schema.json",
        decision_contract,
        "P3 decision contract",
    )
    _validate_schema(
        source_root,
        "frontier-longitudinal-report-v1.schema.json",
        longitudinal,
        "longitudinal report",
    )
    if (
        decision_contract.get("decision_contract_hash")
        != _self_hash_field(decision_contract, "decision_contract_hash")
        or decision_contract.get("candidate_revision") != revision
        or decision_contract.get("candidate_source_tree_hash") != source_tree_hash
        or decision_contract.get("candidate_plugin_tree_hash")
        != evidence.get("plugin_tree_hash")
        or decision_contract.get("evaluator_source_hash")
        != evaluator_source_hash
        or decision_contract.get("evaluated_skill_ids") != EVALUATED_SKILL_IDS
    ):
        raise ValueError("P3 decision contract identity or self-hash is invalid")
    for skill_id, arm in arms.items():
        _validate_schema(
            source_root,
            "p3-arm-report-v3.schema.json",
            arm,
            f"{skill_id} P3 arm report",
        )
        _validate_prior_migration_claim(skill_id, arm)
        expected_gates = [
            (
                gate["gate_id"],
                gate["metric_id"],
                gate["evidence_artifact_kind"],
            )
            for gate in decision_contract["gate_contract"][skill_id]
        ]
        actual_gates = [
            (
                gate["gate_id"],
                gate["metric_id"],
                gate["evidence_artifact_kind"],
            )
            for gate in arm["gate_results"]
        ]
        if (
            arm.get("study") != skill_id
            or arm.get("report_hash") != _self_hash(arm)
            or arm.get("decision_contract_content_hash")
            != hashes["decision_contract"]
            or arm.get("controller_content_hash")
            != decision_contract.get("controller_content_hash")
            or arm.get("evaluator_source_hash")
            != decision_contract.get("evaluator_source_hash")
            or arm.get("usage_closure")
            != EXPECTED_FORMAL_ARM_USAGE[skill_id]
            or actual_gates != expected_gates
            or aggregate["arm_report_content_hashes"].get(skill_id)
            != hashes[skill_id]
        ):
            raise ValueError(f"{skill_id} P3 arm report is invalid or unbound")
    if (
        aggregate.get("aggregate_status") != "passed"
        or aggregate.get("decision_contract_content_hash")
        != hashes["decision_contract"]
        or evidence.get("evaluated_skill_ids") != EVALUATED_SKILL_IDS
        or evidence.get("arm_report_content_hashes")
        != aggregate["arm_report_content_hashes"]
    ):
        raise ValueError("aggregate L2 status or arm content hash does not match")
    budget = decision_contract["budget_contract"]
    arm_provider_calls = sum(
        arm["usage_closure"]["provider_calls"] for arm in arms.values()
    )
    arm_retries = sum(arm["usage_closure"]["retries"] for arm in arms.values())
    usage = {
        field: aggregate.get(field)
        for field in EXPECTED_FORMAL_AGGREGATE_USAGE
    }
    if any(
        type(value) is not int for value in usage.values()
    ):
        raise ValueError("aggregate L2 provider usage fields must be integers")
    if (
        budget != EXPECTED_FORMAL_BUDGET
        or usage != EXPECTED_FORMAL_AGGREGATE_USAGE
        or arm_provider_calls != usage["scored_model_calls"]
        or arm_retries != usage["retries"]
    ):
        raise ValueError(
            "aggregate L2 provider usage does not match the frozen budget"
        )
    if (
        longitudinal.get("report_hash") != _self_hash(longitudinal)
        or longitudinal.get("decision_contract_content_hash")
        != hashes["decision_contract"]
        or longitudinal.get("controller_content_hash")
        != decision_contract.get("controller_content_hash")
        or longitudinal.get("evaluator_source_hash")
        != decision_contract.get("evaluator_source_hash")
    ):
        raise ValueError("longitudinal report identity or self-hash is invalid")

    expected_hashes = {
        "p3_decision_contract_hash": hashes["decision_contract"],
        "l2_scored_report_hash": hashes["aggregate"],
        "longitudinal_report_hash": hashes["longitudinal"],
        "activation_decision_hash": hashes["activation"],
    }
    if any(evidence.get(key) != value for key, value in expected_hashes.items()):
        raise ValueError("release evidence external content hash does not match")

    activation_fields = {
        "schema_version", "bundle_id", "candidate_revision", "source_tree_hash",
        "candidate_plugin_tree_hash", "p3_decision_contract_hash",
        "scored_arm_report_hashes",
        "aggregate_l2_report_hash", "longitudinal_report_hash", "approved_skill_activation",
        "remote_writes", "decision", "blocking_observations",
    }
    if (
        set(activation) != activation_fields
        or activation.get("schema_version") != "activation-decision/2.0"
        or activation.get("bundle_id") != bundle.get("bundle_id")
        or activation.get("decision") != "approve"
        or activation.get("blocking_observations") != []
        or activation.get("approved_skill_activation") != EXPECTED_APPROVED_ACTIVATION
        or activation.get("remote_writes") is not False
        or activation.get("p3_decision_contract_hash")
        != hashes["decision_contract"]
        or activation.get("scored_arm_report_hashes")
        != aggregate["arm_report_content_hashes"]
        or activation.get("aggregate_l2_report_hash") != hashes["aggregate"]
        or activation.get("longitudinal_report_hash") != hashes["longitudinal"]
    ):
        raise ValueError("activation decision is not an exact unblocked approval")

    for label, report in (
        *[(skill_id, arms[skill_id]) for skill_id in EVALUATED_SKILL_IDS],
        ("aggregate", aggregate),
        ("longitudinal", longitudinal),
    ):
        if (
            report.get("candidate_revision") != revision
            or report.get("candidate_source_tree_hash") != source_tree_hash
            or report.get("candidate_plugin_tree_hash") != evidence.get("plugin_tree_hash")
        ):
            raise ValueError(f"{label} candidate identity does not match release evidence")
    if (
        activation.get("candidate_revision") != revision
        or activation.get("source_tree_hash") != source_tree_hash
        or activation.get("candidate_plugin_tree_hash") != evidence.get("plugin_tree_hash")
    ):
        raise ValueError("activation decision candidate identity does not match release evidence")
    return evidence


def _validate_staging(staging: Path, plugin_name: str) -> list[dict[str, Any]]:
    if {path.name for path in staging.iterdir()} != {".codex-plugin", "skills"}:
        raise ValueError("plugin staging root must contain only .codex-plugin and skills")
    plugin_directory = staging / ".codex-plugin"
    if {path.name for path in plugin_directory.iterdir()} != {"plugin.json"}:
        raise ValueError(".codex-plugin must contain only plugin.json")
    manifest = _strict_json(plugin_directory / "plugin.json")
    if manifest.get("name") != plugin_name or FORBIDDEN_PLUGIN_KEYS & set(manifest):
        raise ValueError("rendered plugin manifest identity or runtime surface is invalid")
    skill_names = {path.name for path in (staging / "skills").iterdir() if path.is_dir()}
    if skill_names != set(EXPECTED_SKILLS):
        raise ValueError("staging must contain exactly the four canonical skills")
    candidates = [path for path in staging.rglob("*") if path.is_file() or path.is_symlink()]
    if any(path.name in FORBIDDEN_PLUGIN_NAMES for path in candidates):
        raise ValueError("staging contains a forbidden MCP/app/hook file")
    records = inventory(staging, candidates)
    for record in records:
        path = staging / record["path"]
        if path.suffix in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8")
            if "/" + "home" + "/" in text or "/" + "mnt" + "/" + "data" + "/" in text:
                raise ValueError(f"staging contains a developer absolute path: {record['path']}")
    return records


def _assert_skill_copy_matches(source_records: list[dict[str, Any]], plugin_records: list[dict[str, Any]]) -> None:
    plugin_by_path = {record["path"]: record for record in plugin_records}
    for source in source_records:
        if source["path"] == "bundle-manifest.json":
            continue
        target_path = "skills/" + source["path"]
        target = plugin_by_path.get(target_path)
        if target is None or any(target[field] != source[field] for field in ("content_hash", "size", "mode")):
            raise ValueError(f"E_SOURCE_DRIFT: staged skill bytes differ from frozen source inventory: {source['path']}")


def validate_plugin_build(
    plugin_root: Path,
    build_evidence_path: Path,
    *,
    source_root: Path,
    release_evidence: Path | None,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    _reject_symlink_components(plugin_root)
    _reject_symlink_components(build_evidence_path)
    plugin_root = plugin_root.resolve(strict=True)
    manifest = _strict_json(source_root / "bundle-manifest.json")
    source_records = validate_source(source_root, manifest)
    evidence = _strict_json(build_evidence_path)
    _validate_schema(
        source_root,
        "plugin-build-evidence.schema.json",
        evidence,
        "plugin build evidence",
    )
    if evidence.get("evidence_hash") != _self_hash_field(
        evidence,
        "evidence_hash",
    ):
        raise ValueError("plugin build evidence self-hash is invalid")

    plugin_records = _validate_staging(plugin_root, evidence["plugin_name"])
    versions = {
        skill_id: skill_version(plugin_root / "skills" / skill_id)
        for skill_id in EXPECTED_SKILLS
    }
    activation = {
        skill_id: skill_activation(plugin_root / "skills" / skill_id)
        for skill_id in EXPECTED_SKILLS
    }
    if (
        evidence.get("source_tree_hash") != tree_hash(source_records)
        or evidence.get("source_revision") != _source_revision(source_root)
        or evidence.get("source_file_count") != len(source_records)
        or evidence.get("plugin_tree_hash") != tree_hash(plugin_records)
        or evidence.get("plugin_file_count") != len(plugin_records)
        or evidence.get("files") != plugin_records
        or evidence.get("skill_versions") != versions
        or evidence.get("skill_activation") != activation
    ):
        raise ValueError("plugin build evidence does not match source or plugin bytes")

    output_class = evidence["output_class"]
    if output_class == "staging":
        if release_evidence is not None:
            raise ValueError("staging validation forbids release evidence")
    elif release_evidence is None:
        raise ValueError("release validation requires release evidence")
    else:
        _reject_symlink_components(release_evidence)
        if evidence.get("release_evidence_hash") != _content_hash(release_evidence):
            raise ValueError("release evidence content hash does not match build evidence")
        validate_release_evidence(
            release_evidence,
            source_root=source_root,
            manifest=manifest,
            source_tree_hash=evidence["source_tree_hash"],
            plugin_tree_hash=evidence["plugin_tree_hash"],
        )
    return evidence


def _source_revision(source_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "--show-toplevel", "HEAD"],
        text=True, capture_output=True, check=False, timeout=30,
    )
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or len(lines) != 2
        or Path(lines[0]).resolve(strict=True) != source_root.resolve(strict=True)
        or re.fullmatch(r"[0-9a-f]{40}", lines[1]) is None
    ):
        raise ValueError("source root lacks a canonical Git revision")
    return lines[1]


def _reject_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"symlinked output path component is forbidden: {cursor}")
        if not cursor.exists():
            break


def _rename_no_replace(source: Path, destination: Path) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise ValueError("atomic no-replace publication is unavailable") from None
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    ) == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise ValueError(f"no-overwrite destination appeared: {destination}")
    raise OSError(error, os.strerror(error), destination)


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"owned staging path is not a directory: {path}")
    return info.st_dev, info.st_ino


def _file_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise ValueError(f"owned staging path is not a file: {path}")
    return info.st_dev, info.st_ino


def _remove_owned_tree(path: Path, identity: tuple[int, int]) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if _directory_identity(path) != identity:
        raise RuntimeError(f"owned staging inode changed: {path}")
    shutil.rmtree(path)


def _remove_owned_file(path: Path, identity: tuple[int, int]) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if _file_identity(path) != identity:
        raise RuntimeError(f"owned staging inode changed: {path}")
    path.unlink()


def _plugin_publication_matches(
    output: Path,
    identity: tuple[int, int],
    plugin_name: str,
    records: list[dict[str, Any]],
) -> bool:
    try:
        return (
            _directory_identity(output) == identity
            and _validate_staging(output, plugin_name) == records
        )
    except (OSError, ValueError):
        return False


def _marketplace_publication_matches(
    marketplace_root: Path,
    marketplace_identity: tuple[int, int],
    manifest_identity: tuple[int, int],
    manifest_bytes: bytes,
    output: Path,
    output_identity: tuple[int, int],
    plugin_name: str,
    records: list[dict[str, Any]],
) -> bool:
    manifest_path = (
        marketplace_root / ".agents" / "plugins" / "marketplace.json"
    )
    try:
        return (
            _directory_identity(marketplace_root) == marketplace_identity
            and _file_identity(manifest_path) == manifest_identity
            and manifest_path.read_bytes() == manifest_bytes
            and _plugin_publication_matches(
                output,
                output_identity,
                plugin_name,
                records,
            )
        )
    except (OSError, ValueError):
        return False


def _require_closed_directory(
    path: Path,
    expected_entries: set[str],
    label: str,
) -> None:
    _reject_symlink_components(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} is not a regular directory")
    entries = {item.name: item for item in path.iterdir()}
    if set(entries) != expected_entries or any(
        item.is_symlink() for item in entries.values()
    ):
        raise ValueError(f"{label} inventory has missing, extra, or symlink entries")


def build(
    source_root: Path,
    output: Path,
    release_evidence: Path | None,
    evidence_output: Path,
    marketplace_root: Path | None = None,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    output = output.absolute()
    evidence_output = evidence_output.absolute()
    _reject_symlink_components(output)
    _reject_symlink_components(evidence_output)
    manifest = _strict_json(source_root / "bundle-manifest.json")
    source_records = validate_source(source_root, manifest)
    source_tree_hash = tree_hash(source_records)
    if output.exists() or evidence_output.exists():
        raise ValueError("output and evidence paths are no-overwrite")
    if evidence_output == output or evidence_output.is_relative_to(output):
        raise ValueError("build evidence must be outside the plugin staging tree")

    template = _validate_template(
        _strict_json(source_root / "packaging" / "codex-plugin" / "plugin.json.template"),
        str(manifest["bundle_version"]),
    )
    if output.name != template["name"]:
        raise ValueError(f"plugin output folder must match manifest name: {template['name']}")
    is_release = release_evidence is not None
    if is_release:
        if marketplace_root is None:
            raise ValueError("release build requires a canonical marketplace root")
        marketplace_root = marketplace_root.absolute()
        _reject_symlink_components(marketplace_root)
        if marketplace_root.exists() or marketplace_root.is_symlink():
            raise ValueError("marketplace root is no-overwrite")
        if output != marketplace_root / "plugins" / template["name"]:
            raise ValueError("release plugin output must be inside the canonical marketplace")
        if evidence_output.is_relative_to(marketplace_root):
            raise ValueError("build evidence must be outside the canonical marketplace")
        validate_release_evidence(
            release_evidence,
            source_root=source_root,
            manifest=manifest,
            source_tree_hash=source_tree_hash,
        )
    elif marketplace_root is not None:
        raise ValueError("staging build forbids a marketplace root")

    if is_release:
        assert marketplace_root is not None
        marketplace_root.parent.mkdir(parents=True, exist_ok=True)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    staging = evidence_output.parent / "plugin-build-staging"
    if staging.exists() or staging.is_symlink():
        raise ValueError("plugin build staging path is no-overwrite")
    publish_parent = marketplace_root.parent if marketplace_root is not None else output.parent
    if publish_parent.stat().st_dev != evidence_output.parent.stat().st_dev:
        raise ValueError("plugin staging and destination must share one filesystem")
    marketplace_staging = evidence_output.parent / "marketplace-build-staging"
    if is_release and (
        marketplace_staging.exists() or marketplace_staging.is_symlink()
    ):
        raise ValueError("marketplace build staging path is no-overwrite")
    staging.mkdir(mode=0o700)
    staging_identity = _directory_identity(staging)
    marketplace_staging_identity: tuple[int, int] | None = None
    marketplace_manifest_identity: tuple[int, int] | None = None
    marketplace_manifest_bytes: bytes | None = None
    evidence_temporary: Path | None = None
    evidence_identity: tuple[int, int] | None = None
    evidence_bytes: bytes | None = None
    published = False
    plugin_records: list[dict[str, Any]] | None = None

    def publication_still_matches() -> bool:
        if plugin_records is None:
            return False
        if is_release:
            if (
                marketplace_root is None
                or marketplace_staging_identity is None
                or marketplace_manifest_identity is None
                or marketplace_manifest_bytes is None
            ):
                return False
            return _marketplace_publication_matches(
                marketplace_root,
                marketplace_staging_identity,
                marketplace_manifest_identity,
                marketplace_manifest_bytes,
                output,
                staging_identity,
                template["name"],
                plugin_records,
            )
        return _plugin_publication_matches(
            output,
            staging_identity,
            template["name"],
            plugin_records,
        )

    try:
        (staging / ".codex-plugin").mkdir()
        (staging / "skills").mkdir()
        (staging / ".codex-plugin" / "plugin.json").write_text(
            json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        for item in manifest["skills"]:
            shutil.copytree(source_root / item["path"], staging / "skills" / item["id"])
        plugin_records = _validate_staging(staging, template["name"])
        _assert_skill_copy_matches(source_records, plugin_records)
        if validate_source(source_root, manifest) != source_records:
            raise ValueError("E_SOURCE_DRIFT: bundle source changed during plugin staging")
        plugin_tree_hash = tree_hash(plugin_records)
        if is_release:
            validate_release_evidence(
                release_evidence,
                source_root=source_root,
                manifest=manifest,
                source_tree_hash=source_tree_hash,
                plugin_tree_hash=plugin_tree_hash,
            )
        release_evidence_hash = _content_hash(release_evidence) if release_evidence is not None else None
        evidence: dict[str, Any] = {
            "schema_version": "plugin-build-evidence/3.0",
            "bundle_id": _strict_json(source_root / "frontier-engineering.bundle.json")["bundle_id"],
            "bundle_version": manifest["bundle_version"],
            "skill_versions": {item["id"]: item["version"] for item in sorted(manifest["skills"], key=lambda item: item["id"])},
            "skill_activation": dict(EXPECTED_ACTIVATION),
            "source_tree_hash": source_tree_hash,
            "source_revision": _source_revision(source_root),
            "source_file_count": len(source_records),
            "plugin_tree_hash": plugin_tree_hash,
            "plugin_file_count": len(plugin_records),
            "plugin_name": template["name"],
            "output_class": "release" if is_release else "staging",
            "release_evidence_hash": release_evidence_hash,
            "activation_ceiling": manifest["activation_ceiling"],
            "files": plugin_records,
        }
        evidence["evidence_hash"] = "sha256:" + sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        _validate_schema(
            source_root,
            "plugin-build-evidence.schema.json",
            evidence,
            "plugin build evidence",
        )
        descriptor, temporary_name = tempfile.mkstemp(prefix="plugin-build-evidence-", dir=evidence_output.parent)
        evidence_temporary = Path(temporary_name)
        evidence_identity = _file_identity(evidence_temporary)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _file_identity(evidence_temporary) != evidence_identity:
            raise RuntimeError("build evidence staging inode changed")
        evidence_bytes = evidence_temporary.read_bytes()
        if is_release:
            assert marketplace_root is not None
            marketplace_staging.mkdir(mode=0o700)
            marketplace_staging_identity = _directory_identity(
                marketplace_staging
            )
            (marketplace_staging / "plugins").mkdir()
            marketplace_manifest = (
                marketplace_staging / ".agents" / "plugins" / "marketplace.json"
            )
            marketplace_manifest.parent.mkdir(parents=True)
            marketplace_manifest_bytes = (
                json.dumps(
                    CANONICAL_MARKETPLACE,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
            marketplace_manifest.write_bytes(marketplace_manifest_bytes)
            marketplace_manifest_identity = _file_identity(
                marketplace_manifest
            )
            staging.rename(
                marketplace_staging / "plugins" / template["name"],
            )
            _rename_no_replace(marketplace_staging, marketplace_root)
        else:
            _rename_no_replace(staging, output)
        published = True
        if not publication_still_matches():
            raise ValueError("published plugin tree changed during publication")
        assert evidence_identity is not None
        assert evidence_bytes is not None
        os.link(evidence_temporary, evidence_output)
        if (
            _file_identity(evidence_output) != evidence_identity
            or evidence_output.read_bytes() != evidence_bytes
        ):
            raise ValueError("published build evidence changed")
        _remove_owned_file(evidence_temporary, evidence_identity)
        evidence_temporary = None
        if (
            _file_identity(evidence_output) != evidence_identity
            or evidence_output.read_bytes() != evidence_bytes
        ):
            raise ValueError("published build evidence readback differs")
        if not publication_still_matches():
            raise ValueError(
                "published plugin tree changed after evidence publication"
            )
        return evidence
    except BaseException:
        if evidence_identity is not None and (
            evidence_output.exists() or evidence_output.is_symlink()
        ):
            try:
                if _file_identity(evidence_output) == evidence_identity:
                    _remove_owned_file(
                        evidence_output,
                        evidence_identity,
                    )
            except (OSError, ValueError):
                pass
        if (
            published
            and not staging.exists()
            and publication_still_matches()
        ):
            if is_release:
                assert marketplace_root is not None
                _rename_no_replace(marketplace_root, marketplace_staging)
            else:
                _rename_no_replace(output, staging)
        if is_release and marketplace_staging.exists():
            staged_plugin = (
                marketplace_staging / "plugins" / template["name"]
            )
            if staged_plugin.exists() and not staging.exists():
                _rename_no_replace(staged_plugin, staging)
            assert marketplace_staging_identity is not None
            _remove_owned_tree(
                marketplace_staging,
                marketplace_staging_identity,
            )
        if staging.exists() or staging.is_symlink():
            _remove_owned_tree(staging, staging_identity)
        if evidence_temporary is not None and evidence_identity is not None:
            _remove_owned_file(evidence_temporary, evidence_identity)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--release-evidence", type=Path)
    parser.add_argument("--marketplace-root", type=Path)
    parser.add_argument("--validate-plugin-root", type=Path)
    parser.add_argument("--build-evidence", type=Path)
    args = parser.parse_args(argv)

    validation_mode = (
        args.validate_plugin_root is not None
        or args.build_evidence is not None
    )
    if validation_mode:
        if (
            args.validate_plugin_root is None
            or args.build_evidence is None
            or args.output is not None
            or args.evidence_output is not None
            or args.marketplace_root is not None
        ):
            return 2
        try:
            validate_plugin_build(
                args.validate_plugin_root,
                args.build_evidence,
                source_root=args.source_root,
                release_evidence=args.release_evidence,
            )
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.SubprocessError,
        ):
            return 2
        return 0

    if args.output is None or args.evidence_output is None:
        print(json.dumps({
            "ok": False,
            "error": "build mode requires --output and --evidence-output",
        }, ensure_ascii=False))
        return 1
    try:
        evidence = build(
            args.source_root,
            args.output,
            args.release_evidence,
            args.evidence_output,
            args.marketplace_root,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "ok": True,
        "plugin_name": evidence["plugin_name"],
        "output_class": evidence["output_class"],
        "plugin_tree_hash": evidence["plugin_tree_hash"],
        "evidence_hash": evidence["evidence_hash"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
