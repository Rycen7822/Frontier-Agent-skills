"""Prepare Skill calibration workspaces and close pre-turn Host failures."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from typing import Any

from _model_evolution_contract import (
    SKILL_IDS,
    canonical_bytes,
    load_json,
    make_binding,
    pre_turn_failure_identity,
    resolve_binding,
    validate_document,
    verify_self_hash,
    with_self_hash,
)


class CalibrationPreparationError(ValueError):
    """Calibration preparation is not legal or reproducible."""


def _write_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != payload:
            raise CalibrationPreparationError(
                f"refusing to replace different calibration bytes: {path}",
            )
        return
    with path.open("xb") as handle:
        handle.write(payload)


def _bound_timeout(host: dict[str, Any]) -> float:
    argv = host["command"]["argv"]
    positions = [index for index, item in enumerate(argv) if item == "--timeout"]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        raise CalibrationPreparationError("Host command lacks one timeout")
    try:
        value = float(argv[positions[0] + 1])
    except ValueError as exc:
        raise CalibrationPreparationError("Host timeout is invalid") from exc
    if value <= 0:
        raise CalibrationPreparationError("Host timeout must be positive")
    return value


def _materialize_skill(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    sentinel: dict[str, Any],
    host: dict[str, Any],
    skill_id: str,
    as_of: str,
) -> dict[str, Path]:
    record = sentinel["skills"][skill_id]
    template_path = resolve_binding(
        record["spec_template"], repository_root, campaign_root,
    )
    labels_path = resolve_binding(
        record["calibration_gold"], repository_root, campaign_root,
    )
    template = load_json(template_path, label=f"{skill_id} spec template")
    labels = [
        json.loads(line)
        for line in labels_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model_graders = [item for item in template["graders"] if item["type"] == "model"]
    if len(model_graders) != 1 or len(labels) != record["calibration_request_ceiling"]:
        raise CalibrationPreparationError(
            f"{skill_id} grader or calibration cardinality differs",
        )
    execution = host["identity"]["execution"]
    root = campaign_root / "calibration" / skill_id
    copied = {
        "host.json": resolve_binding(
            campaign["profiles"]["target_observed"], repository_root, campaign_root,
        ),
        "grader-prompt.md": template_path.parent / model_graders[0]["prompt"]["path"],
        "grader-output.schema.json": (
            template_path.parent / model_graders[0]["output_schema"]["path"]
        ),
        "scenarios.public.jsonl": resolve_binding(
            record["public_scenarios"], repository_root, campaign_root,
        ),
        "suite-quality.json": template_path.parent / template["suite"]["quality"]["path"],
    }
    for name, source in copied.items():
        _write_exact(root / name, source.read_bytes())

    spec = copy.deepcopy(template)
    spec["execution"]["as_of"] = as_of
    spec["subject"]["claimed_hosts"] = [host["identity"]["host_id"]]
    spec["host"]["manifest"] = {
        "path": "host.json",
        "sha256": campaign["profiles"]["target_observed"]["sha256"],
    }
    grader = next(item for item in spec["graders"] if item["type"] == "model")
    grader["model"] = execution["model"]
    for row in labels:
        row["host"] = host["identity"]["host_id"]
        row["model"] = execution["model"]
    _write_exact(root / "spec.json", canonical_bytes(spec))
    _write_exact(
        root / "calibration-gold.jsonl",
        b"".join(canonical_bytes(row) + b"\n" for row in labels),
    )
    return {
        "root": root,
        "spec": root / "spec.json",
        "labels": root / "calibration-gold.jsonl",
        "host": root / "host.json",
        "ratings": root / "run/calibration-ratings.jsonl",
        "calibration": root / "grader-calibration.json",
    }


def prepare_calibrations(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    as_of: str,
    created: str,
    expires: str,
    max_workers: int,
) -> dict[str, Any]:
    if campaign["phase"] != "target_profile_ready":
        raise CalibrationPreparationError(
            "calibration preparation requires target_profile_ready",
        )
    if not 1 <= max_workers <= 4:
        raise CalibrationPreparationError("calibration workers must be between 1 and 4")
    sentinel = load_json(
        resolve_binding(campaign["sentinel_index"], repository_root, campaign_root),
        label="sentinel index",
    )
    host = load_json(
        resolve_binding(
            campaign["profiles"]["target_observed"],
            repository_root,
            campaign_root,
        ),
        label="target observed Host",
    )
    host_timeout = _bound_timeout(host)
    runner = repository_root / "skill-evaluator/scripts/run_model_calibration.py"
    validator = repository_root / "skill-evaluator/scripts/validate_eval_suite.py"
    controller = repository_root / "scripts/model_evolution.py"
    commands = []
    for offset, skill_id in enumerate(SKILL_IDS):
        paths = _materialize_skill(
            repository_root=repository_root,
            campaign_root=campaign_root,
            campaign=campaign,
            sentinel=sentinel,
            host=host,
            skill_id=skill_id,
            as_of=as_of,
        )
        run = [
            sys.executable,
            str(runner),
            "--spec", str(paths["spec"]),
            "--labels", str(paths["labels"]),
            "--host", str(paths["host"]),
            "--output-dir", str(paths["root"] / "run"),
            "--created", created,
            "--expires", expires,
            "--expected-requests",
            str(sentinel["skills"][skill_id]["calibration_request_ceiling"]),
            "--host-timeout", str(host_timeout),
            "--max-workers", str(max_workers),
        ]
        validate = [
            sys.executable,
            str(validator),
            "calibration",
            "--spec", str(paths["spec"]),
            "--ratings", str(paths["ratings"]),
            "--labels", str(paths["labels"]),
            "--output", str(paths["calibration"]),
        ]
        record = [
            sys.executable,
            str(controller),
            "--repository-root", str(repository_root),
            "--campaign-root", str(campaign_root),
            "record",
            "--expected-revision", str(campaign["state_revision"] + offset),
            "--role", "grader_calibration",
            "--skill-id", skill_id,
            "--artifact", str(paths["calibration"]),
        ]
        commands.append({
            "skill_id": skill_id,
            "request_count": sentinel["skills"][skill_id][
                "calibration_request_ceiling"
            ],
            "run": run,
            "validate": validate,
            "record": record,
        })
    preparation = with_self_hash(
        {
            "schema_version": "model-evolution-calibration-preparation/1",
            "campaign_id": campaign["campaign_id"],
            "campaign_hash": campaign["campaign_hash"],
            "state_revision": campaign["state_revision"],
            "as_of": as_of,
            "created": created,
            "expires": expires,
            "commands": commands,
        },
        "preparation_hash",
    )
    _write_exact(
        campaign_root / "calibration/preparation.json",
        canonical_bytes(preparation),
    )
    return preparation


def close_calibration_failure(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    output: Path,
) -> dict[str, Any]:
    """Bind a complete pre-turn Host failure batch without replaying requests."""
    if skill_id not in SKILL_IDS:
        raise CalibrationPreparationError("failure receipt Skill is unknown")
    expected_output = campaign_root / f"calibration/failure-{skill_id}.json"
    if output != expected_output:
        raise CalibrationPreparationError("failure receipt output path is not canonical")

    qualification_path = campaign_root / "qualification/qualification.json"
    qualification = load_json(qualification_path, label="qualification")
    validate_document(qualification, "qualification")
    if (
        qualification["decision"] != "blocked"
        or qualification["campaign_hash"] != campaign["campaign_hash"]
    ):
        raise CalibrationPreparationError("campaign is not closed as blocked")

    preparation_path = campaign_root / "calibration/preparation.json"
    preparation = load_json(preparation_path, label="calibration preparation")
    if (
        preparation.get("schema_version")
        != "model-evolution-calibration-preparation/1"
        or preparation.get("campaign_hash") != campaign["campaign_hash"]
        or preparation.get("state_revision") != campaign["state_revision"]
    ):
        raise CalibrationPreparationError("calibration preparation identity differs")
    verify_self_hash(preparation, "preparation_hash")
    commands = [
        row for row in preparation.get("commands", [])
        if row.get("skill_id") == skill_id
    ]
    if len(commands) != 1:
        raise CalibrationPreparationError("calibration preparation command is ambiguous")
    request_count = commands[0].get("request_count")
    if not isinstance(request_count, int) or not 1 <= request_count <= 64:
        raise CalibrationPreparationError("calibration request count is invalid")

    terminal_root = campaign_root / f"calibration/{skill_id}/run/terminals"
    expected_names = {f"{index:03d}" for index in range(1, request_count + 1)}
    if terminal_root.is_symlink() or not terminal_root.is_dir():
        raise CalibrationPreparationError("calibration terminal root is invalid")
    children = list(terminal_root.iterdir())
    if (
        {child.name for child in children} != expected_names
        or any(child.is_symlink() or not child.is_dir() for child in children)
    ):
        raise CalibrationPreparationError("calibration terminal set is incomplete")

    outcomes = {"timeout": 0, "failed": 0}
    requests: list[dict[str, Any]] = []
    request_hashes: set[str] = set()
    for ordinal in range(request_count):
        root = terminal_root / f"{ordinal + 1:03d}"
        stdout_path = root / "host-stdout.jsonl"
        stderr_path = root / "host-stderr.txt"
        if any(
            path.is_symlink() or not path.is_file()
            for path in (stdout_path, stderr_path)
        ):
            raise CalibrationPreparationError("calibration Host evidence is missing")
        try:
            identity = pre_turn_failure_identity(stdout_path, ordinal)
        except ValueError as exc:
            raise CalibrationPreparationError(str(exc)) from exc
        if identity["request_hash"] in request_hashes:
            raise CalibrationPreparationError("Host request hash is duplicated")
        request_hashes.add(identity["request_hash"])
        outcomes[identity["terminal_status"]] += 1
        requests.append({
            **identity,
            "host_result": make_binding(
                stdout_path,
                root="campaign",
                repository_root=repository_root,
                campaign_root=campaign_root,
            ),
            "host_stderr": make_binding(
                stderr_path,
                root="campaign",
                repository_root=repository_root,
                campaign_root=campaign_root,
            ),
        })

    receipt = with_self_hash({
        "schema_version": "model-evolution-failure-receipt/1",
        "campaign_hash": campaign["campaign_hash"],
        "qualification": make_binding(
            qualification_path,
            root="campaign",
            repository_root=repository_root,
            campaign_root=campaign_root,
        ),
        "preparation": make_binding(
            preparation_path,
            root="campaign",
            repository_root=repository_root,
            campaign_root=campaign_root,
        ),
        "skill_id": skill_id,
        "request_kind": "model_grade",
        "classification": "host_failed_before_completed_turn",
        "request_count": request_count,
        "outcomes": outcomes,
        "requests": requests,
    }, "failure_receipt_hash")
    validate_document(receipt, "failure_receipt")
    payload = canonical_bytes(receipt) + b"\n"
    _write_exact(output, payload)
    persisted = load_json(output, label="failed-request receipt")
    validate_document(persisted, "failure_receipt")
    if canonical_bytes(persisted) + b"\n" != payload:
        raise CalibrationPreparationError("failure receipt serialization differs")
    return persisted
