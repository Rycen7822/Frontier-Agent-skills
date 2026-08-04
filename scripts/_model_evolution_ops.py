#!/usr/bin/env python3
"""Allowlisted model-free operations for the model evolution controller."""

from __future__ import annotations

from hashlib import sha256
import json
import math
import os
from pathlib import Path
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

import build_codex_plugin as plugin_builder
import codex_eval_host as host_adapter
from _codex_eval_delivery import (
    DeliveryError,
    project_command_environment,
    validate_plugin_catalog,
)

from _model_evolution_contract import (
    ContractError,
    HOST_CLEANUP_GRACE_SECONDS,
    SAFE_ID,
    SKILL_IDS,
    canonical_bytes,
    content_hash,
    evaluator_evidence_status,
    load_json,
    load_jsonl,
    make_binding,
    project_observed_host,
    project_qualification,
    resolve_binding,
    strict_json_bytes,
    validate_document,
    validate_bundle_build,
    validate_formal_timeout_inputs,
    verify_self_hash,
    with_self_hash,
)


MAX_DIAGNOSTIC_BYTES = 64 * 1024
PLUGIN_BUILD_GATE_SCRIPT = "scripts/build_codex_plugin.py"
ALLOWED_GATE_SCRIPTS = {
    "bundle/build_bundle_manifest.py",
    PLUGIN_BUILD_GATE_SCRIPT,
    "scripts/evaluate_static_contracts.py",
    "scripts/build_model_evolution_sentinels.py",
    "skill-evaluator/scripts/compile_eval_plan.py",
    "skill-evaluator/scripts/run_eval_plan.py",
    "skill-evaluator/scripts/analyze_runs.py",
    "skill-evaluator/scripts/validate_eval_suite.py",
}


class OperationError(ValueError):
    """A model-free operation, Git, or candidate policy failure."""


