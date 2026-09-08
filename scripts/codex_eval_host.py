#!/usr/bin/env python3
"""Run bound Codex CLI requests behind the Skill Evaluator host protocol."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any

from _codex_eval_artifacts import (
    ArtifactError,
    WorkspaceEvidence,
    build_command_trace,
    build_host_observation,
)
from _codex_eval_delivery import (
    DeliveryError,
    ensure_trusted_workspace,
    force_loaded_prompt,
    forced_probe_delivery,
    is_workspace_infrastructure,
    isolated_tool_schema_id,
    RUNTIME_SURFACE_VERSION,
    observed_permission_denials,
    observed_skill_routing,
    prepare_workspace,
    project_command_environment,
    skill_isolation_argv,
    treatment_delivery,
    validate_plugin_catalog,
)
from _codex_transport_diagnostic import capture_child
from _codex_lifecycle_contract import (
    LEGACY_CONTRACT,
    V2_CONTRACT,
    classify_lifecycle,
)
from _codex_eval_events import (
    ITEM_TYPES,
    MAX_JSONL_BYTES,
    MAX_RECORDS,
    base_host_result,
    bind_model_grade_output,
    execute_evidence_diagnostics,
    host_protocol_error,
    model_grade_schema,
    normalize_jsonl,
    project_execute_result,
)
from _codex_eval_isolation import (
    ISOLATED_OUTPUT,
    ISOLATED_SANDBOX_POLICY_IDS,
    LEGACY_ISOLATED_SANDBOX_POLICY_IDS,
    ISOLATED_WORKSPACE,
    IsolationError,
    command_permission_argv,
    isolated_child_argv,
    request_codex_home,
)


MAX_STDERR_BYTES = 64 * 1024
MAX_FAILURE_DETAIL_CHARS = 2048
MAX_FAILURE_PROJECTION_CHARS = 512
LEGACY_ADAPTER_VERSION = "1.13"
PREVIOUS_ADAPTER_VERSION = "1.14"
D38_ADAPTER_VERSION = "1.15"
D39_ADAPTER_VERSION = "1.16"
D40_ADAPTER_VERSION = "1.17"
D42_ADAPTER_VERSION = "1.18"
D43_ADAPTER_VERSION = "1.19"
D44_ADAPTER_VERSION = "1.20"
ADAPTER_VERSION = "1.21"
ADAPTER_SOURCE_FILES = (
    "_bundle_hash.py",
    "_codex_eval_artifacts.py",
    "_codex_eval_delivery.py",
    "_codex_eval_events.py",
    "_codex_eval_isolation.py",
    "_codex_lifecycle_contract.py",
    "_codex_transport_diagnostic.py",
    "codex_eval_host.py",
)
PROBE_RESULT_SCHEMA_VERSION_LEGACY = "codex-interaction-probe-result/1.2"
PROBE_RESULT_SCHEMA_VERSION_PREVIOUS = "codex-interaction-probe-result/1.3"
PROBE_RESULT_SCHEMA_VERSION_D38 = "codex-interaction-probe-result/1.4"
PROBE_RESULT_SCHEMA_VERSION_D39 = "codex-interaction-probe-result/1.5"
PROBE_RESULT_SCHEMA_VERSION_D40 = "codex-interaction-probe-result/1.6"
PROBE_RESULT_SCHEMA_VERSION_D42 = "codex-interaction-probe-result/1.7"
PROBE_RESULT_SCHEMA_VERSION_D43 = "codex-interaction-probe-result/1.8"
PROBE_RESULT_SCHEMA_VERSION_D44 = "codex-interaction-probe-result/1.9"
PROBE_RESULT_SCHEMA_VERSION = "codex-interaction-probe-result/1.10"
PROBE_LIFECYCLE_SCHEMA_VERSION_LEGACY = "codex-probe-lifecycle/1"
PROBE_LIFECYCLE_SCHEMA_VERSION_PREVIOUS = "codex-probe-lifecycle/2"
PROBE_LIFECYCLE_SCHEMA_VERSION_D38 = "codex-probe-lifecycle/3"
PROBE_LIFECYCLE_SCHEMA_VERSION_D39 = "codex-probe-lifecycle/4"
PROBE_LIFECYCLE_SCHEMA_VERSION_D40 = "codex-probe-lifecycle/5"
PROBE_LIFECYCLE_SCHEMA_VERSION_D42 = "codex-probe-lifecycle/6"
PROBE_LIFECYCLE_SCHEMA_VERSION_D43 = "codex-probe-lifecycle/7"
PROBE_LIFECYCLE_SCHEMA_VERSION_D44 = "codex-probe-lifecycle/8"
PROBE_LIFECYCLE_SCHEMA_VERSION = "codex-probe-lifecycle/9"
SECRET_NAME = re.compile(r"(?:TOKEN|KEY|SECRET|PASSWORD|AUTH|COOKIE)", re.IGNORECASE)
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
PROBE_CAPABILITIES = {
    "force_load",
    "natural_routing",
    "multi_turn",
    "principal_tracing",
    "usage_capture",
    "action_authorization_trace",
}
MODEL_CAPACITY_MESSAGE = (
    "Selected model is at capacity. Please try a different model."
)


class AdapterError(ValueError):
    """A deterministic adapter contract failure."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise AdapterError(
            f"required regular file is missing or symlinked: {path.name}"
        )
    return _sha256_bytes(path.read_bytes())


def adapter_source_hash(scripts_root: Path | None = None) -> str:
    """Hash the complete runtime implementation of the Host adapter."""
    root = scripts_root or Path(__file__).resolve().parent
    components = [
        {"path": name, "sha256": _file_sha256(root / name)}
        for name in ADAPTER_SOURCE_FILES
    ]
    return _sha256_bytes(
        _canonical_bytes({"schema_version": 1, "components": components})
    )


def _load_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AdapterError("host manifest is missing or symlinked")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AdapterError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(item: str) -> None:
        raise AdapterError(f"non-finite JSON number: {item}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=no_duplicates,
        parse_constant=reject_constant,
    )
    if not isinstance(value, dict):
        raise AdapterError("JSON input must be an object")
    return value


def _bound_command_option(argv: list[str], name: str) -> str:
    positions = [index for index, value in enumerate(argv) if value == name]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise AdapterError(f"host manifest command must bind {name} exactly once")
    return argv[positions[0] + 1]


def _optional_bound_command_option(argv: list[str], name: str) -> str | None:
    positions = [index for index, value in enumerate(argv) if value == name]
    if not positions:
        return None
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise AdapterError(f"host manifest command must bind {name} at most once")
    return argv[positions[0] + 1]


def _validate_model_catalog_snapshot(
    path: Path,
    *,
    digest: str,
    client_version: str,
    model: str,
) -> None:
    if (
        path.is_symlink()
        or not path.is_file()
        or not HASH.fullmatch(digest)
        or _file_sha256(path) != digest
    ):
        raise AdapterError("model catalog snapshot bytes differ from its binding")
    value = _load_json_object(path)
    models = value.get("models")
    selected = (
        [row for row in models if isinstance(row, dict) and row.get("slug") == model]
        if isinstance(models, list)
        else []
    )
    if value.get("client_version") != client_version or len(selected) != 1:
        raise AdapterError("model catalog snapshot identity differs from the runtime")


