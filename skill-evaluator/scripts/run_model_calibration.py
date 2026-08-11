#!/usr/bin/env python3
"""Run one selected model grader over a frozen blinded calibration corpus."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any

from evidence_io import (
    atomic_write_json,
    atomic_write_jsonl,
    canonical_json_bytes,
    file_sha256,
    load_json,
    load_jsonl_objects,
)
import model_grade_transport as transport
from validate_eval_suite import (
    load_epoch6_schema_registry,
    validate_host_protocol_record,
    validate_epoch6_schema,
)


class CalibrationFailure(RuntimeError):
    """A deterministic input, protocol, lifecycle, or output failure."""


def _utc(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc,
        )
    except (TypeError, ValueError) as exc:
        raise CalibrationFailure("calibration time is not RFC 3339 seconds") from exc


def _thresholds(spec: dict[str, Any]) -> dict[str, int | float]:
    gates = [
        gate for gate in spec["hard_gates"]
        if gate.get("kind") == "calibration" and gate.get("required") is True
    ]
    thresholds = {
        gate["metric"]: gate["threshold"]
        for gate in gates
    }
    if (
        len(gates) != 2
        or set(thresholds) != {"minimum_agreement", "minimum_examples"}
        or any(gate.get("direction") != "at_least" for gate in gates)
    ):
        raise CalibrationFailure("calibration threshold contract differs")
    return thresholds


def _preflight_labels(
    spec: dict[str, Any],
    grader: dict[str, Any],
    host: dict[str, Any],
    labels: list[dict[str, Any]],
    created: str,
    expires: str,
) -> None:
    execution = host["identity"]["execution"]
    checks = {item["check_id"]: item for item in grader["checks"]}
    items = [transport.calibration_item(row) for row in labels]
    if (
        len({item["item_id"] for item in items}) != len(items)
        or grader["model"] != execution["model"]
        or any(
            row["model"] != grader["model"]
            or row["host"] != host["identity"]["host_id"]
            or row["check_id"] not in checks
            or row["dimension"] != checks[row["check_id"]]["dimension"]
            or row["payload"]["check"]["pass_condition"]
            != checks[row["check_id"]]["pass_condition"]
            or row["risk"] != spec["risk_tier"]
            for row in labels
        )
    ):
        raise CalibrationFailure("calibration labels differ from spec, model, or Host")
    required_classes = {"known_good", "known_bad", "boundary", "abstain"}
    if any(
        not required_classes <= {
            row["class"] for row in labels if row["check_id"] == check_id
        }
        for check_id in checks
    ):
        raise CalibrationFailure("calibration class coverage differs")
    if not _utc(created) <= _utc(spec["execution"]["as_of"]) < _utc(expires):
        raise CalibrationFailure("calibration validity window excludes spec as_of")
    _thresholds(spec)


def _first_diagnostic(items: list[dict[str, str]]) -> str:
    item = items[0]
    return f"{item['code']} {item['path']}: {item['message']}"


def _host_command(host: dict[str, Any], root: Path) -> tuple[list[str], dict[str, str]]:
    command = host["command"]
    executable = Path(command["resolved_executable"])
    if (
        not executable.is_absolute()
        or not executable.is_file()
        or executable.is_symlink()
        or file_sha256(executable) != command["executable_digest"]
    ):
        raise CalibrationFailure("Host executable identity differs")
    declared = command["argv"]
    declared_executable = Path(declared[0])
    if declared_executable.is_absolute():
        declared_resolution = declared_executable.resolve()
    elif len(declared_executable.parts) == 1:
        declared_resolution = (executable.parent / declared[0]).resolve()
    else:
        raise CalibrationFailure("Host argv[0] is not safely resolvable")
    if declared_resolution != executable.resolve():
        raise CalibrationFailure("Host argv[0] differs from its executable")
    argv = [str(executable.resolve())]
    for argument in declared[1:]:
        candidate = root / argument
        argv.append(str(candidate.resolve()) if candidate.is_file() else argument)
    repository_scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(repository_scripts) not in sys.path:
        sys.path.insert(0, str(repository_scripts))
    from _codex_eval_delivery import DeliveryError, project_command_environment

    try:
        environment = project_command_environment(command, dict(os.environ))
    except DeliveryError as exc:
        raise CalibrationFailure(str(exc)) from exc
    return argv, environment


def _invoke(
    argv: list[str],
    environment: dict[str, str],
    request: dict[str, Any],
    workspace: Path,
    timeout: float,
) -> tuple[int, bytes, bytes]:
    process = subprocess.Popen(
        argv,
        cwd=workspace,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            canonical_json_bytes(request) + b"\n",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        raise CalibrationFailure("Host exceeded the calibration outer timeout")
    return process.returncode, stdout, stderr


def _host_result(
    raw: bytes,
    request: dict[str, Any],
    registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    try:
        for line in raw.decode("utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationFailure("Host output is not valid JSONL") from exc
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise CalibrationFailure("model-grade Host must emit one terminal result")
    result = rows[0]
    diagnostics = validate_host_protocol_record("host_result", result, registry)
    if diagnostics:
        raise CalibrationFailure(_first_diagnostic(diagnostics))
    if (
        result.get("envelope") != request["envelope"]
        or result.get("terminal") is not True
        or result.get("terminal_status") != "completed"
    ):
        raise CalibrationFailure("model-grade Host did not complete the bound request")
    return result


def _judgment(result: dict[str, Any], workspace: Path) -> dict[str, Any]:
    artifacts = result.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 1:
        raise CalibrationFailure("model-grade Host artifact cardinality differs")
    record = artifacts[0]
    prefix = "workspace/"
    if not isinstance(record.get("path"), str) or not record["path"].startswith(prefix):
        raise CalibrationFailure("model-grade Host artifact path differs")
    path = workspace / record["path"][len(prefix):]
    if not path.is_file() or file_sha256(path) != record.get("digest"):
        raise CalibrationFailure("model-grade Host artifact binding differs")
    value = load_json(path)
    if not isinstance(value, dict):
        raise CalibrationFailure("model-grade judgment is not an object")
    return value


def _request(
    *,
    spec: dict[str, Any],
    grader: dict[str, Any],
    label: dict[str, Any],
    position: int,
    prompt_bytes: bytes,
) -> tuple[dict[str, Any], dict[str, Any]]:
    item = transport.calibration_item(label)
    batch_id = f"batch.calibration.{position}"
    batch = transport.execution_batch([item], batch_id=batch_id)
    payload = transport.request_payload(
        grader_id=grader["grader_id"],
        batch=batch,
        schedule_id=grader["batch_schedule_id"],
        prompt_bytes=prompt_bytes,
        prompt_id=grader["prompt_id"],
        schema_id=grader["schema_id"],
    )
    run_id = label["example_id"]
    attempt_id = f"attempt.{position}"
    request = {
        "record_type": "skill-evaluator-host-request/2",
        "envelope": {
            "plan_id": spec["evaluation_id"],
            "entry_ordinal": position - 1,
            "entry_id": label["example_id"],
            "run_id": run_id,
            "attempt_id": attempt_id,
            "attempt": 1,
            "request_id": f"request.{position}.model-grade",
            "request_kind": "model_grade",
        },
        "payload": payload,
    }
    return request, batch


def _project_terminal(
    *,
    request: dict[str, Any],
    batch: dict[str, Any],
    label: dict[str, Any],
    position: int,
    result: dict[str, Any],
    terminal_root: Path,
) -> dict[str, Any]:
    judgment = _judgment(result, terminal_root)
    transport.normalize_judgment(
        judgment,
        batch=batch,
        requirements=[{"check_id": label["check_id"], "required": True}],
        item_id=label["example_id"],
    )
    check = judgment["items"][0]["checks"][0]
    projected_label, severity = transport.calibration_projection(check)
    return {
        "schema_version": "model-calibration-terminal/2",
        "position": position,
        "example_id": label["example_id"],
        "check_id": label["check_id"],
        "request_id": request["envelope"]["request_id"],
        "label": projected_label,
        "severity": severity,
        "uncertainty": check["uncertainty"],
        "notes": check["notes"],
    }


def _terminal(
    *,
    output_root: Path,
    spec: dict[str, Any],
    grader: dict[str, Any],
    label: dict[str, Any],
    position: int,
    prompt_bytes: bytes,
    argv: list[str],
    environment: dict[str, str],
    registry: dict[str, dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    terminal_root = output_root / "terminals" / f"{position:03d}"
    terminal_path = terminal_root / "terminal.json"
    request, batch = _request(
        spec=spec,
        grader=grader,
        label=label,
        position=position,
        prompt_bytes=prompt_bytes,
    )
    diagnostics = validate_host_protocol_record("host_request", request, registry)
    if diagnostics:
        raise CalibrationFailure(_first_diagnostic(diagnostics))
    if terminal_path.is_file():
        terminal = load_json(terminal_path)
        stdout_path = terminal_root / "host-stdout.jsonl"
        stderr_path = terminal_root / "host-stderr.txt"
        if not stdout_path.is_file() or not stderr_path.is_file():
            raise CalibrationFailure(f"terminal {position} raw evidence is partial")
        result = _host_result(stdout_path.read_bytes(), request, registry)
        expected = _project_terminal(
            request=request,
            batch=batch,
            label=label,
            position=position,
            result=result,
            terminal_root=terminal_root,
        )
        if terminal != expected:
            raise CalibrationFailure(f"terminal {position} projection differs")
        return terminal
    if terminal_root.exists():
        raise CalibrationFailure(
            f"terminal {position} is partial; refusing an unprovable replay",
    )
    terminal_root.mkdir(parents=True)
    code, stdout, stderr = _invoke(
        argv, environment, request, terminal_root, timeout,
    )
    (terminal_root / "host-stdout.jsonl").write_bytes(stdout)
    (terminal_root / "host-stderr.txt").write_bytes(stderr)
    if code:
        raise CalibrationFailure(f"model-grade Host exited {code}")
    result = _host_result(stdout, request, registry)
    terminal = _project_terminal(
        request=request,
        batch=batch,
        label=label,
        position=position,
        result=result,
        terminal_root=terminal_root,
    )
    atomic_write_json(terminal_path, terminal)
    return terminal


def _preflight_terminal_roots(
    output_root: Path,
    spec: dict[str, Any],
    grader: dict[str, Any],
    labels: list[dict[str, Any]],
    prompt_bytes: bytes,
) -> None:
    """Reject every partial or corrupt prior slot before starting a worker."""
    for position, label in enumerate(labels, 1):
        root = output_root / "terminals" / f"{position:03d}"
        if not root.exists():
            continue
        terminal_path = root / "terminal.json"
        if not terminal_path.is_file():
            raise CalibrationFailure(
                f"terminal {position} is partial; refusing an unprovable replay",
            )
        terminal = load_json(terminal_path)
        if not isinstance(terminal, dict):
            raise CalibrationFailure(f"terminal {position} is not an object")
        request, _ = _request(
            spec=spec,
            grader=grader,
            label=label,
            position=position,
            prompt_bytes=prompt_bytes,
        )
        expected = {
            "position": position,
            "example_id": label["example_id"],
            "check_id": label["check_id"],
            "request_id": request["envelope"]["request_id"],
        }
        if any(terminal.get(key) != value for key, value in expected.items()):
            raise CalibrationFailure(f"terminal {position} identity differs")


def _ratings(
    *,
    spec: dict[str, Any],
    grader: dict[str, Any],
    host: dict[str, Any],
    labels_path: Path,
    labels: list[dict[str, Any]],
    terminals: list[dict[str, Any]],
    created: str,
    expires: str,
) -> list[dict[str, Any]]:
    thresholds = _thresholds(spec)
    execution = host["identity"]["execution"]
    evidence_binding = {
        "path": labels_path.name,
        "digest": file_sha256(labels_path),
    }
    reviewer = {
        "reviewer_id": "selected-model-grader",
        "role": "judge",
        "authority": "calibration-owner",
        "principal_id": "selected-model-grader-principal",
        "blinded": True,
    }
    grader_identity = {
        "grader_id": grader["grader_id"],
        "model": execution["model"],
        "model_revision": execution["model_revision"],
        "prompt_id": grader["prompt_id"],
        "schema_id": grader["schema_id"],
    }
    execution_profile = {
        "host_id": host["identity"]["host_id"],
        "host_version": host["identity"]["host_version"],
        "harness": execution["harness"],
        "harness_version": execution["harness_version"],
        "model_genealogy": [execution["model"]],
        "context_exposure": [],
        "evidence_sources": [evidence_binding],
    }
    independence = {
        "candidate_principal_id": "target-executor-principal",
        "grader_principal_id": reviewer["principal_id"],
        "context_mode": "fresh",
        "rationale_exposed": False,
        "candidate_model_genealogy": [execution["model"]],
        "grader_model_genealogy": [execution["model"]],
        "candidate_evidence_source_ids": ["calibration-labels"],
        "grader_evidence_source_ids": ["calibration-labels"],
    }
    ordering = {
        "method": "counterbalanced",
        "seed": spec["suite"]["order_seed"],
        "schedule_id": grader["batch_schedule_id"],
    }
    drift = [
        {
            "field": "prompt_id",
            "expected": grader["prompt_id"],
            "observed": grader["prompt_id"],
            "status": "unchanged",
        },
        {
            "field": "host_version",
            "expected": host["identity"]["host_version"],
            "observed": host["identity"]["host_version"],
            "status": "unchanged",
        },
    ]
    return [
        {
            "schema_version": 3,
            "rating_id": f"rating.{position}",
            "example_id": label["example_id"],
            "grader_id": grader["grader_id"],
            "dimension": label["dimension"],
            "check_id": label["check_id"],
            "label": terminal["label"],
            "severity": terminal["severity"],
            "position": position,
            "blinded_treatment_labels": True,
            "reviewer": reviewer,
            "grader_identity": grader_identity,
            "execution_profile": execution_profile,
            "independence_facts": independence,
            "ordering": ordering,
            "created": created,
            "expires": expires,
            "drift_triggers": drift,
            "adjudication_policy": "frozen gold owner",
            "thresholds": thresholds,
        }
        for position, (label, terminal) in enumerate(
            zip(labels, terminals, strict=True), 1,
        )
    ]


def run(args: argparse.Namespace) -> None:
    spec_path = args.spec.resolve(strict=True)
    labels_path = args.labels.resolve(strict=True)
    host_path = args.host.resolve(strict=True)
    output_root = args.output_dir.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    spec = load_json(spec_path)
    host = load_json(host_path)
    labels = [row for _, row in load_jsonl_objects(labels_path)]
    registry = load_epoch6_schema_registry()
    diagnostics = validate_epoch6_schema(spec, "eval-spec-v6.schema.json", registry)
    if diagnostics:
        raise CalibrationFailure(_first_diagnostic(diagnostics))
    diagnostics = validate_epoch6_schema(host, "host-manifest-v2.schema.json", registry)
    if diagnostics:
        raise CalibrationFailure(_first_diagnostic(diagnostics))
    graders = [item for item in spec["graders"] if item["type"] == "model"]
    if len(graders) != 1 or len(labels) != args.expected_requests:
        raise CalibrationFailure("calibration grader or request count differs")
    grader = graders[0]
    _preflight_labels(spec, grader, host, labels, args.created, args.expires)
    prompt_path = spec_path.parent / grader["prompt"]["path"]
    prompt_bytes = prompt_path.read_bytes()
    argv, environment = _host_command(host, spec_path.parent)
    timeout = args.host_timeout + 30
    _preflight_terminal_roots(
        output_root, spec, grader, labels, prompt_bytes,
    )
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = [
            pool.submit(
                _terminal,
                output_root=output_root,
                spec=spec,
                grader=grader,
                label=label,
                position=position,
                prompt_bytes=prompt_bytes,
                argv=argv,
                environment=environment,
                registry=registry,
                timeout=timeout,
            )
            for position, label in enumerate(labels, 1)
        ]
        terminals = [future.result() for future in futures]
    ratings = _ratings(
        spec=spec,
        grader=grader,
        host=host,
        labels_path=labels_path,
        labels=labels,
        terminals=terminals,
        created=args.created,
        expires=args.expires,
    )
    ratings_path = output_root / "calibration-ratings.jsonl"
    payload = b"".join(canonical_json_bytes(row) + b"\n" for row in ratings)
    if ratings_path.exists():
        if ratings_path.read_bytes() != payload:
            raise CalibrationFailure("refusing to overwrite different ratings")
    else:
        atomic_write_jsonl(ratings_path, ratings)
    print(json.dumps({
        "evaluation_id": spec["evaluation_id"],
        "requests": len(terminals),
        "ratings": str(ratings_path),
        "status": "complete",
    }, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--host", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--created", required=True)
    parser.add_argument("--expires", required=True)
    parser.add_argument("--expected-requests", type=int, required=True)
    parser.add_argument("--host-timeout", type=float, required=True)
    parser.add_argument("--max-workers", type=int, choices=range(1, 5), default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        run(_parser().parse_args(argv))
        return 0
    except (CalibrationFailure, OSError, ValueError) as exc:
        print(f"run_model_calibration: {exc}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