def _run(
    argv: list[str],
    *,
    cwd: Path,
    acceptable: set[int] = {0},
    timeout: float = 120,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            input=stdin,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            shell=False,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperationError(
            f"operation failed to start or timed out: {argv[0]}"
        ) from exc
    if result.returncode not in acceptable:
        diagnostic = (result.stderr or result.stdout).encode("utf-8")[
            :MAX_DIAGNOSTIC_BYTES
        ]
        raise OperationError(
            f"operation exited {result.returncode}: {diagnostic.decode('utf-8', errors='replace').strip()}"
        )
    return result


def _git(repository_root: Path, *args: str, acceptable: set[int] = {0}) -> str:
    return _run(
        ["git", "-C", str(repository_root), *args],
        cwd=repository_root,
        acceptable=acceptable,
        timeout=30,
    ).stdout.strip()


def git_identity(repository_root: Path, revision: str = "HEAD") -> dict[str, str]:
    dirty = _git(repository_root, "status", "--porcelain=v1", "--untracked-files=no")
    if dirty:
        raise OperationError("tracked worktree is not clean")
    commit = _git(repository_root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    tree = _git(repository_root, "rev-parse", "--verify", f"{commit}^{{tree}}")
    _git(repository_root, "verify-commit", commit)
    return {"commit": commit, "tree": tree}


def _git_blob(repository_root: Path, revision: str, path: str) -> bytes | None:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "cat-file",
                "blob",
                f"{revision}:{path}",
            ],
            cwd=repository_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git_blob_matches(
    repository_root: Path,
    revision: str,
    path: str,
    expected_hash: str,
) -> bool:
    blob = _git_blob(repository_root, revision, path)
    return blob is not None and content_hash(blob) == expected_hash


def bundle_skill_at_revision(
    repository_root: Path, revision: str, skill_id: str
) -> dict[str, Any]:
    raw = _git_blob(repository_root, revision, "frontier-engineering.bundle.json")
    if raw is None:
        raise OperationError("Bundle build is unavailable at selected revision")
    try:
        build = validate_bundle_build(
            strict_json_bytes(raw, label="selected Bundle build")
        )
    except (ContractError, KeyError) as exc:
        raise OperationError(str(exc)) from exc
    try:
        return build["skills"][skill_id]
    except KeyError as exc:
        raise OperationError("selected Bundle build lacks the requested Skill") from exc


def is_tracked(repository_root: Path, path: Path) -> bool:
    try:
        relative = path.resolve(strict=True).relative_to(
            repository_root.resolve(strict=True)
        )
    except (OSError, ValueError):
        return False
    result = _run(
        [
            "git",
            "-C",
            str(repository_root),
            "ls-files",
            "--error-unmatch",
            "--",
            relative.as_posix(),
        ],
        cwd=repository_root,
        acceptable={0, 1},
        timeout=30,
    )
    return result.returncode == 0


def require_tracked_binding(repository_root: Path, path: Path) -> None:
    if not is_tracked(repository_root, path):
        raise OperationError(f"repository artifact is not tracked: {path.name}")


def _operation_fact(
    operation_id: str,
    argv: list[str],
    input_value: Any,
    duration_ms: int,
    status: str = "pass",
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "input_hash": content_hash(canonical_bytes(input_value)),
        "command_hash": content_hash(canonical_bytes(argv)),
        "status": status,
        "duration_ms": duration_ms,
    }


def run_model_free_command(
    operation_id: str,
    argv: list[str],
    *,
    repository_root: Path,
    acceptable: set[int] = {0},
    timeout: float = 120,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    if not argv or Path(argv[0]).name not in {
        "python",
        "python3",
        Path(sys.executable).name,
    }:
        raise OperationError(
            "model-free command must use the frozen Python interpreter"
        )
    script = next((item for item in argv[1:] if item.endswith(".py")), None)
    if script is None or script not in ALLOWED_GATE_SCRIPTS:
        raise OperationError("model-free command is not allowlisted")
    before = _git(repository_root, "status", "--porcelain=v1", "--untracked-files=all")
    started = time.monotonic()
    result = _run(argv, cwd=repository_root, acceptable=acceptable, timeout=timeout)
    duration = round((time.monotonic() - started) * 1000)
    after = _git(repository_root, "status", "--porcelain=v1", "--untracked-files=all")
    if before != after:
        raise OperationError("model-free command changed the frozen worktree inventory")
    return _operation_fact(operation_id, argv, before, duration), result


def _materialize_evaluator_fixture(
    repository_root: Path, target: Path
) -> dict[str, Path]:
    code = (
        "import sys; from pathlib import Path; "
        f"sys.path.insert(0, {str(repository_root / 'tests')!r}); "
        "from skill_evaluator_test_support import materialize_v5_contract_fixture; "
        "materialize_v5_contract_fixture(Path(sys.argv[1]))"
    )
    _run([sys.executable, "-c", code, str(target)], cwd=repository_root, timeout=60)
    return {
        "spec": target / "spec-v5.json",
        "scenarios": target / "scenarios-v1.jsonl",
        "host": target / "host-manifest-v1.json",
    }


def fake_full_chain(repository_root: Path) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(
        prefix="frontier-model-evolution-preflight-"
    ) as tmp:
        root = Path(tmp)
        paths = _materialize_evaluator_fixture(repository_root, root)
        plan = root / "execution-plan.json"
        index = root / "artifacts/index.jsonl"
        summary = root / "summary.json"
        failures = root / "failures.json"
        commands = [
            (
                "fake-compile",
                [
                    sys.executable,
                    "skill-evaluator/scripts/compile_eval_plan.py",
                    str(paths["spec"]),
                    str(paths["scenarios"]),
                    str(paths["host"]),
                    "--output",
                    str(plan),
                ],
                {0},
            )
        ]
        for operation_id, argv, acceptable in commands:
            fact, _ = run_model_free_command(
                operation_id,
                argv,
                repository_root=repository_root,
                acceptable=acceptable,
            )
            operations.append(fact)
        status_argv = [
            sys.executable,
            "skill-evaluator/scripts/run_eval_plan.py",
            str(plan),
            "--index",
            str(index),
            "--status",
        ]
        status_fact, status_result = run_model_free_command(
            "fake-runner-status", status_argv, repository_root=repository_root
        )
        operations.append(status_fact)
        status = json.loads(status_result.stdout)
        run_argv = [
            sys.executable,
            "skill-evaluator/scripts/run_eval_plan.py",
            str(plan),
            "--index",
            str(index),
            "--new-attempt-budget",
            str(status["next_pass_new_attempts"]),
        ]
        run_fact, _ = run_model_free_command(
            "fake-runner", run_argv, repository_root=repository_root
        )
        operations.append(run_fact)
        analyze_argv = [
            sys.executable,
            "skill-evaluator/scripts/analyze_runs.py",
            str(index),
            "--spec",
            str(paths["spec"]),
            "--json",
            str(summary),
            "--failure-index",
            str(failures),
        ]
        analyze_fact, _ = run_model_free_command(
            "fake-analyze",
            analyze_argv,
            repository_root=repository_root,
            acceptable={0, 3},
        )
        operations.append(analyze_fact)
        evaluator_evidence_status(summary, kind="current_summary")
        operations.append(
            _operation_fact(
                "fake-bootstrap-comparison",
                ["bootstrap-model-transition"],
                {"predecessor": None, "summary": content_hash(summary.read_bytes())},
                0,
            )
        )
    return operations


def _write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(canonical_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise OperationError(f"refusing to replace artifact: {path.name}") from exc


def _probe_argv(host: dict[str, Any], repository_root: Path) -> list[str]:
    argv = list(host["command"]["argv"])
    if not argv or any(not isinstance(item, str) for item in argv):
        raise OperationError("target Host command argv is invalid")
    executable = shutil.which(argv[0]) if not Path(argv[0]).is_absolute() else argv[0]
    if executable is None:
        raise OperationError("target Host executable is unavailable")
    argv[0] = executable
    if len(argv) > 1 and argv[1].endswith(".py") and not Path(argv[1]).is_absolute():
        argv[1] = str((repository_root / argv[1]).resolve(strict=True))
    for option in ("--codex", "--host-manifest"):
        if option in argv:
            position = argv.index(option) + 1
            candidate = Path(argv[position])
            if not candidate.is_absolute():
                argv[position] = str((repository_root / candidate).resolve(strict=True))
    if "--mode" in argv:
        argv[argv.index("--mode") + 1] = "probe"
    else:
        argv.extend(["--mode", "probe"])
    return argv


def _probe_process_timeout(argv: list[str]) -> float:
    positions = [index for index, value in enumerate(argv) if value == "--timeout"]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise OperationError("target Host timeout is invalid")
    try:
        host_timeout = float(argv[positions[0] + 1])
    except (TypeError, ValueError) as exc:
        raise OperationError("target Host timeout is invalid") from exc
    if not math.isfinite(host_timeout) or host_timeout <= 0:
        raise OperationError("target Host timeout is invalid")
    return host_timeout + HOST_CLEANUP_GRACE_SECONDS


def _run_probe_process(
    argv: list[str],
    row: dict[str, Any],
    *,
    environment: dict[str, str],
    workspace: Path,
    timeout: float,
) -> tuple[dict[str, Any], str]:
    request = {
        "schema_version": "codex-interaction-probe/1.0",
        "probe_id": row["probe_id"],
        "capability": row["capability"],
        "prompt": row["prompt"],
        "expected_event_types": row["required_observations"],
    }
    try:
        process = subprocess.Popen(
            argv,
            cwd=workspace,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=environment,
            start_new_session=True,
        )
    except OSError as exc:
        raise OperationError("interaction probe process failed to start") from exc
    try:
        stdout, stderr = process.communicate(
            input=json.dumps(request, separators=(",", ":")) + "\n",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        diagnostic = stderr[:8192].replace(str(workspace), "<workspace>").strip()
        detail = f": {diagnostic}" if diagnostic else ""
        raise OperationError(
            f"interaction probe exceeded outer timeout after {timeout:g}s{detail}"
        ) from exc
    bounded_stderr = stderr[:8192].replace(str(workspace), "<workspace>")
    if process.returncode:
        raise OperationError(
            f"interaction probe exited {process.returncode}: {bounded_stderr.strip()}"
        )
    lines = [line for line in stdout.splitlines() if line]
    if len(lines) != 1:
        raise OperationError("interaction probe must emit exactly one JSON result")
    try:
        value = strict_json_bytes(
            lines[0].encode("utf-8"), label="interaction probe result"
        )
    except ContractError as exc:
        raise OperationError("interaction probe result is not strict JSON") from exc
    return _validate_probe_result(value, row), bounded_stderr


def _validate_probe_result(value: Any, row: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "probe_id",
        "capability",
        "status",
        "observed",
        "session_id",
        "event_types",
        "direct_observations",
        "routing",
        "usage",
        "diagnostics",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value["schema_version"] != host_adapter.PROBE_RESULT_SCHEMA_VERSION
        or value["probe_id"] != row["probe_id"]
        or value["capability"] != row["capability"]
        or value["status"] not in {"pass", "unknown"}
        or not isinstance(value["routing"], list)
        or not all(
            isinstance(skill_id, str) and skill_id
            for skill_id in value["routing"]
        )
        or value["routing"] != sorted(set(value["routing"]))
        or (
            ("direct.routing" in value["direct_observations"])
            != bool(value["routing"])
        )
    ):
        raise OperationError("interaction probe result shape or identity is invalid")
    return value


def _load_probe_terminal(
    path: Path,
    *,
    request: dict[str, Any],
    row: dict[str, Any],
    probe_set_hash: str,
) -> dict[str, Any]:
    terminal = load_json(path, label="interaction probe terminal")
    required = {
        "schema_version",
        "request_id",
        "probe_id",
        "probe_set_hash",
        "result",
        "stderr",
        "terminal_hash",
    }
    if (
        not isinstance(terminal, dict)
        or set(terminal) != required
        or terminal["schema_version"] != "model-evolution-probe-terminal/1"
        or terminal["request_id"] != request["request_id"]
        or terminal["probe_id"] != row["probe_id"]
        or terminal["probe_set_hash"] != probe_set_hash
        or not isinstance(terminal["stderr"], str)
    ):
        raise OperationError("interaction probe terminal shape or identity is invalid")
    verify_self_hash(terminal, "terminal_hash")
    _validate_probe_result(terminal["result"], row)
    return terminal


def run_interaction_probes(
    campaign: dict[str, Any],
    *,
    probe_set: dict[str, Any],
    approval_binding: dict[str, Any],
    repository_root: Path,
    campaign_root: Path,
    resume_existing: bool = False,
) -> dict[str, Any]:
    provisional_binding = campaign["profiles"]["target_provisional"]
    provisional = load_json(
        resolve_binding(provisional_binding, repository_root, campaign_root),
        label="target provisional Host",
    )
    argv = _probe_argv(provisional, repository_root)
    try:
        environment = project_command_environment(
            provisional["command"],
            dict(os.environ),
            require_model_evolution=True,
        )
    except DeliveryError as exc:
        raise OperationError(str(exc)) from exc
    process_timeout = _probe_process_timeout(argv)
    probes_root = campaign_root / "probes"
    if probes_root.is_symlink():
        raise OperationError("interaction probe artifact root is symlinked")
    if resume_existing:
        if not probes_root.is_dir():
            raise OperationError(
                "reserved probe terminals are missing; automatic resend is forbidden"
            )
        missing = [
            request["request_id"]
            for request in campaign["interaction_probes"]["requests"]
            if not (probes_root / f"{request['request_id']}.json").is_file()
        ]
        if missing:
            raise OperationError(
                "reserved probe terminal is missing; automatic resend is forbidden"
            )
    else:
        probes_root.mkdir(mode=0o700, exist_ok=False)
    artifacts: dict[str, dict[str, Any]] = {}
    statuses: dict[str, str] = {}
    result_rows: list[dict[str, Any]] = []
    by_probe_id = {row["probe_id"]: row for row in probe_set["probes"]}
    for request in campaign["interaction_probes"]["requests"]:
        row = by_probe_id[request["probe_id"]]
        terminal_path = probes_root / f"{request['request_id']}.json"
        if resume_existing:
            terminal = _load_probe_terminal(
                terminal_path,
                request=request,
                row=row,
                probe_set_hash=probe_set["probe_set_hash"],
            )
            value = terminal["result"]
        else:
            with tempfile.TemporaryDirectory(
                prefix="frontier-interaction-probe-"
            ) as tmp:
                workspace = Path(tmp)
                fixture = resolve_binding(
                    row["fixture"], repository_root, campaign_root
                )
                if fixture.is_symlink() or not fixture.is_file():
                    raise OperationError("interaction probe fixture is invalid")
                shutil.copy2(fixture, workspace / fixture.name)
                value, stderr = _run_probe_process(
                    argv,
                    row,
                    environment=environment,
                    workspace=workspace,
                    timeout=process_timeout,
                )
            terminal = with_self_hash(
                {
                    "schema_version": "model-evolution-probe-terminal/1",
                    "request_id": request["request_id"],
                    "probe_id": row["probe_id"],
                    "probe_set_hash": probe_set["probe_set_hash"],
                    "result": value,
                    "stderr": stderr,
                },
                "terminal_hash",
            )
            _write_json_exclusive(terminal_path, terminal)
        binding = make_binding(
            terminal_path,
            root="campaign",
            repository_root=repository_root,
            campaign_root=campaign_root,
        )
        artifacts[request["request_id"]] = binding
        statuses[request["request_id"]] = value["status"]
        result_rows.append(
            {
                "request_id": request["request_id"],
                "probe_id": row["probe_id"],
                "status": value["status"],
                "terminal": binding,
            }
        )
        if value["diagnostics"]:
            raise OperationError(
                "interaction probe protocol diagnostic stopped the probe set"
            )
    results = with_self_hash(
        {
            "schema_version": "model-evolution-probe-results/1",
            "campaign_hash": campaign["campaign_hash"],
            "probe_set_hash": probe_set["probe_set_hash"],
            "budget_approval": approval_binding,
            "requests": result_rows,
        },
        "results_hash",
    )
    results_path = campaign_root / "probe-results.json"
    if results_path.exists():
        if canonical_bytes(
            load_json(results_path, label="probe results")
        ) != canonical_bytes(results):
            raise OperationError(
                "existing probe results differ from recovered terminals"
            )
    else:
        _write_json_exclusive(results_path, results)
    results_binding = make_binding(
        results_path,
        root="campaign",
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    observed_path = campaign_root / "target-observed-host.json"
    observed = project_observed_host(
        provisional,
        probe_set=probe_set,
        results=result_rows,
        observed_manifest_path=observed_path,
    )
    if observed_path.exists():
        if canonical_bytes(
            load_json(observed_path, label="target observed Host")
        ) != canonical_bytes(observed):
            raise OperationError("existing observed Host differs from recovered probes")
    else:
        _write_json_exclusive(observed_path, observed)
    observed_binding = make_binding(
        observed_path,
        root="campaign",
        repository_root=repository_root,
        campaign_root=campaign_root,
    )
    return {
        "artifacts": artifacts,
        "statuses": statuses,
        "results_binding": results_binding,
        "observed_host_binding": observed_binding,
    }


def systemd_probe_argv(unit: str, completion_file: Path) -> list[str]:
    if not unit or not all(
        character.isalnum() or character in "_.-" for character in unit
    ):
        raise OperationError("systemd unit name is unsafe")
    return [
        "systemd-run",
        "--user",
        "--unit",
        unit,
        "--collect",
        sys.executable,
        "-c",
        "import pathlib,time,sys; time.sleep(0.1); pathlib.Path(sys.argv[1]).write_text('closed')",
        str(completion_file),
    ]


def verify_systemd_user(campaign_id: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="frontier-systemd-probe-") as tmp:
        completion = Path(tmp) / "closed"
        argv = systemd_probe_argv(f"frontier-{campaign_id}-preflight", completion)
        started = time.monotonic()
        _run(argv, cwd=Path(tmp), timeout=30)
        deadline = time.monotonic() + 10
        while not completion.is_file() and time.monotonic() < deadline:
            time.sleep(0.1)
        if completion.read_text(encoding="utf-8") != "closed":
            raise OperationError(
                "systemd user transient service did not outlive the client"
            )
        return _operation_fact(
            "systemd-user-lifecycle",
            argv[:-1] + ["<completion>"],
            campaign_id,
            round((time.monotonic() - started) * 1000),
        )


def validate_plugin_staging(
    *,
    repository_root: Path,
    plugin_root: Path,
    evidence_path: Path,
    expected_commit: str,
    expected_bundle_id: str,
    expected_bundle_version: str,
    expected_skill_versions: dict[str, str],
) -> dict[str, Any]:
    try:
        evidence = plugin_builder.validate_plugin_build(
            plugin_root,
            evidence_path,
            source_root=repository_root,
            release_authorization=None,
        )
    except (OSError, ValueError) as exc:
        raise OperationError(f"plugin staging validation failed: {exc}") from exc
    expected = {
        "source_revision": expected_commit,
        "bundle_id": expected_bundle_id,
        "bundle_version": expected_bundle_version,
        "skill_versions": expected_skill_versions,
        "output_class": "staging",
    }
    for field, value in expected.items():
        if evidence.get(field) != value:
            raise OperationError(
                f"plugin staging {field} differs from selected product"
            )
    return evidence


def _validate_host_plugin_binding(host: dict[str, Any], plugin_root: Path) -> None:
    command = host.get("command")
    argv = command.get("argv") if isinstance(command, dict) else None
    if not isinstance(argv, list):
        raise OperationError("target Host command is invalid")
    positions = [index for index, item in enumerate(argv) if item == "--plugin-root"]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise OperationError("target Host does not bind one plugin root")
    try:
        bound = Path(argv[positions[0] + 1]).resolve(strict=True)
    except OSError as exc:
        raise OperationError("target Host plugin root is unavailable") from exc
    if bound != plugin_root.resolve(strict=True):
        raise OperationError("target Host plugin root differs from campaign staging")
    try:
        validate_plugin_catalog(plugin_root, host)
    except DeliveryError as exc:
        raise OperationError(str(exc)) from exc


def validate_target_host_staging(
    host_path: Path,
    plugin_root: Path,
    *,
    repository_root: Path,
    expected_commit: str,
    expected_tree: str,
) -> dict[str, Any]:
    try:
        host = host_adapter.validate_bound_manifest(host_path, plugin_root)
    except (host_adapter.AdapterError, DeliveryError, OSError, ValueError) as exc:
        raise OperationError(f"target Host staging validation failed: {exc}") from exc
    expected = {
        "dirty": False,
        "revision": expected_commit,
        "tree": expected_tree,
        "worktree": str(repository_root.resolve(strict=True)),
    }
    if host.get("identity", {}).get("repository") != expected:
        raise OperationError("target Host repository identity differs")
    return host


def preflight_operations(
    campaign: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    check_systemd: bool,
) -> dict[str, Any]:
    identity = git_identity(repository_root)
    if identity["commit"] != campaign["product"]["source_commit"]:
        raise OperationError("preflight source commit differs from campaign product")
    operations: list[dict[str, Any]] = []
    for operation_id, script in (
        ("bundle-check", "bundle/build_bundle_manifest.py"),
        ("static-check", "scripts/evaluate_static_contracts.py"),
        ("sentinel-check", "scripts/build_model_evolution_sentinels.py"),
    ):
        fact, _ = run_model_free_command(
            operation_id,
            [sys.executable, script, "--check"],
            repository_root=repository_root,
        )
        operations.append(fact)
    plugin_build = resolve_binding(
        campaign["product"]["plugin_build"],
        repository_root,
        campaign_root,
    )
    plugin_root = campaign_root / campaign["product"]["plugin_root"]
    fact, _ = run_model_free_command(
        "plugin-build-check",
        [
            sys.executable,
            PLUGIN_BUILD_GATE_SCRIPT,
            "--source-root",
            str(repository_root),
            "--validate-plugin-root",
            str(plugin_root),
            "--build-evidence",
            str(plugin_build),
        ],
        repository_root=repository_root,
    )
    operations.append(fact)
    host_path = resolve_binding(
        campaign["profiles"]["target_provisional"],
        repository_root,
        campaign_root,
    )
    started = time.monotonic()
    validated_host = validate_target_host_staging(
        host_path,
        plugin_root,
        repository_root=repository_root,
        expected_commit=campaign["product"]["source_commit"],
        expected_tree=campaign["product"]["source_tree"],
    )
    operations.append(
        _operation_fact(
            "host-plugin-binding",
            ["validate-host-plugin-binding"],
            validated_host["manifest_hash"],
            round((time.monotonic() - started) * 1000),
        )
    )
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    for skill_id in SKILL_IDS:
        record = sentinel["skills"][skill_id]
        spec = resolve_binding(record["spec_template"], repository_root, campaign_root)
        scenarios = resolve_binding(
            record["public_scenarios"], repository_root, campaign_root
        )
        validate_formal_timeout_inputs(
            validated_host,
            load_json(spec, label=f"{skill_id} sentinel spec"),
            load_jsonl(scenarios, label=f"{skill_id} sentinel scenarios"),
        )
        host_template = spec.parent / "host-manifest.template.json"
        fact, _ = run_model_free_command(
            f"sentinel-contract-{skill_id}",
            [
                sys.executable,
                "skill-evaluator/scripts/validate_eval_suite.py",
                "contract",
                str(spec),
                str(scenarios),
                str(host_template),
                "--json",
                "-",
            ],
            repository_root=repository_root,
        )
        operations.append(fact)
    for name in (
        "budget_approval",
        "campaign",
        "interaction_probes",
        "sentinel_index",
    ):
        started = time.monotonic()
        validate_document(
            with_self_hash(
                _minimal_schema_fixture(name, campaign),
                {
                    "budget_approval": "approval_hash",
                    "campaign": "campaign_hash",
                    "interaction_probes": "probe_set_hash",
                    "sentinel_index": "sentinel_hash",
                }[name],
            ),
            name,
        )
        operations.append(
            _operation_fact(
                f"schema-{name}",
                ["validate-schema", name],
                campaign["campaign_hash"],
                round((time.monotonic() - started) * 1000),
            )
        )
    operations.extend(fake_full_chain(repository_root))
    qualification = project_qualification(
        campaign,
        repository_root=repository_root,
        campaign_root=campaign_root,
        observed_as_of="2026-01-01T00:00:00Z",
        valid_until="2026-01-02T00:00:00Z",
    )
    operations.append(
        _operation_fact(
            "fake-qualification",
            ["project-qualification"],
            qualification["qualification_hash"],
            0,
        )
    )
    if check_systemd:
        operations.append(verify_systemd_user(campaign["campaign_id"]))
    report = {
        "schema_version": "model-evolution-apparatus-report/1",
        "campaign_id": campaign["campaign_id"],
        "source_commit": identity["commit"],
        "source_tree": identity["tree"],
        "campaign_hash": campaign["campaign_hash"],
        "status": "pass",
        "operations": operations,
    }
    return with_self_hash(report, "apparatus_report_hash")


def _minimal_schema_fixture(name: str, campaign: dict[str, Any]) -> dict[str, Any]:
    if name == "budget_approval":
        return {
            "schema_version": "model-evolution-budget-approval/1",
            "campaign_id": campaign["campaign_id"],
            "campaign_hash": campaign["campaign_hash"],
            "state_revision": campaign["state_revision"],
            "ceilings": campaign["budgets"]["ceiling"],
            "planned": {
                "interaction_probe_requests": 1,
                "public_plan_count": 4,
                "artifact_file_ceiling": 1,
                "wall_clock_seconds": 1,
            },
            "approved": True,
            "approved_by": "preflight-fixture",
            "approved_at": "2026-08-03T00:00:00Z",
        }
    if name == "campaign":
        return {key: value for key, value in campaign.items() if key != "campaign_hash"}
    if name == "interaction_probes":
        return {
            "schema_version": "model-evolution-interaction-probes/1",
            "probe_set_id": "preflight-probes",
            "adapter_protocol_version": "codex-interaction-probe/1.0",
            "probes": [
                {
                    "probe_id": "preflight-probe",
                    "capability": "multi_turn",
                    "prompt": "Return one inert completion.",
                    "fixture": campaign["sentinel_index"],
                    "sandbox": "read-only",
                    "network": "denied",
                    "required_observations": ["thread.started", "turn.completed"],
                    "request_ceiling": 1,
                }
            ],
        }
    if name == "sentinel_index":
        source = campaign["sentinel_index"]
        item = {
            "critical_bucket_id": "preflight-critical",
            "spec_template": source,
            "public_scenarios": source,
            "calibration_gold": source,
            "calibration_request_ceiling": 1,
            "fixture_roots": [source],
            "verifier_roots": [source],
            "required_coverage_tags": ["preflight"],
            "protected_case_ids": ["preflight-case"],
            "external_holdout_contract_id": "preflight-holdout",
            "holdout_case_ceiling": 2,
        }
        return {
            "schema_version": "model-evolution-sentinel-index/1",
            "sentinel_id": "preflight-sentinel",
            "skills": {
                skill_id: dict(item)
                for skill_id in (
                    "long-document-segmented-writing",
                    "skill-evaluator",
                    "software-quality-workflows",
                    "writing-plans",
                )
            },
        }
    raise OperationError(f"unknown schema fixture {name}")


def runner_status(
    plan: Path,
    index: Path,
    *,
    repository_root: Path,
) -> dict[str, Any]:
    result = _run(
        [
            sys.executable,
            "skill-evaluator/scripts/run_eval_plan.py",
            str(plan),
            "--index",
            str(index),
            "--status",
        ],
        cwd=repository_root,
        timeout=60,
    )
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OperationError("runner status is not JSON") from exc
    if not isinstance(status, dict):
        raise OperationError("runner status is not an object")
    return status


def render_runner_command(
    plan: Path,
    index: Path,
    *,
    attempt_budget: int,
    service_id: str,
    repository_root: Path,
) -> str:
    argv = [
        "systemd-run",
        "--user",
        "--unit",
        service_id,
        "--collect",
        f"--working-directory={repository_root}",
        sys.executable,
        "skill-evaluator/scripts/run_eval_plan.py",
        str(plan),
        "--index",
        str(index),
        "--new-attempt-budget",
        str(attempt_budget),
    ]
    return shlex.join(argv)


def canonical_profile_commands(
    repository_root: Path,
    *,
    skill_id: str,
    changed_paths: list[str],
) -> list[list[str]]:
    manifest = load_json(
        repository_root / "bundle-manifest.json", label="bundle manifest"
    )
    profiles = manifest.get("test_profiles") if isinstance(manifest, dict) else None
    if not isinstance(profiles, dict):
        raise OperationError("bundle manifest test profiles are missing")
    commands: list[str] = []
    for profile in ("quick", "extended"):
        for command in profiles.get(profile, []):
            if skill_id in command or (
                skill_id == "skill-evaluator" and "tests/test_" in command
            ):
                commands.append(command)
    for changed in changed_paths:
        if "/test" not in changed and not changed.startswith("tests/"):
            continue
        owners = [
            command
            for profile in ("quick", "extended")
            for command in profiles.get(profile, [])
            if changed in shlex.split(command)
        ]
        if not owners:
            raise OperationError(
                f"changed test has no canonical profile owner: {changed}"
            )
        commands.extend(owners)
    parsed: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for command in commands:
        words = shlex.split(command)
        environment: list[str] = []
        while words and "=" in words[0] and not words[0].startswith("-"):
            environment.append(words.pop(0))
        if set(environment) - {"PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=tests"}:
            raise OperationError(
                "canonical profile command has an unapproved environment override"
            )
        normalized = [*environment, *words]
        key = tuple(normalized)
        if key not in seen:
            seen.add(key)
            parsed.append(normalized)
    if not parsed:
        raise OperationError(
            f"Skill has no canonical Quick/Extended command: {skill_id}"
        )
    return parsed


def _run_profile_command(repository_root: Path, words: list[str]) -> dict[str, Any]:
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    while words and "=" in words[0]:
        name, value = words.pop(0).split("=", 1)
        environment[name] = value
    before = _git(repository_root, "status", "--porcelain=v1", "--untracked-files=all")
    started = time.monotonic()
    result = subprocess.run(
        words,
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        shell=False,
        env=environment,
    )
    if result.returncode:
        diagnostic = (result.stderr or result.stdout)[:MAX_DIAGNOSTIC_BYTES]
        raise OperationError(f"focused gate failed: {diagnostic.strip()}")
    after = _git(repository_root, "status", "--porcelain=v1", "--untracked-files=all")
    if before != after:
        raise OperationError("focused gate changed the frozen worktree inventory")
    return _operation_fact(
        "focused-" + sha256(canonical_bytes(words)).hexdigest()[:16],
        words,
        before,
        round((time.monotonic() - started) * 1000),
    )


def _manifest_versions(raw: bytes, *, label: str) -> dict[str, str]:
    value = strict_json_bytes(raw, label=label)
    skills = value.get("skills") if isinstance(value, dict) else None
    if not isinstance(skills, list):
        raise OperationError(f"{label} has no Skill version catalog")
    versions = {
        row.get("id"): row.get("version")
        for row in skills
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if set(versions) != set(SKILL_IDS) or any(
        not isinstance(version, str) for version in versions.values()
    ):
        raise OperationError(f"{label} does not contain exact four Skill versions")
    return versions


def _validate_candidate_version(
    repository_root: Path,
    *,
    base_commit: str,
    candidate_commit: str,
    owner_surface: str,
    root_cause_ids: list[str],
    changed_paths: list[str],
) -> str:
    base_blob = _git_blob(repository_root, base_commit, "bundle-manifest.json")
    candidate_blob = _git_blob(
        repository_root, candidate_commit, "bundle-manifest.json"
    )
    if base_blob is None or candidate_blob is None:
        raise OperationError("candidate version manifests are unavailable")
    base = _manifest_versions(base_blob, label="base Bundle manifest")
    candidate = _manifest_versions(candidate_blob, label="candidate Bundle manifest")
    for skill_id in SKILL_IDS:
        if skill_id != owner_surface and base[skill_id] != candidate[skill_id]:
            raise OperationError(
                f"candidate changes non-owner Skill version: {skill_id}"
            )
    try:
        base_version = tuple(int(part) for part in base[owner_surface].split("."))
        candidate_version = tuple(
            int(part) for part in candidate[owner_surface].split(".")
        )
    except ValueError as exc:
        raise OperationError(
            "candidate Skill version is not semantic versioning"
        ) from exc
    if len(base_version) != 3 or candidate_version != (
        base_version[0],
        base_version[1] + 1,
        0,
    ):
        raise OperationError(
            "candidate owner must receive exactly one minor version increment"
        )
    required_generated = {
        "bundle-manifest.json",
        "frontier-engineering.bundle.json",
        "evaluation/static-contract-diagnostic.json",
        "RELEASE_NOTES.md",
    }
    if not required_generated <= set(changed_paths):
        raise OperationError(
            "candidate version change lacks generated identity or Release Notes"
        )
    notes = _git(
        repository_root,
        "diff",
        "--unified=0",
        base_commit,
        candidate_commit,
        "--",
        "RELEASE_NOTES.md",
    )
    bullets = [
        line[1:].strip() for line in notes.splitlines() if line.startswith("+- ")
    ]
    if (
        len(bullets) != 1
        or candidate[owner_surface] not in bullets[0]
        or any(root_cause_id not in bullets[0] for root_cause_id in root_cause_ids)
    ):
        raise OperationError(
            "candidate Release Notes must add one versioned root-cause entry"
        )
    return candidate[owner_surface]


def _validate_candidate_file_modes(raw_diff: str) -> None:
    for line in raw_diff.splitlines():
        metadata = line.split("\t", 1)[0].split()
        if len(metadata) < 2 or not metadata[0].startswith(":"):
            raise OperationError("candidate raw diff is malformed")
        old_mode = metadata[0][1:]
        new_mode = metadata[1]
        if old_mode in {"120000", "160000"} or new_mode in {"120000", "160000"}:
            raise OperationError("candidate symlink or submodule changes are forbidden")
        if old_mode != "000000" and new_mode != "000000" and old_mode != new_mode:
            raise OperationError("candidate file mode or type changes are forbidden")


def candidate_source(
    *,
    repository_root: Path,
    campaign: dict[str, Any],
    sentinel: dict[str, Any],
    base_commit: str,
    candidate_commit: str,
    owner_surface: str,
    root_cause_ids: list[str],
    semantic_changes: list[str],
) -> dict[str, Any]:
    if campaign["candidate"] is not None or campaign["budgets"]["candidate_count"] != 0:
        raise OperationError("campaign already owns a candidate")
    if base_commit != campaign["product"]["source_commit"]:
        raise OperationError("candidate base differs from current product")
    if (
        not 1 <= len(semantic_changes) <= 4
        or len(set(semantic_changes)) != len(semantic_changes)
        or not root_cause_ids
        or len(set(root_cause_ids)) != len(root_cause_ids)
        or any(not SAFE_ID.fullmatch(item) for item in root_cause_ids)
    ):
        raise OperationError(
            "candidate requires unique safe root causes and one to four unique semantic changes"
        )
    identity = git_identity(repository_root, candidate_commit)
    if identity["commit"] != candidate_commit:
        raise OperationError("candidate commit did not resolve exactly")
    _git(repository_root, "merge-base", "--is-ancestor", base_commit, candidate_commit)
    if _git(repository_root, "rev-parse", "HEAD") != candidate_commit:
        raise OperationError("candidate commit must be the clean checked-out HEAD")
    summary = _git(
        repository_root,
        "diff",
        "--summary",
        "--find-renames",
        "--find-copies",
        base_commit,
        candidate_commit,
    )
    if " rename " in f" {summary} " or " copy " in f" {summary} ":
        raise OperationError("candidate rename or copy changes are forbidden")
    _validate_candidate_file_modes(
        _git(
            repository_root,
            "diff",
            "--raw",
            "--no-renames",
            base_commit,
            candidate_commit,
        )
    )
    changed_paths = sorted(
        line.split("\t", 1)[1]
        for line in _git(
            repository_root,
            "diff",
            "--name-status",
            "--no-renames",
            base_commit,
            candidate_commit,
        ).splitlines()
        if line
    )
    if not changed_paths:
        raise OperationError("candidate diff is empty")
    skill = sentinel["skills"].get(owner_surface)
    if skill is None:
        raise OperationError("candidate owner surface is not in the sentinel index")
    allowed_prefixes = {f"{owner_surface}/"}
    allowed_exact = {
        "bundle-manifest.json",
        "frontier-engineering.bundle.json",
        "evaluation/static-contract-diagnostic.json",
        "RELEASE_NOTES.md",
        "README.md",
    }
    for field in ("fixture_roots", "verifier_roots"):
        for binding in skill[field]:
            allowed_exact.add(binding["path"])
            allowed_prefixes.add(binding["path"].rstrip("/") + "/")
    forbidden = [
        path
        for path in changed_paths
        if path not in allowed_exact
        and not any(path.startswith(prefix) for prefix in allowed_prefixes)
    ]
    if forbidden:
        raise OperationError(f"candidate changes a non-owner path: {forbidden[0]}")
    _validate_candidate_version(
        repository_root,
        base_commit=base_commit,
        candidate_commit=candidate_commit,
        owner_surface=owner_surface,
        root_cause_ids=root_cause_ids,
        changed_paths=changed_paths,
    )
    operations: list[dict[str, Any]] = []
    for operation_id, script in (
        ("candidate-bundle-check", "bundle/build_bundle_manifest.py"),
        ("candidate-static-check", "scripts/evaluate_static_contracts.py"),
    ):
        fact, _ = run_model_free_command(
            operation_id,
            [sys.executable, script, "--check"],
            repository_root=repository_root,
        )
        operations.append(fact)
    for command in canonical_profile_commands(
        repository_root,
        skill_id=owner_surface,
        changed_paths=changed_paths,
    ):
        operations.append(_run_profile_command(repository_root, list(command)))
    return {
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
        "candidate_tree": identity["tree"],
        "changed_paths": changed_paths,
        "root_cause_ids": sorted(set(root_cause_ids)),
        "owner_surface": owner_surface,
        "skills": {
            skill_id: bundle_skill_at_revision(
                repository_root,
                candidate_commit,
                skill_id,
            )
            for skill_id in SKILL_IDS
        },
        "semantic_changes": semantic_changes,
        "operations": operations,
    }
