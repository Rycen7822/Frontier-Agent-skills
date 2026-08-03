#!/usr/bin/env python3
"""Execute a compiled Skill Evaluator plan into receipt v4 and index v2."""

from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only off POSIX
    fcntl = None

import compile_eval_plan as compiler
import model_grade_transport as model_transport
from runner_status import project_runner_status
from evidence_io import (
    artifact_record,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_jsonl,
    canonical_json_bytes,
    canonical_self_hash,
    canonical_sha256,
    file_sha256,
    load_json,
    load_jsonl_objects,
    normalize_relative_path,
    resolve_contained_path,
    validate_locator,
    verify_artifact_records,
    verify_self_hash,
)
from validate_eval_suite import (
    load_v5_schema_registry,
    validate_host_protocol_record,
    validate_v5_schema,
)


class RunnerFailure(RuntimeError):
    """A fail-closed plan, protocol, identity, CLI, or evidence error."""


class ApparatusFailure(RuntimeError):
    """An execution failure that did not produce complete evidence."""


class BudgetExhausted(ApparatusFailure):
    """The invocation cannot create another authorized attempt."""


ATTEMPT_CUSTODY_NAME = "attempt-custody.lock"


def _owned_lock_stat(fd: int, path: Path) -> os.stat_result:
    opened = os.fstat(fd)
    current = path.lstat()
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or opened.st_uid != os.geteuid()
        or stat.S_IMODE(opened.st_mode) & 0o077
        or (opened.st_dev, opened.st_ino)
        != (current.st_dev, current.st_ino)
    ):
        raise RunnerFailure("attempt custody lock is not owner-safe")
    return opened


