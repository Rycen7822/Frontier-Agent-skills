"""R0/R3 source, runtime, schema, archive, and capability proofs."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import os
from pathlib import Path
import sys
from typing import Any
import zipfile

from . import host
from .artifacts import (
    HASH_PATTERN,
    artifact_binding,
    assert_nofollow,
    atomic_write,
    bundle_source_hash,
    canonical_hash,
    file_hash,
    json_object,
    load_json,
    portable_inventory,
    portable_tree_inventory,
    regular_files,
    raw_hash,
    self_hashed,
    signed_clean_revision,
    tree_hash,
    verify_self_hash,
    write_or_verify_json,
)


class ProofError(RuntimeError):
    """A source-complete proof input or result is invalid."""


PRIVATE_PROBES = (
    "synchronous_single_invocation",
    "interrupted_attempt_seal",
    "no_same_request_resubmit",
    "calibration_private_wire_separation",
)
ROOT_SUBAGENT_SPAWN_REQUIREMENT = {
    "call_owner": "root",
    "tool": "spawn_agent",
    "model": "gpt-5.6-sol",
    "reasoning_effort": "max",
    "service_tier": "priority",
    "fork_turns": "none",
}
EXPECTED_SKILLS = {
    "long-document-segmented-writing",
    "skill-evaluator",
    "software-quality-workflows",
    "writing-plans",
}
CONTROLLER_FILES = {
    "__init__.py",
    "artifacts.py",
    "campaign.py",
    "cli.py",
    "context-clean-subagent-reviewer-receipt-v1.schema.json",
    "controller_testkit.py",
    "host.py",
    "host_contract.py",
    "host_grader.py",
    "model_grader_prompt.md",
    "model_judgment.schema.json",
    "planner_evidence.py",
    "reports.py",
    "reviewer_prompt.txt",
    "source_proof.py",
    "specs.py",
    "studies.py",
    "test_campaign.py",
    "test_host.py",
    "test_reports.py",
    "test_studies.py",
    "transfer.py",
    "workspace.py",
}


def release_source_hash(repo: Path) -> str:
    return bundle_source_hash(repo, EXPECTED_SKILLS)


def source_identity(repo: Path) -> dict[str, str]:
    identity = signed_clean_revision(repo)
    return {
        "candidate_revision": identity["candidate_revision"],
        "candidate_source_tree_hash": release_source_hash(repo),
    }


def controller_sources(controller_root: Path) -> list[Path]:
    root = assert_nofollow(controller_root, kind="directory")
    paths = regular_files(root)
    observed = {path.relative_to(root).as_posix() for path in paths}
    if observed != CONTROLLER_FILES:
        raise ProofError(
            "controller source inventory differs: "
            f"missing={sorted(CONTROLLER_FILES - observed)}, "
            f"extra={sorted(observed - CONTROLLER_FILES)}"
        )
    return paths


def _controller_archive(
    controller_root: Path,
    paths: list[Path],
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in paths:
            relative = path.relative_to(controller_root).as_posix()
            info = zipfile.ZipInfo(
                f"controller/{relative}",
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            mode = 0o755 if path.stat().st_mode & 0o100 else 0o644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def _controller_test_gate(
    value: dict[str, Any],
    sources: list[Path],
    controller_root: Path,
) -> dict[str, Any]:
    tests = sorted(
        (
            Path("evaluation/controller")
            / path.relative_to(controller_root)
        ).as_posix()
        for path in sources
        if path.name.startswith("test_") and path.suffix == ".py"
    )
    expected = ["python", "-m", "pytest", *tests]
    fields = {
        "argv",
        "cwd",
        "returncode",
        "stdout_bytes",
        "stdout_sha256",
        "stderr_bytes",
        "stderr_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value["argv"] != expected
        or value["cwd"] != ".worktrees/frontier-5.0"
        or value["returncode"] != 0
        or any(
            not isinstance(value[field], int) or value[field] < 0
            for field in ("stdout_bytes", "stderr_bytes")
        )
        or any(
            not isinstance(value[field], str)
            or not HASH_PATTERN.fullmatch(value[field])
            for field in ("stdout_sha256", "stderr_sha256")
        )
    ):
        raise ProofError("controller test gate is invalid")
    return value


def freeze_controller(
    *,
    controller_root: Path,
    candidate_identity: dict[str, str],
    candidate_plugin_root: Path,
    evaluator_root: Path,
    app_server_preflight: Path,
    codex_runtime: dict[str, dict[str, Any]],
    corpora: dict[str, Path],
    controller_test_gate: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    sources = controller_sources(controller_root)
    inventory = portable_inventory(controller_root, sources)
    first = _controller_archive(controller_root, sources)
    second = _controller_archive(controller_root, sources)
    if first != second:
        raise ProofError("controller archive rebuild differs")
    output_root.mkdir(parents=True, exist_ok=False)
    archive_path = output_root / "controller.zip"
    atomic_write(archive_path, first, mode=0o444, replace=False)
    preflight = load_json(app_server_preflight)
    verify_self_hash(preflight, "preflight_hash")
    try:
        runtime = host.validate_codex_runtime(codex_runtime)
    except host.HostError as exc:
        raise ProofError("Codex runtime binding is invalid") from exc
    if preflight.get("codex_runtime") != runtime:
        raise ProofError("app-server preflight runtime binding differs")
    manifest = self_hashed({
        "schema_version": "frontier-controller-freeze/5.0",
        **candidate_identity,
        "candidate_plugin_tree_hash": tree_hash(candidate_plugin_root),
        "controller_test_gate": _controller_test_gate(
            controller_test_gate,
            sources,
            controller_root,
        ),
        "controller_inventory": inventory,
        "controller_content_hash": canonical_hash(inventory),
        "stable_analyzer_source_hash": file_hash(
            contained_analyzer(evaluator_root),
        ),
        "skill_evaluator_source_hash": tree_hash(evaluator_root),
        "app_server": {
            "preflight": artifact_binding(
                app_server_preflight,
                app_server_preflight.parent,
            ),
            "preflight_hash": preflight["preflight_hash"],
            "codex_runtime": runtime,
        },
        "corpora": {
            kind: artifact_binding(path, path.parent)
            for kind, path in sorted(corpora.items())
        },
        "archive_content_hash": raw_hash(first),
        "archive_rebuild_verified": True,
    }, "manifest_hash")
    manifest_path = output_root / "controller-manifest.json"
    write_or_verify_json(manifest_path, manifest)
    archive_path.chmod(0o444)
    manifest_path.chmod(0o444)
    output_root.chmod(0o555)
    return manifest


def contained_analyzer(evaluator_root: Path) -> Path:
    return assert_nofollow(
        evaluator_root / "scripts/analyze_runs.py",
        kind="file",
    )


def freeze_corpus(
    *,
    kind: str,
    corpus_root: Path,
    manifest_path: Path,
    output: Path,
) -> dict[str, Any]:
    if kind not in {"formal", "p4"}:
        raise ProofError("corpus kind is invalid")
    root = assert_nofollow(corpus_root, kind="directory")
    manifest_binding = artifact_binding(manifest_path, root)
    inventory = portable_tree_inventory(root)
    value = self_hashed({
        "schema_version": "frontier-corpus-freeze/2.0",
        "kind": kind,
        "manifest": manifest_binding,
        "file_count": len(inventory),
        "corpus_tree_hash": canonical_hash(inventory),
    }, "freeze_hash")
    if output.exists() or output.is_symlink():
        raise ProofError(f"corpus freeze already exists: {output}")
    write_or_verify_json(output, value)
    output.chmod(0o444)
    return value


AUDIT_TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".tsv",
    ".txt",
    ".yaml",
    ".yml",
}


def audit_inventory_hash(root: Path) -> str:
    base = assert_nofollow(root, kind="directory")
    rows = []
    for current, directories, filenames in os.walk(
        base,
        topdown=True,
        followlinks=False,
    ):
        directories.sort()
        filenames.sort()
        current_path = Path(current)
        for directory in directories:
            assert_nofollow(current_path / directory, kind="directory")
        for filename in filenames:
            path = assert_nofollow(current_path / filename, kind="file")
            payload = path.read_bytes()
            sample = payload[:4096]
            file_type = "text"
            if path.suffix.lower() not in AUDIT_TEXT_SUFFIXES:
                if b"\0" in sample:
                    file_type = "binary"
                else:
                    try:
                        sample.decode("utf-8")
                    except UnicodeDecodeError:
                        file_type = "binary"
            rows.append(
                f"{path.relative_to(base).as_posix()}\t{file_type}\t"
                f"{sha256(payload).hexdigest()}\t"
            )
    return sha256("\n".join(rows).encode("utf-8")).hexdigest()
APP_SERVER_SCHEMA_REQUIREMENTS = {
    "v2/ThreadStartParams.json": (
        set(),
        {"approvalPolicy", "cwd", "ephemeral", "experimentalRawEvents", "model", "sandbox", "serviceTier"},
    ),
    "v2/TurnStartParams.json": (
        {"input", "threadId"},
        {"approvalPolicy", "cwd", "effort", "input", "model", "outputSchema", "sandboxPolicy", "serviceTier", "threadId"},
    ),
    "v2/ThreadStartResponse.json": ({"thread"}, {"thread"}),
    "v2/TurnStartResponse.json": ({"turn"}, {"turn"}),
    "v2/TurnCompletedNotification.json": (
        {"threadId", "turn"},
        {"threadId", "turn"},
    ),
    "v2/ItemCompletedNotification.json": (
        {"item", "threadId", "turnId"},
        {"item", "threadId", "turnId"},
    ),
    "v2/ThreadTokenUsageUpdatedNotification.json": (
        {"threadId", "tokenUsage", "turnId"},
        {"threadId", "tokenUsage", "turnId"},
    ),
    "v2/ModelSafetyBufferingUpdatedNotification.json": (
        {"model", "reasons", "showBufferingUi", "threadId", "turnId", "useCases"},
        {"model", "reasons", "showBufferingUi", "threadId", "turnId", "useCases"},
    ),
}


def _schema_variant(
    schema: dict[str, Any],
    definition: str,
    type_name: str,
) -> dict[str, Any]:
    variants = schema.get("definitions", {}).get(definition, {}).get("oneOf")
    if not isinstance(variants, list):
        raise ProofError(f"{definition} is not a oneOf item union")
    matches = [
        item
        for item in variants
        if item.get("properties", {}).get("type", {}).get("enum") == [type_name]
    ]
    if len(matches) != 1:
        raise ProofError(f"{definition} must contain one {type_name!r} variant")
    return matches[0]


def validate_app_server_schema_tree(schema_root: Path) -> dict[str, Any]:
    if schema_root.is_symlink() or not schema_root.is_dir():
        raise ProofError("app-server schema root is unavailable")
    entries = []
    for path in sorted(schema_root.rglob("*")):
        if path.is_symlink() or (not path.is_dir() and not path.is_file()):
            raise ProofError("app-server schema tree contains an invalid entry")
        if path.is_file():
            entries.append({
                "path": path.relative_to(schema_root).as_posix(),
                "sha256": file_hash(path),
            })
    if not entries:
        raise ProofError("app-server schema tree is empty")
    loaded = {}
    for relative, (required, properties) in APP_SERVER_SCHEMA_REQUIREMENTS.items():
        path = assert_nofollow(schema_root / relative, kind="file")
        value = json_object(path.read_bytes(), path)
        loaded[relative] = value
        if (
            not required.issubset(set(value.get("required", [])))
            or not properties.issubset(set(value.get("properties", {})))
        ):
            raise ProofError(f"{relative} is missing transport fields")
    for type_name, fields in {
        "text": {"text", "type"},
        "skill": {"name", "path", "type"},
    }.items():
        variant = _schema_variant(
            loaded["v2/TurnStartParams.json"],
            "UserInput",
            type_name,
        )
        if not fields.issubset(set(variant.get("required", []))):
            raise ProofError(f"UserInput {type_name!r} fields are incomplete")
    for type_name, fields in {
        "agentMessage": {"id", "text", "type"},
        "commandExecution": {"command", "id", "status", "type"},
    }.items():
        variant = _schema_variant(
            loaded["v2/ItemCompletedNotification.json"],
            "ThreadItem",
            type_name,
        )
        if not fields.issubset(set(variant.get("required", []))):
            raise ProofError(f"ThreadItem {type_name!r} fields are incomplete")
    usage = loaded[
        "v2/ThreadTokenUsageUpdatedNotification.json"
    ].get("definitions", {}).get("ThreadTokenUsage", {})
    if (
        not {"last", "total"}.issubset(set(usage.get("required", [])))
        or "last" not in usage.get("properties", {})
    ):
        raise ProofError("terminal token-usage fields are incomplete")
    return {
        "schema_tree_hash": canonical_hash(entries),
        "schema_file_count": len(entries),
        "validated_schema_files": sorted(APP_SERVER_SCHEMA_REQUIREMENTS),
        "scored_grader_transport": "pass",
        "root_subagent_spawn_requirement": ROOT_SUBAGENT_SPAWN_REQUIREMENT,
        "provider_request_count": 0,
    }


def _capability_request(kind: str, capability: str, ordinal: int) -> dict[str, Any]:
    value = {
        "record_type": "skill-evaluator-host-request/1",
        "request_hash": "sha256:" + "0" * 64,
        "envelope": {
            "plan_id": "pl-" + "a" * 24,
            "plan_hash": "sha256:" + "b" * 64,
            "entry_ordinal": ordinal,
            "entry_id": "pe-" + f"{ordinal:024x}"[-24:],
            "run_id": "run-" + f"{ordinal:024x}"[-24:],
            "attempt": 1 if ordinal < 2 else 2,
            "request_kind": kind,
        },
        "payload": {"capability": capability},
    }
    value["request_hash"] = canonical_hash({
        key: item for key, item in value.items() if key != "request_hash"
    })
    return value


def _load_validator(root: Path):
    path = assert_nofollow(root / "scripts/validate_eval_suite.py", kind="file")
    spec = importlib.util.spec_from_file_location("frontier_controller_validator", path)
    if spec is None or spec.loader is None:
        raise ProofError("Skill Evaluator validator cannot be imported")
    module = importlib.util.module_from_spec(spec)
    scripts = str(path.parent)
    sys.path.insert(0, scripts)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
        if sys.path[0] == scripts:
            sys.path.pop(0)
    return module


def build_capability_attestation(
    *,
    host_manifest_path: Path,
    skill_evaluator_root: Path,
) -> dict[str, Any]:
    manifest_path = assert_nofollow(host_manifest_path, kind="file")
    manifest = json_object(manifest_path.read_bytes(), manifest_path)
    validator = _load_validator(skill_evaluator_root)
    registry = validator.load_v5_schema_registry()
    capabilities = [item["capability"] for item in manifest.get("capabilities", [])]
    if (
        not capabilities
        or len(capabilities) != len(set(capabilities))
        or any(not isinstance(item, str) for item in capabilities)
    ):
        raise ProofError("host capability declarations are empty or duplicated")
    requests = {
        capability: _capability_request("probe_capability", capability, ordinal)
        for ordinal, capability in enumerate(sorted(capabilities), 1)
    }
    requests.update({
        "synchronous_single_invocation": _capability_request(
            "probe_capability", "synchronous_single_invocation", 100,
        ),
        "interrupted_attempt_seal": _capability_request(
            "cleanup", "interrupted_attempt_seal", 101,
        ),
        "no_same_request_resubmit": _capability_request(
            "probe_capability", "no_same_request_resubmit", 102,
        ),
        "calibration_private_wire_separation": _capability_request(
            "model_grade", "calibration_private_wire_separation", 103,
        ),
    })
    if (
        requests["no_same_request_resubmit"]["request_hash"]
        == requests["synchronous_single_invocation"]["request_hash"]
        or "calibration_grade"
        in set(host.all_strings(requests["calibration_private_wire_separation"]))
    ):
        raise ProofError("private host transport invariants are not closed")
    results = {}
    for capability, request in requests.items():
        records = host.pure_fake_records(request, manifest)
        result = records[-1]
        if (
            validator.validate_host_protocol_record("host_request", request, registry)
            or validator.validate_host_protocol_record("host_result", result, registry)
            or result["envelope"] != request["envelope"]
            or result["request_hash"] != request["request_hash"]
            or result["terminal_status"] != "completed"
            or result["cleanup"].get("status") != "clean"
            or result["context"].get("status") != "captured"
        ):
            raise ProofError("pure host probe did not close its protocol")
        artifact_paths = {
            item["path"] for item in result["artifacts"] if isinstance(item, dict)
        }
        if any(
            assertion["artifact"]["path"] not in artifact_paths
            for assertion in result["assertions"]
        ):
            raise ProofError("pure host probe assertion lacks artifact closure")
        results[capability] = {
            "capability": capability,
            "probe_request_hash": request["request_hash"],
            "probe_result_hash": canonical_hash(result),
            "status": "pass",
        }
    attestation = {
        "schema_version": "frontier-host-capability-attestation/1.0",
        "host_manifest_content_hash": file_hash(host_manifest_path),
        "host_adapter_content_hash": file_hash(Path(host.__file__)),
        "host_capability_results": {
            key: results[key] for key in sorted(capabilities)
        },
        "private_transport_results": {
            key: results[key] for key in PRIVATE_PROBES
        },
        "attestation_hash": "",
    }
    attestation["attestation_hash"] = canonical_hash({
        key: value for key, value in attestation.items()
        if key != "attestation_hash"
    })
    return attestation