def _validate_manifest(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json_object(path)
    identity = manifest.get("identity")
    execution = identity.get("execution") if isinstance(identity, dict) else None
    adapter = identity.get("adapter") if isinstance(identity, dict) else None
    if not isinstance(adapter, dict):
        raise AdapterError("adapter identity is missing")
    adapter_version = adapter.get("version")
    if adapter_version not in {
        LEGACY_ADAPTER_VERSION,
        PREVIOUS_ADAPTER_VERSION,
        D38_ADAPTER_VERSION,
        D39_ADAPTER_VERSION,
        D40_ADAPTER_VERSION,
        D42_ADAPTER_VERSION,
        D43_ADAPTER_VERSION,
        D44_ADAPTER_VERSION,
        ADAPTER_VERSION,
    }:
        raise AdapterError("unsupported Host adapter version")
    command = manifest.get("command")
    command_argv = command.get("argv") if isinstance(command, dict) else None
    if not isinstance(command_argv, list):
        raise AdapterError("host manifest command argv is invalid")
    runtime_surface = (
        _optional_bound_command_option(command_argv, "--runtime-surface-version")
    )
    if adapter_version in {
        PREVIOUS_ADAPTER_VERSION,
        D38_ADAPTER_VERSION,
        D39_ADAPTER_VERSION,
        D40_ADAPTER_VERSION,
        D42_ADAPTER_VERSION,
        D43_ADAPTER_VERSION,
        D44_ADAPTER_VERSION,
        ADAPTER_VERSION,
    } and runtime_surface != RUNTIME_SURFACE_VERSION:
        raise AdapterError("runtime surface identity is missing")
    if adapter_version == LEGACY_ADAPTER_VERSION and runtime_surface is not None:
        raise AdapterError("legacy Host carries a runtime surface identity")
    if not isinstance(execution, dict) or execution.get("model") != args.model:
        raise AdapterError("model identity differs from the host manifest")
    grading = identity.get("grading")
    if manifest.get("schema_version") == 3:
        if execution.get("effort") != args.effort:
            raise AdapterError("task effort differs from the host manifest")
        if grading is not None and (grading.get("model") != (getattr(args, "judge_model", None) or args.model) or grading.get("effort") != (getattr(args, "judge_effort", None) or args.effort)):
            raise AdapterError("judge model or effort differs from the host manifest")
        if grading is None and (getattr(args, "judge_model", None) or getattr(args, "judge_effort", None)):
            raise AdapterError("judge arguments lack a grading identity")
    elif getattr(args, "judge_model", None) or getattr(args, "judge_effort", None):
        raise AdapterError("independent judge requires Host v3")
    if execution.get("tool_schema_id") != isolated_tool_schema_id(
        args.codex_sha256,
        args.isolation_tool_sha256,
        args.code_mode_host_sha256,
        runtime_surface,
    ):
        raise AdapterError("tool schema identity differs from the host manifest")
    policy_ids = (
        ISOLATED_SANDBOX_POLICY_IDS
        if adapter_version == ADAPTER_VERSION
        else LEGACY_ISOLATED_SANDBOX_POLICY_IDS
    )
    if args.isolation_tool is not None and execution.get("policy_id") != policy_ids.get(args.sandbox):
        raise AdapterError("sandbox policy identity differs from the runtime")
    if adapter.get("id") != "codex-eval-host":
        raise AdapterError("adapter identity differs from the host manifest")
    expected_harness = "codex-cli"
    model_revision = f"codex-catalog-{args.codex_version}"
    if (
        identity.get("host_build") != f"codex-cli-{args.codex_version}"
        or identity.get("host_version") != args.codex_version
        or execution.get("harness") != expected_harness
        or execution.get("harness_version") != args.codex_version
        or execution.get("model_revision") != model_revision
    ):
        raise AdapterError("Codex runtime identity differs from the host manifest")
    if _file_sha256(args.codex) != args.codex_sha256:
        raise AdapterError("Codex executable bytes differ from the bound hash")
    if args.isolation_tool is None:
        if any(
            value is not None
            for value in (
                args.isolation_tool_sha256,
                args.code_mode_host,
                args.code_mode_host_sha256,
            )
        ):
            raise AdapterError("filesystem isolation identity lacks an executable")
    elif (
        not isinstance(args.isolation_tool_sha256, str)
        or not HASH.fullmatch(args.isolation_tool_sha256)
        or _file_sha256(args.isolation_tool) != args.isolation_tool_sha256
        or args.code_mode_host is None
        or args.code_mode_host.name != "codex-code-mode-host"
        or args.code_mode_host.parent != args.codex.parent
        or not isinstance(args.code_mode_host_sha256, str)
        or not HASH.fullmatch(args.code_mode_host_sha256)
        or _file_sha256(args.code_mode_host) != args.code_mode_host_sha256
    ):
        raise AdapterError("filesystem isolation runtime differs from its bound hash")
    command = manifest.get("command")
    argv = command.get("argv") if isinstance(command, dict) else None
    if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
        raise AdapterError("host manifest command argv is invalid")
    try:
        bound_codex = Path(_bound_command_option(argv, "--codex")).resolve(strict=True)
        bound_manifest = Path(_bound_command_option(argv, "--host-manifest")).resolve(
            strict=True
        )
        bound_timeout = float(_bound_command_option(argv, "--timeout"))
        bound_catalog = _optional_bound_command_option(argv, "--model-catalog-snapshot")
        bound_catalog_hash = _optional_bound_command_option(argv, "--model-catalog-sha256")
        bound_catalog_client = _optional_bound_command_option(
            argv, "--model-catalog-client-version"
        )
    except (OSError, ValueError) as exc:
        raise AdapterError("host manifest command binding is invalid") from exc
    expected = {
        "--codex-sha256": args.codex_sha256,
        "--codex-version": args.codex_version,
        "--model": args.model,
        "--effort": args.effort,
        "--profile": args.profile,
        "--sandbox": args.sandbox,
    }
    if adapter_version in {
        PREVIOUS_ADAPTER_VERSION,
        D38_ADAPTER_VERSION,
        D39_ADAPTER_VERSION,
        D40_ADAPTER_VERSION,
        D42_ADAPTER_VERSION,
        D43_ADAPTER_VERSION,
        D44_ADAPTER_VERSION,
        ADAPTER_VERSION,
    }:
        expected.update(
            {
                "--model-catalog-snapshot": str(args.model_catalog_snapshot),
                "--model-catalog-relative-path": f"{Path(args.model_catalog_snapshot).parent.name}/models_cache.json",
                "--model-catalog-sha256": args.model_catalog_sha256,
                "--model-catalog-client-version": args.model_catalog_client_version,
                "--runtime-surface-version": RUNTIME_SURFACE_VERSION,
            }
        )
    for flag, value in (("--judge-model", getattr(args, "judge_model", None)), ("--judge-effort", getattr(args, "judge_effort", None))):
        if value is not None:
            expected[flag] = value
    if grading is not None and (grading.get("provider") != execution.get("provider") or grading.get("model_revision") != model_revision):
        raise AdapterError("judge provider or revision differs from the Codex runtime")
    bound_lifecycle = _optional_bound_command_option(argv, "--lifecycle-contract") or LEGACY_CONTRACT
    isolation_options = {
        "--isolation-tool": (
            str(args.isolation_tool) if args.isolation_tool is not None else None
        ),
        "--isolation-tool-sha256": args.isolation_tool_sha256,
        "--code-mode-host": (
            str(args.code_mode_host) if args.code_mode_host is not None else None
        ),
        "--code-mode-host-sha256": args.code_mode_host_sha256,
    }
    if adapter_version in {
        PREVIOUS_ADAPTER_VERSION,
        D38_ADAPTER_VERSION,
        D39_ADAPTER_VERSION,
        D40_ADAPTER_VERSION,
        D42_ADAPTER_VERSION,
        D43_ADAPTER_VERSION,
        D44_ADAPTER_VERSION,
        ADAPTER_VERSION,
    }:
        if not all(isinstance(value, str) for value in (bound_catalog, bound_catalog_hash, bound_catalog_client)):
            raise AdapterError("runtime surface lacks a model catalog snapshot")
        snapshot_path = Path(bound_catalog).resolve(strict=True)
        runtime_root = path.with_name(f"{path.stem}.runtime").resolve(strict=True)
        if snapshot_path.parent != runtime_root or snapshot_path.name != "models_cache.json":
            raise AdapterError("model catalog snapshot is outside the Host runtime")
        _validate_model_catalog_snapshot(
            snapshot_path,
            digest=bound_catalog_hash,
            client_version=bound_catalog_client,
            model=args.model,
        )
        if grading is not None:
            _validate_model_catalog_snapshot(snapshot_path, digest=bound_catalog_hash, client_version=bound_catalog_client, model=grading["model"])
        bound_relative = _bound_command_option(
            argv, "--model-catalog-relative-path"
        )
        if bound_relative != f"{runtime_root.name}/models_cache.json":
            raise AdapterError("model catalog relative path differs from the Host runtime")
    elif any(value is not None for value in (bound_catalog, bound_catalog_hash, bound_catalog_client)) or "--model-catalog-relative-path" in argv:
        raise AdapterError("legacy Host unexpectedly binds a model catalog")
    if (
        bound_codex != args.codex
        or bound_manifest != path
        or bound_timeout != args.timeout
        or bound_lifecycle != args.lifecycle_contract
        or any(
            _bound_command_option(argv, option) != value
            for option, value in expected.items()
        )
        or any(
            _optional_bound_command_option(argv, option) != value
            for option, value in isolation_options.items()
        )
    ):
        raise AdapterError(
            "runtime options differ from the bound host manifest command"
        )
    if args.plugin_root is None and "--plugin-root" in argv:
        raise AdapterError("runtime omitted the host manifest plugin root")
    if args.plugin_root is not None:
        try:
            bound_plugin = Path(
                _bound_command_option(argv, "--plugin-root")
            ).resolve(strict=True)
        except OSError as exc:
            raise AdapterError("host manifest plugin binding is invalid") from exc
        if bound_plugin != args.plugin_root:
            raise AdapterError("runtime plugin root differs from the host manifest")
        validate_plugin_catalog(args.plugin_root, manifest)
    return manifest


def validate_bound_manifest(path: Path, plugin_root: Path) -> dict[str, Any]:
    """Validate one model-evolution Host before campaign state is created."""
    manifest = _load_json_object(path)
    path = path.resolve(strict=True)
    command = manifest.get("command")
    argv = command.get("argv") if isinstance(command, dict) else None
    if not isinstance(argv, list) or any(not isinstance(item, str) for item in argv):
        raise AdapterError("host manifest command argv is invalid")
    try:
        executable_path = Path(command["resolved_executable"])
        if not executable_path.is_absolute() or executable_path.is_symlink():
            raise AdapterError("host manifest executable identity differs")
        executable = executable_path.resolve(strict=True)
        declared = Path(argv[0])
        declared = (
            declared.resolve(strict=True)
            if declared.is_absolute()
            else (executable.parent / declared).resolve(strict=True)
        )
        codex = Path(_bound_command_option(argv, "--codex")).resolve(strict=True)
        isolation_value = _optional_bound_command_option(argv, "--isolation-tool")
        isolation_tool = (
            Path(isolation_value).resolve(strict=True)
            if isolation_value is not None
            else None
        )
        isolation_tool_sha256 = _optional_bound_command_option(
            argv,
            "--isolation-tool-sha256",
        )
        code_mode_host_value = _optional_bound_command_option(
            argv,
            "--code-mode-host",
        )
        code_mode_host = (
            Path(code_mode_host_value).resolve(strict=True)
            if code_mode_host_value is not None
            else None
        )
        code_mode_host_sha256 = _optional_bound_command_option(
            argv,
            "--code-mode-host-sha256",
        )
        model_catalog_snapshot_value = _optional_bound_command_option(
            argv,
            "--model-catalog-snapshot",
        )
        model_catalog_snapshot = (
            Path(model_catalog_snapshot_value).resolve(strict=True)
            if model_catalog_snapshot_value is not None
            else None
        )
        model_catalog_sha256 = _optional_bound_command_option(
            argv,
            "--model-catalog-sha256",
        )
        model_catalog_client_version = _optional_bound_command_option(
            argv,
            "--model-catalog-client-version",
        )
        timeout = float(_bound_command_option(argv, "--timeout"))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise AdapterError("host manifest command binding is invalid") from exc
    if (
        declared != executable
        or command.get("executable_digest") != _file_sha256(executable)
    ):
        raise AdapterError("host manifest executable identity differs")
    args = argparse.Namespace(
        judge_model=_optional_bound_command_option(argv, "--judge-model"),
        judge_effort=_optional_bound_command_option(argv, "--judge-effort"),
        codex=codex,
        codex_sha256=_bound_command_option(argv, "--codex-sha256"),
        codex_version=_bound_command_option(argv, "--codex-version"),
        model=_bound_command_option(argv, "--model"),
        effort=_bound_command_option(argv, "--effort"),
        profile=_bound_command_option(argv, "--profile"),
        sandbox=_bound_command_option(argv, "--sandbox"),
        timeout=timeout,
        plugin_root=plugin_root.resolve(strict=True),
        isolation_tool=isolation_tool,
        isolation_tool_sha256=isolation_tool_sha256,
        code_mode_host=code_mode_host,
        code_mode_host_sha256=code_mode_host_sha256,
        model_catalog_snapshot=model_catalog_snapshot,
        model_catalog_sha256=model_catalog_sha256,
        model_catalog_client_version=model_catalog_client_version,
        runtime_surface_version=_optional_bound_command_option(
            argv, "--runtime-surface-version"
        ),
        lifecycle_contract=(
            _optional_bound_command_option(argv, "--lifecycle-contract")
            or LEGACY_CONTRACT
        ),
    )
    validated = _validate_manifest(path, args)
    project_command_environment(
        validated["command"],
        dict(os.environ),
        require_model_evolution=True,
    )
    return validated


def _artifact_bytes(
    name: str, payload: bytes, *, encoding: str = "utf-8"
) -> dict[str, str]:
    if not SAFE_ID.fullmatch(name.split(".", 1)[0]):
        raise AdapterError("artifact name is unsafe")
    path = Path(name)
    if path.parent != Path(".") or path.exists() or path.is_symlink():
        raise AdapterError(f"refusing to replace adapter artifact: {name}")
    with path.open("xb") as handle:
        handle.write(payload)
    return {
        "path": f"workspace/{name}",
        "digest": _sha256_bytes(payload),
        "encoding": encoding,
    }


def _artifact_json(name: str, value: Any) -> dict[str, str]:
    return _artifact_bytes(name, _canonical_bytes(value))


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _redact_text(text: str, workspace: Path) -> str:
    redacted = text.replace(str(workspace), "<workspace>").replace(
        ISOLATED_WORKSPACE, "<workspace>"
    )
    secrets = sorted(
        (
            (name, value)
            for name, value in os.environ.items()
            if SECRET_NAME.search(name) and len(value) >= 4
        ),
        key=lambda item: (-len(item[1]), item[0]),
    )
    for _, value in secrets:
        redacted = redacted.replace(value, "<redacted>")
    redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "<redacted>", redacted)
    return redacted


def _write_child_stderr(
    raw: bytes,
    workspace: Path,
    source_root: Path | None = None,
) -> None:
    redacted_raw = raw.replace(
        str(workspace).encode("utf-8"),
        b"<workspace>",
    )
    if source_root is not None:
        redacted_raw = redacted_raw.replace(
            str(source_root).encode("utf-8"),
            b"<source-repository>",
        )
        if source_root.parent.name == ".worktrees":
            redacted_raw = redacted_raw.replace(
                str(source_root.parent.parent).encode("utf-8"),
                b"<repository-root>",
            )
    text = redacted_raw[:MAX_STDERR_BYTES].decode("utf-8", errors="replace")
    if len(redacted_raw) > MAX_STDERR_BYTES:
        text += "\n[stderr truncated by codex_eval_host]\n"
    if text:
        sys.stderr.write(_redact_text(text, workspace))
        sys.stderr.flush()


