"""Account for completed model-grade turns rejected by calibration thresholds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _model_evolution_contract import (
    ContractError,
    SKILL_IDS,
    canonical_bytes,
    load_json,
    load_jsonl,
    make_binding,
    resolve_binding,
    strict_json_bytes,
    validate_document,
)
from _model_evolution_qualification import validate_qualification


class CalibrationReceiptError(ValueError):
    """A completed calibration receipt is invalid or cannot be materialized."""


def _write_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.is_symlink() or path.read_bytes() != payload:
            raise CalibrationReceiptError(
                f"refusing to replace different calibration receipt bytes: {path}",
            )
        return
    with path.open("xb") as handle:
        handle.write(payload)


def _verify_preparation_lineage(
    campaign: dict[str, Any],
    preparation: dict[str, Any],
) -> None:
    """Prove that only successful calibration records followed preparation."""
    commands = {
        row.get("skill_id"): row.get("request_count")
        for row in preparation.get("commands", [])
        if isinstance(row, dict)
    }
    recorded = [
        skill_id
        for skill_id in SKILL_IDS
        if campaign["skill_evidence"][skill_id]["grader_calibration"] is not None
    ]
    prepared_revision = preparation.get("state_revision")
    if (
        preparation.get("campaign_id") != campaign.get("campaign_id")
        or not isinstance(prepared_revision, int)
        or (recorded and campaign.get("phase") != "target_profile_ready")
        or campaign.get("state_revision") != prepared_revision + len(recorded)
        or any(not isinstance(commands.get(skill_id), int) for skill_id in recorded)
    ):
        raise CalibrationReceiptError("campaign calibration lineage differs")

    if preparation.get("schema_version") != "model-evolution-calibration-preparation/2":
        raise CalibrationReceiptError("calibration preparation schema differs")


def _completed_identity(
    host_result_path: Path,
    terminal_path: Path,
    ordinal: int,
) -> dict[str, Any]:
    if (
        host_result_path.is_symlink()
        or terminal_path.is_symlink()
        or not host_result_path.is_file()
        or not terminal_path.is_file()
    ):
        raise ContractError("calibration result must use regular non-symlink files")
    lines = [line for line in host_result_path.read_bytes().splitlines() if line.strip()]
    if len(lines) != 1:
        raise ContractError("Host result must contain one record")
    result = strict_json_bytes(lines[0], label="Host result")
    terminal = load_json(terminal_path, label="calibration terminal")
    envelope = result.get("envelope") if isinstance(result, dict) else None
    cleanup = result.get("cleanup") if isinstance(result, dict) else None
    attempts = terminal.get("attempts") if isinstance(terminal, dict) else None
    expected_request = f"request.{ordinal + 1}.{attempts}.model-grade"
    if (
        not isinstance(result, dict)
        or result.get("record_type") != "skill-evaluator-host-result/2"
        or not isinstance(envelope, dict)
        or envelope.get("entry_ordinal") != ordinal
        or envelope.get("request_kind") != "model_grade"
        or result.get("terminal") is not True
        or result.get("terminal_status") != "completed"
        or result.get("protocol_error") is not None
        or result.get("treatment_error") is not None
        or result.get("timeout") is not False
        or result.get("refusal") is not False
        or not isinstance(cleanup, dict)
        or cleanup.get("status") != "clean"
        or not isinstance(terminal, dict)
        or terminal.get("schema_version") != "model-calibration-terminal/3"
        or attempts not in {1, 2}
        or envelope.get("attempt") != attempts
        or envelope.get("attempt_id") != f"attempt.{ordinal + 1}.{attempts}"
        or envelope.get("request_id") != expected_request
    ):
        raise ContractError("Host result is not a clean completed model-grade turn")
    identity = {
        "entry_ordinal": ordinal,
        "entry_id": envelope.get("entry_id"),
        "request_id": envelope.get("request_id"),
        "check_id": terminal.get("check_id"),
        "terminal_status": "completed",
    }
    if (
        terminal.get("example_id") != identity["entry_id"]
        or terminal.get("position") != ordinal + 1
        or terminal.get("request_id") != identity["request_id"]
        or any(
            not isinstance(identity[field], str)
            for field in ("entry_id", "request_id", "check_id")
        )
    ):
        raise ContractError("completed model-grade identity differs")
    return identity


def _capacity_retry_identity(path: Path, ordinal: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise ContractError("calibration retry Host result is missing")
    lines = [line for line in path.read_bytes().splitlines() if line.strip()]
    result = (
        strict_json_bytes(lines[0], label="calibration retry Host result")
        if len(lines) == 1
        else None
    )
    envelope = result.get("envelope") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("record_type") != "skill-evaluator-host-result/2"
        or result.get("terminal") is not True
        or not isinstance(envelope, dict)
        or envelope.get("entry_ordinal") != ordinal
        or envelope.get("request_kind") != "model_grade"
        or envelope.get("attempt") != 1
        or envelope.get("attempt_id") != f"attempt.{ordinal + 1}.1"
        or envelope.get("request_id") != f"request.{ordinal + 1}.1.model-grade"
        or result.get("terminal_status") != "failed"
        or result.get("failure_class") != "official_transient"
        or result.get("provider_error_code") != "model_at_capacity"
        or result.get("timeout") is not False
        or result.get("artifacts") != []
        or result.get("actions") != []
        or result.get("state") != []
    ):
        raise ContractError("calibration retry is not capacity-bound")


def calibration_attempt_count(
    campaign_root: Path,
    skill_id: str,
    request_count: int,
) -> int:
    """Count completed calibration calls through receipt-owned evidence."""
    terminal_root = campaign_root / f"calibration/{skill_id}/run/terminals"
    expected_names = {f"{index:03d}" for index in range(1, request_count + 1)}
    children = list(terminal_root.iterdir()) if terminal_root.is_dir() else []
    if (
        terminal_root.is_symlink()
        or {path.name for path in children} != expected_names
        or any(path.is_symlink() or not path.is_dir() for path in children)
    ):
        raise CalibrationReceiptError("calibration terminal set is incomplete")
    attempts = 0
    for ordinal in range(request_count):
        root = terminal_root / f"{ordinal + 1:03d}"
        terminal_path = root / "terminal.json"
        _completed_identity(root / "host-stdout.jsonl", terminal_path, ordinal)
        terminal = load_json(terminal_path, label="calibration terminal")
        attempt_count = terminal["attempts"]
        if attempt_count == 2:
            retry = root / "attempt-0001"
            stderr = retry / "host-stderr.txt"
            if (
                retry.is_symlink()
                or not retry.is_dir()
                or {path.name for path in retry.iterdir()}
                != {"host-stdout.jsonl", "host-stderr.txt"}
                or stderr.is_symlink()
                or not stderr.is_file()
            ):
                raise CalibrationReceiptError("calibration retry evidence differs")
            _capacity_retry_identity(retry / "host-stdout.jsonl", ordinal)
        attempts += attempt_count
    return attempts


def _projection(
    labels: list[Any],
    ratings: list[Any],
    requests: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    label_map = {
        (row.get("example_id"), row.get("check_id")): row
        for row in labels if isinstance(row, dict)
    }
    rating_map = {
        (row.get("example_id"), row.get("check_id")): row
        for row in ratings if isinstance(row, dict)
    }
    keys = {(row["entry_id"], row["check_id"]) for row in requests}
    if (
        len(keys) != len(requests)
        or len(label_map) != len(labels)
        or len(rating_map) != len(ratings)
        or set(label_map) != keys
        or set(rating_map) != keys
    ):
        raise ContractError("calibration receipt labels or ratings differ")
    thresholds = ratings[0].get("thresholds")
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != {"minimum_agreement", "minimum_examples"}
        or isinstance(thresholds.get("minimum_agreement"), bool)
        or not isinstance(thresholds.get("minimum_agreement"), (int, float))
        or not 0 <= thresholds["minimum_agreement"] <= 1
        or isinstance(thresholds.get("minimum_examples"), bool)
        or not isinstance(thresholds.get("minimum_examples"), int)
        or thresholds["minimum_examples"] < 1
        or any(row.get("thresholds") != thresholds for row in ratings)
    ):
        raise ContractError("calibration receipt thresholds differ")
    request_map = {
        (row["entry_id"], row["check_id"]): row for row in requests
    }
    for key in keys:
        label = label_map[key]
        rating = rating_map[key]
        request = request_map[key]
        if (
            rating.get("position") != request["entry_ordinal"] + 1
            or label.get("gold_label") not in {"pass", "fail", "abstain"}
            or rating.get("label") not in {"pass", "fail", "abstain"}
        ):
            raise ContractError("calibration receipt row identity differs")
    metrics = []
    for check_id in sorted({row["check_id"] for row in requests}):
        selected = [row for row in requests if row["check_id"] == check_id]
        matches = sum(
            rating_map[(row["entry_id"], check_id)]["label"]
            == label_map[(row["entry_id"], check_id)]["gold_label"]
            for row in selected
        )
        metrics.append({
            "check_id": check_id,
            "sample_count": len(selected),
            "agreement": matches / len(selected),
        })
    failed = [
        row["check_id"] for row in metrics
        if row["sample_count"] < thresholds["minimum_examples"]
        or row["agreement"] < thresholds["minimum_agreement"]
    ]
    if not failed:
        raise ContractError("calibration receipt does not contain a threshold failure")
    return dict(thresholds), metrics, failed


def validate_calibration_rejection_receipt(
    binding: dict[str, Any],
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
) -> int:
    receipt = load_json(
        resolve_binding(binding, repository_root, campaign_root),
        label="calibration rejection receipt",
    )
    validate_document(receipt, "calibration_rejection_receipt")
    qualification = load_json(
        resolve_binding(receipt["qualification"], repository_root, campaign_root),
        label="calibration rejection qualification",
    )
    preparation = load_json(
        resolve_binding(receipt["preparation"], repository_root, campaign_root),
        label="calibration rejection preparation",
    )
    validate_qualification(qualification)
    _verify_preparation_lineage(campaign, preparation)
    if (
        receipt["campaign_id"] != campaign["campaign_id"]
        or receipt["state_revision"] != campaign["state_revision"]
        or qualification.get("campaign_id") != campaign["campaign_id"]
        or qualification.get("terminal_state_revision") != campaign["state_revision"]
        or qualification.get("decision") != "blocked"
    ):
        raise ContractError("calibration rejection receipt differs from its campaign")
    commands = [
        row for row in preparation.get("commands", [])
        if row.get("skill_id") == receipt["skill_id"]
    ]
    requests = receipt["requests"]
    if (
        len(commands) != 1
        or commands[0].get("request_count") != receipt["request_count"]
        or receipt["request_count"] != len(requests)
        or sorted(row["entry_ordinal"] for row in requests)
        != list(range(len(requests)))
        or len({row["request_id"] for row in requests}) != len(requests)
    ):
        raise ContractError("calibration rejection receipt request set differs")
    for row in requests:
        identity = _completed_identity(
            resolve_binding(row["host_result"], repository_root, campaign_root),
            resolve_binding(row["terminal"], repository_root, campaign_root),
            row["entry_ordinal"],
        )
        if any(identity[field] != row[field] for field in identity):
            raise ContractError("calibration rejection receipt differs from Host evidence")
    thresholds, metrics, failed = _projection(
        load_jsonl(
            resolve_binding(receipt["labels"], repository_root, campaign_root),
            label="calibration labels",
        ),
        load_jsonl(
            resolve_binding(receipt["ratings"], repository_root, campaign_root),
            label="calibration ratings",
        ),
        requests,
    )
    if (
        receipt["thresholds"] != thresholds
        or receipt["check_metrics"] != metrics
        or receipt["failed_checks"] != failed
    ):
        raise ContractError("calibration rejection receipt projection differs")
    return len(requests)


def close_calibration_rejection(
    *,
    repository_root: Path,
    campaign_root: Path,
    campaign: dict[str, Any],
    skill_id: str,
    output: Path,
) -> dict[str, Any]:
    if skill_id not in SKILL_IDS:
        raise CalibrationReceiptError("rejection receipt Skill is unknown")
    expected_output = campaign_root / f"calibration/rejection-{skill_id}.json"
    if output != expected_output:
        raise CalibrationReceiptError("rejection receipt output path is not canonical")
    qualification_path = campaign_root / "qualification/qualification.json"
    preparation_path = campaign_root / "calibration/preparation.json"
    qualification = load_json(qualification_path, label="qualification")
    preparation = load_json(preparation_path, label="calibration preparation")
    _verify_preparation_lineage(campaign, preparation)
    if (
        qualification.get("decision") != "blocked"
        or qualification.get("campaign_id") != campaign["campaign_id"]
        or qualification.get("terminal_state_revision") != campaign["state_revision"]
    ):
        raise CalibrationReceiptError("campaign calibration identity differs")
    if campaign["skill_evidence"][skill_id]["grader_calibration"] is not None:
        raise CalibrationReceiptError("rejected calibration is already recorded")
    commands = [
        row for row in preparation.get("commands", [])
        if row.get("skill_id") == skill_id
    ]
    if (
        len(commands) != 1
        or not isinstance(commands[0].get("request_count"), int)
        or not 1 <= commands[0]["request_count"] <= 64
    ):
        raise CalibrationReceiptError("calibration preparation command is ambiguous")
    request_count = commands[0]["request_count"]
    skill_root = campaign_root / "calibration" / skill_id
    terminal_root = skill_root / "run/terminals"
    expected_names = {f"{index:03d}" for index in range(1, request_count + 1)}
    children = (
        list(terminal_root.iterdir())
        if not terminal_root.is_symlink() and terminal_root.is_dir()
        else []
    )
    if (
        terminal_root.is_symlink()
        or not terminal_root.is_dir()
        or {path.name for path in children} != expected_names
        or any(path.is_symlink() or not path.is_dir() for path in children)
    ):
        raise CalibrationReceiptError("calibration terminal set is incomplete")
    requests = []
    for ordinal in range(request_count):
        root = terminal_root / f"{ordinal + 1:03d}"
        host_result = root / "host-stdout.jsonl"
        terminal = root / "terminal.json"
        identity = _completed_identity(host_result, terminal, ordinal)
        requests.append({
            **identity,
            "host_result": make_binding(
                host_result,
                root="external",
                repository_root=repository_root,
                campaign_root=campaign_root,
            ),
            "terminal": make_binding(
                terminal,
                root="external",
                repository_root=repository_root,
                campaign_root=campaign_root,
            ),
        })
    labels_path = skill_root / "calibration-gold.jsonl"
    ratings_path = skill_root / "run/calibration-ratings.jsonl"
    thresholds, metrics, failed = _projection(
        load_jsonl(labels_path, label="calibration labels"),
        load_jsonl(ratings_path, label="calibration ratings"),
        requests,
    )
    receipt = {
        "schema_version": "model-evolution-calibration-rejection-receipt/2",
        "campaign_id": campaign["campaign_id"],
        "state_revision": campaign["state_revision"],
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
        "classification": "completed_turns_rejected_by_calibration_threshold",
        "labels": make_binding(
            labels_path,
            root="external",
            repository_root=repository_root,
            campaign_root=campaign_root,
        ),
        "ratings": make_binding(
            ratings_path,
            root="external",
            repository_root=repository_root,
            campaign_root=campaign_root,
        ),
        "request_count": request_count,
        "thresholds": thresholds,
        "check_metrics": metrics,
        "failed_checks": failed,
        "requests": requests,
    }
    validate_document(receipt, "calibration_rejection_receipt")
    payload = canonical_bytes(receipt) + b"\n"
    _write_exact(output, payload)
    return load_json(output, label="calibration rejection receipt")
