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
    observed_permission_denials,
    observed_skill_routing,
    prepare_workspace,
    project_command_environment,
    skill_isolation_argv,
    treatment_delivery,
    validate_plugin_catalog,
)
from _codex_eval_events import (
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
    ISOLATED_SANDBOX_POLICY_IDS,
    ISOLATED_WORKSPACE,
    IsolationError,
    isolated_child_argv,
    request_codex_home,
)


MAX_STDERR_BYTES = 64 * 1024
MAX_FAILURE_DETAIL_CHARS = 2048
ADAPTER_VERSION = "1.12"
ADAPTER_SOURCE_FILES = (
    "_bundle_hash.py",
    "_codex_eval_artifacts.py",
    "_codex_eval_delivery.py",
    "_codex_eval_events.py",
    "_codex_eval_isolation.py",
    "codex_eval_host.py",
)
PROBE_RESULT_SCHEMA_VERSION = "codex-interaction-probe-result/1.1"
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


def _validate_manifest(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    manifest = _load_json_object(path)
    identity = manifest.get("identity")
    execution = identity.get("execution") if isinstance(identity, dict) else None
    adapter = identity.get("adapter") if isinstance(identity, dict) else None
    if not isinstance(execution, dict) or execution.get("model") != args.model:
        raise AdapterError("model identity differs from the host manifest")
    if execution.get("tool_schema_id") != isolated_tool_schema_id(
        args.codex_sha256,
        args.isolation_tool_sha256,
        args.code_mode_host_sha256,
    ):
        raise AdapterError("tool schema identity differs from the host manifest")
    if (
        args.isolation_tool is not None
        and execution.get("policy_id")
        != ISOLATED_SANDBOX_POLICY_IDS.get(args.sandbox)
    ):
        raise AdapterError("sandbox policy identity differs from the runtime")
    if (
        not isinstance(adapter, dict)
        or adapter.get("id") != "codex-eval-host"
        or adapter.get("version") != ADAPTER_VERSION
    ):
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
    if (
        bound_codex != args.codex
        or bound_manifest != path
        or bound_timeout != args.timeout
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
        timeout = float(_bound_command_option(argv, "--timeout"))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise AdapterError("host manifest command binding is invalid") from exc
    if (
        declared != executable
        or command.get("executable_digest") != _file_sha256(executable)
    ):
        raise AdapterError("host manifest executable identity differs")
    args = argparse.Namespace(
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
    try:
        stdout, stderr = process.communicate(
            input=prompt.encode("utf-8"),
            timeout=max(timeout_seconds, 0.001),
        )
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        timed_out = True
    return {
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "runtime_ms": round((time.monotonic() - started) * 1000, 3),
    }


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
    return {
        "pricing_identity": manifest["identity"]["execution"]["pricing_id"],
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
) -> list[str]:
    argv = [
        str(args.codex),
        "exec",
        "--json",
        "--strict-config",
        "--color",
        "never",
        "--model",
        args.model,
        *_profile_argv(args.profile),
        *(
            skill_isolation_argv(
                include_installed_skills=args.isolation_tool is None,
            )
            if args.plugin_root
            else []
        ),
        "--sandbox",
        args.sandbox,
        "--cd",
        str(workspace),
        "--config",
        _config_override("model_reasoning_effort", args.effort),
        "--output-last-message",
        str(last_message),
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
    return [
        str(args.codex),
        "exec",
        "resume",
        "--json",
        "--strict-config",
        "--model",
        args.model,
        *_profile_argv(args.profile),
        *(
            skill_isolation_argv(
                include_installed_skills=args.isolation_tool is None,
            )
            if args.plugin_root
            else []
        ),
        "--config",
        _config_override("model_reasoning_effort", args.effort),
        "--output-last-message",
        str(last_message),
        session_id,
        "-",
    ]


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
            ),
            prompt=prompt,
            workspace=temporary,
            codex_home=codex_home,
            timeout_seconds=args.timeout,
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
        normalize_text=lambda value: _redact_text(value, workspace),
    )
    workspace_evidence, changed_paths = workspace_timeline.finish()
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
    )
    final_message = normalized_turns[-1]["final_message"] or ""
    final_artifact = _artifact_bytes(
        "final-answer.md",
        _redact_text(final_message, workspace).encode("utf-8"),
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
        child = _run_child(
            args,
            _fresh_argv(
                args,
                workspace,
                last_message,
                ephemeral=True,
            ),
            prompt=(
                force_loaded_prompt(forced[0], forced[1], row["prompt"])
                if forced is not None
                else row["prompt"]
            ),
            workspace=workspace,
            codex_home=codex_home,
            timeout_seconds=args.timeout,
        )
        _write_child_stderr(child["stderr"], workspace, args.source_root)
        normalized = (
            normalize_jsonl(child["stdout"])
            if not child["timed_out"] and child["returncode"] == 0
            else None
        )
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
    child_diagnostics = []
    if normalized is None:
        child_diagnostics = _child_failure_diagnostics(child, workspace)
    elif forced is not None and normalized["status"] == "completed":
        normalized["routing"] = {
            "selected": [forced[0]],
            "loaded": [forced[0]],
            "applied": [forced[0]],
        }
    observed_types = normalized["event_types"] if normalized is not None else []
    direct_observations = []
    if normalized is not None:
        if normalized["routing"] is not None:
            direct_observations.append("direct.routing")
        if normalized["usage"] is not None:
            direct_observations.append("direct.usage")
        if normalized["permission_denials"]:
            direct_observations.append("permission.denied")
    observations = [*observed_types, *direct_observations]
    capability_observed = {
        "force_load": bool(
            normalized is not None
            and forced is not None
            and normalized["status"] == "completed"
        ),
        "natural_routing": bool(
            normalized is not None
            and normalized["routing"] is not None
            and normalized["routing"]["selected"]
        ),
        "usage_capture": bool(
            normalized is not None and normalized["usage"] is not None
        ),
        "action_authorization_trace": bool(
            normalized is not None and normalized["permission_denials"]
        ),
        # Current Codex JSONL has no direct principal record, and one probe request
        # cannot establish same-thread resume. Preserve both as unknown.
        "principal_tracing": False,
        "multi_turn": False,
    }[row["capability"]]
    status = (
        "pass"
        if normalized is not None
        and normalized["status"] == "completed"
        and capability_observed
        and set(row["expected_event_types"]) <= set(observations)
        else "unknown"
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
            "diagnostics": (
                normalized["diagnostics"]
                if normalized is not None
                else child_diagnostics
            ),
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
    parser.add_argument("--profile", required=True)
    parser.add_argument("--plugin-root", type=Path)
    parser.add_argument(
        "--sandbox", choices=("read-only", "workspace-write"), required=True
    )
    parser.add_argument(
        "--probe-sandbox", choices=("read-only", "workspace-write")
    )
    parser.add_argument("--timeout", type=float, required=True)
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