def _run_child(
    args: argparse.Namespace,
    argv: list[str],
    *,
    prompt: str,
    workspace: Path,
    codex_home: Path | None,
    timeout_seconds: float,
    capture_id: str | None = None,
    last_message: Path | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    child_env = dict(os.environ)
    child_env["PWD"] = (
        ISOLATED_WORKSPACE if args.isolation_tool is not None else str(workspace)
    )
    child_env.pop("OLDPWD", None)
    if (args.isolation_tool is None) != (codex_home is None):
        raise AdapterError("Codex isolation home and executable must be bound together")
    effective_argv = argv
    if args.isolation_tool is not None:
        assert codex_home is not None
        assert args.code_mode_host is not None
        effective_argv = isolated_child_argv(
            isolation_tool=args.isolation_tool,
            sandbox=args.sandbox,
            source_root=args.source_root,
            codex=args.codex,
            code_mode_host=args.code_mode_host,
            argv=argv,
            workspace=workspace,
            codex_home=codex_home,
            model_catalog_snapshot=args.model_catalog_snapshot,
            model_catalog_sha256=args.model_catalog_sha256,
        )
    process = subprocess.Popen(
        effective_argv,
        cwd=workspace,
        env=child_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        start_new_session=True,
    )
    kill_sent = False
    try:
        stdout, stderr = process.communicate(
            input=prompt.encode("utf-8"),
            timeout=max(timeout_seconds, 0.001),
        )
        timed_out = False
    except subprocess.TimeoutExpired:
        kill_sent = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        timed_out = True
    child = {
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "kill_sent": kill_sent,
        "reaped": process.returncode is not None,
        "runtime_ms": round((time.monotonic() - started) * 1000, 3),
    }
    capture_dir = getattr(args, "diagnostic_capture_dir", None)
    if capture_dir is not None:
        if capture_id is None:
            raise AdapterError("diagnostic capture requires a stable capture id")
        capture_child(
            capture_dir,
            capture_id,
            child,
            workspace=workspace,
            source_root=args.source_root,
            last_message=last_message,
        )
    return child


def _probe_workspace_snapshot(workspace: Path) -> tuple[dict[str, str] | None, bool]:
    try:
        return _snapshot_workspace(workspace), True
    except (AdapterError, OSError):
        return None, False


def _probe_snapshot_digest(snapshot: dict[str, str] | None) -> str | None:
    if snapshot is None:
        return None
    return _sha256_bytes(_canonical_bytes(snapshot))


def _probe_jsonl_is_classified(normalized: dict[str, Any]) -> bool:
    diagnostics = normalized.get("diagnostics")
    if not isinstance(diagnostics, list):
        return False
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            return False
        kind = diagnostic.get("kind")
        if kind in {"thread_identity", "turn_lifecycle", "missing_terminal"}:
            continue
        if kind == "item_lifecycle" and "incomplete items:" in str(
            diagnostic.get("message", "")
        ):
            continue
        return False
    return True


def _probe_action_effect(normalized: dict[str, Any]) -> bool:
    """Return the D36 effect-capable projection without exposing item content."""
    classification = _probe_item_classification(normalized)
    return bool(classification[3] or classification[5])


def _canonical_probe_event_types(values: Any) -> list[str]:
    """Return the canonical sorted-unique event collection for probe evidence."""
    if not isinstance(values, list):
        return []
    return sorted({value for value in values if isinstance(value, str)})


_NON_EFFECT_PROGRESS_TYPES = {"reasoning", "todo_list", "error"}
_EFFECT_CAPABLE_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "collab_tool_call",
    "web_search",
}


def _probe_item_classification(
    normalized: dict[str, Any],
) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    """Project only normalized item types and evidence classes."""
    completed: set[str] = set()
    started_by_id: dict[str, str] = {}
    completed_ids: set[str] = set()
    non_effect: set[str] = set()
    effect_capable: set[str] = set()
    for item in normalized.get("items", []):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        phase = item.get("phase")
        if not isinstance(item_type, str) or item_type not in ITEM_TYPES:
            continue
        if phase == "completed":
            completed.add(item_type)
            if isinstance(item.get("id"), str):
                completed_ids.add(item["id"])
        elif phase in {"started", "updated"}:
            if isinstance(item.get("id"), str):
                started_by_id[item["id"]] = item_type
        if item_type in _EFFECT_CAPABLE_TYPES:
            effect_capable.add(item_type)
        elif item_type in _NON_EFFECT_PROGRESS_TYPES:
            error = item.get("error")
            if any(field in item for field in ("exit_code", "aggregated_output", "changes")):
                effect_capable.add(item_type)
            elif not (
                item_type == "error"
                and isinstance(error, dict)
                and error.get("kind") == "permission_denied"
            ):
                non_effect.add(item_type)
            else:
                effect_capable.add(item_type)
    outcome_evidence: set[str] = set()
    event_types = _canonical_probe_event_types(normalized.get("event_types", []))
    if "turn.completed" in event_types or "turn.failed" in event_types:
        outcome_evidence.add("turn_completion")
    if isinstance(normalized.get("final_message"), str) and normalized["final_message"]:
        outcome_evidence.add("final_message")
    if isinstance(normalized.get("usage"), dict) and normalized["usage"]:
        outcome_evidence.add("usage")
    if normalized.get("routing") is not None:
        outcome_evidence.add("routing")
    effect_evidence: set[str] = set()
    if normalized.get("permission_denials"):
        effect_evidence.add("permission_denial")
    incomplete = {
        item_type
        for item_id, item_type in started_by_id.items()
        if item_id not in completed_ids
    }
    return (
        sorted(completed),
        sorted(incomplete),
        sorted(non_effect),
        sorted(effect_capable),
        sorted(outcome_evidence),
        sorted(effect_evidence),
    )


