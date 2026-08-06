"""Systemd job commands and lifecycle preflight for model evolution."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import sys
import tempfile
import time

from _model_evolution_ops import OperationError, _operation_fact, _run


def _validate_unit(unit: str) -> None:
    if not unit or not all(
        character.isalnum() or character in "_.-" for character in unit
    ):
        raise OperationError("systemd unit name is unsafe")


def systemd_probe_argv(unit: str, completion_file: Path) -> list[str]:
    _validate_unit(unit)
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


def verify_systemd_user(
    campaign_id: str, env_allowlist: list[str],
) -> dict[str, object]:
    state = _run(
        ["systemctl", "--user", "is-system-running"],
        cwd=Path.cwd(),
        timeout=30,
    ).stdout.strip()
    if state != "running":
        raise OperationError("systemd user manager is not running")
    manager_lines = _run(
        ["systemctl", "--user", "show-environment"],
        cwd=Path.cwd(),
        timeout=30,
    ).stdout.splitlines()
    manager_environment = dict(
        line.split("=", 1) for line in manager_lines if "=" in line
    )
    for name in env_allowlist:
        expected = os.environ.get(name)
        if expected and manager_environment.get(name) != expected:
            raise OperationError(f"systemd user environment differs for {name}")
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


def render_runner_command(
    plan: Path,
    index: Path,
    *,
    attempt_budget: int,
    service_id: str,
    repository_root: Path,
    resume: bool = False,
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
    ]
    if resume:
        argv.append("--resume")
    argv.extend(["--new-attempt-budget", str(attempt_budget)])
    return shlex.join(argv)


def render_probe_command(
    *,
    repository_root: Path,
    campaign_root: Path,
    expected_revision: int,
    budget_approval: Path,
    service_id: str,
) -> str:
    _validate_unit(service_id)
    if (
        not repository_root.is_absolute()
        or not campaign_root.is_absolute()
        or not budget_approval.is_absolute()
    ):
        raise OperationError("probe job paths must be absolute")
    if isinstance(expected_revision, bool) or expected_revision < 0:
        raise OperationError("probe job revision is invalid")
    return shlex.join(
        [
            "systemd-run",
            "--user",
            "--unit",
            service_id,
            "--collect",
            f"--working-directory={repository_root}",
            sys.executable,
            "scripts/model_evolution.py",
            "--repository-root",
            str(repository_root),
            "--campaign-root",
            str(campaign_root),
            "probe",
            "--expected-revision",
            str(expected_revision),
            "--budget-approval",
            str(budget_approval),
        ]
    )