class _AttemptCustody:
    """Hold one attempt's transient POSIX custody lock."""

    def __init__(self, attempt_dir: Path) -> None:
        self.path = attempt_dir / ATTEMPT_CUSTODY_NAME
        self.fd: int | None = None
        self._committed = False

    def __enter__(self) -> _AttemptCustody:
        if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
            raise RunnerFailure("POSIX attempt custody is unsupported")
        try:
            fd = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
            )
        except OSError as exc:
            raise RunnerFailure("attempt custody lock is invalid") from exc
        try:
            _owned_lock_stat(fd, self.path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RunnerFailure("attempt is still active") from exc
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return self

    def commit(self) -> None:
        """Allow owner-only lock removal after receipt/index commit."""
        self._committed = True

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.fd is None:
            return
        try:
            if exc_type is None and self._committed:
                _owned_lock_stat(self.fd, self.path)
                self.path.unlink()
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


class _AttemptBudget:
    def __init__(self, authorized: int) -> None:
        self.authorized = authorized
        self.remaining = authorized

    def consume(self) -> None:
        self.ensure_available()
        self.remaining -= 1

    def ensure_available(self) -> None:
        if self.remaining < 1:
            raise BudgetExhausted("new-attempt budget exhausted")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


def _parse_utc(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc,
    )


def _validate_calibration_time(
    entry: dict[str, Any],
    spec: dict[str, Any],
    spec_path: Path,
    observed_at: str,
) -> None:
    if not entry["model_grade_specs"]:
        return
    binding = spec["suite"].get("calibration")
    if not isinstance(binding, dict):
        raise RunnerFailure("model grading lacks a calibration binding")
    _, calibration_path = resolve_contained_path(
        spec_path.parent,
        binding["path"],
        "grader calibration",
        kind="file",
    )
    calibration = load_json(calibration_path)
    observed = _parse_utc(observed_at)
    created = _parse_utc(calibration["created"])
    expires = _parse_utc(calibration["expires"])
    if not created <= observed <= expires:
        raise ApparatusFailure(
            "attempt time is outside the grader calibration window",
        )


def _first_diagnostic(diagnostics: list[dict[str, str]]) -> str:
    item = diagnostics[0]
    return f"{item['code']} {item['path']}: {item['message']}"


def _load_plan(
    plan_path: Path,
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    plan = load_json(plan_path)
    diagnostics = validate_v5_schema(
        plan, "execution-plan-v1.schema.json", registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    if not verify_self_hash(plan, "plan_hash"):
        raise RunnerFailure("plan_hash does not match the canonical plan")
    return plan


def _find_bound_spec(
    plan: dict[str, Any],
    plan_path: Path,
) -> Path:
    matches: list[Path] = []
    for candidate in sorted(plan_path.parent.glob("*.json")):
        if candidate == plan_path or not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            value = load_json(candidate)
        except ValueError:
            continue
        if (
            isinstance(value, dict)
            and value.get("schema_version") == 5
            and value.get("evaluation_id") == plan["evaluation_id"]
            and canonical_sha256(compiler._normalize_spec(value))
            == plan["spec_hash"]
        ):
            matches.append(candidate)
    if len(matches) != 1:
        raise RunnerFailure(
            "plan parent must contain exactly one spec matching plan spec_hash",
        )
    return matches[0]


def _load_bound_contract(
    plan: dict[str, Any],
    plan_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, dict[str, Any]],
    Path,
]:
    spec_path = _find_bound_spec(plan, plan_path)
    spec = load_json(spec_path)
    _, scenarios_path = resolve_contained_path(
        spec_path.parent,
        spec["suite"]["scenarios"]["path"],
        "scenario corpus",
        kind="file",
    )
    _, host_path = resolve_contained_path(
        spec_path.parent,
        spec["host"]["manifest"]["path"],
        "host manifest",
        kind="file",
    )
    loaded = compiler._load_ready_contract(
        spec_path, scenarios_path, host_path,
    )
    spec, scenarios, host, registry = loaded
    compiler.validate_compiled_plan(
        plan,
        spec,
        scenarios,
        host,
        spec_path=spec_path,
        source_path=Path(compiler.__file__).resolve(),
        registry=registry,
        runtime_override=plan["compiler"],
    )
    return spec, scenarios, host, registry, spec_path


def _run_projection(
    plan_hash: str,
    entry_id: str,
    attempt: int,
) -> dict[str, Any]:
    return {
        "plan_hash": plan_hash,
        "entry_id": entry_id,
        "attempt": attempt,
    }


def _attempt_identity(
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt: int,
) -> tuple[str, str]:
    run_id = (
        "run-"
        + canonical_sha256(
            _run_projection(plan["plan_hash"], entry["entry_id"], attempt),
        ).removeprefix("sha256:")[:24]
    )
    ownership_token = canonical_sha256({
        "plan_hash": plan["plan_hash"],
        "run_id": run_id,
        "purpose": "task-ownership",
    })
    return run_id, ownership_token


def _attempt_paths(
    plan_path: Path,
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt: int,
) -> tuple[Path, str, Path]:
    _, artifacts_root = resolve_contained_path(
        plan_path.parent,
        plan["artifacts"]["root"],
        "artifacts root",
    )
    entry_rel = normalize_relative_path(
        entry["artifact_relpath"], "entry artifact path",
    )
    attempt_rel = f"{entry_rel}/attempt-{attempt:04d}"
    attempt_dir = (artifacts_root / attempt_rel).resolve()
    if not attempt_dir.is_relative_to(artifacts_root.resolve()):
        raise RunnerFailure("attempt path escapes artifacts root")
    return artifacts_root, attempt_rel, attempt_dir


@contextmanager
def _new_attempt_custody(
    plan_path: Path,
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt: int,
    budget: _AttemptBudget,
) -> Iterator[_AttemptCustody]:
    artifacts_root, attempt_rel, attempt_dir = _attempt_paths(
        plan_path, plan, entry, attempt,
    )
    budget.consume()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    if artifacts_root.is_symlink() or not artifacts_root.is_dir():
        raise RunnerFailure("artifacts root must be a regular directory")
    attempt_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        attempt_dir.mkdir()
    except FileExistsError as exc:
        raise RunnerFailure(
            f"attempt path already exists without --resume: {attempt_rel}",
        ) from exc
    with _AttemptCustody(attempt_dir) as custody:
        yield custody


def _lock_is_busy(attempt_dir: Path) -> bool:
    """Probe an existing lock without creating or mutating it."""
    path = attempt_dir / ATTEMPT_CUSTODY_NAME
    if path.is_symlink():
        raise RunnerFailure("attempt custody lock is invalid")
    if not path.exists():
        return False
    if not path.is_file():
        raise RunnerFailure("attempt custody lock is invalid")
    if fcntl is None or not hasattr(os, "O_NOFOLLOW"):
        raise RunnerFailure("POSIX attempt custody is unsupported")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RunnerFailure("attempt custody lock is invalid") from exc
    try:
        _owned_lock_stat(fd, path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _build_marker(
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt: int,
    run_id: str,
    ownership_token: str,
) -> dict[str, Any]:
    marker = {
        "schema_version": 1,
        "marker_hash": "sha256:" + "0" * 64,
        "plan_hash": plan["plan_hash"],
        "plan_id": plan["plan_id"],
        "entry_ordinal": entry["entry_ordinal"],
        "entry_id": entry["entry_id"],
        "attempt": attempt,
        "run_id": run_id,
        "ownership_token": ownership_token,
    }
    marker["marker_hash"] = canonical_self_hash(marker, "marker_hash")
    return marker


def _validate_host_command(
    host: dict[str, Any],
    contract_root: Path,
) -> tuple[list[str], dict[str, str]]:
    command = host["command"]
    executable = Path(command["resolved_executable"])
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or executable.is_symlink()
    ):
        raise RunnerFailure("host resolved executable must be an absolute regular file")
    if file_sha256(executable) != command["executable_sha256"]:
        raise RunnerFailure("host executable sha256 mismatch")
    declared = command["argv"]
    declared_executable = Path(declared[0])
    if declared_executable.is_absolute():
        declared_resolution = declared_executable.resolve()
    elif len(declared_executable.parts) == 1:
        declared_resolution = (executable.parent / declared[0]).resolve()
    else:
        raise RunnerFailure("host argv[0] must be absolute or an executable name")
    if declared_resolution != executable.resolve():
        raise RunnerFailure("host argv[0] does not resolve to the bound executable")

    argv = [str(executable.resolve())]
    for argument in declared[1:]:
        candidate = contract_root / argument
        argv.append(str(candidate.resolve()) if candidate.is_file() else argument)
    environment = {
        name: os.environ[name]
        for name in command["env_allowlist"]
        if name in os.environ
    }
    return argv, environment


def _host_request(
    plan: dict[str, Any],
    entry: dict[str, Any],
    run_id: str,
    attempt: int,
    request_kind: str = "execute_case",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = {
        "record_type": "skill-evaluator-host-request/1",
        "request_hash": "sha256:" + "0" * 64,
        "envelope": {
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
            "entry_ordinal": entry["entry_ordinal"],
            "entry_id": entry["entry_id"],
            "run_id": run_id,
            "attempt": attempt,
            "request_kind": request_kind,
        },
        "payload": copy.deepcopy(
            entry["execute_case_payload"] if payload is None else payload,
        ),
    }
    request["request_hash"] = canonical_self_hash(request, "request_hash")
    return request


def _invocation_record(
    *,
    declared_argv: list[str],
    resolved_argv: list[str],
    environment: dict[str, str],
    executable: Path,
    cwd: Path,
    attempt_dir: Path,
    timeout_seconds: int,
    credential_policy: str,
) -> dict[str, Any]:
    return {
        "declared_argv": declared_argv,
        "resolved_argv": resolved_argv,
        "resolved_executable_sha256": file_sha256(executable),
        "cwd": cwd.relative_to(attempt_dir).as_posix(),
        "env_allowlist": sorted(environment),
        "env": [
            {
                "name": name,
                "value_sha256": "sha256:"
                + sha256(value.encode("utf-8")).hexdigest(),
            }
            for name, value in sorted(environment.items())
        ],
        "credential_policy": credential_policy,
        "shell": False,
        "start_new_session": True,
        "timeout_seconds": timeout_seconds,
    }


def _run_process(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    input_bytes: bytes,
    timeout_seconds: int,
    custody_fd: int,
) -> tuple[int, bytes, bytes]:
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            pass_fds=(custody_fd,),
        )
    except OSError as exc:
        raise ApparatusFailure("child process could not start") from exc
    try:
        stdout, stderr = process.communicate(
            input=input_bytes,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        raise ApparatusFailure(
            f"host process exceeded {timeout_seconds} seconds",
        ) from exc
    return process.returncode, stdout, stderr


def _parse_host_protocol(
    raw_stdout: bytes,
    *,
    request: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    try:
        lines = raw_stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise RunnerFailure(f"host protocol stdout is not UTF-8: {exc}") from None
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(lines, 1):
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunnerFailure(
                f"malformed host record at stdout line {line_no}: {exc.msg}",
            ) from None
        if not isinstance(value, dict):
            raise RunnerFailure(
                f"host record at stdout line {line_no} is not an object",
            )
        records.append(value)

    events: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    terminal_seen = False
    for record in records:
        record_type = record.get("record_type")
        if terminal_seen:
            raise RunnerFailure("host emitted a record after its terminal result")
        if record_type == "skill-evaluator-host-event/1":
            diagnostics = validate_host_protocol_record(
                "host_event", record, registry,
            )
            if diagnostics:
                raise RunnerFailure(_first_diagnostic(diagnostics))
            events.append(record)
        elif record_type == "skill-evaluator-host-result/1":
            diagnostics = validate_host_protocol_record(
                "host_result", record, registry,
            )
            if diagnostics:
                raise RunnerFailure(_first_diagnostic(diagnostics))
            results.append(record)
            terminal_seen = True
        else:
            raise RunnerFailure("host emitted an unknown protocol record type")
    if len(results) != 1:
        raise RunnerFailure("host protocol requires exactly one terminal result")
    if [event["seq"] for event in events] != list(range(len(events))):
        raise RunnerFailure("host event sequence must be the continuous prefix from zero")

    result = results[0]
    envelope = request["envelope"]
    if result["envelope"] != envelope or result["request_hash"] != request[
        "request_hash"
    ]:
        raise RunnerFailure("host terminal identity does not match the request")
    for event in events:
        if event["principal_id"] not in {
            principal["principal_id"] for principal in result["principals"]
        }:
            raise RunnerFailure("host event principal is absent from terminal result")
    checkpoints = [
        event["checkpoint"]
        for event in events
        if event["checkpoint"] is not None
    ]
    if result["state"] != checkpoints:
        raise RunnerFailure("host result state does not match event checkpoints")
    return events, result, checkpoints


def _validate_runtime_records(
    entry: dict[str, Any],
    result: dict[str, Any],
    host: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> None:
    principals = result["principals"]
    slots = [principal["slot_id"] for principal in principals]
    if len(slots) != len(set(slots)) or set(slots) != set(
        entry["principal_slot_ids"],
    ):
        raise RunnerFailure("actual principal slots do not match the plan entry")
    coordination = entry["execute_case_payload"]["coordination"]
    slot_contracts = (
        {
            slot["slot_id"]: slot
            for slot in coordination["principal_slots"]
        }
        if coordination is not None
        else {}
    )
    principal_ids = {principal["principal_id"] for principal in principals}
    if len({
        principal["session_id"] for principal in principals
    }) != len(principals):
        raise RunnerFailure("principal session identities are not isolated")
    for principal in principals:
        diagnostics = validate_host_protocol_record(
            "principal", principal, registry,
        )
        if diagnostics:
            raise RunnerFailure(_first_diagnostic(diagnostics))
        parent = principal["parent_principal_id"]
        if parent is not None and parent not in principal_ids:
            raise RunnerFailure("principal parent is absent from the result")
        execution = host["identity"]["execution"]
        for field in (
            "provider", "model_revision", "prompt_hash", "skill_hash",
            "catalog_hash", "policy_hash",
        ):
            if principal[field] != execution[field]:
                raise RunnerFailure(f"principal {field} differs from host identity")
        if coordination is None:
            if principal["model"] != execution["model"]:
                raise RunnerFailure("principal model differs from host identity")
            if principal["tool_schema_hash"] != execution["tool_schema_hash"]:
                raise RunnerFailure("principal tool schema differs from host identity")
            if principal["authority_hash"] != entry["execute_case_payload"][
                "permission_policy"
            ]:
                raise RunnerFailure("principal authority differs from entry policy")
        else:
            slot = slot_contracts[principal["slot_id"]]
            parent_slot = slot["parent_slot_id"]
            expected_parent = (
                next(
                    item["principal_id"] for item in principals
                    if item["slot_id"] == parent_slot
                )
                if parent_slot is not None
                else None
            )
            for actual, expected, label in (
                (principal["parent_principal_id"], expected_parent, "parent"),
                (principal["role"], slot["role"], "role"),
                (principal["model"], slot["allowed_model_class"], "model"),
                (principal["context_mode"], slot["context_mode"], "context mode"),
                (
                    principal["tool_schema_hash"],
                    slot["tool_schema_ceiling"],
                    "tool schema",
                ),
                (
                    principal["authority_hash"],
                    slot["authority_ceiling"],
                    "authority",
                ),
            ):
                if actual != expected:
                    raise RunnerFailure(
                        f"principal {label} differs from its plan slot",
                    )
            for field, ceiling in slot["budget_ceiling"].items():
                if principal["effective_budget"][field] > ceiling:
                    raise RunnerFailure(
                        f"principal {field} budget exceeds its plan slot",
                    )

    principal_by_id = {
        principal["principal_id"]: principal for principal in principals
    }
    span_ids = [principal["span_id"] for principal in principals]
    if len(span_ids) != len(set(span_ids)):
        raise RunnerFailure("principal span identities are not unique")
    for principal in principals:
        parent_id = principal["parent_principal_id"]
        expected_parent_span = (
            principal_by_id[parent_id]["span_id"]
            if parent_id is not None
            else None
        )
        if principal["parent_span_id"] != expected_parent_span:
            raise RunnerFailure(
                "principal parent span differs from its causal parent",
            )

    for principal in principals:
        seen: set[str] = set()
        current: dict[str, Any] | None = principal
        while current is not None:
            current_id = current["principal_id"]
            if current_id in seen:
                raise RunnerFailure("principal parent graph contains a cycle")
            seen.add(current_id)
            parent_id = current["parent_principal_id"]
            current = (
                next(
                    item for item in principals
                    if item["principal_id"] == parent_id
                )
                if parent_id is not None
                else None
            )
    if coordination is not None:
        if len(principals) > min(
            coordination["max_width"], coordination["max_in_flight"],
        ):
            raise RunnerFailure("principal width/in-flight limit exceeded")
        depth_by_id: dict[str, int] = {}

        def depth(principal: dict[str, Any]) -> int:
            principal_id = principal["principal_id"]
            if principal_id not in depth_by_id:
                parent_id = principal["parent_principal_id"]
                depth_by_id[principal_id] = (
                    1
                    if parent_id is None
                    else 1 + depth(next(
                        item for item in principals
                        if item["principal_id"] == parent_id
                    ))
                )
            return depth_by_id[principal_id]

        if max(map(depth, principals), default=0) > coordination["max_depth"]:
            raise RunnerFailure("principal depth limit exceeded")

    handoffs = result["handoffs"]
    handoff_ids = [item["handoff_id"] for item in handoffs]
    if (
        len(handoff_ids) != len(set(handoff_ids))
        or set(handoff_ids) != set(entry["handoff_ids"])
    ):
        raise RunnerFailure("actual handoffs do not match the plan entry")
    handoff_spans = [item["span_id"] for item in handoffs]
    if len(handoff_spans) != len(set(handoff_spans)):
        raise RunnerFailure("handoff span identities are not unique")
    for handoff in handoffs:
        diagnostics = validate_host_protocol_record(
            "handoff", handoff, registry,
        )
        if diagnostics:
            raise RunnerFailure(_first_diagnostic(diagnostics))
        transform = handoff["transform"]
        if (transform["kind"] == "none") != (transform["artifact"] is None):
            raise RunnerFailure("handoff transform evidence is inconsistent")
    if coordination is not None:
        expected_edges = {
            handoff_id: edge
            for handoff_id, edge in zip(
                compiler._declared_handoff_ids(
                    entry["execute_case_payload"]["case"],
                ),
                coordination["dependency_edges"],
                strict=True,
            )
        }
        by_slot = {
            principal["slot_id"]: principal for principal in principals
        }
        for handoff in handoffs:
            edge = expected_edges[handoff["handoff_id"]]
            receiver_slot = slot_contracts[edge["to"]]
            if (
                handoff["sender_principal_id"]
                != by_slot[edge["from"]]["principal_id"]
                or handoff["receiver_principal_id"]
                != by_slot[edge["to"]]["principal_id"]
            ):
                raise RunnerFailure("handoff endpoints differ from the plan edge")
            if (
                handoff["expected_output_schema_hash"]
                != receiver_slot["expected_return_schema_hash"]
            ):
                raise RunnerFailure(
                    "handoff output schema differs from the receiver slot",
                )
        for principal in principals:
            mode = principal["context_mode"]
            incoming = [
                handoff for handoff in handoffs
                if handoff["receiver_principal_id"]
                == principal["principal_id"]
            ]
            if mode in {"single", "fresh"}:
                if principal["inherited_context_hash"] is not None:
                    raise RunnerFailure(
                        f"{mode} principal cannot inherit hidden context",
                    )
            elif mode == "forked":
                components = result["context"].get("components")
                if not isinstance(components, list):
                    raise RunnerFailure(
                        "forked principal lacks captured context components",
                    )
                component_hashes = {
                    component.get("content_sha256")
                    for component in components
                    if (
                        isinstance(component, dict)
                        and isinstance(component.get("artifact"), dict)
                        and component.get("content_sha256")
                        == component["artifact"].get("sha256")
                    )
                }
                if (
                    principal["parent_principal_id"] is None
                    or principal["inherited_context_hash"]
                    not in component_hashes
                ):
                    raise RunnerFailure("forked principal lacks parent context proof")
            elif (
                len(incoming) != 1
                or principal["inherited_context_hash"]
                != incoming[0]["payload"]["sha256"]
            ):
                raise RunnerFailure(
                    "scoped-handoff principal lacks exact payload proof",
                )
        if (
            coordination["partial_result_policy"] == "fail closed"
            and any(handoff["status"] != "result" for handoff in handoffs)
            and result["terminal_status"] == "completed"
        ):
            raise RunnerFailure(
                "fail-closed coordination silently accepted a partial join",
            )
    actions = result["actions"]
    action_ids = [item["action_id"] for item in actions]
    if (
        len(action_ids) != len(set(action_ids))
        or set(action_ids) != set(entry["action_ids"])
    ):
        raise RunnerFailure("actual actions do not match the plan entry")
    expected_tools = dict(zip(
        compiler._declared_action_ids(
            entry["execute_case_payload"]["case"],
        ),
        entry["execute_case_payload"]["execution_context"]["expected_tools"],
        strict=True,
    ))
    for action in actions:
        if action["tool_identity"]["name"] != expected_tools[
            action["action_id"]
        ]:
            raise RunnerFailure("action tool identity differs from the plan")


def _routing_from_events(
    catalog: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[str, list[str]]:
    routing = {
        "catalog": [item["id"] for item in catalog],
        **{
            key: []
            for key in (
                "declared", "discovered", "loaded", "model_visible",
                "selected", "invoked", "applied", "order", "composition",
            )
        },
    }
    for event in events:
        observed = event["payload"].get("routing")
        if not isinstance(observed, dict):
            continue
        for key in routing:
            if key == "catalog" or key not in observed:
                continue
            values = observed[key]
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                raise RunnerFailure(f"host routing {key} must be an array of IDs")
            routing[key].extend(values)
    return routing


def _validate_routing_contract(
    entry: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    case = entry["execute_case_payload"]["case"]
    contract = case.get("routing_contract")
    if contract is None:
        return
    profile = entry["execute_case_payload"]["treatment"]["profile"]
    expected = {
        item["turn_id"]: {
            key: item[key]
            for key in (
                "declared", "discovered", "loaded", "model_visible",
                "selected", "invoked", "applied", "order", "composition",
            )
        }
        for item in contract["expectations"]
        if item["treatment_profile"] == profile
    }
    observed: dict[str, dict[str, Any]] = {}
    for event in events:
        routing = event["payload"].get("routing")
        if routing is None:
            continue
        turn_id = event["turn_id"]
        if turn_id in observed:
            raise RunnerFailure(
                "host emitted duplicate routing evidence for a turn",
            )
        observed[turn_id] = routing
    if observed != expected:
        raise RunnerFailure(
            "host routing differs from the declared treatment/turn contract",
        )


def _validate_state_contract(
    entry: dict[str, Any],
    events: list[dict[str, Any]],
    result: dict[str, Any],
    checkpoints: list[dict[str, Any]],
) -> None:
    case = entry["execute_case_payload"]["case"]
    turns = case["turns"]
    expected_turn_ids = [turn["turn_id"] for turn in turns]
    if [event["turn_id"] for event in events] != expected_turn_ids:
        raise RunnerFailure("host turn evidence differs from the scenario order")
    if (
        len(checkpoints) != len(turns)
        or [item["turn_id"] for item in checkpoints] != expected_turn_ids
        or [item["seq"] for item in checkpoints] != list(range(len(turns)))
    ):
        raise RunnerFailure("host checkpoints do not close the scenario turns")
    for turn, event in zip(turns, events, strict=True):
        if event["payload"].get("obligations") != {
            "open": turn["open_obligations"],
            "due": turn["due_obligations"],
        }:
            raise RunnerFailure(
                "host obligation evidence differs from the scenario turn",
            )
    model = case["state_model"]
    stateful = model["scope"] != "none"
    if any(
        (checkpoint["state_artifact"] is not None) != stateful
        for checkpoint in checkpoints
    ):
        raise RunnerFailure(
            "host state checkpoints differ from the declared state scope",
        )
    transitions = {
        requirement["transition_id"]
        for requirement in case["requirements"]
        if requirement["transition_id"] is not None
    }
    if stateful and not transitions <= set(model["allowed_transition_ids"]):
        raise RunnerFailure(
            "required transitions exceed the declared state model",
        )
    expected_cleanup = (
        model["expected_cleanup_state"]
        if stateful
        else "not_applicable"
    )
    if (
        result["cleanup"].get("status") != "clean"
        or result["cleanup"].get("state") != expected_cleanup
    ):
        raise RunnerFailure(
            "host cleanup evidence differs from the declared state model",
        )


def _host_artifact_paths(
    result: dict[str, Any],
    attempt_dir: Path,
) -> list[Path]:
    verified = verify_artifact_records(
        result["artifacts"], attempt_dir, label="host result",
    )

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if set(value) == {"path", "sha256", "encoding"}:
                path = value["path"]
                if path not in verified or {
                    key: verified[path][key]
                    for key in ("path", "sha256", "encoding")
                } != value:
                    raise RunnerFailure(
                        f"host artifact reference is outside its catalog: {path}",
                    )
                return
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit({key: value for key, value in result.items() if key != "artifacts"})
    return [item["resolved"] for item in verified.values()]


def _validate_action_lifecycle(
    result: dict[str, Any],
    attempt_dir: Path,
) -> None:
    stage_order = [
        "declared",
        "discovered",
        "loaded",
        "model_visible",
        "selected",
        "invoked",
        "authorization_requested",
        "authorization_resolved",
        "executed",
        "raw_backend_result",
        "model_delivered_result",
        "rendered_or_displayed",
        "effect_observed",
        "effect_confirmed",
    ]
    verified = (
        verify_artifact_records(
            result["artifacts"], attempt_dir, label="action lifecycle",
        )
        if result["actions"]
        else {}
    )
    for action in result["actions"]:
        decision = action["resolved_decision"]
        stages = action["stages"]
        observed = [stage["stage"] for stage in stages]
        expected = stage_order[:8] if decision == "deny" else stage_order
        if observed != expected:
            raise RunnerFailure("action lifecycle stages are incomplete")
        stage_by_name = {stage["stage"]: stage for stage in stages}
        expected_artifacts = {
            "invoked": action["proposed_input"],
            "authorization_requested": action["proposed_input"],
            "executed": action["executed_input"],
            "raw_backend_result": action["backend_result"],
            "model_delivered_result": action["model_delivered_result"],
            "effect_observed": action["confirmed_effect"],
            "effect_confirmed": action["confirmed_effect"],
        }
        if any(
            stage_by_name[name]["artifact"] != artifact
            for name, artifact in expected_artifacts.items()
            if name in stage_by_name
        ):
            raise RunnerFailure("action stage artifact binding is inconsistent")
        rendered = stage_by_name.get("rendered_or_displayed")
        if (
            rendered is not None
            and rendered["artifact"] not in (
                action["delivery_transform"], action["visible_result"],
            )
        ):
            raise RunnerFailure("rendered action stage lacks visible evidence")
        decisions = action["authorization_decisions"]
        if not decisions:
            raise RunnerFailure("action lacks an authorization source decision")
        decision_artifacts = [item["artifact"] for item in decisions]
        if stage_by_name["authorization_resolved"]["artifact"] not in (
            decision_artifacts
        ):
            raise RunnerFailure(
                "authorization stage does not bind a source decision",
            )
        decision_documents: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for source in decisions:
            _, source_path = resolve_contained_path(
                attempt_dir,
                source["artifact"]["path"],
                "authorization artifact",
                kind="file",
            )
            document = load_json(source_path)
            if document.get("decision") != source["decision"]:
                raise RunnerFailure(
                    "authorization artifact differs from its source decision",
                )
            decision_documents.append((source, document))
        if decision == "allow":
            if action["executed_input"] != action["proposed_input"]:
                raise RunnerFailure("allowed action changed the proposed input")
        elif decision == "allow_with_changes":
            executed = action["executed_input"]
            if executed is None:
                raise RunnerFailure("allow-with-changes lacks executed input")
            approvals = [
                (source, document)
                for source, document in decision_documents
                if source["decision"] == "allow_with_changes"
            ]
            if not approvals:
                raise RunnerFailure("allow-with-changes lacks its source decision")
            for _, document in approvals:
                if document.get("approved_input_sha256") != executed["sha256"]:
                    raise RunnerFailure(
                        "executed input differs from the approved rewrite",
                    )
        if action["rollback_cleanup_locator"] is None:
            raise RunnerFailure("action lacks rollback or cleanup evidence")
        try:
            validate_locator(action["rollback_cleanup_locator"], verified)
        except ValueError as exc:
            raise RunnerFailure(f"invalid action cleanup locator: {exc}") from None
        if decision == "deny":
            if any(
                action[field] is not None
                for field in (
                    "executed_input",
                    "backend_request",
                    "backend_result",
                    "transport_error",
                    "model_delivered_result",
                    "delivery_transform",
                    "visible_result",
                    "confirmed_effect",
                )
            ):
                raise RunnerFailure("denied action contains execution evidence")
        if decision != "deny":
            if action["backend_request"] != action["executed_input"]:
                raise RunnerFailure(
                    "backend request differs from the authorized input",
                )
            if action["transport_error"] is not None:
                raise RunnerFailure(
                    "successful action contains a transport error",
                )
            if any(
                action[field] is None
                for field in (
                    "backend_result",
                    "model_delivered_result",
                    "delivery_transform",
                    "visible_result",
                    "confirmed_effect",
                )
            ):
                raise RunnerFailure("successful action lacks effect-stage evidence")


def _capture_observations(
    entry: dict[str, Any],
    attempt_dir: Path,
    event_count: int,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for contract in entry["execute_case_payload"]["observation_contracts"]:
        _, path = resolve_contained_path(
            attempt_dir,
            contract["artifact"],
            f"observation {contract['observation_id']}",
            kind="file",
        )
        record = artifact_record(
            path, attempt_dir, encoding=contract["encoding"],
        )
        if (
            contract["expected_hash"] is not None
            and record["sha256"] != contract["expected_hash"]
        ):
            raise ApparatusFailure(
                f"observation {contract['observation_id']} hash mismatch",
            )
        verified = verify_artifact_records(
            [record], attempt_dir, label="observation",
        )
        validate_locator(contract["locator"], verified)
        if contract["predicate"] is not None:
            text = path.read_text(encoding="utf-8")
            if contract["predicate"] not in text:
                raise ApparatusFailure(
                    f"observation {contract['observation_id']} predicate failed",
                )
        if contract["valid_from_seq"] is not None:
            temporal = (
                contract["valid_from_seq"] >= 0
                and contract["valid_until_seq"] < event_count
            )
        else:
            observed = _parse_utc(_utc_now())
            temporal = (
                _parse_utc(contract["valid_from_utc"])
                <= observed
                <= _parse_utc(contract["valid_until_utc"])
            )
        if not temporal:
            raise ApparatusFailure(
                f"observation {contract['observation_id']} is stale",
            )
        observations.append({
            "observation_id": contract["observation_id"],
            "artifact": record,
            "locator": copy.deepcopy(contract["locator"]),
            "schema_hash": contract["schema_hash"],
            "integrity": "pass",
            "temporal_validity": "pass",
            "reason": "bound bytes, locator, and temporal window verified",
        })
    if {item["observation_id"] for item in observations} != set(
        entry["observation_ids"],
    ):
        raise RunnerFailure("captured observations do not match the plan entry")
    return observations


def _capture_faults(
    entry: dict[str, Any],
    events: list[dict[str, Any]],
    attempt_dir: Path,
    terminal_status: str,
) -> dict[str, list[dict[str, Any]]]:
    expected = {
        fault["fault_id"]
        for fault in entry["execute_case_payload"]["fault_script"]
    }
    captured = {
        phase: [
            copy.deepcopy(item)
            for event in events
            for item in event["payload"].get("faults", {}).get(phase, [])
        ]
        for phase in ("injected", "observed", "recovered")
    }
    for phase, records in captured.items():
        ids = [record["fault_id"] for record in records]
        if len(ids) != len(set(ids)) or not set(ids) <= expected:
            raise RunnerFailure(f"fault {phase} identities are invalid")
        for record in records:
            artifact_path = record["locator"]["artifact"]
            _, resolved = resolve_contained_path(
                attempt_dir,
                artifact_path,
                f"fault {record['fault_id']} artifact",
                kind="file",
            )
            artifact = artifact_record(
                resolved, attempt_dir, encoding="utf-8",
            )
            validate_locator(
                record["locator"],
                verify_artifact_records(
                    [artifact], attempt_dir, label=f"fault {phase}",
                ),
            )
    if terminal_status == "completed" and any(
        {record["fault_id"] for record in captured[phase]} != expected
        for phase in captured
    ):
        raise ApparatusFailure("completed host result lacks fault lifecycle evidence")
    return captured


def _raise_for_host_infrastructure_failure(
    result: dict[str, Any],
    label: str,
) -> None:
    failure_class = result.get("failure_class")
    provider_error_code = result.get("provider_error_code")
    if failure_class is None:
        if provider_error_code is not None:
            raise RunnerFailure(
                f"{label} has an unclassified provider error",
            )
        return
    if failure_class == "model_task_timeout":
        if (
            result["terminal_status"] != "timeout"
            or result["timeout"] is not True
            or provider_error_code is not None
        ):
            raise RunnerFailure(f"{label} timeout classification is invalid")
    elif (
        result["terminal_status"] != "failed"
        or not isinstance(provider_error_code, str)
    ):
        raise RunnerFailure(f"{label} provider classification is invalid")
    raise ApparatusFailure(f"{label} stopped with {failure_class}")


def _merged_usage(
    entry: dict[str, Any],
    result: dict[str, Any],
    model_results: list[dict[str, Any]],
    host: dict[str, Any],
) -> dict[str, Any]:
    sources = [result["usage"], *[
        model_result["usage"] for model_result in model_results
    ]]
    pricing_identity = host["identity"]["execution"]["pricing_id"]
    if any(
        source["pricing_identity"] != pricing_identity
        for source in sources
    ):
        raise RunnerFailure("usage pricing identity differs from the host")
    records = [
        copy.deepcopy(record)
        for source in sources
        for record in source["records"]
    ]
    allowed_principals = {
        principal["principal_id"] for principal in result["principals"]
    } | {
        f"grader-{model_spec['grader_id']}"
        for model_spec in entry["model_grade_specs"]
    }
    allowed_turns = {
        turn["turn_id"] for turn in entry["execute_case_payload"]["turns"]
    }
    identities: set[tuple[Any, ...]] = set()
    for record in records:
        if record["principal_id"] not in allowed_principals:
            raise RunnerFailure("usage record principal is not bound to the entry")
        if record["turn_id"] is not None and record["turn_id"] not in allowed_turns:
            raise RunnerFailure("usage record turn is not bound to the entry")
        identity = (
            record["principal_id"],
            record["turn_id"],
            record["phase"],
            record["call_id"],
        )
        if identity in identities:
            raise RunnerFailure("usage record call identity is duplicated")
        identities.add(identity)
    safety_fields = {
        "capture_status",
        "host_safety_review_count",
        "host_safety_review_latency_ms",
    }
    capture_status = "captured"
    safety_count = 0
    safety_latency_ms = 0.0
    for source in sources:
        observation = source.get("host_safety_review")
        if observation is None:
            capture_status = "missing"
            continue
        if not isinstance(observation, dict) or set(observation) != safety_fields:
            raise RunnerFailure("host safety-review observation is invalid")
        count = observation["host_safety_review_count"]
        latency = observation["host_safety_review_latency_ms"]
        if (
            observation["capture_status"] not in {"captured", "missing"}
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or not isinstance(latency, (int, float))
            or isinstance(latency, bool)
            or latency < 0
        ):
            raise RunnerFailure("host safety-review observation is invalid")
        if observation["capture_status"] != "captured":
            capture_status = "missing"
        safety_count += count
        safety_latency_ms += float(latency)
    return {
        "pricing_identity": pricing_identity,
        "host_safety_review": {
            "capture_status": capture_status,
            "host_safety_review_count": safety_count,
            "host_safety_review_latency_ms": safety_latency_ms,
        },
        "records": records,
    }


def _validate_grader_output(
    value: Any,
    expected_check_ids: list[str],
) -> None:
    fields = {
        "overall_pass", "score", "checks", "missing_evidence",
        "grader_failure", "grader_failure_reason",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise ApparatusFailure("grader output does not match transport v1")
    if (
        not isinstance(value["overall_pass"], bool)
        or not isinstance(value["score"], int)
        or isinstance(value["score"], bool)
        or not 0 <= value["score"] <= 100
        or not isinstance(value["checks"], list)
        or not isinstance(value["missing_evidence"], list)
        or not isinstance(value["grader_failure"], bool)
    ):
        raise ApparatusFailure("grader output has invalid transport values")
    observed = [check.get("check_id") for check in value["checks"]]
    if value["grader_failure"]:
        if (
            value["overall_pass"]
            or value["score"] != 0
            or value["checks"]
            or not value["missing_evidence"]
            or not isinstance(value["grader_failure_reason"], str)
        ):
            raise ApparatusFailure("grader failure output is inconsistent")
    elif (
        value["grader_failure_reason"] is not None
        or sorted(observed) != sorted(expected_check_ids)
        or len(observed) != len(set(observed))
    ):
        raise ApparatusFailure("grader output does not close the selected checks")


def _run_deterministic_graders(
    entry: dict[str, Any],
    spec: dict[str, Any],
    spec_path: Path,
    attempt_dir: Path,
    result_path: Path,
    custody_fd: int,
) -> tuple[list[dict[str, Any]], list[Path]]:
    declarations = {
        grader["grader_id"]: grader
        for grader in spec["graders"]
        if grader["type"] == "deterministic"
    }
    outputs: list[dict[str, Any]] = []
    artifacts: list[Path] = []
    for grader_id in entry["grader_ids"]:
        if grader_id not in declarations:
            continue
        grader = declarations[grader_id]
        verifier = grader["verifier"]
        _, verifier_path = resolve_contained_path(
            spec_path.parent,
            verifier["path"],
            f"grader {grader_id} verifier",
            kind="file",
        )
        if file_sha256(verifier_path) != verifier["sha256"]:
            raise RunnerFailure(f"grader {grader_id} verifier sha256 mismatch")

        grader_dir = attempt_dir / "graders" / grader_id
        grader_dir.mkdir(parents=True)
        cwd_value = verifier["cwd"]
        if cwd_value == ".":
            grader_cwd = grader_dir
        else:
            grader_cwd = grader_dir / normalize_relative_path(
                cwd_value, f"grader {grader_id} cwd",
            )
            grader_cwd.mkdir(parents=True)
        input_paths: list[Path] = []
        for input_name in verifier["input_allowlist"]:
            normalized = normalize_relative_path(
                input_name, f"grader {grader_id} input",
            )
            destination = grader_cwd / normalized
            destination.parent.mkdir(parents=True, exist_ok=True)
            if normalized != "result.json":
                raise RunnerFailure(
                    f"grader {grader_id} declares an unavailable input {normalized}",
                )
            shutil.copy2(result_path, destination)
            input_paths.append(destination)

        executable_name = verifier["argv"][0]
        executable = (
            Path(executable_name)
            if Path(executable_name).is_absolute()
            else Path(shutil.which(executable_name) or "")
        )
        if not executable.is_file():
            raise RunnerFailure(f"grader {grader_id} executable is unavailable")
        argv = [str(executable.resolve())]
        for argument in verifier["argv"][1:]:
            candidate = spec_path.parent / argument
            argv.append(str(candidate.resolve()) if candidate.is_file() else argument)
        environment = {
            name: os.environ[name]
            for name in verifier["env_allowlist"]
            if name in os.environ
        }
        exit_code, stdout, stderr = _run_process(
            argv,
            cwd=grader_cwd,
            environment=environment,
            input_bytes=b"",
            timeout_seconds=verifier["timeout_seconds"],
            custody_fd=custody_fd,
        )
        stdout_path = grader_dir / "stdout.json"
        stderr_path = grader_dir / "stderr.txt"
        atomic_write_bytes(stdout_path, stdout)
        atomic_write_bytes(stderr_path, stderr)
        artifacts.extend([*input_paths, stdout_path, stderr_path])
        try:
            output = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApparatusFailure(
                f"grader {grader_id} output is not one UTF-8 JSON value",
            ) from exc
        expected_checks = [
            check["check_id"]
            for check in grader["checks"]
            if check["check_id"] in entry["check_ids"]
        ]
        _validate_grader_output(output, expected_checks)
        invocation = {
            "grader_id": grader_id,
            "declared_argv": verifier["argv"],
            "resolved_argv": argv,
            "resolved_executable_sha256": file_sha256(executable.resolve()),
            "cwd": cwd_value,
            "env": [
                {
                    "name": name,
                    "value_sha256": "sha256:"
                    + sha256(value.encode("utf-8")).hexdigest(),
                }
                for name, value in sorted(environment.items())
            ],
            "timeout_seconds": verifier["timeout_seconds"],
            "input_allowlist": verifier["input_allowlist"],
            "inputs": [
                artifact_record(path, attempt_dir, encoding="utf-8")
                for path in input_paths
            ],
            "exit_code": exit_code,
            "pass_exit_codes": verifier["pass_exit_codes"],
            "credential_policy": spec["execution"]["credential_policy"],
            "shell": False,
            "start_new_session": True,
        }
        invocation_path = grader_dir / "invocation.json"
        atomic_write_json(invocation_path, invocation)
        artifacts.append(invocation_path)
        outputs.append({
            "kind": "deterministic",
            "grader_id": grader_id,
            "invocation": artifact_record(
                invocation_path, attempt_dir, encoding="utf-8",
            ),
            "output": artifact_record(
                stdout_path, attempt_dir, encoding="utf-8",
            ),
        })
    return outputs, artifacts


def _batch_member(
    *,
    entry_id: str,
    plan_path: Path,
    plan: dict[str, Any],
    prior_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    entries = {item["entry_id"]: item for item in plan["entries"]}
    entry = entries.get(entry_id)
    if entry is None:
        raise RunnerFailure("model grader batch member is outside the plan")
    _, artifacts_root = resolve_contained_path(
        plan_path.parent,
        plan["artifacts"]["root"],
        "artifacts root",
    )
    valid = []
    for row in prior_rows:
        if row["entry_id"] != entry_id:
            continue
        _, receipt_path = resolve_contained_path(
            artifacts_root,
            row["receipt"]["path"],
            "batch member receipt",
            kind="file",
        )
        receipt = load_json(receipt_path)
        if receipt["run"]["valid"] is True:
            valid.append((receipt, receipt_path.parent))
    if len(valid) != 1:
        raise RunnerFailure("model grader batch member is not uniquely valid")
    receipt, attempt_dir = valid[0]
    try:
        result = model_transport.execution_result(receipt)
    except ValueError as exc:
        raise RunnerFailure(str(exc)) from None
    return entry, result, attempt_dir


def _run_model_graders(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    spec: dict[str, Any],
    entry: dict[str, Any],
    host: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    spec_path: Path,
    attempt_dir: Path,
    workspace: Path,
    execution_result: dict[str, Any],
    run_id: str,
    attempt: int,
    credential_policy: str,
    prior_rows: list[dict[str, Any]],
    custody_fd: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[Path],
    list[bytes],
    list[bytes],
]:
    grader_outputs: list[dict[str, Any]] = []
    requests: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    artifacts: list[Path] = []
    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    declarations = {
        grader["grader_id"]: grader
        for grader in spec["graders"]
        if grader["type"] == "model"
    }
    argv, environment = _validate_host_command(host, spec_path.parent)
    for model_spec in entry["model_grade_specs"]:
        if model_spec["batch_owner_entry_id"] != entry["entry_id"]:
            continue
        grader_id = model_spec["grader_id"]
        if grader_id not in declarations:
            raise RunnerFailure("model grader declaration is absent")
        grader_dir = attempt_dir / "model-graders" / model_spec["batch_id"]
        grader_dir.mkdir(parents=True)
        items = []
        for member_id in model_spec["batch_entry_ids"]:
            if member_id == entry["entry_id"]:
                member_entry = entry
                member_result = execution_result
                member_root = attempt_dir
            else:
                member_entry, member_result, member_root = _batch_member(
                    entry_id=member_id,
                    plan_path=plan_path,
                    plan=plan,
                    prior_rows=prior_rows,
                )
            blinded = model_transport.blinded_execution(
                member_entry,
                member_result,
            )
            if sorted(blinded) != sorted(model_spec["blinded_projection"]):
                raise RunnerFailure(
                    "model grader blinded projection is incomplete",
                )

            def read_evidence(
                record: dict[str, Any],
                root: Path = member_root,
            ) -> str:
                _, path = resolve_contained_path(
                    root,
                    record["path"],
                    "model grader evidence",
                    kind="file",
                )
                if artifact_record(path, root, encoding="utf-8") != record:
                    raise RunnerFailure("model grader evidence binding differs")
                try:
                    return path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raise RunnerFailure(
                        "model grader evidence is not UTF-8",
                    ) from None

            items.append(model_transport.execution_item(
                blinded,
                grader_id=grader_id,
                grader_checks=declarations[grader_id]["checks"],
                entry_id=member_id,
                read_artifact=read_evidence,
            ))
        batch = model_transport.execution_batch(
            items,
            batch_id=model_spec["batch_id"],
        )
        _, prompt_path = resolve_contained_path(
            spec_path.parent,
            model_spec["prompt"]["path"],
            "model grader prompt",
            kind="file",
        )
        prompt_bytes = prompt_path.read_bytes()
        if file_sha256(prompt_path) != model_spec["prompt"]["sha256"]:
            raise RunnerFailure("model grader prompt binding differs")
        blinded_path = grader_dir / "blinded-input.json"
        atomic_write_json(blinded_path, batch)
        request = _host_request(
            plan,
            entry,
            run_id,
            attempt,
            request_kind="model_grade",
            payload=model_transport.request_payload(
                grader_id=grader_id,
                batch=batch,
                batch_hash=model_spec["batch_hash"],
                schedule_hash=model_spec["schedule_hash"],
                prompt_bytes=prompt_bytes,
                prompt_hash=model_spec["prompt"]["sha256"],
                schema_hash=model_spec["schema"]["sha256"],
            ),
        )
        diagnostics = validate_host_protocol_record(
            "host_request", request, registry,
        )
        if diagnostics:
            raise RunnerFailure(_first_diagnostic(diagnostics))
        request_path = grader_dir / "host-request.json"
        atomic_write_json(request_path, request)
        invocation_path = grader_dir / "host-invocation.json"
        atomic_write_json(
            invocation_path,
            _invocation_record(
                declared_argv=host["command"]["argv"],
                resolved_argv=argv,
                environment=environment,
                executable=Path(argv[0]),
                cwd=workspace,
                attempt_dir=attempt_dir,
                timeout_seconds=entry["timeout_seconds"],
                credential_policy=credential_policy,
            ),
        )
        exit_code, stdout, stderr = _run_process(
            argv,
            cwd=workspace,
            environment=environment,
            input_bytes=canonical_json_bytes(request) + b"\n",
            timeout_seconds=entry["timeout_seconds"],
            custody_fd=custody_fd,
        )
        stdout_path = grader_dir / "host-stdout.jsonl"
        stderr_path = grader_dir / "host-stderr.txt"
        atomic_write_bytes(stdout_path, stdout)
        atomic_write_bytes(stderr_path, stderr)
        if exit_code != 0:
            raise ApparatusFailure(
                f"model grader {grader_id} host exited {exit_code}",
            )
        batch_events, batch_result, _ = _parse_host_protocol(
            stdout, request=request, registry=registry,
        )
        _raise_for_host_infrastructure_failure(
            batch_result,
            f"model grader {grader_id}",
        )
        _host_artifact_paths(batch_result, attempt_dir)
        requests.append(request)
        events.extend(batch_events)
        results.append(batch_result)
        artifacts.extend([
            blinded_path,
            request_path,
            invocation_path,
            stdout_path,
            stderr_path,
            *[
                (attempt_dir / item["path"]).resolve()
                for item in batch_result["artifacts"]
            ],
        ])
        stdout_chunks.append(stdout)
        stderr_chunks.append(stderr)
        grader_outputs.append({
            "kind": "model",
            "grader_id": grader_id,
            "schedule_hash": model_spec["schedule_hash"],
            "blinded_input": artifact_record(
                blinded_path, attempt_dir, encoding="utf-8",
            ),
            "raw_batch": artifact_record(
                stdout_path, attempt_dir, encoding="utf-8",
            ),
        })
    return (
        grader_outputs,
        requests,
        events,
        results,
        artifacts,
        stdout_chunks,
        stderr_chunks,
    )


def _artifact_encoding(path: Path) -> str:
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "utf-8"


def _receipt_artifacts(
    paths: list[Path],
    attempt_dir: Path,
) -> list[dict[str, str]]:
    unique = {path.resolve(): path for path in paths}
    return sorted(
        (
            artifact_record(
                path,
                attempt_dir,
                encoding=_artifact_encoding(path),
            )
            for path in unique.values()
        ),
        key=lambda item: item["path"],
    )


def _build_receipt(
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    spec: dict[str, Any],
    host: dict[str, Any],
    marker: dict[str, Any],
    reset_request: dict[str, Any],
    reset_events: list[dict[str, Any]],
    reset_result: dict[str, Any],
    request: dict[str, Any],
    events: list[dict[str, Any]],
    result: dict[str, Any],
    model_requests: list[dict[str, Any]],
    model_events: list[dict[str, Any]],
    model_results: list[dict[str, Any]],
    checkpoints: list[dict[str, Any]],
    routing: dict[str, list[str]],
    observations: list[dict[str, Any]],
    faults: dict[str, list[dict[str, Any]]],
    grader_outputs: list[dict[str, Any]],
    usage: dict[str, Any],
    artifacts: list[dict[str, str]],
    raw_stdout: dict[str, str],
    raw_stderr: dict[str, str],
    started_at: str,
    ended_at: str,
) -> dict[str, Any]:
    if result["terminal_status"] == "protocol_error" or result[
        "protocol_error"
    ] is not None:
        raise RunnerFailure("host reported a protocol error")
    receipt = {
        "schema_version": 4,
        "receipt_hash": "sha256:" + "0" * 64,
        "attempt_start": marker,
        "run": {
            "plan_hash": plan["plan_hash"],
            "plan_id": plan["plan_id"],
            "entry_ordinal": entry["entry_ordinal"],
            "entry_id": entry["entry_id"],
            "run_id": marker["run_id"],
            "case_id": entry["case_id"],
            "treatment_id": entry["treatment_id"],
            "repeat": entry["repeat"],
            "attempt": marker["attempt"],
            "completion_origin": "normal",
            "clock_source": host["identity"]["execution"]["utc_clock_id"],
            "started_at": started_at,
            "ended_at": ended_at,
            "valid": True,
            "error": result["treatment_error"],
            "terminal": result["terminal_status"],
        },
        "provenance": {
            "spec_hash": plan["spec_hash"],
            "scenario_corpus_hash": plan["scenario_corpus_hash"],
            "scenario_hash": entry["scenario_hash"],
            "plan_hash": plan["plan_hash"],
            "host_manifest_hash": plan["host_manifest_hash"],
            "package_hash": plan["package_hashes"][
                spec["subject"]["skill_id"]
            ],
            "catalog_hash": entry["catalog_hash"],
            "treatment_hash": entry["treatment_hash"],
            "fixture_hash": entry["fixture_hash"],
            "grader_set_hash": plan["grader_set_hash"],
            "calibration_hash": plan["calibration_hash"],
            "suite_quality_hash": plan["suite_quality_hash"],
        },
        "artifacts": artifacts,
        "host_protocol": {
            "requests": [reset_request, request, *model_requests],
            "events": [*reset_events, *events, *model_events],
            "results": [reset_result, result, *model_results],
            "checkpoints": checkpoints,
            "errors": [],
            "raw_stdout": raw_stdout,
            "raw_stderr": raw_stderr,
        },
        "routing": routing,
        "principals": copy.deepcopy(result["principals"]),
        "handoffs": copy.deepcopy(result["handoffs"]),
        "actions": copy.deepcopy(result["actions"]),
        "observations": observations,
        "state": {
            "before": (
                checkpoints[0]["state_artifact"] if checkpoints else None
            ),
            "after": (
                checkpoints[-1]["state_artifact"] if checkpoints else None
            ),
            "checkpoints": checkpoints,
            "transitions": sorted({
                requirement["transition_id"]
                for requirement in entry["execute_case_payload"]["case"][
                    "requirements"
                ]
                if requirement["transition_id"] is not None
            }),
            "obligations": sorted({
                obligation
                for turn in entry["execute_case_payload"]["turns"]
                for field in ("open_obligations", "due_obligations")
                for obligation in turn[field]
            }),
            "terminal": result["terminal_status"],
            "cleanup": str(result["cleanup"].get("status", "unknown")),
        },
        "faults": faults,
        "usage": usage,
        "context_usage": copy.deepcopy(result["context"]),
        "grader_outputs": grader_outputs,
        "cleanup": {
            "process": "clean",
            "workspace": "retained",
            "service": "not_applicable",
            "state": "not_applicable",
            "residue": [],
            "errors": [],
        },
    }
    receipt["receipt_hash"] = canonical_self_hash(receipt, "receipt_hash")
    return receipt


def _validate_receipt(
    receipt: dict[str, Any],
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    marker: dict[str, Any],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> None:
    diagnostics = validate_v5_schema(
        receipt, "receipt-v4.schema.json", registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    if not verify_self_hash(receipt, "receipt_hash"):
        raise RunnerFailure("receipt_hash does not match the canonical receipt")
    if receipt["attempt_start"] != marker:
        raise RunnerFailure("receipt attempt marker differs from attempt-start.json")
    run = receipt["run"]
    expected = {
        "plan_hash": plan["plan_hash"],
        "plan_id": plan["plan_id"],
        "entry_ordinal": entry["entry_ordinal"],
        "entry_id": entry["entry_id"],
        "case_id": entry["case_id"],
        "treatment_id": entry["treatment_id"],
        "repeat": entry["repeat"],
        "attempt": marker["attempt"],
        "run_id": marker["run_id"],
    }
    for field, value in expected.items():
        if run[field] != value:
            raise RunnerFailure(f"receipt run {field} differs from plan identity")
    expected_provenance = {
        "spec_hash": plan["spec_hash"],
        "scenario_corpus_hash": plan["scenario_corpus_hash"],
        "scenario_hash": entry["scenario_hash"],
        "plan_hash": plan["plan_hash"],
        "host_manifest_hash": plan["host_manifest_hash"],
        "package_hash": plan["package_hashes"][
            spec["subject"]["skill_id"]
        ],
        "catalog_hash": entry["catalog_hash"],
        "treatment_hash": entry["treatment_hash"],
        "fixture_hash": entry["fixture_hash"],
        "grader_set_hash": plan["grader_set_hash"],
        "calibration_hash": plan["calibration_hash"],
        "suite_quality_hash": plan["suite_quality_hash"],
    }
    if receipt["provenance"] != expected_provenance:
        raise RunnerFailure("receipt provenance differs from the plan entry")
    if receipt["routing"]["catalog"] != [
        item["id"] for item in entry["execute_case_payload"]["catalog"]
    ]:
        raise RunnerFailure("receipt routing catalog differs from the plan entry")
    if {
        principal["slot_id"] for principal in receipt["principals"]
    } not in (set(), set(entry["principal_slot_ids"])):
        raise RunnerFailure("receipt principals differ from the plan entry")
    if {item["handoff_id"] for item in receipt["handoffs"]} not in (
        set(), set(entry["handoff_ids"]),
    ):
        raise RunnerFailure("receipt handoffs differ from the plan entry")
    if {item["action_id"] for item in receipt["actions"]} not in (
        set(), set(entry["action_ids"]),
    ):
        raise RunnerFailure("receipt actions differ from the plan entry")
    if {item["observation_id"] for item in receipt["observations"]} not in (
        set(), set(entry["observation_ids"]),
    ):
        raise RunnerFailure("receipt observations differ from the plan entry")
    context = receipt["context_usage"]
    if (
        context["controlled_core_bytes"]
        != context["controlled_bytes"] - context["unique_reference_bytes"]
        or context["bytes"] != sum(
            component["bytes"] for component in context["components"]
        )
    ):
        raise RunnerFailure("receipt context byte conservation failed")


def _validate_marker(
    marker: dict[str, Any],
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt: int,
) -> None:
    run_id, ownership_token = _attempt_identity(plan, entry, attempt)
    expected = _build_marker(
        plan, entry, attempt, run_id, ownership_token,
    )
    if marker != expected or not verify_self_hash(marker, "marker_hash"):
        raise RunnerFailure("attempt marker identity or self-hash is invalid")


def _row_from_receipt(
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt_rel: str,
    receipt_path: Path,
    receipt: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    row = {
        "schema_version": 2,
        "plan_hash": plan["plan_hash"],
        "plan_id": plan["plan_id"],
        "entry_ordinal": entry["entry_ordinal"],
        "entry_id": entry["entry_id"],
        "run_id": receipt["run"]["run_id"],
        "case_id": entry["case_id"],
        "treatment_id": entry["treatment_id"],
        "repeat": entry["repeat"],
        "attempt": receipt["run"]["attempt"],
        "artifact_dir": attempt_rel,
        "receipt": {
            "path": f"{attempt_rel}/receipt.json",
            "sha256": file_sha256(receipt_path),
        },
    }
    diagnostics = validate_v5_schema(
        row, "run-index-row-v2.schema.json", registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    return row


def _load_index(
    index_path: Path,
    *,
    plan: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not index_path.exists():
        return []
    rows = [row for _, row in load_jsonl_objects(index_path)]
    identities: set[tuple[str, int]] = set()
    for row in rows:
        diagnostics = validate_v5_schema(
            row, "run-index-row-v2.schema.json", registry,
        )
        if diagnostics:
            raise RunnerFailure(_first_diagnostic(diagnostics))
        if (
            row["plan_hash"] != plan["plan_hash"]
            or row["plan_id"] != plan["plan_id"]
        ):
            raise RunnerFailure("index row belongs to a different plan")
        identity = (row["entry_id"], row["attempt"])
        if identity in identities:
            raise RunnerFailure("index contains a duplicate execute attempt")
        identities.add(identity)
    if rows != sorted(
        rows, key=lambda row: (row["entry_ordinal"], row["attempt"]),
    ):
        raise RunnerFailure("index rows are not in canonical attempt order")
    return rows


def _attempt_directories(
    plan_path: Path,
    plan: dict[str, Any],
    entry: dict[str, Any],
) -> list[tuple[int, str, Path]]:
    _, _, first = _attempt_paths(plan_path, plan, entry, 1)
    entry_dir = first.parent
    if not entry_dir.exists():
        return []
    if entry_dir.is_symlink() or not entry_dir.is_dir():
        raise RunnerFailure("entry artifact path must be a regular directory")
    attempts: list[tuple[int, str, Path]] = []
    for child in sorted(entry_dir.iterdir()):
        if child.is_symlink() or not child.is_dir():
            raise RunnerFailure("entry artifact directory contains an invalid child")
        name = child.name
        if (
            len(name) != len("attempt-0001")
            or not name.startswith("attempt-")
            or not name[8:].isdigit()
        ):
            raise RunnerFailure("entry artifact directory contains an unknown child")
        attempt = int(name[8:])
        if not 1 <= attempt <= 9999:
            raise RunnerFailure("attempt number is outside [1, 9999]")
        attempts.append((
            attempt,
            f"{entry['artifact_relpath']}/{name}",
            child,
        ))
    if [item[0] for item in attempts] != list(range(1, len(attempts) + 1)):
        raise RunnerFailure("attempt directories are not a continuous prefix")
    return attempts


def _existing_receipt(
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    attempt: int,
    attempt_dir: Path,
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    marker_path = attempt_dir / "attempt-start.json"
    if not marker_path.is_file() or marker_path.is_symlink():
        raise RunnerFailure("attempt directory lacks a valid attempt marker")
    marker = load_json(marker_path)
    _validate_marker(
        marker, plan=plan, entry=entry, attempt=attempt,
    )
    receipt_path = attempt_dir / "receipt.json"
    if not receipt_path.exists():
        return None
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise RunnerFailure("receipt path is not a regular file")
    receipt = load_json(receipt_path)
    _validate_receipt(
        receipt,
        plan=plan,
        entry=entry,
        marker=marker,
        spec=spec,
        registry=registry,
    )
    verify_artifact_records(
        receipt["artifacts"], attempt_dir, label="receipt",
    )
    return marker, receipt


def _reserved_request(
    attempt_dir: Path,
    registry: dict[str, dict[str, Any]],
    expected: dict[str, Any],
) -> dict[str, Any] | None:
    path = attempt_dir / "host-request.json"
    if path.is_symlink():
        raise RunnerFailure("reserved host request is not a regular file")
    if not path.exists():
        if any(
            (attempt_dir / name).exists()
            for name in (
                "host-invocation.json", "host-stdout.jsonl",
                "host-stderr.txt",
            )
        ):
            raise RunnerFailure("host execution exists without its request")
        return None
    if not path.is_file():
        raise RunnerFailure("reserved host request is not a regular file")
    request = load_json(path)
    diagnostics = validate_host_protocol_record(
        "host_request", request, registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    if request != expected:
        raise RunnerFailure("reserved host request identity differs")
    return request


def _resume_seal(
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    spec: dict[str, Any],
    host: dict[str, Any],
    attempt: int,
    attempt_dir: Path,
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    marker = load_json(attempt_dir / "attempt-start.json")
    _validate_marker(
        marker, plan=plan, entry=entry, attempt=attempt,
    )
    request = _reserved_request(
        attempt_dir,
        registry,
        _host_request(plan, entry, marker["run_id"], attempt),
    )
    requests = [request] if request is not None else []
    stdout_path = attempt_dir / "host-stdout.jsonl"
    stderr_path = attempt_dir / "host-stderr.txt"
    if not stdout_path.exists():
        atomic_write_bytes(stdout_path, b"")
    if not stderr_path.exists():
        atomic_write_bytes(stderr_path, b"")

    interruption_class = "interrupted"
    if requests and stdout_path.stat().st_size:
        try:
            _, host_result, _ = _parse_host_protocol(
                stdout_path.read_bytes(),
                request=requests[0],
                registry=registry,
            )
        except RunnerFailure:
            pass
        else:
            if host_result.get("failure_class") == "official_transient":
                interruption_class = "official_transient"

    artifact_paths: list[Path] = []
    for path in sorted(attempt_dir.rglob("*")):
        if path.is_symlink():
            raise RunnerFailure("crashed attempt contains a symlink")
        if path.is_file() and path.name not in {
            ATTEMPT_CUSTODY_NAME, "attempt-start.json", "receipt.json",
        }:
            artifact_paths.append(path)
    artifacts = _receipt_artifacts(artifact_paths, attempt_dir)
    raw_stdout = next(
        item for item in artifacts
        if item["path"] == stdout_path.relative_to(attempt_dir).as_posix()
    )
    raw_stderr = next(
        item for item in artifacts
        if item["path"] == stderr_path.relative_to(attempt_dir).as_posix()
    )
    observed = _utc_now()
    receipt = {
        "schema_version": 4,
        "receipt_hash": "sha256:" + "0" * 64,
        "attempt_start": marker,
        "run": {
            "plan_hash": plan["plan_hash"],
            "plan_id": plan["plan_id"],
            "entry_ordinal": entry["entry_ordinal"],
            "entry_id": entry["entry_id"],
            "run_id": marker["run_id"],
            "case_id": entry["case_id"],
            "treatment_id": entry["treatment_id"],
            "repeat": entry["repeat"],
            "attempt": attempt,
            "completion_origin": "resume_seal",
            "clock_source": host["identity"]["execution"]["utc_clock_id"],
            "started_at": observed,
            "ended_at": observed,
            "valid": False,
            "error": interruption_class,
            "terminal": "interrupted",
        },
        "provenance": {
            "spec_hash": plan["spec_hash"],
            "scenario_corpus_hash": plan["scenario_corpus_hash"],
            "scenario_hash": entry["scenario_hash"],
            "plan_hash": plan["plan_hash"],
            "host_manifest_hash": plan["host_manifest_hash"],
            "package_hash": plan["package_hashes"][
                spec["subject"]["skill_id"]
            ],
            "catalog_hash": entry["catalog_hash"],
            "treatment_hash": entry["treatment_hash"],
            "fixture_hash": entry["fixture_hash"],
            "grader_set_hash": plan["grader_set_hash"],
            "calibration_hash": plan["calibration_hash"],
            "suite_quality_hash": plan["suite_quality_hash"],
        },
        "artifacts": artifacts,
        "host_protocol": {
            "requests": requests,
            "events": [],
            "results": [],
            "checkpoints": [],
            "errors": [],
            "raw_stdout": raw_stdout,
            "raw_stderr": raw_stderr,
        },
        "routing": {
            "catalog": [
                item["id"]
                for item in entry["execute_case_payload"]["catalog"]
            ],
            **{
                field: [] for field in (
                    "declared", "discovered", "loaded", "model_visible",
                    "selected", "invoked", "applied", "order", "composition",
                )
            },
        },
        "principals": [],
        "handoffs": [],
        "actions": [],
        "observations": [],
        "state": {
            "before": None,
            "after": None,
            "checkpoints": [],
            "transitions": [],
            "obligations": [],
            "terminal": "interrupted",
            "cleanup": "ownership-verified-no-live-process",
        },
        "faults": {"injected": [], "observed": [], "recovered": []},
        "usage": {
            "pricing_identity": host["identity"]["execution"]["pricing_id"],
            "records": [],
        },
        "context_usage": {
            "status": "missing",
            "bytes": 0,
            "tokens": None,
            "controlled_bytes": 0,
            "unique_reference_bytes": 0,
            "controlled_core_bytes": 0,
            "components": [],
        },
        "grader_outputs": [],
        "cleanup": {
            "process": "clean",
            "workspace": "retained",
            "service": "not_applicable",
            "state": "not_applicable",
            "residue": [],
            "errors": [],
        },
    }
    receipt["receipt_hash"] = canonical_self_hash(receipt, "receipt_hash")
    _validate_receipt(
        receipt,
        plan=plan,
        entry=entry,
        marker=marker,
        spec=spec,
        registry=registry,
    )
    receipt_path = attempt_dir / "receipt.json"
    atomic_write_json(receipt_path, receipt)
    return receipt


def _restore_fixture(
    entry: dict[str, Any],
    spec_path: Path,
    workspace: Path,
    attempt_dir: Path,
) -> list[Path]:
    fixture = entry["execute_case_payload"]["fixture"]
    restored: list[Path] = []
    seen: set[str] = set()
    manifest_rows: list[dict[str, Any]] = []
    for kind in ("initial_files", "initial_state"):
        for binding in fixture[kind]:
            normalized, source = resolve_contained_path(
                spec_path.parent,
                binding["path"],
                f"fixture {kind}",
                kind="file",
            )
            if normalized in seen:
                raise RunnerFailure("fixture restores the same path twice")
            seen.add(normalized)
            if file_sha256(source) != binding["sha256"]:
                raise RunnerFailure(f"fixture {kind} sha256 mismatch")
            destination = workspace / normalized
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise RunnerFailure("fixture destination already exists")
            shutil.copy2(source, destination)
            destination.chmod(destination.stat().st_mode | stat.S_IWUSR)
            restored.append(destination)
            manifest_rows.append({
                "kind": kind,
                **artifact_record(
                    destination,
                    workspace,
                    encoding=_artifact_encoding(destination),
                ),
            })
    manifest = {
        "schema_version": 1,
        "fixture_hash": entry["fixture_hash"],
        "fake_services": fixture["fake_services"],
        "files": manifest_rows,
    }
    manifest_path = attempt_dir / "fixture-initial-manifest.json"
    atomic_write_json(manifest_path, manifest)
    restored.append(manifest_path)
    return restored


def _write_final_manifest(
    workspace: Path,
    attempt_dir: Path,
) -> Path:
    records: list[dict[str, str]] = []
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink():
            raise RunnerFailure("workspace contains a symlink")
        if path.is_file():
            records.append(
                artifact_record(
                    path,
                    workspace,
                    encoding=_artifact_encoding(path),
                ),
            )
    manifest_path = attempt_dir / "fixture-final-manifest.json"
    atomic_write_json(
        manifest_path,
        {"schema_version": 1, "files": records},
    )
    return manifest_path


def _run_reset_probe(
    *,
    plan: dict[str, Any],
    entry: dict[str, Any],
    host: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    spec_path: Path,
    attempt_dir: Path,
    workspace: Path,
    run_id: str,
    attempt: int,
    custody_fd: int,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    list[Path],
    bytes,
    bytes,
]:
    request = _host_request(
        plan,
        entry,
        run_id,
        attempt,
        request_kind="probe_capability",
        payload={
            "capability": "state_snapshot_reset",
            "strategy": host["reset"]["strategy"],
            "scopes": host["reset"]["scopes"],
        },
    )
    diagnostics = validate_host_protocol_record(
        "host_request", request, registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    reset_dir = attempt_dir / "reset"
    reset_dir.mkdir()
    request_path = reset_dir / "host-request.json"
    atomic_write_json(request_path, request)
    argv, environment = _validate_host_command(host, spec_path.parent)
    exit_code, stdout, stderr = _run_process(
        argv,
        cwd=workspace,
        environment=environment,
        input_bytes=canonical_json_bytes(request) + b"\n",
        timeout_seconds=entry["timeout_seconds"],
        custody_fd=custody_fd,
    )
    stdout_path = reset_dir / "host-stdout.jsonl"
    stderr_path = reset_dir / "host-stderr.txt"
    atomic_write_bytes(stdout_path, stdout)
    atomic_write_bytes(stderr_path, stderr)
    if exit_code != 0:
        raise ApparatusFailure(f"reset probe host exited {exit_code}")
    events, result, _ = _parse_host_protocol(
        stdout, request=request, registry=registry,
    )
    if (
        events
        or result["terminal_status"] != "completed"
        or not any(
            assertion["claim"] == "reset probe passed"
            and assertion["locally_verifiable"]
            for assertion in result["assertions"]
        )
    ):
        raise ApparatusFailure("reset probe did not produce a local pass")
    host_artifacts = _host_artifact_paths(result, attempt_dir)
    return (
        request,
        events,
        result,
        [request_path, stdout_path, stderr_path, *host_artifacts],
        stdout,
        stderr,
    )


def _execute_entry(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    entry: dict[str, Any],
    spec: dict[str, Any],
    host: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    spec_path: Path,
    prior_rows: list[dict[str, Any]],
    custody_fd: int,
    attempt: int = 1,
) -> dict[str, Any]:
    _, attempt_rel, attempt_dir = _attempt_paths(
        plan_path, plan, entry, attempt,
    )
    if not attempt_dir.is_dir() or attempt_dir.is_symlink():
        raise RunnerFailure("attempt custody does not own a regular directory")
    workspace = attempt_dir / "workspace"
    workspace.mkdir()

    run_id, ownership_token = _attempt_identity(
        plan, entry, attempt,
    )
    marker = _build_marker(
        plan, entry, attempt, run_id, ownership_token,
    )
    marker_path = attempt_dir / "attempt-start.json"
    atomic_write_json(marker_path, marker)
    fixture_artifacts = _restore_fixture(
        entry, spec_path, workspace, attempt_dir,
    )

    request = _host_request(plan, entry, run_id, attempt)
    diagnostics = validate_host_protocol_record(
        "host_request", request, registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    request_path = attempt_dir / "host-request.json"
    atomic_write_json(request_path, request)

    argv, environment = _validate_host_command(host, spec_path.parent)
    host_invocation_path = attempt_dir / "host-invocation.json"
    atomic_write_json(
        host_invocation_path,
        _invocation_record(
            declared_argv=host["command"]["argv"],
            resolved_argv=argv,
            environment=environment,
            executable=Path(argv[0]),
            cwd=workspace,
            attempt_dir=attempt_dir,
            timeout_seconds=entry["timeout_seconds"],
            credential_policy=spec["execution"]["credential_policy"],
        ),
    )
    started_at = _utc_now()
    _validate_calibration_time(entry, spec, spec_path, started_at)
    (
        reset_request,
        reset_events,
        reset_result,
        reset_artifacts,
        reset_stdout,
        reset_stderr,
    ) = _run_reset_probe(
        plan=plan,
        entry=entry,
        host=host,
        registry=registry,
        spec_path=spec_path,
        attempt_dir=attempt_dir,
        workspace=workspace,
        run_id=run_id,
        attempt=attempt,
        custody_fd=custody_fd,
    )
    exit_code, stdout, stderr = _run_process(
        argv,
        cwd=workspace,
        environment=environment,
        input_bytes=canonical_json_bytes(request) + b"\n",
        timeout_seconds=entry["timeout_seconds"],
        custody_fd=custody_fd,
    )
    stdout_path = attempt_dir / "host-stdout.jsonl"
    stderr_path = attempt_dir / "host-stderr.txt"
    atomic_write_bytes(stdout_path, stdout)
    atomic_write_bytes(stderr_path, stderr)
    if exit_code != 0:
        raise ApparatusFailure(f"host exited {exit_code} without complete evidence")
    events, result, checkpoints = _parse_host_protocol(
        stdout, request=request, registry=registry,
    )
    _raise_for_host_infrastructure_failure(result, "execute host")
    _validate_routing_contract(entry, events)
    _validate_state_contract(entry, events, result, checkpoints)
    _validate_runtime_records(entry, result, host, registry)
    host_artifacts = _host_artifact_paths(result, attempt_dir)
    _validate_action_lifecycle(result, attempt_dir)
    observations = _capture_observations(
        entry, attempt_dir, len(events),
    )
    faults = _capture_faults(
        entry, events, attempt_dir, result["terminal_status"],
    )
    result_path = attempt_dir / "result.json"
    atomic_write_bytes(result_path, canonical_json_bytes(result) + b"\n")

    grader_outputs, grader_artifacts = _run_deterministic_graders(
        entry, spec, spec_path, attempt_dir, result_path, custody_fd,
    )
    (
        model_outputs,
        model_requests,
        model_events,
        model_results,
        model_artifacts,
        model_stdout,
        model_stderr,
    ) = _run_model_graders(
        plan_path=plan_path,
        plan=plan,
        spec=spec,
        entry=entry,
        host=host,
        registry=registry,
        spec_path=spec_path,
        attempt_dir=attempt_dir,
        workspace=workspace,
        execution_result=result,
        run_id=run_id,
        attempt=attempt,
        credential_policy=spec["execution"]["credential_policy"],
        prior_rows=prior_rows,
        custody_fd=custody_fd,
    )
    grader_outputs.extend(model_outputs)
    usage = _merged_usage(entry, result, model_results, host)
    ended_at = _utc_now()
    _validate_calibration_time(entry, spec, spec_path, ended_at)
    final_manifest_path = _write_final_manifest(workspace, attempt_dir)
    raw_stdout_path = attempt_dir / "host-protocol.jsonl"
    raw_stderr_path = attempt_dir / "host-protocol-stderr.txt"
    atomic_write_bytes(
        raw_stdout_path,
        b"".join([reset_stdout, stdout, *model_stdout]),
    )
    atomic_write_bytes(
        raw_stderr_path,
        b"".join([reset_stderr, stderr, *model_stderr]),
    )
    all_paths = [
        *fixture_artifacts,
        *reset_artifacts,
        request_path,
        host_invocation_path,
        stdout_path,
        stderr_path,
        result_path,
        *host_artifacts,
        *grader_artifacts,
        *model_artifacts,
        final_manifest_path,
        raw_stdout_path,
        raw_stderr_path,
    ]
    artifact_records = _receipt_artifacts(all_paths, attempt_dir)
    raw_stdout = next(
        item for item in artifact_records
        if item["path"] == raw_stdout_path.relative_to(attempt_dir).as_posix()
    )
    raw_stderr = next(
        item for item in artifact_records
        if item["path"] == raw_stderr_path.relative_to(attempt_dir).as_posix()
    )
    receipt = _build_receipt(
        plan=plan,
        entry=entry,
        spec=spec,
        host=host,
        marker=marker,
        reset_request=reset_request,
        reset_events=reset_events,
        reset_result=reset_result,
        request=request,
        events=events,
        result=result,
        model_requests=model_requests,
        model_events=model_events,
        model_results=model_results,
        checkpoints=checkpoints,
        routing=_routing_from_events(
            entry["execute_case_payload"]["catalog"], events,
        ),
        observations=observations,
        faults=faults,
        grader_outputs=grader_outputs,
        usage=usage,
        artifacts=artifact_records,
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
        started_at=started_at,
        ended_at=ended_at,
    )
    _validate_receipt(
        receipt,
        plan=plan,
        entry=entry,
        marker=marker,
        spec=spec,
        registry=registry,
    )
    receipt_path = attempt_dir / "receipt.json"
    atomic_write_json(receipt_path, receipt)
    written = load_json(receipt_path)
    _validate_receipt(
        written,
        plan=plan,
        entry=entry,
        marker=marker,
        spec=spec,
        registry=registry,
    )
    return _row_from_receipt(
        plan=plan,
        entry=entry,
        attempt_rel=attempt_rel,
        receipt_path=receipt_path,
        receipt=receipt,
        registry=registry,
    )


def _verify_index_receipts(
    rows: list[dict[str, Any]],
    *,
    plan_path: Path,
    plan: dict[str, Any],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> None:
    entries = {entry["entry_id"]: entry for entry in plan["entries"]}
    valid_by_identity: dict[tuple[str, int], bool] = {}
    for row in rows:
        entry = entries.get(row["entry_id"])
        if entry is None or entry["disposition"] != "execute":
            raise RunnerFailure("index references a non-execute plan entry")
        _, attempt_rel, attempt_dir = _attempt_paths(
            plan_path, plan, entry, row["attempt"],
        )
        existing = _existing_receipt(
            plan=plan,
            entry=entry,
            attempt=row["attempt"],
            attempt_dir=attempt_dir,
            spec=spec,
            registry=registry,
        )
        if existing is None:
            raise RunnerFailure("index references an attempt without a receipt")
        _, receipt = existing
        valid_by_identity[(row["entry_id"], row["attempt"])] = receipt[
            "run"
        ]["valid"]
        expected = _row_from_receipt(
            plan=plan,
            entry=entry,
            attempt_rel=attempt_rel,
            receipt_path=attempt_dir / "receipt.json",
            receipt=receipt,
            registry=registry,
        )
        if row != expected:
            raise RunnerFailure("index row differs from its bound receipt")
    if not rows:
        return
    execute_ordinals = [
        entry["entry_ordinal"]
        for entry in plan["entries"]
        if entry["disposition"] == "execute"
    ]
    grouped: list[tuple[int, list[dict[str, Any]]]] = []
    for row in rows:
        if not grouped or grouped[-1][0] != row["entry_ordinal"]:
            grouped.append((row["entry_ordinal"], []))
        grouped[-1][1].append(row)
    observed_ordinals = [ordinal for ordinal, _ in grouped]
    if observed_ordinals != execute_ordinals[:len(observed_ordinals)]:
        raise RunnerFailure("index is not a prefix of execute entry order")
    for index, (_, group) in enumerate(grouped):
        if [row["attempt"] for row in group] != list(
            range(1, len(group) + 1),
        ):
            raise RunnerFailure("index attempts are not a continuous prefix")
        if index < len(grouped) - 1:
            last = group[-1]
            if not valid_by_identity[(last["entry_id"], last["attempt"])]:
                raise RunnerFailure(
                    "index advances past an entry without valid terminal evidence",
                )


def _runner_status(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    spec: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    selected: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    execute_entries = [
        entry for entry in selected if entry["disposition"] == "execute"
    ]
    active: list[dict[str, Any]] = []
    recoverable: list[dict[str, Any]] = []
    invalid_attempts = 0
    entry_states: dict[str, dict[str, Any]] = {}

    for entry in execute_entries:
        attempts = _attempt_directories(plan_path, plan, entry)
        last_receipt: dict[str, Any] | None = None
        active_attempt: int | None = None
        recoverable_attempt: int | None = None
        for position, (attempt, _, attempt_dir) in enumerate(attempts):
            busy = _lock_is_busy(attempt_dir)
            if busy:
                if position != len(attempts) - 1:
                    raise RunnerFailure("active attempt precedes a later attempt")
                active_attempt = attempt
                active.append({"entry_id": entry["entry_id"], "attempt": attempt})
                continue
            existing = _existing_receipt(
                plan=plan,
                entry=entry,
                attempt=attempt,
                attempt_dir=attempt_dir,
                spec=spec,
                registry=registry,
            )
            if existing is None:
                if position != len(attempts) - 1:
                    raise RunnerFailure(
                        "recoverable attempt precedes a later attempt",
                    )
                marker = load_json(attempt_dir / "attempt-start.json")
                _reserved_request(
                    attempt_dir,
                    registry,
                    _host_request(plan, entry, marker["run_id"], attempt),
                )
                recoverable_attempt = attempt
                recoverable.append({
                    "entry_id": entry["entry_id"],
                    "attempt": attempt,
                })
                continue
            _, last_receipt = existing
            if not last_receipt["run"]["valid"]:
                invalid_attempts += 1

        complete = (
            active_attempt is None
            and recoverable_attempt is None
            and last_receipt is not None
            and last_receipt["run"]["valid"]
        )
        policy = entry["attempt_policy"]
        last_attempt = attempts[-1][0] if attempts else 0
        retryable = (
            last_receipt is not None
            and not last_receipt["run"]["valid"]
            and last_receipt["run"]["error"]
            in policy["retryable_apparatus_classes"]
            and last_attempt < policy["max_attempts"]
        )
        if complete:
            next_pass = 0
            worst_case = 0
            next_attempt: int | None = None
        elif not attempts:
            next_pass = 1
            worst_case = policy["max_attempts"]
            next_attempt = 1
        elif active_attempt is not None:
            next_pass = 0
            worst_case = policy["max_attempts"] - last_attempt
            next_attempt = active_attempt
        elif recoverable_attempt is not None:
            next_pass = 0
            worst_case = policy["max_attempts"] - last_attempt
            next_attempt = recoverable_attempt
        elif retryable:
            next_pass = 1
            worst_case = policy["max_attempts"] - last_attempt
            next_attempt = last_attempt + 1
        else:
            next_pass = 0
            worst_case = 0
            next_attempt = None
        entry_states[entry["entry_id"]] = {
            "complete": complete,
            "next_pass_new_attempts": next_pass,
            "worst_case_remaining_attempts": worst_case,
            "next_attempt": next_attempt,
            "model_grade_requests_per_attempt": len(entry["model_grade_specs"]),
        }
    status = project_runner_status(
        plan=plan,
        selected=selected,
        execute_entries=execute_entries,
        rows=rows,
        entry_states=entry_states,
        active_attempts=active,
        recoverable_attempts=recoverable,
        invalid_attempts=invalid_attempts,
    )
    diagnostics = validate_v5_schema(
        status, "runner-status-v1.schema.json", registry,
    )
    if diagnostics:
        raise RunnerFailure(_first_diagnostic(diagnostics))
    return status


def _append_index_row(
    index_path: Path,
    rows: list[dict[str, Any]],
    row: dict[str, Any],
) -> bool:
    identity = (row["entry_id"], row["attempt"])
    for existing in rows:
        if (existing["entry_id"], existing["attempt"]) == identity:
            if existing != row:
                raise RunnerFailure("existing index row conflicts with receipt")
            return False
    key = (row["entry_ordinal"], row["attempt"])
    if rows and key <= (
        rows[-1]["entry_ordinal"],
        rows[-1]["attempt"],
    ):
        raise RunnerFailure("new index row would violate canonical prefix order")
    rows.append(row)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_jsonl(index_path, rows, replace=index_path.exists())
    return True


def _resume_entry(
    *,
    plan_path: Path,
    plan: dict[str, Any],
    entry: dict[str, Any],
    spec: dict[str, Any],
    host: dict[str, Any],
    registry: dict[str, dict[str, Any]],
    spec_path: Path,
    prior_rows: list[dict[str, Any]],
    budget: _AttemptBudget,
) -> Iterator[tuple[dict[str, Any], bool]]:
    attempts = _attempt_directories(plan_path, plan, entry)
    if not attempts:
        with _new_attempt_custody(
            plan_path, plan, entry, 1, budget,
        ) as custody:
            row = _execute_entry(
                plan_path=plan_path,
                plan=plan,
                entry=entry,
                spec=spec,
                host=host,
                registry=registry,
                spec_path=spec_path,
                prior_rows=prior_rows,
                custody_fd=custody.fd,
            )
            yield row, True
            custody.commit()
        return
    last_receipt: dict[str, Any] | None = None
    for position, (attempt, attempt_rel, attempt_dir) in enumerate(attempts):
        with _AttemptCustody(attempt_dir) as custody:
            existing = _existing_receipt(
                plan=plan,
                entry=entry,
                attempt=attempt,
                attempt_dir=attempt_dir,
                spec=spec,
                registry=registry,
            )
            if existing is None:
                if position != len(attempts) - 1:
                    raise RunnerFailure(
                        "non-terminal attempt gap precedes a later attempt",
                    )
                receipt = _resume_seal(
                    plan=plan,
                    entry=entry,
                    spec=spec,
                    host=host,
                    attempt=attempt,
                    attempt_dir=attempt_dir,
                    registry=registry,
                )
                row = _row_from_receipt(
                    plan=plan,
                    entry=entry,
                    attempt_rel=attempt_rel,
                    receipt_path=attempt_dir / "receipt.json",
                    receipt=receipt,
                    registry=registry,
                )
                last_receipt = receipt
                yield row, False
                custody.commit()
                break
            _, receipt = existing
            row = _row_from_receipt(
                plan=plan,
                entry=entry,
                attempt_rel=attempt_rel,
                receipt_path=attempt_dir / "receipt.json",
                receipt=receipt,
                registry=registry,
            )
            last_receipt = receipt
            yield row, position == len(attempts) - 1 and receipt["run"]["valid"]
            custody.commit()

    if last_receipt is None:
        raise RunnerFailure("resume inspection produced no terminal receipt")
    last_attempt = attempts[-1][0]
    policy = entry["attempt_policy"]
    retry_class = last_receipt["run"]["error"]
    retryable = (
        not last_receipt["run"]["valid"]
        and retry_class in policy["retryable_apparatus_classes"]
        and last_attempt < policy["max_attempts"]
    )
    if retryable:
        budget.ensure_available()
        if policy["backoff_seconds"]:
            time.sleep(policy["backoff_seconds"])
        with _new_attempt_custody(
            plan_path, plan, entry, last_attempt + 1, budget,
        ) as custody:
            row = _execute_entry(
                plan_path=plan_path,
                plan=plan,
                entry=entry,
                spec=spec,
                host=host,
                registry=registry,
                spec_path=spec_path,
                prior_rows=prior_rows,
                custody_fd=custody.fd,
                attempt=last_attempt + 1,
            )
            yield row, True
            custody.commit()


def _index_path(
    plan_path: Path,
    plan: dict[str, Any],
    requested: Path,
) -> Path:
    _, artifacts_root = resolve_contained_path(
        plan_path.parent,
        plan["artifacts"]["root"],
        "artifacts root",
    )
    _, expected = resolve_contained_path(
        artifacts_root,
        plan["artifacts"]["index_relpath"],
        "run index",
    )
    if requested.resolve() != expected:
        raise RunnerFailure("--index does not match the plan index projection")
    return expected


def _selected_entries(
    plan: dict[str, Any],
    entry_id: str | None,
) -> list[dict[str, Any]]:
    if entry_id is None:
        return list(plan["entries"])
    selected = [
        entry for entry in plan["entries"]
        if entry["entry_id"] == entry_id
    ]
    if len(selected) != 1:
        raise RunnerFailure(f"unknown plan entry ID: {entry_id}")
    return selected


def _run_command(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan).resolve()
    try:
        registry = load_v5_schema_registry()
        plan = _load_plan(plan_path, registry)
        spec, _, host, registry, spec_path = _load_bound_contract(
            plan, plan_path,
        )
        index_path = _index_path(plan_path, plan, Path(args.index))
        selected = _selected_entries(plan, args.entry_id)
        if args.status and (
            args.resume
            or args.new_attempt_budget is not None
            or args.max_parallel is not None
        ):
            raise RunnerFailure(
                "--status conflicts with --resume, --new-attempt-budget, "
                "and --max-parallel",
            )
        max_parallel = args.max_parallel if args.max_parallel is not None else 1
        if max_parallel < 1:
            raise RunnerFailure("--max-parallel must be at least 1")
        if max_parallel > spec["execution"]["max_parallel"]:
            raise RunnerFailure("--max-parallel exceeds the spec limit")

        execute_entries = [
            entry for entry in selected
            if entry["disposition"] == "execute"
        ]
        for entry in execute_entries:
            if not set(entry["required_authority"]) <= set(
                plan["authority"]["runner_capabilities"],
            ):
                raise RunnerFailure("entry requires unavailable runner authority")
        if execute_entries:
            for entry in execute_entries:
                _validate_calibration_time(
                    entry, spec, spec_path, _utc_now(),
                )
            _validate_host_command(host, spec_path.parent)
        rows = _load_index(index_path, plan=plan, registry=registry)
        _verify_index_receipts(
            rows,
            plan_path=plan_path,
            plan=plan,
            spec=spec,
            registry=registry,
        )
        status = _runner_status(
            plan_path=plan_path,
            plan=plan,
            spec=spec,
            registry=registry,
            selected=selected,
            rows=rows,
        )
        if args.status:
            sys.stdout.buffer.write(canonical_json_bytes(status) + b"\n")
            return 0
        if args.new_attempt_budget is None:
            raise RunnerFailure("--new-attempt-budget is required")
        if args.new_attempt_budget < 0:
            raise RunnerFailure("--new-attempt-budget must be non-negative")
        if (
            args.new_attempt_budget
            > status["worst_case_remaining_attempts"]
        ):
            raise RunnerFailure(
                "--new-attempt-budget exceeds worst-case remaining attempts",
            )
        if args.new_attempt_budget < status["next_pass_new_attempts"]:
            raise RunnerFailure(
                "--new-attempt-budget is below next-pass attempts",
            )
        budget = _AttemptBudget(args.new_attempt_budget)
        print(
            "RUN PREFLIGHT: "
            f"selected={status['selected_entries']} "
            f"next_pass={status['next_pass_new_attempts']} "
            f"worst_case={status['worst_case_remaining_attempts']} "
            f"execute_case_ceiling={status['execute_case_request_ceiling']} "
            f"model_grade_ceiling={status['model_grade_request_ceiling']} "
            f"authorized={budget.authorized}",
        )
        if not args.resume and (
            rows
            or any(
                _attempt_directories(plan_path, plan, entry)
                for entry in execute_entries
            )
        ):
            raise RunnerFailure(
                "existing attempt state requires --resume",
            )
        incomplete = False
        for entry in execute_entries:
            if args.resume:
                complete = False
                for row, complete in _resume_entry(
                    plan_path=plan_path,
                    plan=plan,
                    entry=entry,
                    spec=spec,
                    host=host,
                    registry=registry,
                    spec_path=spec_path,
                    prior_rows=rows,
                    budget=budget,
                ):
                    _append_index_row(index_path, rows, row)
            else:
                with _new_attempt_custody(
                    plan_path, plan, entry, 1, budget,
                ) as custody:
                    row = _execute_entry(
                        plan_path=plan_path,
                        plan=plan,
                        entry=entry,
                        spec=spec,
                        host=host,
                        registry=registry,
                        spec_path=spec_path,
                        prior_rows=rows,
                        custody_fd=custody.fd,
                    )
                    complete = True
                    _append_index_row(index_path, rows, row)
                    custody.commit()
            incomplete = incomplete or not complete
            if not complete:
                break
        if incomplete:
            raise ApparatusFailure(
                "one or more entries have only invalid apparatus evidence",
            )
    except ApparatusFailure as exc:
        print(f"runner apparatus failure: {exc}", file=sys.stderr)
        return 3
    except (
        RunnerFailure,
        compiler.ContractFailure,
        FileExistsError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        print(f"runner error: {exc}", file=sys.stderr)
        return 2
    print(
        f"RUN COMPLETE: selected={len(selected)} execute={len(execute_entries)}",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan")
    parser.add_argument("--index", required=True)
    parser.add_argument("--entry-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--new-attempt-budget", type=int)
    parser.add_argument("--max-parallel", type=int)
    return _run_command(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