def _probe_command_custody(normalized: dict[str, Any]) -> dict[str, Any]:
    """Project only the bounded, content-free custody of command items."""
    command_items = [
        item
        for item in normalized.get("items", [])
        if isinstance(item, dict) and item.get("type") == "command_execution"
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    invalid_id_count = 0
    for item in command_items:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not SAFE_ID.fullmatch(item_id):
            invalid_id_count += 1
            continue
        grouped.setdefault(item_id, []).append(item)
    started_count = sum(item.get("phase") == "started" for item in command_items)
    updated_count = sum(item.get("phase") == "updated" for item in command_items)
    completed_items = [
        item for item in command_items if item.get("phase") == "completed"
    ]
    completed_count = len(completed_items)
    reason_counts = {
        "invalid_id": invalid_id_count,
        "unknown_phase": 0,
        "missing_started": 0,
        "duplicate_started": 0,
        "missing_completed": 0,
        "duplicate_completed": 0,
        "unknown_completed_status": 0,
        "missing_exit_code": 0,
        "status_exit_mismatch": 0,
        "changes_present": 0,
        "error_present": 0,
        "incomplete_present": 0,
    }
    zero_exit_count = 0
    failed_nonzero_count = 0
    for items in grouped.values():
        starts = [item for item in items if item.get("phase") == "started"]
        completions = [item for item in items if item.get("phase") == "completed"]
        reason_counts["unknown_phase"] += sum(
            item.get("phase") not in {"started", "updated", "completed"}
            for item in items
        )
        reason_counts["missing_started"] += not starts
        reason_counts["duplicate_started"] += max(0, len(starts) - 1)
        reason_counts["missing_completed"] += not completions
        reason_counts["duplicate_completed"] += max(0, len(completions) - 1)
        for item in items:
            reason_counts["changes_present"] += bool(item.get("changes"))
            reason_counts["error_present"] += isinstance(item.get("error"), dict)
            reason_counts["incomplete_present"] += (
                item.get("incomplete") is True
                or item.get("status") == "incomplete"
            )
        if len(completions) == 1:
            completed = completions[0]
            status = completed.get("status")
            exit_code = completed.get("exit_code")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                reason_counts["missing_exit_code"] += 1
            elif status == "completed" and exit_code == 0:
                zero_exit_count += 1
            elif status == "failed" and exit_code != 0:
                failed_nonzero_count += 1
            elif status not in {"completed", "failed"}:
                reason_counts["unknown_completed_status"] += 1
            else:
                reason_counts["status_exit_mismatch"] += 1
    changes_present = any(
        bool(item.get("changes"))
        for item in command_items
    )
    error_present = any(isinstance(item.get("error"), dict) for item in command_items)
    paired = (
        bool(grouped)
        and not invalid_id_count
        and not any(
            reason_counts[field]
            for field in (
                "unknown_phase",
                "missing_started",
                "duplicate_started",
                "missing_completed",
                "duplicate_completed",
            )
        )
    )
    successful = (
        paired
        and zero_exit_count == len(grouped)
        and not any(reason_counts.values())
    )
    effect_custody_closed = (
        paired
        and zero_exit_count + failed_nonzero_count == len(grouped)
        and not any(reason_counts.values())
    )
    return {
        "present": bool(command_items),
        "item_count": len(grouped),
        "started_count": started_count,
        "updated_count": updated_count,
        "completed_count": completed_count,
        "paired": paired,
        "zero_exit_count": zero_exit_count,
        "failed_nonzero_count": failed_nonzero_count,
        "successful": successful,
        "effect_custody_closed": effect_custody_closed,
        "changes_present": changes_present,
        "error_present": error_present,
        "reason_counts": reason_counts,
    }


_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?i)(token|secret|password|authorization|api[_-]?key)\s*=\s*([^\s\"'\\,}\]]*)"
)
_CREDENTIAL_SECRET_PREFIX = re.compile(rb"sk-[A-Za-z0-9_-]{8,}")
_CREDENTIAL_RAW_MARKER = re.compile(
    rb"(?i)(?:sk-[A-Za-z0-9_-]{8,}|(?:token|secret|password|authorization|api[_-]?key)\s*[:=])"
)
_SAFE_CREDENTIAL_PLACEHOLDERS = {
    b"",
    b"unset",
    b"redacted",
    b"<redacted>",
    b"[redacted]",
}


def _jsonl_credential_scalars(raw: bytes) -> tuple[list[tuple[str, str, str]], bool]:
    """Classify marker-bearing JSONL scalars without retaining them in evidence."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [], False
    values: list[tuple[str, str, str]] = []
    for record_index, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return [], False
        if not isinstance(record, dict):
            return [], False
        record_type = record.get("type")
        item = record.get("item")
        item_id = (
            item.get("id")
            if isinstance(item, dict) and isinstance(item.get("id"), str)
            else f"record-{record_index}"
        )
        classified: set[int] = set()

        def add(value: Any, source: str) -> None:
            if isinstance(value, str):
                classified.add(id(value))
                values.append((item_id, source, value))

        if record_type in {"item.started", "item.updated", "item.completed"} and isinstance(item, dict):
            item_type = item.get("type")
            if item_type == "command_execution":
                add(item.get("command"), "command_text")
                add(item.get("aggregated_output"), "command_output")
            elif item_type == "agent_message":
                add(item.get("text"), "agent_message")
            error = item.get("error")
            if isinstance(error, dict):
                for field in ("kind", "code", "message"):
                    add(error.get(field), "structured_error")
        if record_type in {"error", "turn.failed"}:
            error = record.get("error")
            if isinstance(error, dict):
                for field in ("kind", "code", "message"):
                    add(error.get(field), "structured_error")
            add(record.get("message"), "structured_error")

        def collect_unknown(value: Any) -> None:
            if isinstance(value, str):
                encoded = value.encode("utf-8")
                if id(value) not in classified and _CREDENTIAL_RAW_MARKER.search(encoded):
                    values.append((item_id, "unknown", value))
            elif isinstance(value, dict):
                for child in value.values():
                    collect_unknown(child)
            elif isinstance(value, list):
                for child in value:
                    collect_unknown(child)

        collect_unknown(record)
    return values, True


def _probe_credential_observation(
    stdout: bytes,
    stderr: bytes,
) -> dict[str, Any]:
    """Project bounded structured provenance without retaining marker values."""
    grouped: dict[tuple[str, str, str], int] = {}
    exposure_possible = False
    scalars, structured_coverage_complete = _jsonl_credential_scalars(stdout)
    scalars.append(("stderr", "child_stderr", stderr.decode("utf-8", errors="replace")))
    seen: set[tuple[str, str, str]] = set()

    def add(kind: str, source: str, shape: str, exposure: bool) -> None:
        nonlocal exposure_possible
        grouped[(kind, source, shape)] = grouped.get((kind, source, shape), 0) + 1
        exposure_possible = exposure_possible or exposure

    for item_id, source, value in scalars:
        identity = (item_id, source, value)
        if identity in seen:
            continue
        seen.add(identity)
        channel = value.encode("utf-8")
        covered: list[tuple[int, int]] = []
        for match in _CREDENTIAL_SECRET_PREFIX.finditer(channel):
            add("secret_prefix", source, "secret_like", True)
            covered.append((match.start(), match.end()))
        for match in _CREDENTIAL_ASSIGNMENT.finditer(channel):
            marker_value = match.group(2).lower()
            if marker_value == b"":
                shape, exposure = "empty", False
            elif marker_value in _SAFE_CREDENTIAL_PLACEHOLDERS:
                shape, exposure = "safe_placeholder", False
            elif source == "command_text":
                shape, exposure = "command_syntax", False
            else:
                shape, exposure = "non_placeholder", True
            add("assignment", source, shape, exposure)
            covered.append((match.start(), match.end()))
        for match in _CREDENTIAL_RAW_MARKER.finditer(channel):
            if any(start <= match.start() and match.end() <= end for start, end in covered):
                continue
            add("raw_marker", source, "unattributed", True)
    if not structured_coverage_complete and _CREDENTIAL_RAW_MARKER.search(stdout):
        add("raw_marker", "raw_unattributed", "unattributed", True)
    markers = [
        {"kind": kind, "source": source, "count": count, "value_shape": shape}
        for (kind, source, shape), count in sorted(grouped.items())
    ]
    return {
        "marker_seen": bool(markers),
        "exposure_possible": exposure_possible,
        "occurrence_count": sum(item["count"] for item in markers),
        "structured_coverage_complete": structured_coverage_complete,
        "markers": markers,
    }


_SAFE_FAILURE_SOURCES = {"turn", "item", "record", "child", "normalizer"}
_SAFE_FAILURE_CLASSES = {
    "none",
    "capacity_transient",
    "transport_transient",
    "authentication",
    "configuration",
    "usage_limit",
    "provider_nonretryable",
    "unknown",
    "mixed",
    "malformed",
}
_MALFORMED_FAILURE_DIAGNOSTICS = {
    "unknown_record_type",
    "missing_record_field",
    "unknown_item",
    "usage",
    "routing",
    "duplicate_terminal",
    "post_terminal_event",
    "stream_size",
    "non_utf8",
    "record_count",
    "malformed_jsonl",
}


def _safe_failure_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return token[:64] or None


def _safe_failure_kind(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.casefold()
    if token in {"codex_error", "provider_error", "transport_error", "network_error", "process", "diagnostic"}:
        return token
    if "auth" in token or "credential" in token:
        return "authentication"
    if "config" in token or "request" in token:
        return "configuration"
    return "provider"


def _failure_kind_class(failure: dict[str, Any]) -> tuple[str, str | None]:
    """Project one normalized failure without persisting its message."""
    if _is_model_capacity_failure(failure):
        return "capacity_transient", "model_at_capacity"
    kind = failure.get("kind") if isinstance(failure.get("kind"), str) else ""
    code = failure.get("code") if isinstance(failure.get("code"), str) else ""
    message = failure.get("message") if isinstance(failure.get("message"), str) else ""
    folded = " ".join((kind, code, message)).casefold()
    if "usage limit" in folded or "rate limit" in folded:
        return "usage_limit", "usage_limit"
    if any(token in folded for token in ("authentication", "unauthorized", "credential", "forbidden")):
        return "authentication", "authentication"
    if any(token in folded for token in ("configuration", "invalid_request", "invalid request", "bad_request")):
        return "configuration", "configuration"
    if kind in {"transport_error", "network_error"} and code in {
        "tls_handshake_eof",
        "connection_reset",
        "websocket_eof",
    }:
        return "transport_transient", "transport"
    if kind or code or message:
        return "provider_nonretryable", "provider_error"
    return "unknown", None


def _integer_runtime_ms(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0:
        return 0
    projected = int(math.floor(numeric + 0.5))
    return max(1, projected) if numeric > 0 else 0


def _failure_detail_projection(
    failure: dict[str, Any],
    *,
    workspace: Path,
    source_root: Path | None,
    excluded_values: tuple[str, ...],
) -> str:
    values = [
        f"{field}={failure[field]}"
        for field in ("kind", "code", "message")
        if isinstance(failure.get(field), str) and failure[field]
    ]
    detail = _redact_text("; ".join(values), workspace)
    if source_root is not None:
        detail = detail.replace(str(source_root), "<source-repository>")
        if source_root.parent.name == ".worktrees":
            detail = detail.replace(
                str(source_root.parent.parent), "<repository-root>"
            )
    for value in sorted(
        {item for item in excluded_values if isinstance(item, str) and len(item) >= 4},
        key=len,
        reverse=True,
    ):
        detail = detail.replace(value, "<content-redacted>")
    detail = re.sub(r"(?<![A-Za-z0-9:])/(?:[^\s;]+)", "<path>", detail)
    detail = " ".join(detail.split())
    return detail[:MAX_FAILURE_PROJECTION_CHARS]


def _probe_failure_observation(
    child: dict[str, Any],
    normalized: dict[str, Any],
    *,
    workspace: Path,
    source_root: Path | None,
    excluded_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Return a bounded, redacted failure projection for one attempt."""
    runtime_ms = _integer_runtime_ms(child.get("runtime_ms"))
    failures = normalized.get("failures")
    if not isinstance(failures, list):
        failures = []
    grouped_failures: dict[str, dict[str, Any]] = {}
    source_totals: dict[str, int] = {}
    classes: list[str] = []

    def add_failure(
        failure: dict[str, Any],
        *,
        source: str,
        failure_class: str,
        code: str | None,
    ) -> None:
        safe_source = source if source in _SAFE_FAILURE_SOURCES else "unknown"
        detail_input = (
            failure
            if failure_class
            in {"provider_nonretryable", "capacity_transient", "transport_transient"}
            else {key: failure[key] for key in ("kind", "code") if key in failure}
        )
        detail = _failure_detail_projection(
            detail_input,
            workspace=workspace,
            source_root=source_root,
            excluded_values=excluded_values,
        )
        identity = {
            "kind": _safe_failure_kind(failure.get("kind")),
            "code": code,
            "failure_class": failure_class,
            "detail": detail,
        }
        signature = _sha256_bytes(_canonical_bytes(identity))
        row = grouped_failures.setdefault(
            signature,
            {
                **identity,
                "signature": signature,
                "count": 0,
                "source_counts": {},
            },
        )
        row["count"] += 1
        row["source_counts"][safe_source] = (
            row["source_counts"].get(safe_source, 0) + 1
        )
        source_totals[safe_source] = source_totals.get(safe_source, 0) + 1

    for failure in failures:
        if not isinstance(failure, dict):
            classes.append("malformed")
            continue
        failure_class, code = _failure_kind_class(failure)
        classes.append(failure_class)
        add_failure(
            failure,
            source=failure.get("source", "unknown"),
            failure_class=failure_class,
            code=code,
        )
    transport_marker = (
        b"responses_websocket: failed to connect to websocket: "
        b"IO error: tls handshake eof"
    )
    event_types = _canonical_probe_event_types(normalized.get("event_types", []))
    stderr = child.get("stderr", b"")
    if not isinstance(stderr, bytes):
        stderr = b""
    if (
        child.get("timed_out") is True
        and transport_marker in stderr
        and "turn.completed" not in event_types
        and not grouped_failures
    ):
        classes.append("transport_transient")
        add_failure(
            {
                "kind": "transport_error",
                "code": "tls_handshake_eof",
                "message": "Codex transport interrupted before turn completion",
            },
            source="child",
            failure_class="transport_transient",
            code="transport",
        )
    diagnostics = normalized.get("diagnostics")
    diagnostic_kinds = {
        item.get("kind") for item in diagnostics if isinstance(item, dict)
    } if isinstance(diagnostics, list) else set()
    if not isinstance(diagnostics, list) or any(
        not isinstance(item, dict) or item.get("kind") in _MALFORMED_FAILURE_DIAGNOSTICS
        for item in (diagnostics if isinstance(diagnostics, list) else [])
    ):
        if not grouped_failures and not (
            child.get("timed_out") is True
            and diagnostic_kinds <= {
                "thread_identity", "turn_lifecycle", "missing_terminal", "item_lifecycle"
            }
        ):
            classes.append("malformed")
    if not grouped_failures and child.get("timed_out") is not True:
        returncode = child.get("returncode")
        if isinstance(returncode, int) and not isinstance(returncode, bool) and returncode != 0:
            classes.append("provider_nonretryable")
            process_code = (
                f"codex_exit_{returncode}"
                if returncode >= 0
                else f"codex_signal_{-returncode}"
            )
            add_failure(
                {"kind": "process", "code": process_code},
                source="child",
                failure_class="provider_nonretryable",
                code=process_code,
            )
    classes = sorted(set(classes))
    if not classes:
        failure_class = "none"
    elif len(classes) == 1:
        failure_class = classes[0]
    else:
        failure_class = "mixed"
    projected_failures = []
    for signature in sorted(grouped_failures):
        row = grouped_failures[signature]
        projected_failures.append(
            {
                **{key: row[key] for key in ("kind", "code", "failure_class", "detail", "signature", "count")},
                "source_counts": [
                    {"source": source, "count": count}
                    for source, count in sorted(row["source_counts"].items())
                ],
            }
        )
    return {
        "present": failure_class != "none",
        "failures": projected_failures,
        "failure_class": failure_class if failure_class in _SAFE_FAILURE_CLASSES else "unknown",
        "runtime_ms": runtime_ms,
        "occurrence_count": sum(source_totals.values()),
        "source_counts": [
            {"source": source, "count": count}
            for source, count in sorted(source_totals.items())
        ],
    }


def _probe_lifecycle_projection(
    child: dict[str, Any],
    normalized: dict[str, Any],
    *,
    workspace: Path,
    workspace_before: dict[str, str] | None,
    workspace_after: dict[str, str] | None,
    workspace_before_ok: bool,
    workspace_after_ok: bool,
    last_message: Path,
    source_root: Path | None,
    isolated: bool,
    required_event_types: list[str] | None = None,
    capability_observable: bool | None = None,
    failure_observation: dict[str, Any] | None = None,
    excluded_failure_values: tuple[str, ...] = (),
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    raw = child.get("stdout", b"")
    stderr_raw = child.get("stderr", b"")
    if not isinstance(raw, bytes):
        raw = b""
    if not isinstance(stderr_raw, bytes):
        stderr_raw = b""
    source_path_exposed = bool(
        source_root is not None
        and any(str(source_root).encode("utf-8") in channel for channel in (raw, stderr_raw))
    )
    credential_observation = _probe_credential_observation(raw, stderr_raw)
    credential_marker_seen = credential_observation["marker_seen"]
    credential_exposure_possible = credential_observation["exposure_possible"]
    event_types = _canonical_probe_event_types(normalized.get("event_types", []))
    completed_turn = "turn.completed" in event_types
    last_message_present = last_message.is_file() or bool(
        isinstance(normalized.get("final_message"), str)
        and normalized["final_message"]
    )
    usage_present = isinstance(normalized.get("usage"), dict) and bool(
        normalized["usage"]
    )
    (
        completed_item_types,
        incomplete_item_types,
        non_effect_progress_item_types,
        effect_capable_item_types,
        outcome_evidence_types,
        effect_capable_evidence_types,
    ) = _probe_item_classification(normalized)
    command_custody = _probe_command_custody(normalized)
    workspace_clean = (
        workspace_before_ok
        and workspace_after_ok
        and workspace_before is not None
        and workspace_after is not None
        and workspace_before == workspace_after
    )
    jsonl_bounded = len(raw) <= MAX_JSONL_BYTES
    jsonl_classified = jsonl_bounded and _probe_jsonl_is_classified(normalized)
    process_exited = isinstance(child.get("returncode"), int) and not isinstance(
        child.get("returncode"), bool
    )
    process_reaped = child.get("reaped") is True
    child_timed_out = child.get("timed_out") is True
    child_kill_sent = child.get("kill_sent") is True
    isolation_custody = isolated
    if not workspace_clean:
        effect_capable_evidence_types = sorted(
            {*effect_capable_evidence_types, "workspace_mutation"}
        )
    custody_closed = (
        process_exited
        and process_reaped
        and (not child_timed_out or child_kill_sent)
        and isolation_custody
        and jsonl_classified
        and workspace_clean
        and not source_path_exposed
        and not credential_exposure_possible
    )
    effect_custody_closed = (
        command_custody["effect_custody_closed"]
        and custody_closed
        and not source_path_exposed
        and not credential_exposure_possible
    )
    observations = set(event_types)
    if normalized.get("routing"):
        observations.add("direct.routing")
    if usage_present:
        observations.add("direct.usage")
    if normalized.get("permission_denials"):
        observations.add("permission.denied")
    required_events_complete = (
        required_event_types is not None
        and set(required_event_types) <= observations
    )
    if failure_observation is None:
        failure_observation = _probe_failure_observation(
            child,
            normalized,
            workspace=workspace,
            source_root=source_root,
            excluded_values=excluded_failure_values,
        )
    if (
        failure_observation["failure_class"] in {"capacity_transient", "transport_transient"}
        and "turn.failed" in event_types
        and not completed_turn
    ):
        outcome_evidence_types = [
            item for item in outcome_evidence_types if item != "turn_completion"
        ]
    outcome_evidence = bool(outcome_evidence_types)
    effect_capable = bool(
        effect_capable_item_types or effect_capable_evidence_types
    )
    base = {
        "schema_version": PROBE_LIFECYCLE_SCHEMA_VERSION,
        "child_timed_out": child_timed_out,
        "child_kill_sent": child_kill_sent,
        "child_reaped": process_reaped,
        "process_exited": process_exited,
        "isolation_custody": isolation_custody,
        "jsonl_bounded": jsonl_bounded,
        "jsonl_classified": jsonl_classified,
        "event_count": len(event_types),
        "event_types": sorted(event_types),
        "completed_item_types": completed_item_types,
        "incomplete_item_types": incomplete_item_types,
        "non_effect_progress_item_types": non_effect_progress_item_types,
        "effect_capable_item_types": effect_capable_item_types,
        "outcome_evidence_types": outcome_evidence_types,
        "effect_capable_evidence_types": effect_capable_evidence_types,
        "outcome_evidence": outcome_evidence,
        "effect_capable": effect_capable,
        "command_custody": command_custody,
        "completed_turn": completed_turn,
        "final_message_present": last_message_present,
        "usage_present": usage_present,
        "workspace_pre_digest": _probe_snapshot_digest(workspace_before),
        "workspace_post_digest": _probe_snapshot_digest(workspace_after),
        "workspace_clean": workspace_clean,
        "source_path_exposed": source_path_exposed,
        "credential_marker_seen": credential_marker_seen,
        "credential_exposure_possible": credential_exposure_possible,
        "credential_observation": credential_observation,
        "custody_closed": custody_closed,
        "effect_custody_closed": effect_custody_closed,
        "required_events_complete": required_events_complete,
        "capability_observable": (
            bool(capability_observable)
            if capability_observable is not None
            else False
        ),
        "failure_observation": failure_observation,
        "retryable": False,
        "branch": "unknown",
        "reason": "unknown_lifecycle",
    }
    if (
        normalized.get("status") == "completed"
        and completed_turn
        and custody_closed
    ):
        base.update({"branch": "complete", "reason": "complete"})
        return base, "pass", []
    if (
        custody_closed
        and not outcome_evidence
        and not effect_capable
        and set(incomplete_item_types).issubset(
            set(non_effect_progress_item_types)
        )
        and (
            child.get("timed_out") is True
            or failure_observation["failure_class"] in {
                "capacity_transient",
                "transport_transient",
            }
        )
        and (
            failure_observation["failure_class"] in {
                "none",
                "capacity_transient",
                "transport_transient",
            }
        )
    ):
        reason = (
            "child_timeout_outcome_free"
            if child.get("timed_out") is True
            else "model_capacity_outcome_free"
        )
        base.update({
            "branch": "outcome_free_transient",
            "reason": reason,
            "retryable": True,
        })
        return base, "unknown", [{
            "kind": "official_transient",
            "index": None,
            "message": "probe lifecycle custody closed",
        }]
    if outcome_evidence:
        base["reason"] = "outcome_evidence"
    elif effect_capable:
        base["reason"] = "effect_capable"
    elif failure_observation["present"]:
        base["reason"] = "explicit_failure"
    elif not custody_closed:
        base["reason"] = "custody_incomplete"
    return base, "unknown", [{
        "kind": "probe_lifecycle",
        "index": None,
        "message": "probe lifecycle is not retryable",
    }]


def _apply_probe_capability_projection(
    lifecycle: dict[str, Any],
    status: str,
    diagnostics: list[dict[str, Any]],
    *,
    capability: str,
    capability_observed: bool,
) -> tuple[str, list[dict[str, Any]]]:
    """Separate required-event completeness from capability observability."""
    lifecycle["capability_observable"] = capability_observed
    if status == "pass" and not lifecycle["required_events_complete"]:
        lifecycle.update({
            "branch": "unknown",
            "reason": "required_event_observation_missing",
            "retryable": False,
        })
        return "unknown", [{
            "kind": "probe_lifecycle",
            "index": None,
            "message": "required probe event is missing",
        }]
    if (
        status == "pass"
        and capability in {"multi_turn", "principal_tracing"}
        and not capability_observed
    ):
        failure_observation = lifecycle.get("failure_observation")
        command_custody = lifecycle.get("command_custody")
        completed_command_safe = (
            lifecycle.get("effect_capable_item_types") == ["command_execution"]
            and lifecycle.get("effect_capable_evidence_types") == []
            and isinstance(command_custody, dict)
            and command_custody.get("effect_custody_closed") is True
            and lifecycle.get("effect_custody_closed") is True
            and isinstance(failure_observation, dict)
            and failure_observation.get("present") is False
            and failure_observation.get("failure_class") == "none"
            and lifecycle.get("child_timed_out") is False
            and lifecycle.get("process_exited") is True
            and lifecycle.get("child_reaped") is True
        )
        safe_unknown = (
            lifecycle["branch"] == "complete"
            and lifecycle["required_events_complete"]
            and lifecycle["custody_closed"]
            and lifecycle["completed_turn"]
            and lifecycle["final_message_present"]
            and lifecycle["usage_present"]
            and not lifecycle["incomplete_item_types"]
            and (
                not lifecycle["effect_capable"]
                or completed_command_safe
            )
            and not lifecycle["source_path_exposed"]
            and not lifecycle["credential_exposure_possible"]
        )
        if not safe_unknown:
            lifecycle.update({
                "branch": "unknown",
                "reason": "unsafe_noncritical_observation",
                "retryable": False,
            })
            return "unknown", [{
                "kind": "probe_lifecycle",
                "index": None,
                "message": "noncritical capability custody is not safely closed",
            }]
        lifecycle.update({
            "branch": "noncritical_unknown",
            "reason": "capability_not_directly_observable",
            "retryable": False,
        })
        return "unknown", []
    if status == "pass" and not capability_observed:
        lifecycle.update({
            "branch": "unknown",
            "reason": "capability_observation_missing",
            "retryable": False,
        })
        return "unknown", [{
            "kind": "probe_lifecycle",
            "index": None,
            "message": "required probe capability is missing",
        }]
    return status, diagnostics


def _child_failure_diagnostics(
    child: dict[str, Any], workspace: Path
) -> list[dict[str, Any]]:
    if child["timed_out"]:
        transport_marker = (
            b"responses_websocket: failed to connect to websocket: "
            b"IO error: tls handshake eof"
        )
        completed_turn = False
        for raw in child["stdout"][:MAX_JSONL_BYTES].splitlines()[:MAX_RECORDS]:
            try:
                event = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict) and event.get("type") == "turn.completed":
                completed_turn = True
                break
        if transport_marker in child["stderr"] and not completed_turn:
            return [
                {
                    "kind": "official_transient",
                    "index": None,
                    "message": "Codex transport interrupted before turn completion",
                }
            ]
        return [
            {
                "kind": "child_process",
                "index": None,
                "message": "Codex child timed out",
            }
        ]
    provider_diagnostic = None
    for raw in child["stdout"][:MAX_JSONL_BYTES].splitlines()[:MAX_RECORDS]:
        try:
            event = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") not in {"error", "turn.failed"}:
            continue
        nested = event.get("error")
        messages = [
            event.get("message"),
            nested.get("message") if isinstance(nested, dict) else None,
        ]
        if any(
            _is_model_capacity_failure(
                {"kind": "codex_error", "message": message}
            )
            for message in messages
        ):
            return [
                {
                    "kind": "official_transient",
                    "index": None,
                    "message": "Codex model capacity response",
                }
            ]
        if any(
            isinstance(message, str) and "usage limit" in message.casefold()
            for message in messages
        ):
            return [
                {
                    "kind": "provider_usage_limit",
                    "index": None,
                    "message": "Codex provider usage limit reached",
                }
            ]
        if provider_diagnostic is None:
            facts = nested if isinstance(nested, dict) else event
            values = [
                f"{field}={facts[field]}"
                for field in ("kind", "code", "message")
                if isinstance(facts.get(field), str) and facts[field]
            ]
            if (
                not isinstance(facts.get("message"), str)
                and isinstance(event.get("message"), str)
            ):
                values.append(f"message={event['message']}")
            if values:
                provider_diagnostic = {
                    "kind": "provider_error",
                    "index": None,
                    "message": _redact_text("; ".join(values), workspace)[
                        :MAX_FAILURE_DETAIL_CHARS
                    ],
                }
    if provider_diagnostic is not None:
        return [provider_diagnostic]
    return [
        {
            "kind": "child_process",
            "index": None,
            "message": f"Codex child exited {child['returncode']}",
        }
    ]


def _captured_usage(
    manifest: dict[str, Any],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    records = []
    for call in calls:
        normalized = call["normalized"]
        usage = normalized.get("usage")
        if (
            not isinstance(usage, dict)
            or not isinstance(usage.get("input_tokens"), int)
            or not isinstance(usage.get("output_tokens"), int)
        ):
            raise AdapterError("completed Codex turn lacks captured token usage")
        records.append({
            "principal_id": call["principal_id"],
            "turn_id": call["turn_id"],
            "phase": call["phase"],
            "call_id": call["call_id"],
            "input_tokens": usage["input_tokens"],
            "output_tokens": usage["output_tokens"],
            "cache_read_tokens": usage.get("cached_input_tokens", 0),
            "cache_write_tokens": 0,
            "queue_ms": 0,
            "runtime_ms": call["runtime_ms"],
            "tool_calls": len(normalized["tool_call_ids"]),
            "retries": 0,
            "rework": 0,
            "network_calls": 1,
            "residue_count": 0,
            "requested_effort": 1,
            "effective_effort": 1,
        })
    identities = {}
    if manifest.get("schema_version") == 3:
        for call in calls:
            role = "judge" if call["phase"] == "model-grade" else "task"
            config = manifest["identity"].get("grading" if role == "judge" else "execution")
            if config is None:
                raise AdapterError("usage lacks a bound role configuration")
            identities[call["principal_id"]] = {"principal_id": call["principal_id"], "role": role, "model": config["model"], "pricing_identity": config["pricing_id"]}
    return {
        **({"principal_identities": list(identities.values())} if manifest.get("schema_version") == 3 else {"pricing_identity": manifest["identity"]["execution"]["pricing_id"]}),
        "host_safety_review": {
            "capture_status": "missing",
            "host_safety_review_count": 0,
            "host_safety_review_latency_ms": 0,
        },
        "records": records,
    }


def _captured_context(
    delivery: tuple[str, str, str | None] | None,
    request_id: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    body = delivery[2] if delivery is not None else None
    if body is None:
        return {
            "status": "captured",
            "bytes": 0,
            "tokens": None,
            "controlled_bytes": 0,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": 0,
            "components": [],
        }, []
    payload = body.encode("utf-8")
    artifact = _artifact_bytes(
        f"skill-body-{request_id}.md",
        payload,
    )
    component = {
        "component_id": "target-skill-body",
        "kind": "body",
        "source_path": f"skills/{delivery[0]}/SKILL.md",
        "artifact": artifact,
        "bytes": len(payload),
        "tokens": None,
        "occurrence": 1,
    }
    return {
        "status": "captured",
        "bytes": len(payload),
        "tokens": None,
        "controlled_bytes": len(payload),
        "unique_reference_bytes": 0,
        "controlled_core_bytes": len(payload),
        "components": [component],
    }, [artifact]


def _config_override(name: str, value: str) -> str:
    return f"{name}={json.dumps(value, ensure_ascii=False)}"


def _profile_argv(profile: str) -> list[str]:
    return [] if profile == "none" else ["--profile", profile]


def _fresh_argv(
    args: argparse.Namespace,
    workspace: Path,
    last_message: Path,
    *,
    output_schema: Path | None = None,
    ephemeral: bool,
    role: str = "task",
) -> list[str]:
    argv = [
        str(args.codex),
        "exec",
        *(command_permission_argv(args.sandbox) if args.isolation_tool is not None else []),
        "--json",
        "--strict-config",
        "--color",
        "never",
        "--model",
        (getattr(args, "judge_model", None) or args.model) if role == "judge" else args.model,
        *_profile_argv(args.profile),
        *(
            skill_isolation_argv(
                include_installed_skills=args.isolation_tool is None,
                include_apps=args.runtime_surface_version == RUNTIME_SURFACE_VERSION,
            )
            if args.plugin_root
            else (["--disable", "apps"] if args.runtime_surface_version == RUNTIME_SURFACE_VERSION else [])
        ),
        *(["--sandbox", args.sandbox] if args.isolation_tool is None else []),
        "--cd",
        str(workspace),
        "--config",
        _config_override("model_reasoning_effort", (getattr(args, "judge_effort", None) or args.effort) if role == "judge" else args.effort),
        "--output-last-message",
        str(last_message),
    ]
    if args.runtime_surface_version == RUNTIME_SURFACE_VERSION:
        argv[argv.index("--config") + 2:argv.index("--config") + 2] = [
            "--config",
            _config_override("model_catalog_json", str(args.model_catalog_snapshot)),
        ]
    if ephemeral:
        argv.append("--ephemeral")
    if output_schema is not None:
        argv.extend(["--output-schema", str(output_schema)])
    argv.append("-")
    return argv


def _resume_argv(
    args: argparse.Namespace,
    session_id: str,
    last_message: Path,
) -> list[str]:
    argv = [
        str(args.codex),
        "exec",
        "resume",
        *(command_permission_argv(args.sandbox) if args.isolation_tool is not None else []),
        "--json",
        "--strict-config",
        "--model",
        args.model,
        *_profile_argv(args.profile),
        *(
            skill_isolation_argv(
                include_installed_skills=args.isolation_tool is None,
                include_apps=args.runtime_surface_version == RUNTIME_SURFACE_VERSION,
            )
            if args.plugin_root
            else (["--disable", "apps"] if args.runtime_surface_version == RUNTIME_SURFACE_VERSION else [])
        ),
        "--config",
        _config_override("model_reasoning_effort", args.effort),
        "--output-last-message",
        str(last_message),
        session_id,
        "-",
    ]
    if args.runtime_surface_version == RUNTIME_SURFACE_VERSION:
        config_index = argv.index("--config")
        argv[config_index + 2:config_index + 2] = [
            "--config",
            _config_override("model_catalog_json", str(args.model_catalog_snapshot)),
        ]
    return argv


def _output_message(path: Path, normalized: dict[str, Any]) -> str | None:
    if path.is_symlink() or not path.is_file():
        return normalized["final_message"]
    file_message = path.read_text(encoding="utf-8")
    event_message = normalized["final_message"]
    if event_message is not None and file_message.strip() != event_message.strip():
        raise AdapterError("Codex event and output-last-message differ")
    return event_message if event_message is not None else file_message


def _required_final_output(path: Path) -> str:
    """Read Codex's authoritative final output for schema-bound grading."""
    if path.is_symlink() or not path.is_file():
        raise AdapterError("Codex output-last-message is missing or unsafe")
    return path.read_text(encoding="utf-8")


def _turn_answers(
    turns: list[dict[str, Any]],
    normalized_turns: list[dict[str, Any]],
    workspace: Path,
) -> dict[str, Any]:
    """Retain ordered semantic outputs without duplicating raw Codex events."""
    items = []
    total_bytes = 0
    for turn, normalized in zip(turns, normalized_turns, strict=True):
        content = _redact_text(normalized["final_message"] or "", workspace)
        content_bytes = len(content.encode("utf-8"))
        if content_bytes > 64 * 1024:
            raise AdapterError("Codex turn answer exceeds the Host bound")
        total_bytes += content_bytes
        items.append({"turn_id": turn["turn_id"], "content": content})
    if total_bytes > 256 * 1024:
        raise AdapterError("Codex turn answers exceed the Host bound")
    return {"schema_version": "codex-turn-answers/1", "items": items}


def _snapshot_workspace(workspace: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace)
        if is_workspace_infrastructure(relative):
            continue
        if path.is_symlink():
            raise AdapterError("workspace contains a symlink")
        if path.is_file():
            result[relative.as_posix()] = _file_sha256(path)
    return result


def _manifest_source_root(manifest: dict[str, Any]) -> Path:
    identity = manifest.get("identity")
    repository = identity.get("repository") if isinstance(identity, dict) else None
    worktree = repository.get("worktree") if isinstance(repository, dict) else None
    if not isinstance(worktree, str) or not Path(worktree).is_absolute():
        raise AdapterError("host manifest source worktree is invalid")
    try:
        source_root = Path(worktree).resolve(strict=True)
    except OSError as exc:
        raise AdapterError("host manifest source worktree is unavailable") from exc
    if not source_root.is_dir():
        raise AdapterError("host manifest source worktree is not a directory")
    return source_root


def _json_pointer_source_match(
    value: Any,
    source: str,
    pointer: str = "",
) -> str | None:
    if isinstance(value, str):
        if source in value:
            return pointer or "/"
        return None
    if isinstance(value, list):
        for index, item in enumerate(value):
            match = _json_pointer_source_match(item, source, f"{pointer}/{index}")
            if match is not None:
                return match
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            escaped = key.replace("~", "~0").replace("/", "~1")
            if source in key:
                return f"{pointer}/<redacted-key>"
            match = _json_pointer_source_match(
                item,
                source,
                f"{pointer}/{escaped}",
            )
            if match is not None:
                return match
    return None


def _source_exposure_diagnostic(
    child: dict[str, Any],
    source_root: Path,
) -> dict[str, Any] | None:
    source = str(source_root)
    source_bytes = source.encode("utf-8")
    for channel in ("stdout", "stderr"):
        for index, line in enumerate(child[channel].splitlines(), start=1):
            if source_bytes not in line:
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                record = None
            pointer = _json_pointer_source_match(record, source)
            record_type = record.get("type") if isinstance(record, dict) else None
            item = record.get("item") if isinstance(record, dict) else None
            item_type = item.get("type") if isinstance(item, dict) else None
            labels = [
                value
                for value in (record_type, item_type)
                if isinstance(value, str) and SAFE_ID.fullmatch(value)
            ]
            shape = "/".join(labels) if labels else "unstructured"
            location = pointer if pointer is not None else "/<unparsed>"
            return {
                "kind": "source_contamination",
                "index": index,
                "message": (
                    f"Codex {channel} record {index} ({shape}) exposed the bound "
                    f"source repository at {location}"
                ),
            }
    return None


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(_canonical_bytes(value) + b"\n")
    sys.stdout.buffer.flush()


def _validate_request(request: dict[str, Any]) -> None:
    if (
        set(request) != {"record_type", "envelope", "payload"}
        or request.get("record_type") != "skill-evaluator-host-request/2"
        or not isinstance(request.get("envelope"), dict)
        or not isinstance(request["envelope"].get("request_id"), str)
        or not SAFE_ID.fullmatch(request["envelope"]["request_id"])
        or not isinstance(request.get("payload"), dict)
    ):
        raise AdapterError("host request identity or shape is invalid")


def _reset_probe(
    request: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    proof = _artifact_json(
        "reset-proof.json",
        {
            "capability": request["payload"].get("capability"),
            "workspace": "contained",
        },
    )
    result = base_host_result(request, manifest)
    result["artifacts"] = [proof]
    result["assertions"] = [
        {
            "claim": "reset probe passed",
            "artifact": proof,
            "locally_verifiable": True,
        }
    ]
    return result


def _child_failure_result(
    request: dict[str, Any],
    manifest: dict[str, Any],
    child: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    result = base_host_result(request, manifest)
    if child["timed_out"]:
        result.update(
            {
                "terminal_status": "timeout",
                "timeout": True,
                "treatment_error": "Codex child exceeded the adapter timeout",
                "provider_error_code": None,
                "failure_class": "model_task_timeout",
            }
        )
    else:
        code = child["returncode"]
        normalized = normalize_jsonl(child["stdout"])
        failures = normalized.get("failures")
        detail = None
        failure = None
        if isinstance(failures, list) and failures:
            failure = failures[0]
            if isinstance(failure, dict):
                values = [
                    f"{field}={failure[field]}"
                    for field in ("kind", "code", "message")
                    if isinstance(failure.get(field), str) and failure[field]
                ]
                if values:
                    detail = _redact_text("; ".join(values), workspace)[
                        :MAX_FAILURE_DETAIL_CHARS
                    ]
        failure_class, provider_error_code = _provider_failure_identity(failure, code)
        result.update(
            {
                "terminal_status": "failed",
                "treatment_error": (
                    "Codex child exited without a completed turn"
                    + (f": {detail}" if detail else "")
                ),
                "provider_error_code": provider_error_code,
                "failure_class": failure_class,
            }
        )
    return result


def _provider_failure_identity(
    failure: dict[str, Any] | None,
    returncode: int,
) -> tuple[str, str]:
    """Classify only an observed, explicit Codex capacity response as transient."""
    if _is_model_capacity_failure(failure):
        return "official_transient", "model_at_capacity"
    code = (
        f"codex_signal_{-returncode}"
        if returncode < 0
        else f"codex_exit_{returncode}"
    )
    return "provider_nonretryable", code


def _is_model_capacity_failure(failure: Any) -> bool:
    return (
        isinstance(failure, dict)
        and failure.get("kind") == "codex_error"
        and failure.get("message") == MODEL_CAPACITY_MESSAGE
    )


def _run_model_grade(
    request: dict[str, Any],
    manifest: dict[str, Any],
    args: argparse.Namespace,
    workspace: Path,
) -> dict[str, Any]:
    payload = request["payload"]
    required = {
        "grader_id",
        "schedule_id",
        "grader_prompt",
        "grader_prompt_id",
        "grader_schema_id",
        "blinded_input",
    }
    grader_prompt = payload.get("grader_prompt")
    if (
        set(payload) != required
        or not isinstance(payload.get("grader_id"), str)
        or not SAFE_ID.fullmatch(payload["grader_id"])
        or not isinstance(grader_prompt, str)
        or not grader_prompt.strip()
        or any(
            not isinstance(payload.get(field), str)
            or not SAFE_ID.fullmatch(payload[field])
            for field in (
                "schedule_id",
                "grader_prompt_id",
                "grader_schema_id",
            )
        )
    ):
        raise AdapterError("model-grade instruction identity is invalid")
    batch = payload["blinded_input"]
    if (
        not isinstance(batch, dict)
        or not isinstance(batch.get("batch_id"), str)
        or not isinstance(batch.get("items"), list)
        or not batch["items"]
    ):
        raise AdapterError("model-grade blinded batch is invalid")
    with (
        tempfile.TemporaryDirectory(prefix="frontier-codex-grade-") as temp_dir,
        request_codex_home(args.isolation_tool) as codex_home,
    ):
        temporary = Path(temp_dir)
        ensure_trusted_workspace(temporary)
        schema_path = temporary / "output.schema.json"
        last_message = temporary / "last-message.json"
        schema_path.write_bytes(_canonical_bytes(model_grade_schema(batch)))
        prompt = (
            grader_prompt
            + ("" if grader_prompt.endswith("\n") else "\n")
            + "\nEvaluate only the blinded batch below. Return exactly the JSON shape "
            "required by the supplied output schema. Keep items and checks in input "
            "order; the Host binds their identities. Do not add Markdown or prose.\n"
            + json.dumps(batch, ensure_ascii=False, sort_keys=True)
        )
        child = _run_child(
            args,
            _fresh_argv(
                args,
                temporary,
                last_message,
                output_schema=schema_path,
                ephemeral=True,
                role="judge",
            ),
            prompt=prompt,
            workspace=temporary,
            codex_home=codex_home,
            timeout_seconds=args.timeout,
            capture_id=request["envelope"]["request_id"],
            last_message=last_message,
        )
        _write_child_stderr(child["stderr"], workspace, args.source_root)
        if child["timed_out"] or child["returncode"] != 0:
            return _child_failure_result(request, manifest, child, workspace)
        normalized = normalize_jsonl(child["stdout"])
        if normalized["status"] == "protocol_error":
            result = base_host_result(request, manifest)
            result["terminal_status"] = "protocol_error"
            result["protocol_error"] = host_protocol_error(normalized["diagnostics"])
            return result
        message = _required_final_output(last_message)
    try:
        output = json.loads(message) if message is not None else None
    except json.JSONDecodeError as exc:
        raise AdapterError("model-grade final message is not JSON") from exc
    if not isinstance(output, dict):
        raise AdapterError("model-grade final message is not an object")
    bound_output, identity_diagnostics = bind_model_grade_output(output, batch)
    if not identity_diagnostics and bound_output is None:
        raise AdapterError("model-grade identity binding produced no output")
    artifact = _artifact_json(
        f"model-grade-{request['envelope']['request_id']}.json",
        output if identity_diagnostics else bound_output,
    )
    usage = _captured_usage(
        manifest,
        [{
            "principal_id": f"grader-{payload['grader_id']}",
            "turn_id": None,
            "phase": "model-grade",
            "call_id": f"grade-{request['envelope']['request_id']}",
            "normalized": normalized,
            "runtime_ms": child["runtime_ms"],
        }],
    )
    if identity_diagnostics:
        result = base_host_result(request, manifest)
        result["terminal_status"] = "protocol_error"
        result["artifacts"] = [artifact]
        result["protocol_error"] = host_protocol_error(identity_diagnostics)
        result["protocol_error"]["artifact"] = artifact
        result["usage"] = usage
        return result
    result = base_host_result(request, manifest)
    result["artifacts"] = [artifact]
    result["usage"] = usage
    return result


def _run_execute_in_workspace(
    request: dict[str, Any],
    manifest: dict[str, Any],
    args: argparse.Namespace,
    workspace: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload = request["payload"]
    preflight_diagnostics = execute_evidence_diagnostics(payload, [])
    if preflight_diagnostics:
        result = base_host_result(request, manifest)
        result["terminal_status"] = "protocol_error"
        result["protocol_error"] = host_protocol_error(preflight_diagnostics)
        return [], result
    delivery: tuple[str, str, str | None] | None = None
    if args.plugin_root is not None:
        delivery = treatment_delivery(payload, args.plugin_root)
        skill_id, profile, _ = delivery
        excluded = skill_id if profile.endswith(("/skill_disabled", "/force_loaded")) else None
        prepare_workspace(
            workspace,
            args.plugin_root,
            exclude_skill_id=excluded,
        )
    workspace_timeline = WorkspaceEvidence(
        workspace,
        ignored=is_workspace_infrastructure,
    )
    workspace_timeline.capture_initial()
    started_at = _utc_now()
    normalized_turns: list[dict[str, Any]] = []
    session_id: str | None = None
    child_failure: dict[str, Any] | None = None
    lifecycle_pending: dict[str, Any] | None = None
    last_message_present = False
    with (
        tempfile.TemporaryDirectory(prefix="frontier-codex-exec-") as temp_dir,
        request_codex_home(args.isolation_tool) as codex_home,
    ):
        temporary = Path(temp_dir)
        for index, turn in enumerate(payload["turns"]):
            last_message = temporary / f"last-message-{index}.txt"
            argv = (
                _fresh_argv(
                    args,
                    workspace,
                    last_message,
                    ephemeral=len(payload["turns"]) == 1,
                )
                if session_id is None
                else _resume_argv(args, session_id, last_message)
            )
            child = _run_child(
                args,
                argv,
                prompt=(
                    force_loaded_prompt(
                        delivery[0],
                        delivery[2],
                        turn["input"]["content"],
                    )
                    if index == 0 and delivery is not None and delivery[2] is not None
                    else turn["input"]["content"]
                ),
                workspace=workspace,
                codex_home=codex_home,
                timeout_seconds=args.timeout,
                capture_id=(
                    f"{request['envelope']['request_id']}.turn-{index + 1}"
                ),
                last_message=last_message,
            )
            _write_child_stderr(child["stderr"], workspace, args.source_root)
            if child["timed_out"] or child["returncode"] != 0:
                child_failure = child
                break
            normalized = normalize_jsonl(child["stdout"])
            exposure = (
                _source_exposure_diagnostic(child, args.source_root)
                if args.plugin_root is not None
                else None
            )
            if exposure is not None:
                normalized["diagnostics"].append(exposure)
                normalized["status"] = "protocol_error"
            if args.lifecycle_contract == V2_CONTRACT and exposure is None:
                shape = classify_lifecycle(
                    child["stdout"],
                    contract_version=args.lifecycle_contract,
                )
                if shape["branch"] == "outcome_bearing_abandoned_pending_custody":
                    # The projection is deliberately single-turn.  A later
                    # resumed turn would make the abandoned command's effect
                    # boundary ambiguous, so keep the transport failure
                    # fail-closed instead of attaching the last turn's raw
                    # stream to the earlier incomplete items.
                    if len(payload["turns"]) == 1:
                        lifecycle_pending = shape
                        normalized["status"] = "completed"
                        normalized["diagnostics"] = []
            normalized["runtime_ms"] = child["runtime_ms"]
            normalized["permission_denials"] = sorted(
                {
                    *normalized["permission_denials"],
                    *observed_permission_denials(child["stdout"], child["stderr"]),
                }
            )
            if (
                index == 0
                and delivery is not None
                and delivery[1].endswith("/force_loaded")
            ):
                normalized["routing"] = {
                    "selected": [delivery[0]],
                    "loaded": [delivery[0]],
                    "applied": [delivery[0]],
                }
            elif (
                delivery is not None
                and delivery[1].endswith("/natural_routing")
                and normalized["routing"] is None
            ):
                routed = observed_skill_routing(child["stdout"], args.plugin_root)
                if routed:
                    normalized["routing"] = {
                        "selected": routed,
                        "loaded": routed,
                        "applied": routed,
                    }
            try:
                normalized["final_message"] = _output_message(last_message, normalized)
            except (OSError, UnicodeDecodeError) as exc:
                raise AdapterError("Codex output-last-message is unreadable") from exc
            last_message_present = last_message.is_file()
            workspace_timeline.capture_turn(turn["turn_id"])
            if normalized["status"] == "protocol_error":
                normalized_turns.append(normalized)
                break
            if session_id is None:
                session_id = normalized["thread_id"]
            elif normalized["thread_id"] != session_id:
                normalized["diagnostics"].append(
                    {
                        "kind": "identity_mismatch",
                        "index": None,
                        "message": "Codex resume returned a different thread identity",
                    }
                )
                normalized["status"] = "protocol_error"
            normalized_turns.append(normalized)
            if normalized["status"] != "completed":
                break

    if child_failure is not None:
        return [], _child_failure_result(request, manifest, child_failure, workspace)
    if not normalized_turns or session_id is None:
        result = base_host_result(request, manifest)
        result["terminal_status"] = "protocol_error"
        result["protocol_error"] = host_protocol_error(
            normalized_turns[-1]["diagnostics"] if normalized_turns else []
        )
        return [], result
    workspace_evidence, changed_paths = workspace_timeline.finish()
    preliminary_trace = build_command_trace(
        normalized_turns,
        [turn["turn_id"] for turn in payload["turns"][: len(normalized_turns)]],
        workspace=workspace,
        workspace_alias=ISOLATED_WORKSPACE,
        scratch_root="/tmp",
        protected_scratch_roots=(ISOLATED_WORKSPACE, ISOLATED_OUTPUT),
        normalize_text=lambda value: _redact_text(value, workspace),
        abandoned_items=(lifecycle_pending or {}).get("incomplete_items"),
    )
    lifecycle_result = None
    if lifecycle_pending is not None:
        lifecycle_result = classify_lifecycle(
            child["stdout"],
            contract_version=args.lifecycle_contract,
            custody={
                "process_exited": child_failure is None,
                "timed_out": False,
                "live_process": False,
                "workspace_clean": workspace_evidence["complete"] and not changed_paths,
                "isolation_clean": args.isolation_tool is not None,
                "effects_captured": last_message_present and not preliminary_trace["overflow"],
            },
        )
        if lifecycle_result["branch"] != "outcome_bearing_abandoned":
            result = base_host_result(request, manifest)
            result["terminal_status"] = "protocol_error"
            result["protocol_error"] = host_protocol_error([{
                "kind": "malformed_record",
                "index": None,
                "message": "lifecycle contract could not close abandoned command custody",
            }])
            return [], result

    protocol_diagnostics = execute_evidence_diagnostics(payload, normalized_turns)
    if protocol_diagnostics:
        result = base_host_result(request, manifest)
        result["terminal_status"] = "protocol_error"
        result["protocol_error"] = host_protocol_error(protocol_diagnostics)
        return [], result

    turn_ids = [
        turn["turn_id"]
        for turn in payload["turns"][: len(normalized_turns)]
    ]
    command_trace = build_command_trace(
        normalized_turns,
        turn_ids,
        workspace=workspace,
        workspace_alias=ISOLATED_WORKSPACE,
        scratch_root="/tmp",
        protected_scratch_roots=(ISOLATED_WORKSPACE, ISOLATED_OUTPUT),
        normalize_text=lambda value: _redact_text(value, workspace),
        abandoned_items=(lifecycle_result or {}).get("incomplete_items"),
    )
    terminal_status = (
        "completed"
        if len(normalized_turns) == len(payload["turns"])
        and all(turn["status"] == "completed" for turn in normalized_turns)
        else "failed"
    )
    host_observation = build_host_observation(
        terminal_status=terminal_status,
        codex_status=normalized_turns[-1]["status"],
        turn_ids=turn_ids,
        changed_paths=changed_paths,
        command_trace=command_trace,
        workspace_evidence=workspace_evidence,
        lifecycle=lifecycle_result,
    )
    final_message = normalized_turns[-1]["final_message"] or ""
    final_artifact = _artifact_bytes(
        "final-answer.md",
        _redact_text(final_message, workspace).encode("utf-8"),
    )
    turn_answers_artifact = _artifact_json(
        "turn-answers.json",
        _turn_answers(payload["turns"], normalized_turns, workspace),
    )
    command_artifact = _artifact_json("command-trace.json", command_trace)
    workspace_artifact = _artifact_json(
        "workspace-evidence.json", workspace_evidence
    )
    observation_artifact = _artifact_json(
        "host-observation.json", host_observation
    )
    artifacts = [
        final_artifact,
        turn_answers_artifact,
        command_artifact,
        workspace_artifact,
        observation_artifact,
    ]
    assertions = [
        {
            "claim": "captured final Codex message",
            "artifact": final_artifact,
            "locally_verifiable": True,
        }
    ]
    context, context_artifacts = _captured_context(
        delivery,
        request["envelope"]["request_id"],
    )
    artifacts.extend(context_artifacts)
    events, result = project_execute_result(
        request=request,
        manifest=manifest,
        normalized_turns=normalized_turns,
        session_id=session_id,
        started_at=started_at,
        ended_at=_utc_now(),
        artifacts=artifacts,
        assertions=assertions,
        treatment_error=(
            "abandoned_command_execution"
            if lifecycle_result is not None
            else None
        ),
        lifecycle=lifecycle_result,
    )
    principal_id = f"principal-{payload['execution_context']['expected_principal_slots'][0]}"
    result["usage"] = _captured_usage(
        manifest,
        [
            {
                "principal_id": principal_id,
                "turn_id": turn["turn_id"],
                "phase": "execute",
                "call_id": f"codex-{index + 1}",
                "normalized": normalized,
                "runtime_ms": normalized["runtime_ms"],
            }
            for index, (turn, normalized) in enumerate(
                zip(payload["turns"], normalized_turns, strict=True)
            )
        ],
    )
    result["context"] = context
    return events, result


def _run_execute(
    request: dict[str, Any],
    manifest: dict[str, Any],
    args: argparse.Namespace,
    workspace: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.plugin_root is None or args.sandbox != "read-only":
        return _run_execute_in_workspace(request, manifest, args, workspace)

    catalog = workspace / ".agents" / "skills"
    if catalog.exists() or catalog.is_symlink():
        raise DeliveryError("workspace already contains an Agent Skill catalog")
    _snapshot_workspace(workspace)
    with tempfile.TemporaryDirectory(prefix="frontier-codex-workspace-") as temp_dir:
        isolated = Path(temp_dir) / "workspace"
        shutil.copytree(
            workspace,
            isolated,
            copy_function=shutil.copy2,
            ignore=shutil.ignore_patterns(".agents", ".git"),
        )
        return _run_execute_in_workspace(request, manifest, args, isolated)


def _run_host_mode(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    workspace: Path,
) -> int:
    line = sys.stdin.buffer.readline()
    if not line or sys.stdin.buffer.readline():
        raise AdapterError("host mode requires exactly one JSON request line")
    request = json.loads(line)
    if not isinstance(request, dict):
        raise AdapterError("host request must be an object")
    _validate_request(request)
    request_kind = request["envelope"].get("request_kind")
    if request_kind == "probe_capability":
        result = _reset_probe(request, manifest)
        events: list[dict[str, Any]] = []
    elif request_kind == "model_grade":
        result = _run_model_grade(request, manifest, args, workspace)
        events = []
    elif request_kind == "execute_case":
        events, result = _run_execute(request, manifest, args, workspace)
    elif request_kind == "cleanup":
        result = base_host_result(request, manifest)
        events = []
    else:
        raise AdapterError("unsupported host request kind")
    for event in events:
        _emit(event)
    _emit(result)
    return 0


def _run_probe_mode(args: argparse.Namespace, workspace: Path) -> int:
    line = sys.stdin.buffer.readline()
    if not line or sys.stdin.buffer.readline():
        raise AdapterError("probe mode requires exactly one JSON row")
    row = json.loads(line)
    required = {
        "schema_version",
        "probe_id",
        "capability",
        "prompt",
        "expected_event_types",
    }
    if (
        not isinstance(row, dict)
        or set(row) != required
        or row["schema_version"] != "codex-interaction-probe/1.0"
        or not isinstance(row["probe_id"], str)
        or not SAFE_ID.fullmatch(row["probe_id"])
        or not isinstance(row["capability"], str)
        or row["capability"] not in PROBE_CAPABILITIES
        or not isinstance(row["prompt"], str)
        or not row["prompt"]
        or not isinstance(row["expected_event_types"], list)
        or any(not isinstance(item, str) for item in row["expected_event_types"])
    ):
        raise AdapterError("interaction probe row is invalid")
    forced: tuple[str, str] | None = None
    if args.plugin_root is not None:
        if row["capability"] == "force_load":
            forced = forced_probe_delivery(row["prompt"], args.plugin_root)
        prepare_workspace(
            workspace,
            args.plugin_root,
            exclude_skill_id=forced[0] if forced is not None else None,
        )
    with (
        tempfile.TemporaryDirectory(prefix="frontier-codex-probe-") as temp_dir,
        request_codex_home(args.isolation_tool) as codex_home,
    ):
        last_message = Path(temp_dir) / "last-message.txt"
        workspace_before, workspace_before_ok = _probe_workspace_snapshot(workspace)
        probe_prompt = (
            force_loaded_prompt(forced[0], forced[1], row["prompt"])
            if forced is not None
            else row["prompt"]
        )
        child = _run_child(
            args,
            _fresh_argv(
                args,
                workspace,
                last_message,
                ephemeral=True,
            ),
            prompt=probe_prompt,
            workspace=workspace,
            codex_home=codex_home,
            timeout_seconds=args.timeout,
            capture_id=f"probe-{row['probe_id']}",
            last_message=last_message,
        )
        _write_child_stderr(child["stderr"], workspace, args.source_root)
        normalized = normalize_jsonl(child["stdout"])
        if normalized is not None:
            normalized["permission_denials"] = sorted(
                {
                    *normalized["permission_denials"],
                    *observed_permission_denials(child["stdout"], child["stderr"]),
                }
            )
            if args.plugin_root is not None and normalized["routing"] is None:
                routed = observed_skill_routing(child["stdout"], args.plugin_root)
                if routed:
                    normalized["routing"] = {
                        "selected": routed,
                        "loaded": routed,
                        "applied": routed,
                    }
        workspace_after, workspace_after_ok = _probe_workspace_snapshot(workspace)
        lifecycle, status, diagnostics = _probe_lifecycle_projection(
            child,
            normalized,
            workspace=workspace,
            workspace_before=workspace_before,
            workspace_after=workspace_after,
            workspace_before_ok=workspace_before_ok,
            workspace_after_ok=workspace_after_ok,
            last_message=last_message,
            source_root=args.source_root,
            isolated=args.isolation_tool is not None,
            required_event_types=row["expected_event_types"],
            excluded_failure_values=tuple(
                value
                for value in (
                    probe_prompt,
                    normalized.get("final_message"),
                    *(
                        item.get(field)
                        for item in normalized.get("items", [])
                        if isinstance(item, dict)
                        for field in ("command", "aggregated_output", "query")
                    ),
                )
                if isinstance(value, str)
            ),
        )
    if forced is not None and status == "pass":
        normalized["routing"] = {
            "selected": [forced[0]],
            "loaded": [forced[0]],
            "applied": [forced[0]],
        }
    observed_types = _canonical_probe_event_types(normalized["event_types"])
    direct_observations = []
    if normalized["routing"] is not None:
        direct_observations.append("direct.routing")
    if normalized["usage"] is not None:
        direct_observations.append("direct.usage")
    if normalized["permission_denials"]:
        direct_observations.append("permission.denied")
    observations = [*observed_types, *direct_observations]
    lifecycle["required_events_complete"] = set(
        row["expected_event_types"]
    ) <= set(observations)
    capability_observed = {
        "force_load": bool(forced is not None and status == "pass"),
        "natural_routing": bool(
            normalized["routing"] is not None
            and normalized["routing"]["selected"]
        ),
        "usage_capture": bool(normalized["usage"] is not None),
        "action_authorization_trace": bool(
            normalized["permission_denials"]
        ),
        # Current Codex JSONL has no direct principal record, and one probe request
        # cannot establish same-thread resume. Preserve both as unknown.
        "principal_tracing": False,
        "multi_turn": False,
    }[row["capability"]]
    status, diagnostics = _apply_probe_capability_projection(
        lifecycle,
        status,
        diagnostics,
        capability=row["capability"],
        capability_observed=capability_observed,
    )
    _emit(
        {
            "schema_version": PROBE_RESULT_SCHEMA_VERSION,
            "probe_id": row["probe_id"],
            "capability": row["capability"],
            "status": status,
            "observed": (
                "required direct Codex events observed"
                if status == "pass"
                else "required direct Codex events were not established"
            ),
            "session_id": normalized["thread_id"] if normalized is not None else None,
            "event_types": observed_types,
            "direct_observations": direct_observations,
            "routing": (
                normalized["routing"]["selected"]
                if normalized is not None and normalized["routing"] is not None
                else []
            ),
            "usage": normalized["usage"] if normalized is not None else None,
            "diagnostics": diagnostics,
            "lifecycle": lifecycle,
        }
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("host", "probe"), default="host")
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--codex-sha256", required=True)
    parser.add_argument("--codex-version", required=True)
    parser.add_argument("--isolation-tool", type=Path)
    parser.add_argument("--isolation-tool-sha256")
    parser.add_argument("--code-mode-host", type=Path)
    parser.add_argument("--code-mode-host-sha256")
    parser.add_argument("--host-manifest", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--judge-model")
    parser.add_argument("--judge-effort")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--plugin-root", type=Path)
    parser.add_argument("--model-catalog-snapshot", type=Path)
    parser.add_argument("--model-catalog-relative-path")
    parser.add_argument("--model-catalog-sha256")
    parser.add_argument("--model-catalog-client-version")
    parser.add_argument("--runtime-surface-version")
    parser.add_argument(
        "--sandbox", choices=("read-only", "workspace-write"), required=True
    )
    parser.add_argument(
        "--probe-sandbox", choices=("read-only", "workspace-write")
    )
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument(
        "--lifecycle-contract",
        choices=(LEGACY_CONTRACT, V2_CONTRACT),
        default=LEGACY_CONTRACT,
    )
    parser.add_argument("--diagnostic-capture-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        args.codex = args.codex.resolve(strict=True)
        if args.isolation_tool is not None:
            args.isolation_tool = args.isolation_tool.resolve(strict=True)
        if args.code_mode_host is not None:
            args.code_mode_host = args.code_mode_host.resolve(strict=True)
        if args.plugin_root is not None:
            args.plugin_root = args.plugin_root.resolve(strict=True)
        if args.model_catalog_snapshot is not None:
            args.model_catalog_snapshot = args.model_catalog_snapshot.resolve(strict=True)
        if args.diagnostic_capture_dir is not None:
            args.diagnostic_capture_dir = args.diagnostic_capture_dir.resolve(
                strict=False
            )
            if args.diagnostic_capture_dir.is_symlink():
                raise AdapterError("diagnostic capture directory is symlinked")
        if (
            not math.isfinite(args.timeout)
            or args.timeout <= 0
            or not args.codex_sha256.startswith("sha256:")
        ):
            raise AdapterError("adapter timeout or Codex hash is invalid")
        workspace = Path.cwd().resolve(strict=True)
        manifest = _validate_manifest(args.host_manifest.resolve(strict=True), args)
        args.source_root = _manifest_source_root(manifest)
        if args.mode == "probe":
            if args.probe_sandbox is None:
                raise AdapterError("probe mode requires its frozen sandbox")
            args.sandbox = args.probe_sandbox
            return _run_probe_mode(args, workspace)
        if args.probe_sandbox is not None:
            raise AdapterError("host mode cannot override the manifest sandbox")
        return _run_host_mode(args, manifest, workspace)
    except (
        AdapterError,
        ArtifactError,
        DeliveryError,
        IsolationError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"codex_eval_host: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
